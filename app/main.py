"""Longview — turn investment claims into evidence.

A FastAPI app with a small static front end:

- Backtest Lab: describe a strategy in plain English, get a working
  backtest against 5/10/20 years of real market data, judged honestly
  against buy-and-hold.
- Smart Money: what the famous funds actually hold (SEC 13F filings),
  what they changed last quarter, and where they're crowded together.
- Your portfolio: the saved holdings with live prices, FX, and the
  funds' 13F cross-check (the Home page).
- Risk: what the portfolio becomes if each holding moves — the moves
  typed by hand or suggested by the language model.
- Economy viewer: where the world's wealth is held — a static, global,
  seven-levels-deep tree, with a share, a dollar amount and a growth
  rate at every node.

Run:  .venv/bin/uvicorn app.main:app --port 8010
      (port 8000 is taken on this machine by the local model server)
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

import httpx

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from . import (accounts, backup, backtest, directory, economy, funds,
               lab_research, llm, market_data, netfix, notes, portfolio,
               research, risk, savefile, strategy_lab, translator, vault)

# Some networks hand the host no DNS servers at all (this one, right now):
# install the DoH fallback so the web-facing paths (study search, Yahoo,
# SEC) can resolve names. Inert on machines with a normal resolver.
netfix.install()

app = FastAPI(
    title="Longview",
    version="0.1.0",
    description="Turn investment claims into evidence: a plain-English "
                "backtester and a look at what the big funds are doing.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# The whole wealth tree is one payload (~1.2 MB of JSON, ~90 KB gzipped)
# fetched once and drilled locally, so compress it on the way out.
app.add_middleware(GZipMiddleware, minimum_size=1024)


class NoCacheUI(BaseHTTPMiddleware):
    """Always revalidate the UI files in the browser.

    This is a local tool: a one-millisecond 304 check on refresh beats
    the browser quietly serving a yesterday-version of the interface.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response


app.add_middleware(NoCacheUI)


class LLMOverrideMiddleware:
    """Hold the browser's per-request model key where the ``llm`` seam
    can see it.

    The front end sends its saved Settings as an ``X-Longview-LLM``
    header (base64 JSON) on every request. This is a plain ASGI
    middleware — not the base class — so the context variable set here
    survives into the route handlers, which run in the same task. A
    missing or malformed header simply leaves the server's own
    environment in charge.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            raw = headers.get(b"x-longview-llm")
            if raw is not None:
                llm.set_request_override(llm.parse_header(raw.decode("latin-1")))
        await self.app(scope, receive, send)


app.add_middleware(LLMOverrideMiddleware)


class AuthMiddleware:
    """Hold the signed-in user in the context where the vault resolves.

    The session cookie rides along on every request as ``longview_session``
    (httponly, samesite=lax — no CSRF surface of its own beyond the app's
    own actions). This is a plain ASGI middleware, the same pattern as the
    model-key override, so the context variable survives into the route
    handlers, which run in the same task. A missing or bad cookie simply
    means anonymous use, exactly like a first visit.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            raw = headers.get(b"cookie")
            username = None
            if raw:
                for part in raw.decode("latin-1").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == accounts.COOKIE_NAME:
                        username = accounts.read_token(v)
                        break
            accounts.set_user(username)
        await self.app(scope, receive, send)


app.add_middleware(AuthMiddleware)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

BUILTIN_STRATEGIES = [
    {"key": "bh_spy", "name": "Buy and hold (SPY)", "symbol": "SPY", "rule": "buy_and_hold",
     "params": {}, "desc": "The benchmark: buy an S&P 500 index fund and never touch it."},
    {"key": "golden", "name": "The golden cross (SPY)", "symbol": "SPY", "rule": "sma_cross",
     "params": {"fast": 50, "slow": 200},
     "desc": "Invest when the 50-day average is above the 200-day average — the classic trend filter."},
    {"key": "dip8", "name": "Buy the 8% dip (SPY)", "symbol": "SPY", "rule": "buy_the_dip",
     "params": {"drop_pct": 8, "lookback_days": 90, "max_hold_days": 252},
     "desc": "Wait for a drop, buy the fear, sell the recovery."},
    {"key": "mom12", "name": "12-month momentum (SPY)", "symbol": "SPY", "rule": "momentum",
     "params": {"months": 12}, "desc": "Ride winners: invested while a year above last year, cash otherwise."},
    {"key": "dca_spy", "name": "Save $1,000 a month (SPY)", "symbol": "SPY", "rule": "dca",
     "params": {"monthly_amount": 1000},
     "desc": "The steady saver: a fixed amount every month, no timing at all."},
    {"key": "bh_qqq", "name": "Buy and hold (QQQ)", "symbol": "QQQ", "rule": "buy_and_hold",
     "params": {}, "desc": "Same idea, tech-heavy: the Nasdaq-100 index."},
]


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    symbol: str = ""  # the form's instrument; used when the words name none


class BacktestRequest(BaseModel):
    symbol: str = Field("SPY", max_length=8)
    rule: str = Field("buy_and_hold", max_length=32)
    params: dict = {}
    years: float = Field(10, ge=1, le=20)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "app": "Longview", "version": "0.1.0",
            "llm_configured": llm.is_configured(),
            "rules_available": list(translator.KNOWN_RULES)}


class LLMTestRequest(BaseModel):
    base: str = Field("", max_length=500)
    key: str = Field("", max_length=500)
    model: str = Field("", max_length=200)


@app.get("/api/llm")
def llm_status():
    """Which model will answer: the browser's key if this request
    carried one, else the server's environment. The key itself is
    never returned — only that it is set and where it came from."""
    cfg = llm.resolve()
    env_key = (os.environ.get("LONGVIEW_LLM_KEY")
               or os.environ.get("PROOF_LLM_KEY") or "")
    source = ("request" if (llm.request_override() or {}).get("key")
              else "env" if env_key else "none")
    return {"configured": bool(cfg["key"]), "source": source,
            "base": cfg["base"], "model": cfg["model"],
            "base_problem": llm.validate_base(cfg["base"]),
            "defaults": {"base": llm.DEFAULT_BASE,
                         "model": llm.DEFAULT_MODEL}}


@app.post("/api/llm/test")
def llm_test(req: LLMTestRequest):
    """One small completion with exactly the settings the form holds,
    so the user gets an answer before saving: connected and which
    model it really is, or the plain-English reason it is not."""
    config = {k: v for k, v in
              (("base", req.base), ("key", req.key), ("model", req.model))
              if v.strip()}
    if not config.get("key"):
        return {"ok": False, "error": "there is no key to test with"}
    import time as _time
    t0 = _time.monotonic()
    try:
        content, model = llm.post_chat(
            "Reply with exactly one word: ok", "test", config,
            max_tokens=512, timeout=120)
    except RuntimeError as e:
        return {"ok": False, "model": req.model.strip() or None,
                "ms": int((_time.monotonic() - t0) * 1000),
                "error": str(e)}
    return {"ok": bool(content), "model": model,
            "ms": int((_time.monotonic() - t0) * 1000),
            "error": None if content else
            "the model answered but wrote no text — if this is a "
            "thinking model its budget ran out; try again"}


@app.get("/api/strategies")
def strategies():
    return {"strategies": BUILTIN_STRATEGIES}


