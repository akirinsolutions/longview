"""The backtest engine.

The honest rules:
- Signals are acted on at the *close* of the day they are computed, so a
  strategy never cheats by seeing tomorrow's price (no lookahead).
- Prices come split- and dividend-adjusted, so a dividend doesn't look
  like a crash and a stock split doesn't look like a miracle.
- Optional trading cost per trade, in basis points (1 bp = 0.01%).
- The benchmark is always buy-and-hold of the same symbol over the same
  window. It is the only comparison that makes sense: "would doing
  nothing have beaten this?"
"""
from __future__ import annotations

import math
from datetime import date

TRADING_DAYS_PER_YEAR = 252


def _to_date(s: str) -> date:
    return date.fromisoformat(s)


def _num(params: dict | None, key: str, default: float) -> float:
    if not params:
        return float(default)
    try:
        v = float(params.get(key, default))
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(v) or math.isinf(v):
        return float(default)
    return v


def _sma_series(values: list[float], window: int) -> list[float | None]:
    """Simple moving average, same length as input; None until enough data."""
    out: list[float | None] = [None] * len(values)
    if window <= 0:
        return out
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            out[i] = running / window
    return out


# ---------------------------------------------------------------------------
# Rules: each turns a price series into a per-day "target weight"
# (0 = all cash, 1 = fully invested). The weight held from close t to t+1
# is the weight computed at close t — that's what keeps lookahead out.
# ---------------------------------------------------------------------------

def _buy_and_hold_weights(px: list[float]) -> list[float]:
    return [1.0] * len(px)


def _sma_cross_weights(px: list[float], params: dict) -> list[float]:
    fast = max(1, int(_num(params, "fast", 50)))
    slow = max(fast + 1, int(_num(params, "slow", 200)))
    f = _sma_series(px, fast)
    s = _sma_series(px, slow)
    out = []
    for i in range(len(px)):
        if f[i] is None or s[i] is None:
            out.append(0.0)
        else:
            out.append(1.0 if f[i] > s[i] else 0.0)
    return out


def _buy_the_dip_weights(px: list[float], params: dict) -> list[float]:
    """Buy when price falls `drop_pct`% below its recent high; sell once it
    gets back to that high (or after `max_hold` trading days, whichever first)."""
    drop_pct = min(max(_num(params, "drop_pct", 8.0), 0.5), 99.0)
    lookback = max(5, int(_num(params, "lookback_days", 90)))
    max_hold = max(10, int(_num(params, "max_hold_days", 252)))

    w = [0.0] * len(px)
    in_pos = False
    target = 0.0
    entry_i = 0
    for i in range(len(px)):
        if in_pos:
            w[i] = 1.0
            if px[i] >= target or i - entry_i >= max_hold:
                in_pos = False
                w[i] = 0.0  # sold at this close
                target = 0.0
        if not in_pos:
            lo = max(0, i - lookback + 1)
            high = max(px[lo : i + 1])
            if high > 0 and px[i] <= high * (1.0 - drop_pct / 100.0):
                in_pos = True
                target = high
                entry_i = i
                w[i] = 1.0
    return w


def _momentum_weights(px: list[float], params: dict) -> list[float]:
    """Classic 12-month momentum: long when the price is above where it was
    `months` months ago, flat (cash) otherwise."""
    months = min(max(_num(params, "months", 12.0), 1.0), 120.0)
    lookback = max(1, int(months * TRADING_DAYS_PER_YEAR / 12.0))
    out = []
    for i in range(len(px)):
        if i < lookback:
            out.append(0.0)
        else:
            base = px[i - lookback]
            out.append(1.0 if base > 0 and px[i] > base else 0.0)
    return out


