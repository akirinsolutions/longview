"""Offline tests for the investor's portfolio.

The portfolio file is pointed at a temp dir per test (same trick as the
roster tests), and the two live sources — Yahoo quotes and the 13F pool —
are monkeypatched fakes, so nothing here touches the network or the real
data files.
"""
import json

import pytest

from app import funds, market_data, portfolio


@pytest.fixture
def portfolio_path(tmp_path, monkeypatch):
    p = tmp_path / "portfolio.json"
    monkeypatch.setattr(portfolio, "PORTFOLIO_PATH", p)
    return p


@pytest.fixture(autouse=True)
def _no_live_history(monkeypatch):
    """These tests are offline. The view now also fetches a year of price
    history per position (for the interval gains); default it to nothing
    unless a test installs its own fake (a test-body patch overrides)."""
    monkeypatch.setattr(market_data, "price_series",
                        lambda *a, **k: None)


def _hist(end_price=110.0, start_price=100.0, days=420, end=None,
          weekdays_only=False):
    """A synthetic history: one bar per day (or trading day), log-linear
    from start_price (oldest) to end_price (newest)."""
    from datetime import date as _date, timedelta as _td
    end = end or _date.today()
    out = {}
    for i in range(days, -1, -1):
        d = end - _td(days=i)
        if weekdays_only and d.weekday() >= 5:
            continue
        f = (days - i) / days
        out[d.isoformat()] = round(
            start_price * (end_price / start_price) ** f, 6)
    return out


def _pos(ticker="AAPL", name="Apple Inc.", shares=10, cost=120.0, note="", **extra):
    return {"ticker": ticker, "name": name, "shares": shares,
            "cost_basis": cost, "note": note, **extra}


def _quote(sym, price=150.0, week=0.02, name=None, cur="USD"):
    return {"symbol": sym, "name": name or f"{sym} Co", "price": price,
            "week": week, "as_of": "2026-11-04", "exchange": "NMS",
            "currency": cur, "fetched": 1793000000}


def _pool(rows=None):
    return {"v": 3, "as_of": "2026-06-30", "generated": "2026-08-15",
            "funds": [{"key": "berkshire", "name": "Berkshire Hathaway",
                        "error": None}],
            "rows": rows if rows is not None else [],
            "new_this_quarter": [], "biggest_moves": [], "crowding_change": []}


def _row(issuer="APPLE INC", fund="berkshire", status="increased",
         n_funds=3, value=1e9, change=0.25):
    return {"fund": fund, "fund_name": "Berkshire Hathaway",
            "issuer": issuer, "class": "COM", "cusip": "037833100",
            "key": f"NM {funds.normalize_name(issuer)}",
            "value": value, "shares": 1e7, "weight": 0.1, "asset": "stock",
            "prev_value": value * 0.8, "change": change,
            "move_value": value * 0.2, "status": status,
            "n_funds": n_funds, "holders": [fund], "surprise": False}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_missing_file_is_an_empty_portfolio(portfolio_path):
    assert portfolio.load_portfolio() == []


def test_add_saves_and_reloads(portfolio_path):
    portfolio.add_position(_pos())
    saved = json.loads(portfolio_path.read_text())
    assert saved["v"] == portfolio._PORTFOLIO_VERSION
    assert len(saved["positions"]) == 1
    assert portfolio.load_portfolio()[0]["ticker"] == "AAPL"


def test_corrupt_file_is_an_empty_portfolio(portfolio_path):
    portfolio_path.write_text("{ not json")
    assert portfolio.load_portfolio() == []


def test_wrong_version_file_is_an_empty_portfolio(portfolio_path):
    portfolio_path.write_text(json.dumps(
        {"v": 99, "updated": 0, "positions": [{"ticker": "X"}]}))
    assert portfolio.load_portfolio() == []


def test_remove_and_reload(portfolio_path):
    portfolio.add_position(_pos("AAPL"))
    portfolio.add_position(_pos("MSFT", "Microsoft", shares=5, cost=300.0))
    removed = portfolio.remove_position("aapl")   # case-insensitive
    assert removed["ticker"] == "AAPL"
    assert [p["ticker"] for p in portfolio.load_portfolio()] == ["MSFT"]