@app.post("/api/translate")
def translate(req: TranslateRequest):
    try:
        return translator.translate(req.text, req.symbol or None)
    except Exception as e:  # the rule reader shouldn't raise, but be safe
        raise HTTPException(400, f"Couldn't read that strategy: {e}")


def _downsample(result: dict, max_points: int = 600) -> None:
    for key in ("dates", "equity", "benchmark"):
        series = result.get(key) or []
        if len(series) > max_points:
            step = -(-len(series) // max_points)  # ceil division
            result[key] = series[::step]


@app.post("/api/backtest")
def api_backtest(req: BacktestRequest):
    try:
        prices = market_data.fetch_history(req.symbol, req.years)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Could not fetch market data: {e}")
    try:
        result = backtest.run(prices, req.rule, req.params)
    except ValueError as e:
        raise HTTPException(400, str(e))
    result["symbol"] = market_data._normalize_symbol(req.symbol)
    result["verdict"] = backtest.verdict(result)
    _downsample(result)
    return result


class StrategyBacktestRequest(BaseModel):
    """One strategy-lab backtest. "my_plan" builds the plan from the
    structured form and runs the deterministic rules; "ai" hands the
    words to the language model, which then decides every day.

    The fields stay deliberately loose — ``strategy_lab.make_plan`` is
    the single validation gate and speaks plain English."""
    mode: str = "my_plan"
    symbols: list[str] = []
    start_cash: float = 100_000.0
    frequency: str = "month"
    triggers: list[dict] = []
    targets: dict[str, float] = {}
    on_drop: str = "hold"
    add_weight: float = 0.10
    exit_pct: float | None = None
    research: bool = False
    text: str = ""
    names: dict[str, str] = {}
    start: str | None = None
    end: str | None = None
    years: float = Field(10, ge=1, le=20)


def _strategy_run_sync(req: StrategyBacktestRequest) -> dict:
    """The "my plan" path: synchronous, no model, returns the full result."""
    try:
        plan = strategy_lab.make_plan(
            req.symbols, req.start_cash, req.frequency, req.triggers,
            req.targets, req.on_drop, req.add_weight, req.exit_pct,
            req.research, text=req.text, names=req.names)
    except ValueError as e:
        raise HTTPException(400, str(e))
    prices: dict[str, dict[str, float]] = {}
    try:
        for s in plan["symbols"]:
            prices[s] = market_data.fetch_history(s, req.years)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Could not fetch market data: {e}")
    researcher = lab_research.Researcher() if plan.get("research") else None
    try:
        result = strategy_lab.simulate(plan, prices, strategy_lab.decide_plan,
                                       researcher, start=req.start, end=req.end)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"The backtest did not finish: {e}")
    result["mode"] = "my_plan"
    result["plan_source"] = "form"
    _downsample(result)
    return result


_STRATEGY_JOBS: dict[str, dict] = {}
_STRATEGY_JOBS_LOCK = threading.RLock()
_STRATEGY_JOB_TTL = 600.0        # finished jobs keep ten minutes in memory
_STRATEGY_MAX_JOBS = 500


def _strategy_finish(job_id: str, status: str, message: str,
                     result: dict | None = None) -> None:
    with _STRATEGY_JOBS_LOCK:
        job = _STRATEGY_JOBS.get(job_id)
        if job is None:
            return
        job["status"] = status
        job["message"] = message
        if result is not None:
            job["result"] = result
        job["done"] = time.time()


def _prune_strategy_jobs() -> None:
    """Call under the lock: finished jobs age out, then the oldest go."""
    now = time.time()
    for j in [j for j in _STRATEGY_JOBS.values()
              if j["status"] != "running" and now - j.get("done", now)
              > _STRATEGY_JOB_TTL]:
        _STRATEGY_JOBS.pop(j["id"], None)
    if len(_STRATEGY_JOBS) > _STRATEGY_MAX_JOBS:
        finished = [j for j in _STRATEGY_JOBS.values()
                    if j["status"] != "running"]
        order = sorted(finished, key=lambda j: j.get("done") or j["created"])
        for j in order[: len(_STRATEGY_JOBS) - _STRATEGY_MAX_JOBS]:
            _STRATEGY_JOBS.pop(j["id"], None)


def _strategy_job_view(job: dict) -> dict:
    return {
        "id": job["id"],
        "status": job["status"],
        "message": job.get("message") or "",
        "progress": list(job.get("progress", [])),
        "result": job.get("result"),
    }


def _strategy_worker(job_id: str, text: str, symbols: list[str],
                     start_cash: float, years: float,
                     start: str | None, end: str | None,
                     config: dict | None = None) -> None:
    """The "AI runs it" background job. Never raises — the job records it.

    The model reads the words into a plan once (the deterministic reader
    takes over if the model doesn't land), then it is the trader: one
    model call per decision day, and a research call per decision day
    when the plan says to research. ``config`` is the request's model
    settings, captured at submit time — a fresh thread cannot see the
    request, so without this a browser key would die at the door."""
    def report(msg: str) -> None:
        with _STRATEGY_JOBS_LOCK:
            job = _STRATEGY_JOBS.get(job_id)
            if job is not None and job["status"] == "running":
                job["progress"].append(msg)
                job["progress"] = job["progress"][-8:]

    try:
        report("reading your strategy…")
        plan, source = strategy_lab.interpret_strategy(
            text, symbols or None, start_cash, use_llm=True,
            config=config)
        report(f"plan ready (read from the "
               f"{'model' if source == 'model' else 'words'}): "
               f"{', '.join(plan['symbols'])}")
        prices: dict[str, dict[str, float]] = {}
        for s in plan["symbols"]:
            report(f"fetching {s} market data…")
            prices[s] = market_data.fetch_history(s, years)
        researcher = lab_research.Researcher() if plan.get("research") else None
        report("running the backtest — the model decides every day…"
               if researcher else "running the backtest…")
        result = strategy_lab.simulate(plan, prices,
                                       strategy_lab.make_llm_decider(config),
                                       researcher, start=start, end=end)
        result["mode"] = "ai"
        result["plan_source"] = source
        _downsample(result)
        _strategy_finish(job_id, "done", "the backtest is done",
                         result=result)
    except ValueError as e:
        _strategy_finish(job_id, "failed", str(e))
    except Exception:
        _strategy_finish(job_id, "failed",
                         "the backtest didn't finish — the market data "
                         "didn't come through just now; try again in a moment")


def _strategy_job_start(req: StrategyBacktestRequest) -> dict:
    import secrets

    job = {
        "id": "b" + secrets.token_hex(5),
        "status": "running",
        "message": "reading your strategy…",
        "progress": ["reading your strategy…"],
        "result": None,
        "created": time.time(),
    }
    with _STRATEGY_JOBS_LOCK:
        _prune_strategy_jobs()
        _STRATEGY_JOBS[job["id"]] = job
    threading.Thread(
        target=_strategy_worker,
        args=(job["id"], (req.text or "").strip(), [s.strip().upper()
                                                        for s in req.symbols],
              req.start_cash, req.years, req.start, req.end,
              llm.resolve()),
        daemon=True).start()
    return _strategy_job_view(job)


