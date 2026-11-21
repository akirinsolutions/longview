"""Study: the AI learning notes centre.

A reference library of plain-English notes on how money works, plus two
ways for the reader to bring material of their own:

* paste a financial corpus (or part of one), or
* name a topic and the search gathers the open textbooks and reference
  pages on it from the web (Wikipedia, Wikibooks, Wikiversity, arXiv),

and the configured model turns either into one more note, saved with the
rest.

Two kinds of notes, one pipeline:

* **authored** — the reference set, hand-written in ``study_data/*.md``
  as a strict markdown subset. Never deleted, never model-generated.
* **ai** — notes the model wrote from a document the reader pasted,
  saved to ``data/study.json`` (``LONGVIEW_STUDY_NOTES`` moves the
  file; the legacy ``PROOF_STUDY_NOTES`` is read as a fallback).

The renderer is deliberately small: it escapes everything first, then
applies exactly the subset a note may use — ``##`` sections,
paragraphs, ``-`` bullets, ``1.`` lists, ``>`` pull quotes,
``**bold**``/``*italic*``/`` `code` ``, and ``--`` rules. Markup it
does not know renders as harmless text, so a note can never script the
page.
"""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

from . import llm

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: The reader's own notes. Authored notes live in ``study_data`` next to
#: this file and are part of the app, not the reader's data.
DATA_PATH = Path(os.environ.get(
    "LONGVIEW_STUDY_NOTES",
    os.environ.get(
        "PROOF_STUDY_NOTES",
        str(_DATA_DIR / "study.json"),
    ),
))

NOTES_DIR = Path(__file__).resolve().parent / "study_data"

#: A reentrant lock: ai_summarize holds it across the read-modify-save.
_LOCK = threading.RLock()

# The document the reader pastes (or the text the search gathers) for
# the AI to turn into a note.
MAX_TEXT_CHARS = 20_000

# Sanity bands for the model's answer. The graduate treatment targets
# 1,500–2,500 words; the bands only reject degenerate or runaway output.
AI_TITLE_MAX = 90
AI_FIELD_MAX = 40
AI_SUMMARY_MAX = 220
AI_BODY_WORDS_MIN = 250
AI_BODY_WORDS_MAX = 6_000

# The model call's budget. The resident local model is a *thinking*
# model: its reasoning counts against the token budget. Measured, a full
# graduate note fits a 32,000-token budget in ~2–3 minutes; 16,000 comes
# back empty (the thinking alone spends more). 300 s timeout for the same.
AI_LLM_MAX_TOKENS = 32_000
AI_LLM_TIMEOUT = 300.0
# The search's write step reads up to 18,000 gathered characters — several
# times the paste flow's input, which the 32k/300 s pair was measured
# against. The resident thinking model spends tokens *reasoning* before
# writing a word, and on a real search gather it burned an entire
# 32,000-token budget on reasoning and came back empty (measured: 728 s,
# 99,971 characters of thinking, zero output). 48,000 leaves room to
# think *and* write (the model's context is 262k; verified accepted);
# the window is that same run plus margin. On the timeout the job fails
# in plain English with the pages it found — it never hangs.
AI_LLM_MAX_TOKENS_SEARCH = 48_000
AI_LLM_TIMEOUT_SEARCH = 1_500.0

_SYSTEM = """You are an expert financial writer with graduate-level depth. The reader is bringing source material — a document they pasted, or material gathered from the web — and wants it turned into one study note for a personal learning centre, written at postgraduate level.

Return ONLY one JSON object, no prose around it:
{"title": "...", "field": "...", "summary": "...", "body": "..."}

Rules:
- title: a short descriptive name, at most 10 words.
- field: one or two words naming the subject, e.g. "Credit risk" or "Bonds".
- summary: one plain sentence, at most 30 words. No hype, no "in this document".
- body: 1,500 to 2,500 words, organised as 8 to 12 sections.
- Depth is the point. Write for a smart reader with no specialist
  background: define every technical term in plain English on first use,
  then use it precisely. Where the source describes a mechanism, a model
  or a figure, explain how it works step by step and state the
  assumptions it rests on. For each major idea include its standard
  criticisms and limits, and where the source gives numbers, keep them
  and show what they imply. Prefer exact, structural explanations over
  generalities: a note that could have been written about anything is a
  failure.
- Body markup, using exactly these and nothing else:
  "## " for section headings (no other heading level),
  plain paragraphs separated by blank lines,
  "- " for bullets, "1. " for ordered steps,
  "> " for a short pull quote from the source,
  "**term**" for a few key terms,
  "`code`" for a formula or symbol, e.g. `dP = -D * dr`.
  No tables, no links, no markdown besides that list.
- Be faithful: every figure, name, date and claim in the note must come
  from the source text. If you add standard background to make a point
  land, mark it plainly, e.g. "as a general rule". Never invent figures.
- No preamble, no "here is your note", no closing pleasantries.
- If the source text is thin or partly off-topic for the topic, write
  the best honest note the text supports and say plainly what it cannot
  cover, rather than inventing material."""


