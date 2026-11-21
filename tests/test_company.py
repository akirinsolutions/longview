"""Offline tests for the company page (app/market_data.py, the company
half).

The parsing helpers are pure, so they get real Yahoo-shaped payloads; the
network functions are monkeypatched to failure to prove the never-raises,
never-500 promise — a blocked Yahoo is all dashes, not an error.
"""
import json
import math

import pytest

from app import market_data


def test_opt_filters_junk_and_rounds():
    assert market_data._opt(1.23456789) == 1.234568
    assert market_data._opt(None) is None
    assert market_data._opt("12.3") is None
    assert market_data._opt(float("nan")) is None
    assert market_data._opt(True) is None       # a bool is not a number here


def test_pct_reads_fractions_and_percents():
    assert market_data._pct(0.0055) == 0.55    # 0.55% yield, fraction form
    assert market_data._pct(5.5) == 5.5        # 5.5%, percent form
    assert market_data._pct(None) is None


def test_clip_about_keeps_short_text_and_cuts_long_text_on_a_boundary():
    short = "  Small   story.  "
    assert market_data._clip_about(short) == "Small story."
    long = ("Apple makes phones; Mac computers; iPads; watches; "
            "and a hundred other things that people love.")
    out = market_data._clip_about(long * 8)     # ~660 chars: must be clipped
    assert len(out) <= 401                 # at most `limit` + the ellipsis
    assert out.endswith("…")               # the cut is marked
    assert "  " not in out                 # spacing was tidied


def test_blank_company_is_all_nulls():
    c = market_data._blank_company("AAPL")
    assert c["symbol"] == "AAPL"
    assert c["price"] is None and c["history"] == []
    assert c["margins"] == {"gross": None, "operating": None, "net": None}
    json.dumps(c)                              # must be JSON-safe (no NaNs)


def test_merge_quote_takes_the_market_numbers():
    c = market_data._blank_company("AAPL")
    market_data._merge_quote(c, {
        "shortName": "Apple Inc.",
        "regularMarketPrice": 210.5,
        "regularMarketChange": 3.2,
        "regularMarketChangePercent": 1.5,
        "regularMarketDayLow": 208.0,
        "regularMarketDayHigh": 212.0,
        "fiftyTwoWeekLow": 169.0,
        "fiftyTwoWeekHigh": 260.0,
        "marketCap": 3.2e12,
        "trailingPE": 31.2,
        "epsTrailingTwelveMonths": 6.75,
        "dividendYield": 0.0055,
        "fiftyDayAverage": 205.0,
        "twoHundredDayAverage": 198.0,
        "regularVolume": 4_100_000,
        "averageDailyVolume3Month": 5_400_000,
        "currency": "USD",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "regularMarketTime": 1793000000,
    })
    assert c["name"] == "Apple Inc."
    assert c["price"] == 210.5
    assert c["day_range"] == [208.0, 212.0]
    assert c["week52"] == [169.0, 260.0]
    assert c["div_yield"] == 0.55             # fraction read as percent
    assert c["pe"] == 31.2 and c["sector"] == "Technology"


