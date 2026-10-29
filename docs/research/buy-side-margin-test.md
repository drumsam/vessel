# The buy-side margin test — the walk-away price

28 October 2026. An addendum to `build-brief-vessel-pocket.md`, agreed with
Doug. **It changes screens 3 and 4 of VESSEL Pocket. Nothing else.**

---

## The job this adds

The brief has Doug entering a buyer price and the system computing the spread.
That is the wrong way round for the job he actually does.

An offer arrives on WhatsApp. He needs to know, in seconds, **whether it can be
bought at all** — not what the margin would be if he picked a number. So the
engine should state **the most he can pay** and leave him to compare it with
the ask.

One figure. Deterministic. No opinion.

---

## Definitions

Doug confirmed on 28 October 2026:

**Margin is measured on cost.** Buy at £100, sell at £108, margin 8%.

```
margin = (sell − buy) / buy
```

Not on revenue. If this is ever revisited, it is a decision record, not a
configuration change, because every stored margin figure would change meaning.

New constants, in `app/core/flags.py` alongside the existing ones:

```python
MIN_TRADE_MARGIN   = Decimal("0.08")   # margin on cost, buy-side parcel trades
MIN_BUYER_DISCOUNT = Decimal("0.05")   # the smallest discount worth offering
```

`MIN_BUYER_DISCOUNT` is not arbitrary. Decision 0034 suppresses a savings claim
below 5% because it is not worth stating to a buyer. A sell price that leaves
less than 5% off the Floor therefore has no claim attached to it, and a buyer
who can find the Floor has no reason to take it.

Both are parameters Doug sets, not truths. Changing `MIN_TRADE_MARGIN` to 0.10
must change the output and nothing else.

---

## The walk-away price

Given the **UK Floor** `F` for the exact commercial unit:

```
max sell      S = F × (1 − MIN_BUYER_DISCOUNT)     # 0.95 F
walk-away     W = S ÷ (1 + MIN_TRADE_MARGIN)       # 0.95 F ÷ 1.08
                ≈ 0.8796 F
```

**The walk-away price is about 88% of the UK Floor.**

The ceiling comes from decision 0033 — never price at or above the Floor — and
the 5% haircut from 0034. The engine is not inventing a market view; it is
applying two existing guards plus one parameter Doug chose.

### Worked example

DRC Richebourg 2015, 3 × 75cl, UK In Bond.

```
UK Floor              £10,200   (£3,400/bt)
Max sell  0.95 × F     £9,690   (£3,230/bt)
Walk-away  S ÷ 1.08    £8,972   (£2,991/bt)

Seller ask             £8,400   (£2,800/bt)
                       ------
Headroom                 £572   (£191/bt)
Margin at this ask      15.4%
```

Per-bottle figures primary, line totals secondary — decision 0034.

### When the ask is above the walk-away price

State the gap and stop. Do not suggest a counter-offer, and do not imply the
trade is bad — Doug may have a buyer who pays more than the Floor implies, and
that is his knowledge, not the engine's.

```
Seller ask £9,600 (£3,200/bt)
Walk-away  £8,972 (£2,991/bt)
£628 above walk-away. 8% on this ask needs a sell of £10,368 —
above the UK Floor of £10,200, which decision 0033 forbids.
```

That last line is the useful one: it says the trade cannot be made to work at
his own stated margin without breaching a guard, which is a fact rather than a
judgement.

---

## This is not a verdict, and the distinction has to hold

Doug's own architecture review is explicit that the EVALUATE screen renders no
verdict. A pass/fail against a threshold he set is not a verdict — it is
arithmetic he could do himself, done faster.

So the wording matters:

- **Yes:** "£572 below walk-away", "margin at this ask 15.4%"
- **No:** "good buy", "attractive", a score, a traffic light, a thumbs-up

The engine states the number and the comparison. Doug decides.

---

## The guards that still apply, and the ways this must refuse

The walk-away price is only as good as the Floor underneath it. Every existing
discipline holds, and each has a way of refusing rather than guessing.

