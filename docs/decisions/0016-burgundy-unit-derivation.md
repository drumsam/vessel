# 0016 — Burgundy comps across case sizes, with an assumed 5% case premium

**Status:** accepted, 24 September 2026. Doug's decision, specified in
`docs/research/burgundy-unit-policy.md`.

The policy document asks for this to be recorded as 0014. That number was taken
the same day by brokered comps and identical prices, and 0015 by the vintage
band, so it is **0016**; renumbering would break the references already in code
comments, migrations and `CLAUDE.md`. Nothing else about it differs.

This **relaxes** decision 0001, which is the first time a pricing invariant has
been loosened rather than tightened. It therefore carries more safeguards than
anything else in this folder, and they are the point, not decoration.

## What Doug decided

1. For Burgundy, stop refusing a comp because the case size differs. A 6-pack, a
   3-pack and a loose bottle of the same wine and vintage are all usable.
2. Cases carry a crude **5% premium** over loose bottles, per bottle.
3. Large formats are out. Magnums and above never mix with 750ml prices in
   either direction.

In his words: our job is to find a sensible starting point for a market price,
and refusing to compare 3×75 with 6×75 was costing us most of the evidence we
had.

## The number is an assumption, and it is labelled one everywhere

Decision 0001 was **measured**. Across live merchant data the per-bottle price of
a case ran from **17.3% below** to **20.0% above** the loose-bottle price of the
same wine. A flat 5% sits inside that range and can still be wrong by about 15
points one way and 22 the other — roughly **£200–£290 on a £1,300 six-pack**.

So `CASE_PREMIUM = Decimal("1.05")` carries that history in a comment where it is
defined, `app/market/units.py` carries the sentence the operator reads, and the
console prints it beside every derived figure:

> Derived from a 3x75cl at 225.00 from Bordeaux Index: 450.00 at 6x75cl.
> Case premium of 5% applied — a working assumption, not a measurement.

A figure that looks observed and is not is the failure this whole system exists
to prevent. It may never be silent.

## The two safeguards, which are not negotiable

**A derived comp is never silently equal to an exact-unit comp.** It sets
`DERIVED_FROM_CASE`, which is already a review flag, so a line resting on one can
never be READY and cannot reach a buyer document until a named operator accepts
it and the acknowledgement is recorded. Doug gets the number; nobody ships it
without looking.

**Exact-unit comps rank first.** Derivation runs only when **fewer than two
merchants** hold the seller's own unit, and it never displaces a merchant that
does hold it. With exact-unit depth, the other case sizes stay what they always
were: cross-unit evidence, shown and not priced from. A £180 3×75 derives to
£360 and would otherwise take the Floor away from a real £600 ask, on an
assumption.

If derived comps should rank equally with exact-unit ones, that is Doug's call to
make explicitly. It is not the default here.

## The rule

Scope: **Burgundy only**, by region, and **750ml only**, both sides.

| Offer | Comparable at N×750 |
|---|---|
| `pack_size == N` | the offer itself — exact, no adjustment, ranks first |
| loose (1×750) | `price × N × 1.05` |
| case of M ≠ N, both > 1 | `price / M × N` — no premium, case to case |
| seller line is 1×750, offer is a case of M | `price / M / 1.05` |
| `bottle_ml ≠ 750` | **not usable**, in either direction |

The derived figure is quantised to whole pence, ROUND_HALF_EVEN, at the point of
derivation. That is the **fourth** documented rounding point (decision 0007) and
the second in `benchmark.py`. It is allowed to round because it is not an
observed price — which is exactly why it also carries a review flag.

## Where the region switch lives

The pricing core does not know what Burgundy is and never will (invariant 1). It
is **told**: `SellerLine.derive_units` is a boolean the caller sets, and
`DERIVABLE_REGIONS` in `app/market/units.py` holds the list with this decision
behind it. Default `False` everywhere, which is the exact-unit rule of 0001.
Adding a region means measuring its basis first and recording a decision.

## Large formats

Magnum (1500ml) and above never convert to or from 750ml and never inform a
750ml line: a large format carries a scarcity premium that has nothing to do with
the wine in the bottle. Half bottles are out on the mirror of the same reasoning.
This part is a **tightening**. On the control set it means Bordeaux Index's 3×150
Clos des Lambrays (£1,310 on L68, £1,772 on L52) and Vinum's 3×150 Hubert Lamy
stop being near-misses and become non-evidence.

## What it did to the evidence we have

**Burgundy proof (20 loose-bottle lines), before → after:**

| | READY | REVIEW | NO_MARKET |
|---|---|---|---|
| before | 0 | 5 | 15 |
| after | 0 | **15** | **5** |

Ten lines gained a market. Twelve comparables were derived, every one of them
from a case to a loose bottle, so every one carries the 5% and a review flag.
READY stays 0 — nothing became shippable without a person.

Two lines then went **back** to NO_MARKET because the vintage band threw the
derived figure out: L3 Chambertin 2009 (Bordeaux Index, derived £5,047.62, 1.13×
the £4,455 edge of its own 2005 and 2014) and L8 Clos de Bèze 2012 (£2,876.98,
1.09× a £2,632.50 edge). The two checks working together is the intended
behaviour: derivation proposes, the band disposes, and a figure that does not fit
the wine's own price curve does not become a market.

**Control set (70 lines):** 8 READY · 62 REVIEW, unchanged in the totals. Two
lines gained a second merchant, exactly the two the policy predicted:

- **L09** Henri Germain Morgeot 2021 — Bordeaux Index 3×75 at £225 derives to
  £450 at 6×75, against Lea & Sandeman's £435. Reference £435 → £450.
- **L57** Hubert Lamy Clos de la Chatenière 2018 — Bordeaux Index 6×75 at £585
  derives to £1,170 at 12×75, against L&S's £1,000. Reference £1,000 → £1,170.

**L57 deserves to be named plainly.** The Burgundy control-set report called that
exact figure out as a trap: *"Naive doubling says BI is £1,170, 17% dearer; the
per-bottle arithmetic would have been silently invented."* Case-to-case
derivation now produces £1,170. The word that changed is **silently** — the line
is flagged, the source offer and its real unit sit beside the figure, and a
person has to accept it before it reaches anyone. That is the trade this decision
makes, and it should be looked at again when there is enough live data to measure
the case-to-case basis rather than assume it.

## Next time this is opened

The 5% is the weakest number in the system. It should be replaced by a measured
basis per region, and per case size if the data supports it, as soon as we hold
enough paired observations of the same wine in two units on the same day. Until
then it stays an assumption that says so.
