# Proof — plan and decisions

## What this product is

**Proof** turns investment claims into evidence. The tools share one
idea: don't take claims on faith — check them against real data.

- **Home** answers: "How is *my* portfolio doing?" You add what you
  own; each holding shows a live price (Yahoo Finance — free, no key),
  the week's move, its value, and your gain or loss — plus which of
  Proof's famous funds also hold the same company.
- **Backtest Lab** answers: "Would this strategy actually have worked?"
  You describe it in plain English, it runs against 5/10/20 years of real
  market history, and gets an honest verdict against buy-and-hold.
- **Smart Money** answers: "What are the famous funds *actually* doing?"
  Their SEC-mandated 13F filings, read and compared: what they hold, what
  they added or sold last quarter, where several of them are piled into the
  same stocks, and what new bet only one of them is making — all behind one
  filterable table an investor can query like a pro.
- **Economy** answers: "Where is the world's wealth actually held?" One
  static, rounded tree — about $470T at the end of 2024 — seven levels
  deep: six levels of asset detail, from real estate, cash and shares
  down to the kinds of houses, deposits and funds, then where in the
  world each piece sits. Each screen is a donut you can hover and click,
  with the same parts as a list beside it: share of the part above, the
  dollars that share works out to, and a growth rate you can tune.

## Why it changed

The earlier version of this project was a personal-finance helper (budget
leaks, spending radar, a "see ahead" morning brief). Decision, made with the
user: **scrap that type of idea completely.** The app should help investors
make better investments. Everything from that era (the "brain", "radar",
"see ahead" modules, that UI, those tests and docs) was deleted. The
`beacon/` folder name was kept as a working directory name; the product
itself is called Proof in all user-facing text.

## What's built and verified