# ---------------------------------------------------------------------------
# The small renderer
# ---------------------------------------------------------------------------

def _inline(text: str) -> str:
    """Escape, then apply the inline subset (bold, italic, code)."""
    t = html.escape(text, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
    return t


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9’'-]+", text))


def render_markdown(raw: str) -> str:
    """The strict subset → escaped HTML. Unknown markup is plain text."""
    out: list[str] = []
    para: list[str] = []
    bullets: list[str] = []
    ordered: list[str] = []
    quote: list[str] = []

    def flush_para():
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    def flush_bullets():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{_inline(b)}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    def flush_ordered():
        if ordered:
            out.append("<ol>" + "".join(f"<li>{_inline(b)}</li>" for b in ordered) + "</ol>")
            ordered.clear()

    def flush_quote():
        if quote:
            out.append("<blockquote>" + _inline(" ".join(quote)) + "</blockquote>")
            quote.clear()

    def flush_all():
        flush_para(); flush_bullets(); flush_ordered(); flush_quote()

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            flush_all()
        elif s == "--":
            flush_all(); out.append("<hr>")
        elif s.startswith("## "):
            flush_all(); out.append(f"<h2>{_inline(s[3:])}</h2>")
        elif s.startswith("### "):
            flush_all(); out.append(f"<h3>{_inline(s[4:])}</h3>")
        elif s.startswith("# "):
            flush_all(); out.append(f"<h2>{_inline(s[2:])}</h2>")
        elif s.startswith(("- ", "* ")):
            flush_para(); flush_ordered(); flush_quote()
            bullets.append(s[2:].strip())
        elif re.match(r"^\d+\.\s", s):
            flush_para(); flush_bullets(); flush_quote()
            ordered.append(re.sub(r"^\d+\.\s*", "", s))
        elif s.startswith("> "):
            flush_para(); flush_bullets(); flush_ordered()
            quote.append(s[2:].strip())
        else:
            flush_bullets(); flush_ordered(); flush_quote()
            para.append(s)
    flush_all()
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The two corpora
# ---------------------------------------------------------------------------

_META_RE = re.compile(r"^~\s*([a-z_]+)\s*:\s*(.*)$")


def _parse_authored(path: Path) -> dict:
    """One ``study_data/*.md`` file → one note dict (body unrendered)."""
    raw = path.read_text(encoding="utf-8")
    title, field, summary, body_lines = path.stem, "", "", []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("# "):
            title = s[2:].strip()
        elif (m := _META_RE.match(s)):
            if m.group(1) == "field":
                field = m.group(2).strip()
            elif m.group(1) == "summary":
                summary = m.group(2).strip()
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    return {
        "id": path.stem,
        "kind": "authored",
        "title": title,
        "field": field,
        "summary": summary,
        "body": body,
    }


def authored_notes() -> list[dict]:
    if not NOTES_DIR.exists():
        return []
    return [_parse_authored(p) for p in sorted(NOTES_DIR.glob("*.md"))]


def _user_notes() -> list[dict]:
    if not DATA_PATH.exists():
        return []
    try:
        raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    notes = raw.get("notes") if isinstance(raw, dict) else None
    if not isinstance(notes, list):
        return []
    keep = []
    for n in notes:
        if isinstance(n, dict) and isinstance(n.get("body"), str) and n.get("title"):
            keep.append(n)
    return keep


def _save_user(notes: list[dict]) -> None:
    """Atomic write of the reader's notes (the usual envelope)."""
    with _LOCK:
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA_PATH.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"v": 1, "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "notes": notes}, indent=1),
            encoding="utf-8")
        tmp.replace(DATA_PATH)


def all_notes() -> list[dict]:
    return authored_notes() + _user_notes()


