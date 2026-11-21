# Longview — the filings, decoded

Longview is a research desk for equity investors. It reads public
data — 13F filings, live prices, twenty years of market history, a
map of where the world's wealth is held — and turns it into working
tools. One Python process, no database, no login: everything you
keep in it lives in one file you can carry anywhere, and the only
thing you supply is a language-model key for the AI features.

Run your own with the four lines in Quick start, or use the public
instance (see The hosted version) — both run from this repository.

## What it does

**Smart money.** Every quarter the largest US funds file their
holdings with the SEC (form 13F). Longview reads the latest filing
from every fund on your roster — eleven by default, from Buffett to
Simons — and answers the questions an investor actually asks: what do
they hold, what did they add or sell last quarter, which names have
several of them piled into, and what new bet is *only one* of them
making? Everything sits behind one filterable table, with a
one-row-per-company mode and a CSV export. The roster is yours to
edit: a directory of 10,000+ filers, searchable.

**Risk.** Your portfolio, marked to live prices — weights, a year's
return, the size of the typical swings — and the scenario under which
it stands. Type a hypothetical move per holding, or let the model
suggest plausible ones and approve them line by line; the strip at
the top shows what the total becomes.

**Backtest lab.** Two ways to run a strategy on a portfolio. Set the
rules in a form — up to ten tickers, check frequency, drop triggers,
an upside exit — and Longview applies them literally, day by day, to
real history. Or describe the strategy in your own words: the model
reads it into a plan once, then *is* the trader, deciding on every
check day. With research on, it reads the web on each decision day —
only the pages as they existed on that date, never what came after.
Both are judged against buy-and-hold of the same holdings, and every
decision is logged: what it saw, what it did, why.

**Company.** One page per company: live price, the numbers behind it
(market cap, P/E, dividend, revenue, margins), a year of history, and
a discounted cash flow card — or flipped to implied growth: what
yearly growth does today's price assume?

**Economy.** Where the world's wealth is held, in one picture: about
$470T at the end of 2024, seven levels deep, every branch ending in
the same four regions. Hover for a slice's number, click to descend,
compare two to five branches over the decade, project any node at its
own rate. A reference picture with assumptions you can move — not
accounting.

**Notes.** A plain notebook. Press **Save** on anything else in the
app — an answer, a backtest, a fund's move, a company — to file it
onto a page, with its source and the date you saved it.

**Research.** The section for questions. Give it a goal — a sentence
or two about what you want to understand or decide — and it does the
work: it reads the open textbooks and papers on that goal
(Wikipedia, Wikibooks, Wikiversity, the arXiv; the hosts are fixed,
the goal travels as a parameter), then the model writes one saved
report — a plain-English brief, its sources listed, and a final part
that ties the findings to your own data: your holdings, your notes,
your risk moves. With no data in the file it says so, and the report
stands on its own.

**Ask.** The question box answers from what it can see — your
holdings, the open page, your saved notes — and can act: "backtest
buy the dip on AAPL for five years" opens the lab and runs it. It
always says it is not advice.

All of it is honest by design: the backtester refuses lookahead, the
13F view says what it cannot see, and the caveats sit right on the
page.

## Quick start

Python 3.10 or newer. Nothing else.

```
git clone https://github.com/akirinsolutions/longview.git && cd longview
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8010
```

Then open http://localhost:8010.

The first page is your portfolio, empty until you add something.
What you add lives in one file — `data/longview.json`, created on
first write: every section of the app, one file, yours to keep and
carry (see Your data). The first request that needs 13F data takes
about thirty seconds of SEC time; after that everything is cached on
disk and instant, and the filer directory builds itself in the
background on first use and refreshes daily.

Two notes:

- Any port works; the examples use 8010 because 8000 is the default
  of most local model servers.
- The web-facing lookups need name resolution. On a machine whose
  resolver is broken, the app falls back to DNS-over-HTTPS on its
  own; `LONGVIEW_DNS_FALLBACK=0` disables the fallback.

## The model key

Every feature that uses a language model — Ask, the risk fill, the AI
backtest, research, the economy's AI edits — resolves its model from
one place, in this order:

1. **Your key, per request.** Set it in the Settings tab: a base
   URL, a key, and a model name. It is stored in your browser's local
   storage and sent with each request as an `X-Longview-LLM` header.
   The app never stores it: the key is relayed to your endpoint and
   forgotten.
2. **The server's key.** If no per-request key is set, the app reads
   `LONGVIEW_LLM_KEY`, `LONGVIEW_LLM_BASE`, and `LONGVIEW_LLM_MODEL`
   from its environment (the legacy `PROOF_LLM_*` names are still
   read as a fallback).
3. **No key.** The app is fully functional without one. The AI
   features go quiet and say so plainly, in one sentence, instead of
   failing silently.

Any OpenAI-compatible endpoint works — OpenAI itself, a hosted
provider, or a server you run. The Settings tab's test button makes
one small call and tells you which model is really answering. The
public instance is deployed without a key of its own: its AI
features run on the key each visitor brings, per request. One rule
keeps a shared instance safe: a base URL is vetted before any call
goes out — https to any public host, plain http to 127.0.0.1 only,
private and metadata addresses refused — so a visitor's key can be
relayed to an endpoint, never used to reach a machine behind a
firewall.

## Your data

