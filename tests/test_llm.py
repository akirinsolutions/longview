"""The LLM seam: one config, three layers, no key ever stored.

Layers, in resolution order: an explicit config dict (background jobs
capture it at request time), the per-request ``X-Longview-LLM`` header
(a context variable), and the environment (``LONGVIEW_LLM_*`` with the
legacy ``PROOF_LLM_*`` fallbacks). All faked; the RAM rule — no test
touches a real model.
"""
import base64
import json

import httpx
import pytest

from app import llm
from app.main import app


def _client():
    from fastapi.testclient import TestClient
    return TestClient(app)


def _b64(cfg: dict) -> str:
    return base64.b64encode(json.dumps(cfg).encode()).decode()


# ---------------------------------------------------------------------------
# parse_header: base64 JSON, tolerant of junk, strict about types
# ---------------------------------------------------------------------------

def test_parse_header_reads_a_full_config():
    out = llm.parse_header(_b64(
        {"base": "http://127.0.0.1:1234/v1/", "key": " sk ",
         "model": "some-model"}))
    assert out == {"base": "http://127.0.0.1:1234/v1/", "key": "sk",
                   "model": "some-model"}


def test_parse_header_partial_config_keeps_only_given_fields():
    out = llm.parse_header(_b64({"key": "sk"}))
    assert out == {"key": "sk"}


@pytest.mark.parametrize("raw", [
    None,
    "",
    "not-base64!!",
    base64.b64encode(b"just text").decode(),       # not a JSON object
    base64.b64encode(b"[1, 2]").decode(),          # an array, not an object
    base64.b64encode(json.dumps({"key": 7}).encode()).decode(),  # wrong type
    base64.b64encode(json.dumps({"key": "  "}).encode()).decode(),  # blank
])
def test_parse_header_rejects_junk_silently(raw):
    assert llm.parse_header(raw) is None


# ---------------------------------------------------------------------------
# resolve: explicit > request override > environment, per field
# ---------------------------------------------------------------------------

