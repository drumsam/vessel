# 0014 — Brokered comps stay in the benchmark; an identical price is a note

**Status:** accepted, 23 September 2026. Doug's decision, on the control set.

## Context

Control-set line L68: Goedhuis lists a **brokered** offer (its SKU carries the
`-BR-` segment) at **£1,300.00**, and Lea & Sandeman lists the same wine in the
same unit at **£1,300.00**. To the penny.

Two questions fall out of that, and they have opposite answers.

## Decision

**1. A brokered offer is a comp, and it counts for depth.**

Much of the trade brokes now. A brokered offer is a real offer at a real price
from a named UK merchant, and on a thin wine it is often the only visible price
there is. Excluding brokered stock would delete the cheaper of the only two UK
prices on L68: the Floor would rise, the line would lose its second merchant and
become `ONE_COMP`, and we would be poorer informed, not safer.

This is **not** the same as a brokerage indication (decision 0013). FINE+RARE
publishes an aggregated view of where a wine *would* broker, with `quantity: 0`
against every variant — nobody has said they hold it. Goedhuis holds a named
parcel and will sell it. One is a price; the other is an opinion about prices.

`StockType.BROKERED` therefore changes nothing in the arithmetic. It is recorded
because it is true, and shown to the operator.

**2. Two merchants at one price to the penny is an operator note. Nothing else.**

Identical prices may be one parcel seen twice, so "two merchants" may overstate
how many places the wine can actually be bought. The operator is told:

> same price as another merchant (Goedhuis, Lea & Sandeman at 1300.00) —
> may be the same parcel

`SAME_PRICE_AS_ANOTHER_MERCHANT`, in `app/market/parcel.py`. Deliberately **not**
in `REVIEW_FLAGS`: a coincidence of price is a reason to look, not a reason to
stop. It never gates an export, never excludes a comp, never changes depth,
never moves the Floor, the Reference or the Median, and never reaches a client
document.

Only equality to the penny is reported. £1,300.00 against £1,299.99 is two
merchants pricing keenly, and a note that fires on that is noise that gets
ignored on the day it matters.

The note is computed from the run's own merchant-bests, so one merchant listing
the same wine twice at one price is not reported against itself — that is a
duplicate listing, which the benchmark already collapses — and the note still
reads correctly after the snapshots behind it have been pruned.

## Consequences

- `app/core/` is untouched. No flag, no screen, no arithmetic changed.
- Tests: `test_l68_goedhuis_brokered_offer_stays_in_the_benchmark`,
  `test_l68_identical_price_is_an_operator_note_never_a_gate`,
  `test_a_penny_apart_is_two_merchants_not_one_parcel`,
  `test_one_merchant_listing_twice_is_not_a_parcel_coincidence`.
- Related, and it decided part of 0015: on platforms where the holder sets the
  price, asking prices skew high. That is one reason the vintage-band check
  auto-excludes only *dear* outliers and never cheap ones.
