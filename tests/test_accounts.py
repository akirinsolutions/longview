"""Accounts and sessions — sign in once, keep your own data.

The autouse conftest fixture points the accounts store, the machine
secret and the per-user vault files at the test's scratch directory,
so none of this can touch the real ``data/`` folder.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import accounts, main, vault


# ---------------------------------------------------------------------------
# sign-up
# ---------------------------------------------------------------------------

def test_signup_creates_an_account_and_lowercases():
    u = accounts.signup("Kirin", "hunter2-hunter2")
    assert u == "kirin"
    store = accounts._read_store()
    assert "kirin" in store["users"]
    assert store["users"]["kirin"]["hash"] != "hunter2-hunter2"


def test_signup_rejects_a_bad_username_in_plain_english():
    for bad in ("x", "no spaces", "bad!chars", "" * 100):
        with pytest.raises(accounts.AccountError):
            accounts.signup(bad, "longenoughpassword")


def test_signup_rejects_a_short_password_in_plain_english():
    with pytest.raises(accounts.AccountError, match="8 characters"):
        accounts.signup("goodname", "short")


def test_signup_refuses_a_taken_username():
    accounts.signup("taken", "longenoughpassword")
    with pytest.raises(accounts.AccountError, match="taken"):
        accounts.signup("taKen", "anotherlongpassword")


# ---------------------------------------------------------------------------
# sign-in
# ---------------------------------------------------------------------------

def test_login_verifies_the_pair():
    accounts.signup("alice", "correct horse battery")
    assert accounts.login("Alice", "correct horse battery") == "alice"


def test_login_rejects_the_wrong_password_with_one_message():
    accounts.signup("alice", "correct horse battery")
    with pytest.raises(accounts.AccountError) as exc:
        accounts.login("alice", "wrong horse battery")
    assert "Wrong username or password" in str(exc.value)


def test_login_rejects_an_unknown_username_the_same_way():
    with pytest.raises(accounts.AccountError) as exc:
        accounts.login("nobody", "wrong horse battery")
    assert "Wrong username or password" in str(exc.value)


def test_login_throttles_after_five_failures():
    accounts.signup("alice", "correct horse battery")
    for _ in range(accounts.SIGN_IN_MAX_FAILS):
        with pytest.raises(accounts.AccountError):
            accounts.login("alice", "wrong horse battery")
    with pytest.raises(accounts.AccountError, match="Too many tries"):
        accounts.login("alice", "correct horse battery")


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------

def test_token_round_trips_through_issue_and_read():
    accounts.signup("alice", "correct horse battery")
    token = accounts.issue("alice")
    assert accounts.read_token(token) == "alice"


def test_token_refuses_tampering():
    accounts.signup("alice", "correct horse battery")
    _, expiry, _ = accounts.issue("alice").rsplit(".", 2)
    token = accounts.issue("alice")
    for bad in (
        token.replace("alice", "bob"),
        token + "x",
        token.rsplit(".", 1)[0] + ".deadbeef",
    ):
        assert accounts.read_token(bad) is None


def test_expired_token_is_refused(monkeypatch):
    accounts.signup("alice", "correct horse battery")
    token = accounts.issue("alice")
    # Travel past the expiry: a token minted in the past is refused.
    future = time.time() + accounts.SESSION_SECONDS + 10
    monkeypatch.setattr(time, "time", lambda: future)
    assert accounts.read_token(token) is None


def test_token_dies_with_the_account():
    accounts.signup("alice", "correct horse battery")
    token = accounts.issue("alice")
    store = accounts._read_store()
    store["users"].pop("alice")
    accounts._write_store(store)
    assert accounts.read_token(token) is None


# ---------------------------------------------------------------------------
# the routes
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    return TestClient(main.app)


def test_signup_route_sets_the_cookie(client):
    r = client.post("/api/auth/signup",
                    json={"username": "alice", "password": "correct horse battery"})
    assert r.status_code == 201, r.text
    assert r.json()["username"] == "alice"
    assert accounts.COOKIE_NAME in r.cookies
    r = client.get("/api/auth/me")
    assert r.json() == {"authenticated": True, "username": "alice"}


def test_login_route_sets_the_cookie(client):
    client.post("/api/auth/signup",
                json={"username": "alice", "password": "correct horse battery"})
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login",
                    json={"username": "alice", "password": "correct horse battery"})
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_bad_login_is_a_401_and_says_nothing(client):
    client.post("/api/auth/signup",
                json={"username": "alice", "password": "correct horse battery"})
    r = client.post("/api/auth/login",
                    json={"username": "alice", "password": "wrong horse battery"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Wrong username or password."


def test_logout_expires_the_cookie(client):
    client.post("/api/auth/signup",
                json={"username": "alice", "password": "correct horse battery"})
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    r = client.get("/api/auth/me")
    assert r.json()["authenticated"] is False


def test_signup_route_rejects_bad_input_in_plain_english(client):
    r = client.post("/api/auth/signup",
                    json={"username": "x", "password": "correct horse battery"})
    assert r.status_code == 400
    assert "username" in r.json()["detail"].lower()


def test_login_route_throttles_with_429(client):
    client.post("/api/auth/signup",
                json={"username": "alice", "password": "correct horse battery"})
    for _ in range(accounts.SIGN_IN_MAX_FAILS):
        client.post("/api/auth/login",
                    json={"username": "alice", "password": "wrong horse battery"})
    r = client.post("/api/auth/login",
                    json={"username": "alice", "password": "correct horse battery"})
    assert r.status_code == 429


def test_me_is_anonymous_by_default(client):
    r = client.get("/api/auth/me")
    assert r.json() == {"authenticated": False, "username": None}


# ---------------------------------------------------------------------------
# per-person storage
# ---------------------------------------------------------------------------

def test_a_signed_in_user_gets_a_file_of_their_own():
    token = accounts.set_user("alice")
    try:
        vault.write_section("portfolio",
                            {"v": 1, "updated": 1,
                             "positions": [{"ticker": "AAPL"}]})
    finally:
        accounts.reset_user(token)

    # The same section for someone else is a different file, not a mix.
    token = accounts.set_user("bob")
    try:
        vault.write_section("portfolio",
                            {"v": 1, "updated": 1,
                             "positions": [{"ticker": "MSFT"}]})
    finally:
        accounts.reset_user(token)

    token = accounts.set_user("alice")
    try:
        assert vault.read_section("portfolio")["positions"] == [{"ticker": "AAPL"}]
    finally:
        accounts.reset_user(token)
    token = accounts.set_user("bob")
    try:
        assert vault.read_section("portfolio")["positions"] == [{"ticker": "MSFT"}]
    finally:
        accounts.reset_user(token)


def test_anonymous_use_keeps_the_shared_file():
    # No user set: the shared file is the vault, exactly as before.
    vault.write_section("portfolio",
                        {"v": 1, "updated": 1,
                         "positions": [{"ticker": "AAPL"}]})
    assert vault.current_path() == vault.VAULT_PATH


def test_signed_in_user_is_isolated_in_the_route(client):
    client.post("/api/auth/signup",
                json={"username": "alice", "password": "correct horse battery"})
    r = client.post("/api/portfolio",
                    json={"ticker": "AAPL", "shares": 2, "cost_basis": 100})
    assert r.status_code in (200, 201), r.text
    r = client.get("/api/vault")
    assert r.json()["sections"]["portfolio"]["positions"][0]["ticker"] == "AAPL"


def test_signout_and_signin_as_someone_else_switches_files(client):
    client.post("/api/auth/signup",
                json={"username": "alice", "password": "correct horse battery"})
    client.post("/api/portfolio",
                json={"ticker": "AAPL", "shares": 2, "cost_basis": 100})
    client.post("/api/auth/logout")
    client.post("/api/auth/signup",
                json={"username": "bob", "password": "correct horse battery"})
    r = client.get("/api/vault")
    assert r.json()["sections"]["portfolio"] is None


def test_the_text_export_is_plainly_a_save_file(client):
    r = client.get("/api/vault/text")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "PORTFOLIO" in body
    assert "RISK — SCENARIO MOVES" in body
    assert "NOTES" in body
    assert "FOLLOWED FUNDS" in body
    assert "RESEARCH REPORTS" in body
    assert "ECONOMY TREE" in body
