# Bordeaux Index LiveTrade — a better class of evidence

7 October 2026. Read live from bordeauxindex.com through the desktop browser pane.
All prices **In Bond, GBP, Original Case, Pristine**, per case as listed.

---

## The finding that matters

LiveTrade is not a merchant list. It is a **two-sided marketplace** that publishes,
per wine and per format:

- the **best bid** — what a buyer will pay today
- the **lowest offer** — what you would pay to buy
- the **last executed trade**, with its date
- on some lines, the **full bid ladder** beneath the best bid

This is categorically better evidence than a merchant's asking price, and it
changes what our reference number can mean.

**A merchant ask is an aspiration. A bid is executable demand.** Our whole model
is "sell at a discount to market so it moves". Where a live bid exists, the
discount question partly dissolves: there is a price at which someone has already
committed to buy.

### How the columns were verified

The semantics were not assumed. `.bid-button` carries the left price, `.offer-button`
the right, and in **every two-sided row observed the left price was below the
right**. Offers cannot sit below bids in a functioning market, so the direction is
settled. The `.bids` ladder on Krug 167ᵉ confirmed it again: £908 best bid, then
£875, £870, £819, £784, £733, £600, £590 descending beneath it.

---

## Krug Grande Cuvée — what actually has a market

Doug's cellar holds **no vintage Krug at all** — 454 bottles, every one Grande
Cuvée. So BI's 90 rows of vintage Krug (1964–2004) are irrelevant to this deal,
and only the editions matter.

### Edition-blind generic "Krug, Grande Cuvee" (NV, vintage code 1000)

| Format | Best bid | Lowest offer | Last trade | Date | Per bottle (bid–offer) |
|---|---:|---:|---:|---|---|
| 1 × 75cl | £135 | £240 | £209 | 04/10/2026 | £135–£240 |
| 6 × 75cl | £1,239 | £1,800 | £1,265 | 24/08/2026 | £207–£300 |
| 12 × 75cl | £2,500 | £2,880 | £2,500 | 10/06/2026 | £208–£240 |
| 12 × 37.5cl | — | £666 | £1,200 | 10/09/2026 | £55.50 per half |
| 6 × 150cl | — | £1,517 | £1,670 | 22/06/2026 | £253 per magnum |
| 1 × 150cl | — | £165 | £331 | 21/01/2025 | £165 per magnum |

**The spreads here are wide** — £135 to £240 on a single bottle is 78%. That is the
signature of an edition-blind product: buyers and sellers are not pricing the same
thing, because 156ᵉ and 169ᵉ are not the same wine. Do not take a midpoint.

### Edition-specific

| Edition | Format | Best bid | Lowest offer | Last trade | Date | Spread |
|---|---|---:|---:|---:|---|---|
| **167ᵉ** | 6 × 75cl | **£908** | £977 | **£904** | 14/09/2026 | **7.6%** |
| 167ᵉ | 1 × 75cl | — | £169 | — | | one-sided |
| 162ᵉ | 6 × 75cl | £660 | £1,596 | — | | 142% |
| 162ᵉ | 1 × 300cl | £1,022 | £1,350 | £1,106 | 18/09/2026 | 32% |

**Krug 167ᵉ is the model line.** Bid £908, last trade £904, offer £977 — a 7.6%
spread straddling a recent executed trade. That is a real, liquid market, and it
prices at **£151.33 a bottle at the bid**.

**Krug 162ᵉ is the warning.** Bid £660 against an offer of £1,596 on the same
format is not a market; it is two people a long way apart. A reference built from
the midpoint of that would be fiction. Any line whose bid–offer spread exceeds a
threshold we set should be refused, not averaged.

---

## What this means for the cellar

Doug holds 324 bottles of Grande Cuvée at 750ml across 14 editions, plus 107 at
375ml and 23 at 1500ml.

**Live edition-specific market found: 167ᵉ and 162ᵉ only.** Doug holds 48 bottles
of 167ᵉ and 6 of 162ᵉ. On the 167ᵉ bid, those 48 bottles are worth roughly
**£7,264 executable today** — not an estimate against a merchant ask, an actual bid.

The other twelve editions have no live BI market. For those the choices are:

1. Use the **edition-blind generic** as the comp — but its 78% spread makes it
   nearly worthless as a reference, and it would under-price the older editions
   that carry a premium.
2. Find merchants who list by edition. This is the real answer and it is what
   the rest of the sweep is for.
3. Leave them NO_MARKET and sell them on relationship rather than reference.

### Halves are tradeable after all

Earlier I flagged that 95 bottles of 168ᵉ in 375ml might not price, because policy
excludes halves from 750ml comps. **BI has a half-bottle item code (`KRUNVH`) and a
12 × 37.5cl market** — current offer £666 a case (£55.50 a half), last trade £1,200
(£100 a half).

