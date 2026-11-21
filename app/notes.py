"""Your notes: pages of writing, plus anything you saved from the app.

Pages live in ``data/notes.json`` — the same ``{v, updated, ...}``
envelope and atomic write as the portfolio and the roster. Each page
carries two kinds of content:

- ``body``: free text the person writes (the note itself).
- ``snippets``: pieces saved from elsewhere in Longview — an Ask answer,
  a backtest result, a smart-money row, a company snapshot. Each is a
  tag, a title, and a plain list of lines, rendered verbatim.

A missing or corrupt file is an *empty* notebook, never an error.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from pathlib import Path

NOTES_PATH = Path(__file__).resolve().parent.parent / "data" / "notes.json"
_NOTES_VERSION = 1

_lock = threading.Lock()

_TITLE_MAX = 120
_BODY_MAX = 20000
_LINE_MAX = 400
_LINES_MAX = 60

SOURCES = {"ask", "backtest", "money", "company", "other"}


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(5)


def _clean_text(x, max_len: int) -> str:
    """Collapse whitespace runs, trim to max_len. None/'' -> ''."""
    return " ".join(str(x or "").split())[:max_len]


def _clean_lines(lines) -> list[str]:
    """A list of strings, each trimmed to _LINE_MAX, empty lines dropped
    except between content (they read as paragraph breaks when rendered)."""
    if not isinstance(lines, (list, tuple)):
        raise ValueError("snippet lines must be a list")
    out: list[str] = []
    for ln in lines:
        s = str(ln).strip()[:_LINE_MAX]
        if not s and (not out or not out[-1]):
            continue  # never lead with, or double up, blank lines
        if len(out) >= _LINES_MAX:
            break
        out.append(s)
    while out and not out[-1]:
        out.pop()          # a blank line at the very end is just noise
    return out


def _clean_source(x) -> str:
    s = str(x or "other").strip().lower()[:24]
    return s if s in SOURCES else "other"


def _clean_title(x) -> str:
    return _clean_text(x, _TITLE_MAX)


def _clean_body(x) -> str:
    return str(x or "").strip()[:_BODY_MAX]


def _clean_snippet(raw: dict, now: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("bad snippet")
    title = _clean_title(raw.get("title"))
    lines = _clean_lines(raw.get("lines") or [])
    if not title and not any(lines):
        raise ValueError("a snippet needs a title or some content")
    return {
        "id": _new_id("s"),
        "source": _clean_source(raw.get("source")),
        "title": title,
        "lines": lines,
        "saved_at": now,
    }


def _snippet_hash(source: str, title: str, lines: list[str]) -> str:
    return hashlib.sha1(
        (source + "\x00" + title + "\x00" + "\n".join(lines)).encode("utf-8")
    ).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Persistence (mirrors the portfolio's load/save pair)
# ---------------------------------------------------------------------------

def _load_file() -> list[dict] | None:
    """The saved pages, or None if the file is missing or corrupt."""
    try:
        d = json.loads(NOTES_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if d.get("v") != _NOTES_VERSION:
        return None
    pages = d.get("pages")
    if not isinstance(pages, list):
        return None
    ok = []
    for p in pages:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str):
            return None
        if not isinstance(p.get("snippets"), list):
            p["snippets"] = []
        ok.append(p)
    return ok


def _save_file(pages: list[dict]) -> None:
    """The notebook is the user's data, written atomically.

    Lock-free on purpose: the mutators below hold the lock across the
    read-modify-write (same as the portfolio's save).
    """
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = NOTES_PATH.parent / (NOTES_PATH.name + ".tmp")
    tmp.write_text(json.dumps(
        {"v": _NOTES_VERSION, "updated": int(time.time()), "pages": pages},
        indent=1))
    tmp.replace(NOTES_PATH)


def load_pages() -> list[dict]:
    """All saved pages; a missing or corrupt file means 'none yet'."""
    return _load_file() or []


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_summary(p: dict) -> dict:
    """The list view: everything except the (possibly long) content."""
    body = p.get("body") or ""
    first_snip = (p.get("snippets") or [{}])[0] if p.get("snippets") else {}
    preview = (body or (first_snip.get("lines") or [""])[0])[:90]
    return {
        "id": p["id"],
        "title": p.get("title") or "Untitled",
        "updated": p.get("updated") or p.get("created") or 0,
        "n_snippets": len(p.get("snippets") or []),
        "preview": preview,
    }


def list_pages() -> list[dict]:
    """Every page as a summary, most recently updated first."""
    pages = load_pages()
    pages.sort(key=lambda p: -(p.get("updated") or p.get("created") or 0))
    return [page_summary(p) for p in pages]


def get_page(page_id: str) -> dict:
    """One full page. Raises KeyError when there is no such page."""
    for p in load_pages():
        if p["id"] == page_id:
            return p
    raise KeyError(page_id)


def create_page(title: str, body: str = "") -> dict:
    """A new page. An empty title is allowed: the UI focuses the title
    box on the way in, so the name usually follows within seconds."""
    now = int(time.time())
    page = {
        "id": _new_id("n"),
        "title": _clean_title(title),
        "body": _clean_body(body),
        "created": now,
        "updated": now,
        "snippets": [],
    }
    with _lock:
        pages = load_pages()
        pages.append(page)
        _save_file(pages)
    return page


def update_page(page_id: str, title=None, body=None) -> dict:
    """Change the title and/or body. Passing None leaves that field alone.
    Raises KeyError for a missing page."""
    with _lock:
        pages = load_pages()
        for p in pages:
            if p["id"] == page_id:
                if title is not None:
                    p["title"] = _clean_title(title)
                if body is not None:
                    p["body"] = _clean_body(body)
                p["updated"] = int(time.time())
                _save_file(pages)
                return p
    raise KeyError(page_id)


def delete_page(page_id: str) -> dict:
    """Drop a page. Raises KeyError when it isn't there."""
    with _lock:
        pages = load_pages()
        for i, p in enumerate(pages):
            if p["id"] == page_id:
                removed = pages.pop(i)
                _save_file(pages)
                return removed
    raise KeyError(page_id)


# ---------------------------------------------------------------------------
# Snippets: the pieces saved from the rest of the app
# ---------------------------------------------------------------------------

def add_snippet(page_id: str, source: str, title: str, lines: list[str]) -> dict:
    """Append a saved piece to a page. Returns the page.

    Re-saving the same piece to the same page is a no-op (the page is
    returned, nothing duplicated): the save button is meant to be used
    again while the person is still thinking.
    Raises KeyError for a missing page, ValueError for an empty piece.
    """
    now = int(time.time())
    snip = _clean_snippet(
        {"source": source, "title": title, "lines": lines}, now)
    digest = _snippet_hash(snip["source"], snip["title"], snip["lines"])
    with _lock:
        pages = load_pages()
        for p in pages:
            if p["id"] == page_id:
                for e in p["snippets"]:
                    if _snippet_hash(e.get("source"), e.get("title"),
                                      e.get("lines") or []) == digest:
                        return p  # already here: no duplicate
                p["snippets"].append(snip)
                p["updated"] = now
                _save_file(pages)
                return p
    raise KeyError(page_id)


def delete_snippet(page_id: str, snippet_id: str) -> dict:
    """Remove one saved piece from a page. Raises KeyError either way."""
    with _lock:
        pages = load_pages()
        for p in pages:
            if p["id"] == page_id:
                before = len(p["snippets"])
                p["snippets"] = [e for e in p["snippets"]
                                 if e.get("id") != snippet_id]
                if len(p["snippets"]) == before:
                    raise KeyError(snippet_id)
                p["updated"] = int(time.time())
                _save_file(pages)
                return p
    raise KeyError(page_id)