def test_merge_summary_reads_yahoos_wrapped_raw_numbers():
    """quoteSummary wraps every number as {"raw": …, "fmt": "…"} — the
    real shape since 2024. Every stat must survive the wrapper."""
    c = market_data._blank_company("AAPL")
    market_data._merge_summary(c, {
        "price": {
            "regularMarketPrice": {"raw": 342.37, "fmt": "342.37"},
            "regularMarketChange": {"raw": -1.8, "fmt": "-1.80"},
            "regularMarketChangePercent": {"raw": -0.00523, "fmt": "-0.52%"},
            "regularMarketDayLow": {"raw": 338.3, "fmt": "338.30"},
            "regularMarketDayHigh": {"raw": 345.79, "fmt": "345.79"},
            "marketCap": {"raw": 4.97e12, "fmt": "4.97T"},
            "regularMarketVolume": {"raw": 43_750_861, "fmt": "43.75M"},
            "regularMarketTime": 1793998801,
            "currency": "USD",
        },
        "summaryDetail": {
            "fiftyTwoWeekLow": {"raw": 243.42, "fmt": "243.42"},
            "fiftyTwoWeekHigh": {"raw": 355.38, "fmt": "355.38"},
            "trailingPE": {"raw": 38.12, "fmt": "38.12"},
            "dividendYield": {"raw": 0.0032, "fmt": "0.32%"},
            "fiftyDayAverage": {"raw": 336.01, "fmt": "336.01"},
            "twoHundredDayAverage": {"raw": 298.81, "fmt": "298.81"},
            "volume": {"raw": 43_750_861, "fmt": "43.75M"},
            "averageVolume": {"raw": 42_880_493, "fmt": "42.88M"},
        },
        "defaultKeyStatistics": {
            "trailingEps": {"raw": 8.98, "fmt": "8.98"},
            "sharesOutstanding": {"raw": 14_532_182_000, "fmt": "14.53B"},
        },
        "financialData": {
            "totalRevenue": {"raw": 4.78e11, "fmt": "478.83B"},
            "freeCashflow": {"raw": 105_658_376_192, "fmt": "105.66B"},
            "totalCash": {"raw": 56_722_001_920, "fmt": "56.72B"},
            "totalDebt": {"raw": 94_478_999_552, "fmt": "94.48B"},
            "revenueGrowth": {"raw": 0.0821, "fmt": "8.21%"},
            "financialCurrency": "USD",
            "grossMargins": {"raw": 0.48786, "fmt": "48.79%"},
            "operatingMargins": {"raw": 0.31125, "fmt": "31.13%"},
            "profitMargins": {"raw": 0.27604, "fmt": "27.60%"},
        },
        "calendarEvents": {"earnings": {"earningsDate": [{"raw": 1801170000}]}},
    })
    assert c["price"] == 342.37
    assert c["change"] == -1.8
    assert c["change_pct"] == -0.00523
    assert c["day_range"] == [338.3, 345.79]
    assert c["week52"] == [243.42, 355.38]
    assert c["market_cap"] == 4.97e12
    assert c["pe"] == 38.12 and c["eps"] == 8.98
    assert c["div_yield"] == 0.32
    assert c["ma50"] == 336.01 and c["ma200"] == 298.81
    assert c["volume"] == 43_750_861 and c["avg_volume"] == 42_880_493
    assert c["revenue"] == 4.78e11
    assert c["free_cash_flow"] == 105_658_376_192
    assert c["shares_outstanding"] == 14_532_182_000
    assert c["total_cash"] == 56_722_001_920
    assert c["total_debt"] == 94_478_999_552
    assert c["revenue_growth"] == 8.21
    assert c["financial_currency"] == "USD"
    assert c["margins"] == {"gross": 48.79, "operating": 31.13, "net": 27.6}
    assert c["market_time"] == 1793998801
    assert c["next_earnings"].startswith("2027")


def test_merge_quote_survives_empty_object():
    c = market_data._blank_company("AAPL")
    market_data._merge_quote(c, {})           # nothing, no crash
    assert c["price"] is None
    market_data._merge_quote(c, None)         # and no object at all
    assert c["price"] is None


def test_merge_summary_fills_gaps_and_adds_the_company_numbers():
    c = market_data._blank_company("AAPL")
    market_data._merge_summary(c, {
        "price": {"regularMarketPrice": 210.5, "currency": "USD"},
        "summaryDetail": {
            "dividendYield": 0.55,            # percents here, not fractions
            "trailingPE": 31.0,
            "fiftyTwoWeekRange": {"lower": 169.0, "upper": 260.0},
        },
        "defaultKeyStatistics": {"epsTrailing12Months": 6.7},
        "financialData": {
            "totalRevenue": 4.0e11,
            "grossMargins": 0.45,
            "operatingMargins": 0.31,
            "profitMargins": 0.25,
        },
        "assetProfile": {
            "name": "Apple Inc.",
            "fullTimeEmployees": 161000,
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "city": "Cupertino",
            "state": "CA",
            "country": "US",
            "website": "https://www.apple.com",
            "longBusinessSummary": "  Apple   designs phones.   ",
        },
        "calendarEvents": {"earningsDate": ["2026-12-05"]},
    })
    assert c["name"] == "Apple Inc."
    assert c["div_yield"] == 0.55             # NOT 55: the module says percents
    assert c["revenue"] == 4.0e11
    assert c["margins"] == {"gross": 45.0, "operating": 31.0, "net": 25.0}
    assert c["hometown"] == "Cupertino, CA, US"
    assert c["about"] == "Apple designs phones."
    assert c["next_earnings"] == "2026-12-05"


