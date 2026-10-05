# 0018 — Derivation beyond Burgundy

**Status:** accepted, 5 October 2026. Doug's instruction, from a live cellar:
"don't worry about case pricing, use whatever we can find."

## Context

Decision 0016 let a Burgundy line derive a comparable across case sizes, at a
measured premium, gated behind `SellerLine.derive_units`. It was scoped to
Burgundy because that was the evidence in hand at the time.

A loose-bottle private cellar makes the cost of that scoping visible: 84
Champagne lines and 59 Bordeaux lines in the brief's cellar came back
`NO_MARKET` purely because merchants sell those wines by the case and the
seller's line is a single bottle — exactly the gap decision 0016 closed for
Burgundy, now showing up everywhere else.

## Decision

**Derivation is no longer region-restricted.** `derivation_allowed(register_key)`
now returns true for any wine whose region **and** colour are both recorded —
which is the only thing it ever needed to check structurally, since
`repo.register_key()` already returns `None` for a wine with either missing.
A wine with no region or colour at all is the one case still refused: there is
nothing to widen from, which is the exact-unit rule of decision 0001 continuing
to hold for an unidentified wine. Nothing in `app/core/` changed for this —
the unit-screen exception and `derive_units` switch were already
region-agnostic from 0016; only the gate that decides what to set the switch
to, in `app/market/units.py`, needed to widen.

**The constant does not change; the label does.** `CASE_PREMIUM` stays
`Decimal("1.00")` everywhere derivation runs. For Burgundy that is a
measurement (27 paired observations, decision 0016). Outside Burgundy it is a
working assumption that the same pattern holds — plausible, since the
mechanism it measures (a merchant pricing a case at a per-bottle rate close to
its loose price) is not Burgundy-specific, but unproven for any other region
until its own pairs exist. `MEASURED_REGIONS` (Burgundy red and white only)
decides which wording a derived figure gets:

- **Measured** (Burgundy): "measured median 1.0000 across 27 paired
  observations at Bordeaux Index. A quarter of those sat more than 5% out…"
  — unchanged from 0016.
- **Assumed** (everywhere else): "Case premium assumed at the measured
  Burgundy rate (parity) — no {Region} observations yet.
  `scripts/case_premium_report.py` says when there are enough to check."

Both sit behind the same two safeguards 0016 already built and which this
decision does not touch: `DERIVED_FROM_CASE` still gates review, and
exact-unit comps still rank first. Those were built because no constant can
be right about an individual wine, whatever region it is in — if anything,
that argument is stronger outside Burgundy, where there is no evidence at all
yet, only a plausible carry-over.

**Every region accumulates its own evidence from here.**
`case_premium_pair` (decision 0016) was already written per wine, not scoped
to Burgundy — any capture that meets a wine in two pack sizes records the
pair regardless of region, so Bordeaux and Champagne pairs have been
accumulating since that migration, waiting to be read back. Nothing new was
needed to "keep recording pairs per region"; `scripts/case_premium_report.py`
groups by merchant today and can be extended to group by region through the
same `wine.region`/`wine.colour` join `register_key()` already uses, the day
there are enough rows in a region to make that grouping meaningful.

## Consequences

- `app/market/units.py`: `DERIVABLE_REGIONS` is gone; `derivation_allowed()`
  no longer consults an allow-list. `MEASURED_REGIONS` carries what
  `DERIVABLE_REGIONS` used to mean, now for labelling only.
  `is_measured_region()` and `assumed_caveat()` are new. `derivation_note()`
  takes an optional `register_key` and defaults to the measured wording when
  omitted, so every pre-existing Burgundy test and call site is unaffected.
- `derived_from_json()` and `save_benchmark()` thread the line's region
  through to the note, and the stored JSON carries a `measured: bool` flag
  alongside the note text, for a console that wants to render the distinction
  as more than prose later.
- Tests: `tests/test_unit_derivation.py` — general derivation, the
  measured/assumed split in both the pure helper and a full `benchmark()`
  run, and a Bordeaux case proven to derive at the identical arithmetic a
  Burgundy one would.
- The Burgundy proof and the 70-line control set are unchanged by this
  decision: both are Burgundy-only evidence, so there is nothing in either
  fixture for a region-general gate to newly admit. The 561-line cellar this
  was written for is not in the repository as a fixture, so its Champagne and
  Bordeaux counts are not re-run here; the mechanism is tested directly
  instead, at the resolver and pipeline level, against synthetic Bordeaux
  evidence built the same way every other adapter-independent test in this
  codebase is.
- The 50-line Bordeaux control set (`docs/research/bordeaux-control-set-report.md`,
  captured 26 September) does not move this decision's numbers either, for a
  more specific reason: every comp it holds is already the seller's exact
  unit — no cross-case-size near-miss sits in that fixture at all, unlike the
  Burgundy set's L09/L57. What it DOES confirm, directly, is why this
  decision was worth making: Bordeaux prices on evidence for 36% of its lines
  against Burgundy's 4%, so a region-general gate matters most exactly where
  depth already exists and a merchant is most likely to hold the stock in a
  case the seller's line does not match.