def _rule_weights(rule: str, px: list[float], params: dict) -> list[float]:
    if rule == "buy_and_hold":
        return _buy_and_hold_weights(px)
    if rule == "sma_cross":
        return _sma_cross_weights(px, params)
    if rule == "buy_the_dip":
        return _buy_the_dip_weights(px, params)
    if rule == "momentum":
        return _momentum_weights(px, params)
    raise ValueError(f"Unknown strategy rule '{rule}'")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _metrics(equity: list[float], dates: list[str]) -> dict:
    """Total return, CAGR, max drawdown, volatility, Sharpe (rf = 0)."""
    if len(equity) < 2 or equity[0] <= 0:
        return {"total_return": None, "cagr": None, "max_drawdown": None,
                "volatility": None, "sharpe": None, "years": None}

    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity))
            if equity[i - 1] > 0]
    total = equity[-1] / equity[0] - 1.0
    years = (_to_date(dates[-1]) - _to_date(dates[0])).days / 365.25

    cagr = None
    if equity[-1] > 0 and years > 0.05:
        cagr = (equity[-1] / equity[0]) ** (1.0 / years) - 1.0

    peak = -1.0
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, 1.0 - v / peak)

    vol = 0.0
    sharpe = None
    if rets:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        sd = math.sqrt(var)
        vol = sd * math.sqrt(TRADING_DAYS_PER_YEAR)
        sharpe = (mean / sd) * math.sqrt(TRADING_DAYS_PER_YEAR) if sd > 0 else None

    return {"total_return": total, "cagr": cagr, "max_drawdown": mdd,
            "volatility": vol, "sharpe": sharpe, "years": years}


def _bench_equity(px: list[float]) -> list[float]:
    return [p / px[0] if px[0] > 0 else 1.0 for p in px]


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

def run(prices: dict[str, float], rule: str, params: dict | None = None) -> dict:
    """Run a strategy over a price history.

    prices: {iso_date: adjusted_close}
    rule: one of buy_and_hold / sma_cross / buy_the_dip / momentum / dca
    params: rule-specific (see the rule functions)
    """
    params = dict(params or {})
    dates = sorted(prices)
    px = [prices[d] for d in dates]
    if len(px) < 30:
        raise ValueError("Not enough price data to backtest (need at least ~30 trading days)")

    if rule == "dca":
        return _run_dca(dates, px, params)

    weights = _rule_weights(rule, px, params)
    cost_bps = min(max(_num(params, "cost_bps", 0.0), 0.0), 100.0)

    equity = [1.0]
    for i in range(1, len(px)):
        w_prev = weights[i - 1]
        r = px[i] / px[i - 1] - 1.0 if px[i - 1] > 0 else 0.0
        turn = abs(weights[i] - weights[i - 1])
        net = 1.0 + w_prev * r - turn * cost_bps / 10_000.0
        equity.append(max(1e-12, equity[-1] * net))

    trades = sum(1 for i in range(1, len(px)) if weights[i] != weights[i - 1])
    if weights[0] > 0:
        trades += 1  # the initial buy counts as a trade

    bench = _bench_equity(px)
    return {
        "mode": "unit",
        "rule": rule,
        "params": params,
        "dates": dates,
        "equity": [round(v, 6) for v in equity],
        "benchmark": [round(v, 6) for v in bench],
        "metrics": _metrics(equity, dates),
        "benchmark_metrics": _metrics(bench, dates),
        "trades": trades,
        "time_in_market": sum(weights) / len(weights),
    }


