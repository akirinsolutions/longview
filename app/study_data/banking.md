# How Banks Work
~ field: Banks
~ summary: A bank is a machine that converts short promises into long ones. The deposit, the loan, and the gap between them explain most of economic history's crashes.

## The bank's one trick

A bank does many things, but it does one thing that nothing else in
the economy does, and that thing is the entire business: **it takes
in money at a short maturity and lends it out at a long one.** The
depositor can call their deposit at any time — the promise to pay is
*on demand*; the loan the bank makes with that same money runs for
thirty years and cannot be called. The bank is standing in the gap
between "whenever you like" and "in 2056," and the gap is both its
product and its vulnerability.

The graduate version of this sentence has a name and a theorem
behind it. What the bank does — converting short, redeemable
promises into long, locked-in ones — is the only activity in the
economy that is *structurally* a run: its product (the long loan)
and its vulnerability (the short liability) are the same balance
sheet line seen from two angles. No other business has this
property. A factory that makes a durable good is never
*structurally* unable to meet its obligations on a given day; a
bank is, by construction, unable to meet all of its obligations on
the same day, because the money it owes today is committed until
2056. That is why the study of banking is, at bottom, the study of
one failure mode — the run — and everything else in this note is a
variant on how the gap is priced, insured, policed, or exploited.

The machinery, in the four parts every bank runs:

1. **Deposits** — the raw material. Households and businesses leave
   money with the bank for convenience and safety, paying the bank
   little or no interest. The deposit is a *liability* of the bank
   — a promise to pay — and the bank is allowed, by law and by the
   deposit guarantee, to treat it as a stable funding base, even
   though every single deposit is, in principle, redeemable
   tomorrow.
2. **Loans** — the product. The bank lends the pooled deposits out:
   mortgages (thirty years), business loans (five), credit cards
   (revolving, a year). The loan is an *asset* — a promise to pay
   the bank — and its interest is the bank's revenue.
3. **The spread** — the business model in one number: the interest
   earned on the loans minus the interest paid on the deposits,
   minus the cost of the losses. In good years the spread is the
   bank's profit; it is a small number on a large base, which is
   why banks are, in calm years, unremarkably profitable and in bad
   years catastrophically loss-making.
4. **The reserve and the guarantee** — the public scaffolding. The
   bank keeps a fraction of deposits as liquid reserves against the
   central bank, and the state guarantees the deposits up to a
   limit, which is the piece that converts "the bank promises to
   pay" into "the *system* promises to pay," and which is the
   difference between a bank and every other creditor in history.

One more fact belongs to this section, because it explains why the
business is a franchise and not a commodity. The transformation
works only because two strangers each chose the bank on their own
terms: the depositor chose the convenience of the account and the
safety of the guarantee over a higher yield elsewhere, and the
borrower chose the relationship and the patience over a stranger's
paper. The bank is the middleman that makes those two preferences
compatible, and the middleman's inventory — the gap — is the only
inventory in the economy made of *time*. What protects the
franchise is the state: the license to take deposits, the guarantee
that stops the run, and access to the central bank's rails are what
make the gap *fundable* in the first place. Strip the scaffolding
away and the bank becomes what it was for most of history — a
wealthy family's private arrangement, useful to a few, and dead
every time the family wobbled.

## The balance sheet, read

A bank's balance sheet is the whole institution in two lists, and
the lists have a shape that is worth memorizing because it is the
shape of the risk:

- **Assets:** the loans first (the bulk of the sheet), then the
  government bonds and other liquid securities that are the bank's
  cushion, then the reserves at the central bank — the cash.
- **Liabilities:** the deposits (the bulk, on the wrong side of the
  sheet), then the bank's own borrowing from other banks and from
  the markets, then the **equity** — the owners' money, which is
  the thin layer at the very bottom.

The structural facts, each of which explains a class of failure:

1. **The maturity mismatch is permanent.** The assets are long, the
   liabilities are short, and no amount of good management removes
   the gap — it only prices it. The bank is *structurally* a
   runner: if the depositors ever believed the loans were bad, they
   would all come for their money at once, and the loans could not
   be there to pay them.