def test_remove_unknown_is_keyerror(portfolio_path):
    portfolio.add_position(_pos())
    with pytest.raises(KeyError):
        portfolio.remove_position("NOPE")


def test_update_changes_numbers(portfolio_path):
    portfolio.add_position(_pos())
    out = portfolio.update_position("AAPL",
                                    _pos(shares=25, cost=99.5, note="trimmed"))
    assert out["shares"] == 25 and out["cost_basis"] == 99.5
    assert portfolio.load_portfolio()[0]["note"] == "trimmed"


def test_update_unknown_is_keyerror(portfolio_path):
    portfolio.add_position(_pos())
    with pytest.raises(KeyError):
        portfolio.update_position("NOPE", _pos("NOPE"))


def test_add_rejects_duplicate_ticker(portfolio_path):
    portfolio.add_position(_pos())
    with pytest.raises(ValueError, match="already in your portfolio"):
        portfolio.add_position(_pos(name="Different Name"))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_clean_normalizes_ticker_case():
    p = portfolio.clean_position(_pos(ticker=" aapl "))
    assert p["ticker"] == "AAPL"


def test_clean_keeps_dotted_tickers():
    assert portfolio.clean_position(_pos(ticker="brk.b"))["ticker"] == "BRK.B"


def test_clean_rejects_missing_or_wild_ticker():
    with pytest.raises(ValueError, match="ticker"):
        portfolio.clean_position(_pos(ticker=""))
    with pytest.raises(ValueError, match="ticker"):
        portfolio.clean_position(_pos(ticker="a" * 20))


def test_clean_rejects_bad_shares_and_cost():
    with pytest.raises(ValueError, match="shares"):
        portfolio.clean_position(_pos(shares=0))
    with pytest.raises(ValueError, match="shares"):
        portfolio.clean_position(_pos(shares="lots"))
    with pytest.raises(ValueError, match="cost"):
        portfolio.clean_position(_pos(cost=-5))
    # zero cost is allowed (a gift, or "I don't remember")
    assert portfolio.clean_position(_pos(cost=0))["cost_basis"] == 0.0


def test_clean_trims_and_caps_text():
    p = portfolio.clean_position(_pos(name="  Apple   Inc.  ", note="x" * 300))
    assert p["name"] == "Apple Inc."
    assert len(p["note"]) == 120


# ---------------------------------------------------------------------------
# Smart-money matching (13F pool, faked)
# ---------------------------------------------------------------------------

def test_smart_money_matches_and_ranks_status():
    pool = _pool(rows=[
        _row(status="increased", fund="berkshire"),
        _row(status="new", fund="citadel"),
    ])
    r = portfolio.smart_money("Apple Inc.", pool)
    assert r["n_funds"] == 2
    assert r["status"] == "new"          # strongest move wins
    assert set(r["holders"]) == {"Berkshire Hathaway"}


def test_smart_money_survives_the_del_suffix():
    # 13Fs write 'BERKSHIRE HATHAWAY INC DEL' (Delaware); Yahoo names it
    # 'Berkshire Hathaway Inc.' — these must be the same company.
    pool = _pool(rows=[_row(issuer="BERKSHIRE HATHAWAY INC DEL",
                             status="increased", n_funds=4)])
    r = portfolio.smart_money("Berkshire Hathaway", pool)
    assert r is not None and r["n_funds"] >= 1


def test_smart_money_rejects_lookalikes():
    pool = _pool(rows=[_row(issuer="APPLE HOSPITALITY AND RESORTS")])
    assert portfolio.smart_money("Apple Inc.", pool) is None


def test_smart_money_ignores_exited_funds():
    pool = _pool(rows=[_row(status="exited")])
    assert portfolio.smart_money("Apple Inc.", pool) is None


def test_smart_money_no_pool_means_no_signal():
    assert portfolio.smart_money("Apple Inc.", None) is None
    assert portfolio.smart_money("Apple Inc.", {"rows": []}) is None


# ---------------------------------------------------------------------------
# The home view: enrichment + totals, fully faked
# ---------------------------------------------------------------------------

