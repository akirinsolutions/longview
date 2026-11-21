"""Engine math, tested against hand-computed values on synthetic series.
No network here — prices are made up on purpose."""
from datetime import date, timedelta

from app import backtest


def prices(vals, start="2024-01-01"):
    d0 = date.fromisoformat(start)
    return {str(d0 + timedelta(days=i)): v for i, v in enumerate(vals)}


def test_buy_and_hold_known_values():
    # 100 -> 110 -> 100: full round trip = 0% return, 9.1% drawdown
    px = prices([100] * 10 + [110] * 10 + [100] * 10)
    r = backtest.run(px, "buy_and_hold")
    assert abs(r["equity"][-1] - 1.0) < 1e-9
    assert abs(r["metrics"]["total_return"]) < 1e-9
    assert abs(r["metrics"]["cagr"]) < 1e-9
    assert abs(r["metrics"]["max_drawdown"] - (1 - 100 / 110)) < 1e-9
    assert r["trades"] == 1
    assert r["time_in_market"] == 1.0
    # benchmark must equal the strategy for buy-and-hold
    assert r["equity"] == r["benchmark"]


def test_sma_cross_follows_ramp():
    # 10s, then a 5-day ramp 10->30, then flat at 30
    px = prices([10] * 10 + [10, 15, 20, 25, 30] + [30] * 15)
    r = backtest.run(px, "sma_cross", {"fast": 2, "slow": 3})
    # enters on day 11 (12.5 > 11.67), rides the ramp, exits on the first
    # flat day where 20 > 20 is false. Hand-computed final equity = 2.0.
    assert abs(r["equity"][-1] - 2.0) < 1e-6
    assert r["trades"] == 2
    assert abs(r["metrics"]["max_drawdown"]) < 1e-9
    assert abs(r["time_in_market"] - 5 / 30) < 1e-9


def test_buy_the_dip_known_values():
    # flat at 100, dips to 80, recovers to 100
    px = prices([100] * 20 + [90, 80, 100] + [100] * 7)
    r = backtest.run(px, "buy_the_dip", {"drop_pct": 10, "lookback_days": 90})
    # buys at 90, rides 90->80->100: (8/9) * (10/8) = 10/9
    # (the returned series is rounded to 6dp, hence the looser tolerance)
    assert abs(r["equity"][-1] - 10 / 9) < 5e-6
    # worst point: 8/9 while the running peak was still 1.0 -> 11.1% drawdown
    assert abs(r["metrics"]["max_drawdown"] - 1 / 9) < 1e-9
    assert r["trades"] == 2  # one buy, one sell
    # invested on the two days before the sell close; the sell day itself is cash
    assert abs(r["time_in_market"] - 2 / 30) < 1e-9


def test_momentum_flatline_stays_cash():
    px = prices([100] * 250 + [200] * 10)
    r = backtest.run(px, "momentum", {"months": 12})
    # the jump day's return is earned only after the position exists
    assert abs(r["equity"][-1] - 1.0) < 1e-9
    assert r["trades"] == 1


def test_dca_flat_market_breakeven():
    px = {}
    for m in range(6):
        for d in range(1, 11):
            px[f"2024-{m + 1:02d}-{d:02d}"] = 100.0
    r = backtest.run(px, "dca", {"monthly_amount": 1000})
    assert r["mode"] == "dollars"
    assert r["money_in"] == 6000
    assert abs(r["equity"][-1] - 6000) < 1e-6
    assert abs(r["metrics"]["total_return"]) < 1e-9


def test_dca_rising_market_loses_to_lump_sum():
    # classic result: in a steady bull market the early lump sum wins
    px = {}
    for m in range(6):
        price = 100 * 1.1**m
        for d in range(1, 11):
            px[f"2024-{m + 1:02d}-{d:02d}"] = price
    r = backtest.run(px, "dca", {"monthly_amount": 1000})
    assert r["metrics"]["total_return"] > 0.25
    assert r["benchmark"][-1] > r["equity"][-1]
    assert r["metrics"]["total_return"] < r["benchmark_metrics"]["total_return"]


def test_metrics_max_drawdown_and_cagr():
    dates = ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]
    m = backtest._metrics([1, 1.2, 0.9, 1.5], dates)
    assert abs(m["max_drawdown"] - 0.25) < 1e-9  # peak 1.2 -> trough 0.9
    dates_y = ["2023-01-01", "2024-01-01"]
    m2 = backtest._metrics([1, 2], dates_y)
    assert abs(m2["cagr"] - 1.0) < 0.01  # doubled in ~one year (365d/365.25y)
    m3 = backtest._metrics([1, 1.01, 1.0201], ["2024-01-01", "2024-01-02", "2024-01-03"])
    assert m3["sharpe"] is None  # zero volatility -> undefined


def test_rejects_tiny_history():
    try:
        backtest.run(prices([100, 101, 99]), "buy_and_hold")
        raise AssertionError("should have raised")
    except ValueError:
        pass


def test_verdict_for_buy_and_hold_admits_the_overlap():
    # A pure buy-and-hold backtest has an identical benchmark line; the
    # verdict must say the lines overlap, not that one of them "won".
    px = prices([100] * 10 + [110] * 10 + [121] * 10)
    r = backtest.run(px, "buy_and_hold")
    v = backtest.verdict(r)
    assert "overlap" in v
    assert "beating" not in v
    assert "doing nothing won" not in v
