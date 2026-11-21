"""Offline tests for the risk analysis.

The moves file and the portfolio file are pointed at temp dirs, and the
live sources — Yahoo quotes, price history, FX rates — are monkeypatched
fakes, so nothing here touches the network or the real data files.
"""
import json
import math

import pytest

from app import market_data, portfolio, risk, vault


@pytest.fixture(autouse=True)
def risk_path(tmp_path, monkeypatch):
    # autouse: a test that forgets to request it must still not read or
    # write the real data file. (One once wrote a test move into the
    # reader's real file, and the next suite run tripped over it on
    # re-read.) Moves and positions both live in the one vault file.
    p = tmp_path / "longview.json"
    monkeypatch.setattr(vault, "VAULT_PATH", p)
    return p


@pytest.fixture(autouse=True)
def portfolio_path(tmp_path, monkeypatch):
    # autouse: same reason — no test here may touch the real data file.
    # Both sections live in the one vault file, so both names resolve to
    # the same scratch path.
    p = tmp_path / "longview.json"
    monkeypatch.setattr(vault, "VAULT_PATH", p)
    return p


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    """Offline by default: no quotes, no history, no FX. Individual
    tests install the fakes they need (a test-body patch overrides)."""
    monkeypatch.setattr(
        market_data, "quote",
        lambda *a, **k: None)
    monkeypatch.setattr(
        market_data, "price_series",
        lambda *a, **k: None)
    monkeypatch.setattr(
        market_data, "fx_rate",
        lambda *a, **k: None)


def _hist(start=100.0, end=110.0, days=420):
    """A log-linear year of closes (the portfolio tests' shape)."""
    from datetime import date as _date, timedelta as _td
    today = _date(2026, 11, 15)
    out = {}
    for i in range(days, -1, -1):
        d = today - _td(days=i)
        f = (days - i) / days
        out[d.isoformat()] = round(start * (end / start) ** f, 6)
    return out


def _pos(ticker="AAPL", name="Apple Inc.", shares=10, cost=120.0, **extra):
    return {"ticker": ticker, "name": name, "shares": shares,
            "cost_basis": cost, **extra}


def _quote(sym, price=150.0, week=0.02, name=None, cur="USD"):
    return {"symbol": sym, "name": name or f"{sym} Co", "price": price,
            "week": week, "as_of": "2026-11-14", "exchange": "NMS",
            "currency": cur, "fetched": 1793000000}


def _row(ticker="AAPL", price=150.0, value=1500.0, **extra):
    """A risk-table row as the client would send it to /api/risk/fill."""
    return {"ticker": ticker, "name": f"{ticker} Co", "kind": "stock",
            "currency": "USD", "price": price, "value": value,
            "ret_1y": 0.12, "vol": 0.31, **extra}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_missing_file_means_no_moves(risk_path):
    assert risk.load_moves() == {}


def test_save_roundtrips(risk_path):
    out = risk.save_moves({"AAPL": 12.5, "MSFT": -8})
    assert out["moves"] == {"AAPL": 12.5, "MSFT": -8.0}
    assert risk.load_moves() == {"AAPL": 12.5, "MSFT": -8.0}


def test_save_clamps_out_of_range(risk_path):
    out = risk.save_moves({"A": 5500, "B": -200})
    assert out["moves"]["A"] == 999.0
    assert out["moves"]["B"] == -99.0


def test_save_drops_junk(risk_path):
    out = risk.save_moves({"A": "lots", "B": float("nan"),
                           "C" * 20: 5, "": 1, "D": None})
    assert out["moves"] == {}


def test_save_writes_envelope_atomically(risk_path, tmp_path):
    risk.save_moves({"A": 3})
    saved = json.loads(risk_path.read_text())["sections"]["risk"]
    assert saved["v"] == 1
    assert saved["moves"] == {"A": 3.0}
    assert saved["updated"] > 0
    assert not (risk_path.parent / (risk_path.name + ".tmp")).exists()


def test_corrupt_file_reads_as_empty(risk_path):
    risk_path.write_text("{ not json")
    assert risk.load_moves() == {}


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

def test_volatility_flat_series_is_zero():
    h = {f"2026-{m:02d}-{d:02d}": 100.0 for m in range(1, 10) for d in range(1, 15)}
    assert len(h) >= risk._MIN_BARS
    assert risk.volatility(h) == 0.0


def test_volatility_short_series_is_none():
    assert risk.volatility({"2026-11-10": 100.0, "2026-11-11": 110.0}) is None
    assert risk.volatility(None) is None


