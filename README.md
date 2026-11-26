# Longview — the filings, decoded

Longview is a research desk for equity investors. It reads public
data — 13F filings, live prices, twenty years of market history, a
map of where the world's wealth is held — and turns it into working
tools. One Python process, no database: everything you keep in it
lives in one file you can carry anywhere, and the only thing you
supply is a language-model key for the AI features. Sign in — or
create a free account — and your data is yours alone: one file per
person, stored on the host, downloadable as plain text.

Run your own with the four lines in Quick start, or use the public
instance at https://kirin123.pythonanywhere.com (see The hosted version)
— both run from this repository.

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

## Deploying: Railway (free)

A different host, for anyone who wants one. Railway deploys this
repository straight from GitHub with a persistent volume — the
per-person files outlive restarts, and there is no shared scratchpad
for signed-in users. The app is a single container, so the Dockerfile
in this directory is the whole recipe.

Honest limits: the free plan is $1 of usage a month with no credit
card (a one-time $5 trial in the first 30 days), 0.5 GB of volume,
0.5 GB of RAM and a cold start when the service sleeps — the app is
fine on that for a personal archive, and the save-file download is
still the way to keep a permanent copy outside the host. The 13F
work runs off cache, so the monthly usage stays small.

```bash
# once you have a free Railway account and an API token:
railway login        # or: railway link with RAILWAY_TOKEN in the env
railway init         # pick the project, or create one
railway up           # builds from this Dockerfile
```

Then in the project's service settings: a **volume** mounted at
`/data`, and the environment variables the Dockerfile bakes in are
already correct (`LONGVIEW_VAULT=/data/longview.json` and friends).
The platform sets `PORT`, which the launcher reads. On deploy, open
the public URL, sign in, and keep your data in your own file —
and download the save file from Settings when you finish.

No Dockerfile hand-editing is needed: the image copies `app/` and
runs `uvicorn app.main:app` with `${PORT}` as the port. Python 3.12
is used (3.10+ supported); the free tier has no always-on worker —
a cold start wakes on the next request, same as the PythonAnywhere
free tier.

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

## Cloud backup (optional)

The per-person files live on the host's disk, which a redeploy or a
reset can wipe. The save file is one permanent copy; the cloud copy
is the other one. Each file is a few kilobytes, so a durable home
is cheap: a **private GitHub repository**, one file per signed-in
person, a commit per backup.

It is opt-in — the site operator sets two environment variables on
the instance:

```bash
LONGVIEW_BACKUP_REPO=owner/repo    # the private repo
LONGVIEW_BACKUP_TOKEN=...          # a GitHub token with contents:write
```

and a backup lands automatically after every save, at most once a
minute per person (an explicit "Back up to the cloud" button in
Settings forces one immediately). A failed backup never fails the
save; the Settings page says what happened. The token never enters
the bundle, the repo, or the response — the app sends it only to
api.github.com.

## Sign in with Google (optional)

The login card in Settings offers Google as a second way in, the
same identity story: one file per person on the host, downloadable
as plain text. It is not enabled by default — the site operator
sets two environment variables on the instance:

```bash
LONGVIEW_GOOGLE_CLIENT_ID=...        # from a Google Cloud OAuth client
LONGVIEW_GOOGLE_CLIENT_SECRET=...    # never committed, never in the bundle
```

and the flow is: "Sign in with Google" → redirect to Google →
callback to `/api/auth/google/callback` → the server exchanges the
code, verifies the token (via Google's own tokeninfo endpoint — no
JWT library), provisions or matches the account by Google's stable
`sub`, and signs you in with the same one-month cookie. A Google
account has no password: the password form simply never matches one.

For a Google OAuth client: Google Cloud Console → APIs & Services →
Credentials → Create credentials → OAuth client ID (Web application) —
redirect URIs are `https://<your-host>/api/auth/google/callback` (and `http://127.0.0.1:8010/api/auth/google/callback` for local self-host).

