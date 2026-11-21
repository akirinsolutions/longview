"""Strategy lab: a portfolio simulator driven by a plan.

The engine is pure. Three seams are injectable — the decision-maker,
the research layer, and the prices — so the same ``simulate()`` runs a
language model in production and a deterministic stand-in in the tests
(never the two at once, and never a model from a test). Given those
three, the result is fully determined: the equity curve, the metrics,
an equal-weight buy-and-hold benchmark of the same universe, and a
per-decision log of what the sim saw, researched, did, and why.

Nothing here calls a URL or a model at import time. The date-gated web
research layer lives next door in ``app/research.py``; the LLM seam
imports ``app.risk`` lazily, only inside the interpreter and decider
functions, and is patched in the tests — so the engine and the
deterministic reader stay fully offline.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date

from app import backtest

FREQUENCIES = ("week", "two_weeks", "month", "quarter")
TRIGGER_KINDS = ("drop_from_cost", "drop_from_peak")
ON_DROP_ACTIONS = ("hold", "add", "sell_half", "sell_all")
REARM_MODES = ("recover", "periodic")

MAX_SYMBOLS = 10
MAX_DECISION_LOG = 4000  # a 20-year weekly sim is ~1,050 days; this never bites


def _pct(x: float) -> float:
    return round(x, 4)


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

def make_plan(symbols, start_cash: float = 100_000.0, frequency: str = "month",
              triggers: list[dict] | None = None, targets: dict | None = None,
              on_drop: str = "hold", add_weight: float = 0.10,
              exit_pct: float | None = None, research: bool = False,
              text: str = "", summary: str = "",
              names: dict | None = None) -> dict:
    """Normalize and validate a plan. Raises ValueError in plain English.

    The machine-readable half of the strategy: who, how much, how often
    to check, which drops matter, what each one does. ``text`` keeps the
    user's own words — an LLM decider re-reads them at every decision.
    """
    syms = []
    for s in symbols or []:
        s = str(s).strip().upper()
        if not s or len(s) > 8 or not all(c.isalnum() or c == "." for c in s):
            raise ValueError(f"\"{s}\" is not a valid ticker — letters, digits and dots, up to 8")
        if s not in syms:
            syms.append(s)
    if not syms:
        raise ValueError("name at least one ticker to trade")
    if len(syms) > MAX_SYMBOLS:
        raise ValueError(f"up to {MAX_SYMBOLS} tickers per backtest")

    try:
        start_cash = float(start_cash)
    except (TypeError, ValueError):
        raise ValueError("start cash must be a number")
    if not (1_000 <= start_cash <= 100_000_000):
        raise ValueError("start cash must be between $1,000 and $100,000,000")

    if frequency not in FREQUENCIES:
        raise ValueError(f"check frequency must be one of: {', '.join(FREQUENCIES)}")

    trigs = []
    for t in triggers or []:
        kind = t.get("kind")
        if kind not in TRIGGER_KINDS:
            raise ValueError(f"a trigger's kind must be one of: {', '.join(TRIGGER_KINDS)}")
        pct = float(t.get("pct", 0))
        if not (1 <= pct <= 90):
            raise ValueError("a trigger's drop % must be between 1 and 90")
        lookback = int(t.get("lookback_days", 252))
        if not (5 <= lookback <= 504):
            raise ValueError("a trigger's lookback must be 5–504 days")
        rearm = t.get("rearm", "recover")
        if rearm not in REARM_MODES:
            raise ValueError(f"a trigger's re-arm must be one of: {', '.join(REARM_MODES)}")
        trigs.append({"kind": kind, "pct": pct, "lookback_days": lookback,
                      "rearm": rearm})

    tgts = {}
    for s, w in (targets or {}).items():
        s = str(s).strip().upper()
        if s not in syms:
            raise ValueError(f"target {s} is not in the ticker list")
        w = float(w)
        if not (0 < w <= 1):
            raise ValueError("each target weight must be between 0 and 1")
        tgts[s] = w
    if not tgts:
        w = round(1.0 / len(syms), 6)
        tgts = {s: w for s in syms}

    nm = {}
    for k, v in (names or {}).items():
        k = str(k).strip().upper()
        v = str(v or "").strip()
        if k not in syms:
            raise ValueError(f"research title for {k} — {k} is not in the ticker list")
        if not v or len(v) > 120:
            raise ValueError(f"the research title for {k} must be 1-120 characters")
        nm[k] = v

    if on_drop not in ON_DROP_ACTIONS:
        raise ValueError(f"the on-drop action must be one of: {', '.join(ON_DROP_ACTIONS)}")
    add_weight = float(add_weight)
    if not (0.01 <= add_weight <= 0.5):
        raise ValueError("add-weight on a drop must be between 1% and 50%")
    if exit_pct is not None:
        exit_pct = float(exit_pct)
        if not (1 <= exit_pct <= 500):
            raise ValueError("exit % must be between 1 and 500")

    return {
        "symbols": syms,
        "start_cash": start_cash,
        "frequency": frequency,
        "triggers": trigs,
        "targets": tgts,
        "on_drop": on_drop,
        "add_weight": add_weight,
        "exit_pct": exit_pct,
        "research": bool(research),
        "text": (text or "")[:4000],
        "summary": (summary or "")[:500],
        "names": nm,
    }


# ---------------------------------------------------------------------------
# Schedule: which days are decision points
# ---------------------------------------------------------------------------

def _period_key(d: date, frequency: str) -> str:
    if frequency == "week":
        y, w, _ = d.isocalendar()
        return f"W{y}-{w}"
    if frequency == "two_weeks":
        y, w, _ = d.isocalendar()
        return f"TW{y}-{w // 2}"
    if frequency == "month":
        return f"M{d.year}-{d.month}"
    return f"Q{d.year}-{(d.month - 1) // 3 + 1}"  # quarter


def decision_days(dates: list[str], frequency: str) -> list[int]:
    """Indexes (into ``dates``) of the first trading day of each period.

    The window's first day is always a decision day — that is where the
    initial deployment happens.
    """
    idx, last_key = [], None
    for i, ds in enumerate(dates):
        key = _period_key(date.fromisoformat(ds), frequency)
        if key != last_key:
            idx.append(i)
            last_key = key
    return idx


def _window_stats(closes_up_to_now: list[float]) -> dict:
    """Close plus fixed backward-looking windows and a 52w-ish range.

    Every figure uses only closes up to and including the current day.
    """
    last = closes_up_to_now[-1]

    def back(n: int) -> float:
        return closes_up_to_now[0] if len(closes_up_to_now) <= n else closes_up_to_now[-1 - n]

    hist = closes_up_to_now[-252:]
    return {
        "close": last,
        "1w": back(5), "1m": back(21), "3m": back(63), "1y": back(252),
        "52w_high": max(hist), "52w_low": min(hist),
    }


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

def simulate(plan: dict, prices: dict[str, dict[str, float]],
             decider, researcher=None, cost_bps: float = 0.0,
             start: str | None = None, end: str | None = None) -> dict:
    """Replay the window day by day and return the full result.

    ``prices`` is symbol -> {iso_date: close}. The calendar is the
    intersection of the symbols' dates, so every symbol is tradable on
    every day. ``decider`` is ``context -> {"trades": [...], "note": ...}``
    and is only called on decision days — the periodic ones *and* any day
    a trigger fires. ``researcher``, if given and ``plan["research"]`` is
    set, is ``date_str, symbols, plan -> dict`` and is only called on
    decision days; anything it raises is swallowed and reported, never
    fatal.

    Per day, in order: re-arm any disarmed triggers, evaluate the
    triggers on held positions, act on a decision day (research, decide,
    apply trades at the close), then mark the portfolio to market.
    """
    symbols = plan["symbols"]
    for s in symbols:
        if s not in prices or not prices[s]:
            raise ValueError(f"no price history for {s}")

    common = sorted(set.intersection(*(set(prices[s]) for s in symbols)))
    if not common:
        raise ValueError("the tickers share no trading days in the window")
    if start:
        common = [d for d in common if d >= start]
    if end:
        common = [d for d in common if d <= end]
    if len(common) < 10:
        raise ValueError("the shared history is too short to run — need at least 10 days")

    cost = max(0.0, float(cost_bps)) / 10_000.0
    per_symbol = {s: [prices[s][d] for d in common] for s in symbols}

    port = {
        "cash": float(plan["start_cash"]),
        "qty": {s: 0.0 for s in symbols},
        "cost_basis": {s: 0.0 for s in symbols},   # average cost per unit
        "bought_day": {s: None for s in symbols},
    }
    armed = [[True] * len(plan["triggers"]) for _ in range(len(symbols))]

    eq, bench, dates = [], [], []
    bench_units: dict[str, float] = {}
    ever_held = False
    log = []
    n_decisions = 0
    n_trades = 0
    days_in_market = 0
    cost_paid = 0.0
    decided_at = set(decision_days(common, plan["frequency"]))

    for i, ds in enumerate(common):
        d = date.fromisoformat(ds)
        row = {s: per_symbol[s][i] for s in symbols}
        closes = {s: per_symbol[s][: i + 1] for s in symbols}

        # Benchmark: equal-weight buy-and-hold, fixed at the first day.
        if i == 0:
            alloc = plan["start_cash"] / len(symbols)
            for s in symbols:
                bench_units[s] = alloc * (1 - cost) / row[s]
        bench.append(sum(bench_units[s] * row[s] for s in symbols))

        # --- re-arm phase (a fresh position re-arms all of its triggers) ---
        for si, s in enumerate(symbols):
            if port["qty"][s] <= 0:
                for ti in range(len(plan["triggers"])):
                    armed[si][ti] = True
                continue
            for ti, t in enumerate(plan["triggers"]):
                if armed[si][ti]:
                    continue
                if t["rearm"] == "periodic" and i in decided_at:
                    armed[si][ti] = True
                elif t["rearm"] == "recover":
                    ref = port["cost_basis"][s] if (
                        t["kind"] == "drop_from_cost"
                        and port["cost_basis"][s] > 0) else \
                        max(closes[s][-t["lookback_days"]:])
                    if ref and row[s] > ref * (1 - t["pct"] / 100.0):
                        armed[si][ti] = True

        # --- trigger evaluation, on held positions only ---
        triggered = []
        for si, s in enumerate(symbols):
            if port["qty"][s] <= 0:
                continue
            for ti, t in enumerate(plan["triggers"]):
                if not armed[si][ti]:
                    continue
                if t["kind"] == "drop_from_cost":
                    if port["cost_basis"][s] <= 0:
                        continue
                    ref = port["cost_basis"][s]
                else:  # drop_from_peak
                    ref = max(closes[s][-t["lookback_days"]:])
                if ref <= 0:
                    continue
                drop = (ref - row[s]) / ref * 100.0
                if drop >= t["pct"]:
                    triggered.append({"symbol": s, "kind": t["kind"],
                                      "threshold_pct": t["pct"],
                                      "drop_pct": _pct(drop)})
                    armed[si][ti] = False

        # --- decision point: a periodic check, or a day a trigger fired ---
        if i in decided_at or triggered:
            n_decisions += 1
            research: dict = {}
            research_note = None
            if researcher is not None and plan.get("research"):
                try:
                    got = researcher(ds, symbols, plan)
                    if isinstance(got, dict):
                        research = {k: v for k, v in got.items() if v}
                except Exception as e:  # research must never sink a backtest
                    research, research_note = {}, f"research skipped ({e})"

            pos_value = sum(port["qty"][s] * row[s] for s in symbols)
            equity = port["cash"] + pos_value
            context = _build_context(ds, plan, row, closes, port, equity,
                                     triggered, research, ever_held)
            try:
                decision = decider(context)
            except Exception:
                decision = {"trades": [],
                            "note": "the decider failed — no trades that day"}
            if not isinstance(decision, dict):
                decision = {"trades": [],
                            "note": "the decider's answer was unreadable"}
            trades, day_cost = _apply_trades(decision, ds, row, port, equity, cost)
            n_trades += len(trades)
            cost_paid += day_cost

            note = str(decision.get("note") or "")
            if research_note:
                note = (note + " " + research_note).strip()
            log.append({"date": ds, "research": research,
                        "trades": trades, "note": note})
            if len(log) > MAX_DECISION_LOG:
                log = log[-MAX_DECISION_LOG:]

        # --- mark to market (after any trades, so the day's close is final) ---
        pos_value = sum(port["qty"][s] * row[s] for s in symbols)
        equity = port["cash"] + pos_value
        days_in_market += 1 if pos_value > 0 else 0
        ever_held = ever_held or pos_value > 0
        eq.append(equity)
        dates.append(ds)

    m = backtest._metrics(eq, dates)
    bm = backtest._metrics(bench, dates)
    return {
        "plan": plan,
        "dates": dates,
        "equity": [round(v, 2) for v in eq],
        "benchmark": [round(v, 2) for v in bench],
        "metrics": m,
        "benchmark_metrics": bm,
        "trades": n_trades,
        "decisions": n_decisions,
        "time_in_market": round(days_in_market / len(common), 4),
        "cost_paid": round(cost_paid, 2),
        "log": log,
    }


def _build_context(ds, plan, row, closes, port, equity, triggered, research,
                   ever_held: bool) -> dict:
    """Everything the decider may know on this day — nothing after it.

    ``ever_held`` tells the decider whether the portfolio has held a
    position before this day, so a first-ever deployment can be told
    apart from "we sold everything and now sit in cash".
    """
    d = date.fromisoformat(ds)
    positions = []
    for s in plan["symbols"]:
        if port["qty"][s] <= 0:
            continue
        peak = max(closes[s])
        cb = port["cost_basis"][s]
        drop_cost = ((cb - row[s]) / cb * 100.0 if cb > 0 else 0.0)
        positions.append({
            "symbol": s,
            "qty": round(port["qty"][s], 4),
            "cost_basis": round(cb, 4),
            "value": round(port["qty"][s] * row[s], 2),
            "pnl_pct": _pct((row[s] / cb - 1) * 100.0) if cb > 0 else None,
            "drop_from_cost_pct": _pct(max(0.0, drop_cost)),
            "drop_from_peak_pct": _pct(max(0.0, (peak - row[s]) / peak * 100.0)
                                       if peak > 0 else 0.0),
            "days_held": ((d - date.fromisoformat(port["bought_day"][s])).days
                          if port["bought_day"][s] else None),
        })
    return {
        "date": ds,
        "plan": plan,
        "portfolio": {
            "cash": round(port["cash"], 2),
            "equity": round(equity, 2),
            "positions": positions,
        },
        "prices": {s: _window_stats(closes[s]) for s in plan["symbols"]},
        "triggered": triggered,
        "research": research,
        "ever_held": ever_held,
    }


def _apply_trades(decision, ds, row, port, equity, cost):
    """Apply the decider's trades at the day's close, in place on ``port``.

    Returns ``(executed_trades, cost_charged)`` — the sanitized truth
    for the log. Trades the decider named but the portfolio cannot do
    (no cash, no position, a symbol outside the universe, a weight out
    of range) are dropped, not errors: a decider that overreaches never
    crashes a backtest.
    """
    out, charged = [], 0.0
    if not isinstance(decision, dict):
        return out, 0.0
    for t in decision.get("trades") or []:
        if not isinstance(t, dict):
            continue
        s = str(t.get("symbol", "")).strip().upper()
        side = str(t.get("side", "")).strip().lower()
        try:
            w = float(t.get("weight", 0))
        except (TypeError, ValueError):
            continue
        if s not in row or row[s] <= 0 or not (0 < w <= 1):
            continue
        if side == "buy":
            if port["cash"] <= 0:
                continue
            spend = min(w * equity, port["cash"])
            if spend < 1:
                continue
            fee = spend * cost
            port["cash"] -= spend
            add = (spend - fee) / row[s]
            if port["qty"][s] > 0:
                port["cost_basis"][s] = ((port["cost_basis"][s] * port["qty"][s])
                                          + (spend - fee)) / (port["qty"][s] + add)
            else:
                port["cost_basis"][s] = row[s] * (1 - cost)
                port["bought_day"][s] = ds
            port["qty"][s] += add
            charged += fee
            out.append({"symbol": s, "side": "buy", "weight": round(w, 4),
                        "spend": round(spend, 2)})
        elif side == "sell":
            if port["qty"][s] <= 0:
                continue
            sell_qty = min(port["qty"][s], port["qty"][s] * w)
            proceeds = sell_qty * row[s]
            fee = proceeds * cost
            port["cash"] += proceeds - fee
            charged += fee
            port["qty"][s] -= sell_qty
            if port["qty"][s] <= 1e-9:
                port["qty"][s] = 0.0
                port["cost_basis"][s] = 0.0
                port["bought_day"][s] = None
            out.append({"symbol": s, "side": "sell", "weight": round(w, 4),
                        "proceeds": round(proceeds, 2)})
    return out, charged


# ---------------------------------------------------------------------------
# The deterministic decider ("my plan" mode; the stand-in in tests)
# ---------------------------------------------------------------------------

def decide_plan(context: dict) -> dict:
    """Apply the plan's stated actions, literally.

    - a triggered drop does whatever ``on_drop`` says (add / sell half /
      sell all / hold);
    - a position up at least ``exit_pct`` over cost is sold in full;
    - idle cash is deployed toward the targets on the first-ever day,
      and afterwards only tops up underweight *held* positions. A symbol
      the plan deliberately sold is never bought back on a top-up.
    """
    plan = context["plan"]
    port = context["portfolio"]
    cash, equity = port["cash"], port["equity"]
    if equity <= 0:
        return {"trades": [], "note": "portfolio is flat; nothing to do"}

    pos = {p["symbol"]: p for p in port["positions"]}
    trades: list[dict] = []
    done: list[str] = []

    for trig in context.get("triggered") or []:
        s = trig["symbol"]
        if s not in pos:
            continue
        action = plan["on_drop"]
        label = trig["kind"].replace("drop_from_", "down from ")
        if action == "hold":
            done.append(f"{s} is {label} {trig['drop_pct']:.0f}% — holding, as the plan says")
        elif action == "add":
            if cash <= 0.01 * equity:
                done.append(f"{s} dropped {trig['drop_pct']:.0f}% — would add, but there is no spare cash")
            else:
                trades.append({"symbol": s, "side": "buy", "weight": plan["add_weight"]})
                done.append(f"{s} dropped {trig['drop_pct']:.0f}% ({label}) — "
                            f"added {plan['add_weight'] * 100:.0f}% of the portfolio to it")
        elif action == "sell_half":
            trades.append({"symbol": s, "side": "sell", "weight": 0.5})
            done.append(f"{s} dropped {trig['drop_pct']:.0f}% — sold half the position")
        else:  # sell_all
            trades.append({"symbol": s, "side": "sell", "weight": 1.0})
            done.append(f"{s} dropped {trig['drop_pct']:.0f}% — sold the position")

    if plan.get("exit_pct") is not None:
        for s, p in pos.items():
            if any(t["symbol"] == s for t in trades):
                continue  # a trigger already acted on it this day
            if p["pnl_pct"] is not None and p["pnl_pct"] >= plan["exit_pct"]:
                trades.append({"symbol": s, "side": "sell", "weight": 1.0})
                done.append(f"{s} is up {p['pnl_pct']:.0f}% — exited at the "
                            f"{plan['exit_pct']:.0f}% profit target")

    # --- deploy / top-up the idle cash toward the targets ---
    held = {p["symbol"] for p in port["positions"]}
    if cash > 0.01 * equity:
        deploy = cash / equity
        if not held:
            has_sell_machinery = (plan.get("exit_pct") is not None
                                 or plan.get("on_drop") in ("sell_half", "sell_all")
                                 or bool(plan.get("triggers")))
            if not context.get("ever_held") or not has_sell_machinery:
                for s, w in plan["targets"].items():
                    share = w * deploy
                    if share >= 0.01:
                        trades.append({"symbol": s, "side": "buy",
                                       "weight": share})
        else:
            # the gap is measured on the pre-trade context, so subtract
            # what this very call already bought, and never top up a
            # symbol this call just sold.
            sold_today = {t["symbol"] for t in trades if t["side"] == "sell"}
            bought_today: dict[str, float] = {}
            for t in trades:
                if t["side"] == "buy":
                    bought_today[t["symbol"]] = bought_today.get(t["symbol"], 0.0) + t["weight"]
            for p in port["positions"]:
                s = p["symbol"]
                if s in sold_today:
                    continue
                want = plan["targets"].get(s, 0.0)
                gap = want - p["value"] / equity - bought_today.get(s, 0.0)
                if gap >= 0.05:
                    trades.append({"symbol": s, "side": "buy",
                                   "weight": min(gap, deploy)})
        if any(t["side"] == "buy" for t in trades):
            done.append("topped up toward the targets")

    note = "; ".join(done) if done else "checked — nothing to do"
    return {"trades": trades, "note": note}


# ---------------------------------------------------------------------------
# The interpreter: the user's own words -> a plan
# ---------------------------------------------------------------------------

#: All-caps tokens that are English, not tickers.
_TICKER_STOP = {
    "I", "A", "AN", "OK", "US", "UK", "EU", "AI", "ETF", "ETFS", "IPO",
    "SEC", "FED", "NYSE", "NASDAQ", "SP", "API", "LLM", "MAX", "MIN", "NEW",
    "NOT", "YES", "NO", "OR", "THE",
}


def _extract_tickers(text: str) -> list[str]:
    """All-caps 1-8 letter tokens, first appearance order, deduped.
    A deliberately blunt reader: it is the fallback, the LLM is the
    precise one, and the form's ticker field outranks both."""
    out: list[str] = []
    for tok in re.findall(r"\b[A-Z]{1,8}\b", text):
        if tok in _TICKER_STOP:
            continue
        if not all(c.isalnum() or c in ".-" for c in tok):
            continue
        if tok not in out:
            out.append(tok)
    return out[:MAX_SYMBOLS]


