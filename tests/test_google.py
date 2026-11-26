"""Sign in with Google — the OAuth leg, fully mocked: no network, no
real clients. The routes, the provisioning, and the token shape are
all real code; only the token exchange and Google's answer are faked.
"""
import pytest
from fastapi.testclient import TestClient

from app import accounts, main


@pytest.fixture(autouse=True)
def _google_credentials(monkeypatch):
    monkeypatch.setenv(accounts.GOOGLE_CLIENT_ID_ENV, "cid-123456789")
    monkeypatch.setenv(accounts.GOOGLE_CLIENT_SECRET_ENV, "secret-abc")
    yield
    import os
    for key in (accounts.GOOGLE_CLIENT_ID_ENV, accounts.GOOGLE_CLIENT_SECRET_ENV):
        os.environ.pop(key, None)


FAKE_CLAIMS = {
    "sub": "1234567890",
    "aud": "cid-123456789",
    "iss": "accounts.google.com",
    "exp": 9999999999,
    "email": "Some.Person@gmail.com",
}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(
        accounts, "google_exchange_code", lambda code, redirect: {"id_token": "fake"})
    monkeypatch.setattr(
        accounts, "google_verify_id_token", lambda token, cid: dict(FAKE_CLAIMS))
    return TestClient(main.app)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def test_config_reports_enabled(client):
    r = client.get("/api/auth/config")
    assert r.json() == {"google": True}


def test_start_redirects_to_google_with_state_and_cookie(client):
    r = client.get("/api/auth/google", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=cid-123456789" in loc
    assert "response_type=code" in loc
    assert "state=" in loc
    assert "redirect_uri=" in loc
    assert accounts.COOKIE_GOOGLE_STATE in r.cookies


def test_unconfigured_instance_refuses_the_leg(monkeypatch):
    import os
    monkeypatch.delenv(accounts.GOOGLE_CLIENT_ID_ENV, raising=False)
    monkeypatch.delenv(accounts.GOOGLE_CLIENT_SECRET_ENV, raising=False)
    c = TestClient(main.app)
    r = c.get("/api/auth/config")
    assert r.json() == {"google": False}
    r = c.get("/api/auth/google", follow_redirects=False)
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# the callback
# ---------------------------------------------------------------------------

def test_callback_rejects_a_missing_state_cookie(client):
    # no state cookie set at all — not a real flow
    r = client.get("/api/auth/google/callback?code=x&state=y",
                   follow_redirects=False)
    assert r.status_code == 400


def test_callback_rejects_a_mismatched_state(client):
    client.cookies.set(accounts.COOKIE_GOOGLE_STATE, "wrong-state")
    r = client.get(f"/api/auth/google/callback?code=x&state=right-state",
                   follow_redirects=False)
    assert r.status_code == 400


def test_callback_signs_in_and_redirects_home(client):
    client.cookies.set(accounts.COOKIE_GOOGLE_STATE, "the-state")
    r = client.get("/api/auth/google/callback?code=x&state=the-state",
                   follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/#settings"
    assert accounts.COOKIE_NAME in r.cookies
    assert accounts.COOKIE_GOOGLE_STATE not in r.cookies


def test_callback_provisions_a_stable_account(client):
    client.cookies.set(accounts.COOKIE_GOOGLE_STATE, "the-state")
    r1 = client.get("/api/auth/google/callback?code=x&state=the-state",
                    follow_redirects=False)
    token = accounts.read_token(r1.cookies[accounts.COOKIE_NAME])
    assert token is not None
    store = accounts._read_store()
    u = next(u for u, rec in store["users"].items() if rec.get("sub") == "1234567890")
    assert u


# ---------------------------------------------------------------------------
# provisioning (module-level, no routes)
# ---------------------------------------------------------------------------

def test_google_provision_new_user_provisions_a_google_record():
    u = accounts.google_provision_user("sub-1", "some.person@gmail.com")
    store = accounts._read_store()
    assert store["users"][u]["method"] == "google"
    assert store["users"][u]["sub"] == "sub-1"
    assert store["users"][u]["hash"] == ""


def test_google_provision_new_user_makes_a_valid_username():
    u = accounts.google_provision_user("sub-2", "Real-Name.Live@icloud.com")
    assert accounts._USER_RE.match(u)


def test_google_provision_matches_by_sub_regardless_of_email():
    u1 = accounts.google_provision_user("sub-3", "old@gmail.com")
    u2 = accounts.google_provision_user("sub-3", "new@gmail.com")
    assert u1 == u2


def test_google_provision_does_not_clobber_an_existing_password_account():
    accounts.signup("alice", "longenoughpassword")
    u = accounts.google_provision_user("sub-4", "Alice@gmail.com")
    assert u != "alice"                                  # fresh identity
    u2 = accounts.login("alice", "longenoughpassword")    # still works
    assert u2 == "alice"


def test_google_account_has_no_password_login():
    u = accounts.google_provision_user("sub-5", "nobody@gmail.com")
    with pytest.raises(accounts.AccountError):
        accounts.login(u, "anything")


# ---------------------------------------------------------------------------
# token verification
# ---------------------------------------------------------------------------

def test_verify_id_token_checks_aud_and_iss_and_expiry(monkeypatch):
    import httpx
    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"aud": "my-client", "iss": "accounts.google.com",
                                "exp": 9999999999, "sub": "1"}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp())
    claims = accounts.google_verify_id_token("token", "my-client")
    assert claims["sub"] == "1"


def test_verify_id_token_rejects_wrong_audience(monkeypatch):
    import httpx
    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"aud": "other-client", "iss": "accounts.google.com",
                                "exp": 9999999999, "sub": "1"}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp())
    with pytest.raises(ValueError):
        accounts.google_verify_id_token("token", "my-client")


def test_verify_id_token_rejects_expired(monkeypatch):
    import httpx
    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"aud": "my-client", "iss": "accounts.google.com",
                                "exp": 1, "sub": "1"}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp())
    with pytest.raises(ValueError):
        accounts.google_verify_id_token("token", "my-client")
