"""Research: the goal-driven section (the old study centre's address).

The reference corpus it used to serve is gone from the section; what
remains is the pipeline — the small markdown renderer, the report
store in the vault's research section, the background run job (fake
gather, fake model, every terminal state), and the routes.
"""
import json
import time

import pytest

from app import llm, research, risk, vault, web
from app.main import app

from fastapi.testclient import TestClient


def _client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    for var in ("LONGVIEW_LLM_KEY", "PROOF_LLM_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def c():
    return _client()


def _poll_run(job_id, deadline=15):
    end = time.time() + deadline
    while time.time() < end:
        job = research.get_run_job(job_id)
        if job is not None and job["status"] != "running":
            return job
        time.sleep(0.05)
    return research.get_run_job(job_id)


def _fake_gather(text=("word " * 900).strip(),
                 sources=None):
    sources = sources if sources is not None else [
        {"title": "Merton model",
         "url": "https://en.wikipedia.org/wiki/Merton_model",
         "label": "Wikipedia"},
        {"title": "A paper",
         "url": "https://arxiv.org/abs/2", "label": "arXiv"}]

    def gather(query, report, http_get=None):
        report("reading…")
        return text, [dict(s) for s in sources]
    return gather


def _answer(title="Credit risk, structurally",
            field="Credit",
            summary="Default as a boundary option.",
            ties=None,
            body=None):
    return json.dumps({
        "title": title, "field": field, "summary": summary,
        "body": body if body is not None else
            "## The idea\n\n" + ("word " * 400).strip(),
        "ties": ties if ties is not None else []})


# ---------------------------------------------------------------------------
# The renderer (carried over from the old study module)
# ---------------------------------------------------------------------------

def test_renderer_escapes_html():
    assert "&lt;script&gt;" in research.render_markdown("<script>")
    assert "<script>" not in research.render_markdown("<script>")


def test_renderer_sections_and_lists():
    h = research.render_markdown(
        "# Top\n\n## One\n\ntext\n\n- a\n- b\n\n1. x\n2. y")
    assert "<h2>Top</h2>" in h
    assert "<h2>One</h2>" in h
    assert "<li>a</li>" in h and "<li>b</li>" in h
    assert "<li>x</li>" in h and "<li>y</li>" in h


def test_renderer_quote_rule_and_inline():
    h = research.render_markdown(
        "> quoted\n\n**bold** and *italic* and `code`")
    assert "<blockquote>quoted</blockquote>" in h
    assert "<strong>bold</strong>" in h
    assert "<em>italic</em>" in h
    assert "<code>code</code>" in h


def test_unknown_markup_is_harmless_text():
    assert research.render_markdown("[link](x)") == "<p>[link](x)</p>"


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def test_listing_shape_no_bodies():
    research._save_reports([
        {"id": "r-1", "kind": "ai", "title": "A", "field": "F",
         "summary": "s", "goal": "g", "body": "b" * 200},
        {"id": "r-2", "kind": "ai", "title": "B", "field": "F",
         "summary": "s", "goal": "g", "body": "c" * 200,
         "sources": [{"title": "T", "url": "https://x.y"}]}])
    entries = research.listing()
    assert [e["id"] for e in entries] == ["r-1", "r-2"]
    for e in entries:
        assert "body" not in e
        assert e["words"] > 0 and e["minutes"] >= 1
    assert entries[1]["sources"] == 1


def test_get_report_renders_and_unknown_is_none():
    research._save_reports([
        {"id": "r-1", "kind": "ai", "title": "A", "field": "F",
         "summary": "s", "goal": "g",
         "body": "## Head\n\npara", "ties": ["one tie"]}])
    rep = research.get_report("r-1")
    assert rep is not None
    assert rep["html"] == "<h2>Head</h2>\n<p>para</p>"
    assert rep["ties"] == ["one tie"]
    assert research.get_report("r-ghost") is None


def test_get_report_keeps_http_sources_only_and_caps():
    sources = [{"title": f"t{i}", "url": u}
               for i, u in enumerate(
                   ["https://ok", "ftp://nope"] +
                   ["https://x%d" % i for i in range(14)])]
    research._save_reports([
        {"id": "r-1", "kind": "ai", "title": "A", "field": "F",
         "summary": "s", "goal": "g", "body": "b" * 200,
         "sources": sources}])
    rep = research.get_report("r-1")
    assert len(rep["sources"]) == 12      # capped at 12, ftp dropped
    assert all(s["url"].startswith("http") for s in rep["sources"])


def test_delete_and_unknown_is_an_error():
    research._save_reports([
        {"id": "r-1", "kind": "ai", "title": "A", "field": "F",
         "summary": "s", "goal": "g", "body": "b" * 200}])
    research.delete_report("r-1")
    assert research.listing() == []
    with pytest.raises(RuntimeError):
        research.delete_report("r-1")


def test_store_keeps_only_the_latest_reports():
    reports = [
        {"id": "r-%02d" % i, "kind": "ai", "title": "T%d" % i,
         "field": "F", "summary": "s", "goal": "g", "body": "b" * 200}
        for i in range(research._REPORTS_KEEP + 5)]
    research._save_reports(reports)
    got = vault.read_section("research")["reports"]
    assert len(got) == research._REPORTS_KEEP
    assert got[-1]["id"] == "r-29"


# ---------------------------------------------------------------------------
# The data digest: what the run's prompt says about the reader's file
# ---------------------------------------------------------------------------

def test_data_digest_empty_file_says_so():
    d = research.data_digest()
    assert "no data" in d.lower()


def test_data_digest_carries_holdings_and_moves():
    vault.write_section("portfolio",
                        {"v": 1, "updated": 0,
                         "positions": [{"ticker": "AAPL",
                                        "name": "Apple",
                                        "shares": 10,
                                        "cost_basis": 100.0,
                                        "note": "core"}]})
    vault.write_section("risk",
                        {"v": 1, "updated": 0,
                         "moves": {"AAPL": 12.5}})
    d = research.data_digest()
    assert "AAPL" in d and "Apple" in d
    assert "12.5%" in d
    st = research.data_status()
    assert st["portfolio"] == 1 and st["moves"] == 1
    assert st["pages"] == 0


# ---------------------------------------------------------------------------
# The run job
# ---------------------------------------------------------------------------

def test_start_run_rejects_goals_that_are_not_goals():
    with pytest.raises(RuntimeError):
        research.start_run("ab")
    with pytest.raises(RuntimeError):
        research.start_run("x" * (research.GOAL_MAX + 1))
    assert research.get_run_job("r-deadbeef") is None


def test_run_done_path_saves_the_report(monkeypatch):
    monkeypatch.setattr(web, "gather", _fake_gather())
    monkeypatch.setattr(
        risk, "_post_llm",
        lambda system, user, max_tokens=4000, timeout=60.0, config=None:
            (_answer(), "fake-model"))
    monkeypatch.setenv("PROOF_LLM_KEY", "k")

    job = research.start_run("merton model of credit risk")
    assert job["status"] == "running"
    final = _poll_run(job["id"])
    assert final["status"] == "done", final["message"]
    assert final["report"]["title"] == "Credit risk, structurally"
    assert [s["title"] for s in final["sources"]] == [
        "Merton model", "A paper"]

    saved = vault.read_section("research")["reports"]
    me = next(n for n in saved if n["id"] == final["report"]["id"])
    assert len(me["sources"]) == 2
    # Empty file: the ties say so in plain English.
    assert me["ties"] == [
        "You have no data saved yet — this report stands on its own."]
    assert any(e["id"] == me["id"] for e in research.listing())


def test_run_prompt_carries_the_data_digest(monkeypatch):
    vault.write_section("portfolio",
                        {"v": 1, "updated": 0,
                         "positions": [{"ticker": "AAPL",
                                        "name": "Apple",
                                        "shares": 10,
                                        "cost_basis": 100.0,
                                        "note": ""}]})
    seen = {}

    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        seen["user"] = user
        return (_answer(ties=["Your Apple holding: …"]), "fake-model")
    monkeypatch.setattr(web, "gather", _fake_gather())
    monkeypatch.setattr(risk, "_post_llm", fake)
    monkeypatch.setenv("PROOF_LLM_KEY", "k")

    final = _poll_run(research.start_run("how do option contracts work")["id"])
    assert final["status"] == "done"
    assert "AAPL" in seen["user"]


def test_run_gathered_without_key(monkeypatch):
    monkeypatch.setattr(web, "gather", _fake_gather())
    final = _poll_run(research.start_run("merton model of credit risk")["id"])
    assert final["status"] == "gathered"
    assert final["report"] is None
    assert final["sources"][0]["title"] == "Merton model"
    assert "Settings" in final["message"]


def test_run_failed_when_gather_too_thin(monkeypatch):
    monkeypatch.setattr(web, "gather",
                        lambda q, r, http_get=None: ("tiny", []))
    final = _poll_run(research.start_run("merton model of credit risk")["id"])
    assert final["status"] == "failed"
    assert "too thin" in final["message"]


def test_run_failed_when_web_goes_down(monkeypatch):
    def boom(query, report, http_get=None):
        raise RuntimeError("dns down")
    monkeypatch.setattr(web, "gather", boom)
    final = _poll_run(research.start_run("merton model of credit risk")["id"])
    assert final["status"] == "failed"
    assert "try again" in final["message"]


def test_run_failed_on_bad_model_answer(monkeypatch):
    from app import risk as r
    monkeypatch.setattr(web, "gather", _fake_gather())
    monkeypatch.setattr(
        r, "_post_llm",
        lambda system, user, max_tokens=4000, timeout=60.0, config=None:
            ("sorry, prose", "fake"))
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    final = _poll_run(research.start_run("merton model of credit risk")["id"])
    assert final["status"] == "failed"
    assert "model" in final["message"]
    assert final["sources"]          # the pages it found are still reported


def test_run_survives_raw_model_exception(monkeypatch):
    import httpx
    from app import risk as r

    def raw_boom(system, user, max_tokens=4000, timeout=60.0):
        raise httpx.ReadTimeout("timed out")
    monkeypatch.setattr(web, "gather", _fake_gather())
    monkeypatch.setattr(r, "_post_llm", raw_boom)
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    final = _poll_run(research.start_run("merton model of credit risk")["id"])
    assert final["status"] == "failed"
    assert final["report"] is None
    assert final["sources"]


def test_run_write_uses_the_long_window(monkeypatch):
    seen = {}

    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        seen["timeout"] = timeout
        seen["max_tokens"] = max_tokens
        return (_answer(), "fake-model")
    monkeypatch.setattr(web, "gather", _fake_gather())
    monkeypatch.setattr(risk, "_post_llm", fake)
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    final = _poll_run(research.start_run("merton model of credit risk")["id"])
    assert final["status"] == "done"
    assert seen["timeout"] == research.AI_LLM_TIMEOUT_RUN
    assert seen["max_tokens"] == research.AI_LLM_MAX_TOKENS_RUN


def test_run_progress_is_bounded(monkeypatch):
    def gather(query, report, http_get=None):
        for i in range(20):
            report(f"step {i}")
        return "tiny", []
    monkeypatch.setattr(web, "gather", gather)
    final = _poll_run(research.start_run("merton model of credit risk")["id"])
    assert len(final["progress"]) <= 8
    assert final["progress"][-1] == "step 19"


def test_prune_jobs_ages_out_and_caps(monkeypatch):
    now = time.time()

    def job(jid, **kw):
        return {"id": jid, "status": "done", "message": "",
                "progress": [], "sources": [], "report": None,
                "created": now, "done": now, **kw}
    research._JOBS.clear()
    research._JOBS["r-old"] = job("r-old", done=now - 700)
    research._JOBS["r-fresh"] = job("r-fresh", done=now - 10)
    research._JOBS["r-run"] = job("r-run", status="running", done=None)
    research._prune_jobs()
    assert "r-old" not in research._JOBS
    assert "r-fresh" in research._JOBS
    assert "r-run" in research._JOBS      # running jobs never age out

    monkeypatch.setattr(research, "_MAX_JOBS", 2)
    research._JOBS["r-extra"] = job("r-extra", done=now - 50)
    research._JOBS["r-extra2"] = job("r-extra2", done=now - 40)
    research._prune_jobs()
    assert len(research._JOBS) <= 2
    assert "r-run" in research._JOBS      # eviction never touches the running
    research._JOBS.clear()


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

def test_list_route_is_blank_by_default(c):
    r = c.get("/api/research")
    assert r.status_code == 200
    body = r.json()
    assert body["reports"] == []
    assert body["meta"]["count"] == 0
    assert body["meta"]["llm"] is False
    assert body["meta"]["data"] == {"portfolio": 0, "pages": 0,
                                    "moves": 0}


def test_detail_and_delete_routes_unknown_are_404(c):
    assert c.get("/api/research/ghost").status_code == 404
    assert c.delete("/api/research/ghost").status_code == 404


def test_run_route_rejects_a_short_goal(c):
    r = c.post("/api/research/run", json={"goal": "ab"})
    assert r.status_code == 400
    assert "goal" in r.json()["detail"]


def test_run_routes_start_and_status(c, monkeypatch):
    monkeypatch.setattr(web, "gather", _fake_gather())
    r = c.post("/api/research/run",
               json={"goal": "merton model of credit risk"})
    assert r.status_code == 200
    job_id = r.json()["id"]
    assert job_id.startswith("r")

    end = time.time() + 15
    job = None
    while time.time() < end:
        job = c.get(f"/api/research/run/{job_id}").json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    # No key (autouse fixture) → the terminal state is 'gathered'.
    assert job["status"] == "gathered"
    assert job["sources"][0]["title"] == "Merton model"
    assert c.get("/api/research/run/nope").status_code == 404


def test_run_route_reports_validation_errors_plainly(c):
    r = c.post("/api/research/run", json={"goal": "x" * 5000})
    assert r.status_code == 422        # pydantic's max_length gate
