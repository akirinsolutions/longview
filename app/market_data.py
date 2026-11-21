"""Market price data — free, no API key.

We read Yahoo Finance's public chart API (the same endpoint the popular
yfinance library uses). Every row is split- and dividend-adjusted, which
matters a lot: a company that pays a 4% dividend would otherwise look like
it crashed 4% on the ex-date.

Data is cached to disk (cache/prices/) so repeat runs are instant and we
don't hammer Yahoo.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

try:
    import zoneinfo
except ImportError:  # pragma: no cover
    zoneinfo = None

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
_PRICE_DIR = CACHE_DIR / "prices"

# Yahoo runs the same API on two hosts, and its rate limiting keys on the
# (IP, User-Agent) pair — so on a 429 we rotate both the host and the
# User-Agent. These are all real, ordinary browser strings: Yahoo serves
# the same chart API to any of them the way it would a person's browser.
_YAHOO_HOSTS = ("query1", "query2")
_YAHOO_USER_AGENTS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "Version/17.4 Safari/605.1.15 (KHTML, like Gecko)",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) "
    "Gecko/20100101 Firefox/126.0",
)
_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                headers={"User-Agent": _YAHOO_USER_AGENTS[0]},
                timeout=30.0,
                follow_redirects=True,
            )
        return _client


def _normalize_symbol(raw: str) -> str:
    """' .aapl ' -> 'AAPL', 'SPY.US' -> 'SPY'."""
    s = (raw or "").strip().upper().lstrip(".")
    for suffix in (".US", ".NASDAQ", ".ARCA", ".NYSE", ".NY", ".L"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def _row_date(ts: float, tz_name: str | None) -> str:
    """Daily bar timestamps are midnight in the exchange's timezone."""
    if tz_name and zoneinfo is not None:
        try:
            return datetime.fromtimestamp(ts, tz=zoneinfo.ZoneInfo(tz_name)).date().isoformat()
        except Exception:
            pass
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def _chunk_rows(res: dict) -> list[tuple[str, float]]:
    """Turn one Yahoo chart response into [(iso_date, adjusted_close)].

    Drops rows with missing prices (trading halts, new listings).
    Prefers Yahoo's split/dividend-adjusted close when available.
    """
    ts = res.get("timestamp") or []
    ind = res.get("indicators", {})
    quote = (ind.get("quote") or [{}])[0]
    adj = (ind.get("adjclose") or [{}])[0]
    close = quote.get("close") or []
    adjv = adj.get("adjclose") or []
    tz_name = (res.get("meta") or {}).get("exchangeTimezoneName")

    out: list[tuple[str, float]] = []
    for i, t in enumerate(ts):
        c = close[i] if i < len(close) else None
        a = adjv[i] if i < len(adjv) else None
        v = a if a is not None else c
        if v is None or v <= 0:
            continue
        out.append((_row_date(t, tz_name), round(float(v), 6)))
    return out


def _fetch_chart(symbol: str, start_epoch: int, end_epoch: int,
                 retries: int = 6) -> dict:
    """One chart fetch, with polite retries. Returns the raw chart result.

    Yahoo rate-limits aggressively, and the limit keys on the (host,
    User-Agent) pair, so a 429 or 5xx is retried a few times with a short
    pause, rotating through hosts and browser identities. A definitive
    'no such symbol' answer is returned as-is (no point re-asking a
    question that has already been answered).
    """
    params = {"period1": start_epoch, "period2": end_epoch, "interval": "1d"}
    last_err = "a transient error"
    for attempt in range(retries):
        host = _YAHOO_HOSTS[attempt % len(_YAHOO_HOSTS)]
        ua = _YAHOO_USER_AGENTS[attempt % len(_YAHOO_USER_AGENTS)]
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}"
        try:
            r = _get_client().get(url, params=params, headers={"User-Agent": ua})
        except httpx.HTTPError as e:
            last_err = f"a network problem ({e.__class__.__name__})"
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            data = r.json()
            res = (data.get("chart", {}).get("result") or [None])[0]
            if res is None:
                err = data.get("chart", {}).get("error") or {}
                desc = err.get("description") or err.get("code") or "no data returned"
                raise RuntimeError(f"Yahoo has no data for '{symbol}' ({desc})")
            return res
        if r.status_code in (429, 500, 502, 503, 504):
            last_err = f"Yahoo is busy or rate-limiting (HTTP {r.status_code})"
            time.sleep(1.5 * (attempt + 1))
            continue
        raise RuntimeError(f"Yahoo returned HTTP {r.status_code} for {symbol}")
    raise RuntimeError(f"Could not reach Yahoo for {symbol}: {last_err}. Try again in a minute.")


def _fetch_range(symbol: str, start_epoch: int, end_epoch: int) -> list[tuple[str, float]]:
    return _chunk_rows(_fetch_chart(symbol, start_epoch, end_epoch))