def test_volatility_alternating_series():
    # 100 -> 110 -> 100 ... : daily swings of ~9.1%, annualized ~1.5
    from datetime import date, timedelta
    today = date(2026, 11, 15)
    h = {}
    for i in range(260, -1, -1):
        h[(today - timedelta(days=i)).isoformat()] = 100.0 if i % 2 else 110.0
    v = risk.volatility(h)
    assert v is not None and 1.3 < v < 1.7


# ---------------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------------

def test_view_row_math(portfolio_path, risk_path, monkeypatch):
    portfolio.add_position(_pos(shares=10, cost=120.0))
    risk.save_moves({"AAPL": 10})
    monkeypatch.setattr(
        market_data, "quote",
        lambda sym, ttl, name_hint=None: _quote(sym, price=150.0))
    monkeypatch.setattr(
        market_data, "price_series",
        lambda sym, days=400: _hist())

    v = risk.view()
    p = v["positions"][0]
    assert p["move"] == 10.0
    assert p["value"] == 1500.0
    assert p["scenario_value"] == 1650.0
    assert p["scenario_delta"] == 150.0
    assert p["vol"] is not None
    assert p["ret_1y"] is not None
    assert v["totals"]["scenario"] == 1650.0
    assert v["totals"]["delta"] == 150.0
    assert v["n_live"] == 1


def test_view_without_saved_moves_is_zero_moves(portfolio_path, monkeypatch):
    portfolio.add_position(_pos(shares=10, cost=120.0))
    monkeypatch.setattr(
        market_data, "quote",
        lambda sym, ttl, name_hint=None: _quote(sym, price=150.0))
    v = risk.view()
    p = v["positions"][0]
    assert p["move"] == 0.0
    assert p["scenario_value"] == p["value"]
    assert v["totals"]["delta"] == 0.0


def test_view_null_quote_degrades_to_dashes(portfolio_path, monkeypatch):
    # _no_live's fake quote returns None
    portfolio.add_position(_pos(shares=10, cost=120.0))
    v = risk.view()
    p = v["positions"][0]
    assert p["live"] is False
    assert p["value"] is None and p["scenario_value"] is None
    assert v["totals"]["value"] is None
    assert v["totals"]["priced"] == 0 and v["totals"]["missing"] == 1


def test_view_mixed_currency_totals_are_dashes(portfolio_path, monkeypatch):
    portfolio.add_position(_pos("AAPL", "Apple Inc.", shares=10, cost=120.0))
    portfolio.add_position(_pos("JPF", "JP fund", shares=1000, cost=100.0,
                                kind="custom", price=110.0, currency="JPY"))
    monkeypatch.setattr(
        market_data, "quote",
        lambda sym, ttl, name_hint=None: _quote(
            sym, price=150.0 if sym == "AAPL" else 110.0,
            cur="USD" if sym == "AAPL" else "JPY"))
    v = risk.view()
    assert v["totals"]["value"] is None
    assert v["totals"]["scenario"] is None
    assert v["totals"]["vol"] is None
    assert v["totals"]["currencies"] == ["JPY", "USD"]


def test_view_display_currency_converts(portfolio_path, monkeypatch):
    portfolio.add_position(_pos("AAPL", "Apple Inc.", shares=10, cost=120.0))
    portfolio.add_position(_pos("JPF", "JP fund", shares=1000, cost=100.0,
                                kind="custom", price=110.0, currency="JPY"))
    risk.save_moves({"AAPL": 10})
    monkeypatch.setattr(
        market_data, "quote",
        lambda sym, ttl, name_hint=None: _quote(
            sym, price=150.0 if sym == "AAPL" else 110.0,
            cur="USD" if sym == "AAPL" else "JPY"))
    monkeypatch.setattr(
        market_data, "fx_rate",
        # same currency is 1.0 (the real fx_rate never asks Yahoo for it)
        lambda a, b: 1.0 if a == b
        else 0.0067 if (a, b) == ("JPY", "USD")
        else None)

    v = risk.view(currency="USD")
    aapl, jpf = v["positions"]
    assert aapl["display_value"] == 1500.0
    assert jpf["display_value"] == 737.0            # 110000 JPY
    assert aapl["display_scenario_value"] == 1650.0
    assert v["totals"]["value"] == 2237.0
    assert v["totals"]["scenario"] == 1650.0 + 737.0
    assert v["totals"]["currency"] == "USD"


