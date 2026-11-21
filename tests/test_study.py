"""Study: the AI learning notes centre.

The reference corpus is the main subject: ten hand-written notes that
must be real, long-form, and structurally sound (the "at least an hour
per note" floor, enforced). Then the pipeline: rendering (the small
markdown subset, escaped), the list/detail/delete surface, the AI route
(503 with no key, 200 + saved + listed + rendered + deletable with a
patched model, plain-English failures otherwise), and the web-search job
model — the relevance gate, the capped gather, the background job with
its terminal states, and its two routes.
"""
import re
import time

import pytest

from app import study
from app.main import app

from fastapi.testclient import TestClient


def _client():
    return TestClient(app)


@pytest.fixture
def tmp_study(monkeypatch):
    """Point the reader-notes file at a scratch path."""
    monkeypatch.setattr(study, "DATA_PATH", None)  # set per-test below


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("PROOF_LLM_KEY", raising=False)


@pytest.fixture
def c(tmp_study, monkeypatch, tmp_path):
    monkeypatch.setattr(study, "DATA_PATH", tmp_path / "study.json")
    return _client()


# ---------------------------------------------------------------------------
# The reference corpus
# ---------------------------------------------------------------------------

EXPECTED_NOTES = {
    "markets", "equities", "bonds", "money_inflation", "wealth",
    "real_estate", "banking", "pensions", "investing", "behavior",
}


def test_all_ten_authored_notes_exist():
    ids = {n["id"] for n in study.authored_notes()}
    missing = EXPECTED_NOTES - ids
    assert not missing, f"missing authored notes: {sorted(missing)}"


@pytest.mark.parametrize("nid", sorted(EXPECTED_NOTES))
def test_note_is_substantial(nid):
    """The floor for each of the ten: graduate-level prose (4,500+
    words), properly structured (8+ sections), and named."""
    note = study.get_note(nid)
    assert note is not None, f"no note with id {nid}"
    words = study._words(note["body"])
    assert words >= 4500, f"{nid} is only {words} words — the floor is 4,500"
    assert note["body"].count("## ") >= 8, f"{nid} has fewer than eight sections"
    assert note["title"], f"{nid} has no title"
    assert note["field"], f"{nid} has no field"
    assert note["summary"], f"{nid} has no summary"


@pytest.mark.parametrize("nid", sorted(EXPECTED_NOTES))
def test_notes_carry_no_prices(nid):
    """The round-2 promise: no prices in the reference set. A "$123"
    makes a note date- and market-specific; the corpus speaks in
    relative terms — percentages, ratios, order-of-magnitude."""
    note = study.get_note(nid)
    assert note is not None
    text = "\n".join(filter(None, (note["title"], note["field"],
                                   note["summary"], note["body"])))
    m = re.search(r"\$\s?\d", text)
    assert m is None, f"{nid} names a price near: …{text[max(0, m.start() - 40):m.end() + 40]}…"


def test_note_fields_are_plausible():
    for note in study.authored_notes():
        assert 3 <= len(note["title"]) <= 90, f"{note['id']}: title length"
        assert 2 <= len(note["field"]) <= 40, f"{note['id']}: field length"
        assert 10 <= len(note["summary"]) <= 200, f"{note['id']}: summary length"
        assert note["kind"] == "authored"


def test_note_ids_unique_across_both_corpora():
    ids = [n["id"] for n in study.all_notes()]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# The renderer
# ---------------------------------------------------------------------------

def test_renderer_escapes_html():
    out = study.render_markdown("## T\n\n<script>alert(1)</script> x")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_renderer_sections_and_lists():
    out = study.render_markdown("## One\n\npara text\n\n- a\n- b\n\n1. one\n2. two")
    assert "<h2>One</h2>" in out
    assert "<p>para text</p>" in out
    assert "<ul><li>a</li><li>b</li></ul>" in out
    assert "<ol><li>one</li><li>two</li></ol>" in out


def test_renderer_quote_rule_and_inline():
    out = study.render_markdown("> a quote lands\n\n--\n\n**bold** and *it* and `code`")
    assert "<blockquote>a quote lands</blockquote>" in out
    assert "<hr>" in out
    assert "<strong>bold</strong>" in out
    assert "<em>it</em>" in out
    assert "<code>code</code>" in out