def test_view_enriches_and_sums(portfolio_path, monkeypatch):
    portfolio.add_position(_pos(shares=10, cost=120.0))
    portfolio.add_position(_pos("MSFT", "Microsoft", shares=5, cost=300.0))
    monkeypatch.setattr(
        market_data, "quote",
        lambda sym, ttl, name_hint=None: _quote(
            sym, price=150.0 if sym == "AAPL" else 400.0))
    monkeypatch.setattr(funds, "scan_pool",
                        lambda refresh=False: _pool(rows=[_row()]))
    v = portfolio.view()
    assert v["n_live"] == 2
    aapl, msft = v["positions"]
    assert aapl["value"] == 1500.0 and aapl["pl"] == 300.0
    assert msft["value"] == 2000.0 and msft["pl"] == 500.0
    assert v["totals"]["value"] == 3500.0
    assert v["totals"]["pl"] == 800.0
    assert aapl["smart"] is not None          # 'Apple Inc.' hits the fake row
    assert msft["smart"] is None              # Microsoft: nothing in the pool


def test_view_null_quote_degrades_to_dashes(portfolio_path, monkeypatch):
    portfolio.add_position(_pos())
    monkeypatch.setattr(market_data, "quote",
                        lambda sym, ttl, name_hint=None: None)
    monkeypatch.setattr(funds, "scan_pool", lambda refresh=False: _pool())
    v = portfolio.view()
    p = v["positions"][0]
    assert p["price"] is None and p["value"] is None and p["pl"] is None
    assert p["live"] is False
    assert p["name"] == "Apple Inc."          # saved name still shows
    assert v["totals"]["value"] is None
    assert v["n_live"] == 0


def test_view_pool_failure_kills_only_the_column(portfolio_path, monkeypatch):
    portfolio.add_position(_pos())
    monkeypatch.setattr(market_data, "quote",
                        lambda sym, ttl, name_hint=None: _quote(sym))
    def boom(refresh=False):
        raise RuntimeError("SEC is down")
    monkeypatch.setattr(funds, "scan_pool", boom)
    v = portfolio.view()
    assert v["positions"][0]["price"] == 150.0   # prices survived
    assert v["positions"][0]["smart"] is None    # smart money is just blank


def test_view_mixed_currencies_dont_sum(portfolio_path, monkeypatch):
    portfolio.add_position(_pos())
    portfolio.add_position(_pos("SAP", "SAP SE", shares=2, cost=180.0))
    monkeypatch.setattr(
        market_data, "quote",
        lambda sym, ttl, name_hint=None: _quote(
            sym, price=150.0 if sym == "AAPL" else 200.0,
            cur="USD" if sym == "AAPL" else "EUR"))
    monkeypatch.setattr(funds, "scan_pool", lambda refresh=False: _pool())
    v = portfolio.view()
    assert v["totals"]["value"] is None          # $ + € don't add up
    assert v["totals"]["currencies"] == ["EUR", "USD"]


# ---------------------------------------------------------------------------
# Interval gains: 1 week … 1 year, from one cached history per symbol
# ---------------------------------------------------------------------------

def _one_year_pct(start=100.0, end=110.0, days=420):
    """The 1-year endpoint of the synthetic _hist, by construction."""
    f = (days - 365) / days
    return end / (start * (end / start) ** f) - 1


def test_interval_stats_reads_every_window():
    st = portfolio._interval_stats(_hist(), 10)
    for k in ("1w", "1m", "3m", "6m", "1y"):
        assert st[k] is not None
    # a rising line: every window is positive, longer windows larger
    pcts = [st[k]["pct"] for k in ("1w", "1m", "3m", "6m", "1y")]
    assert all(x > 0 for x in pcts) and pcts == sorted(pcts)
    # pct is rounded to 6 decimals server-side, so an absolute tolerance
    assert st["1y"]["pct"] == pytest.approx(_one_year_pct(), abs=1e-6)
    # the gain is shares times the price move, in currency
    then = 100.0 * (110.0 / 100.0) ** ((420 - 365) / 420)
    assert st["1y"]["pl"] == pytest.approx(10 * (110.0 - then), abs=0.01)