@app.post("/api/backtest/strategy")
def strategy_backtest_start(req: StrategyBacktestRequest):
    """Start a strategy-lab backtest.

    "my_plan" runs synchronously (form → deterministic rules) and returns
    the full result. "AI runs it" returns a job to poll: a missing model
    key is a 503 that names the fallback, unreadable words are a 400, and
    the job itself only fails on the market data or an engine error."""
    if req.mode not in ("my_plan", "ai"):
        raise HTTPException(400, "mode must be \"my_plan\" or \"ai\"")
    if req.mode == "ai":
        if not (req.text or "").strip():
            raise HTTPException(400, "describe the strategy in a few words "
                                      "first — the AI has nothing to read")
        if not llm.is_configured():
            raise HTTPException(503, "The AI mode needs a language model. "
                                     "Set one in Settings — or use "
                                     "\"my plan\" with the form.")
        return _strategy_job_start(req)
    return _strategy_run_sync(req)


@app.get("/api/backtest/strategy/{job_id}")
def strategy_backtest_status(job_id: str):
    """One poll of an "AI runs it" job: status, plain-English progress
    lines, and the full result when it's done."""
    with _STRATEGY_JOBS_LOCK:
        job = _STRATEGY_JOBS.get(job_id)
        view = _strategy_job_view(job) if job else None
    if view is None:
        raise HTTPException(404, "No strategy job at that address — it may "
                                  "have expired.")
    return view


@app.get("/api/funds")
def api_funds(refresh: bool = False):
    try:
        return funds.market_view(refresh=refresh)
    except Exception as e:
        raise HTTPException(502, f"Could not reach the SEC: {e}")


@app.get("/api/funds/{key}")
def api_fund(key: str):
    fund = funds.get_fund(key)
    if fund is None:
        raise HTTPException(404, f"No fund named '{key}'")
    try:
        return funds.fund_detail(fund)
    except Exception as e:
        raise HTTPException(502, f"Could not read {fund['name']}'s filings: {e}")


# ---------------------------------------------------------------------------
# Smart Money: the scan pool endpoints
# ---------------------------------------------------------------------------

def _pool():
    try:
        return funds.scan_pool()
    except Exception as e:
        raise HTTPException(502, f"Could not read the funds' filings: {e}")


def _scan_params(request: Request) -> dict:
    """The twelve scan filters, straight off the query string."""
    return {k: v for k, v in request.query_params.items() if k in funds.SCAN_PARAMS}


@app.get("/api/money/overview")
def money_overview(refresh: bool = False):
    """Fund cards (concentration, ETF share, staleness) + quarter rollups:
    what's new, the biggest moves, and where crowding is rising or falling."""
    try:
        pool = funds.scan_pool(refresh=refresh)
    except Exception as e:
        raise HTTPException(502, f"Could not read the funds' filings: {e}")
    return {
        "as_of": pool["as_of"], "generated": pool["generated"],
        "funds": pool["funds"],
        "new_this_quarter": pool["new_this_quarter"],
        "biggest_moves": pool["biggest_moves"],
        "crowding_change": pool["crowding_change"],
        "exits_this_quarter": pool.get("exits_this_quarter") or [],
        "n_ok": sum(1 for f in pool["funds"] if "error" not in f),
        "n_total": len(pool["funds"]),
        "row_count": len(pool["rows"]),
    }


@app.get("/api/money/scan")
def money_scan(request: Request, refresh: bool = False):
    """The scan table, filtered and sorted. All params optional:

    q (name/CUSIP text), funds / exclude (comma-sep fund keys),
    min_value, min_weight (pct), min_crowding (n funds),
    status (new/increased/decreased/unchanged/exited),
    min_move_value, min_move_pct, asset (stock/etf/preferred/option),
    surprise, aggregate (1 = one row per company, worth = the funds'
    combined holding; each row carries its per-fund breakdown),
    sort, dir, limit
    """
    pool = _pool() if not refresh else funds.scan_pool(refresh=True)
    return funds.scan_query(pool, _scan_params(request))


@app.get("/api/money/export")
def money_export(request: Request):
    """The current scan as a CSV download (everything that matches)."""
    p = _scan_params(request)
    p["limit"] = "500"
    rows = funds.scan_query(_pool(), p)["rows"]
    text = funds.rows_to_csv(rows)
    return Response(content=text, media_type="text/csv",
                    headers={"Content-Disposition":
                             'attachment; filename="proof-smart-money.csv"'})


@app.get("/api/money/security")
def money_security(name: str = ""):
    """One security, every tracked fund at once: who holds it, how much,
    and what each of them did to it last quarter."""
    try:
        return funds.security_view(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"Could not look up '{name}': {e}")


# ---------------------------------------------------------------------------
# Your portfolio: the investor's own holdings, with live prices
#
# The file is the user's data; the prices come from Yahoo Finance's free
# chart API and degrade to dashes when Yahoo is busy, so a blocked quote
# never hides a holding and never 500s. The smart-money column matches
# the company name against the 13F pool.
# ---------------------------------------------------------------------------

@app.get("/api/portfolio")
def portfolio_view(refresh: bool = False, currency: str = ""):
    """Every saved position, enriched with a live quote and a 13F cross-check.

    ``currency`` (USD, GBP, HKD, ...) converts every priced row and the
    totals through Yahoo's FX rates; some rows may stay dashed and the
    total still sums the rest.
    """
    return portfolio.view(refresh=refresh, currency=currency)


