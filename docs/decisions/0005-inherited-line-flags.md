# 0005 — Inherited line flags can only move a line towards review

**Status:** accepted, 19 September 2026.

## Context

`NAME_REVIEW` and `FORMAT_REVIEW` are set by identity verification, upstream of
the benchmark. `DERIVED_FROM_CASE` is stamped by an explicit operator action
(decision 0001). All three are in `REVIEW_FLAGS`. But nothing persisted them on
a line, and `benchmark()` never saw them. A line whose name was in doubt could
come out READY because two merchants agreed on a price for the wine it had been
matched to.

## Decision

- `seller_line.flags text[]` persists them. A CHECK restricts it to exactly
  those three.
- `SellerLine.inherited_flags: frozenset[Flag]` carries them into the core.
- `benchmark()` unions them into `result.flags` before state is derived.
- `benchmark()` raises `ValueError` if an inherited flag is not in
  `REVIEW_FLAGS`.

## The one-way rule

Inherited flags may only ever move a line towards review, never away from it.
Two things enforce this:

1. **Only review flags can be inherited.** An upstream `WIDE_SPREAD`,
   `ONE_COMP` or `NO_MARKET` would be a claim about the market that the
   benchmark did not make. It would sit in the flags beside figures that
   contradict it.
2. **Inheriting only adds.** It cannot remove a flag the benchmark derived, and
   state is computed from the union. With review flags only, adding a flag can
   turn READY into REVIEW. It cannot turn REVIEW into READY, and it cannot turn
   NO_MARKET into anything else.

`tests/test_traps.py::test_inherited_flags_only_ever_move_a_line_towards_review`
checks every subset of the three flags against a READY market, a one-comp market
and no market. It asserts the state never improves, and that the Floor,
Reference and Median are unchanged.

## Clearing a flag

Clearing `NAME_REVIEW` does move a line away from review. That is an operator
decision, not a benchmark decision. It is made through
`PUT /lines/{id}/identity`, which requires `approved_by` and records the
previous and new flags in `seller_line_identity_history`.
