# Bonds, Credit, and the Machinery of Lending
~ field: Bonds
~ summary: A bond is a loan with a schedule. Its price, its yield, and the credit behind it explain more of the financial world than any share price does.

## What a bond is

A bond is a **loan, written as an instrument you can sell**. The
borrower — a government, a city, a company — has borrowed money from
you, and in return promises two things: to pay you a fixed amount of
interest on a fixed date, every year (the **coupon**), and to hand
back the original sum (the **principal**, or **face value**) on a
final date (the **maturity**). That is the whole instrument.

Everything else in this note — prices, yields, credit, duration — is
consequence of that one fact: **the payments are fixed, so the value
of the instrument can only move when the world's view of fixed
payments changes.** A share's payments are whatever the company
chooses; a bond's are whatever it promised. The rigidity is the
point, and it is also the source of all the danger.

The three numbers on every bond:

1. **Face value** — what you get back at the end (usually a round
   number; the rest is scaling).
2. **Coupon rate** — the promised interest as a percentage of face,
   fixed when the bond was issued.
3. **Maturity** — when the promise ends. This is the number that
   decides how much of a bond *is* a bond and how much of it is a
   bet. A three-month bill is almost a cash equivalent; a forty-year
   government bond is a long-dated wager on what money will be worth
   in 2066.

The cleanest way to see the whole instrument is its edge case, the
**zero-coupon bond**: a bond with no coupons at all, sold below face
and redeemed at face on the final date. Its entire promise is the gap
between what it costs and what it pays, and its entire risk is the
time in between. Every coupon bond is just a ladder of zeros: each
coupon is a small promise with its own date, and the bond is the sum
of them. That decomposition is not a trick; it is the honest anatomy,
because each rung of the ladder re-prices on its own clock, and the
bond's price is the sum of rungs that are all, secretly, bets on the
path of rates from *now* to their own dates.

The graduate framing follows: **a bond is a claim on a known stream,
and the stream's value is a function of the discount rate.** Know the
payments (the schedule) and the discount rate (the market's view of
money over time), and the price is arithmetic — no judgment left in
it. The judgment lives in the inputs: the world's view of money, and
the world's view of the borrower. Everything in the remaining
sections is one of those two inputs, moving.

## Why bonds trade, and what yield really is

Bonds do not sit in a drawer. They **trade**, and their prices move
every day, because the fixed promise they carry is being constantly
re-priced against a moving world. The price of a bond and its
**yield** are the same fact seen from two ends, and the relationship
is the most important mechanical fact in fixed income:

- When the price of a bond rises, its yield falls.
- When the price falls, its yield rises.

They are mirror images, and **the yield is the honest number**. The
arithmetic behind the mirror is present value: every promised payment
is worth, today, what you could earn on that payment elsewhere once
the waiting cost is deducted. When the waiting cost rises, every rung
of the ladder is worth less, and the sum — the price — falls; the
fall is not a verdict on the borrower, it is a re-computation. A bond
selling below face (a *discount* bond) is simply one whose promised
coupon has become unattractive relative to what money earns
elsewhere; a bond selling above face (a *premium* bond) is one whose
coupon is still generous by today's standards. Nobody needs to know
the price history of a bond; the yield tells you the annualized
return of holding it to maturity, and it is the number at which all
bonds of a given maturity and credit find their price.

What moves the yield of a *safe* bond is almost entirely one thing:
**the level of interest rates**, which is set by the central bank and
its market of expectations (the money, inflation, and rates note
unpacks the machinery). When the central bank raises rates, the
promises that old bonds made stop competing, and their prices fall
until their effective yield catches up to what the world now pays for
fixed promises of that age. The fall is larger the longer the bond,
because a long bond has *more* of its payments exposed to the rate
change — a point of this, precisely, in the next section.