@app.post("/api/portfolio")
def portfolio_add(body: dict):
    try:
        return portfolio.add_position(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/portfolio/{ticker}")
def portfolio_update(ticker: str, body: dict):
    try:
        return portfolio.update_position(ticker, body)
    except KeyError:
        raise HTTPException(404, f"Nothing named {ticker} in your portfolio")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/portfolio/{ticker}")
def portfolio_remove(ticker: str):
    try:
        return portfolio.remove_position(ticker)
    except KeyError:
        raise HTTPException(404, f"Nothing named {ticker} in your portfolio")


# ---------------------------------------------------------------------------
# Risk: what the portfolio becomes if each holding moves
#
# The moves are the user's data in data/risk.json (small envelope, atomic
# write, same discipline as the portfolio file). The view reuses the
# portfolio's quotes and histories, so the price columns are exactly what
# Home shows — only the moves are new.
# ---------------------------------------------------------------------------

@app.get("/api/risk")
def risk_view(refresh: bool = False, currency: str = ""):
    """Every holding with its move, its typical swing, and the scenario
    totals. ``currency`` converts like the portfolio view does."""
    return risk.view(refresh=refresh, currency=currency)


@app.post("/api/risk")
def risk_save(body: dict):
    """The whole scenario (every row) in one save. Out-of-range moves
    are clamped, junk is dropped; the echo is what was actually saved."""
    try:
        return risk.save_moves(body.get("moves") or {})
    except Exception as e:
        raise HTTPException(400, f"Could not save the moves: {e}")


class RiskFillRequest(BaseModel):
    positions: list = Field(default_factory=list)


@app.post("/api/risk/fill")
def risk_fill(req: RiskFillRequest):
    """The model's suggested move for every holding it recognizes.
    Nothing is saved: the client applies the plan and the user keeps
    only what they agree with."""
    if not llm.is_configured():
        raise HTTPException(503, "Fill with AI needs a language model. "
                                 "Set one in Settings.")
    try:
        return risk.ai_fill({"positions": req.positions})
    except RuntimeError as e:
        raise HTTPException(502, f"Could not get moves from the model: {e}")


# ---------------------------------------------------------------------------
# Economy viewer: where the world's wealth is held
#
# A static global reference picture, seven levels deep, from a stated
# total: six authored levels of detail, then geography. The whole tree is
# served from the top; drill-downs are addressed by the slash-joined node
# keys. Growth rates are assumptions the page can tune; the AI route can
# rewrite one level's list and save it to data/economy_tree.json. A
# compare route gives up to five nodes their ten-year histories (and the
# model's read of them). No prices, no live sources: every number is
# arithmetic on the stated total.
# ---------------------------------------------------------------------------

class EconomyUpdateRequest(BaseModel):
    path: list = Field(default_factory=list)


@app.get("/api/economy")
def economy_view():
    """The whole tree plus the numbers the header and strip need."""
    root = economy.view([])
    meta = economy.meta()
    meta["llm"] = llm.is_configured()
    return {**root, "meta": meta}


@app.get("/api/economy/{path:path}")
def economy_node(path: str):
    segs = [p for p in path.split("/") if p]
    out = economy.view(segs)
    if out is None:
        if len(segs) > economy.MAX_LEVEL:
            raise HTTPException(404, "The wealth tree is seven levels deep — this address is one past the bottom.")
        raise HTTPException(404, "No part of the wealth tree at that address — it may be spelled differently.")
    return out


@app.post("/api/economy/update")
def economy_update(req: EconomyUpdateRequest):
    """Rewrite one sixth-level list with the model's answer.

    The model's children are validated strictly; an unusable answer
    changes nothing. A usable one is saved atomically and returned with
    the refreshed view."""
    if not llm.is_configured():
        raise HTTPException(503, "Updating the tree needs a language model. "
                                 "Set one in Settings.")
    try:
        return economy.ai_update([str(p) for p in req.path])
    except RuntimeError as e:
        raise HTTPException(502, f"Could not update that level: {e}")


@app.post("/api/economy/reset")
def economy_reset():
    """Forget saved AI edits and go back to the authored tree."""
    return {"ok": True, "meta": economy.reset()}


class EconomyCompareRequest(BaseModel):
    paths: list = Field(default_factory=list)
    ai: bool = False


class ResearchRunRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)


@app.post("/api/economy/compare")
def economy_compare(req: EconomyCompareRequest):
    """Up to five nodes, ten years each; optionally the model's read.

    A bad address or more than five picks is a 400 in plain English; a
    missing model key is a 503 that tells the page to show the chart
    without the commentary."""
    try:
        out = economy.compare(list(req.paths or []))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    if req.ai:
        if not llm.is_configured():
            raise HTTPException(503, "The AI read needs a language model. "
                                      "Set one in Settings.")
        try:
            out = economy.ai_compare(list(req.paths or []))
        except RuntimeError as e:
            raise HTTPException(502, f"Could not read that comparison: {e}")
    return out


# ---------------------------------------------------------------------------
# Research — the goal-driven section (the old study centre's address)
# ---------------------------------------------------------------------------

@app.get("/api/research")
def research_list():
    """The saved reports, list shape (no bodies — a detail fetch pays
    for those), plus what the reader's file holds (the "what I can tie
    into" line) and whether a model is set."""
    return {"reports": research.listing(), "meta": research.meta()}


@app.post("/api/research/run")
def research_run_start(req: ResearchRunRequest, request: Request):
    """Kick off a run for a goal: the job gathers the open textbooks
    and papers on it, then the model writes one saved report that ties
    the findings to the reader's data. Returns the job to poll. The
    request's model settings are captured here — the worker thread
    cannot see the request's key."""
    config = llm.resolve()
    try:
        return research.start_run(req.goal, config, user=accounts.current_user())
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/research/run/{job_id}")
def research_run_status(job_id: str):
    """One poll of a run job: status, plain-English progress lines,
    the sources found, and the report when it's done."""
    job = research.get_run_job(job_id)
    if job is None:
        raise HTTPException(404, "No research run at that address — it "
                                  "may have expired.")
    return job


@app.get("/api/research/{rid}")
def research_detail(rid: str):
    rep = research.get_report(rid)
    if rep is None:
        raise HTTPException(404, "No report at that address. The list "
                                 "shows what the section holds.")
    return rep


@app.delete("/api/research/{rid}")
def research_delete(rid: str):
    try:
        research.delete_report(rid)
    except RuntimeError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Accounts and the private save file — the login feature. Sign in once,
# and your data lives in its own file on the host (one per person, no
# database, just the free disk); the save file is plain text, downloadable
# from Settings. Sign out with one click; anonymous use keeps the shared
# file exactly as it was.
# ---------------------------------------------------------------------------

class _Creds(BaseModel):
    username: str = Field("", max_length=40)
    password: str = Field("", max_length=300)


def _set_session_cookie(response, value: str, max_age: int | None, secure: bool):
    response.set_cookie(
        accounts.COOKIE_NAME, value, max_age=max_age, httponly=True,
        samesite="lax", secure=secure, path="/")


@app.post("/api/auth/signup")
def auth_signup(req: _Creds, request: Request):
    """Create a free account. 400 in plain English on a bad name or
    a short password; then the client signs the user in."""
    try:
        username = accounts.signup(req.username, req.password)
    except accounts.AccountError as e:
        raise HTTPException(400, str(e))
    token = accounts.issue(username)
    response = Response(
        content=json.dumps({"ok": True, "username": username}),
        media_type="application/json", status_code=201)
    _set_session_cookie(response, token, accounts.SESSION_SECONDS,
                        request.url.scheme == "https")
    return response


@app.post("/api/auth/login")
def auth_login(req: _Creds, request: Request):
    """Sign in. The cookie is set on the response; a wrong name or
    password is the same 401 every time."""
    try:
        username = accounts.login(req.username, req.password)
    except accounts.ThrottleError as e:
        raise HTTPException(429, str(e))
    except accounts.AccountError as e:
        raise HTTPException(401, str(e))
    token = accounts.issue(username)
    response = Response(
        content=json.dumps({"ok": True, "username": username}),
        media_type="application/json", status_code=200)
    _set_session_cookie(response, token, accounts.SESSION_SECONDS,
                        request.url.scheme == "https")
    return response


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    """Sign out: expire the cookie. The per-person file is untouched —
    signing out only ends the session."""
    response = Response(
        content=json.dumps({"ok": True}), media_type="application/json")
    _set_session_cookie(response, "", 0, request.url.scheme == "https")
    return response


@app.get("/api/auth/config")
def auth_config():
    """What this instance supports — the Settings card hides Google
    sign-in when the client pair is not set."""
    return {"google": accounts.google_configured()}


