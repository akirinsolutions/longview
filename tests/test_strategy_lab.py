"""The strategy-lab engine, tested against hand-computed values on
synthetic series. No network and no model: the decider is the
deterministic stand-in (or a scripted one), the researcher is a stub —
the RAM rule. Every expectation below is worked out by hand.

The calendar is *every calendar day* starting Monday 2020-01-06, so
hand-counting weeks is easy: Mondays fall on indices 0, 7, 14, 21, …
"""
from datetime import date, timedelta

from app import strategy_lab


def series(vals, start="2020-01-06"):
    d0 = date.fromisoformat(start)
    return {str(d0 + timedelta(days=i)): v for i, v in enumerate(vals)}


def daterange(n, start="2020-01-06"):
    d0 = date.fromisoformat(start)
    return [str(d0 + timedelta(days=i)) for i in range(n)]


def plan(symbols, **kw):
    return strategy_lab.make_plan(symbols, **kw)


# ---------------------------------------------------------------------------
# Plan normalization
# ---------------------------------------------------------------------------

def test_make_plan_defaults():
    p = plan(["aapl", "MSFT"])
    assert p["symbols"] == ["AAPL", "MSFT"]
    assert p["frequency"] == "month"
    assert p["triggers"] == []
    assert p["targets"] == {"AAPL": 0.5, "MSFT": 0.5}  # equal weight
    assert p["on_drop"] == "hold"
    assert p["exit_pct"] is None
    assert p["research"] is False
    assert set(p) >= {"symbols", "start_cash", "frequency", "triggers",
                      "targets", "on_drop", "add_weight", "exit_pct",
                      "research", "text", "summary"}


def test_make_plan_validation():
    def bad(fn):
        try:
            fn()
            return None
        except ValueError as e:
            return str(e)

    assert "at least one ticker" in bad(lambda: plan([]))
    assert "valid ticker" in bad(lambda: plan(["A" * 9]))
    assert "valid ticker" in bad(lambda: plan(["  "]))
    assert "up to 10 tickers" in bad(lambda: plan([f"T{i}" for i in range(11)]))
    assert "start cash" in bad(lambda: plan(["SPY"], start_cash=5))
    assert "start cash" in bad(lambda: plan(["SPY"], start_cash="much"))
    assert "frequency" in bad(lambda: plan(["SPY"], frequency="biweekly"))
    assert "drop %" in bad(lambda: plan(["SPY"], triggers=[{"kind": "drop_from_peak", "pct": 0}]))
    assert "drop %" in bad(lambda: plan(["SPY"], triggers=[{"kind": "drop_from_peak", "pct": 91}]))
    assert "kind" in bad(lambda: plan(["SPY"], triggers=[{"kind": "gap", "pct": 10}]))
    assert "lookback" in bad(lambda: plan(["SPY"], triggers=[{"kind": "drop_from_peak", "pct": 10, "lookback_days": 2}]))
    assert "re-arm" in bad(lambda: plan(["SPY"], triggers=[{"kind": "drop_from_peak", "pct": 10, "rearm": "whenever"}]))
    assert "not in the ticker list" in bad(lambda: plan(["SPY"], targets={"TSLA": 0.5}))
    assert "weight" in bad(lambda: plan(["SPY"], targets={"SPY": 0} | {"AAPL": 0.5}))
    assert "on-drop" in bad(lambda: plan(["SPY"], on_drop="explode"))
    assert "add-weight" in bad(lambda: plan(["SPY"], add_weight=0.9))
    assert "exit %" in bad(lambda: plan(["SPY"], exit_pct=0))


def test_plan_dedupes_and_uppercases():
    p = plan(["aapl", "AAPL", "msft"])
    assert p["symbols"] == ["AAPL", "MSFT"]


# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------