The same mirror explains why bonds and the central bank are one
conversation. The bank moves the short end directly, by setting the
overnight rate; the market moves the long end, by pricing what it
believes the bank will *do* next year, next decade, in the years
when inflation and growth are still unknown. A bond price is
therefore always a statement about the future: it is the market's
best guess, in a single number, of the whole path of money's value
between purchase and maturity. That is why a bond market can move
hard on a sentence from a central banker — the sentence changed the
guess, and the guess is the price.

> A bond does not risk you losing the money it promises. It risks
> you holding something that no longer earns what the world pays for
> holding money.

## Duration: how the promise meets the clock

The mirror above tells you the *direction*; the next number tells you
the *size*, and it is the working measure of the whole fixed-income
world: **duration**.

Duration is, at its most honest, a weighted average of *when* a bond's
money comes back. Each payment of the bond carries a weight equal to
its present value's share of the total, and the duration is the
average date of those payments, in years. A one-year bill has a
duration of one; a thirty-year bond whose coupons are thin and whose
face is far off has a duration in the mid-twenties — because most of
its value sits in the one payment at the very end, and that payment
is the one most exposed to what money will be worth in twenty-five
years.

The mechanical use, the one every practitioner carries: **a bond's
price moves, for a one-point change in rates, by roughly its
duration, in the opposite direction.** A ten-year bond with a
duration of eight loses roughly 8% of its value if rates rise one
point, and gains roughly 8% if they fall one. A thirty-year bond
with a duration of twenty-five loses roughly a quarter of its value
on the same one-point rise. The same central-bank sentence that moves
the ten-year a bit can move the long bond violently, because the
sentence has to be true for *longer* in the long bond: its payments
are exposed to the rate path for decades, not years, and a decade of
uncertainty about the future is priced by the duration.

Two refinements, because the graduate version of the fact needs
them. First, the relationship is not a straight line: it curves, in a
property called **convexity**, which means the fall for a one-point
rise is slightly less than the gain for a one-point fall. The
asymmetry is small for short bonds and real for long ones, and it is
one of the quiet reasons the long end of the market is where the
professional drama lives — the big moves are asymmetric, and the
asymmetry is in the tail. Second, duration is not a constant: it
changes as the bond ages and as rates move, so the exposure of a
held bond is a *path*, not a number. Institutions manage that path
deliberately — a pension fund with promises running forty years out
holds assets whose duration matches the duration of the promises, and
the matching is a continuous, active job, because both sides of the
match keep moving (the pensions note covers the liability side of the
same fact).

The private-person consequence, which most holders of "safe" bonds
never internalize, is the one the 2022 episode made famous:
**a bond position is a rate position.** You cannot own a bond
without owning a bet on where rates will be; the only question is
whether the bet was the one you intended, or one that was in the
product by default. A short ladder of bills is a bet that rates
stay where they are; a long bond is a bet that rates fall, or that
they rise less than your duration fears. The word "safe" in the
marketing describes the *payments*; the *price* is doing the
betting.

## The yield curve: the market's compressed view of the future

The **yield curve** — the yields of bonds of different maturities,
plotted against their dates — is the single most-watched line in
finance, because it compresses the market's whole view of the future
into one picture. The short end is the central bank's present policy,
plus the market's guess of the next few moves; the long end is the
market's guess of everything that happens *after* the policy is
known — the years of growth, of inflation, of the bank's patience —
together with a standing charge for bearing all of that
uncertainty, the **term premium**: the extra yield the market
demands for lending long, because a long loan must survive futures
that no one can yet see.

Two facts about the curve, each with a consequence. First, it
normally slopes upward — long money is worth less, so lending it
long must pay more — and its slope is therefore a live read on the
market's patience with the present. Second, when it **inverts** —
short rates above long ones — it is the market saying *we expect
rates to fall*, which historically has meant *we expect the economy
to slow*, which is why an inverted curve has, with annoying
consistency, preceded recessions by a year or two. The graduate
version holds the mechanism, not the mystique: the inversion is
rational arithmetic, not prophecy. The market prices in an expected
downturn and the cuts that will follow it, and it prices them into
the *long* end (where the cuts would matter) more than the short end
(policy is known), and the result is a downward slope. The market
can be wrong — it has been, on occasion, and the timing is
coarse — but the inversion is a statement with a mechanism, and the
statement is the economy's best available summary, in one line, of
its own coming weather.

