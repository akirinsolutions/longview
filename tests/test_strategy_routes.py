"""The strategy-lab routes, tested fully offline.

The RAM rule applies: a fake ``market_data.fetch_history`` plays the
market, a fake ``risk._post_llm`` plays the model (patched, never the
resident :8000 server), and the Researcher is never constructed because
none of these plans research. Everything else is the real glue: the
request model, the plan gate, the job, the worker thread, the poll.
"""
import json
import time
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main, market_data, risk


@pytest.fixture()
def client():
    return TestClient(main.app)


def _days(start="2023-01-02", n=80) -> list[str]:
    out, d = [], date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


DATES = _days()


def _fake_fetch(symbol: str, years: float = 10, **_kw) -> dict[str, float]:
    if symbol == "NOPE":
        raise RuntimeError("No market data for NOPE — check the ticker")
    base = 100.0 if symbol == "SPY" else 50.0
    return {d: round(base * (1 + 0.002 * i), 2)
            for i, d in enumerate(DATES)}


def _body(**kw) -> dict:
    b = {"mode": "my_plan", "symbols": ["SPY", "TSLA"], "start_cash": 100_000,
         "frequency": "month", "triggers": [], "targets": {},
         "on_drop": "add", "add_weight": 0.1, "exit_pct": None,
         "research": False, "text": "", "names": {},
         "start": "2023-01-02", "end": "2023-03-31", "years": 10}
    b.update(kw)
    return b


def test_my_plan_runs_synchronously(client, monkeypatch):
    monkeypatch.setattr(market_data, "fetch_history", _fake_fetch)
    r = client.post("/api/backtest/strategy", json=_body())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mode"] == "my_plan"
    assert d["plan_source"] == "form"
    assert 30 <= len(d["dates"]) <= 80
    assert len(d["equity"]) == len(d["dates"]) == len(d["benchmark"])
    assert d["metrics"]["total_return"] is not None
    assert d["decisions"] >= 2          # day 0 + at least one month boundary
    assert len(d["log"]) == d["decisions"]
    assert all(e["date"] in d["dates"] for e in d["log"])
    # the deterministic decider deployed the plan on day 0
    assert d["time_in_market"] > 0


def test_my_plan_unknown_ticker_is_a_plain_400(client, monkeypatch):
    monkeypatch.setattr(market_data, "fetch_history", _fake_fetch)
    r = client.post("/api/backtest/strategy",
                    json=_body(symbols=["NOPE"]))
    assert r.status_code == 400
    assert "No market data for NOPE" in r.json()["detail"]


def test_my_plan_without_symbols_is_a_400(client):
    r = client.post("/api/backtest/strategy", json=_body(symbols=[]))
    assert r.status_code == 400


def test_ai_mode_without_a_key_is_a_503(client, monkeypatch):
    monkeypatch.delenv("PROOF_LLM_KEY", raising=False)
    r = client.post("/api/backtest/strategy",
                    json=_body(mode="ai", text="buy the dip"))
    assert r.status_code == 503
    assert "Settings" in r.json()["detail"]


def test_ai_mode_without_words_is_a_400(client, monkeypatch):
    monkeypatch.setenv("PROOF_LLM_KEY", "test")
    r = client.post("/api/backtest/strategy", json=_body(mode="ai", text=""))
    assert r.status_code == 400


def test_ai_job_runs_end_to_end(client, monkeypatch):
    monkeypatch.setenv("PROOF_LLM_KEY", "test")
    monkeypatch.setattr(market_data, "fetch_history", _fake_fetch)
    calls = {"decider": 0}

    def fake_post(system: str, user: str, max_tokens: int = 4000,
                  timeout: float = 60.0, config: dict | None = None):
        if "The user's strategy, in their own words" in user:
            # the one interpret call: read the words into a plan
            return (json.dumps(
                {"symbols": ["SPY", "TSLA"], "frequency": "month",
                 "on_drop": "add", "add_weight": 0.1,
                 "triggers": [{"kind": "drop_from_peak", "pct": 15,
                               "lookback_days": 252, "rearm": "recover"}],
                 "exit_pct": None, "research": False}), "fake")
        calls["decider"] += 1
        return ('{"trades": [], "note": "no change needed today"}', "fake")

    monkeypatch.setattr(risk, "_post_llm", fake_post)

    r = client.post("/api/backtest/strategy", json=_body(
        mode="ai",
        text="I own SPY and TSLA. Every month I check, and when one drops "
             "15% from its high I add 10% more."))
    assert r.status_code == 200, r.text
    job = r.json()
    # The fakes are instant: the job may already be done before the
    # POST returns. Either state is fine; the poll handles both.
    assert job["status"] in ("running", "done")

    deadline = time.time() + 20
    view = job
    while view["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
        view = client.get("/api/backtest/strategy/" + job["id"]).json()
    assert view["status"] == "done", view
    d = view["result"]
    assert d["mode"] == "ai"
    assert d["plan_source"] == "model"
    assert calls["decider"] >= 1        # the model decided on real days
    assert d["decisions"] >= 2
    assert len(d["log"]) == d["decisions"]
    assert all(e["note"] for e in d["log"])
    assert d["trades"] == 0             # the fake never traded


def test_model_outage_never_fails_the_job(client, monkeypatch):
    """No key set at the seam level: the worker must still finish, on
    the deterministic reader's plan and quiet no-trade days."""
    monkeypatch.setenv("PROOF_LLM_KEY", "test")
    monkeypatch.setattr(market_data, "fetch_history", _fake_fetch)

    def down(system: str, user: str, max_tokens: int = 4000,
             timeout: float = 60.0):
        raise RuntimeError("the model is down")

    monkeypatch.setattr(risk, "_post_llm", down)

    r = client.post("/api/backtest/strategy", json=_body(
        mode="ai", text="I own SPY and TSLA and I check every month."))
    assert r.status_code == 200, r.text
    job = r.json()

    deadline = time.time() + 20
    view = job
    while view["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
        view = client.get("/api/backtest/strategy/" + job["id"]).json()
    assert view["status"] == "done", view
    assert view["result"]["plan_source"] == "words"
    assert view["result"]["trades"] == 0
    assert any("unavailable" in (e["note"] or "") for e in view["result"]["log"])


def test_unknown_job_is_a_404(client):
    r = client.get("/api/backtest/strategy/doesnotexist")
    assert r.status_code == 404
    assert "expired" in r.json()["detail"]