def test_decision_days_schedules():
    dates = daterange(100)  # Mon 2020-01-06 .. Tue 2020-04-14
    week = strategy_lab.decision_days(dates, "week")
    two = strategy_lab.decision_days(dates, "two_weeks")
    month = strategy_lab.decision_days(dates, "month")
    quarter = strategy_lab.decision_days(dates, "quarter")

    assert week[0] == 0 and len(week) == 15          # the Mondays
    assert week == list(range(0, 100, 7))
    assert two[0] == 0 and len(two) == 8             # 14-day periods
    assert two == list(range(0, 100, 14))
    # the first *calendar day* of each period (this synthetic calendar
    # has a "trading" day every day): Jan 6, Feb 1, Mar 1, Apr 1
    assert month == [0, 26, 55, 86]
    assert quarter == [0, 86]                        # Jan 6, Apr 1


def test_first_day_always_a_decision_day():
    # ten days all inside January, so the only period boundary is day 0
    assert strategy_lab.decision_days(daterange(10), "month") == [0]


# ---------------------------------------------------------------------------
# The engine, by hand
# ---------------------------------------------------------------------------

def test_initial_deploy_and_flat_run():
    px = {"A": series([100] * 40), "B": series([200] * 40)}
    p = plan(["A", "B"], frequency="week")  # equal weight, no triggers
    r = strategy_lab.simulate(p, px, strategy_lab.decide_plan)

    # day 0: 50k each -> 500 @100 + 250 @200; everything flat after that
    assert r["equity"] == [100_000.0] * 40
    assert r["metrics"]["total_return"] == 0.0
    assert r["trades"] == 2
    assert r["decisions"] == 6                       # the six Mondays
    assert r["time_in_market"] == 1.0
    assert len(r["log"][0]["trades"]) == 2
    # with no triggers/exit the strategy is buy-and-hold of the universe
    for e, b in zip(r["equity"], r["benchmark"]):
        assert abs(e - b) < 0.01


def test_drop_trigger_add_and_rearm():
    px = {"A": series([100] * 10 + [79] * 10 + [81] * 10 + [79] * 10)}
    p = plan(["A"], targets={"A": 0.5}, frequency="week",
             triggers=[{"kind": "drop_from_peak", "pct": 20, "lookback_days": 252,
                        "rearm": "recover"}],
             on_drop="add", add_weight=0.10)
    r = strategy_lab.simulate(p, px, strategy_lab.decide_plan)

    # day 0: 500 @100, $50k cash
    # day 10 (Jan 16): -21% from peak -> add 10% of $39.5k = $3,950 -> +50u
    #   550 units; while 79 <= 80 the trigger stays disarmed
    # day 20: 81 > 80 -> re-arms
    # day 30 (Feb 5): -21% again -> add 10% of $43.45k = $4,345 -> +55u
    # end: 605 @79 + $41,705 cash = $89,500
    assert r["equity"][-1] == 89_500.0
    assert r["trades"] == 3
    assert r["decisions"] == 8                      # 6 Mondays + 2 trigger days
    assert r["time_in_market"] == 1.0
    by_date = {e["date"]: e for e in r["log"]}
    assert len(by_date["2020-01-16"]["trades"]) == 1
    assert by_date["2020-01-16"]["trades"][0]["side"] == "buy"
    assert len(by_date["2020-02-05"]["trades"]) == 1
    # the no-trigger Mondays did nothing
    assert by_date["2020-01-13"]["trades"] == []


def test_drop_from_cost_sell_all():
    px = {"A": series([100] * 10 + [85] * 30)}
    p = plan(["A"], targets={"A": 1.0}, frequency="quarter",
             triggers=[{"kind": "drop_from_cost", "pct": 15}],
             on_drop="sell_all")
    r = strategy_lab.simulate(p, px, strategy_lab.decide_plan)

    # day 0: 1,000 @100. day 10: exactly -15% from cost -> sold at 85.
    # No position afterwards; the quarterly top-up must not buy it back.
    assert r["equity"][-1] == 85_000.0
    assert abs(r["metrics"]["total_return"] - (-0.15)) < 1e-9
    assert r["trades"] == 2
    assert r["decisions"] == 2
    assert r["time_in_market"] == 0.25              # held days 0-9 only


