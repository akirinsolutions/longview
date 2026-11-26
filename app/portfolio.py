"""Your portfolio: what you hold, what it's worth, who else holds it.

Positions live in ``data/portfolio.json`` — a plain list of
``{ticker, name, shares, cost_basis, note, kind, purchase_date}``
entries, written with the same ``{v, updated, ...}`` envelope as the
fund roster and saved atomically. The file may simply not exist on
first run: an empty portfolio is a legitimate state, not an error
(unlike the roster, this one is the user's own, so there is nothing
to seed from).

Two kinds of holding:

- ``kind="stock"`` — a listed security, priced live by Yahoo Finance.
  If Yahoo is busy or blocked the price is a dash; the holding is
  never hidden, and a blocked quote is never an error. A bare ticker
  that needs an exchange suffix (``VDST`` -> ``VDST.L``) is resolved
  once through Yahoo's search.
- ``kind="custom"`` — something Yahoo doesn't list (a private fund, a
  property, an unlisted share class). The user supplies the current
  price, its currency, and the purchase price; Longview never asks Yahoo.

The 13F scan pool adds a second, independent signal: which of the
famous funds Longview tracks also hold the same company, matched on the
normalized company name (13Fs carry a name and a CUSIP, so there is
no way around name matching).

Totals are always in one currency. Native mode sums only when every
held currency agrees; ``view(currency=...)`` converts each priced row
through Yahoo's FX charts, keeps the native numbers for editing, and
still reports a total when some rows are dashed — with counts of what
was priced and what was missing. A missing FX rate leaves that row
dashed rather than inventing a number.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from . import funds, market_data, vault

_PORTFOLIO_VERSION = 1
_SECTION = "portfolio"

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Persistence: the vault's "portfolio" section (one file, the whole app)
# ---------------------------------------------------------------------------

def _load_portfolio_file() -> list[dict] | None:
    """The saved positions, or None if the vault holds none or a bad one."""
    d = vault.read_section(_SECTION)
    if d is None:
        return None
    if d.get("v") != _PORTFOLIO_VERSION:
        return None
    entries = d.get("positions")
    if not isinstance(entries, list) or not all(
            isinstance(p, dict) and p.get("ticker") for p in entries):
        return None
    return entries


def _save_portfolio(entries: list[dict]) -> None:
    """The portfolio is the user's real data; the vault writes it
    atomically. Lock-free on purpose: the mutators below hold the lock
    across the read-modify-write, so the writer must not take it again
    (the roster's save does the same).
    """
    vault.write_section(_SECTION, {"v": _PORTFOLIO_VERSION,
                                   "updated": int(time.time()),
                                   "positions": entries})


def load_portfolio() -> list[dict]:
    """The saved positions; a missing or corrupt file means 'none yet'.

    Older files predate custom holdings and purchase dates, so every
    entry is normalized on the way out: missing keys get a safe default
    and the two kinds stay distinguishable.
    """
    return [_normalize_saved(p) for p in (_load_portfolio_file() or [])]


def _normalize_saved(p: dict) -> dict:
    out = dict(p)
    kind = str(out.get("kind") or "").lower()
    out["kind"] = "custom" if kind == "custom" or out.get("price") is not None else "stock"
    out["purchase_date"] = str(out.get("purchase_date") or "")[:10]
    out["note"] = str(out.get("note") or "")
    out["name"] = str(out.get("name") or "")
    return out


def save_portfolio(entries: list[dict]) -> None:
    with _lock:
        _save_portfolio(entries)


# ---------------------------------------------------------------------------
# Positions: validation
# ---------------------------------------------------------------------------

_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CUSTOM_PREFIX = "CUSTOM-"


def _fnum(x, lo: float = 0.0, hi: float = float("inf")) -> float | None:
    """A finite float within [lo, hi], else None."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v < lo or v > hi:
        return None
    return v


def _is_custom(p: dict) -> bool:
    return str(p.get("kind") or "").lower() == "custom"


def _clean_date(x) -> str:
    """An ISO purchase date, or "" when it wasn't given. Rejects the
    obvious typo (anything that isn't a real YYYY-MM-DD day)."""
    s = str(x or "").strip()
    if not s:
        return ""
    if not _DATE.match(s):
        raise ValueError("purchase date must look like 2024-05-31")
    try:
        date.fromisoformat(s)
    except ValueError:
        raise ValueError("purchase date must be a real calendar day")
    return s


def _clean_currency(x, *, required: bool = False) -> str | None:
    s = str(x or "").strip().upper()
    if not s and not required:
        return None
    if not _CURRENCY.match(s):
        raise ValueError("currency must be a three-letter code, like USD or GBP")
    return s


def clean_position(p: dict) -> dict:
    """One raw dict -> a tidy position. Raises ValueError in plain
    English when it isn't one; the routes turn that into a 400."""
    kind = "custom" if _is_custom(p) else "stock"
    ticker = market_data._normalize_symbol(str(p.get("ticker") or ""))
    if not ticker or not _TICKER.match(ticker):
        raise ValueError("needs a ticker, like AAPL or BRK.B")
    name = " ".join(str(p.get("name") or "").split())[:80]
    shares = _fnum(p.get("shares"), lo=1e-6)
    if shares is None:
        raise ValueError("shares must be a number greater than zero")
    cost = _fnum(p.get("cost_basis"))
    if cost is None:
        raise ValueError("cost per share must be zero or a positive number")
    note = " ".join(str(p.get("note") or "").split())[:120]
    purchase_date = _clean_date(p.get("purchase_date"))

    out = {"ticker": ticker, "name": name, "shares": shares,
           "cost_basis": round(cost, 4), "note": note,
           "kind": kind, "purchase_date": purchase_date}
    if kind == "custom":
        if not name:
            raise ValueError("a custom investment needs a name")
        price = _fnum(p.get("price"), lo=1e-9)
        if price is None:
            raise ValueError("current price must be a number greater than zero")
        out["price"] = round(price, 4)
        out["currency"] = _clean_currency(p.get("currency"), required=True)
    return out


def _next_custom_ticker(entries: list[dict]) -> str:
    """CUSTOM-1, CUSTOM-2, ... skipping anything already taken."""
    used = {str(e.get("ticker") or "").upper() for e in entries}
    n = 1
    while f"{CUSTOM_PREFIX}{n}" in used:
        n += 1
    return f"{CUSTOM_PREFIX}{n}"


def add_position(p: dict) -> dict:
    """Validate, refuse a duplicate ticker (plain English), save, return."""
    with _lock:
        entries = load_portfolio()
        raw = dict(p)
        if _is_custom(raw) and not str(raw.get("ticker") or "").strip():
            raw["ticker"] = _next_custom_ticker(entries)
        pos = clean_position(raw)
        for e in entries:
            if e["ticker"] == pos["ticker"]:
                raise ValueError(f"{pos['ticker']} is already in your portfolio — "
                                 "click it to change the numbers")
        entries.append(pos)
        _save_portfolio(entries)
    return pos


def update_position(ticker: str, p: dict) -> dict:
    """Change shares / cost / note / price on an existing position."""
    with _lock:
        entries = load_portfolio()
        for i, e in enumerate(entries):
            if e["ticker"].upper() == ticker.upper():
                raw = dict(p)
                raw.setdefault("kind", e.get("kind", "stock"))
                if not str(raw.get("ticker") or "").strip():
                    raw["ticker"] = e["ticker"]
                pos = clean_position(raw)
                entries[i] = pos
                _save_portfolio(entries)
                return pos
    raise KeyError(ticker)


def remove_position(ticker: str) -> dict:
    """Drop a position. Raises KeyError when it isn't there."""
    with _lock:
        entries = load_portfolio()
        for i, e in enumerate(entries):
            if e["ticker"].upper() == ticker.upper():
                removed = entries.pop(i)
                _save_portfolio(entries)
                return removed
    raise KeyError(ticker)


# ---------------------------------------------------------------------------
# The 13F cross-check: which tracked funds also hold this company
# ---------------------------------------------------------------------------

_STATUS_RANK = {"new": 4, "increased": 3, "unchanged": 2, "decreased": 1, "exited": 0}


def _norm(name: str) -> str:
    """``funds.normalize_name`` plus one 13F quirk.

    13F filings tack the state of incorporation onto the name — a
    trailing "DEL" means Delaware (Berkshire Hathaway *Inc Del*). The
    shared normalizer leaves it in; for matching a Yahoo name against
    a 13F name it is pure noise, so a *trailing* DEL goes away.
    """
    toks = funds.normalize_name(name).split()
    if toks and toks[-1] == "DEL":
        toks = toks[:-1]
    return " ".join(toks)


def smart_money(name: str, pool: dict | None) -> dict | None:
    """'Do the famous funds also hold this company?'

    Matched on the normalized company name (13Fs give a name, not a
    ticker). Returns None when the pool is unavailable or nothing
    matches. ``holders`` are the funds' display names; ``status`` is
    the strongest move among the funds that hold it *this* quarter
    (a fund that exited does not count as a holder).
    """
    if not pool or not pool.get("rows"):
        return None
    key = _norm(name)
    if not key:
        return None
    matches = [r for r in pool["rows"] if _norm(r.get("issuer") or "") == key]
    active = [r for r in matches if r.get("status") != "exited"]
    if not active:
        return None
    keys = sorted({r["fund"] for r in active})
    names = sorted({r["fund_name"] for r in active if r.get("fund_name")})
    statuses = [r.get("status") or "" for r in active]
    status = max(statuses, key=lambda s: _STATUS_RANK.get(s, 0)) or None
    value = sum(r.get("value") or 0.0 for r in active)
    return {
        "n_funds": len(keys),
        "holders": names,
        "fund_keys": keys,
        "status": status,
        "value_13f": round(value, 2),
    }


# ---------------------------------------------------------------------------
# The home views
# ---------------------------------------------------------------------------

def _quote_for(p: dict, ttl: float) -> dict | None:
    """One saved position -> one quote (or None when Yahoo can't say).

    Custom holdings never touch the network: the user's own price is
    the quote. Stock quotes pass the saved name as a hint for the
    exchange-suffix resolver (``VDST`` -> ``VDST.L``).
    """
    if (p.get("kind") or "stock") == "custom":
        return {"symbol": p["ticker"], "name": p.get("name"),
                "price": p.get("price"), "week": None, "as_of": None,
                "currency": p.get("currency")}
    return market_data.quote(p["ticker"], ttl, name_hint=p.get("name") or "")


# The windows the portfolio reports gains over, in calendar days, measured
# back from the most recent close. The bar used is the last trading day
# on or before the cutoff, so a holiday week doesn't change what "1 month"
# means.
_INTERVALS = (("1w", 7), ("1m", 30), ("3m", 91), ("6m", 183), ("1y", 365))


def _bar_at_or_before(history: dict[str, float], target: str) -> float | None:
    """The close of the last trading day on or before `target` (ISO date).

    History comes back date-sorted from fetch_history; a defensive sort
    keeps this pure helper safe for hand-built series in tests.
    """
    if not history:
        return None
    best = None
    for d in sorted(history):
        if d <= target:
            best = history[d]
        else:
            break
    return best


def _interval_stats(history: dict[str, float] | None, shares: float) -> dict:
    """Per-interval gain: shares × (latest close − close N days earlier).

    Both ends come from the same split/dividend-adjusted series, so a
    stock that pays a dividend along the way isn't quietly dented by its
    own ex-date. A window with no bar in it — a recent listing, a blocked
    fetch — is None, never a guess.
    """
    out = {}
    if not history:
        return {k: None for k, _ in _INTERVALS}
    dates = sorted(history)
    last_d, last_c = dates[-1], history[dates[-1]]
    for key, days in _INTERVALS:
        target = (date.fromisoformat(last_d)
                  - timedelta(days=days)).isoformat()
        then = _bar_at_or_before(history, target)
        if then is None or then <= 0:
            out[key] = None
            continue
        out[key] = {
            "pl": round(shares * (last_c - then), 2),
            "pct": round(last_c / then - 1.0, 6),
            "price_then": round(then, 4),
            "price_now": round(last_c, 4),
        }
    return out



def _spark_series(positions: list[dict], hists: list, display: str) -> list:
    """A quiet year of portfolio value, for the Home sparkline.

    Every position that can be charted must be priced and carry a last-
    year history; custom holdings (no exchange history) and blocked
    quotes (no history) are not charted at all — a partial line that
    reads as "the portfolio" would be a lie. Returns [date, value]
    points in the display currency (or the single native currency),
    downsampled to ~150 points. Empty list when it cannot be charted
    honestly.
    """
    if not positions:
        return []
    if any((p.get("kind") or "stock") == "custom" for p in positions):
        return []

    def last_close(history: dict[str, float], date: str) -> float | None:
        """A holding's unchanged price on ``date``: its last close on or
        before it — exchanges differ (holidays, Tokyo), so a close on the
        calendar day is not guaranteed for every name."""
        dates = sorted(history)
        best = None
        for d in dates:
            if d > date:
                break
            best = d
        return history[best] if best else None

    usable = []
    for p, h in zip(positions, hists):
        fx = p.get("fx") if display else None
        if not h:
            return []
        if display and not fx:
            return []
        if not display:
            pass  # single-currency check done below
        usable.append((p["shares"] * (fx if fx else 1.0), h))
    if not display:
        currencies = {p.get("currency") for p in positions if p.get("currency")}
        if len(currencies) > 1:
            return []
    if not usable:
        return []
    dates = sorted({d for _, h in usable for d in h})
    if len(dates) < 2:
        return []
    totals: dict[str, float] = {}
    for d in dates:
        total = 0.0
        for weighted_shares, h in usable:
            px = last_close(h, d)
            if px is None:
                continue
            total += weighted_shares * px
        totals[d] = total
    step = max(1, len(dates) // 150)
    return [[d, round(totals[d], 2)] for d in dates[::step]]

def _history_for(p: dict, q: dict | None) -> dict[str, float] | None:
    """A year of daily closes for one position, for the interval gains.

    Custom holdings have no exchange history. And when the quote already
    failed, the chart API is the most likely reason — asking it again for
    a bigger range would just burn goodwill, so that is None too.
    """
    if (p.get("kind") or "stock") == "custom" or q is None:
        return None
    return market_data.price_series(
        q.get("resolved_symbol") or p["ticker"], 400)


def _enrich(p: dict, q: dict | None, pool: dict | None,
            display: str = "", hist: dict[str, float] | None = None) -> dict:
    """One saved position + one quote -> one table row.

    Native numbers (price/value/pl/cost) always stay in the holding's
    own currency so editing never rewrites them. When a display
    currency is chosen, ``display_*`` carries the converted copy and
    ``fx`` the rate used. Price null-safe throughout: no quote means
    price/week/value/pl are all None and the row simply shows dashes.
    """
    price = q.get("price") if q else None
    week = q.get("week") if q else None
    shares = p["shares"]
    cost_basis = p.get("cost_basis") or 0.0
    currency = (q.get("currency") if q else None) or p.get("currency")
    value = round(shares * price, 2) if price is not None else None
    cost_total = shares * cost_basis
    pl = round(value - cost_total, 2) if value is not None else None
    pl_pct = (pl / cost_total) if (pl is not None and cost_total > 0) else None

    fx = None
    if display and price is not None and currency:
        fx = market_data.fx_rate(currency, display)

    def conv(x, nd=2):
        return round(x * fx, nd) if (x is not None and fx) else None

    name = (q.get("name") if q else None) or p.get("name") or p["ticker"]

    intervals = _interval_stats(hist, shares)
    # display_* mirrors the main columns: present only when a display
    # currency was chosen, converted with the same rate, dashed when the
    # rate is missing.
    display_intervals = None
    if display:
        display_intervals = {
            k: (None if v is None else {
                **v,
                "pl": conv(v["pl"]),
                "price_then": conv(v["price_then"], 4),
                "price_now": conv(v["price_now"], 4),
            })
            for k, v in intervals.items()
        }

    return {
        **p,
        "name": name,
        "price": price,
        "week": week,
        "value": value,
        "cost_total": round(cost_total, 2),
        "pl": pl,
        "pl_pct": pl_pct,
        "live": price is not None,
        "price_as_of": q.get("as_of") if q else None,
        # True when the price came from the stale-cache fallback (Yahoo
        # was blocked); the UI dates it instead of calling it live.
        "price_stale": bool(q.get("stale")) if q else False,
        "currency": currency,
        "resolved_symbol": q.get("resolved_symbol") if q else None,
        "display_currency": display or None,
        "fx": fx,
        "fx_missing": bool(display and price is not None and currency and fx is None),
        "display_price": conv(price, 4),
        "display_value": conv(value),
        "display_cost_basis": conv(cost_basis, 4),
        "display_cost_total": conv(cost_total),
        "display_pl": conv(pl),
        "display_pl_pct": pl_pct,
        "intervals": intervals,
        "display_intervals": display_intervals,
        "smart": smart_money(p.get("name") or name, pool),
    }


def _interval_totals(positions: list[dict], display: bool) -> dict:
    """Portfolio-level gain per interval, over the rows that have one.

    The same mixed-currency rule as the main total applies to the native
    path: numbers in different currencies don't add up, so the total goes
    dashed (the count of priced rows still tells the truth). With a
    display currency every row is converted first, so everything sums.
    """
    out = {}
    for key, _ in _INTERVALS:
        src = "display_intervals" if display else "intervals"
        # On the display path a missing FX rate leaves the window's
        # numbers None — those rows can't be summed, so they don't count.
        rows = [p for p in positions
                if (p.get(src) or {}).get(key)
                and p[src][key].get("pl") is not None]
        if not rows:
            out[key] = None
            continue
        single = display or len({p.get("currency") for p in rows}) <= 1
        pl = round(sum(p[src][key]["pl"] for p in rows), 2)
        v_then = round(sum(p["shares"] * p[src][key]["price_then"]
                           for p in rows), 2)
        out[key] = {
            "pl": pl if single else None,
            "pl_pct": (pl / v_then) if (single and v_then > 0) else None,
            "value_then": v_then if single else None,
            "priced": len(rows),
        }
    return out


def view(refresh: bool = False, currency: str = "") -> dict:
    """The My-Portfolio tab: every position, enriched, plus totals.

    Quotes fetch in parallel (each is disk-cached 10 minutes, and a
    blocked quote degrades to None rather than an error). The 13F pool
    is the smart-money source; if it can't be read the column goes
    blank instead of sinking the prices.

    ``currency`` switches the totals (and the display columns) into one
    chosen currency through cached Yahoo FX rates. Rows that couldn't
    be priced, or whose rate is missing, stay dashed and are counted in
    ``totals.missing``; the total still sums everything that did price.

    Each row also carries ``intervals``: its 1-week … 1-year gain,
    derived from one ~1.1-year history fetch per symbol (disk-cached
    12 hours, shared with the one-year backtest's cache file). Rows
    without history — custom holdings, blocked fetches — carry all-None
    intervals, and ``totals.intervals`` sums only the rows that have
    each window.
    """
    display = str(currency or "").strip().upper()
    if not _CURRENCY.match(display):
        display = ""

    entries = load_portfolio()
    try:
        pool = funds.scan_pool()
    except Exception:
        pool = None
    ttl = 0.0 if refresh else market_data._QUOTE_TTL
    if entries:
        with ThreadPoolExecutor(max_workers=4) as ex:
            quotes = list(ex.map(lambda p: _quote_for(p, ttl), entries))
            hists = list(ex.map(
                lambda pq: _history_for(*pq), zip(entries, quotes)))
    else:
        quotes, hists = [], []
    positions = [_enrich(p, q, pool, display, h)
                 for p, q, h in zip(entries, quotes, hists)]

    valued = [p for p in positions if p["value"] is not None]
    currencies = {p["currency"] for p in positions if p.get("currency")}
    single = len(currencies) <= 1

    if display:
        priced = [p for p in positions if p["display_value"] is not None]
        missing = len(positions) - len(priced)
        total_value = round(sum(p["display_value"] for p in priced), 2) if priced else None
        total_cost = round(sum(p["display_cost_total"] for p in priced), 2) if priced else None
        total_pl = round(sum(p["display_pl"] for p in priced), 2) if priced else None
        pl_pct = (total_pl / total_cost) if (
            total_pl is not None and total_cost and total_cost > 0) else None
        totals = {
            "value": total_value, "cost": total_cost, "pl": total_pl,
            "pl_pct": pl_pct, "currencies": sorted(currencies),
            "currency": display, "priced": len(priced), "missing": missing,
            "n": len(positions), "complete": missing == 0,
        }
    else:
        total_value = round(sum(p["value"] for p in valued), 2) if valued else None
        total_cost = round(sum(p["shares"] * (p.get("cost_basis") or 0.0)
                               for p in positions), 2)
        total_pl = round(sum(p["pl"] for p in valued), 2) if valued else None
        pl_pct = (total_pl / total_cost) if (
            total_pl is not None and total_cost > 0) else None
        totals = {
            "value": total_value if single else None,
            "cost": total_cost,
            "pl": total_pl if single else None,
            "pl_pct": pl_pct if single else None,
            "currencies": sorted(currencies),
            "currency": next(iter(currencies)) if single and currencies else None,
            "priced": len(valued), "missing": len(positions) - len(valued),
            "n": len(positions), "complete": len(valued) == len(positions),
        }

    totals["intervals"] = _interval_totals(positions, bool(display))

    return {
        "positions": positions,
        "totals": totals,
        "spark": _spark_series(positions, hists, display),
        "n_live": sum(1 for p in positions if p["live"]),
        "as_of_13f": (pool or {}).get("as_of"),
        "n_funds_13f": len((pool or {}).get("funds") or []),
    }


def glance(pool: dict | None = None) -> dict:
    """The home's second tab: where the tracked funds *agree*, *move*,
    and *bet new* this quarter — three pre-sorted highlights, no
    filters (the Scan page is the full table)."""
    pool = pool if pool is not None else funds.scan_pool()
    name_of = {c["key"]: c.get("name") or c["key"] for c in pool.get("funds") or []}
    for r in pool.get("rows") or []:
        name_of.setdefault(r["fund"], r.get("fund_name") or r["fund"])

    def holders(names_or_keys: list[str]) -> list[str]:
        return sorted({name_of.get(k, k) for k in names_or_keys})

    # crowded: aggregate the pool's rows by security, keep 2+ holders
    agg: dict[str, dict] = {}
    for r in pool.get("rows") or []:
        if r.get("status") == "exited" or (r.get("n_funds") or 0) < 2:
            continue
        a = agg.setdefault(r["key"], {
            "name": r.get("issuer") or "?", "class": r.get("class") or "",
            "n_funds": 0, "value": 0.0, "holders": set(), "status": None,
        })
        a["n_funds"] = max(a["n_funds"], r.get("n_funds") or 0)
        a["value"] += r.get("value") or 0.0
        a["holders"].update(r.get("holders") or [])
        if _STATUS_RANK.get(r.get("status") or "", 0) > _STATUS_RANK.get(
                a["status"] or "", 0):
            a["status"] = r.get("status")
    crowded = [
        {"name": a["name"], "class": a["class"], "n_funds": a["n_funds"],
         "value": round(a["value"], 2), "status": a["status"],
         "holders": holders(sorted(a["holders"]))}
        for a in agg.values()
    ]
    crowded.sort(key=lambda c: (-c["n_funds"], -c["value"]))

    def row(r: dict) -> dict:
        return {"name": r.get("issuer") or "?", "class": r.get("class") or "",
                "fund": name_of.get(r["fund"], r["fund"]),
                "status": r.get("status"), "value": r.get("value"),
                "move_value": r.get("move_value"), "change": r.get("change"),
                "n_funds": r.get("n_funds"), "surprise": r.get("surprise")}

    moves = [row(r) for r in (pool.get("biggest_moves") or [])][:8]
    new_bets = [row(r) for r in (pool.get("new_this_quarter") or [])][:8]
    return {
        "as_of": pool.get("as_of"),
        "generated": pool.get("generated"),
        "n_funds": len(pool.get("funds") or []),
        "n_ok": sum(1 for f in pool.get("funds") or [] if "error" not in f),
        "crowded": crowded[:10],
        "moves": moves,
        "new": new_bets,
    }