def _cache_path(symbol: str, years: float) -> Path:
    _PRICE_DIR.mkdir(parents=True, exist_ok=True)
    return _PRICE_DIR / f"price_{symbol}_{int(years * 10)}.json"


# ---------------------------------------------------------------------------
# Live quotes: one symbol, one small fetch (14 days of daily bars)
#
# This is the path the portfolio uses: current price, the company's name,
# and the one-week move. Cheap, disk-cached for 10 minutes, and it NEVER
# raises. When Yahoo is blocked we serve the last good price from the
# cache, up to a week old, flagged ``stale`` so the UI can date it; only
# a week of total silence earns an em dash.
# ---------------------------------------------------------------------------

_QUOTE_TTL = 600.0  # 10 minutes is fresh enough for a personal portfolio

# A stale-but-sound number beats an em dash. When a fresh fetch fails, the
# last good cache is served up to this old (a week of stale is already too
# old for a price); anything older falls back to the dash, as before.
_STALE_MAX = 7 * 86400.0


def _quote_from_res(symbol: str, res: dict, fetched: int) -> dict | None:
    """Build one quote from a raw Yahoo chart result. Pure (testable).

    `week` uses *unadjusted* closes: a stock split in the last week leaves
    the ratio correct, and a dividend in that window is a rounding error.
    `price` is the official live price from the meta block, falling back
    to the last bar.
    """
    meta = res.get("meta") or {}
    ts = res.get("timestamp") or []
    closes = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    tz = meta.get("exchangeTimezoneName")

    price = meta.get("regularMarketPrice")
    if price is None:
        for c in reversed(closes):
            if c is not None:
                price = c
                break
    if price is None or price <= 0:
        return None

    week = None
    good = [(t, c) for t, c in zip(ts, closes) if c is not None and c > 0]
    if len(good) >= 6:
        week = price / good[-6][1] - 1.0  # 5 trading days back
    as_of = _row_date(good[-1][0], tz) if good else None

    return {
        "symbol": symbol,
        "name": meta.get("longName") or meta.get("shortName") or None,
        "price": round(float(price), 4),
        "week": round(week, 6) if week is not None else None,
        "as_of": as_of,
        "exchange": meta.get("exchangeName"),
        "currency": meta.get("currency"),
        "fetched": fetched,
    }


def _read_quote_cache(path: Path, s: str, max_age: float) -> dict | None:
    """The quote in a cache file, or None when missing, corrupted, for
    another symbol, price-less, or older than ``max_age``. Never raises.
    """
    try:
        d = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if d.get("symbol") != s or not d.get("price"):
        return None
    if time.time() - path.stat().st_mtime > max_age:
        return None
    return d


def quote(symbol: str, cache_ttl: float = _QUOTE_TTL,
          name_hint: str | None = None) -> dict | None:
    """Current price + name + one-week move. When Yahoo can't be reached,
    the last known price from the cache, flagged ``stale``, if it is under
    a week old. Never raises. Disk-cached for 10 minutes under cache/prices/.

    A bare ticker that doesn't resolve (``VDST``) is retried once through
    Yahoo's search, using the saved name when there is one: UK/European
    listings need their exchange suffix (``VDST.L``), and typing just the
    ticker is an easy mistake. The resolved symbol rides back on the quote
    so the UI can say what it used.
    """
    s = _normalize_symbol(symbol)
    if not s:
        return None
    _PRICE_DIR.mkdir(parents=True, exist_ok=True)
    path = _PRICE_DIR / f"quote_{s}.json"
    now = time.time()
    fresh = _read_quote_cache(path, s, cache_ttl)
    if fresh:
        return fresh

    try:
        res = _fetch_chart(s, int(now - 14 * 86400), int(now))
    except Exception:
        res = None
    resolved = None
    if res is None:
        resolved = _resolve_symbol(s, name_hint)
        if resolved:
            try:
                res = _fetch_chart(resolved, int(now - 14 * 86400), int(now))
            except Exception:
                res = None
    if res is None:
        # Yahoo is blocked: the last good price, up to a week old, is still
        # better than nothing — flag it so the UI can date it.
        stale = _read_quote_cache(path, s, _STALE_MAX)
        if stale:
            return {**stale, "stale": True}
        return None  # 429s exhausted, no such symbol, network: same answer
    out = _quote_from_res(s, res, int(now))
    if out is None:
        return None
    if resolved:
        out["resolved_symbol"] = resolved
    try:
        path.write_text(json.dumps(out))
    except OSError:
        pass  # caching is a convenience, not a requirement
    return out


# A bare ticker (no dot) that Yahoo couldn't chart may simply be missing its
# exchange suffix. Search for it and accept a candidate only when the base
# symbol matches and, if we know the saved name, the names agree.
_resolved: dict[str, str] = {}


def _name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(t) > 1}


