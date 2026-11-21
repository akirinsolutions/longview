# How Markets Actually Work
~ field: Markets
~ summary: Where prices come from: a continuous auction in which every price is a bet, a signal, and a hand-off of risk all at once.

## What a market really is

Strip away the screens and the headlines and a market is a very old
thing: a place where strangers agree to swap something now for
something later. A farmer exchanging grain for a plough was running a
market. A stock exchange is running one. The difference is scale and
speed, not kind.

The defining feature of any market is that it does not produce anything.
It only *reallocates* things. The share traded at midday was not made
any more valuable by the trade; what changed is **who holds it** and,
with it, who carries the risk of it. That word "risk" is the most
important word in this whole note, because markets are, at bottom,
machines for moving risk between people.

Two more properties matter. First, a market needs *liquidity*: enough
buyers and sellers standing ready that you can act on your view without
waiting, and without the act itself wrecking your price. A market for
blue-chip shares is deep; a market for a single company's private
debt is nearly dry. Second, a market needs *trust in the mechanism* —
that the counterparty's performance will be settled honestly. Every
market in history has been an answer to a trust problem.

The institutional history is a record of that trust being engineered.
A medieval market town relied on the town itself: the lord collected a
toll, which was an economic argument for keeping order, because
disorder drove away the traders who paid him. The joint-stock
companies of the early 1600s that created the first exchanges — the
Amsterdam and London companies — invented the exchange as a *room with
rules*, because shipowners and investors would not trade in each
other's private warehouses. The clearing house, the depository, the
self-regulatory body: each a later layer of the same construction, each
a machine for making the counterparty less important than the contract.
A modern trading platform is the same idea at industrial scale: the
reason a household can sell a share to a stranger on another continent
and sleep well is that a dozen institutions between them have each
taken a slice of the risk that the other side will not show up.

## How prices are formed

When you buy a share, you are not buying it from "the market" as if
the market were a shopkeeper. You are buying it from **another person
who just decided to sell**, and the price you pay is whatever the last
agreement between a buyer and a seller happened to be. This is called
**price discovery**, and it happens continuously: an auction with no
auctioneer, in which thousands of orders — each one a person or a
machine expressing *I will buy if it is this cheap* or *I will sell if
it is this rich* — are matched against each other.

The matching itself is a queue, and the queue has a structure worth
knowing. Buy orders rank from most aggressive down; sell orders from
least. An order willing to cross the current gap — to buy at the
seller's price rather than wait — is a **market order**, and it
consumes whatever sits on the opposite side. An order that names a
price and waits is a **limit order**, and it *is* the price: the best
limit order on each side, together, defines the current quotation. So
the "price" on the screen is not a computed value at all; it is the
two most impatient people in the queue, frozen into a number.

A price is therefore not a measurement. It is not like the
temperature. A temperature is what the thermometer finds; a price is
what the most recent two nervous strangers agreed on. It is a
**signal**, and like all signals it is noisy. It carries information —
about the company, about the economy, about what all other traders
expect — but it also carries mood, herding, and the random churn of
people selling for reasons that have nothing to do with value: a house
sale, a pension maturity, a fund's quarterly rebalance.

That last point is the source of most confusion about markets. When a
price moves, the first instinct is to look for what *happened*.
Sometimes something did happen. Often, a price moved because someone
needed the money, not because the world changed. Learning to tell
those two cases apart — **news moves** versus **plumbing moves** — is
a large part of what financial maturity is.

## The order book, laid bare

The queue above — the **order book** — is the actual object a market
is made of, and its anatomy explains most of the practical facts about
trading costs.

- **The spread.** The gap between the best buy and the best sell is
  not friction in the physical sense; it is *pay*. The people standing
  on both sides at once — market makers, funds holding inventory — are
  doing a dangerous job: they have bought things they may have to sell
  into a falling market. The spread is their compensation for that
  **inventory risk**. A market for a safe, liquid, boring asset has a
  thin spread; a market for something volatile and scary has a thick
  one. So the spread is itself information: a sudden widening is the
  market telling you that standing ready has become expensive.
- **Depth.** The price at the top of the book is the price of a *small*
  trade. To buy more, you must work down the queue, at successively
  worse prices. **Market impact** — the cost of being large — is this
  working-down, and it grows worse than proportionally: doubling the
  size of your order more than doubles the cost, because you are
  consuming the book rather than taking a price off it. This is the
  deepest reason institutions split their orders across hours: the
  price you get is a function of how fast you arrive.