def note_entry(n: dict) -> dict:
    """The list-view shape: everything except the body."""
    body = n.get("body") or n.get("summary") or ""
    w = _words(body)
    e = {
        "id": n["id"],
        "kind": n.get("kind", "authored"),
        "title": n.get("title") or n["id"],
        "field": n.get("field") or "General",
        "summary": n.get("summary") or "",
        "words": w,
        "minutes": max(1, round(w / 200)),
    }
    if e["kind"] == "ai":
        e["model"] = n.get("model") or ""
        e["created"] = n.get("created") or ""
        e["sources"] = len(n.get("sources") or [])
    return e


def get_note(nid: str) -> Optional[dict]:
    for n in all_notes():
        if n["id"] == nid:
            e = {
                **note_entry(n),
                "body": n.get("body", ""),
                "html": render_markdown(n.get("body", "")),
            }
            if n.get("kind") == "ai":
                # note_entry carries sources as a *count* (the list card
                # shows "N web sources"); the detail view renders the
                # "AI-written from N web sources" badge and the source
                # links, so the detail fetch returns the list itself.
                e["sources"] = [
                    {"title": s.get("title", "")[:160],
                     "url": s.get("url", "")[:300]}
                    for s in (n.get("sources") or [])[:12]
                ]
            return e
    return None


# ---------------------------------------------------------------------------
# The public surface (main.py routes onto these)
# ---------------------------------------------------------------------------

def meta() -> dict:
    notes = all_notes()
    return {
        "llm": llm.is_configured(),
        "count": len(notes),
        "fields": sorted({n.get("field") or "General" for n in notes}),
    }


def listing() -> list[dict]:
    return [note_entry(n) for n in all_notes()]


def _write_note(text: str, topic: str = "",
                sources: Optional[list[dict]] = None,
                source_label: str = "Document",
                max_tokens: int = AI_LLM_MAX_TOKENS,
                timeout: float = AI_LLM_TIMEOUT,
                config: dict | None = None) -> dict:
    """The shared tail of both AI paths (pasted document, gathered web
    text): one model call, strict validation, one saved note. Returns
    the saved note dict (``sources`` a list of ``{"title", "url"}`` for
    search-made notes); callers that need the rendered view run it
    through ``get_note``. Raises RuntimeError in plain English on any
    failure. Saves a good answer so the note survives a reload.
    ``max_tokens`` / ``timeout`` let the search path give the model a
    bigger budget and a longer window on its larger input
    (``AI_LLM_MAX_TOKENS_SEARCH`` / ``AI_LLM_TIMEOUT_SEARCH``).
    ``config`` is the request's model settings; the search job's thread
    cannot see the request, so its route passes them in."""
    from . import risk  # the shared llm seam

    user = (f"Topic the reader cares about: {topic.strip() or '(their choice)'}\n\n"
            f"{source_label}:\n\n" + text)

    # The local thinking model spends most of a small budget on reasoning
    # before writing a word; a full graduate note (1,500–2,500 words)
    # needs the room to reason *and* write. Measured: a 32,000-token
    # budget leaves a full answer in ~2–3 min; a 16,000 one comes back
    # empty.
    content, model = risk._post_llm(_SYSTEM, user,
                                    config=config,
                                    max_tokens=max_tokens,
                                    timeout=timeout)
    if not content or not content.strip():
        raise RuntimeError(
            "the model ran out of room to answer — try a shorter document")

    # Strict JSON; one rescue pass for models that wrap it in code fences.
    data = None
    for candidate in (content.strip(),
                      re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())):
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", candidate, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                    break
                except json.JSONDecodeError:
                    pass
    if not isinstance(data, dict):
        raise RuntimeError(
            "the model's answer didn't come back in the shape we check for — try again")

    title = str(data.get("title") or "").strip()
    field = re.sub(r"[^a-z0-9+& ]+", " ", str(data.get("field") or "").lower()).strip()
    summary = str(data.get("summary") or "").strip()
    body = str(data.get("body") or "").strip()

    if not (3 <= len(title) <= AI_TITLE_MAX):
        raise RuntimeError("the model's answer didn't come back in the shape we check for — try again")
    field = re.sub(r"\s+", " ", field)
    if not (2 <= len(field) <= AI_FIELD_MAX):
        field = (topic.strip()[:AI_FIELD_MAX] or "General").title()
    summary = re.sub(r"\s+", " ", summary)[:AI_SUMMARY_MAX]
    # The renderer owns the body; drop anything that belongs to the file header.
    body = "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("# ") and not l.strip().startswith("~ ")).strip()
    w = _words(body)
    if not (AI_BODY_WORDS_MIN <= w <= AI_BODY_WORDS_MAX):
        raise RuntimeError(
            "the model's answer came back the wrong size — try again, or a shorter document")

    note = {
        "id": f"ai-{time.strftime('%Y%m%d%H%M%S')}",
        "kind": "ai",
        "title": title,
        "field": field,
        "summary": summary,
        "body": body,
        "model": model,
        "created": time.strftime("%Y-%m-%d"),
    }
    if sources:
        note["sources"] = [
            {"title": (s.get("title") or "")[:160], "url": (s.get("url") or "")[:300]}
            for s in sources[:12]
            if (s.get("url") or "").startswith(("http://", "https://"))
        ]
    # A same-second second note must not overwrite the first.
    with _LOCK:
        notes = _user_notes()
        while any(n["id"] == note["id"] for n in notes):
            note["id"] += "b"
        notes.append(note)
        _save_user(notes)
    return note


