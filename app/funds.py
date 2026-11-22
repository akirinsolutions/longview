"""Smart Money: what are the big funds actually doing?

Source: SEC 13F filings. Every quarter, US funds managing $100M+ of
discretionary long equity must disclose their holdings — free, official,
no API key. We read:

- the latest 13F of every fund in the active roster — the eleven famous
  ones by default (Buffett, Dalio, Simons, Ackman, Tepper, ...), plus
  whatever the user adds from the 13F filer directory,
- their top positions by dollar value,
- what they added / sold vs the prior quarter,
- "crowded" names: stocks held by 3+ of the tracked funds.

The workhorse is `scan_pool()`: every holding of every fund in one
enriched table (weights, asset class, quarter-over-quarter status,
crowding), which the Smart Money tab's filters, rollups and one-security
view all run over.

Honest caveats (also shown in the UI):
- 13Fs are due 45 days after quarter-end, so this always looks slightly
  into the past.
- 13F covers US *long* stock positions only. No shorts, no options, no
  international holdings, no private stakes. What a fund does *not*
  disclose is at least as interesting as what it does.
- Dollar values are as of quarter-end, not today.

EDGAR policy note: the SEC requires automated clients to identify
themselves, so every request carries a declared User-Agent with contact
info, and filings are cached on disk (a 13F never changes once filed).
"""
from __future__ import annotations

import csv
import io
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

from . import vault

import httpx

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "13f"
EDGAR_UA = "Longview (open source, research use; contact: user@example.com)"

FUNDS: list[dict] = [
    {"key": "berkshire",   "name": "Berkshire Hathaway", "manager": "Warren Buffett",       "cik": 1067983},
    {"key": "bridgewater", "name": "Bridgewater",        "manager": "Ray Dalio",            "cik": 1350694},
    # The 13F is filed by the "Inc." entity; the look-alike "L.P." CIK
    # (1009268) only files 13F-NT late notices. (The SEC loves these twins.)
    {"key": "deshaw",      "name": "D. E. Shaw",         "manager": "David Shaw",           "cik": 1009207},
    {"key": "tiger",       "name": "Tiger Global",       "manager": "Chase Coleman",        "cik": 1167483},
    {"key": "citadel",     "name": "Citadel",            "manager": "Ken Griffin",          "cik": 1423053},
    {"key": "renaissance", "name": "Renaissance Tech",   "manager": "Jim Simons",           "cik": 1037389},
    # Pershing Square Inc. is the active 13F filer; the older "GP, LLC"
    # entity (1336476) last filed a holdings table in 2013.
    {"key": "pershing",    "name": "Pershing Square",    "manager": "Bill Ackman",          "cik": 2026053},
    {"key": "thirdpoint",  "name": "Third Point",        "manager": "Daniel Loeb",          "cik": 1040273},
    # Greenlight (Einhorn) stopped filing after Feb 2024, so the card went
    # stale. Replaced with Carl Icahn — the original activist. He files his
    # *personal* 13F ("ICAHN CARL C", CIK 921669) every quarter; verified
    # against the SEC's full-text search index, most recent = Q2 2026.
    {"key": "icahn",       "name": "Icahn",              "manager": "Carl Icahn · personal", "cik": 921669},
    # Coatue Management LLC files the 13F; "Coatue Capital LLC" (1269617)
    # has no holdings filings in the SEC's recent window.
    {"key": "coatue",      "name": "Coatue",             "manager": "Philippe Laffont",     "cik": 1135730},
    {"key": "millennium",  "name": "Millennium",         "manager": "Izzy Englander",       "cik": 1273087},
]

_client: httpx.Client | None = None
_lock = threading.Lock()


def _get_client() -> httpx.Client:
    global _client
    with _lock:
        if _client is None:
            _client = httpx.Client(
                headers={"User-Agent": EDGAR_UA}, timeout=30.0, follow_redirects=True
            )
        return _client


def _cik10(cik: int | str) -> str:
    return f"{int(cik):0>10}"