So halves trade, but that gap between the last trade and the current offer is
nearly 2:1 — thin and volatile. Those 95 bottles are worth pursuing with a proper
same-format comp, not writing off.

---

## Identity: BI names the same wine two different ways

On the producer and search pages: **"Krug, Grande Cuvee 167eme Edition"**.
On the marketplace pages: **"NV Krug Grande Cuvee Edition 162"**.

Comma, word order and edition suffix all differ between BI's own surfaces. Any
adapter reading BI must normalise both forms to the same identity, and the edition
number must be extracted from either position. This is decision 0019's problem
appearing in live data, and it confirms that anchoring the release code to the end
of the string is not sufficient on its own.

Useful corroboration: **BI assigns each edition its own LWIN11.**

| Edition | LWIN11 | Edition | LWIN11 |
|---|---|---|---|
| generic | 10824121000 | 165ᵉ | 15468641000 |
| 160ᵉ | 16530211000 | 166ᵉ | 15539141000 |
| 161ᵉ | 16533371000 | 167ᵉ | 18287401000 |
| 163ᵉ | 14190981000 | 168ᵉ | 18767671000 |
| 164ᵉ | 14401751000 | 169ᵉ | 20597071000 |

Editions **156, 157, 158, 159 and 162** returned no product record in search —
BI does not carry them. Doug holds 94 bottles across those five.

**The LWIN11 is the identity key to use.** It is unambiguous, it is per edition,
and it survives BI's inconsistent naming.

---

## Method, for the adapter

1. **Identity:** `/search/auto-complete-ajax?search=<terms>` returns clean JSON
   with `itemCode`, `lwin11`, `lwin16`, `itemSize`, `productName`, `vintageWebUrl`.
   This is the right way in, and it needs no scraping.
2. **Prices:** the marketplace pages are client-rendered; the DOM classes are
   `.livetrade-item`, `.bid-button`, `.offer-button`, `.bids`, and the last trade
   sits in the item's text as `Last trade: £X (DD/MM/YYYY)`.
3. **Routes that do not work:** `/fine-wine/list?producer=X` 404s;
   `/livetrade/marketplace/<itemCode>` usually returns "NO RESULTS FOUND" and then
   shows an unrelated fallback under "RELATED VINTAGES" — the Krug 167ᵉ data came
   from such a block and happened to be genuine. **Never trust a related-vintages
   row without checking the wine name on the row itself.** A Chablis appeared under
   a Krug query.
4. `/livetrade/marketplace/<free text>` works and is server-rendered, but caps at
   100 items with no pagination control found.
5. The producer page carries a **DELIVERY / IN BOND toggle**. In Bond was active by
   default in this session, but the fine-wine pages elsewhere state "Pricing
   includes duty and VAT" — so **duty status must be read per page, never assumed**.
   The card class itself carries it: `wine-inbond` vs duty-paid.

---

## Three things for the pricing core

1. **A bid is a different evidence type from an ask, and better.** It deserves its
   own source type on the record — not folded in with merchant offers. Where a bid
   exists, the seller's realistic proceeds are knowable rather than modelled.
2. **Refuse wide spreads rather than averaging them.** Krug 162ᵉ at bid £660 /
   offer £1,596 must not produce a reference of £1,128. A spread threshold is the
   control; a midpoint is a fabrication.
3. **A last trade with a date is the strongest single number on the page** — it is
   the only one where money actually changed hands. It should outrank an ask, and
   it should carry its date so staleness is visible. Krug GC 1×150cl last traded
   in January 2025; that is not current evidence.

---

## Still to do

- The remaining Champagne producers: Dom Pérignon (46 + 24 + 18 + 12 × 4 bottles),
  Louis Roederer Cristal, Taittinger Comtes, Pol Roger, Charles Heidsieck,
  Henri Giraud, Eric Rodez, Savart, Pierre Peters, Bollinger.
- A second and third source per line, since ONE_COMP is 87% of the review burden
  and a single source cannot carry a percentage claim.
- Slug caution carried over: `pol_roger` and `pol_roger_(berry_bros._&_rudd)` are
  both present, as are `louis_roederer` and `louis_roederer_(starck)`. Union the
  slugs per producer, exactly as with the Grand Puy Lacoste misspelling.

## Caveats

- One source. Everything above is Bordeaux Index.
- Read once, on 7 October 2026. Bids and offers move.
- Case prices as listed; per-bottle figures are arithmetic, and the measured case
  premium of 1.00 (median, n=27) is what justifies dividing.
- LiveTrade is a marketplace BI operates. A bid there is a real commitment by a
  real counterparty, but it is BI's market, not the whole market.