- **Paper liquidity.** In calm times the books look deep and the
  spreads thin; in a panic the same books become thin and the spreads
  enormous, because the people who were standing ready are the same
  people who must now defend their own positions. Liquidity is not a
  property of the asset; it is a property of *who is standing, and
  what they are afraid of*. Every crisis in the last century has
  included the moment when assets that had been perfectly liquid
  ceased to be — not because their value was in doubt, but because
  the queue of willing buyers emptied at exactly the moment the queue
  of forced sellers filled up.

The practical lessons are two. Size matters: the same trade costs a
retail saver a rounding error and an institution a percentage point,
and the difference is not a fee, it is physics. And timing matters:
the book is a different animal at nine in the morning than at noon,
and a different animal still in the first minutes after a headline.

## Who is actually in the room

A useful map of the participants, because each one trades for a
different reason and that reason shapes the price:

- **Owners** — people and institutions who hold assets for the long
  term: pension funds, endowments, insurers, families, index funds.
  They are generally sellers when markets fall and buyers when they
  rise (forced by their mandates, not by wisdom), which is one reason
  markets can overshoot in both directions.
- **Traders and asset managers** — paid to move money when they think
  they can profit from the move. They add liquidity (they stand ready
  to buy and sell) but they also chase, and chasing is what turns
  wobbles into trends.
- **Hedgers** — people who use markets to *remove* risk from
  themselves: an airline buying protection against fuel, a farmer
  locking a sale price, a fund protecting a portfolio. Hedgers are the
  quiet backbone of the whole system; the markets exist largely to
  serve them.
- **Speculators** — people who take on risk that someone else wanted
  to get rid of, for a fee or a profit. Speculation has a bad
  reputation, but a market without speculators is a market without
  buyers, and a market without buyers is not a market.
- **The venue and its rules** — the exchange, the clearing house, the
  regulators. They set the ground rules that make the other four
  willing to show up.

The price you see is the residual of all these motives colliding.
That is why prices are informative without being omniscient.

A second layer of the map is worth drawing: *the asymmetry of
flows*. At any moment, more money in the market is moving for reasons
of circumstance than for reasons of conviction. The pension fund
selling because of a contribution, the fund raising cash because of
redemptions, the household selling because of a divorce — all of them
are **informed about nothing**, and all of them move the price. The
people with a *view* — a conviction about what something is worth —
are the minority of the flow, and the price is the sum of a majority
of circumstance and a minority of conviction. That is why a price can
be "wrong" for months: the view-people have to buy enough to overcome
the circumstance-people, and the circumstance flow is what makes
their work slow and expensive.

## The efficient market idea, stated honestly

The **efficient market hypothesis** is the idea that prices already
reflect all available information, so that no one can *reliably* beat
the market by studying it. In its strong form it is clearly false —
people do beat markets, for a while, sometimes for a long while, and
some of them understand why. In its weak form it is probably true in a
way that matters for most people: information moves fast, lots of
smart people watch the same data, and by the time a fact becomes
common knowledge it has usually already been priced.

A graduate version separates the three claims that are usually
bundled: **weak-form efficiency** — past prices do not predict future
prices, because any pattern readable from the price history is
competed away; **semi-strong efficiency** — public information
(filings, earnings, headlines) is priced within minutes to hours; and
**strong-form efficiency** — even private information is already in
the price, which is plainly false, because the whole history of
insider-trading law is a history of it being otherwise. The first two
are approximately true in deep markets, with the errors getting
larger in smaller markets and in rarer events; the third is false,
and the law exists because it is false.

The honest working version is this: prices are *roughly* right, they
react *quickly* to news, and the error bars are biggest when the news
is emotional, unusual, or slow. Markets are least reliable exactly
when they feel most dramatic. That single observation does a lot of
work: it is why the boring strategies (broad index, held for decades,
rebalanced on a calendar rather than a headline) have, over the long
run, beaten most of the exciting ones.

The modern synthesis is the **adaptive markets** view: markets are
ecosystems, not equations. The set of strategies chasing a pattern
grows until the pattern is eaten, then shrinks until it re-emerges.
Efficiency is therefore not a state a market *has* but a population it
*maintains* — high in boring times, low in novel ones, and recovering
as the specialists relearn. This is a better model than either the
cult of efficiency or its dismissal: it predicts that your edge, if
you have one, has a half-life.

> A market can be wrong for a longer time than you can stay solvent.
> The efficient market hypothesis is not a promise that prices are
> true. It is a warning that your certainty is more likely to be the
> error than the price.