There is no login and no account, because there is no per-person
storage: one file. Everything you keep in the app — your portfolio,
your notes, your risk moves, your followed funds, your research
reports, the economy tree — lives in `data/longview.json`, and your
browser holds a mirror of it. When you open the app the two compare
and the newer one wins. In Settings the file is in your hands:
download it (that is your whole data), import one back, and see what
it holds. The file is the storage; the server just serves it.

## The hosted version

The public instance runs this repository on a plain Python host,
with nothing else on it. On Render: create a **Web Service** on the
Python runtime, and for the start command:

```
uvicorn app.main:app --port $PORT
```

No Dockerfile, no database, no environment to set: `requirements.txt`
is the whole dependency story. The instance ships without a model
key, so its AI features run on the key each visitor brings in
Settings (sent per request, relayed to the visitor's own endpoint,
never stored).

One honest limitation, stated plainly: the data file lives on the
host's disk, and on an ephemeral free tier that disk may be wiped on
a redeploy. The file is shared, not per-person, so treat the public
instance's file as a scratchpad — use the app freely, and download
the file when you want your work to outlive the instance. To keep a
permanent home for your data, run your own Longview (the four lines
in Quick start) and import the file there.

## Where the data comes from

All free, no API keys:

- **Prices and FX** — Yahoo Finance's public chart and quote APIs:
  split- and dividend-adjusted history for backtests, live quotes
  for your portfolio, the Company page, and currency conversion.
- **Fund holdings** — SEC EDGAR: each fund's latest 13F, parsed from
  the filed XML.
- **Filer directory** — SEC EDGAR's public daily filing index (who
  has filed a 13F).
- **Open reference** — Wikipedia, Wikibooks, and Wikiversity (the
  public MediaWiki search and page APIs) and arXiv (the export
  API): the research gather, and the backtest lab's date-gated
  research, both read from this pool.

Everything is cached on disk in `cache/`: 13F filings forever (a
filing never changes once filed), backtest prices daily, portfolio
quotes every ten minutes, company snapshots every fifteen. The app
sends a declared `User-Agent` with a contact address to the SEC and
spaces out its requests: a polite, light client.

## What the backtester refuses to do

- Trades execute at the **close** of the day the signal fires. A
  strategy can never see tomorrow's price.
- Prices are **split- and dividend-adjusted**, so a dividend does not
  look like a crash and a split does not look like a miracle.
- The benchmark is always **buy-and-hold of the same holdings over
  the same window** — the only comparison that answers "would doing
  nothing have beaten this?"
- An optional trading cost, in basis points, applies to every fill.
- In research mode the web is **date-gated**: on a simulated date the
  reader sees only pages as they existed on or before that date.
- Every verdict ends with the caveat that a backtest is a replay of
  one market, not a promise.

## What the 13F view can and cannot see

- It sees the **US long stock positions** of the funds on your
  roster, as of the end of the last reported quarter, in dollars.
- It cannot see — and says so, on the page — **short positions,
  options, international holdings, private stakes**, or anything in
  the current quarter that has not been filed yet (the 45-day lag).
- A sold position shows as "was $X", valued in the previous quarter:
  a 13F reports only what a fund holds, so a sale appears as a
  position that disappeared.

## The code

```
app/
  main.py           the web app: routes, the no-cache and LLM-override
                    middleware, and the front end
  llm.py            the one seam behind every model feature: config
                    resolution, the base-URL check, the single HTTP call
  vault.py          one file for everything the reader owns: the load,
                    the one-time legacy fold, the export/import replace
  web.py            the polite web client: the open reference pool
                    (Wikipedia, Wikibooks, Wikiversity, arXiv), capped
  research.py       the research section: a goal in, one saved report
                    that ties into the reader's data, the run jobs
  lab_research.py   the backtest lab's date-gated researcher; shares
                    the web client, not the section
  market_data.py    Yahoo: history, live quotes, company data, all
                    disk-cached
  portfolio.py      your portfolio: the positions, quote enrichment,
                    the smart-money cross-check
  risk.py           the Risk page: the scenario math, per-holding
                    volatility, the AI fill
  economy.py        the Economy viewer: shares, dollars, paths,
                    breadcrumbs, the AI list edits
  economy_tree.py   the wealth tree: about 3,900 nodes, six authored
                    levels plus geography, research-tuned splits
  economy_series.py the decade charts: 2015–2024 per node, each point
                    labelled for how measured it is
  backtest.py       the engine: five rules, metrics, the verdict
  strategy_lab.py   the lab: the portfolio engine, the plan reader,
                    the LLM interpreter and decider
  funds.py          the 13F pipeline: fetch, parse, diff, the editable
                    roster, the scan pool
  directory.py      the searchable directory of 13F filers
  translator.py     English to strategy spec: the built-in reader,
                    the optional LLM
  notes.py          your notebook: pages, saved snippets, tidy-up
  netfix.py         DNS-over-HTTPS fallback for hosts whose resolver
                    is broken
  study_data/       the ten authored reference notes — dormant
                    reference material, no longer served
  static/           the front end: index.html, style.css, app.js,
                    dcf.js — hand-built, no frameworks
tests/              432 offline tests
data/               your data: one file (longview.json) holding every
                    section; created on first write, untracked
cache/              downloaded data (prices, filings, directory);
                    untracked
```

## Tests

```
.venv/bin/python -m pytest tests/ -q
```

432 tests, all offline: made-up prices, canned SEC-format XML, fake
filing indexes, and canned web responses. They never touch the
network, and none of them calls a real model.

## License

MIT. The filings belong to the public; the tool that reads them
should too. Fork it, self-host it, build your own.
