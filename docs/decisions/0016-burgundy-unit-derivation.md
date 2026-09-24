# 0016 — Burgundy comps across case sizes, at the measured case premium

**Status:** accepted, 24 September 2026, and revised the same day when the
premium was measured. Doug's decision, specified in
`docs/research/burgundy-unit-policy.md`; the constant comes from
`docs/research/case-premium-measurement.md`.

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
2. Cases carry a crude **5% premium** over loose bottles, per bottle. *(Measured
   the same day and replaced by parity — see the next section. The decision to
   adjust at all is what mattered; the number was always meant to be measured.)*
3. Large formats are out. Magnums and above never mix with 750ml prices in
   either direction.

In his words: our job is to find a sensible starting point for a market price,
and refusing to compare 3×75 with 6×75 was costing us most of the evidence we
had.

## The premium is 1.00, and it was measured

This started at an assumed 5%. It was measured the same day and the answer is
**parity**: `CASE_PREMIUM = Decimal("1.00")`.

Bordeaux Index publishes loose bottles and cases of the same wine on the same
card in the same response, which is a paired same-day observation needing no
assumption about timing or drift. Thirty Burgundy producer pages, 512 cards,
In Bond and 750ml only, 27 usable pairs across 12 domaines and vintages
1999–2020:

| | |
|---|---|
| Median ratio | **1.0000** |
| Mean ratio | 0.9737 |
| Identical to the penny | 10 of 27 |
| Within ±5% of parity | 16 of 27 |
| Range | 0.7038 → 1.1525 |

A case is priced at the same rate per bottle as a loose bottle more often than
at any other rate, and when it differs it is slightly more often **cheaper** per
bottle, not dearer. Ten pairs identical to the penny is a merchant pricing per
bottle and multiplying.

**The 5% was not far off the centre, but it was biased in the direction that
costs us.** A derived figure that is too high raises the UK Reference, which is
how we overpay and how a client gets overpriced. Parity has no such bias.

`CASE_PREMIUM` carries the distribution in a comment where it is defined,
`app/market/units.py` builds the operator's sentence **from the constant** so it
cannot drift away from what the code does, and the console prints it beside
every derived figure:

> Derived from a 1x75cl at 197.00 from Bordeaux Index: 1182.00 at 6x75cl.
> Cases and loose bottles are priced at the same rate per bottle — measured
> median 1.0000 across 27 paired observations at Bordeaux Index. A quarter of
> those sat more than 5% out (0.7038 to 1.1525), so this is not a fact about
> this wine.

A figure that looks observed and is not is the failure this whole system exists
to prevent. It may never be silent.

**The spread is the real finding, and nothing else about this decision changed
because of it.** A quarter of the pairs sit more than 5% from parity and the
tails run to −30% (2014 Lignier-Michelot Clos de la Roche: £175 loose against
£123.17 a bottle in six) and +15% (2006 Roumier Les Cras: £600 against £691.50).
No constant can be right about an individual wine. The flag is the safeguard;
the constant never was.

Honest limits, which is why the next section exists: **one merchant**, 27 pairs,
Burgundy only. Goedhuis Waddesdon was tried for a second opinion — 8,750
variants, 2,194 In Bond 750ml rows, and exactly **one** wine listed both loose
and cased. A merchant who sells only by the case cannot answer this question.

## Measuring it properly, from here on

Every capture now records each wine it meets in two pack sizes in one fetch:
same wine, vintage, bottle size **and duty status**, best price per pack size,
each size paired against the smallest present. `case_premium_pair`, written by
`ingest()`, read by `scripts/case_premium_report.py`, and read by nothing in the
pricing path — it is an observation about a merchant's pricing policy, not
evidence about a wine.

The bar for moving the constant on evidence is **300 pairs across 5 merchants**.
Below that the report says so. Changing it is still a decision record and a pull
request, because it moves prices.

Case-to-case pairs are stored too, and counted separately: they measure
something else, which is why case-to-case derivation applies no premium at all.

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
£360 and would otherwise take the Floor away from a real £600 ask, on a constant
that describes a merchant's pricing policy and not this wine.

If derived comps should rank equally with exact-unit ones, that is Doug's call to
make explicitly. It is not the default here.

## The rule

Scope: **Burgundy only**, by region, and **750ml only**, both sides.

| Offer | Comparable at N×750 |
|---|---|
| `pack_size == N` | the offer itself — exact, no adjustment, ranks first |
| loose (1×750) | `price × N × CASE_PREMIUM` |
| case of M ≠ N, both > 1 | `price / M × N` — no premium, case to case |
| seller line is 1×750, offer is a case of M | `price / M / CASE_PREMIUM` |
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
from a case to a loose bottle, so every one carries the premium and a review
flag. READY stays 0 — nothing became shippable without a person.

Measuring the premium at parity did not change those counts, but it did move
every derived figure on this set **up by 5%**, because these are all cases
divided down to loose bottles: dividing by 1.05 said a loose bottle is cheaper
per bottle than the case, which is what the measurement contradicts. L4's
Reference went from £1,941.90 to £2,039.00. The old constant was under-pricing
in this direction and over-pricing in the other; parity is unbiased in both.

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

The constant is now measured, but from one merchant and 27 pairs. The collection
step is gathering more on every capture. When the report clears 300 pairs across
5 merchants, look at it again — per region, and per case size if the data
supports it. Until then it rests on Bordeaux Index alone, and the report says so
every time it is run.
