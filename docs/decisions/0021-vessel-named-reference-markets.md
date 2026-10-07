# 0021 — VESSEL names its reference market; Hong Kong retail joins UK In Bond

**Status:** accepted, 7 October 2026. Follows decision 0020 directly — this
is a correction and an extension to VESSEL Private Sale, not a new product.

## The missing source, and then found

Doug's instruction named `docs/research/hk-vs-uk-market-reference.md` as the
source for this work. At the time this decision was first written it did not
exist in the repository — checked by filename and by content search, in
`docs/research/` and in `~/Downloads/`. The mechanism below was built from
only the facts stated directly in the request: a median 22% premium, 9
matched pairs, range -21% to +46%, and the two named markets.

The document was added 7 October 2026 (commit `b726309`) and has now been
read in full. Checked against it, point by point:

- **HK retail vs UK In Bond trade are different levels of the chain** — "part
  of the 22% is simply retail margin, not geography." The mechanism never
  conflates them: `UK_IN_BOND` and `HK_RETAIL` are separate, independently
  named values in `vessel_reference.market` and `vessel_listing.reference_market`,
  never blended into one figure. Nothing computes a "true" cross-market
  adjustment; each market's reference is exactly what was captured for it.
- **One HK source (Altaya).** The single-source refusal this decision already
  built — `evidence_claim(1, market="HK_RETAIL", ...)` always returns
  `can_list=False`, backed by `vessel_listing_single_source_needs_band` at the
  database — applies to Altaya exactly as it would to any other single HK
  source. Not softened.