**No Floor, no walk-away.** If merchant evidence is absent or stale beyond
`MAX_OFFER_AGE_DAYS`, there is no walk-away price. It must render as *cannot
compute*, visually distinct, and it must block the CREATE OFFER path. Decision
0040: couldn't-check is not checked-and-clear. An absent walk-away price must
never render as a pass.

**Depth of one is not a market.** If only one merchant is found, the Floor is
one merchant's ask. Show the walk-away price, label it single-source, and
require acknowledgement. The existing depth counting in distinct merchants
already supplies this.

**Review flags come first.** A line priced REVIEW has no walk-away price until
acknowledged — the same gate as the Cellar Desk.

**Want-list producers gate before any arithmetic.** The twenty producers fire
their identity gate first. A walk-away price computed against the wrong Leroy
is worse than no walk-away price, because it looks like diligence.

**Exact commercial unit, as always.** A seller's "3 bottles" is comparable only
to a Floor for 1 × 75cl at the same bond status. Per-bottle derivation from a
case price follows decision 0028, not a guess.

---

## Whisky — captured, not priced

Doug receives whisky offers alongside wine. Confirmed on 28 October 2026:
**whisky is captured and refused, not priced.**

The identity layer has no concept of a distillery, an independent bottler, a
cask number, an age statement or an ABV, and the UK whisky market prices at
auction rather than on merchant pages. Running whisky through wine logic would
resolve confidently and wrongly on exactly the bottles worth the most.

So:

- `inbound_offer` stores whisky exactly as it stores wine. The raw record is
  category-agnostic and nothing is lost.
- A whisky line is flagged **`UNPRICEABLE_CATEGORY`** at identity resolution
  and carries no price, no reference, no walk-away figure.
- The screen says so plainly: *"Whisky — not priced by VESSEL. Captured for
  your records."*
- `assertBuyerSafe()` still applies if Doug chooses to make an offer from his
  own knowledge, but the engine asserts nothing about value.

**Not now:** a whisky identity model, whisky auction sources, a whisky pricing
route. Capture first, then count how many whisky offers actually arrive. If the
volume justifies it, a whisky module is a Phase 2 decision taken on evidence
rather than on the assumption that it is similar to wine. It is not.

---

## Email — paste the body, do not build ingestion

Some offers arrive by email. Phase 1 stays **paste · photo · upload**: Doug
copies the email body and pastes it, exactly as he would a WhatsApp message.

Inbound email parsing remains on the not-now list from the brief. It is a
mailbox, a parser, an address to publish and a spam surface, and it saves one
paste. Revisit only if pasting turns out to be the thing slowing him down,
which it probably is not.

---

## What this changes in the brief

**Screen 3, EVALUATE.** Add the walk-away price and the comparison with the
seller's ask. Still facts only.

```
DRC Richebourg 2015 · 3 × 75cl · UK IB · LCB

Seller ask        £8,400   (£2,800/bt)
UK Floor         £10,200   (£3,400/bt)   4 merchants · read 28 Oct
Walk-away         £8,972   (£2,991/bt)   at 8% on cost
                  £572 below walk-away

[ VIEW EVIDENCE ]  [ PASS ]  [ HOLD ]  [ CREATE OFFER ]
```

**Screen 4, CREATE OFFER.** The `parcel_trade` basis is unchanged — Doug still
enters the buyer price, and the system still may not derive it. What changes is
that the walk-away price is shown alongside the field as a reference, and a
buyer price that would put the margin below `MIN_TRADE_MARGIN` is flagged, not
blocked. Doug may knowingly take a thin trade; he may not take one by accident.

Nothing else in the brief changes. The order of work is unchanged.

---

## Open question for Doug, not blocking

When the walk-away test passes and he creates the offer, what sell price does
he usually pick — the max sell (Floor less 5%), or lower to move it quickly?
Once there are twenty real trades on record, that question answers itself from
his own history and the system can show the range he actually works in. Until
then it stays a field he fills.
