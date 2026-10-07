# 0023 — DERIVED_FROM_CASE trusts source agreement, not the constant

**Status:** accepted, 7 October 2026. A deliberate relaxation of a locked
`app/core/` invariant, made by Doug directly, with evidence cited, exactly
the way `CLAUDE.md` says that must happen: "If you believe an invariant is
wrong, say so and cite evidence. Do not change it quietly."

## The evidence Doug cited

`app/core/flags.py`'s own comment on `CASE_PREMIUM`: "No constant can be
right about an individual wine, so a derived comparable always carries
DERIVED_FROM_CASE." Doug: "Your flags.py comment argues against trusting
the constant, and I agree — the rule trusts source agreement, not the
constant." The comment was written to justify gating on derivation
*unconditionally*; its own reasoning — the constant is a median across 27
pairs, not a fact about any one wine — argues just as strongly for
releasing the gate the moment a wine's own evidence, not the constant,
confirms the derived figure.

## The rule

`DERIVED_FROM_CASE` stops gating a line — never stops being added, never
stops being shown — when:

1. the line's `comp_count` (merchants, not listings — invariant 3) is 2 or
   more, **and**
2. the vintage band (decision 0015) ran for this line and found nothing to
   exclude or flag on either side: `band_low` is not `None`, and both
   `high_outliers` and `low_outliers` are empty.

With one comp, it stays gating, stated explicitly and tested literally
(`test_one_derived_comp_never_qualifies_even_with_a_clean_band`): there is
no second source for a single comp to agree *with*. A high outlier already
means the comps did not agree, so the exemption is refused —
independently, the line would stay in review through
`COMP_EXCLUDED_VINTAGE_BAND` anyway. A kept low outlier is the same: it
already gates on its own through `LOW_COMP_OUT_OF_BAND`, so nothing here
needed to double-check it. And when the band never ran at all — no tier
for the region, invariant 18's "no band, no flag" — the exemption is
refused rather than assumed: no band means nothing to confirm agreement
against, and that is the same conservative default as the single-comp
case, not a free pass for a wine nobody could check.

## Where the line is drawn, and why there, not in `app/core/`

`app/core/benchmark.py` cannot know about vintage bands — that separation
is deliberate and stated in its own docstring ("No LLM. No network. No
name matching. No unit conversion.") and in `app/market/`'s own charter
("nothing in it may change a figure the core produced"). The vintage band
runs strictly *after* the benchmark, on its result, in a different module.

So the exemption could not live as a static change to `REVIEW_FLAGS`
membership (that would release the gate for every line with 2+ comps,
confirmed or not — exactly the blanket relaxation Doug did not ask for).
It had to be a *fact*, decided outside the core from the band's own
result, fed back in — exactly the mechanism `SellerLine.derive_units`
already uses for the same reason (decision 0016: "the pricing core does
not know what a region is and never will... it is told, not asked"). A new
field, `SellerLine.derivation_confirmed`, is that same discipline applied
to this new fact: the caller (`app/worker/jobs._benchmark_with_band`, and
`scripts/rerun_burgundy_proof.py`'s own copy of the same sequence) sets it
from the band's result, after the band has run, and `BenchmarkResult.state`
is the one place that reads it:

```python
gating = self.flags & REVIEW_FLAGS
if (Flag.DERIVED_FROM_CASE in gating and self.comp_count >= 2
        and self.line.derivation_confirmed):
    gating = gating - {Flag.DERIVED_FROM_CASE}
return State.REVIEW if gating else State.READY
```

`REVIEW_FLAGS` itself is untouched — `DERIVED_FROM_CASE` is still a member,
still gates alone, still shown on every line it was ever added to.
`app/core/flags.py`'s own opening line ("One rule, one place. If a flag is
in REVIEW_FLAGS the line cannot be READY") is updated to name this as the
one stated exception, decided where it is checked rather than where
membership is defined, so the file stops silently overstating itself.

## What this is not

Not a change to `CASE_PREMIUM`, to how a comp is derived, or to the
ranking that always puts a derived comp behind a real one at the seller's
own unit. Not a change to `ONE_COMP`, `COMP_EXCLUDED_VINTAGE_BAND` or
`LOW_COMP_OUT_OF_BAND`'s own gating — all three are untouched and still
independently sufficient to hold a line in review regardless of this
exemption. Not a relaxation of invariant 18 ("no band, no flag") — if
anything this decision leans on it more heavily, refusing the exemption
in exactly the silence that invariant already names.

## What it actually moved

Run against the 20-line Burgundy proof set
(`scripts/rerun_burgundy_proof.py`, updated to apply the same sequence
`app.worker.jobs._benchmark_with_band` now does): **no change — still
`READY 0 REVIEW 15 NO_MARKET 5`.** Two lines (L4, L17) have `comp_count ==
2` with `DERIVED_FROM_CASE`, but neither has a vintage band that actually
ran for its own vintage in this dataset ("not enough neighbouring
vintages to check") — the register simply does not have two neighbouring
vintages with offers for either wine yet. The mechanism is real and
proven by four new unit tests
(`tests/test_unit_derivation.py`: a clean two-comp agreement releasing the
gate, a one-comp line that cannot qualify, a high outlier refusing it, and
a missing band refusing it) — this proof set just does not happen to
contain a line that satisfies both conditions at once. Doug asked for the
rule as specified regardless of what this one dataset shows; built as
specified, reported honestly rather than oversold.

## Consequences

- `app/core/models.SellerLine.derivation_confirmed: bool = False` (new
  field, same discipline as `derive_units`).
- `app/core/benchmark.py`: `BenchmarkResult.state` carries the exemption;
  the module docstring (invariants 3 and the rounding note) and
  `app/core/flags.py`'s opening comment, `REVIEW_FLAGS`'s own comment, and
  the `CASE_PREMIUM` comment block all updated to state the exception
  rather than the old unconditional claim.
- `app/worker/jobs._benchmark_with_band`: computes and applies
  `derivation_confirmed` after the existing band-flags re-benchmark step,
  from the same `check` it already had in scope. No new database read, no
  new job.
- `scripts/rerun_burgundy_proof.py`: the same sequence, so the proof stays
  a true mirror of the real pipeline rather than a stale copy of it.
- Tests: 4 new in `tests/test_unit_derivation.py` (offline, pure). 341
  offline (was 337).
