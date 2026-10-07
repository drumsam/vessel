# VESSEL — the liquidity system, v2

6 October 2026. Supersedes the strategy report of the same date where they differ.
Written against the critique: demand graph first, no balance sheet, seller and
buyer as two faces, progressive visibility.

> Note: I'm working from the critique's summary of the VESSEL plan, investor deck,
> operating plan and brand guide — I haven't read those documents. Drop them in
> the Wine project and I'll align the terminology exactly.

---

## 1 · What I got wrong, and what replaces it

| v1 said | v2 says |
|---|---|
| Thursday List as the primary mechanism | **Demand graph first.** The list is stage three of four, not the product. |
| Two speeds: 65% now / 74% later | **VESSEL Clear vs VESSEL Market.** Clear is executable buyer demand, not our cash. No balance sheet. |
| One marketplace surface | **Two surfaces.** Seller sees certainty. Buyer sees opportunity. |
| Buyer membership fee | **Earned status.** Qualification by identity, payment and behaviour. |
| Sell 561 lines | **Route 561 lines.** Each line is a routing decision, not a marketing problem. |

The critique is right on all five. One thing it leaves open is the mechanism that
makes "executable demand" a real number on day one rather than an aspiration.
That mechanism is below, and it's the heart of this version.

---

## 2 · The customer, precisely

Not "people with cellars". This:

**A collector of five years or more, 500+ bottles in bond, who wants 10–30% of it
gone.**

Why they're stuck:

- Taste moved on. The Napa cabernet and the big Rhônes from 2015 no longer get
  opened; the Burgundy does.
- They are paying storage, every year, on wine they will never drink.
- Nobody will sell it for them. Merchants want the twelve good lines, not the
  sixty ordinary ones. Auction means four months, 15–25% of commissions, and a
  public result on wines they may still own more of.
- The spreadsheet of what they own is three years out of date.

What they will accept, stated plainly: **20% below market to a buyer, 8% to us.**
They are not optimising the last 5%. They are buying back their own attention —
and shelf space, and storage fees.

**What the buyer is:** someone who wants a wine they already know at a price they
can verify, delivered without a conversation. Not a geek hunting a rarity. A
buyer with a list.

---

## 3 · Three assets, in order of defensibility

**1. Evidence.** What a line is really worth, traced to named merchant offers.
Built, measured, and running: six merchant sources, identity resolution across
spellings and editions, outlier checks against quality-matched vintages. No
competitor shows their working.

**2. The bid book.** What buyers will actually pay, standing, in advance. This is
the asset that doesn't exist anywhere in fine wine, and it's what makes VESSEL
Clear honest. Section 5.

**3. Routing.** Which of the four exits each line takes, and when. Section 7.

Evidence without demand is a valuation service. Demand without evidence is a
broker's address book. The combination is the business, and the data from each
cellar makes both halves better.

---

## 4 · The two surfaces

### Seller: certainty

```
Cellar in (any format)  →  priced with evidence  →  Offer Room  →  tick lines  →  done
```

The Offer Room, per the critique, with three money columns and one action:

> **YOUR CELLAR** · 561 lines · 3,544 bottles
>
> Market reference **£246,800** · Executable today **£183,400** · VESSEL Market estimate **£205,000–219,000**

| Wine | Market evidence | Executable now | VESSEL Market | |
|---|---:|---:|---:|---|
| Lafite 2000 · 12×75 | £14,800 · 4 sources | £11,600 | £12,900 | **Sell** |
| Rousseau Clos St Jacques 2010 · 6×75 | £9,200 · 3 sources | £7,900 | £8,500 | **Sell** |
| Krug 2008 · 6×75 | £1,650 · 2 sources | — | £1,480 | *Keep* |

Running total updates as they tick. **Confirm 37 lines.** Then: *we'll take it
from here.*

Three rules that make it trustworthy: every market figure carries its source
count; a line with no evidence says so instead of showing a number; and
"Executable now" is only populated where a real standing bid exists.

### Buyer: opportunity

```
Tell VESSEL what you buy  →  matches arrive  →  verify in one screen  →  buy
```

Their page shows only their matches, never the catalogue. Each line: the wine,
the market reference it sits below, the saving in pounds and percent, provenance
and location, and one button. No basket, no browsing, no login — a tokenised
link that opens straight to *their* nine wines.

Two ways to buy: **take the offer now**, or **leave a standing bid** at the price
they'd pay, which routes future cellars to them automatically.

---

## 5 · The bid book — the mechanism v1 was missing

Standing bids turn preferences into money, and they solve the cold-start problem
without any inventory risk.

A buyer can place a bid at two levels of precision:

**Specific**: *Rousseau Clos St Jacques 2010, 6×75, up to £7,900 a case, up to 2 cases.*

**Standing criteria**: *Any Burgundy grand cru, 2010–2018, 20%+ below market
reference, under £400 a bottle, up to £15,000 a month, UK bond.*

