"""The cloud backup — a second, permanent copy of each person's file.

The backup is best-effort and never fails the save: a missing token
answers quietly, a network hiccup never raises, a cooldown stops noisy
sessions from hammering the API. The routes are exercised with the
GitHub round trip mocked out.
"""
import httpx
import pytest

from app import backup, vault


@pytest.fixture(autouse=True)
def _repo_env(monkeypatch):
    monkeypatch.setenv(backup.REPO_ENV, "owner/repo")
    monkeypatch.setenv(backup.TOKEN_ENV, "tok")
    backup._last_backup.clear()
    yield


def _fake_httpx(monkeypatch, get_status=404, put_status=201):
    class FakeResp:
        def __init__(self, status, body=None):
            self.status_code = status
            self._body = body or {}
        def json(self):
            return self._body

    monkeypatch.setattr(httpx, "get",
                        lambda url, headers=None, timeout=20: FakeResp(get_status, {"sha": "abc"} if get_status == 200 else {}))
    monkeypatch.setattr(httpx, "put",
                        lambda url, headers=None, json=None, timeout=20: FakeResp(put_status))


# ---------------------------------------------------------------------------
# the module
# ---------------------------------------------------------------------------

def test_unconfigured_reports_not_ready(monkeypatch):
    monkeypatch.delenv(backup.TOKEN_ENV, raising=False)
    out = backup.backup_vault("alice", {"v": 1, "updated": 1, "sections": {}})
    assert out["ok"] is False
    assert "not configured" in out["detail"]


def test_malformed_repo_reports_not_ready(monkeypatch):
    monkeypatch.setenv(backup.REPO_ENV, "not-a-repo")
    out = backup.backup_vault("alice", {"v": 1, "updated": 1, "sections": {}})
    assert out["ok"] is False
    assert "not set up" in out["detail"]


def test_backup_pushes_the_file(monkeypatch):
    _fake_httpx(monkeypatch, get_status=404, put_status=201)
    out = backup.backup_vault("alice", {"v": 1, "updated": 1, "sections": {"portfolio": {"v": 1, "positions": []}}})
    assert out["ok"] is True
    assert "backed up" in out["detail"]


def test_existing_file_re_pushes_with_sha(monkeypatch):
    sent = {}
    class FakeResp:
        status_code = 200
        def json(self):
            return {"sha": "old-sha"}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResp())
    def fake_put(url, headers=None, json=None, timeout=20):
        sent.update(json or {})
        return type("R", (), {"status_code": 200})()
    monkeypatch.setattr(httpx, "put", fake_put)
    out = backup.backup_vault("alice", {"v": 1, "updated": 1, "sections": {}})
    assert out["ok"] is True
    assert sent.get("sha") == "old-sha"


def test_cooldown_holds_off_repeat_backups(monkeypatch):
    _fake_httpx(monkeypatch)
    first = backup.backup_vault("alice", {"v": 1, "updated": 1, "sections": {}})
    second = backup.backup_vault("alice", {"v": 1, "updated": 1, "sections": {}})
    assert first["ok"] and second["ok"]
    assert "already backed up" in second["detail"]


def test_force_bypasses_the_cooldown(monkeypatch):
    _fake_httpx(monkeypatch)
    first = backup.backup_vault("alice", {"v": 1, "updated": 1, "sections": {}})
    second = backup.backup_vault("alice", {"v": 1, "updated": 1, "sections": {}}, force=True)
    assert second["ok"] is True
    assert "already backed up" not in second["detail"]


def test_worst_case_never_raises(monkeypatch):
    monkeypatch.setattr(httpx, "get",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    out = backup.backup_vault("alice", {"v": 1, "updated": 1, "sections": {}}, force=True)
    assert out["ok"] is False


# ---------------------------------------------------------------------------
# vault write fires the backup (fire-and-forget)
# ---------------------------------------------------------------------------

def test_a_write_fires_a_background_backup(monkeypatch):
    """vault.write_section fires a fire-and-forget cloud copy."""
    import threading
    spy_done = threading.Event()
    spy_user = []

    def spy(user, data, force=False):
        spy_user.append(user)
        spy_done.set()
        return {"ok": True, "detail": ""}

    monkeypatch.setattr(backup, "backup_vault", spy)
    monkeypatch.setattr(backup, "configured", lambda: True)

    from app import accounts
    token = accounts.set_user("alice")
    try:
        vault.write_section("risk", {"v": 1, "updated": 1, "moves": {"AAPL": 1.0}})
    finally:
        accounts.reset_user(token)

    assert spy_done.wait(timeout=3), "the background backup never ran"
    assert spy_user == ["alice"]


# ---------------------------------------------------------------------------
# the route
# ---------------------------------------------------------------------------

def test_the_route_requires_a_signin(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(backup, "backup_vault", lambda *a, **kw: {"ok": True, "detail": ""})
    c = TestClient(main.app)
    r = c.post("/api/vault/backup")
    assert r.status_code == 400


def test_the_route_answers_ok(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(backup, "backup_vault", lambda *a, **kw: {"ok": True, "detail": "backed up to the cloud copy"})
    c = TestClient(main.app)
    c.post("/api/auth/signup", json={"username": "alice", "password": "correct horse battery"})
    r = c.post("/api/vault/backup")
    assert r.status_code == 200
    assert r.json()["ok"] is True