## Two systematic signatures: momentum and reversion

If prices were pure noise — random walks with no structure — studying
them would be astrology. They are not. Two patterns are robust enough
across markets, centuries, and asset classes to be treated as
permanent fixtures of the furniture, and both carry implications a
graduate of the market should keep in pocket.

- **Momentum** — the tendency of recent winners to keep winning, and
  recent losers to keep losing, over a horizon of a few months to a
  year or so. The mechanism is not a single one; several run together.
  Information *diffuses*: when a fact is true but not yet known to
  everyone, prices creep in the right direction as the knowers buy
  ahead of the finders. And participants *extrapolate*: a trend is
  the easiest model in existence, and the flow of trend-following
  money keeps the trend alive past its reason.
- **Reversion** — at horizons beyond that, the same names drift back.
  What the momentum phase paid for — the enthusiasm, the stretched
  valuation — works in reverse: the growth that disappointed the
  extrapolators disappoints again, and the cheapness that the panic
  priced turns out to have been an invitation. Over a multi-year
  horizon, past returns are a weak but persistent *negative*
  predictor of future returns.

The two signatures coexist on different clocks, and the practical
lesson is about **horizon**: the market is a momentum machine on the
short clock and a reversion machine on the long one. Most of the
damage people do to themselves is running the short-clock strategy on
the long clock (chasing a winner they must hold for a decade) or the
long-clock one on the short one (averaging down into a falling knife
that is not done falling). The signatures themselves can no longer be
traded cheaply — the specialists have them — but they can be
*avoided*, and the avoiding is where the ordinary investor's edge
actually lives.

## What markets do for the economy

A market's value to an economy is not that it lets people get rich.
It is that it performs two functions that nothing else does at scale.

1. **Pricing risk.** When a thousand investors can buy a company's
   shares, the company can raise the money it needs to build, hire,
   and invent, without borrowing it all as debt. The price of those
   shares is the economy's running verdict on how much that company's
   future is worth — a verdict that updates daily and that the company
   itself reads.
2. **Pooling risk.** One household cannot absorb a factory closing.
   A diversified market of millions of households can. Markets turn
   local, private, devastating risks into small, shared, priced
   slices — the original idea behind both equities and insurance.

A third function is subtler: **discipline**. The market price is a
standing referendum on how capital is being used. Companies whose
capital is being destroyed find it harder to raise more. That
discipline is imperfect and can be cruel in the short run — a company
building something that takes ten years will look terrible in year
nine — but without it, capital drifts to the loudest uses rather than
the best ones.