## Your data

Sign in once — or create a free account, or sign in with Google —
and everything you keep in the app lives in **its own file on the
host**: one per person, at
`data/users/<username>/longview.json`. The account file is small
and yours alone; signing out keeps the file, and signing back in
brings the same data back. Passwords are stored as PBKDF2-HMAC-SHA256
hashes; a Google account has no password to remember. Your browser holds a mirror of the file keyed by
your username; when you open the app the two compare and the newer
one wins. In Settings the file is in your hands:

- **Download the save file** — plain text, everything you own, for
  keeping a copy. It is not the importable format.
- **Download the JSON** — the data file: the one that round-trips
  through Import.
- **Import a JSON file** — puts a copy of your data back.

Sign in is the whole story for personal data. Anonymous use is still
fine for exploring: it keeps the one shared file at
`data/longview.json`, the one everyone sees — read it, play with it,
but sign in before you start keeping anything. The file is the
storage; the server just serves it.

The save file is plain text by design: no JSON, no markup, a readable
record of every section of your file — the portfolio (ticker, name,
shares, cost, date), your risk moves, every note page and its saved
pieces, your followed funds, your research reports (body capped to
keep the file readable), and the state of the economy tree.

## The hosted version

The public instance: **https://kirin123.pythonanywhere.com**.
No download, no install — anyone can open the URL in a browser and
use it. Sign in once and your data lives in its own file on the host. It runs this repository on PythonAnywhere
(free tier) as an ASGI site that serves the app directly, with no
Dockerfile, no database and no environment to set —
`requirements.txt` is the whole dependency story.

The instance ships without a model key, so its AI features run on
the key each visitor brings in Settings (sent per request,
relayed to the visitor's own endpoint, never stored).

Honesty list:

- **Cold start.** The free tier sleeps an idle site; the first
  request after a stretch of quiet can take 10–30 seconds while
  the app wakes. Repeat requests are fast — around a second.
- **One shared scratchpad for anonymous users.** A visitor who never
  signs in keeps the one shared file — read it, play with it, but
  everything anonymous lands in the same scratchpad, and the next
  anonymous visitor sees it. Signed-in users get their own file;
  signing in also migrates any anonymous data your browser holds
  into your account, once. If your work matters, download the save
  file from Settings when you finish (Import puts it back any time,
  on the same instance or on your own). To keep a permanent home
  for your data, run your own Longview (the four lines in Quick
  start) and import the file there.
- **Free tier storage.** Per-person files live on the same free
  disk as the app — capped at 512 MB in total, and the 100
  CPU-seconds/day budget is shared with the 13F work. Downloading
  the save file when you finish is the only way to keep a copy
  outside the host. There is no delete-account button yet: to
  remove a person's file, delete the folder on the host.
- **Outbound traffic goes through PythonAnywhere's proxy** (the
  free-tier site process cannot open direct connections). The
  app's proxy launcher sets that; SEC and Yahoo both answer
  through it.

To stand one up there yourself: clone the repository into your
home directory, create a virtualenv and install `requirements.txt`,
point an ASGI site's command at a small launcher that exports the
proxy and runs uvicorn (`uvicorn app.main:app --uds ${DOMAIN_SOCKET}`),
and reload. PythonAnywhere's free tier caps you at two consoles and
roughly 100 CPU-seconds a day — the 13F work mostly runs off
cache, but the directory build is the one job that leans on the
quota, so don't refresh it on a whim.

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
tests/              434 offline tests
data/               your data: one file (longview.json) holding every
                    section; created on first write, untracked
cache/              downloaded data (prices, filings, directory);
                    untracked
```

## Tests

```
.venv/bin/python -m pytest tests/ -q
```

434 tests, all offline: made-up prices, canned SEC-format XML, fake
filing indexes, and canned web responses. They never touch the
network, and none of them calls a real model.

## License

MIT. The filings belong to the public; the tool that reads them
should too. Fork it, self-host it, build your own.
