"""Risk analysis: what your portfolio becomes if each holding moves.

Each saved holding gets a ``move``: a hypothetical price change in
percent, either one the user types or one the language model suggests
("Fill with AI"). The view shows the portfolio total after all moves
happen — the expected value of the scenario — and a measured number
beside each chosen one: the holding's annualized volatility, from its
own year of daily closes.

The moves live in ``data/risk.json``, a small ``{v, updated, moves}``
envelope mirroring the portfolio file, saved atomically. A missing
file or a missing entry reads back as 0 — the holding that did not
move — and an out-of-range value is clamped, never an error.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


from . import market_data, portfolio

RISK_PATH = Path(__file__).resolve().parent.parent / "data" / "risk.json"
_VERSION = 1

_LOCK = threading.Lock()

# A move is a percent: -99 (wiped out) to +999 (ten-bagger territory).
# Outside that the number stops meaning anything, so it is clamped.
MOVE_LO, MOVE_HI = -99.0, 999.0

_CURRENCY = re.compile(r"^[A-Z]{3}$")


# ---------------------------------------------------------------------------
# Persistence (mirrors the portfolio's load/save pair)
# ---------------------------------------------------------------------------

def _load_file() -> dict | None:
    """The saved moves, or None if the file is missing or corrupt."""
    try:
        d = json.loads(RISK_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if d.get("v") != _VERSION or not isinstance(d.get("moves"), dict):
        return None
    return d


def _save(moves: dict[str, float]) -> None:
    """The moves are the user's data, written atomically. Lock-free on
    purpose: the mutator below holds the lock across the write."""
    RISK_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RISK_PATH.parent / (RISK_PATH.name + ".tmp")
    tmp.write_text(json.dumps({"v": _VERSION, "updated": int(time.time()),
                               "moves": moves}, indent=1))
    tmp.replace(RISK_PATH)


def _clamp(x: float) -> float:
    return max(MOVE_LO, min(MOVE_HI, x))


def load_moves() -> dict[str, float]:
    """Saved moves as ``{TICKER: percent}``; a missing file means
    "no moves yet", which is a legitimate state, not an error."""
    d = _load_file()
    if not d:
        return {}
    out: dict[str, float] = {}
    for k, v in d["moves"].items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out[str(k)] = _clamp(f)
    return out


def save_moves(moves: dict) -> dict:
    """Persist a whole scenario (the client sends every row).

    Values are clamped into range and rounded; junk — non-numeric
    values, keys that are not tickers — is dropped quietly rather than
    rejected, so a typo of -5000 becomes -99 and the save succeeds.
    """
    out: dict[str, float] = {}
    for k, v in (moves or {}).items():
        key = str(k).strip().upper()
        if not key or len(key) > 16:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(f):
            continue
        out[key] = _clamp(round(f, 2))
    with _LOCK:
        _save(out)
    return {"moves": out, "updated": int(time.time())}


# ---------------------------------------------------------------------------
# The measured number: how much a holding typically moves
# ---------------------------------------------------------------------------

_MIN_BARS = 20  # fewer than ~20 closes is too thin to read as volatility


def volatility(history: dict[str, float] | None) -> float | None:
    """Annualized volatility of a year of daily closes, or None.

    Daily percentage changes, sample standard deviation, scaled by the
    square root of a 252-day trading year. A series shorter than
    ``_MIN_BARS`` closes — a recent listing, a blocked fetch — is
    None, never a number that looks precise.
    """
    if not history:
        return None
    closes = [history[d] for d in sorted(history)]
    rets = [closes[i] / closes[i - 1] - 1.0
            for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(rets) < _MIN_BARS:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252.0)


# ---------------------------------------------------------------------------
# The view: one position -> one row of the risk table
# ---------------------------------------------------------------------------

def _row(p: dict, q: dict | None, display: str,
         hist: dict[str, float] | None, moves: dict[str, float]) -> dict:
    """One saved position + quote + history + its move -> one row.

    Reuses the portfolio's enricher for every price-related field
    (the 13F pool is skipped — risk is about your money, not the
    funds'), then adds the scenario fields. ``scenario_value`` is
    ``value * (1 + move/100)`` and ``scenario_delta`` the difference
    of the two rounded numbers, so the client can recompute exactly
    the same figures when a move changes.
    """
    row = portfolio._enrich(p, q, None, display, hist)
    move = float(moves.get(p["ticker"], 0.0))
    fx = row.get("fx")
    iv = row.get("intervals") or {}
    y1 = iv.get("1y") or {}

    value = row.get("value")
    if value is not None:
        scenario = round(value * (1.0 + move / 100.0), 2)
        delta = round(scenario - value, 2)
    else:
        scenario = delta = None

    def conv(x, nd=2):
        return round(x * fx, nd) if (x is not None and fx) else None

    row["move"] = move
    row["vol"] = volatility(hist)
    row["ret_1y"] = y1.get("pct") if y1.get("pct") is not None else None
    row["scenario_value"] = scenario
    row["scenario_delta"] = delta
    row["display_scenario_value"] = conv(scenario) if display else None
    row["display_scenario_delta"] = conv(delta) if display else None
    return row


def _totals(positions: list[dict], display: str) -> dict:
    """The strip numbers: what the portfolio becomes after all moves.

    The mixed-currency rule is the portfolio's: without a display
    currency the totals only add when every priced holding shares one
    currency. The swing is a value-weighted average of the per-holding
    volatilities — a reading of how much the parts move, not a model
    of the whole (it ignores how the holdings move together).
    """
    def v(p):
        return p.get("display_value") if display else p.get("value")

    rows = [p for p in positions if v(p) is not None]
    curs = {p.get("currency") for p in rows if p.get("currency")}
    single = bool(display) or len(curs) <= 1

    def total(f):
        xs = [f(p) for p in rows if f(p) is not None]
        return round(sum(xs), 2) if xs else None

    value = total(v)
    scenario = total(lambda p: p.get("display_scenario_value") if display
                     else p.get("scenario_value"))

    delta = None
    delta_pct = None
    if single and value is not None and scenario is not None:
        delta = round(scenario - value, 2)
        if value > 0:
            delta_pct = delta / value

    ok = bool(display) or len(curs) <= 1
    wsum = vw = 0.0
    n_vols = 0
    for p in rows:
        vol = p.get("vol")
        w = v(p)
        if vol is None or w is None or w <= 0:
            continue
        n_vols += 1
        if ok:
            wsum += w
            vw += w * vol

    return {
        "value": value if single else None,
        "scenario": scenario if single else None,
        "delta": delta,
        "delta_pct": delta_pct,
        "currencies": sorted(curs),
        "currency": (display if len(curs) > 1 or display
                     else (next(iter(curs)) if len(curs) == 1 else None)) or None,
        "vol": (vw / wsum) if (ok and wsum > 0) else None,
        "n_vols": n_vols,
        "priced": len(rows),
        "missing": len(positions) - len(rows),
        "n": len(positions),
    }


def view(refresh: bool = False, currency: str = "") -> dict:
    """The risk page: every holding with a move and a measured swing,
    plus the scenario totals.

    The same quotes, histories, and FX rules as the portfolio view —
    the same disk caches, the same 10-minute TTL, the same staleness
    honesty. ``currency`` (like the portfolio's) converts rows and
    totals into one chosen currency through Yahoo's FX charts.
    """
    display = str(currency or "").strip().upper()
    if display and not _CURRENCY.fullmatch(display):
        display = ""

    entries = portfolio.load_portfolio()
    moves = load_moves()
    ttl = 0.0 if refresh else market_data._QUOTE_TTL
    if entries:
        with ThreadPoolExecutor(max_workers=4) as ex:
            quotes = list(ex.map(lambda p: portfolio._quote_for(p, ttl), entries))
            hists = list(ex.map(
                lambda pq: portfolio._history_for(*pq), zip(entries, quotes)))
    else:
        quotes, hists = [], []
    positions = [_row(p, q, display, h, moves)
                 for p, q, h in zip(entries, quotes, hists)]

    return {
        "positions": positions,
        "totals": _totals(positions, display),
        "n_live": sum(1 for p in positions if p["live"]),
    }


# ---------------------------------------------------------------------------
# Fill with AI: the model picks a move for every holding
# ---------------------------------------------------------------------------

_FILL_SYSTEM = (
    "You are choosing a price move for each holding in a person's "
    "portfolio, for a risk analysis they are doing themselves. For "
    "each holding, pick the move you expect over the coming year, in "
    "percent (a negative number is a fall). Anchor on what is given: "
    "the holding's own recent return, its typical annual swing, and "
    "your general view of that kind of asset. Keep moves moderate, "
    "between -40 and +40. Reply with ONLY a JSON object of the form "
    '{"moves": {"TICKER": number}} with one entry for every holding. '
    "No other text."
)


def _brief(rows: list[dict]) -> list[dict]:
    """Each holding reduced to what a model can reason about: identity,
    size, recent return, typical swing. No costs and no notes — the
    moves are about where prices go, not about the buyer."""
    total = sum((p.get("display_value") or p.get("value") or 0.0) for p in rows)
    out = []
    for p in rows:
        b = {"ticker": p.get("ticker"), "name": p.get("name"),
             "kind": p.get("kind") or "stock",
             "currency": p.get("currency") or None}
        b["price"] = round(p["price"], 2) if p.get("price") is not None else None
        b["value"] = round(p.get("display_value") or p.get("value") or 0.0, 2) \
            if (p.get("display_value") or p.get("value")) is not None else None
        b["return_1y_pct"] = (round(p["ret_1y"] * 100, 1)
                              if p.get("ret_1y") is not None else None)
        b["swing_pct"] = (round(p["vol"] * 100, 1)
                          if p.get("vol") is not None else None)
        v = p.get("display_value") or p.get("value")
        b["weight_pct"] = round(v / total * 100, 1) if (v and total > 0) else None
        out.append(b)
    return out


def _post_llm(system: str, user: str,
              max_tokens: int = 4000, timeout: float = 60.0,
              config: dict | None = None) -> tuple[str, str]:
    """One chat completion from the model in the shared ``llm`` seam —
    the request's key if the browser sent one, else the server's
    environment. Raises on any failure; the route turns those into
    plain-English errors.

    The budget is 4000, not 800: the default local model is a thinking
    model, and its reasoning counts against the budget. Measured, the
    fill spends ~750 tokens thinking before writing the ~100-token JSON;
    at 800 the JSON came back cut off mid-ticker."""
    from . import llm  # one seam: request override > environment

    try:
        content, model = llm.post_chat(
            system, user, config, max_tokens=max_tokens, timeout=timeout)
    except RuntimeError as e:
        if str(e) == "no key":
            raise RuntimeError(
                "no language model key is set — add one in Settings") from None
        raise
    return content, model


def ai_fill(d: dict) -> dict:
    """The model's move for every holding it recognizes.

    Returns ``{"moves": {ticker: percent}, "model": ..., "n": ...}``.
    Raises ``RuntimeError`` in plain English on any failure. Nothing is
    saved: the client applies the plan to the page and persists only
    what the user keeps, so a bad answer changes nothing.
    """
    rows = d.get("positions") or []
    if not rows:
        raise RuntimeError("There is nothing to fill in yet — "
                           "add holdings on Home first.")
    content, model = _post_llm(
        _FILL_SYSTEM,
        "Holdings: " + json.dumps(_brief(rows), separators=(",", ":")))
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        raise RuntimeError("the model did not return a usable plan")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise RuntimeError("the model's plan was not valid JSON")
    raw = data.get("moves") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        raise RuntimeError("the model's plan was not a moves table")
    real = {p["ticker"].upper(): p["ticker"]
            for p in rows if p.get("ticker")}
    out: dict[str, float] = {}
    for k, v in raw.items():
        hit = real.get(str(k).strip().upper())
        if hit is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(f):
            continue
        out[hit] = round(_clamp(f), 1)
    if not out:
        raise RuntimeError("the model's plan matched none of your holdings")
    return {"moves": out, "model": model, "n": len(out)}