def _frequency_from(text: str) -> str | None:
    t = text.lower()
    m = re.search(r"(\d+)\s*(?:times?|x)\s*(?:a|per|each)\s*month", t)
    if m:
        n = int(m.group(1))
        if n >= 4:
            return "week"
        if n >= 2:
            return "two_weeks"
        return "month"
    if re.search(r"twice\s*(?:a|per|each)\s*month|two times a month", t):
        return "two_weeks"
    if re.search(r"four times a month|five times a month", t):
        return "week"
    if re.search(r"quarterly|every quarter|once a quarter|per quarter", t):
        return "quarter"
    if re.search(r"monthly|every month|once a month|per month", t):
        return "month"
    if re.search(r"bi ?weekly|every two weeks|every fortnight|two weeks", t):
        return "two_weeks"
    if re.search(r"weekly|every week|once a week|per week", t):
        return "week"
    return None


_DROP_VERB = (r"(?:drops?|fell|falls?|falling|dips?|dip|pulls? back|pullback|"
              r"declines?|down|below|under|off)")


_ACTION_VERBS = r"sell|trim|cut|exit|stop|buy|add|average down"


def _trigger_from(text: str) -> tuple[dict | None, str, tuple[int, int] | None]:
    """The one drop trigger the words state, plus the on-drop action.

    Reads the number nearest the drop language: "drops 10%" or
    "25% below my cost". The cost/peak reading comes from the trigger's
    own neighbourhood, so a "paid" in a distant exit clause cannot
    re-aim it. The action is read from the trigger's own clause, then
    the next one: "drops 10%, buy" puts the verb after the comma,
    while an exit stated two clauses later must not be reached.
    The third return is the match span, so the exit reader can skip
    a number that belongs to the drop."""
    t = text.lower()
    m = (re.search(rf"{_DROP_VERB}\D{{0,12}}?(\d{{1,3}}(?:\.\d+)?)\s*%", t)
         or re.search(r"(\d{1,3}(?:\.\d+)?)\s*%\s*(?:below|under)\b", t)
         or re.search(r"(\d{1,3}(?:\.\d+)?)\s*%\s*"
                      r"(?:dips?|pullbacks?|drops?|drawdowns?)\b", t))
    if not m:
        return None, "hold", None
    pct = float(m.group(1))
    if not (1 <= pct <= 90):
        return None, "hold", None
    window = t[max(0, m.start() - 60): m.end() + 60]
    kind = "drop_from_cost" if re.search(r"cost|basis|paid", window) else "drop_from_peak"
    rest = re.split(r"[,.!?;]", t[m.end(): m.end() + 120], maxsplit=2)
    probe = rest[0]
    if not re.search(_ACTION_VERBS, probe) and len(rest) > 1:
        probe += " " + rest[1]
    if not re.search(_ACTION_VERBS, probe):
        probe += " " + t[max(0, m.start() - 60): m.start()]
    if re.search(r"sell|trim|cut|exit|stop", probe):
        action = "sell_half" if "half" in probe else "sell_all"
    elif re.search(r"buy|add|average down", probe):
        action = "add"
    else:
        action = "hold"
    return ({"kind": kind, "pct": pct, "lookback_days": 252, "rearm": "recover"},
            action, (m.start(), m.end()))


