"""Yahoo response handling, offline."""
import json
import os
import time

import pytest

from app import market_data


def test_normalize_symbol_variants():
    assert market_data._normalize_symbol(" aapl.us ") == "AAPL"
    assert market_data._normalize_symbol("SPY") == "SPY"
    assert market_data._normalize_symbol("QQQ.NASDAQ") == "QQQ"
    assert market_data._normalize_symbol(".spy") == "SPY"
    assert market_data._normalize_symbol("") == ""


def test_chunk_rows_prefers_adjusted_and_drops_gaps():
    t = 1_700_000_000  # 2023-11-14, a Tuesday
    res = {
        "timestamp": [t, t + 86400, t + 172800, t + 259200],
        "meta": {"exchangeTimezoneName": "America/New_York"},
        "indicators": {
            "quote": [{"close": [1.0, None, 3.0, None]}],
            "adjclose": [{"adjclose": [1.0, None, None, None]}],
        },
    }
    rows = market_data._chunk_rows(res)
    # row 1: adjusted 1.0; row 2: both missing -> dropped; row 3: raw 3.0;
    # row 4: both missing -> dropped
    assert len(rows) == 2
    assert rows[0][1] == 1.0
    assert rows[1][1] == 3.0
    # daily bars are stamped midnight in the exchange timezone; for a US
    # exchange the UTC calendar date must match
    assert rows[0][0] == "2023-11-14"


def test_chunk_rows_handles_missing_indicator_blocks():
    rows = market_data._chunk_rows({"timestamp": [1_700_000_000]})
    assert rows == []


# ---------------------------------------------------------------------------
# Bare-ticker resolution (VDST -> VDST.L)
# ---------------------------------------------------------------------------

def test_resolve_symbol_picks_the_same_base_and_name(monkeypatch):
    monkeypatch.setattr(market_data, "_resolved", {})
    monkeypatch.setattr(market_data, "search", lambda q, limit=8: [
        {"symbol": "VUCF.DE", "name": "Vanguard U.S. Treasury 0-1 Year Bond UCITS ETF"},
        {"symbol": "VDST.L", "name": "Vanguard U.S. Treasury 0-1 Year Bond UCITS ETF"},
        {"symbol": "VDST.MI", "name": "Vanguard U.S. Treasury 0-1 Year Bond UCITS ETF"},
    ])
    got = market_data._resolve_symbol(
        "VDST", "Vanguard U.S. Treasury 0-1 Year Bond UCITS ETF")
    assert got in ("VDST.L", "VDST.MI")       # same base only, never VUCF
    assert got == "VDST.L"                    # first best candidate wins


def test_resolve_symbol_never_swaps_a_different_company(monkeypatch):
    monkeypatch.setattr(market_data, "_resolved", {})
    monkeypatch.setattr(market_data, "search", lambda q, limit=8: [
        {"symbol": "VDST.L", "name": "Something Else Entirely"},
    ])
    # A matching base with a name that disagrees is too risky when we
    # know the saved name: no candidate is accepted.
    assert market_data._resolve_symbol("VDST", "Vanguard Treasury") is None


def test_resolve_symbol_leaves_a_suffixed_ticker_alone(monkeypatch):
    monkeypatch.setattr(market_data, "_resolved", {})
    assert market_data._resolve_symbol("VDST.L", "Vanguard") is None


# ---------------------------------------------------------------------------
# Currency conversion (Yahoo FX charts)
# ---------------------------------------------------------------------------

def test_fx_rate_reads_direct_and_inverse_pairs(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path)
    monkeypatch.setattr(market_data, "_fx_mem", {})
    def fake_chart(sym, start, end, retries=3):
        if sym == "EURUSD=X":
            return {"meta": {"regularMarketPrice": 1.25}}
        return None
    monkeypatch.setattr(market_data, "_fetch_chart", fake_chart)
    assert market_data.fx_rate("EUR", "USD") == 1.25
    assert market_data.fx_rate("USD", "USD") == 1.0


def test_fx_rate_flips_the_inverse_when_needed(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path)
    monkeypatch.setattr(market_data, "_fx_mem", {})
    monkeypatch.setattr(
        market_data, "_fetch_chart",
        lambda sym, start, end, retries=3: {"meta": {"regularMarketPrice": 0.8}}
        if sym == "USDEUR=X" else None)
    assert market_data.fx_rate("EUR", "USD") == pytest.approx(1.25)


def test_fx_rate_missing_pair_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path)
    monkeypatch.setattr(market_data, "_fx_mem", {})
    monkeypatch.setattr(market_data, "_fetch_chart",
                        lambda *a, **k: None)
    assert market_data.fx_rate("GBP", "JPY") is None


# ---------------------------------------------------------------------------
# price_series: the portfolio's interval gains come from here, and its
# callers pass symbols Yahoo already resolved — the exchange suffix matters.
# ---------------------------------------------------------------------------