2. **The equity is thin on purpose.** A typical bank's equity is a
   few percent of its assets; the rest is funded by deposits and
   wholesale borrowing. The thinness is the business (a thick
   equity base would price the loans out of the market), and it is
   also the fragility: a loss of a few percent of *assets* can
   erase the entire equity, which is why banks' profits and losses
   swing by multiples of their calm-year size.
3. **The loans are illiquid by design.** A mortgage is not a
   tradable position the way a bond is; it is a thirty-year
   relationship with one family. The bank's asset side is a wall of
   such relationships, which means the bank cannot sell its way out
   of a bad year the way a fund can.

The graduate habit is to read the sheet not as a list of assets but
as a *risk position*. Almost every line on the asset side is a bet:
the mortgage is a bet on the borrower's employment over thirty
years, the bond is a bet on the issuer's credit and on the path of
rates, and even the reserve line is a bet on the central bank's
willingness to be the counterparty of last resort. The liability
side is the opposite of a bet: it is a *promise* with a deadline
that can move at any moment. Read this way, a bank is an
institution that has taken a large, long-dated, illiquid bet on
the whole economy and has funded it with a wall of short-dated,
redeemable promises — and the equity is the cushion between the
two, sized to absorb the ordinary bad year and deliberately too
thin to absorb the extraordinary one. That last clause is the whole
balance sheet in one sentence: **the bank's equity is an act of
faith in the frequency of the bad year.**

> A bank is the one institution in the economy whose business model
> is to be, at all times, slightly more liquid in promise than it
> is in fact. The entire history of banking regulation is the
> attempt to keep the "slightly" honest.

## The run: a coordination game

The **bank run** is the failure mode that has no counterpart outside
banking, and its mechanics are a coordination story with a precise
shape:

- Each depositor, alone, has no reason to run: the guarantee
  covers them, and the bank is probably fine.
- But each depositor knows the guarantee has a *line*, and that the
  bank's queue is first-come, and that the other depositors are
  reasoning the same way.
- The moment a *sufficient* number believe the others will come,
  coming is the individually rational act — and the bank, whose
  money is in thirty-year mortgages, cannot pay the queue. The bank
  fails **on a truth it had not yet discovered**: it may have been
  solvent, and the run still kills it, because solvency is a
  statement about a year and a run is a question about an hour.

The graduate framing is that a bank like this has **two
equilibria** — a quiet one and a running one — and that nothing in
the balance sheet alone decides which one obtains; the
*distribution of beliefs* among the depositors decides it. The same
bank, with the same loans and the same equity, is stable on a
Tuesday and dead on a Wednesday. This is the deep reason banking
can never be made safe the way a fund or an insurer can: the
failure is not a property of the bank's assets, it is a property of
the bank's *public's attention*, and attention moves in ways that
no asset can be diversified against. It is also why a run has a
speed that no other financial failure has: it does not have to be
true, it only has to be *believed simultaneously* — and the moment
enough people believe it simultaneously, it is true, because the
queue forms and the queue is the proof.

The record shows the run evolving rather than disappearing. In the
early 1930s it moved town to town through a whole country, closing
a fraction of the banking system in a few months; in the 1980s it
returned in the savings-and-loan form, slower because the assets
were opaque rather than the depositors frightened; in 2008 it ran
through the *wholesale* side — the overnight market the banks lend
to each other — which is why the failure of one huge bank could
not be contained to its depositors; and in 2023 it ran through a
social network in a single morning, with the queue forming in a
transfer app rather than a physical line. Each era's run is the
same coordination game expressed in that era's fastest channel,
which is a standing warning: **the run is not defeated by making
the bank stronger; it is managed by making the belief that it will
run unprofitable**, and the channel through which the belief
travels always gets faster than the institution that has to answer
it.

## The state's three answers

The management of the run is done with three public instruments, one
per scale at which a run can form:

- **The deposit guarantee** removes the *household-scale* run by
  making the small depositor's line effectively infinite: no
  individual has anything to gain from queuing, so no queue forms.
  The guarantee does not make the bank safe — it makes the
  *depositor* safe up to the line, and the bank remains exactly as
  exposed as before; what has changed is who can run it.