def _exit_from(text: str, skip: tuple[int, int] | None = None) -> float | None:
    """The take-profit, "sell at a 30% gain" and friends. A number that
    sits inside ``skip`` (the drop trigger's span) is the drop's, not
    a gain's, and is skipped."""
    t = text.lower()
    for m in re.finditer(
            r"(?:sell|exit|take profits?|lock in|rebalance)[^.]{0,40}?"
            r"(\d{1,3}(?:\.\d+)?)\s*%", t):
        if skip and skip[0] - 5 <= m.start(1) <= skip[1] + 5:
            continue
        pct = float(m.group(1))
        if 1 <= pct <= 500:
            return pct
    return None


def _start_cash_from(text: str) -> float | None:
    m = re.search(r"\$\s?([\d,]{3,9})\b", text)
    if m:
        return float(m.group(1).replace(",", ""))
    m = re.search(r"\b(\d{1,5})\s?k\b", text.lower())
    if m:
        return float(m.group(1)) * 1000.0
    return None


def draft_from_text(text: str, symbols: list[str] | None = None,
                    start_cash: float = 100_000.0) -> dict:
    """The deterministic reader: plain English -> make_plan() kwargs.

    It is a fallback, not a promise — what it does not read stays at
    the default, and the plan it returns is always the honest one for
    the words it actually heard.
    """
    t = (text or "").strip()
    tickers = _extract_tickers(t) or [str(s).upper() for s in (symbols or [])]
    trig, on_drop, span = _trigger_from(t)
    trigs = [trig] if trig else []
    m = re.search(r"\badd(?:ing)?\D{0,10}?(\d{1,3}(?:\.\d+)?)\s*%", t.lower())
    add_w = 0.10
    if m:
        add_w = float(m.group(1))
        if add_w > 1:                      # "add 20%" means 0.20 of equity
            add_w /= 100.0
    return {
        "symbols": tickers[:MAX_SYMBOLS],
        "start_cash": _start_cash_from(t) or start_cash,
        "frequency": _frequency_from(t) or "month",
        "triggers": trigs,
        "targets": {},          # let make_plan default to equal weights
        "on_drop": on_drop,
        "add_weight": add_w if 0.01 <= add_w <= 0.5 else 0.10,
        "exit_pct": _exit_from(t, span),
        "research": bool(re.search(
            r"research|news|read up|search the web|check (?:the )?(?:web|internet|filings)",
            t.lower())),
        "names": {},
    }