The curve is also the system's reference frame: every other asset in
the economy — every share (the equities note's discounting), every
mortgage (the real-estate note's payment), every project's
justification — is priced against the rates the curve sets, because
the curve is the market's price of *time itself*. When the curve
steepens or flattens, what is moving is the relative value of
waiting, and everything that depends on waiting re-prices around it.
The rest of the corpus can be read, in part, as a record of what
other assets do when the curve bends.

## The credit dimension: the other half of a bond's price

A government bond's yield is (almost) all rate. A **corporate bond's**
yield has a second ingredient: **credit risk** — the chance that the
borrower simply cannot pay, in which case the promise is worth less
than its words. The difference between a risky company's yield and a
riskless government's yield, for the same maturity, is the
**credit spread**, and it is the market's running price of *this
borrower's* reliability — a live auction, every day, over how much
the borrower's reliability is worth.

Credit is where lending lives or dies, and the vocabulary is
short and stable:

- **Investment grade** — borrowers whose credit is good enough that
  institutions are allowed, by rule, to hold them in bulk. Spreads
  are thin because the crowd is deep; the risk is that the crowd is
  *all* invested grade, and in a bad year they all wobble together,
  thin spreads and all.
- **High yield** (the old word: *junk*) — borrowers paying a fat
  spread because the chance of default is real. The spread is
  compensation, and it has usually been fair compensation over
  decades — until the year it was not, which is the recurring lesson
  of every credit cycle.
- **Default and recovery** — when a borrower fails, bondholders do
  not get zero; they get whatever the liquidation or restructuring
  returns, the **recovery rate**. The credit story of a business is
  therefore a two-act play: the probability of default, and the size
  of the wound. A name can be cheap for good reasons (the
  probability is high) or expensive for bad ones (the crowd does not
  believe the probability is as high as it is), and the art of
  credit is in separating the two.

The credit cycle has a shape worth memorizing because it repeats,
and because it is the same loop the banking note described from the
lender's side: in good times spreads tighten (the market decides
everyone is safe), which makes risky borrowing cheap, which produces
*more* risky borrowing, which ends when the economy turns and
defaults cluster in the crowd that the tightening created. Spreads
are therefore a **lagging confidence indicator and a leading danger
indicator at once**: wide spreads mark fear, but narrow spreads mark
the *approach* of the fear, and the narrowing is itself the signal,
because the narrowing is what built the crowd. The dashboard reading,
which the professional world uses as a standing check on the
economy: the corporate spread is one of the cleanest windows on how
the market thinks businesses are faring, because it is a price set
daily, by the people with the most at stake, on the question of
whether businesses will be able to pay.

One more ingredient belongs to the spread, and it matters for the
reader of the news: **liquidity**. Part of the spread is the cost of
*being able to sell* — the discount the market charges for an
instrument that trades thinly. In a calm market the liquidity piece
is small; in a panic it can be larger than the credit piece, because
the fear is not that the borrower will fail, it is that no one will
buy the bond while the failure is being discovered. The same
instrument, same payments, same borrower — a different price,
because the *exit* changed. This is why spreads can move violently
on a day when no borrower has done anything, and why the spread is,
in the end, a price of confidence as much as a price of risk.

## Who issues what, and what it tells you

The map of the bond world is a map of who owes the world money:

- **Government bonds** — the benchmark of safety in each currency.
  They set the whole yield curve that every other price hangs from.
  (They carry their own quiet risks — inflation, currency, and the
  long shadow of the state's spending — but within a currency they
  are the zero, the thing other prices are measured against.)
- **Municipal and supranational bonds** — the cities, agencies, and
  international bodies in between; mostly about credit, with a tax
  twist in some jurisdictions that makes a given yield look
  different after the tax is done.
- **Corporate bonds** — the business world's balance sheets, sliced
  into tradeable debt. Reading a sector's spread movement is one of
  the cleanest windows on how the market thinks businesses are
  faring, and sectors move apart for reasons — the energy name and
  the airline name, in the same spread dashboard, are two different
  stories.
- **Mortgage-backed securities** — pools of home loans re-cut into
  bonds; the class that showed the world, in 2008, that a fixed
  promise can hide a *correlated* risk. The housing note covers that
  anatomy; the bonds lesson is that the pool was not a bundle of
  independent promises, it was one promise wearing a thousand faces.
- **The funds and swaps that wrap all of it** — bond funds pool the
  bonds (and pass on the daily wobble); interest-rate swaps let
  institutions convert fixed promises into floating ones, or vice
  versa. Most of the system's leverage lives in these wrappers,
  which is why the wrappers are where the system's shocks start.

One structural fact ties the map together, and it is the reason this
note exists before the equities one in any honest ordering of the
system: **bonds are where institutional money parks.** Pensions,
insurers, and endowments must hold assets whose payouts match their
promises, and the promises are fixed, so the assets are fixed —
which is why the bond market is several times the size of the stock
market, and why a bond-market shock is a *system* shock, not an
asset-class wobble. The same fact is why the bond market is the
least *watched* half of finance from the private side: households
hold their risk in the loud half (shares, houses), and the quiet
half — the one that is several times larger and that sets the price
of time for the whole system — is mostly a professional
neighborhood, and its news arrives at the private person secondhand,
a week late, dressed up as "rates are doing something." The student
of the system who reads the bond market directly is, in the literal
sense, upstream of the rest of the news.

## The 2022 reckoning

The standing lesson of this note crystallized in one year, and it is
worth a section of its own because it is the episode that broke the
calm decade's assumptions.

For the generation of investors who entered the market in the years
after 2010, bonds had a character that was, in one sense, a
mischaracterization of their own: rates sat near the bottom of their
historical range for a decade, and a bond that pays little and loses
a little in bad years was, in practice, a *quiet* asset — the safe
corner of the portfolio, the thing you buy and forget. Nothing in
that decade's experience suggested what the instrument actually is:
a long-dated claim on a stream of fixed payments, whose price is the
arithmetic of the discount rate. Then, in 2022, the fastest
sequence of rate rises in forty years — the answer to an inflation
that the calm decade had not seen — met a generation of holders who
had never held bonds through anything like it, and the arithmetic
collected its fee all at once.

The size of the move: the long end of the curve, with durations in
the mid-twenties, lost roughly a quarter of its value on a rise in
rates of the size that occurred; the ten-year, with a duration of
roughly eight, lost close to that fraction of a point-move times its
duration. For an instrument class marketed and held as *safe*, the
price fell by as much as it had risen in the entire preceding
decade, in a single year. And the fall was not a verdict on any
borrower: the governments and companies in the bonds paid every
coupon on schedule, to the day. The price moved because the
*discount rate* moved; the payments did not. That distinction —
between the promise and its price — is the whole lesson, and it is
the one the calm decade had made impossible to learn, because for
ten years the two had moved so little that no one had noticed they
were two things.

The second part of the lesson is institutional, and it connects
straight to the banking note: the holders of the falling bonds were
not a free crowd of speculators, they were *obliged* ones. The
pension and insurance books that must match promises could not
simply sell; the funds that marked to market showed the loss on the
day; and the banks that held the quiet paper on their balance sheets
found the paper's *market value* falling fast, the losses sitting
unrealized, and a run forming in a day around the institution rather
than the instrument. The price event became a solvency question
became a system question, in the space of weeks. The mechanism is
the general one: **a fixed promise, held by parties who cannot all
leave at once, turns a market move into a coordination event** —
the same two-equilibrium logic as the bank run, expressed on a bond
portfolio instead of a deposit base.

The standing lesson, in the form the graduate carries: **a bond's
"safety" is a statement about its payments, not about its price**,
and a price can fall a third on an instrument that pays every cent
it promised. Anyone who owns long bonds owns a rate bet, whatever
the word "safe" does in the marketing. The calm-decade version of
the mistake, which the 2023 bank episode extended: a decade of
rates near zero taught every holder of long paper that *duration
was free* — that the long promise cost nothing to hold, because the
discount rate had nowhere lower to go and the calm made the wobble
invisible. The return of a normal rate charged the fee in one move,
to the people who had stopped paying attention to what the fee was
for.

## The wrappers and the plumbing

The instruments above are the raw forms; the system most people
actually touch is the layer wrapped around them, and the layer has
its own risk properties:

- **Bond funds** pool the bonds and pass on the daily wobble — the
  fund's price moves with the market value of what it holds, which
  means a "fund of safe government bonds" can fall a third in a
  falling-rate-year's arithmetic, and the fund's duration is the
  duration of *what it holds*, not of "bonds" in the abstract. The
  wrapper adds one quiet feature the raw bond does not have: the
  fund can be *redeemed* on a schedule the manager controls, and the
  gap between the redemption promise (short) and the paper (long) is
  the banking note's gap, again, wearing a fund's clothes.
- **Interest-rate swaps** let institutions convert a fixed promise
  into a floating one, or vice versa — the professional's way of
  taking a position on the rate path without owning the bond. Swaps
  are where a large share of the system's *leverage* on the rate
  view actually sits: the bet is taken, in large size, without the
  balance sheet, which is efficient in calm years and is the thing
  that unwinds violently in the years the calm ends.
- **Mortgage-backed securities**, the class that needs its own
  paragraph because 2008 made it load-bearing for the whole system:
  pools of home loans, re-cut into slices with different risks, sold
  as if each slice's risk were its own. The anatomy the housing note
  gives — the pool, the correlation, the slice — has the bonds
  lesson attached: a bundle of fixed promises, each individually
  plausible, can be *one* risk when the thing that breaks them is
  the same thing (the price of houses), and the wrapping that made
  the bundle tradeable made the correlation *invisible* to the
  buyer, because the buyer priced the slices, not the source.

The structural fact of the wrapper layer: **the promise on the cover
is not the risk in the basement.** Every wrapper above is, in some
way, a bank in a different coat — short promises out, long promises
in, a thin layer between, and a mark that the calm years taught the
market to ignore. When the calm ends, the wrappers are where the
system's shocks begin, because the wrappers are where the system's
leverage concentrated: the leverage is not in the bonds, it is in
*what the bonds fund*, and in the promises the wrappers made to the
people who put money into them.

## How to think about a bond position

The practical section, because a bond is a position with a schedule,
and the schedule is where the private person's life actually meets
it. The checklist, in the order the failures come:

1. **What is my duration, really?** Add it up across everything you
   hold, including the bond funds (which carry the duration of what
   they hold, not of "bonds" in the abstract). This is your rate
   bet, whether you intended it or not, and the number that answers
   the question "what happens if rates rise one point?" is this one.
   Most holders of "safe" paper have never written the number down,
   and the 2022 lesson is that the unwritten number is the one that
   surprises.
2. **What credit am I actually holding, and what does the spread say
   I'm being paid for it?** Thin spread on a name you cannot explain
   is not a margin of safety; it is a price the crowd set, and the
   crowd's price is the thing that moves first when the crowd's
   confidence leaves. The honest question is not "is this safe?" but
   "what would I be paid for this, and is that what I think I am
   being paid?"
3. **What is my cash-flow need?** The honest use of a bond is to
   *match* a known future need — tuition, a retirement drawdown, a
   house purchase a decade out. Ladder the maturities to the needs:
   a maturity falling when the money is needed, year by year, so
   that the plan does not depend on the market's price on the day.
   The matching is the point, and it is what the word "safe"
   actually deserves — safety as *timing*, not safety as *price*.
4. **What happens to me if rates double?** Do the duration math
   before the market does it for you: the position's value, at
   double the current rate, and the decision it would force. If the
   answer is "I would have to sell at the bottom," the position was
   wrong, not the rates — and the fix is a shorter duration, or a
   cash-flow need that actually matches the paper.
5. **Where is the leverage hiding?** In the fund's structure, in the
   swap, in the mortgage pool, in the wrapper's redemption promise.
   The wrapper section above is this question, expanded: the
   instrument you bought is the cover, and the cover is not the
   basement.

The ladder deserves one more word, because it is the one structure
that answers most of the checklist at once: a spread of maturities
means that *some* of the paper matures in each of the coming years,
so the plan never depends on selling at a price, and the rate bet is
distributed across the years rather than concentrated in the long
end — which is to say, the ladder is the *de-risked* version of the
same instrument, and it costs a little yield for the privilege,
because the short rungs pay less than the long ones. The private
person's bond, in the end, is usually the ladder: not a bet, not a
cushion in the abstract, but a schedule of known money arriving
when known money is needed, with the duration question answered in
advance, in the structure, instead of in the panic.

## Bonds and the rest of your money

The final section is the integration one, because bonds only make
sense *inside* a portfolio:

- **As a cushion.** The job of the bond allocation in a mixed
  portfolio is not to outgrow the shares (it will not); it is to be
  the part you can sell in the bad year without selling the shares
  at their low, and the part that calms the drawdown you will live
  through. That job is worth more than any of its returns, because
  it is what keeps the *person* in the plan — the behavior note's
  architecture, in asset form. The cushion that is sized to the
  worst plausible year is the plan's acceptance test, made out of
  paper.
- **As a different kind of weather.** Shares and bonds have, most of
  the time, moved independently — which is the whole reason to own
  both, and the arithmetic behind most of the portfolio's smoothness.
  The caution, made famous by the year this note is about: in an
  *inflation* shock, the two can move together, because inflation
  hurts the fixed promise (the bonds) and the growth fear that
  follows hurts the shares, and the cushion that works in a growth
  scare fails in a price shock. Know which weather you are
  insuring against; the 2022 lesson, at the portfolio scale, is
  that the correlation was the surprise, and the surprise was
  *known in advance* to anyone who had read the mechanism — both
  assets are claims on future money, and a shock that re-prices
  future money hits both.
- **As the source of the "free" money in the system.** Everything
  else in finance is priced against the riskless rate that
  governments set and the market trades. When that rate is near
  zero, everything looks cheap in yield terms and leverage
  flourishes — the calm decade, in one sentence; when the rate
  rises, the whole edifice re-prices at once, because the discount
  rate inside every share and every property valuation is the curve.
  The bond market is not a side of the economy. It is the *price of
  time* in the economy, and every other asset rents from it.

## The deep lesson

Strip the vocabulary away and the whole note compresses to one
fact, and one distinction. The fact: **a bond is a fixed promise in
a moving world** — the promise is the payments, and the world is
the discount rate and the borrower's reliability, and the price is
the continuous arithmetic of the two. The distinction, which is the
one the whole century of fixed income lives on: **the promise and
the price are different objects, and the safety you buy is a
statement about one of them.** The promise — the payments, the
schedule, the credit — is what the borrower owes, and it is
measurable in a good year and a bad one alike. The price — the
market's valuation of that promise, today — is what the world pays,
and it moves every day on the world's moods, its rate path, its
confidence in the borrower, and its willingness to be the exit.

Hold that distinction and the instrument behaves exactly as it
should, and stops behaving as the marketing says. A falling bond
that pays on schedule is not a failing bond; it is a bond whose
world moved. A rising spread on a name that has done nothing is not
a failing name; it is a crowd that is leaving. And the person who
bought the promise for the *timing* — the ladder, the matched
schedule, the known need — has made the price movement irrelevant
to the plan, which is the only thing a private person can ever do
with a market they do not control.

> The stock market pays you for risk. The bond market pays you for
> patience, and then tests whether the patience was real.
