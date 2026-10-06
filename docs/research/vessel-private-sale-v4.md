# VESSEL Private Sale — v4, cut to the bone

6 October 2026. Supersedes v3. Shorter on purpose: v4 removes things.

Governing rule, unchanged: *if a feature does not increase supply, conversion,
trust or transaction speed, don't build it.*

---

## The four rules

1. **VESSEL chooses what to sell.** Not the cellar — the lines we believe will transact.
2. **VESSEL sets the price.** Evidence underneath, conviction on top. No offers, no haggling.
3. **The buyer buys.** Press, reserve, pay.
4. **VESSEL finishes it.** Verification, transfer, seller payment. Neither party does anything else.

---

## Accepted from the critique

**Seller floors are gone.** No editable field, no anchor. The seller sees market
reference, VESSEL price, their net, and two words: Move or Keep. Declining *is*
their floor.

**The seller never sees our state machine.** One approval covers everything:

> VESSEL may market these wines for 30 days at a net to you of no less than
> HK$63,940 per line. We handle release timing, presentation and price
> positioning within that. We'll tell you what sold, when, and what didn't.

After 30 days on anything unsold: *this one didn't move — keep it, or shall we
revisit the price?* That is the only other conversation.

**The 20% spread is no longer doctrine.** Three internal bands, invisible to
everyone:

| Band | Discount to reference | Typical |
|---|---|---|
| Strong | 10–15% | blue-chip, deep evidence, recent comparable sales |
| Normal | 15–20% | the default |
| Clearance | 20–25%+ | awkward parcels, thin demand, mature oddities |

This is strictly better for everyone: a line sold at 12% below instead of 20%
nets the seller more **and** earns us more, since 8% of a bigger number is a
bigger number.

**Curate for transaction likelihood, not editorial balance.** If the cellar is
80% Burgundy, the drop is 80% Burgundy. You were right and I was wrong: we're
selling wine, not publishing a magazine.

**Payment language is now true.** *Reserved for you until 18:30. Pay by FPS or
bank transfer. Your purchase is confirmed when funds are received.* And on a
large transfer, submitting proof of payment extends the hold automatically —
nobody loses a wine to reconciliation lag.

**SOLD in 11 min** stays on the page all week. Social proof, consequence for
waiting, and validation of our pricing, in three words.

**Behaviour is the profile.** No questionnaire, no preference centre. A Follow
button later, at most.

---

## Where I'd hold a line on evidence

You're right that a hard two-source rule would exclude exactly the Burgundy that
makes a drop interesting. So: list on limited evidence, with two protections.

**1. The claim scales with the evidence.**

| Evidence | What the page says |
|---|---|
| 3+ current merchant offers | **Market reference HK$84,000** · 17% below market |
| 2 offers | **Market reference HK$84,000** · 17% below market |
| 1 offer, sanity check passed | **Indicative reference HK$84,000** · no percentage claim |
| 1 offer, no sanity check | not listed |

The percentage is the strongest thing we say. It only appears when two
independent merchants agree the reference is real. On a single source the buyer
still gets a number and a decision — just not a claim we can't stand behind.

**2. A single source must pass the sanity check that already exists.**

We built the quality-matched vintage band for exactly this. A single merchant
price gets compared against the same wine in neighbouring vintages of similar
quality; if it sits outside the band, it isn't listed at that price.

This isn't theoretical caution. Bordeaux Index listed 2020 Mugneret-Gibourg
Vosne-Romanée at £2,070 a case when Lea & Sandeman had it at £1,200 — a 72%
error. Price "17% below" that single source and the buyer pays 40% **over**
market. One line like that, early, and the price conviction is gone for good.

The check is built and costs nothing per line. It's the reason we can safely do
what you're asking.

---

## The screens, reduced

**Seller**

```
42 wines we think we can move          Estimated net to you  HK$486,000

Rousseau Clos St Jacques 2010 · 6 bottles
Market reference HK$84,000  ·  You receive HK$63,940              [ MOVE ✓ ]

                                                   Approve 42 wines
```

Under the button, one paragraph: the 30-day mandate, the net per line, authority
to sell, warranty that the wine is theirs and unencumbered, and the warehouse
hold while it's listed. **The approve button is the mandate** — one signature
moment, not a contract to read separately.

**Buyer**

```
Rousseau Clos St Jacques 2010
6 bottles · Hong Kong bond

Market reference HK$84,000
HK$69,500          17% below market

Professionally stored · Original case · VESSEL verified

                        [ BUY ]
```

Evidence, condition and provenance expand on tap. Everything else is behind the
interface.

---

## The only analytics worth keeping

Every listing records: band, discount applied, source count, views, time to sell
or time unsold. Nothing else. After twenty or thirty drops that table tells you
the right discount per wine type, which is how the bands stop being judgement
and start being data — without anyone building a pricing model.

**The one number to maximise: quality-adjusted sell-through.** Not traffic, not
listings, not GMV. What share of what we list sells, and how fast.

---

## Still open, and worth closing before the first drop

1. **Which market is the reference?** The stock and probably the buyers are in
   Hong Kong; our evidence is UK In Bond. If HK trades Burgundy above UK — likely
   for grand cru and prestige Champagne — then every discount here is
   conservative and the bands are mis-set. A day's work to measure: Altaya, Kerry
   Wines, Madison, Watson's. This is the last thing I'd want to be guessing about
   when the first thirty prices go out.
2. **Minimum line value.** Below roughly £400 a line, freight, transfer, payment
   and insurance eat the 8%. Set a floor and don't list under it.
3. **Who pays transfer.** One line on the wine page, every time.
4. **Trade or private buyers.** Private is what v4 assumes. Trade will push on
   price, which breaks rule 2.
5. **Money and licensing.** Buyer funds flowing through VESSEL, two
   jurisdictions, and UK alcohol wholesale registration if any buyer is UK trade.
   Needs your adviser, not a developer, and needs it before the first sale rather
   than after.

---

## What to do now

Build the five screens. List thirty wines. Watch what buyers do.

Then let reality write v5 — and only add sophistication where a real transaction
exposed a real problem.