_INTERPRET_SYSTEM = (
    "You are the planning reader of a strategy backtester. The user "
    "describes their own trading strategy in plain English. Convert it "
    "into a machine-readable plan.\n\n"
    "Respond with STRICT JSON only — no markdown fences, no commentary — "
    "exactly this shape:\n"
    '{"symbols": ["SPY"], "frequency": "month", '
    '"triggers": [{"kind": "drop_from_peak", "pct": 20, "lookback_days": 252, '
    '"rearm": "recover"}], "targets": {"SPY": 0.5}, "on_drop": "add", '
    '"add_weight": 0.1, "exit_pct": null, "research": false, "names": {}}\n\n'
    "Rules:\n"
    "- frequency: the check cadence the user stated, one of week, "
    "two_weeks, month, quarter (default month).\n"
    "- triggers: kind is drop_from_peak (a drop from its recent high) or "
    "drop_from_cost (a drop from what the user paid); pct is the drop in "
    "percent (1-90); lookback_days is 5-504 (how far back the peak "
    "window looks, default 252); rearm is recover (re-arm when the price "
    "recovers above the trigger level) or periodic (re-arm at the next "
    "check). An empty list when the user states no drop trigger.\n"
    "- targets: the desired weight of each symbol, fractions that sum to "
    "1 (an equal split when the user does not say).\n"
    "- on_drop: what the user says to do when a trigger fires, one of "
    "hold, add, sell_half, sell_all (default hold).\n"
    "- add_weight: the fraction of total equity added when buying a drop, "
    "0.01-0.5 (default 0.1).\n"
    "- exit_pct: the take-profit percent above cost, or null when the "
    "user states none.\n"
    "- research: true only when the user asks for research, news-reading "
    "or checking the web.\n"
    "- names: optional ticker -> real company or document name, which "
    "helps web research find the right page.\n"
    "- symbols: the tickers to trade, upper-case. If the user names "
    "none, use the form tickers you are given."
)