```sql
CREATE TABLE standing_bid (
    standing_bid_id bigserial PRIMARY KEY,
    buyer_id        bigint NOT NULL REFERENCES buyer(buyer_id),
    kind            text   NOT NULL,        -- SPECIFIC | CRITERIA
    wine_id         text   NULL,            -- SPECIFIC only
    vintage_from    integer NULL, vintage_to integer NULL,
    region          text[] NOT NULL DEFAULT '{}',
    producer_ids    text[] NOT NULL DEFAULT '{}',
    bottle_ml       integer NULL,
    max_per_bottle_gbp numeric(14,2) NULL,
    min_discount_to_reference numeric(5,4) NULL,  -- e.g. 0.20
    max_spend_gbp   numeric(14,2) NULL,           -- per month, or per fill
    stock_location  text[] NOT NULL DEFAULT '{}',
    quantity_appetite integer NULL,
    expires_at      timestamptz NOT NULL,
    state           text NOT NULL,          -- LIVE | FILLED | EXPIRED | WITHDRAWN
    created_at      timestamptz NOT NULL DEFAULT now()
);
```

Rules that keep it clean:

- **A bid is a commitment with an expiry.** 30 days default, one tap to renew.
  An unrenewed bid is not demand.
- **Payment verified before a bid goes live.** This is the qualification, and it
  is what lets us tell a seller "executable" and mean it.
- **A bid fills at the bid price, not below.** No shading. The buyer's number is
  the buyer's number, which is why they'll leave one.
