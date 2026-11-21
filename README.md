# Longview — the filings, decoded

Longview is a self-hosted research desk for equity investors. It
reads public data — 13F filings, live prices, twenty years of market
history, a map of where the world's wealth is held — and turns it
into working tools. One Python process, no database, no login: the
state is yours, it lives on your machine, and the only thing you
supply is a language-model key for the AI features.

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

**Reference.** Ten long-form notes on how money works — markets,
shares, bonds, money and inflation, wealth, housing, banks,
pensions, the mechanics of investing, and why people lose money —
each roughly five thousand words, structured, no prices and no
advice. With a model key set, a bring-material card appears: paste a
document, or name a topic and the app gathers open reference pages
(Wikipedia, open textbooks, arXiv) and writes one saved note with
its sources listed beneath it.

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
git clone <your-git-host>/longview.git && cd longview
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8010
```

Then open http://localhost:8010.

The first page is your portfolio, empty until you add something. The
first request that needs 13F data takes about thirty seconds of SEC
time; after that everything is cached on disk and instant, and the
filer directory builds itself in the background on first use and
refreshes daily.

Two notes:

- Any port works; the examples use 8010 because 8000 is the default
  of most local model servers.
- The web-facing lookups need name resolution. On a machine whose
  resolver is broken, the app falls back to DNS-over-HTTPS on its
  own; `LONGVIEW_DNS_FALLBACK=0` disables the fallback.

## The model key

Every feature that uses a language model — Ask, the risk fill, the AI
backtest, the reference notes, the economy's AI edits — resolves its
model from one place, in this order:

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
one small call and tells you which model is really answering.

## Where the data comes from

All free, no API keys:

- **Prices and FX** — Yahoo Finance's public chart and quote APIs:
  split- and dividend-adjusted history for backtests, live quotes
  for your portfolio, the Company page, and currency conversion.
- **Fund holdings** — SEC EDGAR: each fund's latest 13F, parsed from
  the filed XML.
- **Filer directory** — SEC EDGAR's public daily filing index (who
  has filed a 13F).
- **Reference search** — Wikipedia, Wikibooks, and Wikiversity (the
  public MediaWiki search and page APIs) and arXiv (the export
  API).

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
  main.py          the web app: routes, the no-cache and LLM-override
                   middleware, and the front end
  llm.py           the one seam behind every model feature: config
                   resolution (per-request header, environment) and
                   the single HTTP call
  market_data.py   Yahoo: history, live quotes, company data, all
                   disk-cached
  portfolio.py     your portfolio: the positions file, quote
                   enrichment, the smart-money cross-check
  risk.py          the Risk page: the scenario math, per-holding
                   volatility, the AI fill
  economy.py       the Economy viewer: shares, dollars, paths,
                   breadcrumbs, the AI list edits
  economy_tree.py  the wealth tree: about 3,900 nodes, six authored
                   levels plus geography, research-tuned splits
  backtest.py      the engine: five rules, metrics, the verdict
  strategy_lab.py  the lab: the portfolio engine, the plan reader,
                   the LLM interpreter and decider
  research.py      the lab's date-gated web research, with a budget
  funds.py         the 13F pipeline: fetch, parse, diff, the editable
                   roster, the scan pool
  directory.py     the searchable directory of 13F filers
  translator.py    English to strategy spec: the built-in reader,
                   the optional LLM
  notes.py         your notebook: pages, saved snippets, tidy-up
  study.py         the Reference centre: the note pipeline, the AI
                   document and web modes
  study_data/      the ten authored reference notes (plain markdown)
  static/          the front end: index.html, style.css, app.js,
                   dcf.js — hand-built, no frameworks
tests/             439 offline tests
data/              your files (roster, portfolio, notes, risk moves,
                   reference notes); created on first write, untracked
cache/             downloaded data (prices, filings, directory);
                   untracked
```

## Tests

```
.venv/bin/python -m pytest tests/ -q
```

439 tests, all offline: made-up prices, canned SEC-format XML, fake
filing indexes, and canned web responses. They never touch the
network, and none of them calls a real model.

## License

MIT. The filings belong to the public; the tool that reads them
should too. Fork it, self-host it, build your own.