def _parse_json_lenient(content: str) -> dict | None:
    """A model answer -> dict. Tolerates code fences and a chatty
    preamble: take the outermost braces. Anything else is None."""
    t = (content or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except ValueError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if 0 <= start < end:
        try:
            v = json.loads(t[start:end + 1])
            return v if isinstance(v, dict) else None
        except ValueError:
            return None
    return None


def _clamp(v, lo: float, hi: float, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, x))


def _coerce_llm_plan(raw: dict, form_symbols: list[str] | None,
                     start_cash: float) -> dict:
    """Raw model JSON -> make_plan() kwargs, leniently.

    Clamps what it can, drops what it cannot, and keeps the user's
    universe fixed: when the form named tickers, those are the
    universe and the model may only annotate them."""
    if form_symbols:
        syms: list[str] = []
        for s in form_symbols:
            s = str(s).strip().upper()
            if s and s not in syms:
                syms.append(s)
    else:
        syms = [str(s).strip().upper() for s in (raw.get("symbols") or [])
                if str(s).strip()]
        syms = list(dict.fromkeys(syms))[:MAX_SYMBOLS]

    tgts: dict[str, float] = {}
    for s, w in (raw.get("targets") or {}).items():
        s = str(s).strip().upper()
        if s not in syms:
            continue
        w = _clamp(w, 0.001, 1.0, 0.0)
        if w > 0:
            tgts[s] = w
    if not tgts:
        w = round(1.0 / len(syms), 6) if syms else 1.0
        tgts = {s: w for s in syms}
    total = sum(tgts.values())
    if total > 1.0 + 1e-9:
        tgts = {s: w / total for s, w in tgts.items()}

    trigs = []
    for t in (raw.get("triggers") or [])[:4]:
        if not isinstance(t, dict):
            continue
        kind = t.get("kind")
        if kind not in TRIGGER_KINDS:
            continue
        rearm = t.get("rearm")
        trigs.append({
            "kind": kind,
            "pct": _clamp(t.get("pct"), 1, 90, 10.0),
            "lookback_days": int(_clamp(t.get("lookback_days"), 5, 504, 252)),
            "rearm": rearm if rearm in REARM_MODES else "recover",
        })

    on_drop = raw.get("on_drop")
    exit_pct = raw.get("exit_pct")
    if exit_pct in (None, False, 0):
        exit_pct = None                    # a 0% take-profit is no exit
    else:
        exit_pct = _clamp(exit_pct, 1, 500, 0.0) or None

    names = {}
    for k, v in (raw.get("names") or {}).items():
        k = str(k).strip().upper()
        v = str(v or "").strip()
        if k in syms and v and len(v) <= 120:
            names[k] = v

    return {
        "symbols": syms,
        "start_cash": start_cash,
        "frequency": raw.get("frequency") if raw.get("frequency") in FREQUENCIES
        else "month",
        "triggers": trigs,
        "targets": tgts,
        "on_drop": on_drop if on_drop in ON_DROP_ACTIONS else "hold",
        "add_weight": _clamp(raw.get("add_weight"), 0.01, 0.5, 0.10),
        "exit_pct": exit_pct,
        "research": bool(raw.get("research")),
        "names": names,
    }


