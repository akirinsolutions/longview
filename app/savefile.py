"""The save file — everything the reader owns, as plain text.

One file, human-readable, no markup: the reader downloads it from
Settings and keeps it somewhere safe. It is not the importable format
(the JSON data file round-trips through Import); this is the copy a
person reads — their portfolio, risk moves, notes, followed funds,
research reports, and the economy tree's state, in plain words.

Nothing here invents numbers the app doesn't hold: no prices, no
weights — those come from live market data and are out of date the
moment they are shown. What the file holds is what the app saved,
plus a line per section on what it means.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import vault

_SECTION_CAP = 4_000_000          # no file bigger than this goes out
_NOTE_BODY_CAP = 1_200
_REPORT_BODY_CAP = 1_500
_PAGE_SNIPPET_LINES = 6


def _money(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    return f"{v:,.2f}"


def _line(s) -> str:
    return " ".join(str(s or "").split())


def _portfolio(v) -> str:
    sec = (v.get("sections", {}) or {}).get("portfolio") or {}
    positions = sec.get("positions") or []
    if not positions:
        return "Nothing saved — add a holding in the app and it appears here."
    out = []
    for p in positions:
        bits = []
        bits.append(p.get("ticker") or "?")
        name = _line(p.get("name"))
        if name and name != p.get("ticker"):
            bits.append(f"— {name}")
        if p.get("kind") == "custom":
            bits.append("(custom)")
        shares = p.get("shares")
        cost = p.get("cost_basis")
        if cost is not None:
            if p.get("kind") == "custom":
                bits.append(f"{_money(cost)} per unit")
            else:
                bits.append(f"cost {_money(cost)}/share")
        if shares is not None:
            bits.append(f"{_money(shares)} sh")
        if p.get("purchase_date"):
            bits.append(f"bought {p['purchase_date']}")
        if p.get("kind") == "custom" and p.get("price") is not None:
            bits.append(f"price {_money(p['price'])} {p.get('currency') or ''}".strip())
        line = "  ".join(bits)
        note = _line(p.get("note"))
        if note:
            line += f"  ·  {note}"
        out.append(line)
    return "\n".join(out)


def _risk(v) -> str:
    sec = (v.get("sections", {}) or {}).get("risk") or {}
    moves = sec.get("moves") or {}
    if not moves:
        return "No scenario yet — the moves you typed live here once you save them."
    out = []
    for key in sorted(moves):
        try:
            val = float(moves[key])
        except (TypeError, ValueError):
            continue
        out.append(f"  {key}  {val:+.1f}%")
    return "\n".join(out) if out else "No scenario yet."


def _notes(v) -> str:
    sec = (v.get("sections", {}) or {}).get("notes") or {}
    pages = sec.get("pages") or []
    if not pages:
        return "No note pages."
    out = []
    for p in pages:
        if not isinstance(p, dict):
            continue
        title = _line(p.get("title")) or "Untitled"
        created = p.get("created") or p.get("updated") or 0
        when = ""
        try:
            if created:
                when = "  (" + datetime.fromtimestamp(
                    int(created), timezone.utc).strftime("%Y-%m-%d") + ")"
        except (OSError, ValueError, OverflowError):
            when = ""
        out.append(f"## {title}{when}")
        body = (p.get("body") or "").strip()
        if body:
            if len(body) > _NOTE_BODY_CAP:
                body = body[:_NOTE_BODY_CAP] + " …"
            out.append(body)
        for snip in (p.get("snippets") or []):
            if not isinstance(snip, dict):
                continue
            tag = _line(snip.get("source") or "other")
            title2 = _line(snip.get("title"))
            if tag:
                out.append(f"  − saved piece ({tag})"
                           + (f" — {title2}" if title2 else ""))
            for ln in (snip.get("lines") or [])[:_PAGE_SNIPPET_LINES]:
                s = _line(ln)
                if s:
                    out.append(f"    {s}")
        out.append("")
    return "\n".join(out).rstrip()


def _roster(v) -> str:
    sec = (v.get("sections", {}) or {}).get("roster") or {}
    funds = sec.get("funds") or []
    if not funds:
        return "No followed funds — the app scans its eleven defaults."
    out = []
    for f in funds:
        if not isinstance(f, dict):
            continue
        bits = [_line(f.get("name")) or f.get("key") or "?"]
        if f.get("manager"):
            bits.append(f"— {_line(f.get('manager'))}")
        if f.get("cik"):
            bits.append(f"(CIK {f.get('cik')})")
        out.append("  " + " ".join(bits))
    return "\n".join(out)


def _research(v) -> str:
    sec = (v.get("sections", {}) or {}).get("research") or {}
    reports = sec.get("reports") or []
    if not reports:
        return "No research reports — give the Research section a goal and it writes one here."
    out = []
    for r in reports:
        if not isinstance(r, dict):
            continue
        title = _line(r.get("title")) or r.get("id") or "?"
        when = r.get("created") or ""
        out.append(f"## {title}" + (f"  ({when})" if when else ""))
        goal = _line(r.get("goal"))
        if goal:
            out.append(f"goal: {goal}")
        body = (r.get("body") or r.get("summary") or "").strip()
        if body:
            if len(body) > _REPORT_BODY_CAP:
                body = body[:_REPORT_BODY_CAP] + " …"
            out.append(body)
        src = r.get("sources") or []
        if isinstance(src, list) and src:
            out.append(f"sources: {len(src)}")
        out.append("")
    return "\n".join(out).rstrip()


def _economy(v) -> str:
    sec = (v.get("sections", {}) or {}).get("economy") or {}
    if not sec:
        return "The economy tree is untouched — the authored tree stands."
    tree = sec.get("tree") if isinstance(sec, dict) else None
    if not isinstance(tree, dict):
        return "The economy tree was edited (the file holds the edited tree — see the JSON)."
    updated = sec.get("updated") or ""
    try:
        note = f"The economy tree is edited in the file."
        if updated:
            note += f"  ·  last edited {str(updated).replace('T', ' ')[:19]}"
        return note
    except Exception:
        return "The economy tree is edited in the file."


def render(vault_dict=None, username=None) -> str:
    """The whole file, as one string of plain text."""
    v = vault_dict if isinstance(vault_dict, dict) else vault.load()
    exported = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    who = (username or "").strip()
    out = [
        "Longview — save file",
        "",
        f"Exported: {exported}" + (f"   ·   account: {who}" if who else ""),
        "",
        "This is a COPY for you to keep. It is plain text, not the importable",
        "format — for a full restore, keep the JSON data file exported in",
        "Settings (Download → JSON). The text file is for reading: it holds",
        "your portfolio, risk moves, notes, followed funds, research reports",
        "and the economy tree's state — exactly what the app holds.",
        "",
        "=" * 72,
        "PORTFOLIO",
        "=" * 72,
        _portfolio(v),
        "",
        "=" * 72,
        "RISK — SCENARIO MOVES",
        "=" * 72,
        _risk(v),
        "",
        "=" * 72,
        "NOTES",
        "=" * 72,
        _notes(v),
        "",
        "=" * 72,
        "FOLLOWED FUNDS (SMART MONEY)",
        "=" * 72,
        _roster(v),
        "",
        "=" * 72,
        "RESEARCH REPORTS",
        "=" * 72,
        _research(v),
        "",
        "=" * 72,
        "ECONOMY TREE",
        "=" * 72,
        _economy(v),
        "",
        "—",
        "Longview · the filings, decoded · MIT license",
    ]
    text = "\n".join(out)
    if len(text) > _SECTION_CAP:
        text = text[:_SECTION_CAP] + "\n\n… (truncated — the full data lives in the JSON file)\n"
    return text
