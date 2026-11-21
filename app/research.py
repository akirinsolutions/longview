"""Research — give it a goal, get a report that ties into your data.

The section the old study centre used to be. The ten authored
reference notes it served are gone from the section (their files
remain in ``study_data`` as dormant reference material); it starts
blank and its input is a *goal*: one sentence about what the reader
wants to understand or decide.

A run has two halves. The first gathers: the shared web client in
``app/web.py`` reads the open textbooks and papers on the goal
(Wikipedia, Wikibooks, Wikiversity, arXiv) — the same pool the old
search ran, hosts fixed, the goal travelling as a parameter. The
second writes: the configured model turns the material into one saved
report — a plain-English brief with a "how this ties into your data"
part, its prompt carrying a digest of what the vault holds (holdings,
note pages, risk moves). A reader with an empty file gets a standalone
brief and is told as much.

Reports are the vault's ``research`` section — one file, exportable,
importable, portable between a self-host and the public instance.
The backtest lab's date-gated researcher is a different creature in
``app/lab_research.py``; it shares the web client, not the section.
"""
from __future__ import annotations

import html
import json
import re
import threading
import time
from typing import Optional

from . import llm, vault, web

_SECTION = "research"
_VERSION = 1

_LOCK = threading.RLock()

#: The goal is one or two sentences; shorter is noise, longer is a project.
GOAL_MIN = 10
GOAL_MAX = 2_000

# Sanity bands for the model's answer: reject the degenerate and the
# runaway, accept anything between.
AI_TITLE_MAX = 90
AI_FIELD_MAX = 40
AI_SUMMARY_MAX = 220
AI_BODY_WORDS_MIN = 200
AI_BODY_WORDS_MAX = 6_000
AI_TIES_MAX = 6

# The write step reads up to 18,000 gathered characters on top of the
# data digest. The resident thinking model spends tokens *reasoning*
# before writing a word, and on a real gather it burned an entire
# 32,000-token budget on reasoning and came back empty (measured).
# 48,000 leaves room to think *and* write; the window is that same run
# plus margin. On the timeout the job fails in plain English with the
# pages it found — it never hangs.
AI_LLM_MAX_TOKENS_RUN = 48_000
AI_LLM_TIMEOUT_RUN = 1_500.0

#: How many reports the section keeps. Older ones fall off the end.
_REPORTS_KEEP = 25

_JOB_TTL = 600.0               # finished jobs keep 10 minutes in memory
_MAX_JOBS = 500

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.RLock()

_SYSTEM = """You are a research desk for a personal finance app. The reader has given you a goal — what they want to understand or decide — together with the contents of their own data file, and with material gathered from open reference sources on that goal. Write one research report.

Return ONLY one JSON object, no prose around it:
{"title": "...", "field": "...", "summary": "...", "body": "...", "ties": ["..."]}

Rules:
- title: a short descriptive name, at most 10 words.
- field: one or two words naming the subject, e.g. "Credit risk" or "Rates".
- summary: one plain sentence, at most 30 words. No hype, no "in this report".
- body: 800 to 1,500 words of plain English, organised as 6 to 10 sections.
  Write for a smart reader with no specialist background: define every
  technical term in plain English on first use, then use it precisely.
  Explain how things work step by step, state the assumptions, and give
  each major idea its standard criticisms and limits. Where the gathered
  material gives numbers, keep them and show what they imply. Prefer
  exact, structural explanations over generalities: a report that could
  have been written about anything is a failure.
- body markup, using exactly these and nothing else:
  "## " for section headings (no other heading level),
  plain paragraphs separated by blank lines,
  "- " for bullets, "1. " for ordered steps,
  "> " for a short pull quote from the material,
  "**term**" for a few key terms,
  "`code`" for a formula or symbol, e.g. `dP = -D * dr`.
  No tables, no links, no markdown besides that list.
- ties: two to five short sentences. Each must connect the research to
  something concrete in the reader's file — a holding by name, a saved
  page, a number they have on record — and say what it means for their
  goal. If the file holds no data, ties must be exactly one sentence:
  "You have no data saved yet — this report stands on its own."
- Be faithful: every figure, name, date and claim in the body must come
  from the gathered material. If you add standard background to make a
  point land, mark it plainly, e.g. "as a general rule". Never invent
  figures. If the material is thin or partly off-goal, write the best
  honest report it supports and say plainly what it cannot cover.
- No preamble, no "here is your report", no closing pleasantries."""