@app.get("/api/auth/google")
def auth_google_start(request: Request):
    """Send the browser to Google's authorization page. The state
    cookie binds the callback to this browser; the exchange happens
    server-side with the Client Secret, which never leaves the box."""
    if not accounts.google_configured():
        raise HTTPException(
            503, "Google sign-in is not set up on this instance — "
                 "the instance needs a Google OAuth client to offer it.")
    state = secrets.token_urlsafe(24)
    callback = f"{request.url.scheme}://{request.url.netloc}/api/auth/google/callback"
    response = RedirectResponse(
        accounts.google_auth_url(state, callback), status_code=302)
    response.set_cookie(accounts.COOKIE_GOOGLE_STATE, state,
                        max_age=600, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")
    return response


@app.get("/api/auth/google/callback")
def auth_google_callback(request: Request, code: str = "", state: str = ""):
    """The return leg. Google bounces the browser back here with a
    code; the server exchanges it for a token, verifies it, provisions
    (or matches) the account, signs the person in, and sends the
    browser home. Anything that fails is said in plain words."""
    if not accounts.google_configured():
        raise HTTPException(
            503, "Google sign-in is not set up on this instance.")
    cookie_state = request.cookies.get(accounts.COOKIE_GOOGLE_STATE)
    if not cookie_state or not state or not hmac.compare_digest(cookie_state, state):
        raise HTTPException(
            400, "That Google sign-in didn't come from a real request — "
                 "try again.")
    cb = f"{request.url.scheme}://{request.url.netloc}/api/auth/google/callback"
    try:
        token = accounts.google_exchange_code(code, cb)
    except Exception:
        raise HTTPException(
            502, "Couldn't talk to Google — try again in a moment.")
    try:
        claims = accounts.google_verify_id_token(
            token.get("id_token", ""),
            os.environ[accounts.GOOGLE_CLIENT_ID_ENV])
    except Exception as e:
        raise HTTPException(
            502, f"That Google answer didn't check out: {e}. "
                 "If you are signed into another Google account in this "
                 "browser, that may be why — sign out of the wrong one "
                 "and retry.")
    sub = str(claims.get("sub") or "")
    email = str(claims.get("email") or "")
    try:
        username = accounts.google_provision_user(sub, email)
    except Exception:
        raise HTTPException(400, "Couldn't finish that sign-in — try again.")
    response = RedirectResponse("/#settings", status_code=302)
    response.delete_cookie(accounts.COOKIE_GOOGLE_STATE, path="/")
    response.set_cookie(
        accounts.COOKIE_NAME, accounts.issue(username),
        max_age=accounts.SESSION_SECONDS, httponly=True,
        samesite="lax", secure=request.url.scheme == "https", path="/")
    return response


@app.get("/api/auth/me")
def auth_me():
    """Who is signed in, for the Settings page and the sidebar chip."""
    user = accounts.current_user()
    return {"authenticated": bool(user), "username": user}


@app.get("/api/vault/text")
def vault_text():
    """The save file — everything the reader owns, as plain text.

    This is the file a person downloads and keeps. The JSON export in
    Settings round-trips through Import; this one is for reading."""
    return Response(
        content=savefile.render(username=accounts.current_user()),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition":
                 'attachment; filename="longview-save.txt"'})


# The vault — one file for everything the reader owns. Export is a GET;
# import is a PUT. The client mirrors it in localStorage and syncs on
# load; these routes are the file itself, on the server's side.
# ---------------------------------------------------------------------------

@app.post("/api/vault/backup")
def vault_backup():
    """Force a second copy of your file into the cloud backup repo.
    Best-effort: a failed backup is reported, never raised."""
    user = accounts.current_user()
    if not user:
        raise HTTPException(400, "Sign in first — anonymous use keeps the shared scratchpad, not yours.")
    return backup.backup_vault(user, vault.load(), force=True)


@app.get("/api/vault")
def vault_get():
    """The whole data file (all sections, or the empty skeleton)."""
    return vault.load()


@app.put("/api/vault")
async def vault_put(request: Request):
    """Replace the server's copy with the reader's file — the import
    path. Accepts a full vault, a vault's sections block, or a bare
    {section: envelope} map; unknown names are dropped."""
    raw = await request.body()
    if len(raw) > 4_000_000:
        raise HTTPException(413, "That file is bigger than 4 MB — a "
                                 "Longview data file should not be.")
    try:
        body = json.loads(raw)
    except Exception:
        raise HTTPException(400, "That file did not parse as JSON.")
    try:
        return vault.replace(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/search")
def api_search(q: str):
    """Ticker candidates for the add-position box.

    ``results`` is a list (possibly empty) when Yahoo answered, or
    null when Yahoo couldn't be reached at all — the box shows a
    friendly note in either case and never an error."""
    results = market_data.search(q)
    return {"results": results}


@app.get("/api/money/glance")
def money_glance():
    """The home page's Smart Money tab: three pre-sorted highlights
    (most crowded, biggest moves, new bets) off the same 13F pool."""
    try:
        return portfolio.glance()
    except Exception as e:
        raise HTTPException(502, f"Could not read the funds' filings: {e}")


# ---------------------------------------------------------------------------
# Ask: one question, a plain-English answer from a language model
#
# The model sees only the numbers in funds.ask_data() — never the filings
# themselves — and its prompt says to use nothing but those numbers. It
# reuses the same LLM settings as the backtest translator
# the shared ``llm`` seam but with its own
# budget: the local model is a thinking model, and its reasoning counts
# against the output budget. Measured: the full 11-fund data block made it
# spend all of 4000 tokens on thinking and return an empty answer, so the
# budget is 8192 and funds.ask_data() keeps the data small (~4K prompt
# tokens). Answers still take 1-2 minutes, hence the 180s timeout.
# ---------------------------------------------------------------------------

ASK_SYSTEM_PROMPT = (
    "Answer the user's one question about fund holdings. "
    "Use ONLY the numbers in the JSON data block. "
    "Be plain and warm. 3 to 5 short sentences. "
    "No jargon without a quick plain-English gloss. "
    "Never invent a number that is not in the data. "
    "If the data cannot answer, say so in one plain sentence. "
    "Do not use markdown."
)


class AskRequest(BaseModel):
    q: str = Field(min_length=1, max_length=500)
    quarters: int = Field(1, ge=1, le=4)
    funds: str = Field("", max_length=200)    # comma-separated keys; empty = all
    exclude: str = Field("", max_length=200)  # keys to leave out


def _ask_llm(question: str, data: dict) -> tuple[str, str]:
    """Data + question -> one plain-English answer. Returns (answer, model).
    Raises on any failure — the route turns those into plain-English errors."""
    cfg = llm.resolve()
    if not cfg["key"]:
        raise RuntimeError("no key")
    r = httpx.post(
        cfg["base"] + "/chat/completions",
        headers={"Authorization": f"Bearer {cfg['key']}"},
        json={
            "model": cfg["model"],
            "temperature": 0,
            "max_tokens": 8192,   # thinking tokens count against this
            "messages": [
                {"role": "system", "content": ASK_SYSTEM_PROMPT},
                {"role": "user",
                 "content": f"Question: {question}\n"
                            f"Data: {json.dumps(data, separators=(',', ':'))}"},
            ],
        },
        timeout=180,
    )
    r.raise_for_status()
    content = (r.json()["choices"][0]["message"]["content"] or "").strip()
    if not content:
        raise RuntimeError("the model returned an empty answer")
    return content, cfg["model"]


# ---------------------------------------------------------------------------
# Chat: the little bubble in the corner. Same local model as Ask, but a
# compact look at the saved portfolio instead of the 13F data block.
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = (
    "You are Longview's assistant, a calm, plain-spoken guide. You can see "
    "three things: the user's saved portfolio, the page of the app they "
    "are currently looking at, and their saved notes. Use whichever of "
    "these the question is about, and say plainly when the answer is not "
    "in the data. 'This' and 'it' usually mean the current page. You may "
    "use general financial knowledge for definitions and context. Answer "
    "in 2 to 5 short sentences. No markdown, no bullet lists. Never invent "
    "a price, a return, or a holding. Be clear that you are not a "
    "financial adviser and this is not advice. If the question is "
    "unrelated to investing or this app, answer briefly and steer back to "
    "the app."
)


class ChatMessage(BaseModel):
    role: str = Field("user", max_length=16)
    content: str = Field("", max_length=2000)


class ChatRequest(BaseModel):
    q: str = Field(min_length=1, max_length=800)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)
    currency: str = Field("", max_length=3)
    page: dict = Field(default_factory=dict)  # a brief of the current page


