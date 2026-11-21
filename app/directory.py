"""The 13F filer directory: a searchable snapshot of who files 13Fs.

Where the data comes from
-------------------------
The SEC publishes a *daily index* of everything filed with EDGAR. Each
business day has a small master file (a pipe-separated line per filing):

    CIK | filer name | form | filing date (YYYYMMDD) | accession path

    1009016|FORT WASHINGTON INVESTMENT ADVISORS INC /OH/|13F-HR|20261015|\
edgar/data/1009016/0001193125-26-422223.txt

Each calendar quarter's ``index.json`` lists exactly which business days
have a file (weekends and holidays are simply absent), so building the
directory is a bounded crawl: the master files of the last two quarters
(~85–90 files of 50–100 KB). We keep the 13F-family forms and dedupe by
CIK, keeping each filer's most recent *holdings* filing — a 13F-NT is a
"we're not filing this quarter" note and loses to a 13F-HR on the same
day. The result: roughly a thousand+ filers, refreshed at most once a day.

Search is instant and local (substring on name or CIK) — no per-keystroke
call to the SEC.

The directory is a *catalog*: it is what you search. The list of funds
that is actually scanned lives in ``data/roster.json`` (see funds.py).
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import date
from pathlib import Path

import httpx

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "directory"

# Same declared identity funds.py uses — the SEC asks automated clients
# to identify themselves (and blocks the anonymous ones).
EDGAR_UA = "Longview (open source, research use; contact: user@example.com)"

TTL = 24 * 3600          # a day of filings; the directory is a moving target
_VERSION = 1             # bump when the snapshot shape changes

_client: httpx.Client | None = None
_lock = threading.Lock()


class DirectoryError(RuntimeError):
    """A plain-English explanation, safe to show in the UI."""


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            headers={"User-Agent": EDGAR_UA}, timeout=30.0, follow_redirects=True
        )
    return _client


def _cached_read(name: str, ttl: float = TTL) -> str | None:
    path = CACHE_DIR / name
    try:
        if path.exists() and time.time() - path.stat().st_mtime < ttl:
            return path.read_text()
    except OSError:
        return None
    return None


def _cached_write(name: str, text: str) -> None:
    with _lock:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_DIR / (name + ".tmp")
        tmp.write_text(text)
        tmp.replace(CACHE_DIR / name)


# ---------------------------------------------------------------------------
# Building the snapshot
# ---------------------------------------------------------------------------

def _http_text(url: str) -> str | None:
    """Fetch one file from the SEC, the way they ask us to.

    The SEC politely rate-limits bursts: a 503 (or a 403 block page) means
    "slow down", so we wait a little longer and retry. A 404 means the file
    genuinely doesn't exist (the weekends have no master file), so we return
    None and let the caller skip that day.
    """
    last = 0
    for attempt in range(3):
        r = _get_client().get(url, timeout=30.0, follow_redirects=True)
        last = r.status_code
        if r.status_code == 200:
            return r.text
        if r.status_code == 404:
            return None  # really absent; not worth a retry
        time.sleep(2.0 * (attempt + 1))  # 503/403: slow down, then try again
    raise DirectoryError(
        f"The SEC's index didn't answer (HTTP {last}) for {url}")


def quarter_days(year: int, qtr: int) -> list[str]:
    """Business days in the quarter that have a master index file (YYYYMMDD)."""
    name = f"qtr_{year}q{qtr}.json"
    if (t := _cached_read(name)) is not None:
        return json.loads(t)["days"]
    url = f"https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{qtr}/index.json"
    try:
        text = _http_text(url)
    except DirectoryError:
        raise DirectoryError(
            f"Couldn't read the SEC's {year} Q{qtr} index right now; "
            f"it usually comes back on its own.")
    if text is None:
        raise DirectoryError(
            f"Couldn't read the SEC's {year} Q{qtr} index (HTTP 404)")
    data = json.loads(text)
    entry = data.get("directory") if isinstance(data, dict) else data
    if isinstance(entry, dict):
        entries = entry.get("item") or []  # newer index format: nested dict
    else:
        entries = entry or []              # older index format: flat list
    days = set()
    for e in entries:
        if not isinstance(e, dict) or e.get("type") != "file":
            continue
        # Older indexes list bare dates; the newer ones use filenames like
        # "master.20261104.idx", so pull the 8-digit date out of the name.
        m = re.search(r"\d{8}", f"{e.get('name') or ''} {e.get('href') or ''}")
        if m:
            days.add(m.group())
    days = sorted(days)
    _cached_write(name, json.dumps({"days": days}))
    return days


def parse_master(text: str) -> list[dict]:
    """The 13F-family lines of one daily master file, as dicts.

    Non-13F forms (8-K, 10-Q, …) and malformed lines are dropped; a line
    that is *not* a 13F is simply not our concern.
    """
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        cik, name, form, fdate, path = parts[:5]
        form = form.upper()
        if not cik.isdigit() or not form.startswith("13F") \
                or not re.fullmatch(r"\d{8}", fdate):
            continue
        out.append({
            "cik": cik,
            "name": name,
            "form": form,
            "date": f"{fdate[:4]}-{fdate[4:6]}-{fdate[6:]}",
            "path": path,
        })
    return out


def _rank(form: str) -> int:
    """0 = a real holdings filing, 1 = a note (13F-NT / 13F-CONP) without any."""
    return 0 if form in ("13F-HR", "13F-HR/A") else 1


def _prev_quarter(year: int, qtr: int) -> tuple[int, int]:
    qtr -= 1
    if qtr == 0:
        qtr, year = 4, year - 1
    return year, qtr


def build_snapshot(refresh: bool = False) -> dict:
    """Crawl the last two quarters' daily indexes → the filer snapshot.

    Bounded: ~85–90 small files. Each master file is cached for 24h, so a
    rebuild after day one costs only the new days. One unreachable day or
    quarter is skipped; if *nothing* came back we raise, in plain English.
    """
    path = CACHE_DIR / "directory.json"
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < TTL:
        try:
            d = json.loads(path.read_text())
            if d.get("v") == _VERSION:
                return d
        except (json.JSONDecodeError, OSError):
            pass

    today = date.today()
    quarters = [(today.year, (today.month - 1) // 3 + 1)]
    quarters.append(_prev_quarter(*quarters[0]))

    filers: dict[str, dict] = {}
    n_filings = 0
    for y, q in quarters:
        try:
            days = quarter_days(y, q)
        except DirectoryError:
            continue  # one unreachable quarter; the other may still be fine
        for d in days:
            cache_name = f"master_{d}.idx"
            t = _cached_read(cache_name)
            if t is None:
                url = (f"https://www.sec.gov/Archives/edgar/daily-index/"
                       f"{y}/QTR{q}/master.{d}.idx")
                try:
                    t = _http_text(url)
                except (DirectoryError, httpx.HTTPError):
                    continue  # one missing day shouldn't sink the whole quarter
                if t is None:
                    continue  # no file for that day (a weekend)
                _cached_write(cache_name, t)
                time.sleep(0.2)  # be polite: the SEC asks us to pace ourselves
            for row in parse_master(t):
                n_filings += 1
                e = filers.get(row["cik"])
                if e is None:
                    filers[row["cik"]] = row
                else:
                    # Most recent wins; on the same day a real holdings
                    # filing (13F-HR) beats a "not filing" note (13F-NT).
                    if (row["date"], -_rank(row["form"])) > (e["date"], -_rank(e["form"])):
                        filers[row["cik"]] = row

    if not filers:
        raise DirectoryError(
            "Couldn't read the SEC's filing index right now, so the directory "
            "is empty. It'll be back — try again in a few minutes.")

    entries = sorted(filers.values(), key=lambda f: f["name"].upper())
    snap = {
        "v": _VERSION,
        "generated": int(time.time()),
        "quarters": [f"{y} Q{q}" for y, q in quarters],
        "n_filings": n_filings,
        "n_filers": len(entries),
        "filers": entries,
    }
    try:
        _cached_write("directory.json", json.dumps(snap))
    except OSError:
        pass
    return snap


def load_snapshot() -> dict | None:
    """The snapshot if we have a fresh one on disk, else None."""
    path = CACHE_DIR / "directory.json"
    try:
        if path.exists() and time.time() - path.stat().st_mtime < TTL:
            d = json.loads(path.read_text())
            if d.get("v") == _VERSION:
                return d
    except (json.JSONDecodeError, OSError):
        return None
    return None


# ---------------------------------------------------------------------------
# Searching (instant, local)
# ---------------------------------------------------------------------------

def search(q: str, limit: int = 12) -> list[dict]:
    """Substring search over filer names and CIKs. Needs 2+ characters."""
    snap = load_snapshot()
    if snap is None:
        raise DirectoryError(
            "The directory is still being built (or the SEC's index is "
            "unreachable) — try again in a minute.")
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []

    hits = []
    for f in snap["filers"]:
        nl = f["name"].lower()
        if q in nl:
            score = 0 if nl.startswith(q) else 1
        elif q in f["cik"]:
            score = 2
        else:
            continue
        hits.append((score, f["name"].upper(), f))
    hits.sort(key=lambda t: (t[0], t[1]))

    limit = max(1, min(int(limit), 25))
    return [{k: f[k] for k in ("cik", "name", "form", "date")}
            for _, _, f in hits[:limit]]