def ai_summarize(text: str, topic: str = "") -> dict:
    """The reader's pasted document → one saved note. Raises RuntimeError
    in plain English; the route maps a missing key to 503 and failures to
    502."""
    if not llm.is_configured():
        raise RuntimeError(
            "no language model key is set — add one in Settings")
    text = (text or "").strip()
    if len(text) < 200:
        raise RuntimeError(
            "that's not much to read — paste more of the document "
            "(a few hundred words at least)")
    if len(text) > MAX_TEXT_CHARS:
        raise RuntimeError(
            f"that document is {len(text):,} characters; the reader "
            f"accepts up to {MAX_TEXT_CHARS:,} — paste the part that matters")
    note = _write_note(text, topic, source_label="Document",
                       config=llm.resolve())
    return get_note(note["id"])


def delete_note(nid: str) -> None:
    """The reader's own notes only; the reference set is part of the app."""
    with _LOCK:
        notes = _user_notes()
        if not any(n["id"] == nid for n in notes):
            raise RuntimeError(
                "that note is part of the reference set — the centre's "
                "own notes can't be deleted")
        notes = [n for n in notes if n["id"] != nid]
        _save_user(notes)


# ---------------------------------------------------------------------------
# Web search — "find the textbook material on this topic"
# ---------------------------------------------------------------------------
#
# The pool is four backends with clean, challenge-free APIs, all verified
# reachable from this machine (over the DNS-over-HTTPS fallback in
# ``netfix`` for hosts whose names the system resolver can't answer):
#
#   Wikipedia   — the encyclopedic treatment of the topic.
#   Wikibooks   — open textbooks; the closest thing to a real chapter.
#   Wikiversity — study material and worked examples.
#   arXiv       — the academic papers, by abstract.
#
# Each backend is best-effort: a slow or blocked one is skipped and the
# job's progress says so. The gathered text is capped, then handed to the
# model through the same ``_write_note`` tail as a pasted document.
#
# (Bing and the classic meta-searchers were probed and rejected from this
# network: Bing answers with a correct page frame but unrelated results —
# a datacenter-IP behaviour that changes with the wind — and
# DuckDuckGo/Mojeek serve bot challenges.)

SEARCH_TIMEOUT = 15.0          # per backend request, seconds
_MAX_GATHER_CHARS = 18_000     # the text handed to the model (≤ MAX_TEXT_CHARS)
_PER_SOURCE_CHARS = 4_500      # any single page's cap inside that
_MIN_GATHER_CHARS = 300        # below this the model would invent material
_JOB_TTL = 600.0               # finished jobs keep 10 minutes in memory
_MAX_JOBS = 500

_UA = {"User-Agent": "Longview/1.0 (a reference research tool)"}

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.RLock()


def _http_get(url: str, params: dict, timeout: float = SEARCH_TIMEOUT):
    """One GET, with retries for 429/503. The wiki API and arXiv both
    rate-limit bursts (arXiv asks for 1 request per 3 s), and this
    machine's resolver makes every call a longer hop — a single retry
    was not enough in a live gather, where half a page list failed
    silently. Three attempts, with the backoff climbing. Raises
    RuntimeError in plain English on anything else that fails."""
    import httpx

    waits = (None, 2.5, 5.0)
    r = None
    for wait in waits:
        if wait:
            time.sleep(wait)
        r = httpx.get(url, params=params, headers=_UA,
                      timeout=timeout, follow_redirects=True)
        if r.status_code in (429, 503):
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"{url} answered {r.status_code}")
        return r
    raise RuntimeError(f"{url} answered {r.status_code}")