- **The lender of last resort** — the central bank standing ready to
  lend, against good collateral, to a bank under pressure — removes
  the *wholesale-scale* run, because the banks that fund each other
  overnight do not queue if the central bank is at the back of the
  line. The standing doctrine, from 1890, has three parts: lend
  *heavily*, lend against *good collateral*, lend at a *penalty
  rate* — the price being the acknowledgment that the central bank
  has taken a position in the very asset whose quality it cannot
  fully see, in the hour it matters least to be wrong.
- **The resolution regime** — the rulebook for what happens to a
  bank that fails anyway: the equity is wiped, the debt is written
  down, and the healthy part continues, *without* a taxpayer
  bailout of the owners. The regimes built after 2008 are the first
  in which a large bank's death is a planned procedure rather than
  a negotiation, and their value is not that they prevent failure
  — they cannot — but that they change the *expectation*: a bank
  whose owners know they will be wiped out on failure prices that
  fact into today's lending, which is the whole point.

The honest residual is that all three are promises with a
credibility term, and the credibility term is what moves in a
crisis. A guarantee is only as strong as the public's belief that
the state will honor it when honoring it is expensive — which is to
say, always. The banking episodes of 2008 and of 2023 were the
market's audit of that belief: in 2008 the question was whether the
state would honor its promise to the *whole system*, and the
answer, at enormous cost, was yes; in 2023 the question was whether
it would honor the guarantee line to the *uninsured* balances of a
bank it had just let die, and the answer was a qualified yes that
took an emergency line of credit to deliver. The student of banking
should hold the general lesson: **the guarantee is a coordination
device, not an insurance policy** — its main function is to keep
the two-equilibrium game from flipping, and it can only do that if
the public believes it, and the belief is the one asset of the
system that cannot be collateralized, only demonstrated, in the
hour of the test.

## Credit: the bank's real product

The spread is the bank's margin; **credit is its product**, and
lending is where the bank's judgment — and the economy's
vulnerability — actually live. The bank's credit decision is a
calculation on three numbers:

1. **The probability the borrower defaults** — the chance, over the
   life of the loan, that the payments stop. The bank estimates it
   from the borrower's history, the industry's cycle, and the
   economy's.
2. **The loss given a default** — of the money that stops, the
   fraction that is not recovered: the collateral (the house, the
   machines) sold, at whatever the stressed market will give, minus
   the cost and the delay of selling it.
3. **The price that compensates for both** — the interest and the
   fees that make the expected loss, plus the bank's cost of
   funding and of holding the thin equity, equal to the return the
   money would earn elsewhere.

The art is in how the bank *learns* the first two numbers, and the
vulnerability is in the same place, because both are **cycle-
dependent**: a long expansion teaches the bank that defaults are
rare and recoveries are high, and the bank — rationally, from its
own experience — lends more easily into the late cycle, which is
what builds the defaults that the next downturn collects. Banks
lend best in bad times (the standards are recent, the spreads are
wide) and worst in good times (the standards are memory, the
spreads are thin). The regulatory answer — capital and liquidity
requirements that are *counter-cyclical*, heavier in the good years
— is an attempt to force the bank to remember the bad years while
it is still profitable.

At the household scale the same calculation is the mortgage
decision, and it is worth naming what the bank is really doing
there: it is selling *time* to a family, at a price that embeds the
family's expected employment over thirty years and the expected
price of the house that secures it. The two ratios behind the desk
— how much of the house's value is borrowed, and how much of the
family's income is spoken for by the payment — are the economy's
throttle in its most personal form: when the bank tightens them,
every household that was about to move, build, or refinance feels
the turn at once, which is why the mortgage market is the first
place an ordinary person sees the credit cycle, long before the
economy's headlines catch up with the banks' own books.

One more structural fact separates banking from the other half of
the financial system: the bank lends *exclusively*. The borrower's
loan is not a traded position with a market price that discovers
the risk continuously; it is a contract held to maturity by one
counterparty, and the risk is re-discovered only when it hurts — at
the next default, or at the next mark-down. The bond market prices
risk daily; the bank's loan book prices risk *on contact with
reality*, and contact with reality, in a long book, is thin and
late. That is why the bank's books can look perfect for years and
wrong for a quarter, and it is why the market — which watches the
bank's *traded* bonds and the equity — is usually one crisis ahead
of the bank's own reporting.