def test_merge_summary_earnings_epoch_and_old_shapes():
    c = market_data._blank_company("X")
    market_data._merge_summary(
        c, {"calendarEvents": {"earningsDate": [1799000000]}})
    assert c["next_earnings"].startswith("2027")      # epoch -> ISO date
    c = market_data._blank_company("X")
    market_data._merge_summary(
        c, {"calendarEvents": {"earningsDate": [{"epochDate": 1799000000}]}})
    assert c["next_earnings"].startswith("2027")


def test_returns_from_history_math():
    # 400 straight daily closes, closing prices 100..499 (a 5x climb)
    from datetime import date, timedelta
    d0 = date(2025, 1, 1)
    hist = [((d0 + timedelta(days=i)).isoformat(), 100 + i)
            for i in range(400)]
    r = market_data._returns_from_history(hist)
    assert r is not None
    # last 499 vs ~139 a year earlier ≈ +259%
    assert 2.0 < r["1y"] < 3.0
    assert 0.0 < r["ytd"] < 0.2     # a mild January-so-far
    assert 0.0 < r["1m"] < 0.2


def test_returns_too_short_is_none():
    assert market_data._returns_from_history(
        [("2025-01-0%d" % i, float(i)) for i in range(1, 9)]) is None


def test_company_from_parts_assembles():
    c = market_data._company_from_parts(
        "AAPL",
        {"shortName": "Apple Inc.", "regularMarketPrice": 210.5},
        {"assetProfile": {"name": "Apple Inc."}},
        None,
        [("2025-01-01", 100.0), ("2025-01-02", 101.0)],
    )
    assert c["name"] == "Apple Inc."
    assert c["price"] == 210.5
    assert c["history"] == [{"d": "2025-01-01", "c": 100.0},
                            {"d": "2025-01-02", "c": 101.0}]


def test_company_all_blocked_is_all_dashes_not_an_error(tmp_path, monkeypatch):
    """Yahoo 429s everything: the page still renders, with nulls."""
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path / "prices")
    monkeypatch.setattr(market_data, "_crumb", lambda force=False: None)

    def no_chart(symbol, start, end, retries=6):
        raise RuntimeError("Could not reach Yahoo")
    monkeypatch.setattr(market_data, "_fetch_chart", no_chart)

    c = market_data.company("AAPL")
    assert c["symbol"] == "AAPL"
    assert c["price"] is None and c["name"] is None and c["history"] == []
    json.dumps(c)                       # and it is still JSON-safe
    assert not (tmp_path / "prices" / "company_AAPL.json").exists()  # nothing worth caching


def test_company_with_all_three_parts_and_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "_PRICE_DIR", tmp_path / "prices")
    monkeypatch.setattr(market_data, "_crumb", lambda force=False: {
        "cookie": "a=1", "crumb": "tok", "ua": "ua", "ts": 1.0})

    def fake_crumb_get(path, symbol, params, force=False):
        if "/v8/" in path:
            return {"quoteResponse": {"result": [{
                "shortName": "Apple Inc.", "regularMarketPrice": 210.5,
                "currency": "USD"}]}}
        if "/v10/" in path:
            return {"quoteSummary": {"result": [{
                "financialData": {"totalRevenue": 4.0e11}}]}}
        return None
    monkeypatch.setattr(market_data, "_crumb_get", fake_crumb_get)
    monkeypatch.setattr(market_data, "_fetch_chart",
                        lambda s, a, b, retries=6: {
                            "timestamp": [1_700_000_000, 1_700_086_400],
                            "meta": {"exchangeTimezoneName": "America/New_York"},
                            "indicators": {"quote": [
                                {"close": [100.0, 101.0]}]}})

    c = market_data.company("AAPL")
    assert c["name"] == "Apple Inc."
    assert c["price"] == 210.5
    assert c["revenue"] == 4.0e11
    assert len(c["history"]) == 2
    cache = tmp_path / "prices" / "company_AAPL.json"
    assert cache.exists()               # at least one part landed: cached
    assert json.loads(cache.read_text())["symbol"] == "AAPL"


def test_company_bad_symbol_is_blank_not_an_error():
    c = market_data.company("   ")
    assert c["symbol"] is None and c["price"] is None