# ---------------------------------------------------------------------------
# The small renderer (carried over from the old study module)
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
# The store: the vault's research section
# ---------------------------------------------------------------------------

def _reports() -> list[dict]:
    """The saved reports, newest last; an absent section means none."""
    d = vault.read_section(_SECTION)
    if d is None:
        return []
    reports = d.get("reports")
    if not isinstance(reports, list):
        return []
    keep = []
    for n in reports:
        if isinstance(n, dict) and isinstance(n.get("body"), str) and n.get("title"):
            keep.append(n)
    return keep


def _save_reports(reports: list[dict]) -> None:
    """Atomic write of the section through the vault (it caps the tail)."""
    with _LOCK:
        vault.write_section(_SECTION, {
            "v": _VERSION,
            "updated": int(time.time()),
            "reports": reports[-_REPORTS_KEEP:],
        })


def report_entry(n: dict) -> dict:
    """The list-view shape: everything except the body."""
    body = n.get("body") or n.get("summary") or ""
    w = _words(body)
    e = {
        "id": n["id"],
        "kind": n.get("kind", "ai"),
        "title": n.get("title") or n["id"],
        "field": n.get("field") or "General",
        "summary": n.get("summary") or "",
        "goal": n.get("goal") or "",
        "words": w,
        "minutes": max(1, round(w / 200)),
    }
    if e["kind"] == "ai":
        e["model"] = n.get("model") or ""
        e["created"] = n.get("created") or ""
        e["sources"] = len(n.get("sources") or [])
    return e


def get_report(rid: str) -> Optional[dict]:
    for n in _reports():
        if n["id"] == rid:
            e = {
                **report_entry(n),
                "body": n.get("body", ""),
                "html": render_markdown(n.get("body", "")),
                "ties": list(n.get("ties") or []),
            }
            if n.get("kind") == "ai":
                # The client renders these as links, and a report can
                # arrive by import: only http/https crosses the gate.
                srcs = [s for s in (n.get("sources") or [])
                        if isinstance(s, dict)
                        and (s.get("url") or "")
                        .startswith(("http://", "https://"))]
                e["sources"] = [
                    {"title": (s.get("title") or "")[:160],
                     "url": (s.get("url") or "")[:300]}
                    for s in srcs[:12]
                ]
            return e
    return None


def listing() -> list[dict]:
    return [report_entry(n) for n in _reports()]


def delete_report(rid: str) -> None:
    with _LOCK:
        reports = _reports()
        if not any(n["id"] == rid for n in reports):
            raise RuntimeError("no saved report at that address")
        _save_reports([n for n in reports if n["id"] != rid])


# ---------------------------------------------------------------------------
# The public surface (main.py routes onto these)
# ---------------------------------------------------------------------------

def data_digest() -> str:
    """What the reader's file holds, in the shape the model is told
    about. The digest is deliberately small: a goal plus this plus the
    gathered material must fit the model's window with room to think."""
    from . import notes, portfolio, risk

    bits: list[str] = []
    try:
        ps = portfolio.load_portfolio()
    except Exception:
        ps = []
    if ps:
        lines = []
        for p in ps[:15]:
            line = f"- {p.get('ticker') or '?'}"
            if p.get("name"):
                line += f" ({p['name']})"
            if p.get("shares"):
                line += f", {p['shares']:g} shares"
            if p.get("cost_basis"):
                line += f", cost basis {p['cost_basis']:g}"
            if p.get("note"):
                line += f" — note: {str(p['note'])[:120]}"
            lines.append(line)
        bits.append(f"Portfolio — {len(ps)} holding"
                    + ("s:" if len(ps) != 1 else ":") + "\n" + "\n".join(lines))

    try:
        pages = notes.load_pages()
    except Exception:
        pages = []
    if pages:
        lines = []
        for pg in pages[:10]:
            head = re.sub(r"\s+", " ", pg.get("body") or "")[:150]
            lines.append(f"- “{pg.get('title') or 'Untitled page'}”: {head}")
            for s in (pg.get("snippets") or [])[:3]:
                first = " ".join(s.get("lines") or [])[:120]
                lines.append(f"    saved from {s.get('source') or 'somewhere'}: "
                             f"“{s.get('title') or ''}” — {first}")
        bits.append(f"Note pages — {len(pages)} page"
                    + ("s:" if len(pages) != 1 else ":") + "\n" + "\n".join(lines))

    try:
        moves = risk.load_moves()
    except Exception:
        moves = {}
    if moves:
        top = sorted(moves.items(), key=lambda kv: abs(kv[1]), reverse=True)[:10]
        bits.append("Risk moves — the expected moves the reader has on record:\n"
                    + "\n".join(f"- {k}: {v:+.1f}%" for k, v in top))

    if not bits:
        return ("The reader's file holds no data yet — no holdings, no pages, "
                "no moves. Write a standalone report, and say so in `ties`.")
    return "The reader's file holds:\n\n" + "\n\n".join(bits)