def _normalize(text: str) -> str:
    """Light whitespace tidying: keep paragraph breaks, kill runs."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


#: Query words too generic to count as relevance evidence on their own.
_QUERY_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over",
    "model", "models", "theory", "theories", "guide", "guides", "overview",
    "basics", "basic", "intro", "introduction", "chapter", "book", "books",
    "textbook", "textbooks", "explain", "explains", "explanation", "notes",
    "note", "study", "finance", "financial",
}


def _query_words(query: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", query.lower()) if w not in _QUERY_STOP}


def _relevant(hit: dict, words: set[str]) -> bool:
    """MediaWiki search over-matches hard (a London emission-zone page,
    and education pages, for a Merton query — verified). Keep a hit only
    when its title or snippet echoes the query at word boundaries: at
    least two words, or one when the query is one or two — and always
    the longest word, the one a truly on-topic page must contain.
    ``sorted`` makes the longest-word tie-break deterministic: the words
    come from a set, so a bare ``max`` flips with iteration order (a
    Black–Scholes vs. CAPM tie observed in a live gather)."""
    if not words:
        return True
    hay = (hit.get("title", "") + " " + hit.get("snippet", "")).lower()

    def has(w: str) -> bool:
        return re.search(rf"\b{re.escape(w)}\b", hay) is not None

    echoed = [w for w in words if has(w)]
    if not echoed or (len(echoed) < 2 and len(words) > 2):
        return False
    return has(max(sorted(words), key=len))


def _wiki_search(host: str, label: str, query: str) -> list[dict]:
    """The MediaWiki search API (shared by Wikipedia, Wikibooks,
    Wikiversity). Titles, URLs and snippets; content comes in the
    gather. Off-topic hits are dropped here, before the page fetches.

    Two passes: the reader's own query, and the same query anchored to
    the domain. For a how-phrase, MediaWiki's rank serves the page it
    associates most with a single word first — for "how do bonds work"
    that is a baseball player, a grief-psychology page and a jazz
    composer, ahead of the actual bond pages. The anchored pass is what
    lifts the on-domain pages (verified: it is the difference between a
    gather of four off-topic pages and a gather of bond pages). The
    merge dedupes by URL and lists the anchored hits first, so the
    gather reads the on-domain pages before the stragglers."""
    from urllib.parse import quote

    words = _query_words(query)
    out = []
    seen_urls: set[str] = set()
    for q in (f"{query} finance", query):
        r = _http_get(
            f"https://{host}/w/api.php",
            {"action": "query", "list": "search", "srsearch": q,
             "srlimit": "8", "srprop": "snippet", "format": "json"},
        )
        for it in r.json().get("query", {}).get("search", []):
            title = (it.get("title") or "").strip()
            url = f"https://{host}/wiki/{quote(title, safe='')}"
            if not title or url in seen_urls or not _relevant(it, words):
                continue
            it = dict(it)
            it.pop("snippet", None)      # keep the dict lean for storage
            seen_urls.add(url)
            out.append({"title": title, "url": url, "label": label})
    return out


def _wiki_text(host: str, title: str) -> str:
    """One wiki page as plain text: the extracts extension first, the
    tag-stripped HTML of the parse endpoint when a wiki lacks it."""
    r = _http_get(f"https://{host}/w/api.php",
                  {"action": "query", "titles": title, "prop": "extracts",
                   "explaintext": 1, "format": "json"})
    for p in r.json().get("query", {}).get("pages", {}).values():
        ext = (p.get("extract") or "").strip()
        if ext:
            return ext
    r2 = _http_get(f"https://{host}/w/api.php",
                   {"action": "parse", "page": title, "prop": "text",
                    "format": "json"})
    page = (r2.json().get("parse", {}).get("text", {}) or {}).get("*") or ""
    return re.sub(r"<[^>]+>", " ", page)


def _arxiv_search(query: str) -> list[dict]:
    """The arXiv API (Atom XML). Abstracts come with the results, so no
    second fetch per hit."""
    import xml.etree.ElementTree as ET

    q = re.sub(r'[^A-Za-z0-9 ]', " ", query).strip()
    words = {w for w in re.findall(r"[a-z]{4,}", q.lower()) if w not in _QUERY_STOP}
    # A quoted phrase is arXiv's strictest mode and often returns zero for
    # a natural-language topic; the AND of its significant words is the
    # honest fallback. The arXiv export API is also a famously slow index:
    # 15 s times out on a cold start, 45 s is the window.
    r = _http_get("https://export.arxiv.org/api/query",
                  {"search_query": f'all:"{q}"', "max_results": "5",
                   "sortBy": "relevance"},
                  timeout=45.0)
    if not r.text.count("<entry>") and words:
        r = _http_get("https://export.arxiv.org/api/query",
                      {"search_query": " AND ".join(f"all:{w}" for w in list(words)[:5]),
                       "max_results": "5", "sortBy": "relevance"},
                      timeout=45.0)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in ET.fromstring(r.text).findall("a:entry", ns):
        t = re.sub(r"\s+", " ", e.findtext("a:title", default="", namespaces=ns) or "").strip()
        url = (e.findtext("a:id", default="", namespaces=ns) or "").strip()
        s = re.sub(r"\s+", " ", e.findtext("a:summary", default="", namespaces=ns) or "").strip()
        if not (t and url.startswith("http")):
            continue
        if not _relevant({"title": t, "snippet": s}, words):
            continue
        out.append({"title": t, "url": url, "label": "arXiv", "_text": s})
    return out


def _gather(query: str, report) -> tuple[str, list[dict]]:
    """Run the pool, in order. ``report`` gets plain-English progress
    lines as it goes. Returns (gathered_text, sources)."""
    sources: list[dict] = []
    texts: list[str] = []
    total = 0
    seen: set[str] = set()

    def keep(h: dict, text: str) -> None:
        nonlocal total
        if total >= _MAX_GATHER_CHARS or h["url"] in seen:
            return
        text = _normalize(text)[:_PER_SOURCE_CHARS]
        if len(text) < 80:          # a stub is no source
            return
        seen.add(h["url"])
        # The header line is part of the text the model reads; budget it.
        header = f"[Source: {h['title'][:80]} — {h.get('label', '')}]"
        sources.append({"title": h["title"], "url": h["url"], "label": h.get("label", "")})
        texts.append(text)
        total += len(text) + len(header) + 8

    for label, host in (("Wikipedia", "en.wikipedia.org"),
                        ("Wikibooks", "en.wikibooks.org"),
                        ("Wikiversity", "en.wikiversity.org")):
        report(f"Searching {label}…")
        hits: list[dict] = []
        search_failed = False
        try:
            hits = _wiki_search(host, label, query)
        except Exception:
            search_failed = True
        if search_failed:
            # A search that never came back is not the same as an empty
            # one: say so, and move on — the other backends still run.
            report(f"{label}: the search itself didn't answer — skipped.")
            continue
        if not hits:
            report(f"{label}: nothing for that topic.")
            continue
        plural = "s" if len(hits) != 1 else ""
        report(f"{label}: found {len(hits)} page{plural} — reading the best of them…")
        for h in hits[:5]:
            if total >= _MAX_GATHER_CHARS:
                break
            try:
                keep(h, _wiki_text(host, h["title"]))
            except Exception:
                # A page that won't load is skipped, but the reader
                # should know it happened — a silent skip looked like a
                # working search that simply "found" few pages.
                report(f"{label}: “{h['title'][:48]}” didn't load — skipped")
        if total >= _MAX_GATHER_CHARS:
            break

    report("Searching arXiv — the academic index is a slow one, bearing with it…")
    try:
        for h in _arxiv_search(query)[:5]:
            if total >= _MAX_GATHER_CHARS:
                break
            text = h.pop("_text", "")
            if text:
                keep(h, text)
    except Exception:
        report("arXiv: the index didn't answer in the end — skipped")

    parts = [f"[Source {i}: {s['title'][:80]} — {s['label']}]\n{t}"
             for i, (s, t) in enumerate(zip(sources, texts), 1)]
    text = "\n\n".join(parts)
    if len(text) > _MAX_GATHER_CHARS:      # backstop: cut on a word boundary
        cut = text[:_MAX_GATHER_CHARS]
        text = cut[:cut.rfind(" ")] if " " in cut else cut
    return text, sources


def _finish(job_id: str, status: str, message: str,
            sources: Optional[list[dict]] = None,
            note: Optional[dict] = None) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = status
        job["message"] = message
        if sources:
            job["sources"] = sources
        if note is not None:
            job["note"] = note_entry(note)
        job["done"] = time.time()


def _search_worker(job_id: str, query: str, topic: str,
                   config: dict | None = None) -> None:
    """The background thread: gather, then write the note through the
    same tail as a pasted document. Never raises — the job records it.
    ``config`` is captured at request time: a fresh thread cannot see
    the request's model key, so its route passes the settings in."""
    def report(msg: str) -> None:
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
            if job is not None and job["status"] == "running":
                job["progress"].append(msg)
                job["progress"] = job["progress"][-8:]

    try:
        text, sources = _gather(query, report)
    except Exception:
        _finish(job_id, "failed",
                "the search didn't complete — the web wasn't reachable just now; try again in a moment")
        return
    if len(text) < _MIN_GATHER_CHARS:
        _finish(job_id, "failed",
                "I could reach the web, but the pages came back too thin to make a solid note — try a more specific topic",
                sources=sources)
        return
    if not llm.is_configured(config):
        _finish(job_id, "gathered",
                "I found the material, but no model key is set to write the note with — add one in Settings; the pages it found are listed in the sources",
                sources=sources)
        return
    plural = "s" if len(sources) != 1 else ""
    report(f"Got {len(sources)} source{plural}. Writing the graduate note — "
           f"from this much material the local model needs ten minutes or "
           f"more; I'll let you know the moment it lands…")
    try:
        note = _write_note(text, topic, sources=sources,
                           source_label="Gathered web material",
                           max_tokens=AI_LLM_MAX_TOKENS_SEARCH,
                           timeout=AI_LLM_TIMEOUT_SEARCH,
                           config=config)
        _finish(job_id, "done", "the note is written and saved",
                sources=sources, note=note)
    except RuntimeError as e:
        _finish(job_id, "failed",
                f"the model didn't finish the note ({e}) — the pages it found are in the sources",
                sources=sources)
    except Exception:
        # A worker that dies on an unhandled exception strands the job in
        # "running" forever and the client polls a dead job: the spinner
        # turns and nothing ever lands. The docstring says "never raises"
        # — this is what that means. The search itself worked, so the
        # pages it found are still worth seeing.
        _finish(job_id, "failed",
                "the model stopped before the note was finished — the "
                "search itself worked, so the pages it found are listed; "
                "try the search again",
                sources=sources)


