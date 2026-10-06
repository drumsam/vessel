# VESSEL Private Sale — one mechanism

v3, 6 October 2026. Supersedes v2. Written to the rule: *if a feature does not
increase supply, conversion, trust or transaction speed, don't build it.*

---

## What we delete, and the one thing that must replace it

Gone: the bid book, standing bids, criteria matching, indicative and firm
interest, make-an-offer, buyer–seller messaging, the four-stage waterfall, the
demand graph as a built thing, membership fees, two-speed seller pricing.

You're right that it was a Bloomberg terminal for a business that needs a shop
window. One mechanism: **curated fixed-price drops.**

But deleting the bid book removes the honest basis for the middle column of the
seller's Offer Room — "executable today" was only true because someone had
committed a price. So the seller promise changes with it:

| Was | Now |
|---|---|
| "Executable demand is £183,400" | **"We'd move these 42 lines. Estimated proceeds £486,000. We set the price; you set your floor."** |

That is a better promise anyway, because it's one we control. It makes **price
conviction** the product rather than someone else's bid. And it means the seller
approves two things, not one: the lines, and the **minimum net they'll accept**.

---

## The two promises

**Seller.** Send us your cellar — spreadsheet, storage statement, photo, PDF,
whatever you have. We'll come back with what we'd move and what you'd net.
Approve it. We'll take it from here.

**Buyer.** Good wine. Properly priced. Ready to buy.

---

## The product: five screens

### 1 · Seller approval

The cellar, reduced to a decision. Only the lines we recommend moving, each with
the evidence behind the price and the net to them.

```
YOUR CELLAR · 561 lines received · we recommend moving 42

Estimated net proceeds       HK$486,000
Lines recommended            42 of 561
Why not the rest             319 no UK market · 147 thin evidence · 53 better held

┌─────────────────────────────────────────────────────────────────────────┐
│ Rousseau Clos St Jacques 2010 · 6 × 75cl                                │
│ Market reference HK$84,000 · 3 merchants, read 6 Oct                    │
│ VESSEL price HK$69,500 · your net HK$63,940          [✓ move]           │
│ Minimum you'd accept: HK$ [63,940]                                      │
└─────────────────────────────────────────────────────────────────────────┘

                                              Approve 42 lines · HK$486,000
```

Two inputs per line: the tick, and a floor they can raise. Default floor is our
net figure, so the fast path is a single button. One sentence under the total
tells them what happens to anything that doesn't sell (below).

### 2 · Drop page

Thursday, 6pm Hong Kong. Twenty to forty lines. Edited, not dumped.

Each card: wine, vintage, bottles, location, VESSEL price, the market reference
beside it, the saving in percent. **SOLD** stays on the page, greyed, for the
week. Seeing good things go is the behavioural loop.

### 3 · Wine page

Wine. Price. Proof. Buy. In that order, on one screen, no scrolling needed on a
phone.

```
2010 Armand Rousseau · Gevrey-Chambertin 1er Cru Clos St Jacques
6 bottles · 75cl · Hong Kong bond

Market reference   HK$84,000        VESSEL   HK$69,500
                                    17% below current market

Evidence     3 UK merchants, read 6 October  ·  see all three
Provenance   Single private cellar, professionally stored since purchase
Condition    Original case, labels and levels as new
Drinking     Open now to 2035. At its best from 2027.

                              [ BUY — HK$69,500 ]
```

The evidence line expands to the three merchant prices with dates. That one
detail is the whole brand: nobody else in wine will show you theirs.

### 4 · Payment

```
Reserved for you · 29:41

Pay HK$69,500 by FPS or bank transfer
[QR]  FPS ID 1234 5678  ·  Account details
Reference  VS2847        ← must be quoted

We'll confirm within minutes of the money landing.
If payment doesn't arrive in 30 minutes the wine goes back on sale.
```

### 5 · Confirmation

Yours. What happens next, in three lines: transfer in bond, timing, where it
will sit. Nothing else.

---

## The part that must be exactly right: line state

Everything else is screens. This is the machine.

```
APPROVED → LISTED → RESERVED → PAID → TRANSFERRING → SETTLED
                        ↓ timeout
                      LISTED
```

- **One reservation at a time per line.** Taken on the BUY tap, released by a
  timer. A line can only be reserved by one buyer — this is a database
  constraint, not application logic.
- **Partial lines are not a thing at launch.** Six bottles is six bottles. Splits
  come later, if at all.
- **Nothing is confirmed until funds clear.** The confirmation screen says
  reserved; the email says yours.
- **No title moves before cleared funds.** Hard rule, no exceptions, no favours.
- **Expiry on the whole drop.** A line unsold after its window returns to the
  pool for the next drop.

```sql
CREATE UNIQUE INDEX one_live_reservation_per_line
  ON reservation (listing_id) WHERE state = 'HELD';
```

## What happens to what doesn't sell — say it up front

The seller must know this before approving, or trust goes on the first cellar:

1. **Re-dropped once** at the same price in the next release.
2. **Re-priced down**, within their approved floor, for a third release.
3. **Floor reached** → we tell them, and they choose: hold, lower the floor, or
   take it to auction.
4. **Never silently discounted.** The floor is theirs, and it binds us.

---

## Pricing conviction — how the number is set

The engine already produces, per line: a market reference traced to named
merchant offers, a source count, and a flag when evidence is thin.