def test_view_custom_holding_never_fetches(portfolio_path, monkeypatch):
    portfolio.add_position(_pos("JPF", "JP fund", shares=100, cost=50.0,
                                kind="custom", price=55.0, currency="USD"))
    v = risk.view()
    p = v["positions"][0]
    assert p["value"] == 5500.0
    assert p["vol"] is None        # no exchange history for a custom holding


# ---------------------------------------------------------------------------
# Fill with AI
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, content, status=200):
        self._content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("bad", request=None, response=self)

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _llm(monkeypatch, content):
    import app.llm as m
    monkeypatch.setattr(m.httpx, "post", lambda *a, **k: _FakeResp(content))


def test_ai_fill_no_key_is_plain_error(monkeypatch):
    monkeypatch.delenv("PROOF_LLM_KEY", raising=False)
    with pytest.raises(RuntimeError, match="no language model key"):
        risk.ai_fill({"positions": [_row()]})


def test_ai_fill_parses_and_matches_case_insensitively(monkeypatch):
    monkeypatch.setenv("PROOF_LLM_KEY", "test")
    _llm(monkeypatch, json.dumps({"moves": {"aapl": 15, "MSFT": -8}}))
    out = risk.ai_fill({"positions": [_row("AAPL"), _row("MSFT")]})
    assert out["moves"] == {"AAPL": 15.0, "MSFT": -8.0}
    assert out["n"] == 2


def test_ai_fill_clamps_and_drops_unknown(monkeypatch):
    monkeypatch.setenv("PROOF_LLM_KEY", "test")
    _llm(monkeypatch, json.dumps(
        {"moves": {"AAPL": 5500, "ZZZZ": 5, "MSFT": "lots"}}))
    out = risk.ai_fill({"positions": [_row("AAPL"), _row("MSFT")]})
    assert out["moves"] == {"AAPL": 999.0}   # clamped; ZZZZ unknown; junk dropped


def test_ai_fill_no_match_is_plain_error(monkeypatch):
    monkeypatch.setenv("PROOF_LLM_KEY", "test")
    _llm(monkeypatch, json.dumps({"moves": {"ZZZZ": 5}}))
    with pytest.raises(RuntimeError, match="matched none"):
        risk.ai_fill({"positions": [_row("AAPL")]})


def test_ai_fill_unparsable_is_plain_error(monkeypatch):
    monkeypatch.setenv("PROOF_LLM_KEY", "test")
    _llm(monkeypatch, "I cannot do that.")
    with pytest.raises(RuntimeError):
        risk.ai_fill({"positions": [_row("AAPL")]})


def test_ai_fill_no_holdings_is_plain_error(monkeypatch):
    monkeypatch.setenv("PROOF_LLM_KEY", "test")
    with pytest.raises(RuntimeError, match="nothing to fill"):
        risk.ai_fill({"positions": []})


def test_ai_fill_http_error_is_runtime(monkeypatch):
    monkeypatch.setenv("PROOF_LLM_KEY", "test")
    import httpx

    def boom(*a, **k):
        raise httpx.TimeoutException("timeout")

    import app.llm as m
    monkeypatch.setattr(m.httpx, "post", boom)
    with pytest.raises(RuntimeError) as ei:
        risk.ai_fill({"positions": [_row("AAPL")]})
    # The shared caller converts transport failures into plain English;
    # the route turns that into a 502 the reader can act on.
    assert "seconds" in str(ei.value)
    assert "try again" in str(ei.value)


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

def test_routes_end_to_end(portfolio_path, risk_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m

    portfolio.add_position(_pos(shares=10, cost=120.0))
    monkeypatch.setattr(
        m.market_data, "quote",
        lambda sym, ttl, name_hint=None: _quote(sym, price=150.0))
    monkeypatch.setattr(
        m.market_data, "price_series", lambda *a, **k: None)
    monkeypatch.setattr(
        m.market_data, "fx_rate", lambda *a, **k: None)
    monkeypatch.delenv("PROOF_LLM_KEY", raising=False)

    with TestClient(m.app) as client:
        r = client.get("/api/risk")
        assert r.status_code == 200
        body = r.json()
        assert body["positions"][0]["ticker"] == "AAPL"
        assert body["positions"][0]["move"] == 0.0

        r = client.post("/api/risk", json={"moves": {"AAPL": 25, "JUNK": "x"}})
        assert r.status_code == 200
        assert r.json()["moves"] == {"AAPL": 25.0}

        r = client.get("/api/risk")
        assert r.json()["positions"][0]["move"] == 25.0
        assert r.json()["positions"][0]["scenario_value"] == 1875.0

        r = client.post("/api/risk/fill", json={"positions": body["positions"]})
        assert r.status_code == 503   # no key configured