def _llm_plan(text: str, draft: dict,
              form_symbols: list[str] | None,
              config: dict | None = None) -> dict | None:
    """One model call: the words -> make_plan() kwargs, or None when the
    call fails or its answer does not read. Never raises. ``config`` is
    the request's model settings (the llm seam) — a background thread
    cannot see the request, so the route captures it and passes it in."""
    from app import risk

    universe = form_symbols or draft["symbols"]
    user = (f"Form tickers: {', '.join(universe) if universe else '(none given)'}\n"
            f"Start cash: ${draft['start_cash']:,.0f}\n\n"
            f"The user's strategy, in their own words:\n\"\"\"\n"
            f"{text[:4000]}\n\"\"\"")
    try:
        content, _model = risk._post_llm(_INTERPRET_SYSTEM, user,
                                         config=config,
                                         max_tokens=800, timeout=60.0)
    except Exception:
        return None
    raw = _parse_json_lenient(content)
    if raw is None:
        return None
    return _coerce_llm_plan(raw, form_symbols, draft["start_cash"])


def interpret_strategy(text: str, symbols: list[str] | None = None,
                       start_cash: float = 100_000.0,
                       use_llm: bool | None = None,
                       config: dict | None = None) -> tuple[dict, str]:
    """The user's words -> a validated plan.

    Returns ``(plan, source)`` where source is "model" (the language
    model read the words) or "words" (the deterministic reader did).
    The deterministic reader always runs first: it is the fallback when
    no model is configured or the model's answer fails validation.
    ``config`` is the request's model settings from the llm seam.
    Raises ValueError in plain English when nothing can be read.
    """
    from . import llm

    text = (text or "").strip()
    if not text:
        raise ValueError("describe the strategy in a few words first")
    draft = draft_from_text(text, symbols, start_cash)
    if use_llm is None:
        use_llm = llm.is_configured(config)
    if use_llm:
        llm_plan = _llm_plan(text, draft, symbols, config)
        if llm_plan is not None:
            plan = make_plan(**llm_plan)
            plan["text"] = text[:4000]   # keep the user's words for the decider
            return plan, "model"
    plan = make_plan(**draft)
    plan["text"] = text[:4000]
    return plan, "words"


