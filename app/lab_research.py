"""Date-gated web research for the strategy lab.

A backtest that does research must not see the future. On a simulated
date D this module may only read what a reader could have read that
day:

- **Wikipedia** — the newest page revision with a timestamp on or
  before D, then that revision's text. A page first published after D
  was not known that day; it is skipped, honestly.
- **arXiv** — only papers submitted on or before D. The API's
  ``submittedDate`` range does the heavy lifting, and a client-side
  check of each entry's published date is the guarantee.

The HTTP layer is the shared web client's ``_http_get`` in
``app/web.py`` (three attempts, 429/503 backoff — the same
rate-limit reality). One ``Researcher`` per backtest owns a call
budget and a result cache: repeated decision days that share a
Wikipedia revision cost one content fetch, and when the budget runs
out, later days skip research and say so in the log.

Tests pass a fake ``http_get``; nothing in this module is called with
a real URL from a test.
"""
from __future__ import annotations

import re

from app.web import _http_get

WIKI_HOST = "en.wikipedia.org"
ARXIV_URL = "https://export.arxiv.org/api/query"

#: One backtest's whole research budget, in web fetches.
DEFAULT_CALL_CAP = 120

#: How much of a page or a paper lands in the decider's context.
MAX_TEXT_CHARS = 2000