The size of these functions is worth grasping. The bulk of what an
economy *owns* — the machinery, the factories, the intellectual
property, the farmland — is held by investors who are not its owners
in the operational sense: a few billion shareholders, most holding one
small slice, collectively own the productive assets of the advanced
economies. The market is the machinery that makes that separation
possible — capital owned by millions, operated by a handful — and it
does so by converting a single huge, indivisible, uninsurable risk
(one company's future) into a cloud of small, diversifiable, priced
bets. Economies with deep markets grow faster than similar ones
without them, and the correlation is not merely that rich countries
happen to have both; the mechanism is the conversion above, and it is
the reason an economy's wealth is a function of how *liquid* its
ownership is, not just how large it is.

## Markets extended in time: derivatives

The cash market — spot prices, settled now — is only half of the
market system. The other half is a market in *the future*, and it is
arguably the half that makes the first one work.

A **futures contract** is an agreement, struck today, to buy or sell
something at a price fixed today, at a date in the future. The price
in it — the **futures price** — is not a prediction in the mystical
sense; it is the no-arbitrage consequence of the cost of carrying the
thing: the spot price plus storage and financing costs, minus the
convenience of holding it. That is why the futures curve can be
*upward* (the thing is scarce to store: the world is paying for the
privilege of not waiting) or *downward* (the thing is expensive to
hold, or abundant: the world is paying to get rid of it). The shape of
that curve is itself a statistic about scarcity — the same logic that
makes the yield curve a statistic about patience.

Who uses them, and why they matter:

- **The hedgers.** The airline locking fuel, the farmer locking a sale
  price, the miner locking a metal price: they pay the market to
  *remove* the risk from themselves, and in doing so transfer it to
  someone else. The hedge is a premium paid for certainty, and the
  price of that premium is the futures cost.
- **The risk-takers.** The other side of every hedge is a party that
  accepted the risk — usually for a spread, usually with a view — and
  this is the speculator's real economic function: to be the standing
  offer of risk-absorption that makes hedging affordable.
- **The arbitrageurs** — the people whose job is to keep the futures
  price from drifting away from its no-arbitrage price. They are the
  market's immune system, and in a panic their *capacity*, not their
  willingness, is what breaks.

**Options** extend the same idea one step further: a contract on a
*contingency* — the right, not the obligation, to buy or sell at a
price in the future. The market for options produces a statistic no
other instrument can: a *price for uncertainty itself*, the market's
own estimate of how far the underlying can move. That number — the
volatility embedded in option prices — is the market speaking directly
about its own mood, and it is why the options market, in a sense, is
the only place where fear has a quoted price.

The reason to take this section seriously is that most of the
plumbing of the modern financial system lives here: the
interest-rate derivatives that let a bank convert a floating
liability into a fixed one, the credit derivatives that let an
insurer sell the tail of its own loss distribution, the index futures
that let a fund reposition without trading the underlying thousand
positions. The cash market is the market; the derivatives market is
the market's *immune and circulatory system* — and it is the part that
fails in crises, not because its ideas are wrong, but because its
participants are the most leveraged people in the room, and the
leveraged are the first to be forced out.

## How markets talk to each other

No market is an island, and the graduate version of that truism is a
mechanism, not a mood. The channels through which a move in one
market becomes a move in another:

- **The common risk factor.** Most assets in a given economy are
  claims on the same underlying thing: the growth of that economy. A
  piece of news that changes expected growth — a central-bank decision,
  a jobs report, a war — moves *all* claims on growth at once, which
  is why a bad morning in the stocks is usually a bad morning in the
  bonds and a bad week in the housing market. This is the boring
  channel, and it is the one diversification is built to exploit:
  hold claims that answer to *different* drivers.
- **The liquidity channel.** The dangerous one. In a stress event the
  same forced sellers — funds facing redemptions, leveraged traders
  facing margin calls — sell *everything they hold*, because the
  constraint is cash, not judgment. The asset that "should not" fall
  falls, because the selling is not about that asset. This is why
  correlations between uncorrelated assets *rise* in a crisis: the
  liquidity factor becomes the dominant factor, and for a few weeks
  everything is a proxy for the same thing — cash.
- **The expectations channel.** Rates and inflation expectations are
  a single object that every asset is priced against. A shift in what
  the market expects the central bank to do moves stocks, bonds,
  currencies, and property simultaneously, because the discount rate
  inside all of them moved. The assets disagree about *how much* to
  move — the one whose cash flows are longest in the future moves
  most — but they move in concert.

The practical lesson is about **when** diversification works. It is a
device that works in the ordinary world — the common factor calm, the
liquidity channel idle — and it fails exactly in the world that
diversification was *for*, the stressed one, because in severe stress
the liquidity channel subsumes the others. The honest formulation:
diversification is a way of not caring which *particular* bad
scenario happens, at the cost of caring that *a* bad scenario
happens. It reduces the variance of the ordinary; it does nothing for
the tail. Anyone who has built a "diversified" portfolio that fell in
one move in a crisis has learned the distinction the hard way; the
point of knowing the mechanism in advance is to size positions for
the day when the channels couple.

## The life of a price move

Watch a single day of a market and you can usually identify the same
cast of scenes repeating:

- **The open** — a burst of activity as overnight information
  (foreign markets, a late earnings call, a headline) is absorbed in
  a few minutes of aggressive trading. Opens are noisy; much of the
  open is the market catching up with itself.
- **The drift** — the long middle of the session, when prices trade
  on the day's net of orders. Trends form here, and trends have a
  habit of continuing for a while even after their reason has run
  out, because momentum traders ride them.
- **The close** — a second burst, as funds hit targets, indexes are
  computed, and the day's price is *declared*. The closing print
  matters more than the rest of the day to most participants, which
  creates its own distortions.

The lesson of the scenes is that **when** a price happens matters.
The same price at nine-oh-two and at fifteen-fifty-seven is not the
same information, because the *mixture of people* agreeing to it is
different. Anyone who buys or sells needs to be aware that they are
joining one of these scenes, not standing outside them.

The same scene-logic runs at longer clocks. A week opens with the
market absorbing the prior week's close and the weekend's news; a
month opens with the repositioning of funds that rebalance on
calendar dates — a flow of buyers and sellers that is mechanical,
recurring, and *uninformed*, which is why the first and last day of a
rebalancing month trade differently from the middle. And a year opens
with the annual reports and the institutional review of the prior
year's bets. The practitioner's map is therefore not "the market" but
a calendar of *who is forced to act, and when* — because the most
predictable trades in the world are the ones whose motive is the
calendar rather than the news.

## Why markets crash

Crashes are the event everyone asks about, so the mechanism deserves
its own section. A crash is almost never a discovery of new bad
information in one instant. It is a **coordination failure**: a
moment when enough participants, for reasons that individually are
defensible, decide at the same time to be rid of the same assets.

The standard ingredients:

1. **Leverage.** Borrowed money turns a ten-percent fall into a
   thirty-percent forced sell, because lenders start demanding the
   debt be paid. This is the amplifier — it is why crashes are
   crashes and not just bad afternoons.
2. **Correlated triggers.** Margin calls, fund redemptions, and stop
   orders are all *automatic* sellers: they fire because of the price,
   not because of a judgment. One seller's trigger becomes another
   buyer's absence, the price falls further, and more triggers fire.
3. **The disappearance of the bid.** In a calm market, someone is
   always willing to buy at a slightly lower price. In a panic, the
   queue of buyers thins faster than the queue of sellers grows, and
   price discovery literally breaks: trades happen at prices no one
   would have quoted a minute ago, because the only people left
   trading are the ones who must trade.

The arithmetic of the first ingredient is worth stating precisely,
because it is the difference between a correction and a crash. A
borrower who has bought an asset worth a hundred units against a
ninety-unit loan is fine while the asset holds ninety-odd: a ten
percent fall still leaves the asset worth more than the debt. But the
lender's contract is not "sell when you lose ten percent"; it is
"sell when the asset falls below *X*, a line set when the market was
calm." The trigger is a line, not a percentage, and lines do not move
with the asset. So the fall that crosses the line converts a *value*
problem (the asset is worth less) into a *liquidity* problem (the
asset must be sold *now, at any price*) — and a liquidity problem
does not care what the asset is worth, only what it can be sold for
in the next hour. This is the entire mechanism of a crash in one
sentence: **the conversion of a slow variable (value) into a fast one
(liquidity), at a trigger that was set when the world was calm.**

The resolution is also mechanical: leverage has to leave the system
before prices stop falling, because leverage is what makes the
falling self-reinforcing. That is why crashes, in a sense, are
*good* for the system — they are the expensive, violent way in which
excess borrowing is flushed out — which is also exactly why they are
so traumatic for the individuals inside them. The history of the last
century is a series of the same mechanism at different scales: the
leveraged house market of the early 1930s, the leveraged bond market
of 1974, the leveraged housing market of 2008, the leveraged index
fund of 2010. Each was, in its week, "unrelated to the others"; each
was, in its mechanism, the same event. (The housing note deals with
the same mechanism at the scale of one household.)

## What a market cannot do

The final section is the negative one, because it protects you.

Markets are excellent at one thing and useless at another. They are
excellent at **aggregating**: compressing the dispersed knowledge of
millions into a single number. They are useless at **knowing**: that
number is a bet made by the last person, not a fact. It cannot tell
you what a company is worth; it can only tell you what the last buyer
was willing to pay, today, in this mood, under these constraints.

Three corollaries follow, and they are worth memorizing because each
defeats a common temptation.

- **A price is a statement about willingness, not about truth.** The
  same asset can be "expensive" by a cash-flow arithmetic and "cheap"
  by a sentiment arithmetic, and both arithmetics are running in the
  room at the same time. The market's number is the compromise, and a
  compromise is a starting point for your own arithmetic, not an
  answer to it.
- **A price can be right and wrong at once, in the sense that
  matters.** It can be correct about the *next year* and wrong about
  the *next decade* — because it is a short-horizon object used, by
  most people, to make long-horizon decisions. The mismatch of
  horizons is the standing source of both market bubbles and market
  panics.
- **A price does not include what the market cannot see.** The
  unknown — the technology that has not happened, the regulation that
  has not been written, the war that has not started — is absent from
  the number by construction, because a price is a statement about
  what is *known to the people who are trading*. The market is as
  smart as its room; a room cannot know what it has not heard.

So the mature use of a market is humble. Use the price as a *very
good* estimate that is usually close to right, update fast, and
sometimes wrong by a lot for a while. Buy at prices you can defend
when the estimate is wrong. And remember that the market is not a
thing that happens to you from outside — it is a room you are in, and
one of the people in it is you.
