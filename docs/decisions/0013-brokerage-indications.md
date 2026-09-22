# 0013 — A brokerage indication is corroboration, never a price

**Status:** accepted, 22 September 2026. The first brokerage source; there will be more.

## Context

FINE+RARE is a brokerage, not a stockholder. What it publishes per wine is
`productMarketInfo.unitPrice`: an aggregated pan-European indication of where
the wine would broker, gathered across merchants. Nobody has said they hold it
at that price, which is why **every variant on every product reads
`quantity: 0`**.

That is not a small distinction dressed up. Measured live on 2026-09-22, the
indication for 2011 Rousseau Charmes-Chambertin was **£590**, against Farr at
£610 and Bordeaux Index at £650 for the same bottle. Ingested as an ASK it
would have become the Floor, and with one other merchant it would have become
the Reference — a client document quoting a price nobody offered stock at.

## Decision

**`PriceKind.INDICATION`.** The existing `Reject.KIND` screen then excludes it
from Floor, Reference and Median with no change to `benchmark()`'s arithmetic.
Duty status is `UNKNOWN` — nobody has said In Bond or Duty Paid either — so the
`DUTY` screen excludes it a second time. An indication fails closed twice.

**Kept as corroboration, beside cross-unit evidence.** `BenchmarkResult.indications`
carries each indication with `variance_vs_reference`, and a run stores them with
role `indication`. Same treatment as cross-unit: visible to the operator, never
priced from, never on a client document. Where a line has both a Reference and
an indication the variance is shown, because a Reference 20% away from where a
brokerage thinks the wine trades is worth an operator's eye — as context, not as
a correction.

An indication alone is `NO_MARKET`. A market is somewhere you can buy.

**`merchantCount` is context, and FINE+RARE counts once.** The 2011 Chambertin
indication is drawn from 8 merchants. That is one FINE+RARE record; depth counts
merchants we hold an offer from, not merchants a third party says it polled.
Invariant 3 is untouched — depth counts merchants, not listings, and not other
people's counts. The figure is kept in the offer's `raw` and shown beside the
indication, so an operator can see how thin the brokerage's own view is.

## Why not just drop them

Coverage is thin and honest (decision 0001), and an indication is real evidence
about a real market — it is simply not an offer. Discarding it would throw away
the only signal we have on wines no approved merchant is currently listing.
Pricing from it would be inventing a market. Showing it, clearly labelled,
beside figures it cannot influence, is the same bargain we struck with
cross-unit evidence.

## For the next brokerage

The shape generalises: a source that publishes a view rather than stock is
`PriceKind.INDICATION`, `DutyStatus.UNKNOWN`, `is_buyable=False`,
`StockType.BROKERED`, and counts as one merchant. If a future source publishes
both its own stock and an aggregated view, they are two different records and
must be normalised as two, not merged into a cheaper-looking one.

## Consequence

- FINE+RARE is a deep-search source (decision 0011), searched per producer and
  vintage: `/sitemap-producers.xml` is its key index, and product URLs shaped
  `/product/<id>/<vintage>-<wine>-<producer-slug>` select a target exactly.
- `MIXED_LOT` matches `assort` and `assortment`: FINE+RARE writes "2002 DRC
  Assortment (2xEZ, 2xGDE, ...)" and never "mixed", so a pattern looking only
  for "mixed" ingests a twelve-bottle assortment as one wine.
- Most of the back catalogue publishes no indication at all; those records are
  ordinary rejections with a reason, not silence.