class _Skip(Exception):
    """A symbol could not be researched as of this date — carrying the
    plain-English reason that goes into the decision log."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _wikitext_to_plain(wt: str) -> str:
    """Wikitext lead section -> readable plain text (good enough for a
    language model; not for publication)."""
    t = re.sub(r"<[^>]+>", " ", wt)
    t = re.sub(r"\{\{[^{}]*\}\}", " ", t)
    t = re.sub(r"\[\[File:[^\]]+\]\]", " ", t)
    t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[https?://[^\]]+\]", " ", t)
    t = re.sub(r"={2,}|-{2,}", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _parse_atom(xml_text: str) -> list[tuple[str, str, str]]:
    """arXiv API Atom feed -> [(title, summary, published-iso-date)].

    Entries without a usable published date are dropped: an undated
    entry cannot be proven not to be from the future.
    """
    import xml.etree.ElementTree as ET

    ns = {"a": "http://www.w3.org/2005/Atom"}
    out: list[tuple[str, str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for e in root.findall("a:entry", ns):
        t = re.sub(r"\s+", " ", e.findtext("a:title", default="", namespaces=ns) or "").strip()
        s = re.sub(r"\s+", " ", e.findtext("a:summary", default="", namespaces=ns) or "").strip()
        pub = (e.findtext("a:published", default="", namespaces=ns) or "").strip()
        if t and pub[:10]:
            out.append((t, s, pub))
    return out


class Researcher:
    """The engine's researcher seam, with state.

    ``simulate()`` takes a callable ``(ds, symbols, plan) -> dict``;
    this object is that callable, and it owns what a single backtest
    shares across all of its decision days:

    - a **call budget** (``call_cap`` web fetches total, not per day)
      so a long backtest cannot hammer the web;
    - a **cache** of Wikipedia revisions by (title, revision-timestamp)
      so decision days that share a revision reuse one content fetch.

    The result of one call is ``{symbol: text-or-None}`` plus a
    ``_skips`` key (symbol -> plain-English reason) whenever something
    could not be read — an empty ``_skips`` is dropped by the engine.
    """

    def __init__(self, call_cap: int = DEFAULT_CALL_CAP,
                 http_get=None, host: str = WIKI_HOST):
        self.cap = max(1, int(call_cap))
        self.host = host
        self._http_get = http_get or _http_get
        self.calls = 0                      # web fetches made so far
        self._rev_cache: dict[tuple[str, str], tuple[int, str]] = {}
        self._content_cache: dict[tuple[str, str], str] = {}

    # -- one web fetch, budgeted ----------------------------------------
    def _get(self, url: str, params: dict, timeout: float = 30.0):
        if self.calls >= self.cap:
            return None                     # budget spent; caller skips
        self.calls += 1
        return self._http_get(url, params, timeout=timeout)

    # -- Wikipedia: the revision live as of D, then its lead ------------
    def _wiki(self, ds: str, title: str) -> str | None:
        url = f"https://{self.host}/w/api.php"

        rev = self._rev_cache.get((title, ds))
        if rev is None:
            resp = self._get(url, {
                "action": "query", "titles": title, "prop": "revisions",
                "rvprop": "ids|timestamp", "rvlimit": "1",
                "rvstarttimestamp": f"{ds}T23:59:59Z", "rvdir": "older",
                "redirects": 1, "format": "json",
            })
            if resp is None:
                raise _Skip("the research budget is spent")
            page = None
            for p in resp.json().get("query", {}).get("pages", {}).values():
                page = p
                break
            if page is None or page.get("missing") or int(page.get("id", -1)) < 0:
                raise _Skip(f"no Wikipedia page for {title} as of {ds}")
            for r in page.get("revisions", []):
                rev = (int(r["revid"]), r.get("timestamp") or "")
                break
            if rev is None or not rev[1]:
                raise _Skip(f"no Wikipedia page for {title} as of {ds}")
            if rev[1][:10] > ds:
                # The newest revision as of D is after D: the page did
                # not exist on that day. Never fetch it.
                raise _Skip(f"{title} had no Wikipedia page yet on {ds}")
            self._rev_cache[(title, ds)] = rev

        revid, revts = rev
        text = self._content_cache.get((title, revts))
        if text is None:
            resp = self._get(url, {
                "action": "query", "titles": title, "prop": "revisions",
                "revids": str(revid), "rvprop": "content",
                "rvsection": "0", "format": "json",
            })
            if resp is None:
                raise _Skip("the research budget is spent")
            wt = ""
            for p in resp.json().get("query", {}).get("pages", {}).values():
                for r in p.get("revisions", []):
                    wt = r.get("*") or ""
            text = _wikitext_to_plain(wt)[:MAX_TEXT_CHARS]
            self._content_cache[(title, revts)] = text
        return text or None

    # -- arXiv: papers submitted on or before D -------------------------
    def _arxiv(self, ds: str, name: str) -> str | None:
        q = re.sub(r"[^A-Za-z0-9 ]", " ", name).strip()
        if not q:
            return None
        d8 = ds.replace("-", "")
        resp = self._get(ARXIV_URL, {
            "search_query": f'(all:"{q}") AND submittedDate:[000000000000 TO {d8}2359]',
            "max_results": "3", "sortBy": "relevance",
        }, timeout=45.0)
        entries = _parse_atom(resp.text) if resp is not None else []
        if not entries:
            # The ranged query failed or matched nothing: retry undated
            # and let the client-side published check do the gating.
            resp = self._get(ARXIV_URL, {"search_query": f'all:"{q}"',
                                          "max_results": "5",
                                          "sortBy": "relevance"},
                             timeout=45.0)
            entries = _parse_atom(resp.text) if resp is not None else []
        texts = []
        for t, s, pub in entries:
            if pub[:10] > ds:      # the no-lookahead guarantee
                continue
            texts.append(f"Paper: {t}\n{s[:500]}")
        return "\n\n".join(texts)[:MAX_TEXT_CHARS] or None

    # -- the seam ---------------------------------------------------------
    def __call__(self, ds: str, symbols, plan: dict | None = None) -> dict:
        names = (plan or {}).get("names") or {}
        out: dict = {}
        skips: dict[str, str] = {}
        for s in symbols:
            name = names.get(s) or s
            wiki = None
            try:
                wiki = self._wiki(ds, name)
            except _Skip as e:
                skips[s] = e.reason
            except Exception as e:   # http layer failure, whatever it is
                skips[s] = f"the Wikipedia lookup failed ({e})"
            arx = None
            try:
                arx = self._arxiv(ds, name)
            except _Skip as e:
                skips.setdefault(s, e.reason)
            except Exception as e:
                skips.setdefault(s, f"the arXiv lookup failed ({e})")
            text = "\n\n".join(t for t in (wiki, arx) if t)
            out[s] = text or None
            if not text and s not in skips:
                skips[s] = f"nothing readable about {s} as of {ds}"
        if skips:
            out["_skips"] = skips
        return out


def research_as_of(ds: str, symbols, plan: dict | None = None,
                   call_cap: int = DEFAULT_CALL_CAP, http_get=None) -> dict:
    """One decision day of research with a fresh researcher.

    A running backtest makes one ``Researcher`` instead, so the budget
    and the cache persist across its decision days.
    """
    return Researcher(call_cap=call_cap, http_get=http_get).__call__(
        ds, symbols, plan)