def _resolve_symbol(symbol: str, name_hint: str | None = None) -> str | None:
    """``VDST`` -> ``VDST.L`` (or another exchange) when Yahoo agrees.

    Conservative on purpose: never swap a working ticker, never accept a
    different company. Pure-ish (one cached search), never raises.
    """
    if "." in symbol:
        return None
    if symbol in _resolved:
        return _resolved[symbol]
    try:
        cands = search(symbol)
    except Exception:
        return None
    if not cands:
        return None
    base = symbol.split(".")[0]
    want = _name_tokens(name_hint or "")
    best, best_score = None, 0.0
    for c in cands:
        sym = (c.get("symbol") or "").upper()
        if not sym.startswith(base + "."):
            continue
        got = _name_tokens(c.get("name") or "")
        if want and got:
            overlap = len(want & got) / max(1, len(want))
            if overlap <= 0:
                continue          # same letters, different company: no
            score = 2.0 + overlap
        else:
            score = 1.0
        if score > best_score:
            best, best_score = sym, score
    if best:
        _resolved[symbol] = best
    return best


# ---------------------------------------------------------------------------
# Currency conversion: one cached rate per pair, straight from Yahoo's FX
# charts (``EURUSD=X``). A missing rate is None — the caller keeps the
# native number and says it couldn't convert, never invents a value.
# ---------------------------------------------------------------------------

_FX_TTL = 3600.0
_fx_mem: dict[tuple[str, str], tuple[float, float | None]] = {}
_fx_lock = threading.Lock()


def _fx_from_res(res: dict | None) -> float | None:
    if not res:
        return None
    meta = res.get("meta") or {}
    px = meta.get("regularMarketPrice")
    if px is None:
        closes = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        for c in reversed(closes):
            if c is not None and c > 0:
                px = c
                break
    if px is None or px <= 0:
        return None
    return float(px)


def _read_fx_cache(path: Path, base: str, quote: str, max_age: float) -> float | None:
    """The last known rate in a cache file, or None when missing, corrupted,
    for another pair, rate-less, or older than ``max_age``. Never raises.
    """
    try:
        d = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if d.get("base") != base or d.get("quote") != quote:
        return None
    rate = d.get("rate")
    if rate is None:
        return None
    if time.time() - path.stat().st_mtime > max_age:
        return None
    return float(rate)


def fx_rate(base: str, quote: str) -> float | None:
    """How many ``quote`` units one ``base`` unit buys. Cached one hour.

    Yahoo's FX symbols put the base first (``EURUSD=X``); when only the
    inverse exists the rate is simply flipped. When Yahoo is blocked, the
    last known rate, up to a week old, is served instead of None: a stale
    rate converts a little off; a dash converts to nothing.
    """
    base = (base or "").upper()
    quote = (quote or "").upper()
    if not base or not quote:
        return None
    if base == quote:
        return 1.0
    key = (base, quote)
    now = time.time()
    with _fx_lock:
        hit = _fx_mem.get(key)
        if hit and now - hit[0] < _FX_TTL:
            return hit[1]

    _PRICE_DIR.mkdir(parents=True, exist_ok=True)
    path = _PRICE_DIR / f"fx_{base}_{quote}.json"
    if path.exists() and now - path.stat().st_mtime < _FX_TTL:
        try:
            d = json.loads(path.read_text())
            if d.get("base") == base and d.get("quote") == quote:
                rate = d.get("rate")
                with _fx_lock:
                    _fx_mem[key] = (now, rate)
                return rate
        except (json.JSONDecodeError, OSError):
            pass

    rate = None
    ok = False
    for sym, invert in ((f"{base}{quote}=X", False),
                        (f"{quote}{base}=X", True)):
        try:
            res = _fetch_chart(sym, int(now - 7 * 86400), int(now), retries=2)
        except Exception:
            continue
        px = _fx_from_res(res)
        if px:
            rate = 1.0 / px if invert else px
            ok = True
            break
    if not ok:
        # Yahoo is blocked: the last known rate, up to a week old. A stale
        # rate converts a little off; a dash converts to nothing.
        rate = _read_fx_cache(path, base, quote, _STALE_MAX)
    with _fx_lock:
        _fx_mem[key] = (now, rate)
    if ok:
        try:
            path.write_text(json.dumps(
                {"base": base, "quote": quote,
                 "rate": rate, "fetched": int(now)}))
        except OSError:
            pass  # caching is a convenience, not a requirement
    return rate



# Yahoo's search endpoint: name -> candidate tickers, for the add-position
# box. Same rotation and retry discipline as the chart API. The in-memory
# cache is short (2 min) and keyed on the lowercase query, since this is
# typed at with a debounce.
_SEARCH_TTL = 120.0
_search_cache: dict[str, tuple[float, list[dict] | None]] = {}
_search_lock = threading.Lock()

_US_EXCHANGES = {"NMS", "NGM", "PCX"}  # Nasdaq, NYSE, ARCA