def test_interval_stats_new_listing_gaps_the_long_windows():
    st = portfolio._interval_stats(_hist(days=100), 5)
    assert st["1w"] is not None and st["1m"] is not None
    assert st["3m"] is not None
    assert st["6m"] is None and st["1y"] is None
    # no history at all: every window None, never a guess
    assert portfolio._interval_stats(None, 5) == {
        k: None for k in ("1w", "1m", "3m", "6m", "1y")}


def test_view_carries_interval_gains_and_totals(portfolio_path, monkeypatch):
    portfolio.add_position(_pos(shares=10, cost=120.0))
    monkeypatch.setattr(market_data, "quote",
                        lambda sym, ttl, name_hint=None: _quote(sym))
    monkeypatch.setattr(market_data, "price_series",
                        lambda s, days=400: _hist())
    monkeypatch.setattr(funds, "scan_pool",
                        lambda refresh=False: _pool())
    v = portfolio.view()
    p = v["positions"][0]
    assert p["intervals"]["1y"]["pct"] == pytest.approx(
        _one_year_pct(), rel=1e-3)
    t = v["totals"]["intervals"]["1y"]
    assert t["priced"] == 1
    assert t["pl_pct"] == pytest.approx(_one_year_pct(), rel=1e-3)
    then = 100.0 * (110.0 / 100.0) ** ((420 - 365) / 420)
    assert t["pl"] == pytest.approx(10 * (110.0 - then), abs=0.05)


def test_view_null_quote_skips_the_history_fetch(portfolio_path, monkeypatch):
    portfolio.add_position(_pos())
    monkeypatch.setattr(market_data, "quote",
                        lambda sym, ttl, name_hint=None: None)
    calls = []
    monkeypatch.setattr(market_data, "price_series",
                        lambda s, days=400: calls.append(s) or None)
    monkeypatch.setattr(funds, "scan_pool", lambda refresh=False: _pool())
    v = portfolio.view()
    assert calls == []                          # Yahoo is busy: don't ask again
    assert v["positions"][0]["intervals"] == {
        k: None for k in ("1w", "1m", "3m", "6m", "1y")}
    assert v["totals"]["intervals"]["1y"] is None


def test_view_custom_holding_has_no_intervals(portfolio_path, monkeypatch):
    portfolio.add_position(_custom())
    calls = []
    monkeypatch.setattr(market_data, "price_series",
                        lambda s, days=400: calls.append(s) or None)
    monkeypatch.setattr(funds, "scan_pool", lambda refresh=False: _pool())
    v = portfolio.view()
    assert calls == []                          # custom never touches Yahoo
    p = v["positions"][0]
    assert all(p["intervals"][k] is None
               for k in ("1w", "1m", "3m", "6m", "1y"))
    assert v["totals"]["intervals"]["1m"] is None


def test_view_mixed_currencies_dont_sum_interval_totals(
        portfolio_path, monkeypatch):
    portfolio.add_position(_pos())
    portfolio.add_position(_pos("SAP", "SAP SE", shares=2, cost=180.0))
    monkeypatch.setattr(
        market_data, "quote",
        lambda sym, ttl, name_hint=None: _quote(
            sym, price=150.0 if sym == "AAPL" else 200.0,
            cur="USD" if sym == "AAPL" else "EUR"))
    monkeypatch.setattr(market_data, "price_series",
                        lambda s, days=400: _hist())
    monkeypatch.setattr(funds, "scan_pool", lambda refresh=False: _pool())
    one = portfolio.view()["totals"]["intervals"]["1y"]
    assert one["priced"] == 2                   # both rows have history…
    assert one["pl"] is None                    # …but $ + € don't add up
    # …and a display currency converts both, so the total sums
    monkeypatch.setattr(market_data, "fx_rate", lambda a, b: 1.0)
    one = portfolio.view(currency="USD")["totals"]["intervals"]["1y"]
    assert one["priced"] == 2 and one["pl"] is not None
    assert one["pl_pct"] is not None