def _cache_file(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / name


# Bump when the on-disk filing format changes; older caches refetch.
_CACHE_VERSION = 2


# ---------------------------------------------------------------------------
# The roster: which funds actually get scanned
#
# FUNDS (above) is the *default* roster — the eleven famous ones. What we
# actually scan is ``data/roster.json``: the defaults minus whatever the
# user removed, plus whatever they added from the 13F filer directory
# (see directory.py). The pool, rollups, crowding and one-security view
# all run over the active roster, and the pool caches remember a roster
# fingerprint so a roster change rebuilds them (from forever-cached
# filings — no extra SEC traffic).
# ---------------------------------------------------------------------------

_SECTION = "roster"
_ROSTER_VERSION = 1


def _load_roster_file() -> list[dict] | None:
    """The saved roster, or None if the vault holds none or a bad one."""
    d = vault.read_section(_SECTION)
    if d is None:
        return None
    if d.get("v") != _ROSTER_VERSION:
        return None
    entries = d.get("funds")
    if not isinstance(entries, list) or not all(
            isinstance(f, dict) and f.get("key") and f.get("name") and f.get("cik")
            for f in entries):
        return None
    return entries


def _save_roster(entries: list[dict]) -> None:
    """The roster is real data (the user's own list); the vault writes
    it atomically."""
    vault.write_section(_SECTION, {"v": _ROSTER_VERSION,
                                   "updated": int(time.time()),
                                   "funds": entries})


def active_roster() -> list[dict]:
    """The funds we actually scan. First run seeds the file from FUNDS.

    The saved file is the *membership* list: which funds, and any the
    user added. Display metadata for the eleven curated funds (name,
    manager) stays in code, so a corrected name reaches an existing
    roster without the user re-adding anything.
    """
    entries = _load_roster_file()
    if entries is None:
        entries = [dict(f) for f in FUNDS]
        _save_roster(entries)
        return entries
    curated = {f["key"]: f for f in FUNDS}
    changed = False
    for f in entries:
        base = curated.get(f.get("key"))
        if base is None:
            continue
        if f.get("name") != base["name"] or f.get("manager") != base["manager"]:
            f["name"], f["manager"] = base["name"], base["manager"]
            changed = True
    if changed:
        try:
            _save_roster(entries)
        except OSError:
            pass  # read-only vault: show the right name anyway
    return entries


def roster_fingerprint() -> str:
    """What the pool caches remember about the roster (change -> rebuild)."""
    return json.dumps(sorted((str(f["cik"]), f["key"]) for f in active_roster()))


def _apply_curated_metadata(d: dict) -> dict:
    """Overlay code-owned name/manager labels on a pool dict.

    The scan cache holds whatever label was current when it was built.
    Curated funds get their labels from FUNDS instead, so a corrected
    manager name shows up even when the cached pool is still warm.
    User-added funds are left exactly as they were saved.
    """
    curated = {f["key"]: f for f in FUNDS}
    for f in d.get("funds") or []:
        base = curated.get(f.get("key"))
        if base is not None:
            f["name"] = base["name"]
            f["manager"] = base["manager"]
    return d


def get_fund(key: str) -> dict | None:
    return next((f for f in active_roster() if f["key"] == key), None)


def _clean_filer_name(name: str) -> str:
    """Tidy an EDGAR registration name for display:
    'FORT WASHINGTON INV ADVISORS INC /OH/' -> drop the trailing state code."""
    s = re.sub(r"\s*/[A-Za-z0-9.]{1,6}/\s*$", "", (name or "").strip())
    return re.sub(r"\s+", " ", s)


def _fund_key(name: str, cik: int, existing: list[dict]) -> str:
    """A short stable key for a roster entry, unique within the roster."""
    base = re.sub(r"[^a-z0-9]+", "", (name or "").lower())[:24] or f"c{cik}"
    keys = {f["key"] for f in existing}
    key, i = base, 2
    while key in keys:
        key, i = f"{base}{i}", i + 1
    return key


def _check_active_13f(sub: dict, name: str) -> None:
    """A roster fund must have a *current* holdings 13F, in plain English.

    A filer whose newest 13F-family filing is a 13F-NT ("not filing this
    quarter") or 13F-CONP has no holdings table to read, and one whose
    last real filing is a year old would just decorate the tab with a
    stale card. Either way: refuse, and say why.
    """
    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    for i, f in enumerate(forms):
        if not f.upper().startswith("13F"):
            continue
        if f in ("13F-NT", "13F-CONP"):
            raise RuntimeError(
                "its newest 13F is a 'not filing this quarter' note, so there "
                "are no holdings to read")
        age = _days_since(dates[i] if i < len(dates) else None)
        if age is None or age > 150:
            if age is None:
                raise RuntimeError(
                    "the SEC doesn't show a date for its last holdings filing — "
                    "too stale to be useful on the roster")
            raise RuntimeError(
                f"its last holdings filing is {age} days old — too stale to be "
                "useful on the roster")
        return
    raise RuntimeError(
        "the SEC has no recent 13F history for this filer — it may have "
        "stopped filing")


def add_fund(name: str, cik: int | str) -> tuple[dict, list[dict]]:
    """Add a fund from the filer directory to the roster.

    Returns (the new entry, the updated roster). Raises ValueError for
    bad input and RuntimeError for filers without a current 13F — both
    worded to be shown verbatim in the UI.
    """
    try:
        cik = int(str(cik).strip())
    except (TypeError, ValueError):
        raise ValueError("That CIK isn't a number — try searching again.")
    name = _clean_filer_name(name)
    if not name:
        raise ValueError("I need a name for this fund.")

    entries = active_roster()
    same = next((f for f in entries if str(f["cik"]) == str(cik)), None)
    if same is not None:
        raise ValueError(f"{same['name']} is already on the roster.")

    _check_active_13f(_submissions(_cik10(cik)), name)

    entry = {"key": _fund_key(name, cik, entries),
             "name": name, "manager": "", "cik": cik}
    entries.append(entry)
    _save_roster(entries)
    return entry, entries


def remove_fund(key: str) -> tuple[dict, list[dict]]:
    """Take a fund off the roster. Refuses to empty the roster entirely."""
    entries = active_roster()
    i = next((j for j, f in enumerate(entries) if f["key"] == key), None)
    if i is None:
        raise KeyError(key)
    if len(entries) == 1:
        raise ValueError(
            f"You can't remove {entries[0]['name']} — it's the only fund on "
            "the roster, and the tab would be empty.")
    removed = entries.pop(i)
    _save_roster(entries)
    return removed, entries


# ---------------------------------------------------------------------------
# EDGAR plumbing
# ---------------------------------------------------------------------------

def _submissions(cik10: str) -> dict:
    """A filer's submissions index (cached 24h — it changes as new filings land)."""
    path = _cache_file(f"sub_{cik10}.json")
    if path.exists() and time.time() - path.stat().st_mtime < 24 * 3600:
        return json.loads(path.read_text())
    r = _get_client().get(f"https://data.sec.gov/submissions/CIK{cik10}.json")
    if r.status_code != 200:
        raise RuntimeError(f"SEC has no filing history for this fund (HTTP {r.status_code})")
    data = r.json()
    path.write_text(json.dumps(data))
    return data


def _recent_13f(sub: dict, how_many: int = 2) -> list[dict]:
    """The most recent 13F filings that actually contain holdings.

    Only 13F-HR (regular) and 13F-HR/A (amendment) carry a holdings table.
    13F-NT is a note saying "we won't file this quarter" (or "we're late")
    and 13F-CONP a cover-only form — neither has positions to read, so
    they're skipped even if they're the newest 13F-ish filing.
    """
    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form") or []
    out = []
    for i, f in enumerate(forms):
        if f in ("13F-HR", "13F-HR/A"):
            out.append({
                "date": (recent.get("filingDate") or [""])[i],
                "form": f,
                "accession": (recent.get("accessionNumber") or [""])[i].replace("-", ""),
            })
            if len(out) >= how_many:
                break
    if not out:
        raise RuntimeError("no holdings filings (13F-HR) found in the SEC's recent window — this fund may have stopped filing")
    return out


def _loc(tag) -> str:
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def parse_info_table(xml_text: str) -> list[dict]:
    """Parse a 13F holdings table, handling both XML generations:

    - new: <informationTable><infoTable>...one position...</infoTable>...
    - old: <informationTable><tableData> flat, repeating fields </tableData>

    Positions for the same issuer+class (multiple portfolio managers in one
    filing) are merged into one line.
    """
    root = ET.fromstring(xml_text)
    raw: list[dict] = []

    def _scalar(el, name: str) -> str:
        for c in el:
            if _loc(c.tag) == name:
                return (c.text or "").strip()
        return ""

    for el in root.iter():
        n = _loc(el.tag)
        if n == "infoTable":
            value = 0.0
            shares = 0.0
            for c in el:
                cn = _loc(c.tag)
                if cn == "value":
                    try:
                        value = float(c.text)
                    except (TypeError, ValueError):
                        pass
                elif cn == "shrsOrPrnAmt":
                    for s in c:
                        if _loc(s.tag) == "sshPrnamt":
                            try:
                                shares = float(s.text)
                            except (TypeError, ValueError):
                                pass
            e = {"issuer": _scalar(el, "nameOfIssuer"),
                 "class": _scalar(el, "titleOfClass"),
                 "cusip": _scalar(el, "cusip"),
                 "value": value, "shares": shares}
            if e["issuer"]:
                raw.append(e)
        elif n == "tableData":
            cur = None
            for c in el:
                cn = _loc(c.tag)
                if cn == "nameOfIssuer":
                    if cur:
                        raw.append(cur)
                    cur = {"issuer": (c.text or "").strip(), "class": "",
                           "value": 0.0, "shares": 0.0}
                elif cur is not None:
                    if cn == "titleOfClass":
                        cur["class"] = (c.text or "").strip()
                    elif cn == "cusip":
                        cur["cusip"] = (c.text or "").strip()
                    elif cn == "value":
                        try:
                            cur["value"] = float(c.text)
                        except (TypeError, ValueError):
                            pass
                    elif cn == "shrs":
                        try:
                            cur["shares"] = float(c.text)
                        except (TypeError, ValueError):
                            pass
            if cur:
                raw.append(cur)

    merged: dict[tuple, dict] = {}
    for e in raw:
        key = (e["issuer"].upper(), e.get("class", ""))
        m = merged.setdefault(key, {"issuer": e["issuer"], "class": e.get("class", ""),
                                    "cusip": e.get("cusip", ""),
                                    "value": 0.0, "shares": 0.0, "entries": 0})
        if not m["cusip"] and e.get("cusip"):
            m["cusip"] = e["cusip"]
        m["value"] += e["value"]
        m["shares"] += e.get("shares", 0.0)
        m["entries"] += 1
    out = list(merged.values())
    out.sort(key=lambda e: -e["value"])
    return out


def _extract_period(xml_text: str) -> str | None:
    """The quarter-end a 13F reports (e.g. '2026-06-30'), if present.

    Two generations of 13F documents declare it differently:
    - old:  <reportingPeriod><endDate>2026-06-30</endDate>
    - new:  <periodOfReport>06-30-2026</periodOfReport>  (MM-DD-YYYY)
    Both are normalized to YYYY-MM-DD.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    for el in root.iter():
        if _loc(el.tag) in ("endDate", "periodOfReport", "reportCalendarOrQuarter"):
            t = (el.text or "").strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", t):
                return t
            m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", t)
            if m:
                return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    for a, v in root.attrib.items():
        if "period" in _loc(a):
            return v
    return None


def _cover_period(cik10: str, accession: str) -> str | None:
    """The reporting quarter of a filing, read from its cover page.

    The holdings table document is a bare table with no header at all, so
    the quarter-end only lives on the cover page. The cover page is always
    the *smallest* XML in the filing folder (a few KB vs the megabyte-scale
    table), which is how we find it without downloading the table. Fetched
    once per filing, then cached forever — a filed 13F never changes.
    """
    path = _cache_file(f"cov_{cik10}_{accession}.json")
    if path.exists():
        try:
            return json.loads(path.read_text()).get("period")
        except (OSError, json.JSONDecodeError):
            pass
    period: str | None = None
    base = f"https://www.sec.gov/Archives/edgar/data/{cik10}/{accession}/"
    try:
        r = _get_client().get(base + "index.json")
        if r.status_code == 200:
            items = [i for i in r.json().get("directory", {}).get("item", [])
                     if i["name"].lower().endswith(".xml")]
            def _size(i: dict) -> int:
                try:
                    return int(i.get("size") or 0)
                except ValueError:
                    return 1 << 30  # unknown size: fetch it last
            for i in sorted(items, key=_size)[:3]:
                x = _get_client().get(base + i["name"])
                if x.status_code != 200:
                    continue
                try:
                    root = ET.fromstring(x.text)
                except ET.ParseError:
                    continue
                if _loc(root.tag) == "edgarSubmission":
                    period = _extract_period(x.text)
                    break
    except httpx.HTTPError:
        period = None
    try:
        path.write_text(json.dumps({"v": _CACHE_VERSION, "period": period}))
    except OSError:
        pass
    return period


def _filing_period(cik10: str, accession: str) -> str | None:
    """A filing's reporting quarter, without downloading its big table.

    The table's parse cache (pos_*.json) already stores the period when we
    knew it; otherwise ask the cover page.
    """
    try:
        d = json.loads(_cache_file(f"pos_{cik10}_{accession}.json").read_text())
        if d.get("period") is not None:
            return d["period"]
    except (OSError, json.JSONDecodeError):
        pass
    return _cover_period(cik10, accession)


def _diff_filings(cik10: str, sub: dict) -> tuple[dict, dict | None]:
    """The latest holdings filing, plus the filing to diff it against.

    Amended filings (13F-HR/A) report the *same* quarter as the filing they
    amend, so "the two most recent 13Fs" can be two versions of one
    quarter. We diff against the most recent filing that reports a
    *different* quarter; when a quarter can't be determined we fall back to
    the next most recent (the old behavior).
    """
    filings = _recent_13f(sub, 8)
    latest = filings[0]
    prev: dict | None = None
    lp = _filing_period(cik10, latest["accession"])
    for f in filings[1:]:
        p = _filing_period(cik10, f["accession"])
        if p is None or lp is None or p != lp:
            prev = f
            break
    return latest, prev


def _fetch_filing(cik10: str, accession: str) -> tuple[list[dict], str | None]:
    """Download a 13F filing and return (positions, quarter_end_date).

    The holdings table document has no predictable name (Berkshire calls
    theirs '56757.xml'), so we look at each XML in the filing folder and
    keep the one whose root element is <informationTable>. Cached forever:
    a filed 13F never changes.
    """
    cache = _cache_file(f"pos_{cik10}_{accession}.json")
    if cache.exists():
        try:
            d = json.loads(cache.read_text())
        except (json.JSONDecodeError, OSError):
            d = {}
        # A filed 13F never changes, but *our format* can: if the cached
        # copy predates a parser upgrade (e.g. missing cusips), refetch.
        if d.get("v") == _CACHE_VERSION and d.get("positions"):
            if d.get("period") is None:
                # The table doc carries no header, so the quarter wasn't
                # known when we cached this; backfill from the cover page.
                d["period"] = _cover_period(cik10, accession)
                try:
                    cache.write_text(json.dumps(d))
                except OSError:
                    pass
            return d["positions"], d.get("period")

    r = _get_client().get(
        f"https://www.sec.gov/Archives/edgar/data/{cik10}/{accession}/index.json")
    r.raise_for_status()
    items = r.json().get("directory", {}).get("item", [])
    base = f"https://www.sec.gov/Archives/edgar/data/{cik10}/{accession}/"

    positions: list[dict] | None = None
    period: str | None = None
    for name in [i["name"] for i in items if i["name"].lower().endswith(".xml")][:6]:
        x = _get_client().get(base + name)
        if x.status_code != 200:
            continue
        try:
            root = ET.fromstring(x.text)
        except ET.ParseError:
            continue
        if _loc(root.tag) == "informationTable":
            positions = parse_info_table(x.text)
            period = _extract_period(x.text)
            break
        if period is None:
            period = _extract_period(x.text)

    # Rare fallback: some filers ship the table as .htm
    if positions is None:
        for name in [i["name"] for i in items if i["name"].lower().endswith(".htm")][:3]:
            x = _get_client().get(base + name)
            if x.status_code == 200 and "<informationTable" in x.text:
                try:
                    positions = parse_info_table(x.text)
                except ET.ParseError:
                    continue
                break

    if positions is None:
        raise RuntimeError("could not find the holdings table inside that filing")

    if period is None:
        period = _cover_period(cik10, accession)

    cache.write_text(json.dumps(
        {"v": _CACHE_VERSION, "cik": cik10, "accession": accession,
         "period": period, "positions": positions}))
    return positions, period


def normalize_name(name: str) -> str:
    """'ALLY FINL INC' / 'Allied Financial, Inc.' -> 'ALLY FINL' (for matching)."""
    s = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper())
    noise = {"INC", "LLC", "LP", "CO", "COMPANY", "CORP", "CORPORATION", "LTD",
             "PLC", "SA", "AG", "GMBH", "BV", "NV", "FKA", "AND", "DE", "HOLDINGS"}
    toks = [t for t in s.split() if t not in noise or t in {"A", "U", "X", "3"}]
    return " ".join(toks)


def fund_summary(fund: dict) -> dict:
    """Latest 13F of one fund: what it holds, and how big it is."""
    cik10 = _cik10(fund["cik"])
    sub = _submissions(cik10)
    latest = _recent_13f(sub, 1)[0]
    positions, period = _fetch_filing(cik10, latest["accession"])
    return {
        "key": fund["key"], "name": fund["name"], "manager": fund["manager"],
        "as_of": period or latest["date"],
        "filed": latest["date"],
        "form": latest["form"],
        "total_value": sum(p["value"] for p in positions),
        "n_positions": len(positions),
        "top": [{"issuer": p["issuer"], "class": p["class"],
                 "value": p["value"], "shares": p["shares"]} for p in positions[:10]],
    }


def _match_key(p: dict) -> str:
    """How two quarters' rows refer to the same security.

    The CUSIP is the official, stable identifier — a company can rename
    itself ('Bank of America' / 'Bank of Amer') or change how it's spelled
    between filings without the security changing. When a row has no
    CUSIP we fall back to the normalized name.
    """
    cusip = (p.get("cusip") or "").strip().upper()
    if len(cusip) >= 6:
        return f"CU {cusip}"
    return f"NM {normalize_name(p['issuer'])}"


def _diff_positions(latest: list[dict], prev: list[dict]
                    ) -> tuple[list[dict], list[dict], list[dict]]:
    """Compared to the prior quarter: added, exited, big moves (>=25% and >=$50M)."""
    prev_by_key = {_match_key(p): p for p in prev}
    latest_keys = {_match_key(p) for p in latest}
    added = [p for p in latest if _match_key(p) not in prev_by_key]
    exited = [p for p in prev if _match_key(p) not in latest_keys]
    moves = []
    for p in latest:
        q = prev_by_key.get(_match_key(p))
        if q and q.get("value", 0) > 0:
            chg = p["value"] / q["value"] - 1.0
            if abs(chg) >= 0.25 and max(p["value"], q["value"]) >= 5e7:
                moves.append({**p, "change": chg})
    added.sort(key=lambda p: -p["value"])
    exited.sort(key=lambda p: -p["value"])
    moves.sort(key=lambda p: -abs(p.get("change", 0.0)))
    return added[:10], exited[:10], moves[:10]


def fund_detail(fund: dict) -> dict:
    """Latest quarter + what changed vs the quarter before it."""
    out = fund_summary(fund)
    cik10 = _cik10(fund["cik"])
    latest, prev = _diff_filings(cik10, _submissions(cik10))
    if prev is not None:
        lpos, _ = _fetch_filing(cik10, latest["accession"])
        ppos, pperiod = _fetch_filing(cik10, prev["accession"])
        added, exited, moves = _diff_positions(lpos, ppos)
        out["prev_as_of"] = pperiod or prev["date"]
        out["added"] = [{k: p[k] for k in ("issuer", "class", "value", "shares")} for p in added]
        out["exited"] = [{k: p[k] for k in ("issuer", "class", "value", "shares")} for p in exited]
        out["big_moves"] = [{k: p[k] for k in ("issuer", "class", "value", "shares", "change")}
                            for p in moves]
    return out


# ---------------------------------------------------------------------------
# Ask: a window of quarters, sized for a language model's prompt
#
# The tab's other views compare two quarters; Ask spans up to four of them.
# fund_history() reads a fund's N most recent *distinct* reported quarters
# (an amendment of a quarter collapses into the original's slot). ask_data()
# then adds the cross-fund picture — what everyone added or sold over the
# window — and keeps the result deliberately small, because it goes into a
# language model's prompt, not a table.
# ---------------------------------------------------------------------------

def fund_history(fund: dict, quarters: int = 4) -> list[dict]:
    """A fund's N most recent *distinct* reported quarters, newest first.

    Amended 13Fs (13F-HR/A) report the same quarter as the filing they
    amend, so the window dedupes by reporting period: the most recently
    filed version of a quarter wins. Each entry keeps its parsed
    positions (already largest-first) so callers can build any view.
    """
    n = max(1, min(int(quarters), 8))
    cik10 = _cik10(fund["cik"])
    sub = _submissions(cik10)
    out: list[dict] = []
    seen: set[str] = set()
    for f in _recent_13f(sub, 8):
        positions, period = _fetch_filing(cik10, f["accession"])
        key = period or f["accession"]
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "as_of": period or f["date"],
            "filed": f["date"],
            "form": f["form"],
            "total_value": sum(p["value"] for p in positions),
            "n_positions": len(positions),
            "positions": positions,
        })
        if len(out) >= n:
            break
    if not out:
        raise RuntimeError(
            "no holdings filings (13F-HR) found for this fund in the "
            "SEC's recent window")
    return out


def _display_name(p: dict) -> str:
    """The issuer's name with 13Fs' messy interior spacing collapsed
    ('MICRON   TECHNOLOGY   INC' -> 'MICRON TECHNOLOGY INC')."""
    return " ".join(str(p.get("issuer", "")).split())


def ask_data(quarters: int = 1, roster: list[dict] | None = None) -> dict:
    """A compact picture of the tracked funds over the last `quarters`
    quarters (1-4), sized to go into a language model's prompt.

    The budget matters: the local model is a *thinking* model and spends
    its whole output budget on reasoning before it writes a word, so this
    dict deliberately stays around one screen of text. Per fund: each
    window quarter's total and holding count, with the top 6 names on the
    window's newest and oldest quarters (middle quarters of a long window
    keep only their totals — that's what a person would read first, too).
    Across funds: the biggest additions and sales over the window span
    (window start vs window end, CUSIP-matched), plus names that were
    never held in the window's first quarter. Only numbers — the model
    does the talking.
    """
    qs = max(1, min(int(quarters or 1), 4))
    entries = roster if roster is not None else active_roster()

    fund_blocks: list[dict] = []
    missing: list[str] = []
    asofs: list[str] = []
    moves: dict[str, dict] = {}   # match key -> accumulated move over window

    for fund in entries:
        try:
            hist = fund_history(fund, qs + 1)
        except Exception:
            missing.append(fund["name"])
            continue

        window = hist[:qs]         # newest first
        # What a move is measured against: for a single-quarter window,
        # the extra (prior) quarter we fetched; otherwise the window's
        # oldest quarter.
        base = hist[qs] if (qs == 1 and len(hist) > qs) else window[-1]
        end = window[0]

        n_q = len(window)
        fund_blocks.append({
            "key": fund["key"], "name": fund["name"],
            "manager": fund.get("manager", ""),
            "quarters": [
                {"as_of": q["as_of"],
                 "total": round(q["total_value"]),
                 "n": q["n_positions"],
                 # full top list only on the window's newest + oldest
                 # quarter — those two are what the moves compare
                 **({"top": [
                     {"name": _display_name(p),
                      "usd": round(p.get("value", 0.0)),
                      "w": (round(p["value"] / q["total_value"] * 100, 1)
                            if q["total_value"] else 0.0)}
                     for p in q["positions"][:6]
                 ]} if i in (0, n_q - 1) else {})}
                for i, q in enumerate(window)
            ],
        })
        for q in window:
            asofs.append(q["as_of"])

        base_map = {_match_key(p): p for p in base["positions"]}
        end_map = {_match_key(p): p for p in end["positions"]}
        for k in set(base_map) | set(end_map):
            b = base_map.get(k)
            e = end_map.get(k)
            a = moves.setdefault(k, {"delta": 0.0, "now_usd": 0.0,
                                     "base_funds": set(), "now_funds": set(),
                                     "name": ""})
            bv = b.get("value", 0.0) if b else 0.0
            ev = e.get("value", 0.0) if e else 0.0
            a["delta"] += ev - bv
            a["now_usd"] += ev
            if b is not None:
                a["base_funds"].add(fund["key"])
            if e is not None:
                a["now_funds"].add(fund["key"])
            nm = (e or b).get("issuer", "")
            if nm:
                a["name"] = nm

    def _entry(a: dict) -> dict:
        fl = sorted(a["now_funds"] or a["base_funds"])
        return {"name": _display_name({"issuer": a["name"]}),
                "usd": round(a["delta"]),
                "held_now_usd": round(a["now_usd"]),
                "funds": fl, "n_funds": len(fl)}

    added = [_entry(a) for a in sorted(
        (a for a in moves.values() if a["delta"] > 0),
        key=lambda a: -a["delta"])][:6]
    sold = [_entry(a) for a in sorted(
        (a for a in moves.values() if a["delta"] < 0),
        key=lambda a: a["delta"])][:6]
    brand_new = [_entry(a) for a in sorted(
        (a for a in moves.values()
         if a["delta"] > 0 and not a["base_funds"]),
        key=lambda a: -a["delta"])][:5]

    return {
        "window": {"quarters": qs,
                   "start": min(asofs) if asofs else None,
                   "end": max(asofs) if asofs else None},
        "funds": fund_blocks,
        "added": added,
        "sold": sold,
        "brand_new": brand_new,
        "totals": {
            "added_usd": round(sum(a["delta"] for a in moves.values()
                                   if a["delta"] > 0)),
            "sold_usd": round(sum(a["delta"] for a in moves.values()
                                  if a["delta"] < 0)),
        },
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# The scan pool: every holding of every fund, in one enriched table
#
# This is the engine behind the Smart Money tab. For each of the tracked
# funds we take its latest 13F and the quarter before it, and every
# position becomes one row, enriched with:
#
#   - weight      its share of that fund's book
#   - asset       stock / ETF / preferred / option (from the class title)
#   - status      new / increased / decreased / unchanged / exited
#   - change      % vs the prior quarter (None = was not held)
#   - move_value  dollars added or sold
#   - n_funds / holders  how many of the tracked funds hold the same
#                 security this quarter (the crowding picture)
#   - surprise    a new bet that no other tracked fund shares
#
# The whole pool is cached ~12h on disk (13Fs only change quarterly;
# every filing we need is already cached).
# ---------------------------------------------------------------------------

_SCAN_VERSION = 2   # v2: cover-page periods; amendment-aware diff pairing
_VIEW_VERSION = 4   # v4: corrected manager labels (code-owned metadata)


def asset_class(p: dict) -> str:
    """What kind of thing is this 13F row? From the class title, honestly.

    13Fs only use short class strings ('COM', 'ETF', '6.75% PREF', 'CALL'),
    so this is a signal, not a guarantee.
    """
    c = (p.get("class") or "").upper()
    if any(s in c for s in ("ETF", "EXCHANGE TRADED", "INDEX FUND")):
        return "etf"
    if any(s in c for s in ("PRF", "PREF", "PERF", "PFD")):
        return "preferred"
    if "CALL" in c or "PUT" in c:
        return "option"
    return "stock"


def _days_since(iso_date: str | None) -> int | None:
    if not iso_date:
        return None
    try:
        d = datetime.strptime(iso_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (date.today() - d).days


def _enrich_row(fund: dict, p: dict, prev: dict | None, total: float,
                exited: bool = False) -> dict:
    """One position -> one pool row, compared against the prior quarter."""
    if exited:
        value, prev_value, shares = 0.0, p.get("value", 0.0), 0.0
        status, change = "exited", -1.0
    else:
        value, shares = p.get("value", 0.0), p.get("shares", 0.0)
        prev_value = prev.get("value") if prev else None
        if prev_value:
            change = value / prev_value - 1.0
            status = "unchanged" if abs(change) < 0.005 else (
                "increased" if change > 0 else "decreased")
        else:
            change = None
            status = "new"
    return {
        "fund": fund["key"], "fund_name": fund["name"],
        "issuer": p.get("issuer", ""), "class": p.get("class", ""),
        "cusip": p.get("cusip", ""), "key": _match_key(p),
        "value": value, "shares": shares,
        "weight": (value / total) if total else 0.0,
        "asset": asset_class(p),
        "prev_value": prev_value, "change": change,
        "move_value": value - (prev_value or 0.0),
        "status": status,
    }


def _build_pool() -> dict:
    rows: list[dict] = []
    cur: dict[str, dict] = {}      # match key -> who holds it this quarter
    prevfunds: dict[str, set] = {}  # match key -> who held it last quarter
    prevnames: dict[str, str] = {}
    cards: list[dict] = []
    as_ofs: list[str] = []

    for fund in active_roster():
        try:
            cik10 = _cik10(fund["cik"])
            latest, prev = _diff_filings(cik10, _submissions(cik10))
            lpos, period = _fetch_filing(cik10, latest["accession"])
            ppos: list[dict] = []
            if prev is not None:
                ppos, _ = _fetch_filing(cik10, prev["accession"])
        except Exception as e:  # one bad fund shouldn't sink the pool
            cards.append({"key": fund["key"], "name": fund["name"],
                          "manager": fund["manager"], "error": str(e)})
            continue

        total = sum(p["value"] for p in lpos)
        prev_map = {_match_key(p): p for p in ppos}
        for p in ppos:
            k = _match_key(p)
            prevfunds.setdefault(k, set()).add(fund["key"])
            prevnames.setdefault(k, p.get("issuer", ""))

        cur_keys: set[str] = set()
        for p in lpos:
            k = _match_key(p)
            cur_keys.add(k)
            e = cur.setdefault(k, {"funds": set(), "name": p.get("issuer", ""),
                                   "value": 0.0})
            e["funds"].add(fund["key"])
            e["value"] += p.get("value", 0.0)
            rows.append(_enrich_row(fund, p, prev_map.get(k), total))

        for k, p in prev_map.items():
            if k not in cur_keys:
                rows.append(_enrich_row(fund, p, None, total, exited=True))

        as_ofs.append(period or latest["date"])
        fund_rows = [r for r in rows if r["fund"] == fund["key"]]
        top10 = sum(p["value"] for p in lpos[:10])
        # Staleness measures the *filing*, not the quarter: 13Fs are due
        # 45 days after quarter-end, so "days since quarter-end" would call
        # every fund stale a few months after any quarter. A filing that is
        # >150 days old, though, really does mean "stopped filing".
        staleness = _days_since(latest["date"])
        cards.append({
            "key": fund["key"], "name": fund["name"], "manager": fund["manager"],
            "as_of": period or latest["date"], "filed": latest["date"],
            "form": latest["form"],
            "total_value": total, "n_positions": len(lpos),
            "top10_conc": (top10 / total) if total else None,
            "etf_share": (sum(p["value"] for p in lpos if asset_class(p) == "etf")
                          / total) if total else None,
            "n_new": sum(1 for r in fund_rows if r["status"] == "new"),
            "n_exited": sum(1 for r in fund_rows if r["status"] == "exited"),
            "staleness_days": staleness,
            "stale": (staleness is not None and staleness > 150),
        })

    # crowding: who holds each security this quarter, and is that more or
    # fewer than last quarter?
    for r in rows:
        e = cur.get(r["key"])
        r["n_funds"] = len(e["funds"]) if e else 0
        r["holders"] = sorted(e["funds"]) if e else []
        r["surprise"] = (r["status"] == "new" and r["n_funds"] == 1)

    new_rows = [r for r in rows if r["status"] == "new"]
    new_rows.sort(key=lambda r: -r["value"])
    moves = [r for r in rows if r["status"] in ("increased", "decreased", "exited")
             and abs(r.get("move_value") or 0.0) >= 5e7]
    moves.sort(key=lambda r: -abs(r.get("move_value")))

    crowding_change = []
    for k, e in cur.items():
        then = len(prevfunds.get(k, ()))
        now = len(e["funds"])
        if now != then:
            crowding_change.append({
                "key": k, "name": e["name"],
                "then": then, "now": now, "delta": now - then,
                "value": e["value"],
                "funds_now": sorted(e["funds"]),
                "funds_then": sorted(prevfunds.get(k, ())),
            })
    for k, s in prevfunds.items():
        if k not in cur and s:  # everyone held it, now no one does
            crowding_change.append({
                "key": k, "name": prevnames.get(k, "?"),
                "then": len(s), "now": 0, "delta": -len(s),
                "value": 0.0, "funds_now": [], "funds_then": sorted(s),
            })
    crowding_change.sort(key=lambda c: (-abs(c["delta"]), -c["value"]))

    return {
        "v": _SCAN_VERSION,
        "roster": roster_fingerprint(),
        "generated": int(time.time()),
        "as_of": max(as_ofs) if as_ofs else None,
        "funds": cards,
        "rows": rows,
        "new_this_quarter": new_rows[:15],
        "biggest_moves": moves[:15],
        "crowding_change": crowding_change[:25],
    }


def scan_pool(refresh: bool = False) -> dict:
    """The enriched table above, cached ~12h (13Fs change quarterly).

    The cache also stores a roster fingerprint: add or remove a fund and
    the pool rebuilds (from forever-cached filings, so no SEC traffic for
    the funds that were already read)."""
    path = _cache_file("_scan.json")
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < 12 * 3600:
        try:
            d = json.loads(path.read_text())
            if d.get("v") == _SCAN_VERSION and d.get("roster") == roster_fingerprint():
                return _apply_curated_metadata(d)
        except (json.JSONDecodeError, OSError):
            pass
    d = _apply_curated_metadata(_build_pool())
    try:
        path.write_text(json.dumps(d))
    except OSError:
        pass
    return d


def _num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


_SORTABLE = ("value", "prev_value", "weight", "change", "move_value",
             "n_funds", "shares", "issuer")

# The twelve scan filters, plus the aggregate view toggle and the
# sort controls, as query-string names.
SCAN_PARAMS = ("q", "funds", "exclude", "min_value", "min_weight",
               "min_crowding", "status", "min_move_value", "min_move_pct",
               "asset", "surprise", "aggregate", "sort", "dir", "limit")


def _aggregate_group(key: str, rows: list[dict]) -> dict:
    """Many positions in one security -> a single 'each company once' row.

    The scan's aggregate view: worth is what the funds hold *together* now,
    'held by' is how many of them do, and the per-fund detail is carried in
    `breakdown` for the click-into view. `rows` arrive already filtered
    (every filter keeps its per-position meaning); everything here is a sum.
    """
    value = sum(r["value"] for r in rows)
    prev_total = sum(r.get("prev_value") or 0.0 for r in rows)
    shares = sum(r.get("shares") or 0.0 for r in rows)
    move = sum(r.get("move_value") or 0.0 for r in rows)
    change = (value / prev_total - 1.0) if prev_total > 0 else None
    if all(r["status"] == "exited" for r in rows):
        status = "exited"
    elif prev_total <= 0:
        status = "new"
    elif change is None or abs(change) < 0.005:
        status = "unchanged"
    else:
        status = "increased" if change > 0 else "decreased"

    holders = sorted({r["fund"] for r in rows if r["value"] > 0})
    if not holders:  # everyone sold it: count who held it last quarter
        holders = sorted({r["fund"] for r in rows})

    # The biggest position stands for the company's identity (name, class,
    # CUSIP); the display name is the most common spelling, longest first.
    top = max(rows, key=lambda r: r["value"] or r.get("prev_value") or 0.0)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["issuer"]] = counts.get(r["issuer"], 0) + 1
    name = max(counts, key=lambda n: (counts[n], len(n)))

    return {
        "key": key,
        "fund": top["fund"], "fund_name": top.get("fund_name", ""),
        "issuer": name, "class": top.get("class", ""),
        "cusip": top.get("cusip", ""), "asset": top.get("asset", "stock"),
        "value": value, "shares": shares, "weight": None,
        "prev_value": prev_total, "change": change,
        "move_value": move, "status": status,
        "n_funds": len(holders), "holders": holders,
        "surprise": (prev_total <= 0) and len(holders) == 1,
        "breakdown": [
            {"fund": r["fund"], "fund_name": r.get("fund_name", ""),
             "status": r["status"], "value": r["value"],
             "prev_value": r.get("prev_value"), "change": r.get("change"),
             "move_value": r.get("move_value") or 0.0}
            for r in sorted(rows,
                            key=lambda r: -(r["value"] or r.get("prev_value") or 0.0))
        ],
    }


def scan_query(pool: dict, p: dict) -> dict:
    """Apply the tab's twelve scan filters + sort + limit. Pure function.

    With `aggregate` set (the 'aggregate' toggle), the filtered positions
    are first summed into one row per security — each company appears once,
    worth = what the funds hold in it together — and the limit/sort apply
    to companies, not positions.
    """
    q = (p.get("q") or "").strip().lower()
    include = {x for x in (p.get("funds") or "").split(",") if x}
    exclude = {x for x in (p.get("exclude") or "").split(",") if x}
    min_value = _num(p.get("min_value"))
    min_weight = _num(p.get("min_weight"))        # entered as %
    min_crowd = _num(p.get("min_crowding")) or 0
    status = (p.get("status") or "").strip()
    min_mv = _num(p.get("min_move_value"))
    min_mp = _num(p.get("min_move_pct"))          # entered as %
    asset = (p.get("asset") or "").strip()
    surprise = str(p.get("surprise") or "").lower() in ("1", "true", "yes")

    out = []
    for r in pool["rows"]:
        if q and q not in r["issuer"].lower() and q not in (r.get("cusip") or ""):
            continue
        if include and r["fund"] not in include:
            continue
        if exclude and r["fund"] in exclude:
            continue
        # For an exited position the meaningful "size" is what they sold
        # last quarter (its value is $0 now, which would match nothing).
        size = (r["prev_value"] or 0.0) if r["status"] == "exited" else r["value"]
        if min_value is not None and size < min_value:
            continue
        if min_weight is not None and r["weight"] * 100 < min_weight:
            continue
        if min_crowd and r.get("n_funds", 0) < min_crowd:
            continue
        if status and r["status"] != status:
            continue
        if min_mv is not None and abs(r.get("move_value") or 0.0) < min_mv:
            continue
        if min_mp is not None and abs(r.get("change") or 0.0) * 100 < min_mp:
            continue
        if asset and r["asset"] != asset:
            continue
        if surprise and not r.get("surprise"):
            continue
        out.append(r)

    sort = (p.get("sort") or "value").strip().lower()
    if sort not in _SORTABLE:
        sort = "value"

    def _skey(r: dict):
        v = r.get(sort)
        return (1, 0) if v is None else (0, v)  # missing values sort last-ish

    try:
        limit = max(1, min(int(_num(p.get("limit")) or 100), 500))
    except (TypeError, ValueError):
        limit = 100

    if str(p.get("aggregate") or "").lower() in ("1", "true", "yes"):
        groups: dict[str, list[dict]] = {}
        for r in out:
            k = r.get("key") or f"NM {normalize_name(r['issuer'])}"
            groups.setdefault(k, []).append(r)
        aggs = [_aggregate_group(k, rs) for k, rs in groups.items()]
        aggs.sort(key=_skey, reverse=(p.get("dir") != "asc"))
        return {"total": len(aggs), "shown": min(limit, len(aggs)),
                "rows": aggs[:limit]}

    out.sort(key=_skey, reverse=(p.get("dir") != "asc"))
    return {"total": len(out), "shown": min(limit, len(out)),
            "rows": out[:limit]}


_CSV_COLS = ["fund", "issuer", "class", "cusip", "asset", "status",
             "value", "shares", "weight_pct", "prev_value", "change_pct",
             "move_value", "n_funds", "holders", "surprise"]


def rows_to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["fund", "issuer", "class", "cusip", "asset", "status",
                "value_usd", "shares", "weight_pct", "prev_value_usd",
                "change_pct", "move_value_usd", "held_by_n_funds",
                "holders", "surprise"])
    for r in rows:
        w.writerow([
            r["fund"], r["issuer"], r.get("class", ""), r.get("cusip", ""),
            r["asset"], r["status"],
            f"{r['value']:.0f}", f"{r.get('shares') or 0:.0f}",
            # aggregate rows have no single fund to take a % of
            "" if r.get("weight") is None else f"{r['weight'] * 100:.2f}",
            "" if r.get("prev_value") is None else f"{r['prev_value']:.0f}",
            "" if r.get("change") is None else f"{r['change'] * 100:.1f}",
            f"{r.get('move_value') or 0:.0f}",
            r.get("n_funds", 0), ";".join(r.get("holders") or []),
            "yes" if r.get("surprise") else "",
        ])
    return buf.getvalue()


def security_view(query: str, pool: dict | None = None) -> dict:
    """Feature: one security, every tracked fund at once.

    Look up a company by name or CUSIP and see who holds it, how much,
    and what each of them did to it last quarter.
    """
    pool = pool if pool is not None else scan_pool()
    q = (query or "").strip()
    if not q:
        raise ValueError("Type a company name or a CUSIP first")
    ql = q.lower()
    matches = [r for r in pool["rows"]
               if ql in r["issuer"].lower()
               or (r.get("cusip") and ql in r.get("cusip", "").lower())]
    if not matches:
        raise LookupError(f"None of the tracked funds show a position "
                          f"matching '{q}' in their latest 13F")

    by_key: dict[str, dict] = {}
    for r in matches:
        e = by_key.setdefault(r["key"], {"issuer": r["issuer"], "class": r.get("class", ""),
                                         "cusip": r.get("cusip", ""), "rows": []})
        e["rows"].append(r)

    def _total(e: dict) -> float:
        return sum(r["value"] for r in e["rows"])

    best = max(by_key.values(), key=_total)
    holders = sorted({r["fund"] for r in best["rows"] if r["value"] > 0})
    return {
        "name": best["issuer"], "class": best.get("class", ""),
        "cusip": best.get("cusip", ""),
        "asset": next((r["asset"] for r in best["rows"]), "stock"),
        "total_value": _total(best),
        "prev_total_value": sum(r["prev_value"] or 0.0 for r in best["rows"]),
        "n_funds": len(holders),
        "funds": holders,
        "rows": sorted(best["rows"], key=lambda r: -r["value"]),
        "alternatives": [{"name": e["issuer"], "cusip": e.get("cusip", "")}
                         for e in by_key.values() if e is not best][:5],
    }


def market_view(refresh: bool = False) -> dict:
    """All tracked funds at once + the 'crowded names' picture.

    Cached ~12h (13F only changes quarterly). One fund failing to load
    doesn't sink the rest. A roster change invalidates the cache via the
    same fingerprint the pool uses.
    """
    view_path = _cache_file("_marketview.json")
    if not refresh and view_path.exists() and time.time() - view_path.stat().st_mtime < 12 * 3600:
        try:
            d = json.loads(view_path.read_text())
            if d.get("v") == _VIEW_VERSION and d.get("roster") == roster_fingerprint():
                return _apply_curated_metadata(d)
        except (json.JSONDecodeError, OSError):
            pass

    pool = scan_pool(refresh=refresh)

    # Crowded names, the CUSIP-aware way: group current holdings by the
    # stable security key, not by fuzzy name (which used to split a company
    # that was spelled slightly differently by two funds into two rows).
    grouped: dict[str, dict] = {}
    for r in pool["rows"]:
        if r["value"] <= 0:
            continue
        g = grouped.setdefault(r["key"], {"name": r["issuer"], "funds": set(), "value": 0.0})
        g["funds"].add(r["fund"])
        g["value"] += r["value"]
    crowded = [{"name": g["name"], "funds": sorted(g["funds"]), "value": g["value"]}
               for g in grouped.values() if len(g["funds"]) >= 3]
    crowded.sort(key=lambda c: -c["value"])

    view = {
        "v": _VIEW_VERSION,
        "roster": roster_fingerprint(),
        "as_of": pool["as_of"],
        "funds": pool["funds"],
        "crowded": crowded[:20],
        "n_ok": sum(1 for f in pool["funds"] if "error" not in f),
        "n_total": len(pool["funds"]),
        "generated": pool["generated"],
    }
    try:
        view_path.write_text(json.dumps(view))
    except OSError:
        pass
    return view