def _search_from_json(data: dict, limit: int = 8) -> list[dict]:
    """One search response -> clean candidates. Pure (testable).

    Keeps stocks and ETFs only (futures, indices and currencies are noise
    for a personal portfolio). US listings come first; if the query has no
    US candidates at all, the others still show (better "SAP (XETRA)"
    than nothing).
    """
    keep = []
    for q in (data.get("quotes") or []):
        sym = (q.get("symbol") or "").strip()
        if not sym:
            continue
        t = (q.get("quoteType") or "").upper()
        if t not in ("EQUITY", "ETF"):
            continue
        exch = q.get("primaryExchange") or q.get("exchchng") or ""
        us = (exch in _US_EXCHANGES) or ("." not in sym)
        name = q.get("longname") or q.get("shortname") or sym
        keep.append({"symbol": sym, "name": name,
                     "type": q.get("typeDisp") or t.title(),
                     "exchange": exch or None, "us": us})
    keep.sort(key=lambda x: not x["us"])
    for c in keep:
        c.pop("us")
    return keep[:limit]


def search(q: str, limit: int = 8) -> list[dict] | None:
    """Candidate tickers for a name. [] when Yahoo knows nothing, None
    when Yahoo itself can't be reached. Never raises.
    """
    q = (q or "").strip()
    if len(q) < 2:
        return []
    limit = max(1, min(int(limit), 12))
    key = q.lower()
    with _search_lock:
        hit = _search_cache.get(key)
        if hit and time.time() - hit[0] < _SEARCH_TTL:
            return None if hit[1] is None else hit[1][:limit]

    out: list[dict] | None = None
    last_err = "a transient error"
    for attempt in range(6):
        host = _YAHOO_HOSTS[attempt % len(_YAHOO_HOSTS)]
        ua = _YAHOO_USER_AGENTS[attempt % len(_YAHOO_USER_AGENTS)]
        try:
            r = _get_client().get(
                f"https://{host}.finance.yahoo.com/v1/finance/search",
                params={"q": q, "quotesCount": 12},
                headers={"User-Agent": ua})
        except httpx.HTTPError as e:
            last_err = f"a network problem ({e.__class__.__name__})"
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            out = _search_from_json(r.json(), limit)
            break
        if r.status_code in (429, 500, 502, 503, 504):
            last_err = f"Yahoo is busy or rate-limiting (HTTP {r.status_code})"
            time.sleep(1.5 * (attempt + 1))
            continue
        # Anything else (a 401/403/404) is not worth retrying. The search
        # box should see "Yahoo is unreachable" (None), never an error.
        last_err = f"Yahoo refused the search (HTTP {r.status_code})"
        break
    if out is None:
        with _search_lock:
            _search_cache[key] = (time.time(), None)
        return None
    with _search_lock:
        _search_cache[key] = (time.time(), out)
    return out


def fetch_history(symbol: str, years: float = 10, cache_ttl_hours: float = 12.0,
                  normalize: bool = True) -> dict[str, float]:
    """Daily split/dividend-adjusted closes for the last N years.

    Returns {iso_date: adjusted_close} sorted by date.
    Cached on disk; a copy newer than `cache_ttl_hours` is reused.
    Raises RuntimeError with a friendly message when the symbol is unknown.

    ``normalize=False`` uses the symbol as given (whitespace and case
    cleaned, but exchange suffixes like ``.L`` kept) — for symbols that
    already came from Yahoo itself, such as a quote's ``resolved_symbol``.
    """
    s = _normalize_symbol(symbol) if normalize else (symbol or "").strip().upper()
    if not s:
        raise RuntimeError("No ticker given")
    if years <= 0 or years > 20:
        years = min(max(years, 1.0), 20.0)

    path = _cache_path(s, years)
    if path.exists():
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        if age_h < cache_ttl_hours:
            try:
                cached = json.loads(path.read_text())
                if cached.get("symbol") == s and len(cached.get("data") or {}) > 10:
                    return dict(cached["data"])
            except (json.JSONDecodeError, OSError):
                pass  # corrupted cache: refetch

    now = time.time()
    total_span = years * 365.25 * 86400
    chunk_span = 10 * 365.25 * 86400  # 10-year chunks keep each request small
    merged: dict[str, float] = {}
    cursor = now
    while cursor > now - total_span:
        start = max(now - total_span, cursor - chunk_span)
        for d, v in _fetch_range(s, int(start), int(cursor)):
            merged[d] = v
        cursor = start

    if not merged:
        raise RuntimeError(f"No price history found for '{s}'")

    data = {d: merged[d] for d in sorted(merged)}
    try:
        path.write_text(json.dumps({"symbol": s, "fetched": int(time.time()), "data": data}))
    except OSError:
        pass  # caching is a convenience, not a requirement
    return data