| Piece            | Status |
|------------------|--------|
| Yahoo prices (free, no key) | Verified live: split/dividend-adjusted closes, 10-yr chunking, disk cache, 429 resilience (rotates hosts + browser User-Agents with backoff — the rate limit keys on the IP+UA pair) |
| Backtest engine (5 rules)   | Verified: offline tests, hand-computed values |
| English → strategy reader   | Verified offline; optional LLM path (env key); function words can't read as tickers, and words the five rules can't express earn an honest "I only tested the plain part" note on both paths |
| SEC 13F pipeline            | Verified live end-to-end on all 11 default funds: 21,925 holdings rows in the scan pool |
| 13F filer directory         | Verified live: 10,924 filers from the SEC's own daily filing index (last two quarters), 24h refresh, instant local search |
| Fund roster (editable)      | 11 defaults, persisted to `data/roster.json`; add any filer, remove any fund; every CIK verified against SEC's own submissions index, incl. the "twin CIK" traps (see below) |
| Smart Money scan pool       | Verified live: 12 filters, a One row per company toggle (summed worth, per-fund column hidden, click-into breakdown), 3 cross-fund rollups, one-line security lookup, CSV export — all exercised against the running server, all roster-aware |
| Web UI (landing + app shell) | Verified live in-browser: editorial research-desk redesign (serif display headings, hairline rules, squared chips, dense tables) at `?v=19`, landing door (staggered load-in → fade into the app), sidebar hash routing, 3-step Backtest wizard end-to-end (describe → run → results + chart), all four Smart Money subpages with staggered pane reveals, portfolio chat bubble, zero console errors |
| Multi-tab workspaces | Verified live: Company, Notes, Smart Money and the Lab each hold several open pages — add, close, reorder by drag, `@id` hash routes, strip persisted in `localStorage` (lab results in memory only); stale `@id` hashes and deleted note pages recover gracefully; duplicate labels get `· 2` numbering |
| Reverse DCF (implied growth) | Verified live: the Company "Value it" card solves for the FCF growth matching the market price (bisection; terminal growth 2.5% fixed, discount must exceed it) — AAPL implies 25.5%/yr at 8% over 5 years; offline math tests |
| Chat actions (open + run) | Verified live: the bubble answers in plain English and, when the message is a Smart Money lookup or a backtest request, opens the page and runs it — decided deterministically server-side (`_plan_action`), the LLM stays swappable via `PROOF_LLM_*` |
| Ask (plain-English Q&A)     | Verified offline (5 tests: quarter dedupe, missing funds, window moves) and live end-to-end with the local model: 1-, 2- and 4-quarter answers, plain English, numbers matching the data exactly |
| Yahoo quotes + search (free, no key) | Verified live: price + 1-week move from the 14-day chart (10-minute disk cache), company search ranked US-first; when Yahoo rate-limits us we serve the last known price, dated in the UI (one-week cap), never an error |
| Your portfolio (Home)       | Verified live: add (search-pick, bare ticker, or custom unlisted holding), edit in place, remove; purchase date on every position; real quote round-trip (price, week move, value, P/L); exchange-suffix resolution (VDST → VDST.L, CSPX → CSPX.L); one-currency view (USD/GBP/EUR/HKD/…) with partial totals and priced/missing counts; smart-money chip matched against the 13F pool; a rate-limited Yahoo shows the last known price, dated in the row's tooltip (one-week cap), instead of an all-dash row; **v25: total strip at the top of the page, every column sortable (state remembered), and gains over a chosen window (Cost / 1W / 1M / 3M / 6M / 1Y) from one 12h-cached year of price history per symbol** |
| Home glance (smart money)    | Verified live: three stacked tables — most crowded, biggest moves, new bets — from the cached scan pool |
| Notes (your notebook)        | Verified live: pages in `data/notes.json` (the portfolio's atomic envelope); write, rename, delete; a universal save sheet files any piece — an answer, a backtest, a fund move, a company — onto an existing page or a new one, deduped, with source + date; autosaves while you type |
| Company (detail pages)       | Verified live: price hero, market cap / P/E / EPS / dividend band, 1-year chart + returns, business facts from Yahoo's free endpoints (15-minute disk cache), and an adjustable DCF card (growth, discount rate, years → per-share and total value). The parser unwraps quoteSummary's `{"raw": …}` numbers, so the page no longer shows dashes while the chart works; every part still loads independently and the page fills in on its own |
| Portfolio chat               | Verified live against the local model: a bottom-right bubble that sees your saved holdings, the page in front of you, and your saved notes; 2–5 plain sentences, explicitly not advice |
| Risk (what the portfolio becomes if each holding moves) | Verified offline (23 tests): one hypothetical move per holding, clamped −99…+999, saved in `data/risk.json` (the portfolio's atomic envelope, whole-scenario save); each row reuses the portfolio's prices, FX and intervals, then adds the scenario figure; the measured number is the holding's own annualized volatility; the strip shows what the total becomes after all moves (same mixed-currency honesty as Home); "Fill with AI" posts the positions to the `PROOF_LLM_*` model and the client applies the plan — no key is a plain-English 503, blocked Yahoo is a dash |
| Economy viewer (global wealth tree) | Verified live (39 offline tests): a static, seven-level tree of world household wealth at end-2024 — about **$470T** per the UBS Global Wealth Report 2025 — 3,910 nodes, six authored levels of detail then a seventh that is always geography, every sibling set summing to 100, dollars and per-node growth derived from the stated total (world blended 4.6%/yr); projections at 5/10/15/20 years, rate tuning with the level's blend held, and an AI button that rewrites a level's list and saves it (resettable); each screen is a hand-built SVG donut (staggered sweep-in, hover lift, click-to-grow then drill) with a legend of share bar + % + dollars + growth, breadcrumbs, a back link and multi-segment hash routes; ten years of history per node (2015–2024, the reports' record where it exists, labelled assumed where it does not), a sparkline and vs on every row, and a 2–5-part compare page with an indexed chart and an AI read of it; no prices, no live data |
| Study (AI learning notes centre) | Verified offline (32 tests) and live in-browser: a reference corpus of ten comprehensively authored notes (1,651–2,003 words, 5–8 sections each, in `app/study_data/`) rendered through a strict escaped-markdown subset, listed as cards with reading time, deep-linkable per note; a bring-a-document card (gated on the LLM key) turns a pasted document into a saved, badged, deletable note via `POST /api/study/ai` (32,000-token / 300 s budget — measured against the resident thinking model) into `data/study.json`; plain-English 503/502/409/404 everywhere; live round trip exercised (2,700-char insurance doc → six-section saved note, survived a reload, deleted cleanly), zero console errors |
| Docs                      | This file + README rewritten in plain English |

### The five backtest rules

`buy_and_hold`, `sma_cross` (moving-average cross), `buy_the_dip`,
`momentum`, and `dca` (monthly fixed-amount investing, in real dollars).
Each is defined in `app/backtest.py` with a comment explaining it in
everyday terms, and each can be described in a sentence by the translator.

### The eleven default funds (the roster)

Berkshire (Buffett), Bridgewater (Dalio), D. E. Shaw, Tiger Global,
Citadel (Griffin), Renaissance Technologies (Simons), Pershing Square
(Ackman), Third Point (Tepper), Icahn, Coatue, Millennium.

These are the *defaults*. The list that actually gets scanned is the
**roster** — the defaults minus any you removed, plus anything you add
from the filer directory — persisted in `data/roster.json`.

(Greenlight — Einhorn — used to be here but stopped filing after Feb 2024;
user decision: every card must be current, so Icahn replaced it. He files
his personal 13F, "ICAHN CARL C", CIK 921669 — one filing per quarter,
verified via the SEC's full-text search index.)

Each CIK was verified against the SEC's own submissions index, and three
turned out to be "twin entity" traps where the famous name files under a
look-alike but different filer:

- **D. E. Shaw** — holdings come from *D. E. Shaw & Co., Inc.* (1009207);
  the L.P. entity (1009268) only files 13F-NT late notices.
- **Pershing Square** — the active filer is *Pershing Square Inc.*
  (2026053, filing every quarter through Aug 2026); the "GP, LLC" entity
  last filed holdings in 2013.
- **Coatue** — the active filer is *Coatue Management LLC* (1135730);
  "Coatue Capital LLC" has no recent holdings filings.
- (Citadel: the active filer is Citadel Advisors LLC, 1423053.)

Quarter-over-quarter diffs in the fund detail match on **CUSIP** (the
stable official identifier), falling back to normalized name. Without this,
a company that renames itself shows up as both "added" *and* "sold".

### The Smart Money tab, rebuilt (20 features)

The tab was rebuilt around one data structure: a **scan pool** — every
holding of every fund in the roster as a single table (~21,000 rows for
the eleven defaults), where each row carries the fund, the security, its
dollar value, its **weight** in that fund's book, its **asset class**
(stock / ETF / preferred / option), its quarter-over-quarter **status**
(new / increased / decreased / unchanged / exited), its **% change** and
**dollar move**, and its **crowding** — how many of the tracked funds hold
the same security this quarter. "Surprise" flags a new bet that no other
tracked fund shares. The pool is built once and cached on disk ~12 hours
(`cache/13f/_scan.json`); the filings it reads from are cached forever, so
rebuilding is free. The pool and the one-fund view both store a roster
fingerprint, so a roster change rebuilds them without re-hitting the SEC
for funds that were already read.

Two filing quirks are handled explicitly:

- **Amendments.** A 13F-HR/A restates the *same* quarter as the filing it
  amends (Citadel restated Q2 2026 in September 2026). The holdings table
  document is a bare table with no header, so each filing's reported
  quarter is read from its cover page (always the smallest XML in the
  folder — a few KB, fetched once, cached forever) and the "vs the prior
  quarter" diff compares against the most recent filing that reports a
  *different* quarter. Without this, an amendment would make "what changed
  this quarter" show the restatement's corrections, not a real quarter.
- **The quarter-end date** on every card comes from that same cover page
  (new-generation cover pages write `06-30-2026`; it's normalized to
  `2026-06-30`), so "as of" shows the true quarter-end, not the filing
  date — matching the fine print that dollar values are as of quarter-end.

The 20 features fall into three groups, matching the three UI blocks:

1. **Scan filters (1–12)** — search, include/exclude specific funds,
   minimum position size, minimum weight, minimum crowding, status,
   minimum dollar move, minimum % move, asset class, surprises only,
   and sort/order/limit. One code path (`funds.scan_query`) powers the
   table, the cross-fund rollups, and the CSV export.
2. **Per-fund cards (13–15)** — top-10 concentration, ETF share, and
   data-freshness (with an "old data" badge on stale filers like
   Greenlight), plus AUM, position count, and new/exit counts. Clicking
   a card toggles that fund in/out of the scan.
3. **Cross-fund views (16–20)** — a one-line "who holds X?" lookup, a
   crowding-shift tracker, a "new bets this quarter" rollup, a "biggest
   moves" rollup, and CSV export of the current view.

One deliberate semantic choice: an **exited** position keeps its
*previous* quarter's value (`prev_value`) as its "size" for filtering and
display ("was $X"), because a 13F only reports holdings — the size of a
sale is what they had, not the $0 they have now.

## Decisions (made with the user)

1. **The name stays "Proof."** Asked to confirm; the user answered "just
   name it NAME" — i.e. *you decide*. "Proof" it is (claims → evidence).
   One search-and-replace if they ever change their mind.
2. **Every card must be current.** "Everything needs to be active."
   Greenlight (Einhorn) stopped filing after Feb 2024 → **replaced with
   Carl Icahn** (CIK 921669, "ICAHN CARL C" — his personal 13F, filed
   every quarter; verified via the SEC's full-text search index).
3. **The LLM stays optional, user-supplied.** "Keep it so they can add
   their own model to it or connect an API." That's exactly how it already
   works: `PROOF_LLM_KEY` (any OpenAI-compatible endpoint, including a
   local model) + the built-in offline reader as fallback.
4. **The funds are *yours* to choose (built).** The user's call — and a
   better one than the candidates I proposed: **add your own funds** to
   the tracked list, with a **searchable directory of 10,000+ 13F filers**
   to pick from, and remove any tracked fund. Built and verified live;
   design in the section below. The "two tools talk" backtest-basket idea
   waits for after; live price-enrichment shipped with Home (decision 8).
5. **The UI is minimal: at most 100 words per subpage.** The user
   pushed back on the all-on-one-page layout ("it's still convoluted")
   and granted: *"you can organize and create subpages but maximum 100
   words per subpage."* **Counting basis, ruled by the user: live data
   does not count** — the budget covers only the app's own written copy
   (labels, notes, buttons, starter chips); company names and dollar
   figures are excluded. Measured written copy: **Landing 28, Home 79
   (portfolio) / 67 (smart money), Funds 12, This quarter 23, Holdings 88,
   Ask 91, Notes 38 (grid) / 43 (editor), Company 48 (search) / 55
   (detail)** (Backtest Lab steps 33 / 24 / 33) — every page is well
   under 100.
   The shell was rebuilt after the user said the old design *"feels way
   too AI generated and nothing professional"*: a fixed **sidebar** on
   the left switches every subpage — Smart Money (**Funds**
   `#money/funds`, **This quarter** `#money/quarter`, **Holdings**
   `#money/scan`) and Backtest Lab, which the user asked to become a
   **3-step wizard** — each step is one form page (**Strategy**
   `#lab/strategy` → **Setup** `#lab/setup` → **Results**
   `#lab/results`, numbered 1–3 in the sidebar) — and the content
   column is centered (860px). The look is a warm **beige/ivory theme,
   near-black bold type, one dark accent** (redesigned per decision 7;
   no gradients, no emoji). Density stays
   low: Holdings shows 3 of its 12 filters by default (6 in a collapsed
   "More filters"), the table is 6 columns defaulting to 10 rows, and
   fund cards are single lines. **Cache rule:** static files are served
   with `Cache-Control: no-cache` (a `NoCacheUI` middleware in
   `main.py`) and links are version-tagged (`?v=N` in `index.html`,
   currently v=19). Bump the tag whenever the UI changes, or browsers
   will keep serving yesterday's interface.
6. **Ask is a fourth Smart Money subpage** (built). The user's ask: a
   page where you ask a question — or tap a starter chip — and a
   language model answers from the 13F numbers, including across the
   past 1–4 quarters. Design in the section above. It reuses the
   existing `PROOF_LLM_*` variables, so no new setup is needed for
   people who already ran the translator's LLM path.
7. **Redesigned to feel like a real app (built).** The user's brief: a
   very simple **landing page — beige background, thick bold black,
   large centered text** — plus *nice clean animations throughout*.
   (Process per a design article they shared — Anshu Chimala on
   Lenny's: bold distinctive identity, cut what doesn't add value,
   remove AI tells, polish details.) Built: a full-viewport landing
   door (one small mark, one eyebrow line, the wordmark at ~150px /
   weight 800, one tagline, one button; Enter also enters) that fades
   out as the app fades in; a warm beige/ivory theme with near-black
   bold type across the whole app, the chart included; motion is
   staggered rise-ins on page and content switches, hover lifts on
   cards and chips, press feedback on buttons, all disabled under
   `prefers-reduced-motion`. Landing copy: 28 words. Static assets
   bumped to `?v=10`. Verified live: landing load-in, enter fade,
   every subpage, zero console errors; 67/67 tests still green.
8. **Home: your portfolio + smart money highlights (built).** The
   user's direction: Proof should help investors *strengthen their
   portfolio* — so the first thing they see is their own money, not
   the funds'. Home is the first sidebar item and the default route
   (`#home/portfolio`), with two tabs. This borrows WhaleWisdom's
   *functions* (tabbed glance views + data tables), never its look.
   - **My portfolio.** Add what you own: Yahoo search-as-you-type
     (free, no key; US-first, up to 8 matches) or a bare ticker,
     then shares, cost per share, and an optional note. Positions
     live in `data/portfolio.json` — the same `{v, updated, ...}`
     envelope as the roster, saved atomically; a missing or corrupt
     file is an *empty* portfolio, never an error. Each row: live
     price + 1-week move (Yahoo's 14-day chart, 10-minute disk
     cache), value, P/L vs cost, and a chip — which of Proof's
     funds also hold the company, matched on the normalized name
     with a trailing `DEL` token stripped (13Fs write "… INC DEL");
     lookalikes are rejected (Apple Hospitality ≠ Apple Inc.).
     Click a row to edit in place; a totals row sums value, P/L
     and % — and says plainly when it cannot (mixed currencies, or
     no live prices). When Yahoo is busy the price is a dash; the
     holding is never hidden, and a blocked quote is never an error.
   - **Smart money.** Three stacked glance tables from the cached
     scan pool — most crowded (≥2 of your tracked funds, by dollar
     value), biggest moves, new bets — plus a door to the full
     Holdings page.
   Verified live in-browser: add (search-pick and bare ticker),
   edit, remove, a real quote round-trip (BRK-B: price, +7.1% week,
   value, P/L, "4 funds" chip), all three glance tables, zero
   console errors. 25 new offline tests; the suite is 92/92 green.
 9. **Notes + Company: save anything, study one company (built).**
   - **Your notebook** — pages in `data/notes.json`, the same
     `{v, updated, ...}` envelope and atomic, locked save as the
     portfolio; a missing or corrupt file is an *empty* notebook,
     never an error. You write freely — a title and a body, autosaved
     0.7 s after you stop typing (and on blur or Cmd/Ctrl-S) — and
     the app can file things in for you: every piece of data — a
     backtest result, a smart-money move, an Ask answer, a company —
     has a **Save** button that opens one sheet: a preview of the
     piece, a pick of your pages, or a name for a new one. Only one
     sheet can be open at a time — a double-click used to stack two,
     whose page picks shared one radio group and silently cancelled
     each other (in-flight flag, verified by double-clicking). A
     saved piece is a snippet: its source (ask / backtest / money /
     company / other), a title, up to six lines of plain text, and a
     date; saving the same piece to the same page again is a no-op,
     and dash lines are dropped, so a rate-limited quote saves as a
     clean stub instead of a row of "—".
   - **Company** — a page per company, `#company/{TICKER}`, with its
     own sidebar item grouped with Notes. The quote, the size
     numbers (market cap, P/E, dividend, revenue, margins), the
     business profile (what they do, people, sector, hometown,
     website), a 1-year price chart, and the 1-month / year-to-date /
     1-year returns all come from Yahoo's free v8 + v10 endpoints,
     behind a 15-minute disk cache and the same never-500 rule: each
     part is independent, so a rate-limited module renders a dash
     and the page self-heals when the window lifts. The about-text
     clips at a sentence or clause boundary, never mid-word. The
     whole page saves to the notebook with one button.
    Verified live in-browser: notebook grid + editor (two seeded
   example pages kept as demos), the save sheet exercised from Ask,
   Backtest, Smart Money and Company, the double-click guard, a full
   AAPL backtest saved end-to-end, and the Company page while Yahoo
   was in a 429 window (dashes, zero errors, self-healed on refetch).
   Word counts: Notes grid 38, editor 43, Company search 48, detail
   71 — all under the 100-word rule. 37 new offline tests; the suite
   is 129/129 green. Static tag bumped to `?v=14`.
 10. **Holdings: a "One row per company" toggle — each company once (built).** The
    user's ask, in their words: *"only see each company ONCE, and the
    worth is the total sum of the investment put in by the funds, you
    can click INTO the company and see a detailed breakdown."* Built as
    a projection of the same pool, not a new endpoint: the twelve
    filters keep their per-position meaning, then the survivors are
    summed into one row per security (grouped on CUSIP, falling back to
    the normalized name), and sort/limit count *companies*. An
    aggregate row hides the per-fund column (so a company row cannot be
    read as one fund's position), shows the summed worth (a company
    everyone sold shows "was $X"), a net quarter move, and how many of the
    funds hold it; clicking the row unfolds its per-fund breakdown right
    under it (the breakdown ships with the row — no extra request) and its
    Save files a snippet with the total and up to four fund lines. Measured
    live: 9,168 companies from 21,925 holdings; the lede flips to say what
    a row means, and the count says "companies" instead of "match".
    14 new offline tests; the suite is 143/143 green. Static tag bumped to
    `?v=15`.
11. **Professional pass: an editorial research desk, and company numbers
    that actually load (built).** The user asked for a UI that reads
    professional, not "AI slop", keeping the warm palette; and allowed two
    deliberate repairs: copy that is easier for a person to follow, and the
    Company page, whose chart worked while every number showed a dash.
    - **The data bug.** Yahoo's `quoteSummary` wraps every number as
      `{"raw": …, "fmt": "…"}`; the old `_opt()` accepted only bare numbers,
      so price, ranges, cap, P/E, EPS, volume, margins and earnings all
      became null. `_opt` now unwraps `raw`, `_pct` prefers the `fmt`
      percent string, and the merge maps the current module shapes
      (`summaryDetail.fiftyTwoWeekLow/High`, `price.regularMarketDayLow/High`
      and `marketCap`, `defaultKeyStatistics.trailingEps`,
      `calendarEvents.earnings.earningsDate`). The legacy bare-number
      dividend keeps its old percent meaning. One regression test; the
      suite is 144/144 green.
    - **The look.** Same palette; an editorial financial-report geometry:
      serif display headings (Iowan/Palatino/Georgia), sans body, hairline
      rules, 3–4px radii, squared chips and buttons, uppercase letterspaced
      labels, dense tabular tables, no hover lifts or floating shadows. The
      landing keeps one mark and one door.
    - **Clearer copy.** Sidebar **Scan → Holdings**; a heading on every
      money subpage; **Worth → Value**; "Aggregate" → **One row per
      company**; quarter cards get one-line captions; Company detail is
      rebuilt as a price hero, a four-cell stat band (market cap, P/E, EPS,
      dividend), a labelled 1-year chart with returns, and three fact cards
      (today's trading, 52-week range, the business), with `abbr`
      explanations for P/E and EPS.
    - **Measured written copy:** Landing 28, Home 83/67, Funds 12, This
      quarter 23, Holdings 88, Ask 91, Notes 38/43, Company 21/47, Lab
      33/24/33 — every page under 100. Static tag **v=16**; verified live
      across every route with zero console errors.
12. **Yahoo gaps, one-currency portfolios, custom holdings, chat, DCF
    (built).** The user asked why some holdings showed no Yahoo data, for a
    standard-currency view whose total still shows when rows are dashed, for
    unlisted investments (purchase + current price), purchase dates, a local
    AI chat bubble, and an adjustable discounted-cash-flow card.
    - **Why data went missing.** Two causes, both now handled. First, bare
      UK/European tickers need their exchange suffix — `VDST` is `VDST.L`,
      `CSPX` is `CSPX.L` — so a failed chart fetch now searches Yahoo and
      accepts only the same base symbol with a matching saved name
      (`_resolve_symbol`), then retries once; the resolved symbol rides back
      on the quote. Second, Yahoo's chart endpoint rate-limits (HTTP 429)
      from this IP; the existing host/UA rotation still applies and a
      blocked quote stays a dash, never an error. Genuinely unlisted things
      (a private fund) are now custom holdings instead. Live check: all 11
      saved positions price, with VDST and CSPX resolved.
    - **One currency, honest totals.** A "Show in" picker converts price,
      value, P/L and cost through Yahoo FX charts (`EURUSD=X`, inverse
      fallback), cached hourly. Native numbers stay on the row for editing;
      `display_*` carries the converted copy. Totals sum every row that
      priced and report `priced` / `missing` rather than refusing to total;
      a missing FX rate leaves its row dashed, never invents a number.
      Native mode keeps the old mixed-currency guard.
    - **Custom holdings + purchase dates.** `kind="custom"` gets a generated
      `CUSTOM-*` ticker, manual current price and currency, purchase price
      (`cost_basis`), shares, note, and an optional ISO purchase date. The
      table has a Bought column; the form and inline editor collect it.
      Custom rows never call Yahoo and have no company-page link.
    - **Chat bubble.** Bottom-right on every page, posts to `/api/chat`
      with the same `PROOF_LLM_*` model as Ask. The model sees only a compact
      snapshot of saved positions (no live fetching), answers in 2–5 plain
      sentences, invents no prices, and says it is not advice.
    - **DCF.** The Company page gains a "Value it" card: projected free cash
      flow at an adjustable growth rate, discounted at an adjustable rate
      for adjustable years, plus a 2.5% terminal value, cash, debt, and
      shares. Per-share and total value update as you type. Yahoo supplies
      FCF, shares, cash, debt, revenue growth, and reporting currency.
    Verified live: 11/11 priced; USD/GBP/HKD totals (e.g. USD 6,770,525);
    custom add/edit/remove with a 2024 purchase date; DCF per-share moves
    from $198.02 at 8% to $110.87 at 12%; chat answered in ~9 s; zero console
    errors. 13 new offline tests; the suite is **157/157 green**. Static tag
    **v=19**. Measured Home copy 79 words, Company detail 55.
13. **Multi-tab workspaces, a reverse DCF, and a chat that acts (built).**
    The user asked for several open pages at once (two companies, a fund
    and a backtest side by side), for the DCF to answer "what growth does
    the *price* imply?", and for the chat to actually open things.
    - **Tabs.** Company, Notes, Smart Money and the Backtest Lab each
      became a tab strip above their content: `wsRender`/`wsActivate`/
      `wsClose` in `app.js`, stable IDs (`<kind>-<seq>`), hash routes
      `#<kind>/@<id>` (the lab appends its step: `#lab/@lab-2/results`).
      Per-tab state lives in memory; the strip (tabs, titles, per-tab
      inputs, active tab) persists to `localStorage` under
      `proof-ws-{company,notes,money,lab}` — **lab results stay in memory
      only** (a 20-year daily series is too big for the storage quota; the
      inputs survive a refresh, the numbers don't). Repeating labels get
      `· 2`, `· 3` numbering; the first stays plain.
    - **Reverse DCF.** The Company page's "Value it" card gains a second
      mode, *Implied growth*: discount rate, years, terminal growth
      (fixed 2.5%), FCF, cash, debt and shares all lock to the company;
      the card solves for the FCF growth whose present value equals the
      current price (bisection in `dcf.js`; the discount must beat the
      terminal growth, else the math is meaningless). Verified live:
      AAPL implies 25.5%/yr at an 8% discount over 5 years.
    - **A chat that acts.** The bubble can *do* things. The server
      decides deterministically — `_plan_action` in `main.py`, keyword
      rules, not the model — whether a message is a Smart Money lookup
      or a backtest request; if so, the answer carries an `action` and
      the frontend opens a new page and runs it. The bubble still answers
      in plain English and says it's not advice; the model stays
      portfolio-context only, so a question about a backtest tab is
      answered from the portfolio, not the lab.
    - Suite **166/166 green**; static tag **v=20**; verified live (tab
      add/close/reorder, chat → new page, implied growth) with zero
      console errors.
14. **The stale-tab robustness pass (built).** After the release, the
    chat → backtest flow was reported as "doesn't work". Root cause,
    confirmed in the server log and the browser: the app is used in two
    windows of one origin, and they share one `localStorage`. A hash
    naming a tab the other window had closed, a restore that ignored the
    saved active tab, and 304-cached old `app.js` made the page look dead
    while the server ran everything correctly (every chat, translate and
    backtest POST returned 200). Fixes:
    - **No ghost tabs.** A hash can name a tab that no longer exists
      (closed here, or in the other window). `wsStaleFallback` falls back
      to the current page and quietly corrects the address with
      `history.replaceState` — it never invents a tab for a ghost id.
    - **Restore where you were.** `wsRestoreAll` comes back to the saved
      active tab when it still exists, not always tab one.
    - **Deleted note pages** (from the other window) show a plain "This
      page no longer exists" and a Close button, not a raw 404.
    - **In-flight lab runs write only to their own tab.** `runLab` guards
      every DOM write with `WS.lab.active === tab.id` and remembers
      `tab.running`; `showLabTab` re-derives the status line from tab
      state ("Done." / "Still running…" / cleared), so switching away and
      back always shows the truth.
    - **The status line actually writes.** `labStatus()` overwrote the
      element's `className` and dropped its own selector class, so every
      call after the first was a silent no-op. It keeps the class now.
    - **The summary matches the run.** The "what I understood" line named
      a ticker found in the words (default SPY) while the form's ticker
      applied afterwards — a line could read "Buy SPY…" over an AAPL
      chart. The form's ticker now rides in the translate request and is
      used when the words name none (a ticker in the words still wins).
      Three new translator tests.
    - **Honest empty state.** A lab tab after a refresh shows its saved
      inputs plus one line: results don't survive a refresh.
    - Static tag **v=21 → v=23**; suite **169/169 green**. Verified live
      on a fresh load: chat "backtest buy the dip on AAPL for 5 years"
      opens a new page, runs to results, and its summary says AAPL; a
      mid-run tab switch stays clean; a ghost `@id` hash and a deleted
      note page both recover gracefully; zero console errors.
    - Measured written copy (app words only: numeric tokens, live data,
      tables and tab strips excluded) — every subpage stays under the
      100-word budget: Landing 28, Home/portfolio 68, Home/money 50,
      chat 13, Funds 10, This quarter 23, Holdings 72, Ask 63, Lab 86,
      Company 66, Notes 3.
15. **Reader honesty, an Ask that can see, and the stale-tab zeros (built).**
    Three reports after the release: the lab's "What I understood" card
    read "Buy BUT and never sell" for a sell-into-dips idea (and the
    verdict contradicted what was said); the Ask bubble on a company page
    answered "I don't have a description of Microsoft"; and the Smart
    Money tables showed 0 / 0 / 0.0% in every row while the rollups
    beside them were correct. Fixes:
    - **Function words can't be tickers.** ~33 common English words (but,
      is, never, everything, reinvest, compared, beat, …) could
      masquerade as symbols in the reader's ticker scan. They're in the
      stopword list now, so the user's text reads "Buy SPY and never
      sell" — never "Buy BUT…".
    - **The card admits what it tested.** When a description mixes
      sell-into-dips / buy-back words with a rule the engine can't
      express, the reader adds one italic line ("You also described
      selling into dips and buying back — I only tested the plain
      buy-and-hold part of your idea") and downgrades high → medium
      confidence. The annotation runs on *both* paths, rules and LLM.
    - **The LLM path actually worked again.** `_validate_llm` referenced
      a `symbol` that was never passed in; the `NameError` was swallowed
      by its `except Exception`, so every model answer was silently
      rejected and the "language model" source was never real. It's
      passed now — and the translator's `max_tokens` went 300 → 800,
      because the thinking model behind it spends the budget on reasoning
      first: simple inputs answer in 1–3 s with valid specs, while the
      long strategy still over-reasons and falls back to the now-honest
      rule reader.
    - **The Ask bubble sees the page and your notes.** The request
      carries a brief of the open page (company: name, price, market cap,
      P/E, about; lab: the strategy text + verdict; money: the subpage)
      and up to ten saved notes, newest first (titles + trimmed bodies).
      Verified live: "what is this company?" on the MSFT page answers
      from the page — name, business, price, market cap — and a notes
      question quotes the saved Apple backtests. The LLM stays swappable
      via `PROOF_LLM_*`.
    - **The verdict tells the truth for identical lines.** A pure
      buy-and-hold backtest's two lines overlap exactly, so the verdict
      says that ("both made +303.9% on the same thing") instead of
      "doing nothing won"; and "Over 10" gained its missing unit ("Over
      10 years").
    - **The zeros were your tab, not the data.** The screenshots came
      from a pre-redesign client: its holders table, its "Total value /
      QoQ change / % of fund" headers, the chart legend chips, and the lab
      line on a money page exist in no current file (grep-verified). The
      current client renders real values everywhere — holdings $66.0B /
      +14% / 6 funds; quarter rollups $3.3B / +$28.6B / 0→7 — and the
      server rows carry exactly the fields it reads (`value`, `change`,
      `n_funds`). A hard reload (⌘⇧R) in the old tab is the fix; the
      data was never wrong.
    - Static tag **v=23 → v=24**; suite **169 → 181 green** (5
      translator, 6 chat-context, 1 verdict). The lab's note line and
      the verdict are server-generated copy, so the 100-word static
      budgets measured in decision 14 are unchanged.

### The directory + custom roster (built)

- **Directory snapshot** — `app/directory.py` crawls the SEC's *daily
  filing index* (`daily-index/{year}/QTR{n}/master.YYYYMMDD.idx` — the
  same pipe-separated index EDGAR publishes), the last two quarters
  (~85–90 small files), keeps the 13F-family forms, and dedupes by CIK
  keeping each filer's most recent holdings filing (a 13F-NT "not filing"
  note loses to a 13F-HR on the same day). Caches to disk with a 24h TTL;
  search is then an instant local string match, and each entry shows its
  most recent filing form + date so you can see it's alive.
- **Active roster** — the eleven defaults (minus any you removed) plus
  your additions, persisted to `data/roster.json` — a real data file that
  a cache refresh never touches. Adding a filer whose newest 13F is a
  "not filing" note, or whose last real filing is a year old, is refused
  in plain English — every roster fund must be current.
- **Everything downstream is roster-aware** — the scan pool, the three
  rollups, crowding ("how many of *your* funds hold this"), surprise, the
  security lookup, and the CSV export all compute over the *active*
  roster, so adding a rival quant or a family office changes the answers
  honestly. The pool cache stores a roster fingerprint and rebuilds (from
  the forever-cached filings — no network) whenever the roster changes.

### Ask: a language model over the filings (built)

The fourth Smart Money subpage (`#money/ask`). The user asks one question
in plain English — or taps a starter chip — and a language model answers
in plain English, using *only* the numbers Proof read from the 13Fs.

- **The model never sees the filings** — only the compact JSON that
  `funds.ask_data()` builds: per fund, each window quarter's total and
  holding count, with the top-6 names on the window's newest and oldest
  quarters (middle quarters keep only their totals — that's what a person
  reads first); across funds, the biggest additions and sales over the
  window (CUSIP-matched) and the newest names. The system prompt forbids
  inventing numbers and forbids markdown. The model does the talking;
  the code does the math.
- **The look-back is 1–4 quarters** (a "Look back" dropdown).
  `fund_history(fund, n)` reads a fund's `n` most recent *distinct*
  reported quarters, newest first — an amendment (13F-HR/A) collapses
  into the original's slot, so the window never compares a quarter
  against itself. A single-quarter window fetches one extra quarter as
  the base to measure the move against.
- **The LLM is the same opt-in as the backtest translator** (decision 3):
  `PROOF_LLM_KEY` / `PROOF_LLM_BASE` / `PROOF_LLM_MODEL` point at any
  OpenAI-compatible server, local or cloud. Without a key, the Ask page
  says so in one sentence instead of failing silently.
- **Budgets are Ask's own** — the model behind the default setup is a
  *thinking* model: its reasoning counts against the output budget.
  Measured: the full 11-fund data block made it spend all of 4000 tokens
  on thinking and return an empty answer, so the data block is kept to
  ~4K prompt tokens and the budget is `max_tokens` 8192 (the
  translator's 300 would cut the answer off mid-thought). Answers take
  1–2 minutes, hence the 180-second HTTP timeout.
- The answer card shows the question, the answer, and one line of facts:
  how many funds were read, the window dates, and how long it took. A
  fund that couldn't be read is named in a note, never silently dropped.

16. **The portfolio: total on top, sortable columns, and gains over time
    (built).** Three asks in one round: "move the portfolio total to the
    top of the page"; "make the table columns sortable"; and "also make
    it so you can see the gain or loss in the portfolio over a time
    interval — one week, month, etc."
    - **The total is the first thing on the page.** A strip under the
      lede (serif, one ink rule) shows the portfolio's total worth and,
      beside it, the gain for the chosen window ("Total $6.8M +$37,517
      (+0.6%) over 1 month"). The old bottom totals row is gone. A mixed
      currency still reads "Total —" with the "currencies don't add up"
      tooltip — the strip inherits the main total's honesty.
    - **One year of history per symbol, fetched once.** Each listed
      holding gets a ~400-day split/dividend-adjusted series from the
      new `market_data.price_series()` (12h disk cache, the same file a
      one-year lab backtest uses, so portfolio and lab share history).
      Five windows are derived from it — 1W 7d, 1M 30d, 3M 91d, 6M 183d,
      1Y 365d, calendar days back from the most recent close, taking the
      last trading day *on or before* each cutoff, so a holiday week
      doesn't change what "1 month" means. Both ends of a window come
      from the same adjusted series, so a dividend en route doesn't dent
      the number. Custom holdings have no history; a quote that already
      failed skips the fetch entirely (don't double-burn a busy Yahoo).
      Any window with no bar is a dash, never a guess.
    - **The window is a picker, not a refetch.** Six chips in the
      toolbar (Cost / 1W / 1M / 3M / 6M / 1Y). The server always sends
      every window with every row, so switching repaints locally in a
      frame — the P/L column, its header label, the strip, and the sort
      all follow the window. The choice is remembered.
    - **Every column sorts on click.** Company, Price, Value, P/L,
      Bought, Smart money. Clicking a header sorts the rows already on
      screen (no refetch); clicking again flips direction; a ↑/↓ marks
      the active column; unpriced rows stay at the bottom either way.
      State is remembered as `column:direction`. Handlers are scoped to
      the headers, so row-click editing and the remove buttons are
      untouched.
    - **The `.L`-suffix bug, found and fixed.** End-to-end, CSPX and
      VDST returned all-dash intervals while their quotes worked: the
      quotes resolve the exchange suffix (VDST → VDST.L via search) but
      `fetch_history` re-normalized and *stripped* it, so the history
      re-fetch 404'd on the bare ticker. `fetch_history` gained a
      `normalize=False` path (symbol as-is) and `price_series` uses it:
      a symbol Yahoo already resolved is exactly the symbol that works.
      After the fix both show real gains (11/11 rows, 11/11 intervals);
      three regression tests.
    - Verified live on a fresh load (static tag **v=24 → v=26**; the
      25→26 bump lands the final fineprint wording past the browser
      cache): strip renders, chip
      switching repaints strip + column + header label (and only
      those), all six sorts order correctly with nulls last, row-click
      edit → cancel is intact, the multi-currency view still dashes the
      total, zero console errors; the user's real tabs still run the old
      client — a plain reload now pulls the new assets (the `?v` URL
      changed), ⌘⇧R if in doubt. Suite **181 → 191 green**
      (7 interval tests, 3 suffix tests, 1 suite guard). The portfolio
      static copy measures 96 words by the strict count (every label,
      option, placeholder, chip, and strip word; live data, tables,
      tab strips and numeric tokens excluded) — under the 100 budget;
      decision 14's looser convention would measure less.

 17. **When Yahoo is blocked: the last good number, dated (built).**
     Report: "the vanguard stopped loading" — while the other ten rows
     kept showing prices, the Vanguard row went all-dash.
     - **The root cause was a thrown-away number.** Yahoo rate-limited
       our IP (a ~25-minute 429 burst). `quote()` worked like this: cache
       newer than 10 minutes → serve it; older → refetch, and a failed
       fetch → nothing. The Vanguard's cache entry was 19 minutes old at
       the moment the block hit, so the row earned a dash while the ten
       neighbours' entries happened to be 2 minutes old. The last good
       price was on disk; the code discarded it.
     - **The fix dates the fallback instead of discarding it.** A failed
       fresh fetch now serves the last cached quote, up to a week old,
       flagged `stale`. The price cell's tooltip says "last seen
       Nov 6" rather than "live" — a number you can tell apart from a
       fresh one, never a blank. Only a week of total silence earns the
       dash, so the fineprint ("a dash means no data") stays true.
     - **The same pattern for the other two dash paths.** The interval
       columns read `price_series()`, which now serves the last good
       history file (≤ 1 week) when its fetch fails — daily closes change
       once a day, so a day-old file is usually the very data a fetch
       would return. And `fx_rate()` serves the last known rate, and
       stopped overwriting a good cache file with *no* rate when a fetch
       failed — that overwrite was a latent bug: one 429 burned a good
       rate off disk for a day. `fetch_history()` itself still raises:
       the lab's backtests would rather fail loudly than run on stale
       numbers; only the portfolio's interval path softens.
     - Verified: five new offline tests plus one portfolio test (suite
       **191 → 197 green**); an in-process check with Yahoo's chart
       fetch disabled returned the real cached VDST price flagged stale,
       its 276-bar history, and a live FX rate; the running server
       answered 11/11 priced after restart; a fresh tab on the new client
       rendered all rows with zero console errors. Static tag
       **v=26 → v=27**; the user's existing tabs need only a plain
       reload to pick the new client up (⌘⇧R if in doubt).

 18. **Risk: what the portfolio becomes if each holding moves (built).**
     The user asked for a risk-analysis page on the saved portfolio.
     - **One move per holding.** A hypothetical price change in percent,
       clamped to −99…+999 (outside that the number stops meaning
       anything), typed into its row or picked by the model. The
       scenario is the user's data, saved in `data/risk.json` — the same
       `{v, updated, moves}` envelope as the portfolio, written
       atomically, one save per whole scenario (the client sends every
       row; out-of-range values clamp, junk is dropped, never an error).
       A missing file or a missing entry reads back as 0 — the holding
       that did not move.
     - **The rows are the portfolio, plus the scenario.** Each holding
       reuses the portfolio's enricher — the same quotes (10-minute
       cache), the same 400-day series (12-hour cache), the same FX
       rules, the same staleness honesty — and gains its move, its
       scenario figure (`value × (1 + move/100)`), its scenario delta,
       and one measured number: the holding's own **annualized
       volatility** (daily returns, sample standard deviation, scaled by
       √252; fewer than ~20 closes is a dash, never a number that looks
       precise). Custom holdings have no exchange history, so their
       swing is a dash.
     - **The strip.** What the total becomes after *all* the moves, with
       the change versus today and the value-weighted swing. The
       mixed-currency rule is the portfolio's: without a chosen display
       currency the total only sums when one currency, and the "Show in"
       picker converts through Yahoo's FX charts like Home does.
     - **Fill with AI.** One button posts the positions — ticker, name,
       size, 1-year return, typical swing, weight — to the `PROOF_LLM_*`
       model, which returns one plausible move per holding (the prompt
       asks for moderate moves and only the JSON table). Nothing is
       saved on receipt: the client applies the plan and the user edits
       whatever they disagree with before the save fires. No key is a
       plain-English 503; a model failure is a plain-English error. The
       chat bubble fires the same fill ("do the risk fill" — the word
       boundary keeps "risky" out of it).
     - Routes: `GET /api/risk` (with `?currency` / `?refresh`), `POST
       /api/risk` (the whole scenario), `POST /api/risk/fill`. 23 new
       offline tests.

 19. **Economy viewer: where the world's wealth is held, seven
     levels deep (rebuilt twice).** Three asks, in the user's words:
     *"make another section called economy viewer, where you see what
     part of the total economy is held in where, i.e., stocks,
     commodities, banks, cash, etc. what's following, and within each
     category you can see its sub categories"*; then, after living with
     it: *"i don't understand how the economy part works, why is there a
     price to the economy and what does that mean. shouldn't it be total
     share and total wealth in assets. I also want to see a pie chart
     interactive that has smooth animations. also this shouldn't be only
     for US but global."*; and finally: *"increase the depth to 7, and
     add even more specificity… there should be an AI update feature
     where the AI updates and finishes the list, it should be quite
     comprehensive… there should be predictions of growth and manual
     tweaking of rates to see the impact… there should also be balancing
     so comparing typical total wealth growth, and increasing one rate
     to see how much the other decreases."*
     - **Why there was a price at all.** The first version put one
       liquid fund beside each slice (VNQ for real estate, SPY for
       stocks, …) and showed that fund's share price and 1W/1M/1Y moves.
       It was never the price *of* the economy — it was a stand-in for
       "how is this part doing", and it read as a non-sequitur. Removed:
       there are no prices, quotes, or live sources anywhere on the
       page now.
     - **The picture is global, and static.** Total household wealth at
       the end of 2024, **$470T** (UBS Global Wealth Report 2025: $470.5T
       across 56 markets). Top level, shares summing to 100: real estate
       52, insurance & pensions 18, cash & deposits 13, equities 11,
       bonds & loans 4, gold 1, crypto 1 — i.e. the published 52
       non-financial / 48 financial split, and the dollars ($244T, $85T,
       $61T, $52T, $19T, $4.7T, $4.7T) are derived from the total.
       Branch splits follow sector research rather than invention:
       residential ~70% of real estate (OECD expert group on household
       wealth; ECB for Europe), bank deposits 72% of cash, pensions 65%
       of insurance (WTW/Thinking Ahead: $58.5T in the 22 biggest pension
       markets), large companies 40% of equities, government 55% of
       bonds (most bonds are held by banks and funds, not households —
       BIS/SIFMA), coins & bars 65% of gold (~45,000t of investment gold,
       World Gold Council), Bitcoin 60% of crypto (CoinGecko, ~$3.5T
       market). Deeper levels are illustrative splits of the same kind.
     - **Seven levels, every branch.** 3,910 nodes: the root, then 7 +
       25 + 67 + 156 + 324 + 666 tiers of detail, then 2,664 leaves that
       are all geography. The detail tiers go deeper where the research
       allows — kinds of homes, kinds of funds, kinds of bonds and
       deposits — and the seventh level is always the same four regions,
       from UBS's regional wealth figures: United States & Canada 39%,
       Europe 25%, China 21%, Asia-Pacific & rest 15%, attached to every
       bottom branch, with per-branch overrides where a branch is known
       to skew. Every sibling set sums to 100, every branch runs to the
       seventh level, fan-out two to five (the root seven), and
       `validate_tree` re-checks all of it on every load. The tree lives
       in its own module (`economy_tree.py`) as nested `n(name, share,
       *children, note, g, regions, rg)` calls so the numbers read like
       prose; `economy.py` only turns it into views.
     - **Growth, the new column.** Every node carries a nominal percent-
       per-year rate. The root anchors at 4.8 — UBS saw real household
       wealth grow 3.4%/yr since 2000 and projects close to 5%/yr for
       the rest of the decade. A leaf gets an authored rate where the
       long-run record supports a specific number, otherwise it inherits
       its parent's; every internal node then blends its children by
       share, so the whole world works out at a 4.6%/yr blend. The
       regions differ by design: a regional leaf carries a *tilt* (the
       region's growth minus the branch's) rather than an absolute rate,
       so the branch's own authored rate still shows while United States
       & Canada outgrows Europe.
     - **Predictions, and tuning with balancing.** A horizon strip
       (5/10/15/20 years) projects the level and every row: the page's
       only forecast is `value × (1 + g/100)^years` — plain compound
       arithmetic on a rate the reader can see. "Tune rates" turns each
       row's rate into an input; "Hold this level's growth" (on by
       default) is the balancing ask — moving one rate spreads the exact
       counter-move across the other siblings, sized so the level's
       share-weighted blend does not move; at the top of the tree that
       holds the world's growth. Off, the one rate moves alone, and
       "Reset rates" puts a level back to its saved numbers.
     - **The AI keeps the list current.** "Finish this list with AI"
       appears on the sixth displayed tier (five path segments down)
       when a `PROOF_LLM_KEY` is set: the model — the same swappable
       `PROOF_LLM_*` env the Risk page uses — proposes two to five
       replacement children for that list, each with a name, a share, a
       growth and a plain-English note. The answer is validated strictly
       before it touches the tree: two to five usable rows, unique
       slugs, no child may reuse the parent's name, shares rounded to
       whole percents that sum to 100, growth within −5…25. A usable
       answer replaces the list, gets the branch's geography attached,
       is re-blended, saved atomically to `data/economy_tree.json`
       (`PROOF_ECONOMY_TREE` moves the file) and returned with the
       refreshed view; an unusable one changes nothing (a 502 in plain
       English). `POST /api/economy/reset` forgets saved edits and
       restores the authored tree, after which the page offers "Undo
       saved AI edits"; no key at all is a 503 that says so. Verified
       live against the local model — it rewrote a detached-houses list
       into four children, the save round-tripped, and the reset brought
       the authored tree back.
     - **The donut.** One SVG ring per screen, a `<path>` per child, no
       library: slices sweep in staggered (90 ms apart, 700 ms each,
       cubic ease-out), a hovered slice grows 6px outward and the middle
       of the ring switches to that child's dollars and share, and a
       click grows the chosen slice into a full ring before opening it
       (560 ms, so the response is visible). The legend beside it is the
       same data as text: colour dot, name, share bar, percentage,
       dollars. Leaf rows dim and stop being clickable; the rows are
       keyboard-reachable (Tab + Enter).
     - **Drilling is client-side.** The whole tree arrives once, so a
       click re-renders from memory with no request. The hash carries the
       path (`#economy/real_estate/residential/own_homes/family_houses`),
       breadcrumbs are walked from the local tree, a back link names the
       parent it returns to, and a hash one level too deep truncates to
       seven segments — a hash that names nothing quietly resets to the
       world instead of showing an error.
     - Routes: `GET /api/economy` (the world, with every subtree
       embedded) and `GET /api/economy/{path}` for a spot, with
       plain-English 404s — an unknown part, and "The wealth tree is
       seven levels deep — this address is one past the bottom."
     - **Three bugs found by checking it rather than assuming.** The
       animation engine was cleared when it went idle, so a click after
       the sweep-in did nothing (now the engine idles instead of
       vanishing); the back link named the *current* node because it
       walked the path including the last segment (now the parent); and
       `_view_node` appended the parent's key when building child paths,
       so every drill address repeated itself (caught by the round-trip
       test).
     - **Smaller on the wire.** The whole tree is the page's payload; at
       3,910 nodes that is 1.24 MB of JSON. A `GZipMiddleware` brings
       the one-time fetch to about 80 KB.
     - Suite **242 → 263 green** (39 economy tests: shape and level
       sums, geography on the seventh level, the growth blend and the
       regional tilt, the projections, the strict child validation,
       update / persist / reset against a sandboxed file, the routes,
       the 404s and the 503). Static tag **v=30 → v=31**; open tabs need
       a plain reload, ⌘⇧R if in doubt.
20. **A decade of history on every node, and a compare page (built).**
    One ask, in the user's words: *"include data from the past 10 years,
    and let there be graphs showing each one's growth according to
    whatever categori or level of category its one. allow the option to
    compare one category with another, or a specific thing within a
    category with another. let the Ai do this by opening a new page for
    you to view etc as part of the economy section."*
    - **The decade is real where the reports are real.** A new module
      (`economy_series.py`) holds the UBS Global Wealth Reports'
      56-market sample, 2015–2024: the world's own record
      ($285.2T → $470.5T, +5.7%/yr) and the four regions — 2023 and 2024
      anchored to the reports' actual figures (US & Canada $174.7T in
      2024, Europe $110.0T, Greater China $101.0T, the fourth bucket the
      residual), earlier years grown back from the reports' published
      CAGRs. The regions' *shares* in the tree were re-anchored to the
      same 2024 actuals (37 / 23 / 21 / 18); their forward growth stays
      as authored. The ten-year record and the shares are two labelled
      numbers that agree in 2024.
    - **Every node has a ten-year chart, computed by the page.** The
      server sends one series bundle (years, world, four regions); the
      page picks the shape a node deserves — the world's, where no
      market record exists below the total (level one); the node's own
      growth, back-computed from its 2024 value (deeper levels, labelled
      "assumed"); or its region's record (geography leaves, where the
      reports publish one). Every chart ends exactly on the node's
      displayed value, so tuned rates re-shape history for free, and no
      per-node series ever travels over the wire.
    - **The decade panel.** Above the projection strip: an area chart —
      "$285T in 2015 → $470T in 2024 · +5.7%/yr over the decade" — with
      a one-line basis (*the world's own record* / *assumed: this
      growth rate* / *geography: measured where the reports publish it,
      modelled in between*) and a vs button. Every row gains a 64 px
      sparkline and a vs button of its own (the row widens to nine
      columns).
    - **Compare: 2–5 parts at any level.** The vs buttons feed a slim
      tray under the tree; *Compare →* opens a workspace page inside
      the section: all picks indexed at 2015 = 100 on one chart, a table
      per pick (share of all, today, growth, decade CAGR, end-2024, path
      and basis under the name), *Ask the AI to read this*, and a back
      link to the tree. Picks cap at five (a sixth is refused in a
      toast) and dedupe by canonical path; a fresh user gets one blank
      compare tab, which shows the tree. The page keeps an address
      (`#compare/@compare-N`), and a deep link on a fresh page fetches
      the tree its chart is arithmetic of, saying so while it waits.
    - **The AI reads the comparison.** The button posts the same series
      the chart draws to the swappable `PROOF_LLM_*` model and shows
      the read with the model's name and a *Re-ask*. Measured: the local
      thinking model spends a 4,000-token budget entirely on reasoning
      and answers empty, so the read gets 8,000 tokens and a 180 s
      clock; if it still runs out of room the page shows a plain-
      English note and the chart stands alone. No key means no button.
    - Suite **263 → 279 green** (55 economy tests). Static tag
      **v=31 → v=34**; open tabs need a plain reload, ⌘⇧R if in doubt.
21. **Study: the AI learning notes centre (built).** One ask, in the
    user's words: *"i want you to create a AI learning notes centre.
    The AI will read and summarize corpuses of financial information
    from a variety of fields that the users wants, but there should
    already be preexisting notes that I want you to comprehensively
    fill out."*
    - **A new section, "Study"**, beside Risk and Economy. The page
      lists the reference corpus as note cards (field chip, title,
      one-line summary, reading time); opening one renders a long-form
      plain-English note. The address is `#study/{id}`, so any note is
      linkable.
    - **The reference corpus: ten comprehensively authored notes** in
      `app/study_data/*.md` — hand-written (not model-generated) deep
      treatments of ten fields: how markets work; shares and what a
      company is worth; bonds and credit; money, inflation and
      interest rates; where the world's wealth sits; housing and the
      arithmetic of leverage; how banks work; pensions, insurance and
      the long risks; the mechanics of investing (compounding,
      diversification, fees, timing); and why people lose money
      (behavioral finance). Each is 1,651–2,003 words of structured
      prose in 5–8 sections; the floor (800 words, ≥4 sections, named)
      is enforced by test for all ten.
    - **The format is a strict markdown subset** — `##` sections,
      paragraphs, `-` bullets, `1.` lists, `>` pull quotes, `**bold**`,
      `--` rules — that a small hand-rolled server-side renderer turns
      into escaped HTML. No new dependencies; a note that contains
      markup it doesn't know renders as harmless text.
    - **Bring your own corpus.** A card at the top of the centre takes
      a pasted financial document (up to ~20,000 characters) and an
      optional topic. `POST /api/study/ai` runs it through the
      swappable `PROOF_LLM_*` model (32,000 tokens / 300 s — measured:
      the resident thinking model spends its *entire* completion budget
      on reasoning, so 8,000 and even 16,000 came back empty after
      167 s, while 32,000 leaves a full 800–1,200-word note in ~130 s;
      `enable_thinking:false` is accepted but ignored by this model)
      asking for strict JSON `{title, field, summary, body}`; the body
      is validated (word count in a sane band, bounds on the other
      fields) and saved into `data/study.json`
      (`PROOF_STUDY_NOTES` moves the file) with the usual
      `{v, updated, ...}` envelope, atomic, with the model name and a
      timestamp. Saved notes join the list with an "AI-written from
      your document" badge, are deletable, and render through the same
      pipeline. No key means no card; a model failure is a plain-
      English 502; the reference set itself never needs a model and
      can't be deleted (a 409 that says so).
    - Routes: `GET /api/study` (the list, no bodies), `GET
      /api/study/{id}` (rendered note, plain-English 404), `POST
      /api/study/ai`, `DELETE /api/study/{id}`.
    - Client: a section resolver like Economy's (list fetch cached in
      `STUDY`, detail fetched per id), no workspace tabs; static tag
      **v=34 → v=36** (v=35 shipped with a bug — the document card
      wired its button through the document instead of the card element
      and threw on open; fixed and re-tagged so nothing could cache
      the broken copy).
    - **Verified**: 32 Study tests (the reference corpus, the renderer,
      the list/detail/delete surface, and the AI route incl. every
      failure mode) — full suite **279 → 311**, green. Live in the
      browser: list of ten cards plus the bring-a-document card, a deep
      link into a note (8 sections, pull quote, lists), and a real
      round trip — a 2,700-character insurance document came back as a
      saved six-section note, survived a page reload, and deleted
      cleanly. One bug found in the pipeline: a self-deadlock (`Lock`
      held by the summarize step, re-taken by the save step) →
      reentrant lock. One bug found in the *test* (checked persistence
      after the delete that was supposed to remove it) → test fixed;
      the app was right all along.
 22. **Study round 2: web search for textbooks, live progress, and a
     graduate-level corpus (built).** One ask, in the user's words:
     *"make sure the AI can search for textbooks on the internet in the
     study thing and when it is working, it should say searching with
     the spinning icon, and occasionally give updates on progress."*
     - **The search pool is four backends with clean, challenge-free
       APIs**: Wikipedia (the encyclopedic treatment), Wikibooks (open
       textbooks — the closest thing to a real chapter), Wikiversity
       (study material), and arXiv (the academic papers, by abstract).
       All four verified reachable from this machine. The pool was
       chosen by probing, not preference: **Bing answered a
       correct-titled page with unrelated results 9/9 times** (Bellevue
       hotels, a dictionary entry, Seattle weather, for a Merton-model
       query — a datacenter-IP behaviour that changes with the wind),
       and DuckDuckGo/Mojeek/searx-be served bot challenges. Each
       backend is best-effort — a slow or blocked one is skipped and
       the job's progress says so.
     - **A DNS fix the app now carries** (`app/netfix.py`): this
       machine has **zero nameservers configured** (`scutil --dns` →
       0), so no hostname resolves at all without it. `netfix.install()`
       (at `main.py` import) wraps `socket.getaddrinfo` with a
       DNS-over-HTTPS fallback (1.1.1.1 / 8.8.8.8, IP literals) that
       fires only when the system resolver fails; `PROOF_DNS_FALLBACK=0`
       disables it. Inert on machines with a normal resolver. This is
       what makes the search work *from this machine* — and would fix
       Yahoo/SEC lookups here too.
     - **A relevance gate** for the MediaWiki hits: search over-matches
       hard (verified: a London emission-zone page and education
       syllabi for a Merton query). A hit survives only when its
       title/snippet echoes the query at word boundaries — ≥2 words (1
       for a one-word query) and always the *longest* word. arXiv uses
       the same gate, with a quoted-phrase-first / AND-of-words
       fallback (verified: the phrase returns 0, the AND returns exactly
       the right paper) and a 45 s window (15 s times out cold).
     - **The gather** runs the pool in order, reads each hit, and caps:
       18,000 chars total (≤ the 20,000 document limit), 4,500 per
       page, stubs under 80 chars dropped, header lines budgeted, plus
       a word-boundary backstop cut. Below 300 gathered chars the job
       fails with plain English rather than letting the model invent
       material.
     - **A job model** (in-memory, `s`+token ids, 10-minute TTL, 500
       cap — eviction never touches a running job; that flaw was caught
       and fixed in test). Statuses: `running` → `done` (key set:
       gathered text → the same `_write_note` tail → one saved note
       with a `sources` list of `{title, url}`, http/https only, ≤12),
       `gathered` (no key: the pages are reported, no note), or
       `failed` (web down, thin result, or a model that didn't finish —
       always in plain English, with the pages it *did* find attached).
     - **Routes**: `POST /api/study/search` (400 in plain English for a
       topic under 4 characters) and `GET /api/study/search/{id}`
       (404 "it may have expired").
     - **Client v=37**: the bring-material card gains a
       Paste/Search chipmode toggle. Search: a topic box (Enter
       submits), a **spinner while it runs**, and a plain-English
       status line refreshed by a 4 s poll (immediate first tick;
       navigation-safe — it stops cleanly if the reader leaves, the
       job still finishes server-side). Done → straight into the saved
       note, which shows an "AI-written from N web sources" badge and a
       Sources link line; list cards show the count.
     - **The corpus goes up a level**: all ten reference notes
       rewritten from ~1,900 words of intro-level prose to **4,500–
       5,500 graduate-level words in 8–12 sections each** (the
       "comprehensively fill out" half of decision 21, done properly),
       still no prices, same strict markdown subset. Test floor raised
       accordingly (800 words/4 sections → 4,500 words/8 sections)
       plus a no-prices check (no `$`+digit anywhere in an authored
       note).
     - **A quiet failure, found only by watching the app run**: the
       first live search hung forever. The 300 s read timeout fired
       *inside the worker thread*; the thread died on an exception the
       ``except RuntimeError`` didn't cover; the job sat in "running"
       while the browser polled a dead job (spinner turning, no
       landing — `lsof` showed no connection left to the model
       server). Fixed at both levels: the shared `risk._post_llm` now
       converts every transport/shape failure into a plain-English
       ``RuntimeError`` (fixing all four LLM features at once), and
       the worker gained a final `except Exception` backstop, so its
       "never raises" promise is actually true — the job lands
       "failed" with the pages it found, never hangs.
     - **The search write, calibrated against a real run**: a timed
       probe of the exact search gather (18,000 chars, 4 sources)
       took **728 s and came back empty** — the thinking model spent
       its whole 32,000-token budget reasoning (100k characters of
       it) and wrote zero words. The search path now gets
       `AI_LLM_MAX_TOKENS_SEARCH = 48_000` (the model's context is
       262k; verified the server accepts it) and
       `AI_LLM_TIMEOUT_SEARCH = 1_500.0`; the paste flow keeps the
       32k / 300 s pair it was measured with. The progress line tells
       the truth: *ten minutes or more*.
     - **The gather went on-domain**: MediaWiki's rank for a how-
       phrase serves the page it associates with a single word first —
       a live "how do bonds work" gathered a baseball player, a
       grief-psychology page, a jazz composer and a celebrity. The
       wiki search now runs **two passes** (the query anchored to the
       domain, then the reader's own; deduped, anchored first): the
       same query now gathers Finance, Sukuk, Surety and Catastrophe
       bond. The gate's longest-word tie-break is deterministic
       (`sorted`; a bare `max` over a set flips with hash
       randomisation — a Black–Scholes / CAPM tie was observed live),
       and the HTTP layer retries 429/503 with climbing backoff and
       *reports* the skips (a page that won't load says so, instead
       of a search that quietly "found" few pages).
     - **End-to-end, in the app**: "how do bonds work" → the gather
       lifted the four on-domain pages (Finance, Sukuk, Surety,
       Catastrophe bond); the local model then reasoned and wrote
       **Risk Transfer in Financial Instruments** (2,559 words, 10
       sections; ~12 min inside the 48k budget) and the job landed
       **done** — the client navigated to the new note, and the note
       is saved in `data/` and survives a restart. That pass caught
       the round's last contract bug: `get_note` spread `note_entry`
       (sources as a *count* for the list card) over the saved list,
       so the detail view saw a number where the client expects an
       array — the badge read "AI-written from your document" and the
       source links were gone. `get_note` now returns the list for AI
       notes (list cards keep the count); the detail shows
       "AI-written from 4 web sources" with all four links. The price
       figures in the note are the sources' own numbers, which the
       prompt keeps; the no-prices floor binds the ten authored notes
       only.
     - **Verified**: full suite **311 → 342**, green (~1 s, offline).
       Live probes: the two-pass gather on "how do bonds work" and
       "how do stock markets work" (on-domain sources; the stock-
       market one fills the budget with the bubble, OTC, the 2025
       crash, the crashes list and the EMH page). Browser round trip
       in the app: a full reload shows the **Bring material** card
       (both modes) above the note cards, zero console errors; a
       card opens its note (11 sections, no prices, back link); the
       search shows the spinner and each progress line as it lands.
 
23. **Strategy lab: the AI runs your own strategy (built).**
     One ask, in the user's words: *"make an option that the AI trades
     based on that strategy instead of a routine formula, and the AI
     manages the portfolio and makes decisions at every interval that
     requires a check, based on what the strategy says, e.g. if it says
     check X times a month, or when the price drops by Y%, or when the
     value drops by Z%* — and the AI does its own web research, on
     **data before the simulation date only**. Two standing rules: the
     **compaction** rule (this block is the anchor; work in the
     increments below, keep reads tight) and the **RAM rule** (the
     resident :8000 model must never be called from my test passes —
     the engine takes an injectable decision-maker and my tests run a
     lightweight stand-in, "I pretend to be the backtest person";
     fully offline, zero model calls).
     - **The engine is pure: three injectable seams.** A decider
       `decide(context) -> {trades, note}` (LLM in production, a
       deterministic stand-in in tests), a research layer (or `None`),
       and the prices (a dict of symbol -> {iso_date: close}, already
       injectable). Given those, `simulate()` is deterministic and
       testable offline, in a new module `app/strategy_lab.py`. The
       existing single-symbol `backtest.py` and `/api/backtest` keep
       working unchanged.
     - **A machine-readable plan drives the schedule.** A plan =
       symbols + start cash + a periodic cadence (week / two weeks /
       month / quarter — the engine calls the decider on the first
       trading day of each period) + event triggers (drop-from-cost
       % / drop-from-peak % on a holding, with a lookback; a fired
       trigger re-arms when the price recovers above the threshold,
       or at the next periodic check) + targets + an on-drop action +
       an optional upside exit + the user's own words (passed verbatim
       to any LLM decider) + a research flag.
     - **Portfolio semantics:** cash + positions. A trade =
       {symbol, side, weight} — a buy takes a fraction of total
       equity, a sell a fraction of the holding; all trades execute
       at the decision day's *close* (the current engine's
       no-lookahead rule); costs in bps; equity marked to market
       daily; the benchmark is an equal-weight buy-and-hold of the
       same universe over the same window; metrics reuse
       `backtest._metrics`; every result ships a per-decision log
       (date, what it saw, what it researched, what it did, why).
     - **No-lookahead research, date-gated.** Wikipedia: the revision
       live *as of* date D (newest revision with timestamp <= D, then
       its content — nothing the reader could not have seen that
       day). arXiv: `submittedDate <= D`. Reuses study's `_http_get`
       (3x retry, 429/503 backoff, honest skip reporting); a hard cap
       on research calls per backtest; results cached by (page,
       revision-timestamp) so repeated decision days sharing a
       revision reuse one fetch.
     - **Two UI modes, mirroring study's Bring material:** "my plan"
       — a structured form (tickers, checks per month, drop
       thresholds, what to do on a drop, targets) -> the
       deterministic decider; no LLM, synchronous, fast, RAM-safe.
       "AI runs it" — one LLM call interprets the free text into the
       plan shape, then the LLM re-reads the *full original text* at
       every decision point; that mode is a background job (study's
       model: in-memory dict, TTL, worker thread, progress lines, 4 s
       client poll, spinner).
     - **The LLM never sees the future.** The decision context carries
       only history up to the decision date: per-symbol close plus
       1w/1m/3m/1y/52w figures, the portfolio state, the research
       gathered for *that* date, and the user's strategy text verbatim.
       The prompt asks for strict JSON
       `{trades: [{symbol, side, weight}], note}`.
     - **Build order:** 1 engine core + deterministic decider +
       offline tests (hand-computed expectations) -> 2 date-gated
       research layer -> 3 interpreter (deterministic + LLM) -> 4 LLM
       decider (prompt/parse via `risk._post_llm`) -> 5 routes
       (`/api/backtest/strategy` + job poll) + UI (mode chip, universe,
       spinner/progress, decision log) -> 6 docs close + live browser
       verification on the **my-plan** path only (deterministic, no
       model; prices come from the live API, which is fine) and, only
       if the user wants, at most one tiny bounded real-LLM run.
      - **As built.** `app/strategy_lab.py` holds the engine, the
        deterministic decider, the word-reader, the LLM interpreter
        and the LLM decider; `app/research.py` the date-gated
        researcher. Routes in `app/main.py`: `POST
        /api/backtest/strategy` — "my_plan" runs synchronously and
        returns the full result; "ai" returns a pollable job (a
        missing key is a 503 that names the form fallback; unreadable
        words a 400; a model outage never fails the job — the reader
        takes over and the days come back as quiet no-trades) — and
        `GET /api/backtest/strategy/{job_id}` for the poll. The UI is
        the old three-step lab with a mode chip on step 1 ("My plan"
        / "The AI runs it"), the plan form on step 2 (tickers, cash,
        cadence, up to three drop triggers, on-drop action, upside
        exit, research, wiki names, window) and step 3 showing the
        plan as read — including *who* read it: form / words / model
        — the metrics, the curve, a verdict, and a scrollable log of
        what was decided each day. Tests: `test_strategy_lab.py`
        (19), `test_research.py` (11), `test_interpret.py` (21),
        `test_llm_decider.py` (9), `test_strategy_routes.py` (8 —
        the route glue with faked prices and a faked model) —
        410 total, all offline.

24. 24. **Rebrand to Longview, then convert to an open-source SaaS (in
     progress).** Ask in the user's words: *the target audience are
     professionals; rebrand this; start converting it into a full
     functioning website SaaS, no login, open source; and the one must-
     include is a way to set up your own AI model key, because everyone
     else can't use my local model.* Decisions: the name is **Longview**
     (user's pick); the Study section is **kept but tucked away** -
     renamed "Reference", moved out of the main nav to a bottom-of-
     sidebar link.
     - - 1 **Rebrand.** Longview on every user-facing surface (title,
       landing, sidebar brand, ledes, health endpoint, system prompts,
       README); a cooler professional palette (dark landing, paper app,
       blue-black ink); Study -> "Reference" in a bottom nav group. The
       tests pin nothing on the name, so the 410 must stay green
       untouched.
     - - 2 **Bring-your-own model key (the must-include).** New
       `app/llm.py` seam: canonical env vars `LONGVIEW_LLM_KEY` /
       `LONGVIEW_LLM_BASE` / `LONGVIEW_LLM_MODEL` with `PROOF_LLM_*`
       legacy fallback; a per-request override arrives in an
       `X-Longview-LLM` header (base64 JSON of {base, key, model});
       `risk._post_llm` resolves request > env. A Settings tab: base
       URL, key, model, a Test button, saved in localStorage; `GET
       /api/llm` status + `POST /api/llm/test`; every LLM route honors
       the header, background jobs capture it at start. Every "no model"
       state points at Settings, not at env vars.
     - - 3 **SaaS site.** A real public landing (dark hero, three
       pillars, bring-your-own-key steps, open source, honest rules,
       CTAs into the app and the docs); an in-app `#docs` route with the
       self-hosting guide; a footer (Reference, Docs, license). No
       login: state is per-browser (localStorage). The key travels
       browser -> app server -> model provider per request; the app
       never stores it.
     - - 4 **Open source.** `.gitignore` (data/, .venv/, caches, logs),
       MIT `LICENSE`, the public README rewrite, `git init` + first
       commit - "let it be open source" supersedes the earlier no-repo
       rule; `data/` stays on disk, just untracked.
     Standing rules unchanged: no login, no new deps (httpx is
     existing), RAM rule (tests never touch the :8000 model), plain-
     English errors, no-lookahead math, data/ preserved.

## How to run

See `README.md`. Short version:

```
cd beacon
.venv/bin/uvicorn app.main:app --port 8010   # open http://localhost:8010
.venv/bin/python -m pytest tests/ -q          # 410 tests, offline
```