def _clean_env(monkeypatch):
    for var in ("LONGVIEW_LLM_KEY", "LONGVIEW_LLM_BASE", "LONGVIEW_LLM_MODEL",
                "PROOF_LLM_KEY", "PROOF_LLM_BASE", "PROOF_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_resolve_defaults_when_nothing_is_set(monkeypatch):
    _clean_env(monkeypatch)
    cfg = llm.resolve()
    assert cfg == {"base": "https://api.openai.com/v1", "key": "",
                   "model": "gpt-4o-mini"}
    assert not llm.is_configured()


def test_resolve_reads_longview_env(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("LONGVIEW_LLM_KEY", "env-key")
    cfg = llm.resolve()
    assert cfg["key"] == "env-key"
    assert llm.is_configured()


def test_resolve_keeps_legacy_proof_env_working(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("PROOF_LLM_KEY", "legacy-key")
    monkeypatch.setenv("PROOF_LLM_MODEL", "legacy-model")
    cfg = llm.resolve()
    assert cfg["key"] == "legacy-key"
    assert cfg["model"] == "legacy-model"


def test_resolve_longview_env_wins_over_legacy(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("LONGVIEW_LLM_MODEL", "new-model")
    monkeypatch.setenv("PROOF_LLM_MODEL", "legacy-model")
    assert llm.resolve()["model"] == "new-model"


def test_resolve_per_field_merge(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("LONGVIEW_LLM_KEY", "k")
    monkeypatch.setenv("PROOF_LLM_MODEL", "legacy-model")
    # the request supplies a model only: key from env, model from request
    llm.set_request_override({"model": "req-model"})
    try:
        cfg = llm.resolve()
        assert cfg["key"] == "k"
        assert cfg["model"] == "req-model"
    finally:
        llm.set_request_override(None)


def test_resolve_explicit_config_beats_request_override(monkeypatch):
    _clean_env(monkeypatch)
    llm.set_request_override({"key": "req", "model": "req-model"})
    try:
        cfg = llm.resolve({"key": "explicit", "model": "explicit-model"})
        assert cfg["key"] == "explicit"
        assert cfg["model"] == "explicit-model"
    finally:
        llm.set_request_override(None)


def test_resolve_strips_base_slash(monkeypatch):
    _clean_env(monkeypatch)
    cfg = llm.resolve({"base": "http://127.0.0.1:9/v1///",
                       "key": "k", "model": "m"})
    assert cfg["base"] == "http://127.0.0.1:9/v1"


# ---------------------------------------------------------------------------
# post_chat: the one httpx call behind every model feature
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def test_post_chat_no_key_raises_plain(monkeypatch):
    _clean_env(monkeypatch)
    llm.set_request_override(None)
    with pytest.raises(RuntimeError, match="no key"):
        llm.post_chat("s", "u")


def test_post_chat_posts_the_resolved_config(monkeypatch):
    _clean_env(monkeypatch)
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["auth"] = headers["Authorization"]
        seen["body"] = json
        return _Resp("  the answer  ")

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.set_request_override({"base": "http://m.test/v1", "key": "sk",
                              "model": "m1"})
    try:
        content, model = llm.post_chat("system", "user", None,
                                       max_tokens=123, timeout=5.5)
    finally:
        llm.set_request_override(None)
    assert content == "the answer"
    assert model == "m1"
    assert seen["url"] == "http://m.test/v1/chat/completions"
    assert seen["auth"] == "Bearer sk"
    assert seen["body"]["model"] == "m1"
    assert seen["body"]["max_tokens"] == 123
    assert seen["body"]["messages"][0]["role"] == "system"


def test_post_chat_timeout_is_plain_english(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("LONGVIEW_LLM_KEY", "k")
    monkeypatch.setattr(
        llm.httpx, "post",
        lambda *a, **k: (_ for _ in ()).throw(
            httpx.TimeoutException("slow")))
    with pytest.raises(RuntimeError, match="didn't answer within"):
        llm.post_chat("s", "u", timeout=9.0)


def test_post_chat_http_error_is_plain_english(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("LONGVIEW_LLM_KEY", "k")
    req = httpx.Request("POST", "http://m.test/v1/chat/completions")
    monkeypatch.setattr(
        llm.httpx, "post",
        lambda *a, **k: (_ for _ in ()).throw(
            httpx.ConnectError("refused", request=req)))
    with pytest.raises(RuntimeError, match="endpoint didn't answer"):
        llm.post_chat("s", "u")


# ---------------------------------------------------------------------------
# The routes: status and test, and the header the middleware installs
# ---------------------------------------------------------------------------

def test_llm_status_none(monkeypatch):
    _clean_env(monkeypatch)
    r = _client().get("/api/llm")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["source"] == "none"
    assert body["base"] == llm.DEFAULT_BASE
    assert body["model"] == llm.DEFAULT_MODEL


def test_llm_status_env(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("LONGVIEW_LLM_KEY", "k")
    monkeypatch.setenv("LONGVIEW_LLM_MODEL", "m")
    body = _client().get("/api/llm").json()
    assert body["configured"] is True
    assert body["source"] == "env"
    assert body["model"] == "m"


def test_llm_status_request_beats_env(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("LONGVIEW_LLM_KEY", "env-k")
    monkeypatch.setenv("LONGVIEW_LLM_MODEL", "env-m")
    body = _client().get(
        "/api/llm",
        headers={"X-Longview-LLM": _b64(
            {"key": "browser-k", "model": "browser-m"})}).json()
    assert body["source"] == "request"
    assert body["model"] == "browser-m"


def test_llm_status_bad_header_falls_to_env(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("LONGVIEW_LLM_KEY", "env-k")
    body = _client().get(
        "/api/llm", headers={"X-Longview-LLM": "garbage"}).json()
    assert body["source"] == "env"


def test_llm_test_no_key():
    body = _client().post(
        "/api/llm/test",
        json={"base": "http://m.test/v1", "key": "", "model": "m"}).json()
    assert body["ok"] is False
    assert "no key" in body["error"]


def test_llm_test_connected(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _Resp("ok")

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    body = _client().post(
        "/api/llm/test",
        json={"base": "http://m.test/v1", "key": "sk",
              "model": "the-model"}).json()
    assert body["ok"] is True
    assert body["model"] == "the-model"
    assert body["error"] is None


def test_llm_test_empty_answer_is_not_ok(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _Resp(""))
    body = _client().post(
        "/api/llm/test",
        json={"base": "http://m.test/v1", "key": "sk",
              "model": "the-model"}).json()
    assert body["ok"] is False
    assert "no text" in body["error"]


def test_risk_post_llm_reports_settings(monkeypatch):
    """The old "env var is not set" error is gone: the app has a
    Settings tab, and every no-model error points there."""
    _clean_env(monkeypatch)
    llm.set_request_override(None)
    from app import risk
    with pytest.raises(RuntimeError, match="Settings"):
        risk._post_llm("s", "u")


def test_risk_post_llm_passes_config_through(monkeypatch):
    """An explicit config is the layer the background threads use: it
    must win over both the request header and the environment."""
    from app import risk

    _clean_env(monkeypatch)
    monkeypatch.setenv("LONGVIEW_LLM_KEY", "env-k")
    llm.set_request_override({"key": "req-k", "model": "req-m"})
    try:
        seen = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            seen["auth"] = headers["Authorization"]
            return _Resp("x")

        monkeypatch.setattr(llm.httpx, "post", fake_post)
        content, model = risk._post_llm("s", "u",
                                        config={"key": "explicit-k",
                                                "model": "exp-m"})
        assert seen["auth"] == "Bearer explicit-k"
        assert model == "exp-m"
    finally:
        llm.set_request_override(None)
