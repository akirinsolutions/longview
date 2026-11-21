"""The shared web client: the open-textbook gather behind research.

Everything is faked — no test touches the network. The subjects are
the relevance gate, the capped gather (per-source and total budgets,
dedupe, stub-skip), and the two-pass anchored wiki search.
"""
import pytest

from app import web


# ---------------------------------------------------------------------------
# The relevance gate
# ---------------------------------------------------------------------------

def test_query_words_drop_stopwords():
    assert web._query_words("the Merton model of credit risk") == {
        "merton", "credit", "risk"}


def test_relevant_requires_word_boundaries():
    words = web._query_words("efficient market hypothesis")
    # A substring echo ("markets" / "stockmarket" for "market") is not
    # evidence; the longest word must always appear.
    assert not web._relevant(
        {"title": "Stockmarket trading", "snippet": "buy and hold"}, words)
    assert web._relevant(
        {"title": "Efficient market hypothesis", "snippet": ""}, words)
    # Two echoes, but the longest word absent → dropped (the verified
    # failure mode: off-topic pages that mention half the query).
    assert not web._relevant(
        {"title": "Stock market prediction",
         "snippet": "the efficient pricing of shares"}, words)
    # A two-word query survives on one echo — but only the longer word.
    words2 = web._query_words("bond duration")
    assert web._relevant({"title": "Duration (finance)", "snippet": ""}, words2)
    assert not web._relevant({"title": "Bond", "snippet": "a bond"}, words2)
    # A query of pure stopwords has no gate to apply.
    assert web._relevant({"title": "Anything", "snippet": ""}, set())


def test_relevant_longest_word_tie_is_deterministic():
    # "merton" and "credit" tie at six letters. A bare max() over a set
    # would let the winner flip with hash randomisation (the tie between
    # Black–Scholes and CAPM was observed live). The gate must pick the
    # same word every run, so the same page is dropped every run.
    words = web._query_words("merton model of credit risk")
    assert {"merton", "credit", "risk"} <= words
    for _ in range(50):
        # Two echoes, but "credit" absent: dropped, stably.
        assert not web._relevant(
            {"title": "Merton risk", "snippet": "merton risk"}, words)
        # Three echoes including the tied-longest "credit": kept, stably.
        assert web._relevant(
            {"title": "Credit risk", "snippet": "merton credit risk"}, words)


# ---------------------------------------------------------------------------
# The wiki search: two passes, anchored first
# ---------------------------------------------------------------------------

def test_wiki_search_anchors_the_query(monkeypatch):
    # Two passes: the domain-anchored query, then the reader's own. For a
    # how-phrase, MediaWiki's rank serves person-name and same-word noise
    # first (a live "how do bonds work" gathered a baseball player and a
    # grief-psychology page); the anchored pass is what lifts the on-domain
    # pages, so it comes first. Duplicates collapse on the URL.
    class R:
        def __init__(self, hits):
            self._hits = hits
        def json(self):
            return {"query": {"search": self._hits}}
    canned = {
        "merton model of credit risk": [
            {"title": "Merton model",
             "snippet": "a credit risk model by merton"},
            {"title": "Model risk", "snippet": "merton risk"},
        ],
        "merton model of credit risk finance": [
            {"title": "Credit risk",
             "snippet": "merton credit risk finance"},
            {"title": "Merton model",
             "snippet": "duplicate of the first pass"},
        ],
    }
    seen = []

    def fake_get(url, params, timeout=15.0):
        seen.append(params["srsearch"])
        return R(canned[params["srsearch"]])
    monkeypatch.setattr(web, "_http_get", fake_get)

    hits = web._wiki_search("en.wikipedia.org", "Wikipedia",
                            "merton model of credit risk")
    assert seen == ["merton model of credit risk finance",
                    "merton model of credit risk"]
    # Anchored hit first, the off-topic gate-drop stays dropped, the
    # duplicate Merton model appears once.
    assert [h["title"] for h in hits] == ["Credit risk", "Merton model"]
    assert all(h["label"] == "Wikipedia" for h in hits)