def _ticker_currency(ticker: str) -> str:
    """A saved ticker's likely currency, from its exchange suffix.

    The portfolio file stores no currency for listed holdings (the live
    quote supplies it), but the chat model should not read a JPY cost as
    dollars. This is a hint only: the table's live numbers still come
    from Yahoo.
    """
    t = (ticker or "").upper()
    for suffix, cur in (
        (".T", "JPY"), (".TO", "CAD"), (".V", "CAD"), (".HK", "HKD"),
        (".L", "GBP"), (".IL", "GBP"), (".DE", "EUR"), (".PA", "EUR"),
        (".AS", "EUR"), (".MI", "EUR"), (".MC", "EUR"), (".SW", "CHF"),
        (".AX", "AUD"), (".SI", "SGD"), (".SS", "CNY"), (".SZ", "CNY"),
    ):
        if t.endswith(suffix):
            return cur
    return "USD"


def _chat_context(currency: str = "") -> dict:
    """A small, safe snapshot of the saved portfolio: no live fetching,
    no notes beyond what the user already sees in the table."""
    positions = portfolio.load_portfolio()
    rows = []
    cost_by_currency: dict[str, float] = {}
    for p in positions:
        custom = (p.get("kind") or "stock") == "custom"
        cur = p.get("currency") if custom else _ticker_currency(p.get("ticker") or "")
        row = {
            "ticker": p.get("ticker"),
            "name": p.get("name") or p.get("ticker"),
            "shares": p.get("shares"),
            "purchase_price": p.get("cost_basis"),
            "purchase_date": p.get("purchase_date") or None,
            "kind": "custom" if custom else "stock",
            "currency": cur,
        }
        if custom:
            row["current_price"] = p.get("price")
        rows.append(row)
        try:
            cost_by_currency[cur] = cost_by_currency.get(cur, 0.0) + float(
                p.get("shares") or 0) * float(p.get("cost_basis") or 0)
        except (TypeError, ValueError):
            pass
    return {"display_currency": (currency or "").upper() or None,
            "cost_by_currency": {k: round(v, 2) for k, v in cost_by_currency.items()},
            "holdings": rows}


def _notes_context(max_pages: int = 10, max_chars: int = 5000) -> list[dict]:
    """The saved notebook, trimmed to fit the model's attention. Most
    recently updated pages first; each page is its title plus body and a
    little of the first saved snippet. A notebook the model can't see is
    a notebook it can't use — so it's always in the context."""
    pages = notes.load_pages()
    pages.sort(key=lambda p: -(p.get("updated") or p.get("created") or 0))
    out: list[dict] = []
    used = 0
    for p in pages:
        parts = [(p.get("body") or "")[:800]]
        snip = (p.get("snippets") or [{}])[0]
        if snip.get("title"):
            parts.append(snip["title"])
        parts.extend((snip.get("lines") or [])[:6])
        text = " ".join(" ".join(x.split()) for x in parts if x)
        text = text[:1200]
        if not text.strip():
            continue
        out.append({"title": (p.get("title") or "Untitled").strip()[:120],
                    "text": text})
        used += len(text)
        if len(out) >= max_pages or used >= max_chars:
            break
    return out


def _s(x) -> str:
    """Collapse whitespace and cap length: page briefs are prompt text,
    not data to preserve verbatim."""
    return " ".join(str(x or "").split())[:400]


def _page_context(page: dict) -> str:
    """The page the user is looking at, as one plain-English line.
    The client sends the same numbers it is rendering, so the model
    answers about what the user sees."""
    if not isinstance(page, dict) or not page.get("kind"):
        return ""
    kind = str(page.get("kind"))[:16]
    if kind == "company":
        line = (f"Company page: {_s(page.get('name') or page.get('symbol'))} "
                f"({_s(page.get('symbol'))})")
        bits = []
        if page.get("price") is not None:
            bits.append(f"price {page.get('currency') or 'USD'} {page['price']:g}")
        if page.get("change_pct") is not None:
            bits.append(f"change {page['change_pct']:+.1f}%")
        if page.get("market_cap") is not None:
            bits.append(f"market cap {page['market_cap']:,.0f}")
        if page.get("pe") is not None:
            bits.append(f"P/E {page['pe']:.1f}")
        if page.get("about"):
            bits.append(f"business: {_s(page.get('about'))}")
        if page.get("dcf"):
            bits.append(f"DCF card: {_s(page.get('dcf'))}")
        if bits:
            line += " — " + ", ".join(bits)
        return line[:600]
    if kind == "lab":
        line = (f"Backtest Lab: strategy \"{_s(page.get('text'))}\" on "
                f"{_s(page.get('symbol') or 'SPY')} for "
                f"{int(page.get('years') or 10)} years")
        if page.get("verdict"):
            line += " — " + _s(page.get("verdict"))
        elif page.get("summary"):
            line += " — " + _s(page.get("summary"))
        return line[:600]
    if kind == "money":
        return f"Smart Money page (the {_s(page.get('sub') or 'holdings')} view)"
    if kind == "notes":
        return "Notes (the notebook)"
    if kind == "home":
        return "Home (the portfolio)"
    if kind == "risk":
        line = ("Risk page: a scenario of moves for the saved portfolio")
        if page.get("scenario") is not None:
            cur = f" {page['currency']}" if page.get("currency") else ""
            line += (f" — after the moves, {page['value']:g}{cur} becomes "
                     f"{page['scenario']:g}{cur}")
        return line[:600]
    if kind == "economy":
        sub = _s(page.get("sub"))
        return ("Economy viewer: a static picture of global household "
                "wealth, seven levels deep"
                + (f" — currently looking at {sub}" if sub else ""))
    return ""


SMART_PATTERNS = (
    r"\bwho\s+(?:holds|owns|is buying|bought|has been buying)\s+(.+)",
    r"\bwhich\s+(?:funds?|investors?|managers?)\s+"
    r"(?:hold|own|are buying|bought|like)\s+(.+)",
    r"\b(?:do|are)\s+(?:the\s+)?(?:funds?|big investors|smart money)\s+"
    r"(?:hold|own|buying|bought)\s+(.+)",
    r"\bsmart money\s+(?:on|for|in|check|lookup|look up)\s+(.+)",
    r"\b(?:check|look up|show)\s+(.+?)\s+"
    r"(?:in|on)\s+(?:smart money|13f|holdings)\b",
    r"\b(?:what|how much)\s+(?:do\s+)?(?:the\s+)?funds?\s+"
    r"(?:hold|own)\s+(?:of|in)\s+(.+)",
    r"\b(?:is|are)\s+(.+?)\s+(?:held|owned)\s+by\s+(?:the\s+)?funds?\b",
)
SMART_TRIM = re.compile(
    r"\s+(?:right now|currently|these days|this quarter|last quarter|"
    r"and how much|and why|please)\s*$", re.I)