- **Nine pairs, range -21% to +46%, "not a constant."** Confirmed by reading
  the code, not just by intent: nothing in `app/vessel/` computes, stores, or
  defaults to 22%, 1.22, or any other fixed HK/UK ratio (`grep -rn "22%\|1\.22"
  app/vessel/` finds only this decision's own explanatory comment). Every
  `HK_RETAIL` reference price is a number an operator typed in for that
  specific wine, never a UK figure scaled by a market-wide median.
- **FX 10.37 is a public rate, not a bank rate.** Confirmed `10.37` appears
  nowhere in the codebase outside this research document
  (`grep -rn "10.37"` across `.py`/`.jsx`/`.sql`, repo-wide, zero matches
  outside `docs/research/`). `fx_hkd_per_gbp` has no default anywhere it is
  declared (`vessel_schemas.RecommendIn`, the engine functions, the
  migration's column) and `vessel_listing_fx_recorded` requires it, its
  source and its date whenever currency is not GBP — a listing cannot be
  priced in HKD without an explicit, recorded rate from an explicit, recorded
  source. Nothing defaults or falls back.
- **Montrose 1989 was cheaper in HK — mature Bordeaux is a real exception.**
  Nothing in the mechanism assumes `HK_RETAIL > UK_IN_BOND`, or orders the two
  markets at all: `recommend_lines()` takes whichever market the operator
  names for that line and prices from exactly the figure given for it, with
  no comparison against the other market's figure and no validation that one
  must exceed the other. The document's own suggestion — "route by market,
  sell prestige Burgundy and Champagne into Asia, mature Bordeaux into the UK"
  — is a merchandising judgement for the operator to make per line by picking
  `reference_market`; it is deliberately not encoded as a rule, which would be
  exactly the kind of invented assumption `CLAUDE.md` rules out.

No code changed as a result of this check. The mechanism already matched the
document's caveats before the document itself was available; this section
records that it was checked, not assumed.

## What changed, and why "a listing needs a named reference market" cuts both ways

Before this decision, every `vessel_listing` was priced from the UK
benchmark implicitly — there was no column saying so, because there was only
ever one market. `vessel_listing.reference_market` now names it on every
row, `NOT NULL`, no default after backfill: code must always say which
market it means, exactly as instructed.

The reverse direction matters just as much: naming `HK_RETAIL` without
supplying what it needs does not fall back to UK silently, and does not
invent a Hong Kong price from the UK one scaled by 22%. It excludes the
line with `NO_MARKET`, same as a UK line with zero comps. "Accuracy beats
coverage... fail closed" (`CLAUDE.md`) applies to a market exactly as it
applies to a merchant.

## `vessel_reference`: append-only, one row per captured market

"Allow more than one reference per line" meant a new table, not a second
column: `vessel_reference` holds one row per (line, market) capture —
`reference_price` (the lot total, in `currency`), `source_count`, and
`evidence` (a `jsonb` array — a `benchmark_run.run_id` for `UK_IN_BOND`, or
whatever notes/URLs an operator typed in for `HK_RETAIL`, since no adapter
exists for that market yet). It is append-only, enforced by a trigger
(`vessel_forbid_reference_mutation`) that mirrors `vessel_mandate`'s own:
a market's price changing is a new captured row, never an edit to one a
listing may already point to. `vessel_listing.reference_id` is the FK to
the exact row consulted — provenance a seller or an auditor can trace,
not just a number.

A line can hold both: `test_a_line_can_carry_both_a_uk_and_an_hk_reference`
recommends a line against its UK benchmark, then records an independent
`HK_RETAIL` capture for the same line, and confirms neither row disturbs
the other. Which one prices a given listing is the operator's per-line
choice at `recommend_lines()` time (`reference_market` in each line's
choice dict) — the band the buyer actually buys in, as instructed.

## No HK-equivalent of the vintage-band check — refused, not guessed

`UK_IN_BOND`'s one-source exception exists because
`app/market/vintage_band.py` (decision 0015) gives it a quality-matched
neighbour check to lean on. Nothing like that exists for `HK_RETAIL`, and
the missing source document would have been the place such a check might
have been specified. Rather than inventing one, a single-source `HK_RETAIL`
reference is refused outright —
`evidence_claim(1, market="HK_RETAIL", ...)` returns `can_list=False`
always, regardless of `vintage_band_passed`. The database repeats this:
`vessel_listing_single_source_needs_band` now reads `source_count >= 2 OR
(reference_market = 'UK_IN_BOND' AND vintage_band_passed)` — a HK line
cannot be written in with one source no matter what future code forgets to
call `evidence_claim` first. `test_hk_retail_single_source_is_excluded_at_the_database_too`
proves the constraint, not just the Python gate.

## The page claim names the market

`reference_label` and the new `market_claim_sentence()` are both
market-aware, but `UK_IN_BOND`'s own wording is deliberately unchanged:
every listing built under decision 0020 said "Market reference" /
"Indicative reference" and "N% below market" with no market named, and
naming the market now does not reword what they already said. Only a
market other than `UK_IN_BOND` gets the explicit name — "Hong Kong retail
reference", "34% below the best Hong Kong retail offer we can find" — the
exact shape from the request. Composed once, server-side
(`app/api/vessel_schemas.ListingOut.market_claim`), so the wine page and
the drop page print the same words; both JSX pages were updated to render
it in place of their old market-silent copy.

## What this is not

No HK adapter, no automated HK evidence collection, no `HK_RETAIL`
single-source sanity check, and no change to how `UK_IN_BOND` listings are
priced or worded. "Small now" is built: a named market, a place to capture
more than one, and the arithmetic generalised to use whichever one is
named. "A migration later" is still owed once a real HK evidence pipeline
exists — most likely a proper adapter-style capture for `HK_RETAIL` in
place of today's by-hand entry, and whatever single-source check that
pipeline's own evidence quality turns out to support.

## The REVIEW/NO_MARKET mismatch: real, but not decision 0018's doing

`scripts/rerun_burgundy_proof.py` prints `READY 0 REVIEW 15 NO_MARKET 5`
where `CLAUDE.md`'s testing section once said to expect `READY 0 REVIEW 5
NO_MARKET 15`. Doug asked, correctly, whether this was decision 0018
(derivation beyond Burgundy) doing exactly what it should — moving
previously-unpriceable lines out of `NO_MARKET` into `REVIEW` — or a
regression hiding behind a stale doc, and specifically whether `READY` had
silently dropped from a non-zero number.

Checked by walking the commit history in a disposable worktree
(`git worktree add`, not `git stash`, so the check could step through
several commits without disturbing the working tree) and running the proof
script at each:

| Commit | Change | READY | REVIEW | NO_MARKET |
|---|---|---|---|---|
| `6038a05` and three commits after it | pre-derivation | 0 | 5 | 15 |
| `2ecb7a2` | **decision 0016** — Burgundy comps across case sizes | 0 | 15 | 5 |
| `b4d27fb` | 0016's premium measured, not assumed | 0 | 15 | 5 |
| `0ccbd62` | **decision 0018** — derivation beyond Burgundy | 0 | 15 | 5 |
| `e4ac3ca` / current | this decision's own work | 0 | 15 | 5 |

**`READY` is 0 in every commit checked, before and after.** No regression:
derivation never reduced ready lines, because none of the Burgundy proof's
20 lines were `READY` to begin with or after — deriving a comparable only
moves a line into `REVIEW` (it always carries `DERIVED_FROM_CASE`, a review
flag by invariant 9), never straight to `READY`.

**The flip is decision 0016, not 0018.** 10 of the 20 Burgundy lines moved
from `NO_MARKET` to `REVIEW` the moment case-size derivation shipped
(`2ecb7a2`, 24 September), a full session before decision 0018 existed.
0018 extended derivation to every other region with a recorded colour; it
left these 20 Burgundy lines' own counts untouched, because Burgundy was
already covered. `CLAUDE.md`'s own doc has already been corrected to say
`REVIEW 15 NO_MARKET 5` (re-read after this session's compaction, it no
longer says the stale `REVIEW 5 NO_MARKET 15`) — this section exists to
record that the number is right and attribute it to the correct decision,
since the request asked specifically whether it was.

## Consequences

- Schema: `vessel_reference` (new table, append-only via trigger) and
  `vessel_listing.reference_market`/`reference_id` (migration
  `0017_vessel_multi_market_ref`); `vessel_listing_single_source_needs_band`
  and `vessel_forbid_price_change_once_approved` both updated to know about
  the new columns.
- `app/vessel/engine.py`: `MARKET_LABELS`, `reference_label()`,
  `market_claim_sentence()`, and `evidence_claim()` taking an optional
  `market` (default `UK_IN_BOND`, preserving every existing call site's
  behaviour and wording exactly).
- `app/vessel/repo.recommend_lines()`: per-line `reference_market` choice;
  `HK_RETAIL` requires `hk_reference_price`/`hk_source_count` (and optional
  `hk_evidence`) in that line's choice dict or the line is excluded,
  `NO_MARKET`. Every recommended listing, either market, now gets its own
  `vessel_reference` row.
- `app/api/vessel_schemas.py`/`vessel.py`: `LineChoiceIn` carries the new
  per-line fields; `ListingOut` carries `reference_market`, `reference_id`
  and the composed `market_claim`.
- `web/app/vessel/listings/[listingId]/page.jsx` and
  `web/app/vessel/drops/[dropId]/page.jsx`: print `listing.market_claim`
  in place of the old unqualified "% below market" text.
- Tests: 8 new in `tests/test_vessel.py` (3 offline, 5 against Postgres),
  covering the market-aware label and claim sentence, the HK single-source
  refusal (Python and database), pricing a listing purely from a manual HK
  figure with no UK run at all, the missing-input exclusion, a line
  carrying both markets, and `vessel_reference`'s append-only trigger. 326
  offline, 458 with Postgres — up from 323 / 450 after the three corrections
  below.

## The three corrections this decision shipped alongside

Requested in the same message, built first, same commit:

1. **`fx_rate` renamed to `fx_hkd_per_gbp`** everywhere in `app/vessel/`,
   its migration, its API schemas and routes, and its tests. Decision
   0020 had flagged the bare name as "worth a second pair of eyes"; Doug's
   call was to remove the ambiguity structurally rather than leave it to a
   comment. `migrations/versions/0016_vessel_private_sale.py` was edited
   directly (not a follow-up migration) since it was committed this same
   session and had not shipped anywhere beyond it.
2. **Proof of payment: one fixed 2-hour extension, then an operator.**
   `submit_proof_of_payment()` now grants exactly `PROOF_OF_PAYMENT_EXTENSION`
   once and refuses a second call (`AlreadyExtended`);
   `expire_overdue_reservations()` skips any reservation that has already
   used its extension; `reservations_needing_confirmation()` and
   `cancel_reservation()` (both new, operator-only) give the human path
   decision 0020 had left as "confirm before drop one goes live with real
   money."
3. **`seller_offer`/`seller_offer_line` corrected to `uuid`** directly in
   `docs/research/offer-document-spec.md` — already reported fixed in
   decision 0020; unaffected by this decision's own work.