def test_exit_pct_take_profit():
    px = {"A": series([100 + i for i in range(30)] + [130] * 10)}
    p = plan(["A"], targets={"A": 1.0}, frequency="week", exit_pct=25)
    r = strategy_lab.simulate(p, px, strategy_lab.decide_plan)

    # the +25% exit is checked on the weekly decision days only:
    # Jan 28 (close 128, +28%) is the first that qualifies. Sold there;
    # the next check (Feb 10) must not buy the winner back.
    assert r["equity"][-1] == 128_000.0
    assert abs(r["metrics"]["total_return"] - 0.28) < 1e-9
    assert r["trades"] == 2
    assert r["time_in_market"] == 0.7               # held days 0-27 of 40
    by_date = {e["date"]: e for e in r["log"]}
    assert len(by_date["2020-02-03"]["trades"]) == 1
    assert by_date["2020-02-03"]["trades"][0]["side"] == "sell"
    assert "exited" in by_date["2020-02-03"]["note"]
    assert by_date["2020-02-10"]["trades"] == []   # no buy-back


def test_cost_bps_charged_on_buys():
    px = {"A": series([100] * 40)}
    p = plan(["A"], targets={"A": 1.0})
    r = strategy_lab.simulate(p, px, strategy_lab.decide_plan, cost_bps=10)

    # $100k buy at 10 bps: $100 fee -> 999 units. The curve's day-0 point
    # is post-trade ($99,900), so the fee shows up in absolute dollars,
    # not in total return — the same convention as the old engine.
    assert r["equity"][0] == 99_900.0
    assert r["equity"][-1] == 99_900.0
    assert r["metrics"]["total_return"] == 0.0
    assert r["cost_paid"] == 100.0
    assert r["trades"] == 1


def test_drawdown_hand_computed():
    px = {"A": series([100] * 10 + [90] + [100] * 19)}
    p = plan(["A"], targets={"A": 1.0})
    r = strategy_lab.simulate(p, px, strategy_lab.decide_plan)

    assert r["metrics"]["total_return"] == 0.0
    assert abs(r["metrics"]["max_drawdown"] - 0.10) < 1e-9


def test_benchmark_equal_weight_of_universe():
    px = {"A": series([100 + 100 * i / 19 for i in range(20)]),   # 100 -> 200
          "B": series([100 - 50 * i / 19 for i in range(20)])}    # 100 -> 50
    p = plan(["A", "B"], frequency="quarter")  # one decision: deploy day 0
    r = strategy_lab.simulate(p, px, strategy_lab.decide_plan)

    assert r["equity"][-1] == 125_000.0         # 500*200 + 500*50
    assert abs(r["metrics"]["total_return"] - 0.25) < 1e-9
    for e, b in zip(r["equity"], r["benchmark"]):
        assert abs(e - b) < 0.01
    assert r["metrics"] == r["benchmark_metrics"]


def test_research_injection_and_failures():
    px = {"A": series([100] * 40)}

    calls = []
    def researcher(ds, symbols, pl):
        calls.append((ds, tuple(symbols)))
        return {"A": f"note {ds}"}

    p = plan(["A"], targets={"A": 1.0}, frequency="week", research=True)
    r = strategy_lab.simulate(p, px, strategy_lab.decide_plan, researcher=researcher)
    assert len(calls) == r["decisions"] == 6            # decision days only
    for e in r["log"]:
        assert e["research"] == {"A": f"note {e['date']}"}

    def broken(ds, symbols, pl):
        raise ValueError("boom")
    r2 = strategy_lab.simulate(p, px, strategy_lab.decide_plan, researcher=broken)
    for e in r2["log"]:
        assert e["research"] == {}
        assert "research skipped" in e["note"]
    # research failing never changes the math
    assert r2["equity"] == r["equity"]

    calls.clear()
    p_noresearch = plan(["A"], targets={"A": 1.0})  # research flag off
    strategy_lab.simulate(p_noresearch, px, strategy_lab.decide_plan, researcher=researcher)
    assert calls == []