def price_series(symbol: str, days: int = 400,
                 cache_ttl_hours: float = 12.0) -> dict[str, float] | None:
    """Daily split/dividend-adjusted closes for the last `days` days, or None.

    The portfolio's interval gains derive their 1-week … 1-year windows
    from one such series. The 400-day default lands on the same disk
    cache as a one-year backtest, so the portfolio and the lab share
    history instead of fetching it twice. Never raises — a blocked or
    unknown symbol means "no history" (dashes), the same discipline as
    quote().

    The symbol is used as-is, suffix and all: callers pass a symbol
    Yahoo already resolved (a quote's ``resolved_symbol``), and for
    LSE-listed funds such as ``CSPX.L`` the ``.L`` is exactly what
    distinguishes the fund from a bare ticker — which 404s.

    When the fetch fails (a 429 burst), the last good file, up to a week
    old, is served instead: daily closes change once a day, so a day or
    two of staleness is usually the very same data a fetch would return.
    ``fetch_history`` itself keeps raising — the lab's backtests would
    rather fail loudly than run on stale numbers.
    """
    s = (symbol or "").strip().upper()
    if not s:
        return None
    years = days / 365.25
    try:
        return fetch_history(s, years=years,
                             cache_ttl_hours=cache_ttl_hours, normalize=False)
    except Exception:
        pass  # fall through to the stale file
    path = _cache_path(s, years)
    try:
        d = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    data = d.get("data") or {}
    if d.get("symbol") != s or len(data) <= 10:
        return None
    if time.time() - path.stat().st_mtime > _STALE_MAX:
        return None
    return {k: data[k] for k in sorted(data)}


# ---------------------------------------------------------------------------
# Company pages: the "little parts" behind a stock
#
# Yahoo's quote and quoteSummary endpoints demand a one-time credential
# exchange since 2023: fetch a page that sets a cookie, then ask for a
# short "crumb" token, then send both. We do that exchange ourselves,
# remember the pair for six hours (memory + disk, so a restart doesn't
# re-ask), and treat every failure as "those numbers are unavailable
# right now". Each part degrades independently; the page still renders,
# just with dashes. Same never-raises discipline as quote().
# ---------------------------------------------------------------------------

_CRUMB_TTL = 6 * 3600.0
_COMPANY_TTL = 900.0  # 15 minutes is fresh enough for a company page
_crumb_state: dict | None = None
_crumb_lock = threading.Lock()


def _crumb_path() -> Path:
    _PRICE_DIR.mkdir(parents=True, exist_ok=True)
    return _PRICE_DIR / "_crumb.json"


def _fetch_crumb() -> dict | None:
    """One cookie + crumb exchange, with the usual host/UA rotation.
    Returns ``{cookie, crumb, ua, ts}`` or None. Never raises."""
    for attempt in range(4):
        host = _YAHOO_HOSTS[attempt % len(_YAHOO_HOSTS)]
        ua = _YAHOO_USER_AGENTS[attempt % len(_YAHOO_USER_AGENTS)]
        try:
            c = _get_client()
            # fc.yahoo.com 404s on purpose — the point is the cookie it sets.
            c.get("https://fc.yahoo.com", headers={"User-Agent": ua},
                  timeout=15.0)
            cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
            r = c.get(f"https://{host}.finance.yahoo.com/v1/test/getcrumb",
                      headers={"User-Agent": ua}, timeout=15.0)
        except httpx.HTTPError:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            text = r.text.strip()
            # A real crumb is one bare token; error bodies ("Too Many
            # Requests", JSON) contain a space or a brace.
            if text and " " not in text and "{" not in text:
                return {"cookie": cookie, "crumb": text, "ua": ua,
                        "ts": time.time()}
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(1.5 * (attempt + 1))
            continue
        return None  # a definitive refusal: don't keep asking
    return None


def _crumb(force: bool = False) -> dict | None:
    """A valid crumb pair from memory or disk, else a fresh exchange."""
    global _crumb_state
    with _crumb_lock:
        st = _crumb_state
        if st and not force and time.time() - st["ts"] < _CRUMB_TTL:
            return st
        if st is None:  # a restart shouldn't re-ask for a still-valid crumb
            try:
                d = json.loads(_crumb_path().read_text())
                if d.get("crumb") and time.time() - d.get("ts", 0) < _CRUMB_TTL:
                    _crumb_state = st = d
                    return st
            except (OSError, json.JSONDecodeError):
                pass
        st = _fetch_crumb()
        if st is not None:
            _crumb_state = st
            try:
                _crumb_path().write_text(json.dumps(st))
            except OSError:
                pass
        else:
            _crumb_state = None
        return st


def _invalidate_crumb() -> None:
    """A 401 means the pair went stale: drop it so the next call re-exchanges."""
    global _crumb_state
    with _crumb_lock:
        _crumb_state = None
        try:
            _crumb_path().unlink()
        except OSError:
            pass


def _crumb_headers(st: dict | None) -> dict:
    h = {"User-Agent": st["ua"]} if st else {}
    if st and st.get("cookie"):
        h["Cookie"] = st["cookie"]
    return h