def test_view_missing_fx_rate_dashes_interval_gains(
        portfolio_path, monkeypatch):
    portfolio.add_position(_pos("SAP", "SAP SE", shares=2, cost=100.0))
    monkeypatch.setattr(market_data, "quote",
                        lambda sym, ttl, name_hint=None: _quote(
                            sym, price=150.0, cur="EUR"))
    monkeypatch.setattr(market_data, "fx_rate", lambda a, b: None)
    monkeypatch.setattr(market_data, "price_series",
                        lambda s, days=400: _hist())
    monkeypatch.setattr(funds, "scan_pool", lambda refresh=False: _pool())
    v = portfolio.view(currency="USD")
    p = v["positions"][0]
    assert p["display_intervals"]["1y"] is not None
    assert p["display_intervals"]["1y"]["pl"] is None   # no rate, no number
    assert v["totals"]["intervals"]["1y"] is None       # and it doesn't sum


# ---------------------------------------------------------------------------
# Custom holdings + purchase dates
# ---------------------------------------------------------------------------

def _custom(name="North America Equity Fund", shares=100, cost=10.0,
            price=12.0, cur="USD", **extra):
    return {"kind": "custom", "name": name, "shares": shares,
            "cost_basis": cost, "price": price, "currency": cur, **extra}


def test_custom_gets_a_generated_ticker_and_survives_reload(portfolio_path):
    p = portfolio.add_position(_custom())
    assert p["ticker"] == "CUSTOM-1"
    assert p["kind"] == "custom" and p["currency"] == "USD"
    assert portfolio.load_portfolio()[0]["price"] == 12.0
    assert portfolio.add_position(_custom(name="Second Fund"))["ticker"] == "CUSTOM-2"


def test_custom_is_not_priced_by_yahoo(portfolio_path, monkeypatch):
    portfolio.add_position(_custom(price=12.0, cur="USD"))
    def boom(*a, **k):
        raise AssertionError("custom holdings must not call Yahoo")
    monkeypatch.setattr(market_data, "quote", boom)
    monkeypatch.setattr(funds, "scan_pool", lambda refresh=False: _pool())
    v = portfolio.view()
    p = v["positions"][0]
    assert p["price"] == 12.0 and p["value"] == 1200.0 and p["pl"] == 200.0
    assert p["live"] is True
    assert v["totals"]["value"] == 1200.0


def test_custom_needs_a_name_price_and_currency():
    raw = _custom()
    for missing, msg in (("name", "name"), ("price", "price"),
                         ("currency", "currency")):
        bad = {**raw, missing: ""}
        with pytest.raises(ValueError, match=msg):
            portfolio.clean_position({**bad, "ticker": "CUSTOM-9"})


def test_purchase_date_is_validated_and_kept():
    p = portfolio.clean_position(_pos(purchase_date="2024-05-31"))
    assert p["purchase_date"] == "2024-05-31"
    assert portfolio.clean_position(_pos())["purchase_date"] == ""
    with pytest.raises(ValueError, match="purchase date"):
        portfolio.clean_position(_pos(purchase_date="31/05/2024"))
    with pytest.raises(ValueError, match="calendar"):
        portfolio.clean_position(_pos(purchase_date="2024-02-31"))


# ---------------------------------------------------------------------------
# Currency conversion + partial totals
# ---------------------------------------------------------------------------

def test_view_converts_to_one_currency(portfolio_path, monkeypatch):
    portfolio.add_position(_pos("AAPL", shares=10, cost=100.0))
    portfolio.add_position(_pos("SAP", "SAP SE", shares=2, cost=100.0))
    monkeypatch.setattr(
        market_data, "quote",
        lambda sym, ttl, name_hint=None: _quote(
            sym, price=150.0, cur="USD" if sym == "AAPL" else "EUR"))
    monkeypatch.setattr(market_data, "fx_rate",
                        lambda base, quote: {"EUR": 1.25, "USD": 1.0}.get(base))
    monkeypatch.setattr(funds, "scan_pool", lambda refresh=False: _pool())
    v = portfolio.view(currency="usd")
    aapl, sap = v["positions"]
    assert aapl["display_value"] == 1500.0
    assert sap["display_value"] == 2 * 150.0 * 1.25     # € -> $
    assert sap["display_cost_basis"] == 125.0
    assert v["totals"]["currency"] == "USD"
    assert v["totals"]["value"] == 1875.0
    assert v["totals"]["complete"] is True
    assert v["totals"]["priced"] == 2 and v["totals"]["missing"] == 0


