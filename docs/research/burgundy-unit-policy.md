# Burgundy unit policy — cross-format comps with a 5% case premium

Doug's decision, 24 September 2026. For Claude Code. This changes a rule that
decision 0001 locked, so it needs a decision record of its own (0014) rather than
a quiet edit.

## What Doug decided

1. **For Burgundy, stop refusing a comp because the case size differs.** A
   6-pack, a 3-pack and a loose bottle of the same wine and vintage are all
   usable evidence.
2. **Cases carry a crude 5% premium** over loose bottles, per bottle.
3. **Large formats are out.** Magnums and above trade at a premium of their own
   and must not be mixed with 750ml prices in either direction.

The reasoning, in his words: our job is to find a sensible starting point for a
market price. A refusal to compare 3×75 with 6×75 was costing us most of the
evidence we had.

## What the numbers say, so this is on the record

Decision 0001 was measured, not assumed: across live merchant data the per-bottle
price of a case ran from **17.3% below** to **20.0% above** the loose-bottle price
of the same wine. A flat 5% sits inside that range but can be wrong by roughly 15
points in one direction and 22 in the other. On a £1,300 six-pack that is about
£200–£290.

So the 5% is a **working assumption, not a measurement**, and it should be
labelled that way everywhere it appears. Two consequences follow, and I'd hold
both:

- **A derived comp is never silently equal to an exact-unit comp.** It carries
  `DERIVED_FROM_CASE`, which is already in `REVIEW_FLAGS`, so any line priced off
  one goes to a human. That is the whole safeguard: Doug gets the number, and
  nobody ships it without looking.
- **Exact-unit comps rank first.** Derived comps are used only when fewer than
  two merchants hold the seller's exact unit. When the exact unit has depth, the
  derived figures sit alongside as context and do not move Floor, Reference or
  Median.

If Doug wants derived comps to rank equally with exact-unit ones, that is his
call to make explicitly — it is not the default I would build.

## The rule, precisely

Scope: **Burgundy only**, switched by region, and only at **750ml**.

```
per_bottle(offer)  = offer.price / offer.pack_size          # 750ml only
loose              = pack_size == 1
```

Deriving a comparable at the seller's unit U (pack size N, 750ml):

| Offer | Derived comparable at N×750 |
|---|---|
| pack_size == N | the offer itself — exact, no adjustment, ranks first |
| loose bottle (1×750) | `price × N × 1.05` |
| case of M ≠ N (both > 1) | `price / M × N` — no premium, case-to-case |
| any bottle_ml ≠ 750 | **not usable** — no derivation, in either direction |

And the reverse, for a seller line that is a single bottle:

| Offer | Derived comparable at 1×750 |
|---|---|
| case of M > 1 | `price / M / 1.05` |

`CASE_PREMIUM = Decimal("1.05")` lives beside the other band constants, with a
comment saying it is an assumption, who made it and when. Money stays `Decimal`;
the derived figure is rounded half-even to 2dp at the point of derivation, and
that is a fourth documented rounding point in decision 0007.

## Large formats

Magnum (1500ml) and above are **never** converted to or from 750ml, and never
inform a 750ml line. They are only comparable with the same size: a 6×150 line
takes 150ml comps only.

This is a tightening, and it is right — large formats carry a scarcity premium
that has nothing to do with the wine in the bottle. Practical effect on the
control set: the four magnum and double-magnum lines (L15, L64, L65, L67, all
Courcel) stay NO_MARKET unless magnum comps appear, and the magnum offers we
captured at Bordeaux Index and Vinum stop being near-misses and become
non-evidence.

Half bottles (375ml) are out on the same reasoning, in the other direction.

## What the operator sees

On any line priced from a derived comp:

> Derived from a 3-pack at £X. Case premium of 5% applied — a working
> assumption, not a measurement.

The source offer, its real unit and its real price are shown next to the derived
figure. `raw` keeps the original untouched, as always.

## Export

A derived comp can support a client offer only through the existing review path:
the line is flagged, a named operator acknowledges it, and the acknowledgement is
recorded. No client document ever presents a derived figure as an observed market
price.

## Tests

1. `test_burgundy_loose_bottle_derives_to_case_with_premium` — BI 2020
   Mugneret-Gibourg loose at £197 derives to £1,241.10 at 6×75 (197 × 6 × 1.05),
   not £1,182.
2. `test_case_to_case_carries_no_premium` — a 3×75 at £X derives to 6×75 at 2X.
3. `test_magnum_never_derives_to_750` — BI 2015 Clos des Lambrays 3×150 at
   £1,310 contributes nothing to the 6×75 line, in either direction.
4. `test_750_never_derives_to_magnum` — the mirror.
5. `test_derived_comp_forces_review` — a line whose Reference rests on a derived
   comp is never READY.
6. `test_exact_unit_outranks_derived` — with two exact-unit merchants, derived
   figures do not move Floor, Reference or Median.
7. `test_derivation_is_burgundy_only` — the same shapes in Bordeaux are still
   rejected with `Reject.UNIT`.
8. `test_derived_money_is_decimal_and_rounded_once`.
9. `test_operator_sees_source_unit_and_price` — the real offer is never replaced
   by its derived figure.
10. `test_half_bottles_are_not_usable`.

## Effect on the control set, predicted

Lines that gain evidence: **L09** (Henri Germain Morgeot 2021 — BI 3×75 at £225
derives to £450 at 6×75, against L&S £435), **L57** (Hubert Lamy Chatenière 2018
— BI 6×75 at £585 derives to £1,170 at 12×75, against L&S £1,000; Albany's 2017
12×75 is a different vintage and stays band evidence), and any line where a loose
bottle exists at Bordeaux Index.

Lines that lose near-misses: the Courcel magnum lines, and the 2015 Lambrays
magnum case.

Rerun the control set after building and report the new counts — that is the
measurement of whether this trade was worth making.