def _crumb_get(path: str, symbol: str, params: dict, force: bool = False) -> dict | None:
    """One crumb-protected GET (v8 quote / v10 quoteSummary).

    Retries transient failures with rotation, re-exchanges the crumb on
    a 401 once, and returns the parsed JSON object or None. Never raises.
    """
    st = _crumb(force=force)
    if st is None:
        return None
    for attempt in range(3):
        host = _YAHOO_HOSTS[attempt % len(_YAHOO_HOSTS)]
        ua = st["ua"] if attempt == 0 else _YAHOO_USER_AGENTS[
            attempt % len(_YAHOO_USER_AGENTS)]
        try:
            r = _get_client().get(
                f"https://{host}.finance.yahoo.com{path}",
                params={**params, "crumb": st["crumb"]},
                headers={"User-Agent": ua,
                         **({"Cookie": st["cookie"]} if st.get("cookie") else {})},
                timeout=20.0)
        except httpx.HTTPError:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except json.JSONDecodeError:
                return None
        if r.status_code == 401 and attempt == 0:
            _invalidate_crumb()  # stale pair: re-exchange and try once more
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(1.5 * (attempt + 1))
            continue
        return None  # 403/404 and friends: a definite no
    return None


def _opt(x) -> float | None:
    """A finite number rounded for display, or None (Yahoo writes nulls
    freely; a NaN would poison the JSON, so it is filtered here).

    The quoteSummary endpoint wraps every number as `{"raw": 1.23,
    "fmt": "1.23"}`; the older quote endpoint sends bare numbers. Both
    shapes mean the same thing, so unwrap the wrapper here once.
    """
    if isinstance(x, dict):
        x = x.get("raw")
    if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x:
        return round(float(x), 6)
    return None


def _pct(x) -> float | None:
    """Yahoo sends yields/margins as fractions in some modules and as
    plain percents in others. Prefer the formatted "12.34%" when it is
    present (unambiguous), else read a value below 1 as a fraction."""
    if isinstance(x, dict):
        fmt = x.get("fmt")
        if isinstance(fmt, str) and fmt.strip().endswith("%"):
            try:
                return round(float(fmt.strip().rstrip("%")), 2)
            except ValueError:
                pass
    v = _opt(x)
    if v is None:
        return None
    return round(v * 100 if v < 1.0 else v, 2)


def _clip_about(about: str, limit: int = 400) -> str:
    """The company's story, shortened to fit the page: tidy the spacing,
    and if it is longer than `limit`, stop at a sentence (or clause)
    boundary and mark the cut with an ellipsis — never mid-word."""
    about = " ".join(about.split())
    if len(about) <= limit:
        return about
    cut = about[:limit]
    for end in (". ", "; ", ", ", " "):
        i = cut.rfind(end)
        if i > limit // 2:
            cut = cut[: i + len(end)] if end == ". " else cut[:i]
            break
    return cut.rstrip(" ,;:–-") + "…"


def _blank_company(symbol: str) -> dict:
    """Every part of a company page, all None: the shape the front end
    renders against, where any None becomes a dash."""
    return {
        "symbol": symbol or None, "name": None, "price": None,
        "change": None, "change_pct": None, "day_range": None,
        "week52": None, "market_cap": None, "pe": None, "eps": None,
        "div_yield": None, "ma50": None, "ma200": None,
        "volume": None, "avg_volume": None, "next_earnings": None,
        "revenue": None,
        "free_cash_flow": None, "shares_outstanding": None,
        "total_cash": None, "total_debt": None,
        "revenue_growth": None, "financial_currency": None,
        "margins": {"gross": None, "operating": None, "net": None},
        "employees": None, "sector": None, "industry": None,
        "hometown": None, "website": None, "about": None,
        "currency": None, "market_time": None,
        "returns": None, "history": [],
    }


def _merge_quote(c: dict, q: dict | None) -> None:
    """The v8/quote object: the market's numbers. Pure (testable)."""
    if not q:
        return
    c["name"] = q.get("shortName") or c["name"]
    c["price"] = _opt(q.get("regularMarketPrice")) or c["price"]
    c["change"] = _opt(q.get("regularMarketChange"))
    c["change_pct"] = _opt(q.get("regularMarketChangePercent"))
    lo, hi = q.get("regularMarketDayLow"), q.get("regularMarketDayHigh")
    if lo is not None and hi is not None:
        c["day_range"] = [round(float(lo), 4), round(float(hi), 4)]
    lo, hi = q.get("fiftyTwoWeekLow"), q.get("fiftyTwoWeekHigh")
    if lo is not None and hi is not None:
        c["week52"] = [round(float(lo), 4), round(float(hi), 4)]
    c["market_cap"] = _opt(q.get("marketCap"))
    c["pe"] = _opt(q.get("trailingPE")) or c["pe"]
    c["eps"] = _opt(q.get("epsTrailingTwelveMonths")) or c["eps"]
    c["div_yield"] = _pct(q.get("dividendYield")) or c["div_yield"]
    c["ma50"] = _opt(q.get("fiftyDayAverage")) or c["ma50"]
    c["ma200"] = _opt(q.get("twoHundredDayAverage")) or c["ma200"]
    c["volume"] = _opt(q.get("regularMarketVolume")) or _opt(q.get("regularVolume"))
    c["avg_volume"] = _opt(q.get("averageDailyVolume3Month")) or c["avg_volume"]
    c["currency"] = q.get("currency") or c["currency"]
    c["sector"] = q.get("sector") or c["sector"]
    c["industry"] = q.get("industry") or c["industry"]
    t = q.get("regularMarketTime")
    if isinstance(t, (int, float)) and t:
        c["market_time"] = int(t)