```
VESSEL price   = market reference × (1 − 20%)       rounded down to a clean figure
Seller net     = VESSEL price × (1 − 8%)
Floor check    = seller net ≥ seller's minimum, or the line is not listed
```

Three rules that protect the conviction:

- **A line with one source is not listed at all.** It goes in the "thin
  evidence" bucket on the seller's page. One merchant is not a market, and the
  buyer is being asked to act without negotiating — that promise has to be
  earned on every line.
- **Clean figures.** HK$69,500, not HK$69,473. A computed price that looks
  computed invites haggling.
- **Published price never moves inside a drop.** If we got it wrong, we learn it
  on the next one.

---

## Curation — the cellar is supply, not the shop

A 561-line cellar becomes several drops of 25 to 35 lines. What earns a place:

- **Two or more merchant sources.** Non-negotiable, per above.
- **A name the buyer already knows.** The point is recognition, not discovery.
- **A real saving**, 15% or better against the reference.
- **Enough bottles to matter**, 3+ where possible; singles only for serious wines.
- **Spread across the drop**: Burgundy, Bordeaux, Champagne, something mature,
  something to drink this month, a couple of trophies.

What's held back: thin-evidence lines, odd formats, anything in the identity
queue, and — deliberately — some of the best lines, so the next drop has a spine.

**A drop can be skipped.** Better nothing on a Thursday than filler.

---

## VESSEL VERIFIED — claim only what we can defend

| We verify | How | We do not claim |
|---|---|---|
| Identity | the engine's resolver plus a human eye on every listed line | that we tasted it |
| Quantity and format | the seller's statement, reconciled against the storage statement | |
| Location and bond status | warehouse documentation | |
| Provenance chain | where it's been, who held it, since when | that it's never been moved |
| Condition basis | stated: OWC, labels, levels, as declared and as seen | a condition report we didn't do |
| Price evidence | named merchants, with dates | that it's the lowest price anywhere |

Over-claiming here is the one thing that could kill the business. "Professionally
stored since purchase, single owner, OWC, labels as new" is strong *because*
every clause is checkable.

---

## Operational musts (small, non-negotiable)

- **KYC on buyers** at account creation, and enhanced checks above a threshold
  you set with your compliance adviser. A private room needs a door policy.
- **Payment reference matching**, automated: the reference is the key, unmatched
  money sits in a queue, nothing ships on an unmatched payment.
- **Insurance in transit and in bond**, stated on the confirmation.
- **Bond-to-bond transfer instructions** generated per sale, HK and UK.
- **Seller paid on a stated schedule** after cleared funds — say the number of
  days and never miss it. This is what makes the second cellar arrive.

---

## Behaviour is the profile

Nothing asked of the buyer. Logged per buyer: viewed, clicked, bought, declined
after viewing, time to act. That's enough to rank the next drop for them —
Burgundy first for the Burgundy buyers — and it costs no UI.

No questionnaires, no preference centre, no "complete your profile". If someone
buys three Coche-Durys, VESSEL knows what to put at the top of their page.

---

## Build order

**Drop one (weeks 1–3).** Seller approval screen · drop page · wine page · buy
and reserve with the timer · payment instructions and confirmation · reservation
and payment-matching behind them. Run the Hong Kong cellar's first 30 lines
through it, end to end, with real money.

**Drop two to five (weeks 4–8).** Payment matching automated. Re-drop and
re-price logic within the seller floor. SOLD state persisting on the page.
Buyer ranking from behaviour. Seller payout schedule.

**Then (weeks 9–12).** My Cellar for sellers — their holdings, valued, free,
with *someone is looking for this* — because that's the supply engine. Referral:
a member brings a member, both get the drop an hour early.

**Not now.** Auction. Custody. Bid book. Live video. Membership fees. App.

Mapped to what exists: the pricing engine, identity layer, evidence and the
offer document are built. What's missing is listings, reservations, payments and
the two buyer screens — a fortnight of work, not a platform.

---

## The test, applied

| Feature | Supply | Conversion | Trust | Speed | Build? |
|---|---|---|---|---|---|
| Seller approval screen | ✓ | | ✓ | ✓ | yes |
| Drop + wine page + BUY | | ✓ | | ✓ | yes |
| Evidence expander | | ✓ | ✓ | | yes |
| Reservation timer | | ✓ | | ✓ | yes |
| SOLD left visible | | ✓ | ✓ | | yes |
| My Cellar | ✓ | | ✓ | | soon |
| Referral priority | ✓ | | | | soon |
| Bid book | | | | | no |
| Auction | | | | | not yet |
| Live video | | | | | no |

---

## Four decisions

1. **Thin-evidence lines: list or hold?** I'd hold them. It costs volume on the
   first drops and buys the thing the whole model rests on — a buyer who doesn't
   second-guess the price. (On the Hong Kong cellar this is most of the Burgundy,
   so it's a real cost: say the word and we list them with the evidence shown and
   a slightly deeper discount instead.)
2. **Who holds the money?** Buyer pays VESSEL, VESSEL pays the seller on a stated
   schedule — simplest for the buyer, and it needs a compliance conversation
   about client money before the first sale.
3. **Reservation window: 30 minutes, or longer for large amounts?** I'd do 30
   minutes under HK$50,000 and 2 hours above, because bank transfers at size
   aren't instant.
4. **First drop date.** Pick it now and never move it. Everything above is
   sized to hit a Thursday.