# ---------------------------------------------------------------------------
# The LLM decider ("AI runs it": the model is the trader)
# ---------------------------------------------------------------------------

_DECIDER_SYSTEM = (
    "You are the trader of a backtest re-running a strategy the user "
    "described in their own words. The strategy, verbatim:\n"
    "\"\"\"\n{text}\n\"\"\"\n\n"
    "Each message you receive states a date and everything known on that "
    "date: the portfolio, each holding's price stats, the drop triggers "
    "firing, and any research gathered. Nothing after that date exists "
    "for you.\n\n"
    "Respond with STRICT JSON only — no markdown fences, no commentary:\n"
    '{"trades": [{"symbol": "SPY", "side": "buy", "weight": 0.25}], '
    '"note": "one plain-English sentence"}\n\n'
    "Rules:\n"
    "- symbol must be one of the tickers in the holdings or price list.\n"
    "- side is buy or sell. weight is a fraction of total equity, 0 to 1: "
    "a buy spends up to weight x equity from cash, a sell sells weight of "
    "that position.\n"
    "- Trade only when the user's strategy calls for it; otherwise an "
    "empty trades list.\n"
    "- Follow the user's words, not your own trading opinions."
)


def build_decision_prompt(context: dict) -> tuple[str, str]:
    """The one LLM call per decision day.

    System: the user's strategy verbatim plus the JSON contract. User:
    the state as of that date, field by field — nothing the engine did
    not put in the context can reach the model.
    """
    plan = context.get("plan") or {}
    words = (plan.get("text") or "").strip() or "(no strategy words given)"
    # .replace, not .format: the JSON example below is full of braces.
    system = _DECIDER_SYSTEM.replace("{text}", words, 1)

    port = context.get("portfolio") or {}
    lines = [f"Date: {context.get('date', '?')}",
             f"Cash: ${port.get('cash', 0.0):,.2f}    "
             f"Total equity: ${port.get('equity', 0.0):,.2f}"]

    pos = port.get("positions") or []
    if pos:
        lines.append("Holdings:")
        for p in pos:
            pnl = (f"{p['pnl_pct']:+.1f}%" if p.get("pnl_pct") is not None
                   else "n/a")
            lines.append(
                f"- {p['symbol']}: {p['qty']:.4f} units, cost "
                f"${p['cost_basis']:.2f}, value ${p['value']:.2f}, P&L {pnl} "
                f"vs cost, down {p['drop_from_cost_pct']:.1f}% from cost, "
                f"down {p['drop_from_peak_pct']:.1f}% from peak")
    else:
        lines.append("Holdings: none"
                     + (" — the portfolio has never held a position"
                        if not context.get("ever_held") else ""))

    prices = context.get("prices") or {}
    if prices:
        lines.append("Prices through today's close:")
        for s, w in prices.items():
            lines.append(
                f"- {s}: ${w['close']:.2f} (1w ${w['1w']:.2f}, "
                f"1y ${w['1y']:.2f}, 52w ${w['52w_low']:.2f}"
                f"-${w['52w_high']:.2f})")

    triggered = context.get("triggered") or []
    if triggered:
        lines.append("Drop triggers firing today: " + "; ".join(
            f"{t['symbol']} is down {t['drop_pct']:.1f}% from its "
            f"{'cost' if t['kind'] == 'drop_from_cost' else 'peak'} "
            f"(threshold {t['threshold_pct']:.0f}%)" for t in triggered))
    else:
        lines.append("Drop triggers firing today: none")

    research = {k: v for k, v in (context.get("research") or {}).items()
                if k != "_skips"}
    skips = (context.get("research") or {}).get("_skips") or {}
    if research or skips:
        lines.append("Research gathered as of this date:")
        for s, txt in research.items():
            lines.append(f"- {s}: {(txt or 'nothing readable')[:1200]}")
        for s, reason in skips.items():
            lines.append(f"- {s}: (skipped — {reason})")

    lines.append("Respond with the strict JSON decision now.")
    return system, "\n".join(lines)


