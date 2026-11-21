"""The polite web client: open textbooks, on their own terms.

The research section's gather runs over four backends with clean,
challenge-free APIs, all verified reachable from a normal machine
(over the DNS-over-HTTPS fallback in ``netfix`` for hosts whose names
the system resolver can't answer):

  Wikipedia   — the encyclopedic treatment of the topic.
  Wikibooks   — open textbooks; the closest thing to a real chapter.
  Wikiversity — study material and worked examples.
  arXiv       — the academic papers, by abstract.

Each backend is best best-effort: a slow or blocked one is skipped and
the caller's progress lines say so. The gathered text is capped, then
handed to the model by the research module.

The backtest lab's date-gated researcher lives in
``app/lab_research.py`` and shares the ``_http_get`` below (the same
rate-limit reality: the wiki API and arXiv both throttle bursts).

(Bing and the classic meta-searchers were probed and rejected from
this network: Bing answers with a correct page frame but unrelated
results — a datacenter-IP behaviour that changes with the wind — and
DuckDuckGo/Mojeek serve bot challenges.)

Tests pass a fake ``http_get``; nothing in this module is called with
a real URL from a test.
"""
from __future__ import annotations

import re
import time

SEARCH_TIMEOUT = 15.0          # per backend request, seconds
_MAX_GATHER_CHARS = 18_000     # the text handed to the model
_PER_SOURCE_CHARS = 4_500      # any single page's cap inside that
_MIN_GATHER_CHARS = 300        # below this the model would invent material

_UA = {"User-Agent": "Longview/1.0 (a reference research tool)"}


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


def gather(query: str, report,
           http_get=None) -> tuple[str, list[dict]]:
    """Run the pool, in order. ``report`` gets plain-English progress
    lines as it goes. Returns (gathered_text, sources).

    The backends call the module-global ``_http_get``; passing a
    different ``http_get`` swaps the global for the duration of the
    call — the tests use a fake and never touch the web. The live path
    passes nothing and nothing is swapped, so concurrent jobs cannot
    see one another's fetcher. The wiki hosts are fixed — the query
    travels as a parameter, never in the URL host.
    """
    if http_get is None:
        return _gather(query, report)
    saved = _http_get
    globals()["_http_get"] = http_get
    try:
        return _gather(query, report)
    finally:
        globals()["_http_get"] = saved


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