# ---------------------------------------------------------------------------
# The gather: caps, dedupe, stubs, progress
# ---------------------------------------------------------------------------

def test_gather_caps_dedupes_and_reports(monkeypatch):
    wiki_hits = [
        {"title": "Merton model",
         "url": "https://en.wikipedia.org/wiki/Merton_model",
         "label": "Wikipedia"},
        {"title": "Credit risk",
         "url": "https://en.wikipedia.org/wiki/Credit_risk",
         "label": "Wikipedia"},
    ]
    monkeypatch.setattr(
        web, "_wiki_search",
        lambda host, label, query:
            [dict(h) for h in wiki_hits] if host == "en.wikipedia.org" else [])
    # 1200 words of page ≈ 6,000 chars: more than the per-source cap.
    monkeypatch.setattr(
        web, "_wiki_text", lambda host, title: ("word " * 1200).strip())
    monkeypatch.setattr(
        web, "_arxiv_search",
        lambda query: [{"title": "A Merton paper",
                        "url": "https://arxiv.org/abs/1",
                        "label": "arXiv", "_text": ("abs " * 300).strip()}])

    reports = []
    text, sources = web._gather("merton model of credit risk",
                                reports.append)

    assert len(text) <= web._MAX_GATHER_CHARS
    assert [s["title"] for s in sources] == [
        "Merton model", "Credit risk", "A Merton paper"]
    for name in ("Merton model — Wikipedia", "Credit risk — Wikipedia",
                 "A Merton paper — arXiv"):
        assert name in text, name
    assert "word" in text                       # the (capped) page body
    assert "abs" in text                        # the arXiv abstract
    # Progress was reported in plain English, per backend.
    assert any("Wikipedia" in r for r in reports)
    assert any("arXiv" in r for r in reports)


def test_gather_dedupes_urls_and_skips_stubs(monkeypatch):
    same = {"title": "Merton model",
            "url": "https://en.wikipedia.org/wiki/Merton_model",
            "label": "Wikipedia"}
    monkeypatch.setattr(
        web, "_wiki_search",
        lambda host, label, query: [dict(same), dict(same)])
    monkeypatch.setattr(web, "_wiki_text", lambda host, title: "short")
    monkeypatch.setattr(web, "_arxiv_search", lambda query: [])
    text, sources = web._gather("merton model of credit risk",
                                lambda m: None)
    assert sources == []        # a stub is no source, a twin is one
    assert text == ""


def test_gather_respects_total_budget(monkeypatch):
    hits = [{"title": f"Page {i}",
             "url": f"https://en.wikipedia.org/wiki/Page_{i}",
             "label": "Wikipedia"} for i in range(5)]
    # 7,500 chars of page each: every one caps at the per-source limit,
    # so four fill the 18,000-char budget and the fifth must wait.
    monkeypatch.setattr(web, "_wiki_search",
                        lambda host, label, query: hits)
    monkeypatch.setattr(
        web, "_wiki_text", lambda host, title: ("word " * 1500).strip())
    monkeypatch.setattr(web, "_arxiv_search", lambda query: [])
    text, sources = web._gather("merton model of credit risk",
                                lambda m: None)
    assert len(text) <= web._MAX_GATHER_CHARS
    assert len(sources) == 4


def test_gather_public_wrapper_never_swaps_in_production(monkeypatch):
    # The public wrapper takes a fake http_get in tests; in production
    # no fake exists, so the module global must never be swapped.
    seen = []

    def fake_get(url, params, timeout=15.0):
        seen.append(url)

        class R:
            def json(self):
                return {"query": {"search": []}}
        return R()
    monkeypatch.setattr(web, "_http_get", lambda *a, **k: None)
    text, sources = web.gather("merton model of credit risk",
                               lambda m: None, http_get=fake_get)
    assert seen                    # the fake did the reaching