- **Partial fills allowed, stated up front** (2 of 6 cases is a yes or a no,
  buyer's choice at bid time).
- **Bids are private.** Neither side sees the book. Sellers see the aggregate as
  "executable today"; buyers see only their own.

**Why this is the unlock:** the moment the book has depth, pricing a cellar
produces two numbers instantly — what the market says, and what someone will pay
today. That is a service no merchant, broker or auction house can offer, and it
needs none of our own money.

**Cold start, in order:** seed the book from the buyers already transacting at
−20% (their appetite is already known — write it down as bids); capture wants in
60 seconds from any buyer, including by uploading their own cellar list or
wishlist, which the identity layer already parses; and record every decline with
a reason, because "too dear at £700" is a bid at £600 in disguise.

---

## 6 · The demand graph

A buyer profile is partly declared and mostly observed:

| Declared | Observed |
|---|---|
| regions, producers, vintages | what they bought, at what discount |
| formats, price bands | what they opened and asked for again |
| bond / duty paid, location | what they viewed and didn't buy |
| drinking vs investment | what they declined, and the reason |
| monthly appetite | how fast they answer |

Scoring must be **deterministic and explainable**, not a model nobody can argue
with — the same discipline as the pricing core. A transparent weighted score,
printed as a sentence:

> **Match 0.82** — buys Burgundy grand cru (0.3) · bought Rousseau twice (0.2) ·
> price inside band (0.2) · vintage inside range (0.1) · UK bond (0.02) ·
> answered within a day on last three offers (0.1)

Store the features and the weights with every routing decision, so a match can be
audited later and the weights tuned on evidence rather than vibes. When there is
enough history to justify a learned model, the explainable score stays as the
fallback and the floor.

```
line_match(line, buyer) → { score, reasons[], bid_id | null, routed_at }
```

---

## 7 · The waterfall — progressive visibility

Each line walks the stages until it clears. Visibility increases only when
necessary.

| Stage | Who sees it | Window | Price |
|---|---|---|---|
| **0 · Bid fill** | nobody — it's already sold | instant | the standing bid |
| **1 · Direct match** | 3–15 highest-scoring buyers, each privately | 3 hours | VESSEL Clear |
| **2 · Inner market** | the qualified buyers for that region | 24 hours | VESSEL Clear |
| **3 · Weekly release** | the whole private network, Thursday | 7 days | VESSEL Market |
| **4 · Clear** | auction, or a trade buyer in volume | — | discovery |

Stage 0 is the prize: a line that matches a live standing bid is **sold before it
is offered**. For a cellar like the Hong Kong one, every bottle of Cristal and
Comtes de Champagne should fill this way.

Routing policy, deliberately simple at first: take the stage that maximises
expected proceeds per day — `(price × probability) ÷ days` — with one override,
that any line the seller marks *urgent* skips to stage 3 immediately. No cleverness
until there is data to be clever with.

What the seller sees while this happens: a line's state and nothing else.
*Matched · offered to 7 · sold.* Not the buyers, not the book.

---

## 8 · The economics, stated openly on both sides

The critique is right that hiding the spread is the mistake. It reads as a fleece
when hidden and as professional when printed.

**To the seller:**

> Market reference £9,200 · Buyers in this trade transact 20% below market ·
> VESSEL fee 8% of the sale · **You receive £6,771**

**To the buyer:**

> Market reference £9,200 · **Your price £7,360** · You save £1,840 (20%) ·
> Market evidence: 3 UK merchants, read 6 October

Both sides see the same market figure and the same arithmetic. The seller gets
their storage bill back and their shelf space; the buyer gets a wine they know at
a verifiable discount; VESSEL takes 8% for making the match and carrying none of
the risk. Nobody needs to feel clever at the other's expense, which is exactly
why both will come back.

---

## 9 · Simple, fast, and actually enjoyable

Speed targets, because this is the product: **cellar list to priced Offer Room in
under an hour. Seller confirmation to first sale in under a day. A buyer from
link to purchase in under two minutes, on a phone, with no login.**

Three delight mechanics worth building, each cheap:

**"Why this drinks well."** Every offer carries two or three lines in plain
English: where the wine is in its life, what it tastes like now, what to put with
it, when to open the last bottle. Written by us, from the vintage register and
the producer's style — never lifted from critics. It turns a line item into a
bottle somebody wants to drink tonight.

**"Look like a pro."** One tap on a purchase produces a card the buyer can show
at dinner: the wine, the vintage, why this vintage matters, how to serve it, and
what it would cost at a merchant. The point isn't vanity — it's that a buyer who
can talk about the wine buys more wine.

**The deal, said out loud.** "£1,840 below the best UK merchant price we can
find, with the evidence." Collectors enjoy a good buy more than a cheap one, and
evidence is what makes it a good buy rather than a suspicion.

**Referral, built in.** A member can bring one member. Both get a first-look
window on the next three cellars — not a discount, which cheapens the room, but
*priority*, which is the thing the room is for. Track who brought whom; it will be
the cheapest acquisition channel by a distance.

---

## 10 · Where AI earns, and where it is banned

**Earns:**

- Ingestion: any spreadsheet, a photo of a rack, a warehouse PDF → clean lines.
- Identity: the hard part, already built — seven domaines' Chambertin, Krug by
  edition, Courcel's two Épenots.
- Market collection: six sources, scheduled, polite.
- Offer and document drafting from priced lines.
- Match explanations, in a sentence a human can check.
- Drinking windows and tasting copy, from our own data.
- The seller's and buyer's questions answered on the page, with the evidence
  attached, instead of a phone call at 11pm.
- Decline-reason parsing: turning "too dear" into a price.

**Banned:** the price, the margin, the routing decision's arithmetic, and
identity approval on a four-figure line. Those stay deterministic, traceable and
boring. The system's entire credibility is that a seller can ask "why that
number?" and get an answer with a merchant's name and a date on it.

---

## 11 · Build order

**Now — the two surfaces and the book.**

1. **Offer Room** with the three columns and per-line Accept. Tokenised link,
   expiry, full audit of what the seller saw. (Spec written: `offer-document-spec.md`.)
2. **Standing bids**: the table above, a 60-second capture flow, payment
   verification, expiry and renewal.
3. **Buyer page**: their matches only, tokenised link, one-tap buy, leave-a-bid.

**Next — the graph and the routing.**

4. **Buyer profiles** with declared wants plus observed behaviour.
5. **Explainable match scoring**, features and weights stored per decision.
6. **Waterfall engine**: four stages, timers, the one override, state per line.

**Then — the compounding part.**

7. **My Cellar**: the seller's holdings, valued monthly, free. Drink / hold /
   move. This is the seller-acquisition engine, because it sits beside the cellar
   and occasionally says *someone is looking for this*.
8. **Referral and earned status.**
9. **Thursday release** as stage three, with the delight layer attached.

Custody stays last, for the reason the critique gives: it needs capital, and the
model works without it.

---

## 12 · The four numbers

- **Hours from cellar received to Offer Room sent.**
- **Share of lines accepted by the seller.**
- **Share of accepted lines sold in 7 days** — split by stage, because that tells
  you whether the bid book or the list is doing the work.
- **Margin per cellar after logistics.**

One diagnostic worth watching from the start: **bid-book depth** — how many live
standing bids, covering what share of a typical cellar's value. When that share
passes about a third, VESSEL Clear becomes the main product and everything else
is overflow.

---

## 13 · Decisions I need from you

1. **Does a standing bid bind the buyer?** My view: yes, with payment verified,
   and a 24-hour cooling window on fills above a stated size. Without binding, a
   seller can't be told "executable" and the whole idea collapses into another
   wish list.
2. **Can a seller see executable demand before confirming?** My view: yes —
   it's the reason they'll confirm — but as one aggregate figure, never the names.
3. **Partial cellars**: do we accept a seller who ticks 6 lines of 561? My view:
   yes, gladly, and never mention exclusivity. It's how the second cellar arrives.
4. **The VESSEL Market estimate** — is it our number or the band from the
   evidence? My view: the band from the evidence (floor to reference), never a
   point estimate we'd have to defend.
5. **HK or UK first?** The stock is in Hong Kong, the evidence is UK. Which side
   the first ten cellars sit on changes what we build next: freight and bond
   transfer, or Asian market sources.