def data_status() -> dict:
    """The same contents, as counts — the section's “what I can tie
    into” line is built from this."""
    from . import notes, portfolio, risk

    def safe(fn, *a):
        try:
            return fn(*a)
        except Exception:
            return [] if fn.__name__ != "load_moves" else {}

    return {
        "portfolio": len(safe(portfolio.load_portfolio)),
        "pages": len(safe(notes.load_pages)),
        "moves": len(safe(risk.load_moves)),
    }


def meta() -> dict:
    reports = _reports()
    return {
        "llm": llm.is_configured(),
        "count": len(reports),
        "data": data_status(),
    }


# ---------------------------------------------------------------------------
# The write step
# ---------------------------------------------------------------------------

def _write_report(goal: str, text: str, sources: list[dict],
                  max_tokens: int = AI_LLM_MAX_TOKENS_RUN,
                  timeout: float = AI_LLM_TIMEOUT_RUN,
                  config: dict | None = None) -> dict:
    """One model call, strict validation, one saved report. Raises
    RuntimeError in plain English on any failure. ``config`` is the
    request's model settings; the run job's thread cannot see the
    request, so its route passes them in."""
    from . import risk  # the shared llm seam

    user = (f"The goal: {goal.strip()}\n\n"
            + data_digest() + "\n\n"
            + "Gathered material:\n\n" + text)

    content, model = risk._post_llm(_SYSTEM, user,
                                    config=config,
                                    max_tokens=max_tokens,
                                    timeout=timeout)
    if not content or not content.strip():
        raise RuntimeError(
            "the model ran out of room to answer — try a shorter goal")

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
    ties = [re.sub(r"\s+", " ", str(t)).strip()[:400]
            for t in (data.get("ties") or [])
            if isinstance(t, (str, int, float))][:AI_TIES_MAX]

    if not (3 <= len(title) <= AI_TITLE_MAX):
        raise RuntimeError(
            "the model's answer didn't come back in the shape we check for — try again")
    field = re.sub(r"\s+", " ", field)
    if not (2 <= len(field) <= AI_FIELD_MAX):
        field = (goal.strip()[:AI_FIELD_MAX] or "General").title()
    summary = re.sub(r"\s+", " ", summary)[:AI_SUMMARY_MAX]
    # The renderer owns the body; drop anything that belongs to a file header.
    body = "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("# ") and not l.strip().startswith("~ ")).strip()
    w = _words(body)
    if not (AI_BODY_WORDS_MIN <= w <= AI_BODY_WORDS_MAX):
        raise RuntimeError(
            "the model's answer came back the wrong size — try a narrower goal")
    if not ties:
        ties = ["You have no data saved yet — this report stands on its own."]

    report = {
        "id": f"r-{time.strftime('%Y%m%d%H%M%S')}",
        "kind": "ai",
        "title": title,
        "field": field,
        "summary": summary,
        "goal": goal.strip(),
        "body": body,
        "ties": ties,
        "model": model,
        "created": time.strftime("%Y-%m-%d"),
    }
    if sources:
        report["sources"] = [
            {"title": (s.get("title") or "")[:160], "url": (s.get("url") or "")[:300]}
            for s in sources[:12]
            if (s.get("url") or "").startswith(("http://", "https://"))
        ]
    with _LOCK:
        reports = _reports()
        while any(n["id"] == report["id"] for n in reports):
            report["id"] += "b"
        reports.append(report)
        _save_reports(reports)
    return report