## The credit cycle: banks and boom-bust

The bank and the economy are locked in a feedback the rest of the
corpus covers at other scales — the real-estate note at the
household level, the markets note at the asset level — and the
banking system is where the two scales connect. Banks lend into
the boom; the boom's collateral values flatter the loans on the
books; the flattered books support more lending; and the more
lending pushes the collateral values up again. The loop is not a
malfunction, it is the *business model operating correctly* — each
round of it is a rational decision on the information available —
and that is exactly why it cannot stop itself: no single bank,
looking at its own book, sees the loop. It sees only that its
collateral is performing and its borrowers are improving, which is
the *output* of the loop, not a signal to step away from it. The
information each bank has is locally true and globally the engine
of its own failure, and that is the credit cycle in its purest
statement.

The turn runs the same loop in reverse, and it is the reverse that
is the economy's real injury. When collateral values fall, the
flattered books become the impaired ones; the impaired books
tighten the standards; the tightened standards contract the supply
of credit — from the banks, from the borrowers' own banks, at the
moment the economy's need for patient money is largest, because the
downturn is exactly when the good borrower and the bad one are
hardest to tell apart, and the bank's rational move under
uncertainty is to lend to fewer, safer people, which leaves the
healthy ones unfunded and the whole system running on less fuel
precisely when it most needs it. This **credit cycle** is the
banking system's deepest contribution to the boom-bust pattern,
and it is why "the banks are fine" and "the economy is fine" are
not the same sentence.

The policy consequence follows directly and is often missed: the
response to a banking crisis that saves only the failing bank, and
not the *lending* the bank was doing, fixes the balance sheet and
contracts the economy — because the loan book was the product, and
the product has now vanished with the maker. The full response
backstops the credit supply itself — standing ready to lend
against the good collateral of the surviving banks, so that the
healthy borrowers can still be found — and that is why the central
bank's actions in a banking crisis look, to the untrained eye, like
a rescue of the banks, when they are in fact a rescue of the
economy's *future lending*. The graduate habit: read a banking
crisis as a *statement about the credit cycle's phase*. A crisis
late in a long expansion is a signal about where the economy's
borrowing was; a crisis early in a downturn is a signal about how
much of the loop has already turned. The same bank failure means
different things in the two places on the cycle, and the person who
dates the crisis gets the policy — and the portfolio — half right
for free.

## The plumbing and the creation of money

Behind the balance sheet is the **payment system**, and the modern
version is less romantic than the word suggests:

- **The accounts are entries, not objects.** Your deposit is a
  ledger line at the bank; the bank's reserve is a ledger line at
  the central bank. "Moving money" is updating two ledgers, and the
  speed of the modern system is the speed at which the ledgers
  agree with each other.
- **The card and the app are the retail layer** — authorizations
  against lines of credit or balances, settled in batches, the
  convenience layer built on the ledger layer.
- **The large-value systems are the wholesale layer** — the
  central-bank-operated rails on which the big transfers move, in
  real time, irrevocably. The stability of this layer is what the
  phrase "the plumbing" means, and it is why a failure of the
  plumbing — which has happened, in every era of the technology —
  stops the economy in a way that is not an economic event at all,
  but a *mechanical* one: the ledgers stopped agreeing.

The deeper fact, the one that connects this note to the money note:
**most of the money in the system is not cash and was not made by
the central bank.** It is the deposit entries that banks create
when they lend — the loan *makes* the deposit, not the other way
round. When the bank lends 100, the borrower's account rises by
100; the money exists from the moment of the loan. This is
**credit creation**, and it is why the banking system, and not the
central bank, sets the day-to-day quantity of money in the economy
— and why a banking crisis is, automatically, a *money supply*
crisis, whatever the central bank's balance sheet says.