def _clean_security(q: str) -> str:
    q = re.sub(r"\s+", " ", (q or "").strip()).strip(" .,:;!?")
    q = re.sub(r"^(?:the|a|an)\s+", "", q, flags=re.I)
    q = SMART_TRIM.sub("", q)
    return q.strip(" .,:;!?")[:80]


def _plan_backtest(q: str) -> dict | None:
    low = q.lower()
    if not re.search(
            r"\bback[- ]?test(?:ing)?\b|^\s*test\b|"
            r"\bhow would\b.+\b(?:have done|have performed|have held up)\b",
            low):
        return None
    rest = q
    m = re.search(r"\bback[- ]?test(?:ing)?\b(.*)$", q, re.I)
    if m:
        rest = m.group(1)
    else:
        m = re.match(r"^\s*(?:test|try)\s+(.+)$", q, re.I)
        if m:
            rest = m.group(1)
        else:
            m = re.search(r"\bhow would\s+(.+?)\s+have done\b", q, re.I)
            if m:
                rest = m.group(1)
    rest = rest.strip(" .,:;!?")
    years = 10
    ym = re.search(r"\b(\d{1,2})\s*(?:years?|yrs?)\b", rest, re.I)
    if ym:
        years = max(1, min(30, int(ym.group(1))))
        rest = (rest[:ym.start()] + " " + rest[ym.end():]).strip()
    symbol = "SPY"
    sm = re.search(r"\b(?:on|for|in|with)\s+\$?([A-Z][A-Z0-9.\-]{0,9})\b", rest)
    if sm:
        symbol = sm.group(1).upper()
        rest = (rest[:sm.start()] + " " + rest[sm.end():]).strip()
    else:
        sm = re.search(r"\$?\b([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\b", rest)
        if sm and sm.group(1).upper() not in {"SPY", "BUY", "SELL", "HOLD", "A", "I"}:
            symbol = sm.group(1).upper()
            rest = (rest[:sm.start()] + " " + rest[sm.end():]).strip()
    text = re.sub(r"^(?:of|for|on|with|to|the)\s+", "", rest.strip(), flags=re.I)
    text = re.sub(r"\s+(?:of|for|on|with|to|the)$", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" .,:;!?")
    if not text or re.fullmatch(r"(?:it|this|that|my portfolio)", text, re.I):
        text = "buy and hold"
    return {"type": "backtest", "text": text[:120],
            "symbol": symbol, "years": years}


def _plan_risk_fill(q: str) -> dict | None:
    """'Do the risk fill' and friends. The word boundary keeps
    'risky' and 'what is the risk' out of it; a verb is required."""
    low = q.lower()
    if not re.search(r"\brisk\b", low):
        return None
    if re.search(r"\b(?:do|run|fill|auto-?fill)\b", low):
        return {"type": "risk_fill"}
    return None


def _plan_action(question: str) -> dict | None:
    """Spot a request that should open a Smart Money page, a backtest,
    or the risk fill.
    Deterministic on purpose: it must be reliable, and it works even when
    the language model is not configured."""
    q = re.sub(r"\s+", " ", (question or "").strip())
    if not q:
        return None
    rf = _plan_risk_fill(q)
    if rf:
        return rf
    bt = _plan_backtest(q)
    if bt:
        return bt
    for pat in SMART_PATTERNS:
        m = re.search(pat, q, re.I)
        if m:
            query = _clean_security(m.group(1))
            if query and query.lower() not in {
                    "most", "the most", "more", "the biggest", "biggest"}:
                return {"type": "smart_money", "query": query}
    return None


def _action_answer(action: dict) -> str:
    if action["type"] == "risk_fill":
        return ("Opening Risk and filling in the moves: the model picks a "
                "plausible move for each holding, and you keep whatever "
                "you agree with. Not advice.")
    if action["type"] == "smart_money":
        return (f"Opening Smart Money for {action['query']}. "
                "It will show which funds hold it and how their positions "
                "changed. Not advice.")
    return (f"Opening a backtest of {action['text']} on {action['symbol']} "
            f"over {action['years']} years. Not advice.")


def _chat_llm(question: str, history: list[ChatMessage], context: dict) -> tuple[str, str]:
    cfg = llm.resolve()
    if not cfg["key"]:
        raise RuntimeError("no key")
    key, base, model = cfg["key"], cfg["base"], cfg["model"]
    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    for m in history[-8:]:
        role = m.role if m.role in ("user", "assistant") else "user"
        text = (m.content or "").strip()
        if text:
            messages.append({"role": role, "content": text[:1000]})
    body = f"Question: {question}\n"
    body += ("Portfolio: " + json.dumps(
        {k: v for k, v in context.items() if k not in ("page", "notes")},
        separators=(",", ":"))) + "\n"
    if context.get("page"):
        body += f"Current page: {context['page']}\n"
    if context.get("notes"):
        body += "Saved notes:\n" + "\n".join(
            f"- {n['title']}: {n['text']}" for n in context["notes"]) + "\n"
    messages.append({"role": "user", "content": body.rstrip()})
    r = httpx.post(
        base + "/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "temperature": 0.2, "max_tokens": 4096,
              "messages": messages},
        timeout=180,
    )
    r.raise_for_status()
    content = (r.json()["choices"][0]["message"]["content"] or "").strip()
    if not content:
        raise RuntimeError("the model returned an empty answer")
    return content, model


@app.post("/api/chat")
def chat(req: ChatRequest):
    """The corner bubble: one question about the saved portfolio.
    Requests that name a Smart Money lookup or a backtest open that page
    instead of guessing an answer."""
    action = _plan_action(req.q)
    if action:
        return {"q": req.q, "model": "Longview",
                "answer": _action_answer(action), "action": action}
    if not llm.is_configured():
        raise HTTPException(503, "The chat bubble needs a language model. "
                                 "Set one in Settings.")
    try:
        context = _chat_context(req.currency)
        context["page"] = _page_context(req.page)
        context["notes"] = _notes_context()
        answer, model = _chat_llm(req.q, req.history, context)
    except httpx.TimeoutException:
        raise HTTPException(504, "The model took too long to answer. "
                                 "Give it a minute, then try again.")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"The language model is not answering: {e}")
    except Exception as e:
        raise HTTPException(502, f"Could not get an answer: {e}")
    return {"q": req.q, "model": model, "answer": answer}