def make_llm_decider(config: dict | None = None) -> Callable[[dict], dict]:
    """The decider for "AI runs it": one model call per decision day.

    The model re-reads the user's strategy verbatim at every decision
    and rules on the day's state. It lazily imports ``app.risk`` — the
    shared ``llm`` seam — and the tests patch ``risk._post_llm`` so no
    model is ever really called. ``config`` is the request's model
    settings; the lab's background thread cannot see the request, so the
    route captures it and passes it in. Trades in
    symbols outside the plan's universe, with a bad side or weight, are
    dropped, and weights are clamped to 0-1: a decider that overreaches
    never crashes a backtest. Any failure (no key, server down,
    unreadable answer) becomes a "no trades" decision that says so."""
    from app import risk

    def decide(context: dict) -> dict:
        universe = {str(s).upper()
                    for s in ((context.get("plan") or {}).get("symbols") or [])}
        system, user = build_decision_prompt(context)
        try:
            content, _model = risk._post_llm(system, user, config=config,
                                              max_tokens=800, timeout=60.0)
        except Exception as e:
            return {"trades": [],
                    "note": f"the model was unavailable ({e}); no trades"}
        raw = _parse_json_lenient(content)
        if raw is None:
            return {"trades": [],
                    "note": "the model's answer did not read; no trades"}
        trades = []
        for t in (raw.get("trades") or [])[:10]:
            if not isinstance(t, dict):
                continue
            side = str(t.get("side", "")).strip().lower()
            if side not in ("buy", "sell"):
                continue
            s = str(t.get("symbol", "")).strip().upper()
            if not s or (universe and s not in universe):
                continue
            try:
                w = float(t.get("weight", 0.0))
            except (TypeError, ValueError):
                continue
            w = min(1.0, max(0.0, w))
            if w <= 0:
                continue
            trades.append({"symbol": s, "side": side, "weight": w})
        note = str(raw.get("note") or "")[:300] or \
            "the model saw no reason to trade"
        return {"trades": trades, "note": note}

    return decide