The graduate version makes the division of labor exact. The central
bank creates the *base* — the reserves at its own books — and sets
the price of that base; the banks, through the gap, decide how much
of the *derivative* money exists, and the derivative is the layer
the public actually touches: every card payment, every payroll,
every deposit is derivative money. The popular "money multiplier"
story inverts the causality — it describes the banks as lending
out the central bank's cash, a multiple times, until the multiple
is used up — but the actual mechanism runs the other way: the
lending comes first and the reserve position is settled *after*, by
the bank borrowing what it is short. The multiplier is a
description of an accounting identity, not a machine, and the
machine's operator is the lending decision. The consequence for the
whole system: when the gap tightens — when banks stop lending in a
credit contraction — the derivative money *shrinks even while the
base is untouched*, and that is the channel by which a banking
crisis becomes a monetary event and then a deflationary one, the
debt-deflation mechanism of the money note running on the plumbing.
The central bank can flood the base; it cannot flood the gap. The
gap is a decision, made daily, ten thousand times a day, by
lenders.

## What a deposit is, honestly

The note now turns to the private person. First: what your money
is, sitting in a bank account.

It is, in law, a **debt of the bank**. You are not holding the
bank's money in a box; you are a *creditor* of the bank, ranked
alongside every other depositor, above the shareholders, and — up
to the guarantee limit — backed by the state. The practical
consequences, plainly:

1. **The limit matters, and it is per institution.** Split
   balances above the guaranteed limit across banks, or into the
   instruments the guarantee covers differently; the limit is a
   number per bank per person, and the un-guaranteed excess is, in
   a run, exactly the run that the guarantee exists to prevent.
2. **The bank's health is your credit risk.** A deposit is as safe
   as the bank, up to the line. In the calm decades this made no
   practical difference; in 2023 it did, for the balances above the
   line, and the lesson generalized: *the name on the account is
   part of the risk*, not just the rate.
3. **The cash alternative** — physical cash is the one money that
   is not a debt of anyone; it is the central bank's promise
   directly. The system assumes almost nobody holds it, and for
   almost everybody that is rational; the fraction who keep some is
   the fraction who have thought about what a run *is*.

And one more that the calm decades never forced on anybody: **the
deposit is also a bet on the rate path.** The deposit pays the rate
the bank chooses, and the bank chooses it slowly; in an era of
rising rates the deposit lags the new market rate for the whole
transition, which means the *real* return on the deposit is set by
the speed of the rate move, not by the bank's stated number. The
money note covers the arithmetic; here the banking fact is that
the deposit is the one "safe" instrument whose safety and whose
return are set by the same institution — the bank — and the person
who wants both should know which of the two they are actually being
paid for.

## Regulation: a century of learning

The regulatory record, read as a sequence, is a sequence of
one-crash-behind responses:

1. **The 1930s** — the crash of the decade, which was a run
   repeated a thousand times, produced the two standing
   instruments: the deposit guarantee and the central bank's
   accepted role as lender of last resort. The lesson taken: the
   run is a public problem and is therefore answerable by public
   instruments.
2. **The decades after** — the lesson that *capital* is the private
   answer: the equity layer, the buffer that absorbs losses before
   the promise is tested. For a long time the argument was about how
   thick the buffer should be, and the argument ran mostly in the
   units of the regulators' own models, which is how the next era
   begins.
3. **1990s to 2007 — the model era.** Risk-weighted capital: the
   buffer's size is set by *models* of the risk on each asset, and
   the models said that the new, complex, long-dated paper was no
   riskier than a government bond, so it needed little buffer. The
   era's achievement — a system that appeared, on its own
   instruments, to be safer than any in history — and its failure
   are the same sentence: **the measurement became the target**,
   and the system optimized the measurement. The 2008 crash was
   the moment the system discovered that its capital was, in large
   part, a number its own models had signed.
4. **Post-2008 — the structure era.** The response was less about
   the size of the buffer and more about its *quality* and about the
   other two structural facts: higher and better capital, a
   standing liquidity requirement (the bank must hold enough of the
   very liquid stuff to survive a short, severe stress on its own),
   counter-cyclical buffers that thicken in the good years, and the
   resolution regime that makes failure a procedure. The explicit
   target: a system in which *no bank is too big to fail*, because
   the 2008 lesson included the fact that the guarantee's
   credibility had been spent on the banks themselves, and the
   system's size had become part of its safety.