@app.post("/api/money/ask")
def money_ask(req: AskRequest):
    """One question about what the tracked funds hold and how it is
    changing. A language model reads the filings' numbers and answers
    in plain English."""
    if not llm.is_configured():
        raise HTTPException(503, "Ask needs a language model. "
                                 "Set one in Settings.")
    include = {x.strip() for x in req.funds.split(",") if x.strip()}
    exclude = {x.strip() for x in req.exclude.split(",") if x.strip()}
    all_roster = funds.active_roster()
    if include and not include & {f["key"] for f in all_roster}:
        raise HTTPException(400, "None of those funds are on the roster.")
    roster = [f for f in all_roster
              if (not include or f["key"] in include)
              and f["key"] not in exclude]
    if not roster:
        raise HTTPException(400, "Those fund picks leave nothing to ask about.")
    try:
        data = funds.ask_data(quarters=req.quarters, roster=roster)
    except Exception as e:
        raise HTTPException(502, f"Could not read the funds' filings: {e}")
    if not data["funds"]:
        raise HTTPException(502, "None of the tracked funds have a readable "
                                 "13F right now.")
    try:
        answer, model = _ask_llm(req.q, data)
    except httpx.TimeoutException:
        raise HTTPException(504, "The model took too long to answer. "
                                 "Give it a minute, then try again.")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"The language model is not answering: {e}")
    except Exception as e:
        raise HTTPException(502, f"Could not get an answer: {e}")
    return {
        "q": req.q,
        "quarters": data["window"]["quarters"],
        "window": {"start": data["window"]["start"],
                   "end": data["window"]["end"]},
        "n_funds": len(data["funds"]),
        "missing": data["missing"],
        "model": model,
        "answer": answer,
    }


# ---------------------------------------------------------------------------
# The filer directory (what you search) + the roster (what gets scanned)
# ---------------------------------------------------------------------------

# The first build crawls ~90 small index files from the SEC; run it in a
# background thread and let the front end poll this status.
_dir_build_lock = threading.Lock()
_dir_building = False


class RosterAddRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    cik: str = Field(min_length=1, max_length=12)


def _roster_change():
    """After an add/remove: rebuild the pool and the view over the new
    roster (all filings are forever-cached, so this is disk work, not
    SEC traffic — except where a fund's 24h filing index expired)."""
    try:
        return funds.market_view(refresh=True)
    except Exception as e:
        raise HTTPException(502, f"The roster changed, but re-reading the "
                                 f"filings failed: {e}")


@app.get("/api/money/directory/status")
def money_directory_status():
    """Is the filer directory ready yet? Kicks off the first build."""
    global _dir_building
    if directory.load_snapshot() is not None:
        snap = directory.load_snapshot()
        return {"ready": True, "n_filers": snap["n_filers"],
                "quarters": snap["quarters"], "generated": snap["generated"]}
    with _dir_build_lock:
        if not _dir_building:
            _dir_building = True

            def _build():
                try:
                    directory.build_snapshot(refresh=True)
                except Exception as e:
                    # The front end keeps polling, so the next try rebuilds.
                    print(f"[directory] first build failed: {e!r}", flush=True)
                finally:
                    with _dir_build_lock:
                        _dir_building = False

            threading.Thread(target=_build, daemon=True).start()
    return {"ready": False}


@app.get("/api/money/directory")
def money_directory(q: str = "", limit: int = 12):
    """Search the directory of 13F filers by name (or CIK), 2+ characters."""
    try:
        results = directory.search(q, limit)
    except directory.DirectoryError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(502, f"Couldn't read the filer directory: {e}")
    in_roster = {str(f["cik"]) for f in funds.active_roster()}
    return {"q": q, "results": [dict(r, in_roster=r["cik"] in in_roster)
                                for r in results]}


@app.get("/api/money/roster")
def money_roster():
    """The funds that actually get scanned (defaults + adds − removals)."""
    return {"funds": funds.active_roster()}


@app.post("/api/money/roster")
def money_roster_add(req: RosterAddRequest):
    """Add a fund from the directory. Refuses filers without a current
    13F, in plain English; then re-reads everything over the new roster."""
    try:
        entry, roster = funds.add_fund(req.name, req.cik)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except directory.DirectoryError as e:
        raise HTTPException(502, str(e))
    except RuntimeError as e:
        raise HTTPException(400, f"Couldn't add {req.name}: {e}")
    except Exception as e:
        raise HTTPException(502, f"Could not check {req.name} against the "
                                 f"SEC: {e}")
    return {"ok": True, "added": entry, "funds": roster, "view": _roster_change()}


@app.delete("/api/money/roster/{key}")
def money_roster_remove(key: str):
    """Remove a fund from the roster (the roster can never be emptied)."""
    try:
        removed, roster = funds.remove_fund(key)
    except KeyError:
        raise HTTPException(404, f"No fund called '{key}' on the roster")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "removed": removed, "funds": roster, "view": _roster_change()}


# ---------------------------------------------------------------------------
# Company: one company, every part of it
#
# The "little parts" behind a stock — price and ranges, market cap, P/E,
# dividend, averages, volume, earnings date, revenue, margins, the story.
# Yahoo's quote/quoteSummary endpoints plus a year of chart history,
# assembled in market_data.company(). Every part degrades to a dash when
# Yahoo is busy, so this route returns 200 with nulls — never a 500.
# ---------------------------------------------------------------------------

@app.get("/api/company/{symbol}")
def company_view(symbol: str):
    """One company, every part. All fields null when Yahoo couldn't be
    reached — the page renders with dashes, it never fails."""
    return market_data.company(symbol)


# ---------------------------------------------------------------------------
# Notes: your pages, plus anything you saved from the app
#
# The notebook is the user's data in data/notes.json (same envelope and
# atomic write as the portfolio). A page has free text plus snippets —
# pieces saved from the Ask answers, backtest results, smart-money rows,
# and company pages. A missing or corrupt file is an empty notebook.
# ---------------------------------------------------------------------------

@app.get("/api/notes")
def notes_list():
    """Every page as a summary (title, date, counts), newest first."""
    return {"pages": notes.list_pages()}


@app.post("/api/notes")
def notes_create(body: dict):
    """A new page. An empty title is fine — the editor focuses the name."""
    try:
        return notes.create_page(body.get("title") or "",
                                 body.get("body") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/notes/{page_id}")
def notes_get(page_id: str):
    try:
        return notes.get_page(page_id)
    except KeyError:
        raise HTTPException(404, "No note with that id")


@app.patch("/api/notes/{page_id}")
def notes_update(page_id: str, body: dict):
    """Change the title and/or body; omit a key to leave it alone."""
    try:
        return notes.update_page(page_id, title=body.get("title"),
                                 body=body.get("body"))
    except KeyError:
        raise HTTPException(404, "No note with that id")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/notes/{page_id}")
def notes_delete(page_id: str):
    try:
        removed = notes.delete_page(page_id)
    except KeyError:
        raise HTTPException(404, "No note with that id")
    return {"ok": True, "removed": {"id": removed["id"]}}


@app.post("/api/notes/{page_id}/snippets")
def notes_add_snippet(page_id: str, body: dict):
    """Append a saved piece (a tag, a title, lines of text). Re-saving
    the same piece to the same page changes nothing but returns the page."""
    try:
        return notes.add_snippet(page_id, body.get("source") or "other",
                                 body.get("title") or "",
                                 body.get("lines") or [])
    except KeyError:
        raise HTTPException(404, "No note with that id")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/notes/{page_id}/snippets/{snippet_id}")
def notes_delete_snippet(page_id: str, snippet_id: str):
    try:
        return notes.delete_snippet(page_id, snippet_id)
    except KeyError:
        raise HTTPException(404, "No such saved piece")