def test_price_series_keeps_exchange_suffix(tmp_path, monkeypatch):
    # LSE-listed funds: "CSPX" 404s, "CSPX.L" works. The suffix is what
    # makes the symbol valid, so it must survive the round trip.
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path)
    seen = []
    bars = [("2026-11-%02d" % d, 100.0 + d) for d in range(1, 11)]
    monkeypatch.setattr(
        market_data, "_fetch_range",
        lambda s, a, b: (seen.append(s), bars)[1])
    h = market_data.price_series("cspX.L", days=30)
    assert seen == ["CSPX.L"]
    assert h == dict(bars)


def test_price_series_bare_tickers_still_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path)
    seen = []
    bars = [("2026-11-01", 100.0), ("2026-11-02", 101.0)]
    monkeypatch.setattr(
        market_data, "_fetch_range",
        lambda s, a, b: (seen.append(s), bars)[1])
    assert market_data.price_series(" aapl ", days=30) is not None
    assert seen == ["AAPL"]


def test_price_series_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path)
    def boom(s, a, b):
        raise RuntimeError("Yahoo has no data for 'X' (delisted)")
    monkeypatch.setattr(market_data, "_fetch_range", boom)
    assert market_data.price_series("X", days=30) is None
    assert market_data.price_series("", days=30) is None


# ---------------------------------------------------------------------------
# Stale-cache fallback: when Yahoo is blocked (a 429 burst), the last good
# cache is served, up to a week old, instead of a dash.
# ---------------------------------------------------------------------------

def _boom(*a, **k):
    raise RuntimeError("Yahoo is busy or rate-limiting (HTTP 429)")


def _age_file(path, seconds_ago):
    t = time.time() - seconds_ago
    os.utime(path, (t, t))


def test_quote_serves_stale_cache_when_yahoo_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path)
    q = {"symbol": "VDST",
         "name": "Vanguard U.S. Treasury 0-1 Year Bond UCITS ETF",
         "price": 59.945, "week": 0.001, "as_of": "2026-11-06",
         "exchange": "LSE", "currency": "USD", "fetched": 1}
    p = tmp_path / "quote_VDST.json"
    p.write_text(json.dumps(q))
    _age_file(p, 3600)  # an hour ago: past the 10-min TTL, inside a week
    monkeypatch.setattr(market_data, "_fetch_chart", _boom)
    monkeypatch.setattr(market_data, "_resolved", {})
    monkeypatch.setattr(market_data, "search", lambda *a, **k: None)
    got = market_data.quote("vdst")
    assert got["price"] == 59.945 and got["as_of"] == "2026-11-06"
    assert got["stale"] is True


def test_quote_ignores_a_cache_older_than_a_week(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path)
    p = tmp_path / "quote_VDST.json"
    p.write_text(json.dumps({"symbol": "VDST", "price": 59.945, "fetched": 1}))
    _age_file(p, 8 * 86400)  # 8 days: even a blocked Yahoo earns a dash
    monkeypatch.setattr(market_data, "_fetch_chart", _boom)
    monkeypatch.setattr(market_data, "_resolved", {})
    monkeypatch.setattr(market_data, "search", lambda *a, **k: None)
    assert market_data.quote("vdst") is None


def test_price_series_serves_stale_file_when_fetch_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path)
    bars = {"2026-11-%02d" % d: 100.0 + d for d in range(1, 12)}  # 11 bars
    p = tmp_path / "price_X_10.json"  # days=400 -> years 1.095 -> "10" file
    p.write_text(json.dumps({"symbol": "X", "fetched": 1, "data": bars}))
    _age_file(p, 24 * 3600)  # a day: past the 12-h TTL, inside a week
    monkeypatch.setattr(market_data, "_fetch_range", _boom)
    assert market_data.price_series("X", days=400) == bars


def test_price_series_ignores_a_file_older_than_a_week(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path)
    bars = {"2026-11-%02d" % d: 100.0 + d for d in range(1, 12)}
    p = tmp_path / "price_X_10.json"
    p.write_text(json.dumps({"symbol": "X", "fetched": 1, "data": bars}))
    _age_file(p, 8 * 86400)
    monkeypatch.setattr(market_data, "_fetch_range", _boom)
    assert market_data.price_series("X", days=400) is None


def test_fx_rate_serves_stale_rate_and_keeps_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path)
    monkeypatch.setattr(market_data, "_fx_mem", {})
    p = tmp_path / "fx_EUR_USD.json"
    p.write_text(json.dumps(
        {"base": "EUR", "quote": "USD", "rate": 1.2, "fetched": 1}))
    _age_file(p, 2 * 3600)  # 2 hours: past the 1-h TTL, inside a week
    monkeypatch.setattr(market_data, "_fetch_chart", _boom)
    assert market_data.fx_rate("EUR", "USD") == 1.2
    # a failed fetch must not clobber the last good rate on disk
    assert json.loads(p.read_text())["rate"] == 1.2