# ---------------------------------------------------------------------------
# Run jobs: the background thread behind a goal
# ---------------------------------------------------------------------------

def _finish(job_id: str, status: str, message: str,
            sources: Optional[list[dict]] = None,
            report: Optional[dict] = None) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = status
        job["message"] = message
        if sources:
            job["sources"] = sources
        if report is not None:
            job["report"] = report_entry(report)
        job["done"] = time.time()


def _run_worker(job_id: str, goal: str, config: dict | None = None) -> None:
    """The background thread: gather, then write the report through the
    same tail a run needs. Never raises — the job records it.
    ``config`` is captured at request time: a fresh thread cannot see
    the request's model key, so its route passes the settings in."""
    def report(msg: str) -> None:
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
            if job is not None and job["status"] == "running":
                job["message"] = msg
                progress = job.setdefault("progress", [])
                progress.append(msg)
                # The client shows the last few lines; a gather that
                # reports per source can produce more than fit.
                del progress[:-8]

    report("Reading the open textbooks and papers on that goal…")
    try:
        text, sources = web.gather(goal, report)
    except Exception:
        _finish(job_id, "failed",
                "the search didn't complete — the web wasn't reachable just now; "
                "try again in a moment")
        return
    if len(text) < web._MIN_GATHER_CHARS:
        _finish(job_id, "failed",
                "I could reach the web, but the pages came back too thin to make "
                "a solid report — try a more specific goal",
                sources=sources)
        return
    if not llm.is_configured(config):
        _finish(job_id, "gathered",
                "I found the material, but no model key is set to write the report "
                "with — add one in Settings; the pages it found are listed in the "
                "sources",
                sources=sources)
        return
    plural = "s" if len(sources) != 1 else ""
    report(f"Got {len(sources)} source{plural}. Writing the report — from this "
           f"much material the local model needs ten minutes or more; I'll let "
           f"you know the moment it lands…")
    try:
        rep = _write_report(goal, text, sources, config=config)
        _finish(job_id, "done", "the report is written and saved",
                sources=sources, report=rep)
    except RuntimeError as e:
        _finish(job_id, "failed",
                f"the model didn't finish the report ({e}) — the pages it found "
                f"are in the sources",
                sources=sources)
    except Exception:
        # A worker that dies on an unhandled exception strands the job in
        # "running" forever and the client polls a dead job: the spinner
        # turns and nothing ever lands. The docstring says "never raises"
        # — this is what that means. The gather itself worked, so the
        # pages it found are still worth seeing.
        _finish(job_id, "failed",
                "the model stopped before the report was finished — the search "
                "itself worked, so the pages it found are listed; try the goal "
                "again",
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
        finished = [j for j in _JOBS.values()
                    if j["status"] != "running"]
        order = sorted(finished, key=lambda j: j.get("done") or j.get("created"))
        for j in order[: len(_JOBS) - _MAX_JOBS]:
            _JOBS.pop(j["id"], None)


def _job_view(job: dict) -> dict:
    return {
        "id": job["id"],
        "status": job["status"],
        "message": job.get("message") or "",
        "progress": list(job.get("progress", [])),
        "sources": list(job.get("sources", [])),
        "report": job.get("report"),
    }


def start_run(goal: str, config: dict | None = None) -> dict:
    """Create a run job and start its thread. Raises RuntimeError in
    plain English for a goal too short to be a goal."""
    import secrets

    goal = (goal or "").strip()
    if len(goal) < GOAL_MIN:
        raise RuntimeError(
            "give me a real goal — a sentence or two about what you want "
            "to understand or decide")
    if len(goal) > GOAL_MAX:
        raise RuntimeError(
            f"that goal is {len(goal):,} characters; I accept up to "
            f"{GOAL_MAX:,} — one or two sentences is plenty")
    job = {
        "id": "r" + secrets.token_hex(5),
        "status": "running",
        "message": "starting the research…",
        "progress": ["starting the research…"],
        "sources": [],
        "report": None,
        "created": time.time(),
    }
    with _JOBS_LOCK:
        _prune_jobs()
        _JOBS[job["id"]] = job
    threading.Thread(
        target=_run_worker, args=(job["id"], goal, config),
        daemon=True, name=f"research-{job['id']}").start()
    return _job_view(job)


def get_run_job(job_id: str) -> Optional[dict]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return _job_view(job) if job is not None else None
