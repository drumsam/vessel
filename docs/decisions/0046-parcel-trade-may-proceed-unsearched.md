# 0046 — a parcel trade may proceed on a line nobody has searched

**Status:** accepted, 30 October 2026, on Doug's instruction. Found during
the first production smoke test of VESSEL Pocket Milestone 1: production
had never collected anything (0 offers, 0 snapshots, 0 search keys), so
EVALUATE could not run a benchmark for any wine, and CREATE OFFER — which
saved its price against a benchmark run — refused every trade. "Market-data
weakness should not prevent trading; factual/identity uncertainty may."

## What changes

Invariant 10 said a line nobody has searched gets "no run, no price, no
buyer export." It still does, for every basis that derives its price from
the market. The one exception is `parcel_trade`, where the sell price is
Doug's own number and the market is a comparison, not an input:

- `pricing_result.state` gains `NOT_SEARCHED`, with `run_id` NULL exactly
  then (`pricing_result_run_iff_searched`), and only on `parcel_trade`
  (`pricing_result_not_searched_parcel_only`) — enforced by the database,
  not by convention.
- `NOT_SEARCHED` gates export through `requires_acknowledgement` exactly
  as `NO_MARKET` and `REVIEW` do. CREATE OFFER refuses without an explicit
  accept ("Proceed without current market evidence"), recorded in
  `pricing_acknowledgement` like any other.
- It applies only while there is genuinely nothing to search against. Once
  any capture exists, EVALUATE benchmarks the line and CREATE OFFER refuses
  a run-less price until it has.

## What does not change

The states are never collapsed (decision 0040): MARKET found, no current
market evidence found (`NO_MARKET`), not checked (`NOT_SEARCHED`), and a
collection that failed are four different things on screen and in data.
Identity, vintage, bottle size, pack size, bond status and price basis
still block. Running a merchant collection is not a prerequisite for
Pocket to work; whether to seed production with merchant lists as
background data is a separate decision.

Migration `0038_parcel_not_searched`.