def _merge_summary(c: dict, s: dict | None) -> None:
    """The v10/quoteSummary object: the company's numbers. Pure
    (testable). Applied after _merge_quote: it fills gaps and adds what
    the quote endpoint doesn't carry (revenue, margins, people, place,
    the story)."""
    if not s:
        return
    sd = s.get("summaryDetail") or {}
    kd = s.get("defaultKeyStatistics") or {}
    fd = s.get("financialData") or {}
    ap = s.get("assetProfile") or {}
    ce = s.get("calendarEvents") or {}
    pr = s.get("price") or {}

    c["name"] = ap.get("name") or pr.get("longName") or pr.get("shortName") or c["name"]
    if c["price"] is None:
        c["price"] = _opt(pr.get("regularMarketPrice"))
    if c["change"] is None:
        c["change"] = _opt(pr.get("regularMarketChange"))
    if c["change_pct"] is None:
        c["change_pct"] = _opt(pr.get("regularMarketChangePercent"))
    if c["day_range"] is None:
        dr = sd.get("dayRange") or {}
        lo = _opt(dr.get("lower")) or _opt(pr.get("regularMarketDayLow"))
        hi = _opt(dr.get("upper")) or _opt(pr.get("regularMarketDayHigh"))
        if lo is not None and hi is not None:
            c["day_range"] = [lo, hi]
    if c["week52"] is None:
        w = sd.get("fiftyTwoWeekRange") or {}
        lo = _opt(w.get("lower")) or _opt(sd.get("fiftyTwoWeekLow"))
        hi = _opt(w.get("upper")) or _opt(sd.get("fiftyTwoWeekHigh"))
        if lo is not None and hi is not None:
            c["week52"] = [lo, hi]
    if c["ma50"] is None:
        c["ma50"] = _opt(sd.get("fiftyDayAverage"))
    if c["ma200"] is None:
        c["ma200"] = _opt(sd.get("twoHundredDayAverage"))
    if c["pe"] is None:
        c["pe"] = _opt(sd.get("trailingPE"))
    if c["eps"] is None:
        c["eps"] = _opt(kd.get("trailingEps")) or _opt(kd.get("epsTrailing12Months"))
    if c["div_yield"] is None:
        dy = sd.get("dividendYield")
        if isinstance(dy, dict):          # current shape: {"raw","fmt"}
            c["div_yield"] = _pct(dy)
        else:                             # legacy shape already speaks percents
            v = _opt(dy)
            c["div_yield"] = round(v, 2) if v is not None else None
    if c["volume"] is None:
        c["volume"] = _opt(sd.get("volume")) or _opt(pr.get("regularMarketVolume"))
    if c["avg_volume"] is None:
        c["avg_volume"] = _opt(sd.get("averageVolume"))
    if c["market_cap"] is None:
        c["market_cap"] = _opt(sd.get("marketCap")) or _opt(pr.get("marketCap"))
    t = pr.get("regularMarketTime")
    if c["market_time"] is None and isinstance(t, (int, float)) and t:
        c["market_time"] = int(t)
    if c["currency"] is None:
        c["currency"] = pr.get("currency")
    c["revenue"] = _opt(fd.get("totalRevenue"))
    c["free_cash_flow"] = _opt(fd.get("freeCashflow"))
    c["shares_outstanding"] = _opt(kd.get("sharesOutstanding"))
    c["total_cash"] = _opt(fd.get("totalCash"))
    c["total_debt"] = _opt(fd.get("totalDebt"))
    c["revenue_growth"] = _pct(fd.get("revenueGrowth"))
    c["financial_currency"] = fd.get("financialCurrency") or c["currency"]
    m = c["margins"]
    m["gross"] = _pct(fd.get("grossMargins"))
    m["operating"] = _pct(fd.get("operatingMargins"))
    m["net"] = _pct(fd.get("profitMargins"))
    c["employees"] = _opt(ap.get("fullTimeEmployees"))
    c["sector"] = ap.get("sector") or c["sector"]
    c["industry"] = ap.get("industry") or c["industry"]
    place = ", ".join(x for x in (ap.get("city"), ap.get("state"),
                                  ap.get("country")) if x)
    c["hometown"] = place or c["hometown"]
    c["website"] = ap.get("website") or c["website"]
    about = ap.get("longBusinessSummary")
    if about:
        c["about"] = _clip_about(about)
    dates = ce.get("earningsDate") or (ce.get("earnings") or {}).get("earningsDate") or []
    if isinstance(dates, dict):        # older shapes wrapped it once more
        dates = dates.get("earningsDate") or []
    if isinstance(dates, list) and dates:
        d = dates[0]
        if isinstance(d, dict):        # shapes seen: {epochDate} / {raw}
            d = d.get("epochDate") or d.get("raw")
        if isinstance(d, str) and d:
            c["next_earnings"] = d
        elif isinstance(d, (int, float)) and d:
            c["next_earnings"] = datetime.fromtimestamp(
                d, tz=timezone.utc).date().isoformat()