def test_unknown_markup_is_harmless_text():
    out = study.render_markdown("a [link](http://x) and ~~strike~~ end")
    assert "<a" not in out
    assert "[link](http://x)" in out


# ---------------------------------------------------------------------------
# Listing, detail, minutes
# ---------------------------------------------------------------------------

def test_listing_shape_no_bodies():
    for e in study.listing():
        assert set(e) >= {"id", "kind", "title", "field", "summary", "words", "minutes"}
        assert "body" not in e and "html" not in e
        assert e["minutes"] >= 1


def test_get_note_renders_and_unknown_is_none():
    note = study.get_note("markets")
    assert note and note["html"] and "<h2>" in note["html"]
    assert study.get_note("no-such-note") is None


def test_get_note_hands_sources_to_the_detail_view(c):
    # note_entry carries sources as a count for the list card, but the
    # detail view renders the "AI-written from N web sources" badge and
    # the source links — so the detail fetch must return the list.
    # (Round 2 found the opposite live: the badge said "from your
    # document" and the links were gone, because the count overwrote
    # the list in get_note.)
    note = {
        "id": "ai-20261117000000", "kind": "ai",
        "title": "Risk transfer in instruments", "field": "Bonds",
        "summary": "How instruments move risk.",
        "body": "## One\n\n" + "Some words. " * 40,
        "model": "fake", "created": "2026-11-17",
        "sources": [
            {"title": "Finance",
             "url": "https://en.wikipedia.org/wiki/Finance"},
            {"title": "Sukuk",
             "url": "https://en.wikipedia.org/wiki/Sukuk"},
        ],
    }
    study._save_user([note])
    got = study.get_note("ai-20261117000000")
    assert isinstance(got["sources"], list) and len(got["sources"]) == 2
    assert got["sources"][0]["url"].startswith("http")
    # The list view keeps its count contract.
    entry = next(e for e in study.listing() if e["id"] == note["id"])
    assert entry["sources"] == 2
    # A pasted-document note (no sources) renders the document badge.
    doc = dict(note, id="ai-20261117000001", sources=[])
    study._save_user([note, doc])
    assert study.get_note("ai-20261117000001")["sources"] == []


def test_minutes_math():
    body = "word " * 501  # 501 words → 2.5 minutes, rounds up
    e = study.note_entry({"id": "x", "kind": "ai", "title": "T",
                          "field": "F", "summary": "s", "body": body})
    assert e["minutes"] == 3
    # and tiny notes still read as "a minute"
    assert study.note_entry({"id": "y", "kind": "ai", "title": "T",
                             "field": "F", "summary": "s", "body": "one two"})["minutes"] == 1


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

def test_list_endpoint(c):
    # No reader notes yet: just the reference set.
    r = c.get("/api/study")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["llm"] is False
    assert body["meta"]["count"] == len(EXPECTED_NOTES)
    assert {n["id"] for n in body["notes"]} == EXPECTED_NOTES


def test_detail_endpoint_and_404(c):
    r = c.get("/api/study/markets")
    assert r.status_code == 200
    assert r.json()["html"]
    assert c.get("/api/study/nope").status_code == 404


def test_ai_without_key_is_503(c, monkeypatch):
    monkeypatch.delenv("PROOF_LLM_KEY", raising=False)
    r = c.post("/api/study/ai", json={"text": "x " * 300, "topic": ""})
    assert r.status_code == 503
    assert "Settings" in r.json()["detail"]


def test_ai_thin_text_is_502_plain_english(c, monkeypatch):
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    r = c.post("/api/study/ai", json={"text": "too short"})
    assert r.status_code == 502
    assert "not much to read" in r.json()["detail"]


def test_ai_oversized_text_is_502(c, monkeypatch):
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    r = c.post("/api/study/ai", json={"text": "x" * (study.MAX_TEXT_CHARS + 1)})
    assert r.status_code == 502
    assert "characters" in r.json()["detail"]