def _run_dca(dates: list[str], px: list[float], params: dict) -> dict:
    """Dollar-cost averaging: invest a fixed amount at the first close of each
    calendar month. Benchmark: one lump sum of the same total, invested day one.
    Equity is expressed in actual dollars (mode = "dollars")."""
    monthly = max(1.0, _num(params, "monthly_amount", 1000.0))

    cash = 0.0
    units = 0.0
    equity: list[float] = []
    last_month: str | None = None
    contributions = 0
    for i, d in enumerate(dates):
        month = d[:7]
        if month != last_month:
            if px[i] > 0:
                units += monthly / px[i]
                contributions += 1
            last_month = month
        equity.append(units * px[i])

    total_in = monthly * contributions
    if total_in <= 0 or contributions == 0:
        raise ValueError("The backtest window is too short for monthly investing")

    bench = [total_in * (p / px[0]) if px[0] > 0 else total_in for p in px]
    bm = _metrics(bench, dates)

    years = (_to_date(dates[-1]) - _to_date(dates[0])).days / 365.25
    final = equity[-1]
    cagr = (final / total_in) ** (1.0 / years) - 1.0 if years > 0.05 else None

    # drawdown on the portfolio curve
    peak = -1.0
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, 1.0 - v / peak)

    metrics = {"total_return": final / total_in - 1.0, "cagr": cagr,
               "max_drawdown": mdd, "volatility": bm.get("volatility"),
               "sharpe": bm.get("sharpe"), "years": years}

    return {
        "mode": "dollars",
        "rule": "dca",
        "params": params,
        "dates": dates,
        "equity": [round(v, 2) for v in equity],
        "benchmark": [round(v, 2) for v in bench],
        "metrics": metrics,
        "benchmark_metrics": bm,
        "trades": contributions,
        "time_in_market": 1.0,
        "money_in": total_in,
    }


# ---------------------------------------------------------------------------
# Plain-English verdict
# ---------------------------------------------------------------------------

def _pct(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "?"
    return f"{x * 100:+.{digits}f}%"


def _money(x: float) -> str:
    return f"${x:,.0f}"


def verdict(res: dict) -> str:
    """A short, warm, jargon-free summary of what happened."""
    m = res["metrics"]
    bm = res["benchmark_metrics"]
    years = m.get("years") or 0
    yrs = (f"{int(round(years))} years" if years and years > 1
           else "less than a year")

    if res["mode"] == "dollars":
        final = res["equity"][-1]
        money_in = res.get("money_in", 0)
        bfinal = res["benchmark"][-1]
        best = "your steady saving" if final >= bfinal else "the lump sum"
        return (
            f"By putting in a fixed amount every month for {yrs}, you'd end up with "
            f"{_money(final)}. The lump sum of the same total, invested all at once on "
            f"day one, would be {_money(bfinal)}. Here {best} came out ahead — but the "
            f"gap is mostly luck: with a steady saver, investing early is only an "
            f"advantage if prices kept going up. Past performance is the one thing "
            f"that is never guaranteed to repeat."
        )

    total = m.get("total_return")
    btotal = bm.get("total_return")
    mdd = m.get("max_drawdown") or 0.0
    bmdd = bm.get("max_drawdown") or 0.0

    if total is None or btotal is None:
        return "Not enough data to call it."

    if abs(total - btotal) < 1e-9:
        # The strategy *is* buy-and-hold: the two lines are identical by
        # design, and saying one "won" would be a lie.
        head = (
            f"Over {yrs}, this is buy-and-hold, so the two lines overlap "
            f"exactly: both made {_pct(total)} on the same thing."
        )
    elif total > btotal:
        head = (
            f"Over {yrs}, this strategy made {_pct(total)} — beating buy-and-hold's "
            f"{_pct(btotal)} on the same thing."
        )
    else:
        head = (
            f"Over {yrs}, doing nothing won: buy-and-hold made {_pct(btotal)} while "
            f"this strategy made {_pct(total)}."
        )

    risk = (
        f"At its worst, the strategy was down {_pct(-mdd)} from its peak "
        f"(buy-and-hold was down {_pct(-bmdd)})."
    )
    effort = (
        f"It traded {res.get('trades', 0)} times and was invested "
        f"{res['time_in_market'] * 100:.0f}% of the time."
    )
    tail = (
        "The honest caveat: a backtest is a replay of one market, not a promise. "
        "The same rules in a different decade could do the opposite."
    )
    return f"{head} {risk} {effort} {tail}"