def test_context_is_no_lookahead():
    px = {"A": series([100 + i for i in range(25)])}
    p = plan(["A"], targets={"A": 1.0}, frequency="week")
    seen = []

    def spy(context):
        seen.append(context)
        # deploy once, on the first-ever day; watch afterwards
        if not context["portfolio"]["positions"] and not context["ever_held"]:
            return {"trades": [{"symbol": "A", "side": "buy", "weight": 1.0}],
                    "note": "initial deploy"}
        return {"trades": [], "note": "watching"}

    strategy_lab.simulate(p, px, spy)

    dates = set(px["A"])
    assert {c["date"] for c in seen} <= dates
    for c in seen:
        i = daterange(25).index(c["date"])
        past = [px["A"][d] for d in daterange(i + 1)]
        assert c["prices"]["A"]["close"] == past[-1]
        assert c["prices"]["A"]["1w"] == past[-6] if len(past) > 5 else past[0]
        assert c["prices"]["A"]["52w_high"] == max(past)
        assert c["prices"]["A"]["52w_low"] == min(past)
        # the portfolio is marked on the same close (empty on day 0,
        # where the context is built before the deploy trade applies)
        if c["portfolio"]["positions"]:
            pos = c["portfolio"]["positions"][0]
            assert pos["value"] == pos["qty"] * past[-1]


def test_invalid_trades_are_dropped_not_fatal():
    px = {"A": series([100] * 40)}
    p = plan(["A"], targets={"A": 1.0})

    def overreacher(context):
        return {"trades": [
            {"symbol": "ZZZ", "side": "buy", "weight": 0.5},   # outside universe
            {"symbol": "A", "side": "buy", "weight": 5.0},     # weight out of range
            {"symbol": "A", "side": "fly", "weight": 0.5},     # not a side
            {"symbol": "A", "side": "buy", "weight": 0.1},     # the only legal one
        ], "note": "x"}

    r = strategy_lab.simulate(p, px, overreacher)
    assert len(r["log"][0]["trades"]) == 1
    # day 0: 100 @100 = $10k, $90k cash -> equity unchanged
    assert r["equity"][0] == 100_000.0

    def garbage(context):
        return "hello"  # not even the right shape

    r2 = strategy_lab.simulate(p, px, garbage)
    assert r2["equity"][-1] == 100_000.0
    assert all(e["trades"] == [] for e in r2["log"])
    assert any("unreadable" in e["note"] for e in r2["log"])


def test_deciding_decider_that_raises_never_kills_the_run():
    px = {"A": series([100] * 40)}
    p = plan(["A"], targets={"A": 1.0})

    def explodes(context):
        raise RuntimeError("the model died")

    r = strategy_lab.simulate(p, px, explodes)
    assert r["equity"] == [100_000.0] * 40
    assert all("decider failed" in e["note"] for e in r["log"])


def test_start_end_slice():
    px = {"A": series([100 + i for i in range(60)])}
    p = plan(["A"], targets={"A": 1.0})
    r = strategy_lab.simulate(p, px, strategy_lab.decide_plan,
                              start=daterange(60)[5], end=daterange(60)[30])
    assert len(r["dates"]) == 26
    assert r["dates"][0] == daterange(60)[5]


def test_engine_refuses_bogus_inputs():
    px_short = {"A": series([100] * 5)}
    p = plan(["A"])
    try:
        strategy_lab.simulate(p, px_short, strategy_lab.decide_plan)
        assert False, "should have raised"
    except ValueError as e:
        assert "too short" in str(e)

    px_missing = {"A": series([100] * 40)}  # plan wants B too
    try:
        strategy_lab.simulate(plan(["A", "B"]), px_missing, strategy_lab.decide_plan)
        assert False, "should have raised"
    except ValueError as e:
        assert "no price history" in str(e)

    a = series([100] * 40)
    b = series([100] * 40, start="2020-03-01")  # disjoint (A ends Feb 14)
    try:
        strategy_lab.simulate(plan(["A", "B"]), {"A": a, "B": b}, strategy_lab.decide_plan)
        assert False, "should have raised"
    except ValueError as e:
        assert "no trading days" in str(e)


def test_same_input_same_output():
    px = {"A": series([100] * 10 + [79] * 10 + [81] * 10 + [79] * 10)}
    p = plan(["A"], targets={"A": 0.5},
             triggers=[{"kind": "drop_from_peak", "pct": 20}],
             on_drop="add", add_weight=0.10)
    r1 = strategy_lab.simulate(p, px, strategy_lab.decide_plan)
    r2 = strategy_lab.simulate(p, px, strategy_lab.decide_plan)
    assert r1 == r2