def test_ai_happy_path_saves_and_lists(c, monkeypatch, tmp_path):
    import json
    from app import risk
    answer = json.dumps({"title": "How a pension pot actually works",
                         "field": "Pensions",
                         "summary": "A pot of savings that buys an income later.",
                         "body": "## The pot\n\n" + ("word " * 400).strip()})
    monkeypatch.setattr(risk, "_post_llm",
                        lambda system, user, max_tokens=4000, timeout=60.0, config=None: (answer, "fake-model"))
    monkeypatch.setenv("PROOF_LLM_KEY", "k")

    r = c.post("/api/study/ai", json={"text": "y " * 500, "topic": "Pensions"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "ai"
    assert body["model"] == "fake-model"
    assert body["id"].startswith("ai-")

    # It's in the list, renders, and can be deleted.
    lst = c.get("/api/study").json()
    assert any(n["id"] == body["id"] for n in lst["notes"])
    assert lst["meta"]["count"] == len(EXPECTED_NOTES) + 1
    assert c.get(f"/api/study/{body['id']}").json()["html"]
    # It is on disk, so it would survive a reload.
    saved = json.loads(study.DATA_PATH.read_text())
    assert any(n["id"] == body["id"] for n in saved["notes"])
    # And it can be deleted.
    assert c.delete(f"/api/study/{body['id']}").status_code == 200
    assert not any(n["id"] == body["id"] for n in c.get("/api/study").json()["notes"])
    assert json.loads(study.DATA_PATH.read_text())["notes"] == []


def test_ai_bad_json_is_502(c, monkeypatch):
    from app import risk
    monkeypatch.setattr(risk, "_post_llm",
                        lambda system, user, max_tokens=4000, timeout=60.0, config=None: ("sorry, prose", "fake"))
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    r = c.post("/api/study/ai", json={"text": "z " * 500})
    assert r.status_code == 502
    assert "shape" in r.json()["detail"]


def test_ai_empty_answer_is_502(c, monkeypatch):
    from app import risk
    monkeypatch.setattr(risk, "_post_llm",
                        lambda system, user, max_tokens=4000, timeout=60.0, config=None: ("", "fake"))
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    r = c.post("/api/study/ai", json={"text": "q " * 500})
    assert r.status_code == 502
    assert "ran out of room" in r.json()["detail"]


def test_ai_too_short_body_is_502(c, monkeypatch):
    import json
    from app import risk
    answer = json.dumps({"title": "A Title", "field": "Field", "summary": "s", "body": "tiny"})
    monkeypatch.setattr(risk, "_post_llm",
                        lambda system, user, max_tokens=4000, timeout=60.0, config=None: (answer, "fake"))
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    r = c.post("/api/study/ai", json={"text": "w " * 500})
    assert r.status_code == 502
    assert "wrong size" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Web search — the relevance gate, the gather, the job model
# ---------------------------------------------------------------------------

def _poll_job(job_id, timeout=15.0):
    """Poll a job until it leaves 'running' (the worker is a real thread)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = study.get_search_job(job_id)
        assert job is not None
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    return study.get_search_job(job_id)


def test_query_words_drop_stopwords():
    assert study._query_words("the Merton model of credit risk") == {
        "merton", "credit", "risk"}


def test_relevant_requires_word_boundaries():
    words = study._query_words("efficient market hypothesis")
    # A substring echo ("markets" / "stockmarket" for "market") is not
    # evidence; the longest word must always appear.
    assert not study._relevant(
        {"title": "Stockmarket trading", "snippet": "buy and hold"}, words)
    assert study._relevant(
        {"title": "Efficient market hypothesis", "snippet": ""}, words)
    # Two echoes, but the longest word absent → dropped (the verified
    # failure mode: off-topic pages that mention half the query).
    assert not study._relevant(
        {"title": "Stock market prediction",
         "snippet": "the efficient pricing of shares"}, words)
    # A two-word query survives on one echo — but only the longer word.
    words2 = study._query_words("bond duration")
    assert study._relevant({"title": "Duration (finance)", "snippet": ""}, words2)
    assert not study._relevant({"title": "Bond", "snippet": "a bond"}, words2)
    # A query of pure stopwords has no gate to apply.
    assert study._relevant({"title": "Anything", "snippet": ""}, set())


def test_relevant_longest_word_tie_is_deterministic():
    # "merton" and "credit" tie at six letters. A bare max() over a set
    # would let the winner flip with hash randomisation (the tie between
    # Black–Scholes and CAPM was observed live). The gate must pick the
    # same word every run, so the same page is dropped every run.
    words = study._query_words("merton model of credit risk")
    assert {"merton", "credit", "risk"} <= words
    for _ in range(50):
        # Two echoes, but "credit" absent: dropped, stably.
        assert not study._relevant(
            {"title": "Merton risk", "snippet": "merton risk"}, words)
        # Three echoes including the tied-longest "credit": kept, stably.
        assert study._relevant(
            {"title": "Credit risk", "snippet": "merton credit risk"}, words)


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
    monkeypatch.setattr(study, "_http_get", fake_get)

    hits = study._wiki_search("en.wikipedia.org", "Wikipedia",
                              "merton model of credit risk")
    assert seen == ["merton model of credit risk finance",
                    "merton model of credit risk"]
    # Anchored hit first, the off-topic gate-drop stays dropped, the
    # duplicate Merton model appears once.
    assert [h["title"] for h in hits] == ["Credit risk", "Merton model"]
    assert all(h["label"] == "Wikipedia" for h in hits)


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
        study, "_wiki_search",
        lambda host, label, query:
            [dict(h) for h in wiki_hits] if host == "en.wikipedia.org" else [])
    # 1200 words of page ≈ 6,000 chars: more than the per-source cap.
    monkeypatch.setattr(
        study, "_wiki_text", lambda host, title: ("word " * 1200).strip())
    monkeypatch.setattr(
        study, "_arxiv_search",
        lambda query: [{"title": "A Merton paper",
                        "url": "https://arxiv.org/abs/1",
                        "label": "arXiv", "_text": ("abs " * 300).strip()}])

    reports = []
    text, sources = study._gather("merton model of credit risk",
                                  reports.append)

    assert len(text) <= study._MAX_GATHER_CHARS
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
        study, "_wiki_search",
        lambda host, label, query: [dict(same), dict(same)])
    monkeypatch.setattr(study, "_wiki_text", lambda host, title: "short")
    monkeypatch.setattr(study, "_arxiv_search", lambda query: [])
    text, sources = study._gather("merton model of credit risk",
                                  lambda m: None)
    assert sources == []        # a stub is no source, a twin is one
    assert text == ""


def test_gather_respects_total_budget(monkeypatch):
    hits = [{"title": f"Page {i}",
             "url": f"https://en.wikipedia.org/wiki/Page_{i}",
             "label": "Wikipedia"} for i in range(5)]
    # 7,500 chars of page each: every one caps at the per-source limit,
    # so four fill the 18,000-char budget and the fifth must wait.
    monkeypatch.setattr(study, "_wiki_search",
                        lambda host, label, query: hits)
    monkeypatch.setattr(
        study, "_wiki_text", lambda host, title: ("word " * 1500).strip())
    monkeypatch.setattr(study, "_arxiv_search", lambda query: [])
    text, sources = study._gather("merton model of credit risk",
                                  lambda m: None)
    assert len(text) <= study._MAX_GATHER_CHARS
    assert len(sources) == 4


def test_search_job_done_path(c, monkeypatch):
    import json
    from app import risk
    monkeypatch.setattr(
        study, "_gather",
        lambda query, report:
            ("word " * 900,
             [{"title": "Merton model",
               "url": "https://en.wikipedia.org/wiki/Merton_model",
               "label": "Wikipedia"},
              {"title": "A paper",
               "url": "https://arxiv.org/abs/2", "label": "arXiv"}]))
    answer = json.dumps({"title": "Credit risk, structurally",
                         "field": "Credit",
                         "summary": "Default as a boundary option.",
                         "body": "## The idea\n\n" + ("word " * 400).strip()})
    monkeypatch.setattr(
        risk, "_post_llm",
        lambda system, user, max_tokens=4000, timeout=60.0, config=None:
            (answer, "fake-model"))
    monkeypatch.setenv("PROOF_LLM_KEY", "k")

    job = study.start_search("merton model of credit risk", "Credit risk")
    assert job["status"] == "running"
    final = _poll_job(job["id"])
    assert final["status"] == "done", final["message"]
    assert final["note"]["kind"] == "ai"
    assert final["note"]["title"] == "Credit risk, structurally"
    assert [s["title"] for s in final["sources"]] == [
        "Merton model", "A paper"]
    # The saved note carries the sources (http urls only), and the list
    # view reports them as a count.
    saved = json.loads(study.DATA_PATH.read_text())
    me = next(n for n in saved["notes"] if n["id"] == final["note"]["id"])
    assert me["sources"][0]["url"].startswith("http")
    assert len(me["sources"]) == 2
    assert any(e.get("sources") == 2 for e in study.listing())


def test_search_job_gathered_without_key(c, monkeypatch):
    monkeypatch.setattr(
        study, "_gather",
        lambda query, report:
            ("word " * 900,
             [{"title": "Merton model",
               "url": "https://en.wikipedia.org/wiki/Merton_model",
               "label": "Wikipedia"}]))
    final = _poll_job(study.start_search("merton model of credit risk")["id"])
    assert final["status"] == "gathered"
    assert final["note"] is None
    assert final["sources"][0]["title"] == "Merton model"
    assert "Settings" in final["message"]


def test_search_job_failed_when_thin(c, monkeypatch):
    monkeypatch.setattr(study, "_gather", lambda query, report: ("tiny", []))
    final = _poll_job(study.start_search("merton model of credit risk")["id"])
    assert final["status"] == "failed"
    assert "too thin" in final["message"]


def test_search_job_failed_when_web_goes_down(c, monkeypatch):
    def boom(query, report):
        raise RuntimeError("dns down")
    monkeypatch.setattr(study, "_gather", boom)
    final = _poll_job(study.start_search("merton model of credit risk")["id"])
    assert final["status"] == "failed"
    assert "try again" in final["message"]


def test_search_job_failed_on_bad_model_answer(c, monkeypatch):
    from app import risk
    monkeypatch.setattr(
        study, "_gather",
        lambda query, report:
            ("word " * 900,
             [{"title": "Merton model",
               "url": "https://en.wikipedia.org/wiki/Merton_model",
               "label": "Wikipedia"}]))
    monkeypatch.setattr(
        risk, "_post_llm",
        lambda system, user, max_tokens=4000, timeout=60.0, config=None:
            ("sorry, prose", "fake"))
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    final = _poll_job(study.start_search("merton model of credit risk")["id"])
    assert final["status"] == "failed"
    assert "model" in final["message"]
    assert final["sources"]          # the pages it found are still reported


def test_search_job_survives_raw_model_exception(c, monkeypatch):
    # The worker's docstring promises "never raises": even an exception
    # that is not a RuntimeError (a transport error escaping the shared
    # caller) must land as a failed job, not strand it in "running" with
    # a client polling a dead job forever.
    import httpx
    from app import risk
    monkeypatch.setattr(
        study, "_gather",
        lambda query, report:
            ("word " * 900,
             [{"title": "Merton model",
               "url": "https://en.wikipedia.org/wiki/Merton_model",
               "label": "Wikipedia"}]))
    def raw_boom(system, user, max_tokens=4000, timeout=60.0):
        raise httpx.ReadTimeout("timed out")
    monkeypatch.setattr(risk, "_post_llm", raw_boom)
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    final = _poll_job(study.start_search("merton model of credit risk")["id"])
    assert final["status"] == "failed"
    assert final["note"] is None
    assert final["sources"]          # the pages it found are still reported


def test_search_write_uses_longer_window(c, monkeypatch):
    import json
    from app import risk
    seen = {}
    monkeypatch.setattr(
        study, "_gather",
        lambda query, report:
            ("word " * 900,
             [{"title": "Merton model",
               "url": "https://en.wikipedia.org/wiki/Merton_model",
               "label": "Wikipedia"}]))
    answer = json.dumps({"title": "Credit risk, structurally",
                         "field": "Credit",
                         "summary": "Default as a boundary option.",
                         "body": "## The idea\n\n" + ("word " * 400).strip()})
    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        seen["timeout"] = timeout
        seen["max_tokens"] = max_tokens
        return (answer, "fake-model")
    monkeypatch.setattr(risk, "_post_llm", fake)
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    final = _poll_job(study.start_search("merton model of credit risk")["id"])
    assert final["status"] == "done", final["message"]
    # The search write gets the longer window *and* the bigger budget
    # (the thinking model burns its budget on reasoning; a full graduate
    # note needs room to think and write).
    assert seen["timeout"] == study.AI_LLM_TIMEOUT_SEARCH
    assert seen["max_tokens"] == study.AI_LLM_MAX_TOKENS_SEARCH
    # The paste path keeps the pair it was measured with.
    study._write_note("word " * 900, "Credit")
    assert seen["timeout"] == study.AI_LLM_TIMEOUT
    assert seen["max_tokens"] == study.AI_LLM_MAX_TOKENS


def test_job_progress_is_bounded(c, monkeypatch):
    def gather(query, report):
        for i in range(20):
            report(f"step {i}")
        return "tiny", []
    monkeypatch.setattr(study, "_gather", gather)
    final = _poll_job(study.start_search("merton model of credit risk")["id"])
    assert len(final["progress"]) <= 8
    assert final["progress"][-1] == "step 19"


def test_start_search_rejects_short_query():
    with pytest.raises(RuntimeError):
        study.start_search("ab")


def test_get_search_job_unknown_is_none():
    assert study.get_search_job("s-deadbeef") is None


def test_prune_jobs_ages_out_and_caps(monkeypatch):
    now = time.time()
    def job(jid, **kw):      # test data, not product code
        return {"id": jid, "status": "done", "message": "", "progress": [],
                "sources": [], "note": None, "created": now, "done": now, **kw}
    study._JOBS.clear()
    study._JOBS["s-old"] = job("s-old", done=now - 700)
    study._JOBS["s-fresh"] = job("s-fresh", done=now - 10)
    study._JOBS["s-run"] = job("s-run", status="running", done=None)
    study._prune_jobs()
    assert "s-old" not in study._JOBS
    assert "s-fresh" in study._JOBS
    assert "s-run" in study._JOBS      # running jobs never age out

    monkeypatch.setattr(study, "_MAX_JOBS", 2)
    study._JOBS["s-extra"] = job("s-extra", done=now - 50)
    study._JOBS["s-extra2"] = job("s-extra2", done=now - 40)
    study._prune_jobs()
    assert len(study._JOBS) <= 2
    assert "s-run" in study._JOBS      # eviction never touches the running
    study._JOBS.clear()


def test_search_start_route_rejects_short(c):
    r = c.post("/api/study/search", json={"query": "ab"})
    assert r.status_code == 400
    assert "topic" in r.json()["detail"] or "words" in r.json()["detail"]


def test_search_start_and_status_routes(c, monkeypatch):
    monkeypatch.setattr(
        study, "_gather",
        lambda query, report:
            ("word " * 900,
             [{"title": "Merton model",
               "url": "https://en.wikipedia.org/wiki/Merton_model",
               "label": "Wikipedia"}]))
    r = c.post("/api/study/search",
               json={"query": "merton model of credit risk", "topic": ""})
    assert r.status_code == 200
    job_id = r.json()["id"]
    assert job_id.startswith("s")

    # No LLM key (autouse fixture) → the terminal state is 'gathered'.
    deadline = time.time() + 15
    job = None
    while time.time() < deadline:
        job = c.get(f"/api/study/search/{job_id}").json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "gathered"
    assert job["sources"][0]["title"] == "Merton model"
    assert c.get("/api/study/search/nope").status_code == 404


def test_delete_authored_is_409(c):
    r = c.delete("/api/study/markets")
    assert r.status_code == 409
    assert "reference set" in r.json()["detail"]


def test_delete_unknown_is_409(c):
    r = c.delete("/api/study/ghost")
    assert r.status_code == 409


def test_corrupt_user_file_is_tolerated(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "DATA_PATH", tmp_path / "study.json")
    study.DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    study.DATA_PATH.write_text("{ not json")
    assert study._user_notes() == []
    assert len(study.all_notes()) == len(EXPECTED_NOTES)