def test_view_partial_total_still_shows(portfolio_path, monkeypatch):
    portfolio.add_position(_pos("AAPL", shares=10, cost=100.0))
    portfolio.add_position(_pos("VDST", "Vanguard Treasury", shares=5, cost=50.0))
    monkeypatch.setattr(
        market_data, "quote",
        lambda sym, ttl, name_hint=None: _quote(sym, price=150.0)
        if sym == "AAPL" else None)
    monkeypatch.setattr(market_data, "fx_rate", lambda base, quote: 1.0)
    monkeypatch.setattr(funds, "scan_pool", lambda refresh=False: _pool())
    v = portfolio.view(currency="USD")
    assert v["totals"]["value"] == 1500.0         # the priced row still sums
    assert v["totals"]["priced"] == 1
    assert v["totals"]["missing"] == 1
    assert v["totals"]["complete"] is False
    assert v["positions"][1]["display_value"] is None


def test_view_missing_fx_rate_dashes_the_row(portfolio_path, monkeypatch):
    portfolio.add_position(_pos("SAP", "SAP SE", shares=2, cost=100.0))
    monkeypatch.setattr(market_data, "quote",
                        lambda sym, ttl, name_hint=None: _quote(
                            sym, price=150.0, cur="EUR"))
    monkeypatch.setattr(market_data, "fx_rate", lambda base, quote: None)
    monkeypatch.setattr(funds, "scan_pool", lambda refresh=False: _pool())
    v = portfolio.view(currency="USD")
    p = v["positions"][0]
    assert p["fx_missing"] is True
    assert p["display_value"] is None          # never invent a rate
    assert p["value"] == 300.0                 # native number stays for editing
    assert v["totals"]["value"] is None and v["totals"]["missing"] == 1


def test_enrich_flags_a_stale_quote():
    """A stale-cache quote (Yahoo was blocked) still prices the row; the
    UI dates it via the flag instead of calling it live."""
    p = _pos("VDST", "Vanguard U.S. Treasury 0-1 Year Bond UCITS ETF")
    stale = portfolio._enrich(p, {**_quote("VDST", price=59.945),
                                  "stale": True}, None)
    assert stale["live"] is True and stale["price_stale"] is True
    fresh = portfolio._enrich(p, _quote("VDST"), None)
    assert fresh["price_stale"] is False
    dead = portfolio._enrich(p, None, None)
    assert dead["live"] is False and dead["price_stale"] is False


# ---------------------------------------------------------------------------
# The glance (Smart Money tab)
# ---------------------------------------------------------------------------

def test_glance_highlights_aggregate():
    pool = _pool(rows=[
        _row(issuer="ALPHABET INC", n_funds=9, value=2e10),
        _row(issuer="ALPHABET INC", n_funds=9, value=3e10, fund="citadel"),
        _row(issuer="LONELY CO", n_funds=1, value=1e9),   # solo: not crowded
        _row(issuer="GONE CO", n_funds=2, status="exited"),  # exited: not crowded
    ])
    pool["biggest_moves"] = [_row(issuer="MICRON TECHNOLOGY INC",
                                  status="increased", change=2.5)]
    pool["new_this_quarter"] = [_row(issuer="SPACE EXPLORATION TECHN CORP",
                                     status="new")]
    g = portfolio.glance(pool)
    assert g["as_of"] == "2026-06-30"
    assert g["n_funds"] == 1
    assert [c["name"] for c in g["crowded"]] == ["ALPHABET INC"]
    c = g["crowded"][0]
    assert c["n_funds"] == 9
    assert c["value"] == 5e10
    assert [m["name"] for m in g["moves"]] == ["MICRON TECHNOLOGY INC"]
    assert [n["name"] for n in g["new"]] == ["SPACE EXPLORATION TECHN CORP"]


def test_glance_empty_pool_is_fine():
    g = portfolio.glance(_pool())
    assert g["crowded"] == [] and g["moves"] == [] and g["new"] == []