def _returns_from_history(history: list[tuple[str, float]]) -> dict | None:
    """1-month / YTD / 1-year returns from daily closes. Pure (testable).
    None whenever the history is too short to be honest about it."""
    if len(history) < 10:
        return None
    last = history[-1][1]
    if last <= 0:
        return None
    out: dict[str, float | None] = {"1m": None, "ytd": None, "1y": None}

    def back(days: int) -> float | None:
        for d, v in reversed(history[:-1]):
            if (datetime.fromisoformat(history[-1][0])
                - datetime.fromisoformat(d)).days >= days:
                return v
        return None

    m = back(28)
    if m:
        out["1m"] = round(last / m - 1.0, 6)
    year = history[-1][0][:4]
    prior = [v for d, v in history if d[:4] == str(int(year) - 1)]
    if prior:
        out["ytd"] = round(last / prior[-1] - 1.0, 6)
    year_ago = back(360)
    if year_ago:
        out["1y"] = round(last / year_ago - 1.0, 6)
    return out


def _company_from_parts(symbol: str, quote: dict | None,
                        summary: dict | None, res: dict | None,
                        history: list[tuple[str, float]]) -> dict:
    """Assemble one company page from its (possibly missing) parts.
    Pure (testable): the network lives in company(), the shape here."""
    out = _blank_company(symbol)
    _merge_quote(out, quote)
    _merge_summary(out, summary)
    if res and out["name"] is None:
        meta = res.get("meta") or {}
        out["name"] = meta.get("longName") or meta.get("shortName")
    if history:
        out["history"] = [{"d": d, "c": c} for d, c in history[-260:]]
        out["returns"] = _returns_from_history(history)
    return out


def company(symbol: str, cache_ttl: float = _COMPANY_TTL) -> dict:
    """Everything the company page shows, in one call. Never raises.

    Three independent parts, each degrading to None when Yahoo is busy:
    the quote (crumb-protected), the quoteSummary (crumb-protected), and
    a year of chart history (plain chart API — it also doubles as the
    chart the page draws and the 1m/YTD/1y returns). A part that comes
    back is a part you see; a blocked part is a dash, never an error.
    Disk-cached for 15 minutes, but only when at least one part landed.
    """
    s = _normalize_symbol(symbol)
    if not s:
        return _blank_company("")
    _PRICE_DIR.mkdir(parents=True, exist_ok=True)
    path = _PRICE_DIR / f"company_{s}.json"
    now = time.time()
    if path.exists():
        if now - path.stat().st_mtime < cache_ttl:
            try:
                d = json.loads(path.read_text())
                if d.get("symbol") == s:
                    return d
            except (json.JSONDecodeError, OSError):
                pass  # corrupted cache: refetch

    st = _crumb()
    quote = _crumb_get("/v8/finance/quote", s, {"symbols": s}) if st else None
    if isinstance(quote, dict):
        result = (quote.get("quoteResponse") or {}).get("result") or []
        quote = result[0] if result else None
    summary = None
    if st:
        raw = _crumb_get(
            f"/v10/finance/quoteSummary/{s}", s,
            {"modules": "price,summaryDetail,defaultKeyStatistics,"
                        "financialData,assetProfile,calendarEvents"})
        if isinstance(raw, dict):
            results = (raw.get("quoteSummary") or {}).get("result") or []
            summary = results[0] if results else None

    history: list[tuple[str, float]] = []
    res: dict | None = None
    try:
        res = _fetch_chart(s, int(now - 370 * 86400), int(now), retries=3)
        history = _chunk_rows(res)
    except Exception:
        res = None  # no chart: the page still renders, minus the chart

    out = _company_from_parts(s, quote, summary, res, history)
    if out["price"] is not None or out["history"]:
        try:
            path.write_text(json.dumps(out))
        except OSError:
            pass  # caching is a convenience, not a requirement
    return out