def _prune_jobs() -> None:
    """Call under the lock: finished jobs age out, then the oldest go."""
    now = time.time()
    for j in [j for j in _JOBS.values()
              if j["status"] != "running" and now - j.get("done", now) > _JOB_TTL]:
        _JOBS.pop(j["id"], None)
    if len(_JOBS) > _MAX_JOBS:
        # Only finished jobs may be evicted: dropping a running one would
        # orphan its worker (its _finish would land on nothing).
        finished = [j for j in _JOBS.values() if j["status"] != "running"]
        order = sorted(finished, key=lambda j: j.get("done") or j["created"])
        for j in order[: len(_JOBS) - _MAX_JOBS]:
            _JOBS.pop(j["id"], None)


def _job_view(job: dict) -> dict:
    return {
        "id": job["id"],
        "status": job["status"],
        "message": job.get("message") or "",
        "progress": list(job.get("progress", [])),
        "sources": list(job.get("sources", [])),
        "note": job.get("note"),
    }


def start_search(query: str, topic: str = "") -> dict:
    """Create a search job and start its thread. Raises RuntimeError in
    plain English for a too-short topic."""
    import secrets

    query = (query or "").strip()
    if len(query) < 4:
        raise RuntimeError("give me a topic to search — a few words at least")
    query = query[:120].strip()
    job = {
        "id": "s" + secrets.token_hex(5),
        "status": "running",
        "message": "starting the search…",
        "progress": ["starting the search…"],
        "sources": [],
        "note": None,
        "created": time.time(),
    }
    with _JOBS_LOCK:
        _prune_jobs()
        _JOBS[job["id"]] = job
    threading.Thread(target=_search_worker,
                     args=(job["id"], query, (topic or "").strip(),
                           llm.resolve()),
                     daemon=True).start()
    return _job_view(job)


def get_search_job(job_id: str) -> Optional[dict]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return _job_view(job) if job else None
