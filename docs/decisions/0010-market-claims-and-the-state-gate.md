# 0010 — A line with no UK Reference may not carry a market claim

**Status:** accepted, 20 September 2026.

## What the rehearsal showed

The first end-to-end run issued a buyer offer for twenty lines, every one of
them `NO_MARKET`, priced from cost at the deal's margin. Nothing stopped it. The
lines showed `NO_MARKET` on the operator's screen, so nothing was hidden from
us — but the document that would have gone to a client quotes prices against
"the UK market", and for those twenty wines we had found no UK market at all.

Two separate faults, and the first matters more than the second.

## 1. The content rule: no reference, no claim

A market claim is a statement about a market we measured. Where there is no
`uk_reference`, the document must not contain "UK Market" or "% Below UK Market"
for that line **at all** — not blank, not zero, not a dash. Absent.

This is enforced by structure, not by a template convention:

- `buyer_offer_market_claim` holds the claim, and its `uk_reference` is
  `NOT NULL`. A line with no reference has **no row**, so there is nothing to
  print, and no template change can reintroduce a claim we cannot support.
- The claim keeps what it was made against: the `run_id`, the `as_of` it was
  measured at, the `comp_count` behind it, and `below_reference`. A document is
  explicable a year later without joining back to a benchmark that may since
  have been re-run.
- The API sends `market_claim` only where one exists, so the browser has no
  field to render for a line without one.
- The document prints the two kinds of line in two tables — "Priced against the
  UK market" and "Priced on cost" — so a cost-priced line has no market cell to
  leave blank.

A line can still be sold on cost-plus. We know our cost and our price. The
document simply may not imply a basis we do not have.

## 2. The gate: NO_MARKET and REVIEW need a name

`pricing_result.requires_acknowledgement` already fired on `NEGATIVE_GP` and
`SELL_ABOVE_UK_REFERENCE` (decision 0008). It now also fires when the benchmark
state is `NO_MARKET` or `REVIEW`, through the same generated column and the same
composite-key chain into `buyer_offer_line`.

The two gates answer different questions. The commercial flags ask *is this
trade sensible*; the state asks *did we measure a market at all*. The
acknowledgement records both: `pricing_acknowledgement.state` alongside `flags`.

Yes, this means that in the Burgundy case every line needs sign-off. That is the
correct reading of the data. The fix is more merchants — see 0011 — not a softer
gate.

## What is still true

`REVIEW_FLAGS` is unchanged and still means evidence quality alone.
`COST_ABOVE_UK_REFERENCE` and `DEEP_DISCOUNT` still do not gate: buying badly is
a commercial fact, and selling below market is the product.

## Consequence

`tests/test_service.py` covers both rules, and `web/e2e/smoke.spec.mjs` drives
them through the real UI: a no-market line cannot be issued until a named
operator accepts it, and the issued document carries a market claim for the line
that has a reference and none at all for the line that does not.