5. **2023 — the audit.** The small-bank episode that followed a
   fast rate rise: the banks that held long-dated, low-yield paper
   through the calm years found the paper's *market value* falling
   fast when the rates rose, the losses sat on the books
   unrealized, a run formed in a day through the new channels, and
   the public instruments had to be used — the guarantee honored,
   the loss covered, the run stopped in hours. The lesson of the
   episode, the one the next era of rules will answer: **the calm
   years' rate environment was itself the risk** — a decade of
   rates near zero taught every holder of long paper that duration
   was free, and the return of the normal rate charged the fee in
   one move.

The pattern of the five acts is the graduate summary: **each
era's regulation is a faithful answer to the previous crash and a
blind spot for the next one**, because the crash that answers it is
always the one the current era has made cheap. The student's habit
is to ask, of any regulatory regime, what it *assumes will not
happen* — that assumption is where the next crash will come from,
and the size of the assumption, not the elegance of the rules, is
the measure of the system's fragility. A regime that assumes
depositors will never look, models will never lie, and rates will
never move is a regime built to be broken, and the only honest
question to ask of the current one is which of the three it is
weakest on.

## What it means for a person

The synthesis, because this is the note's purpose and the rest of
the material exists to serve it.

The private person meets the bank twice, on opposite sides of the
gap, and the two meetings are one risk:

- **As the depositor**, you are on the short side of the
  transformation — you have given the bank money it will lend for
  thirty years, in exchange for convenience, a stated rate, and the
  state's promise up to a line. Your exposure is the one described
  above: the bank's health is your credit risk, the line is your
  safety, and the stated rate is your *rate-path* exposure. The
  three standing moves: keep the important balances under the
  guarantee line, spread the excess across institutions rather than
  stacking it in one, and know that the rate you are quoted is a
  number the bank updates slowly, in a direction you cannot choose.
- **As the borrower** — the mortgage is the other side of the same
  transformation, and it is the larger meeting, because it is the
  one that runs for decades. You have received the bank's long
  money: patient, fixed (if you fixed it), and now, in the
  rising-rate era, *scarce relative to what it was a year ago*. The
  borrower's standing position, which the money note stated and
  this note completes, is that **your mortgage is the bank's
  balance sheet with your name on the other side**: the bank's
  boom-bust loop is your payment schedule, the credit cycle's
  contraction is your refinance option, and the rate path is the
  variable your fixed and your variable portions bet on in opposite
  directions.

The three moves that follow the two meetings:

1. **Match the gap's length to your life.** The transformation
   works because the bank pools many short promises into one long
   one; your life is a single long promise — the house, the
   decades — and the honest question is not "is this rate good?"
   but "what happens to me if the bank's side of the gap tightens,
   in the year my flexibility is lowest?" The fixed-rate mortgage
   is the answer that closes the gap for you; the variable one is
   the bet that the gap stays cheap, and it should be the choice of
   the person whose income is more certain than the rate path.
2. **Read the bank, not just the rate.** The name on the account is
   part of the risk; the guarantee line is the safety; and the
   *kind* of bank is the third term — a large system bank and a
   small community bank are different bets on the resolution regime
   and on the rate path, and the stated rate is the one term of the
   three that both advertise.
3. **Know what the run is, so you can recognize it in the news.**
   The run is a belief forming; the guarantee is the promise that
   stops the belief; and the hour of the test is the only hour in
   which either of them is a fact rather than a claim. The person
   who has read this note will see the 2023-style episode in a
   headline and know the sequence — the belief, the queue, the
   promise, the test — before the sequence is finished, which is
   the whole practical return of the subject.

The bank, in the end, is the economy's **time machine**: it takes
the world's short, nervous money and turns it into the long,
patient money that houses and factories are built with, and it is
paid the spread for the transformation, and it has spent two
millennia learning — in crash after crash — how thin the margin is
between the transformation and the fire. The private person's share
of the lesson is the smaller and the sturdier one: you are one link
in the chain of short promises the machine runs on, and the
machine's whole history is a record of what happens to the links
when the machine hiccups.
