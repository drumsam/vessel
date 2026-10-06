# 0021 — VESSEL names its reference market; Hong Kong retail joins UK In Bond

**Status:** accepted, 7 October 2026. Follows decision 0020 directly — this
is a correction and an extension to VESSEL Private Sale, not a new product.

## The missing source

Doug's instruction named `docs/research/hk-vs-uk-market-reference.md` as the
source for this work. It does not exist in the repository — checked by
filename and by content search, in `docs/research/` and in `~/Downloads/`.
Nothing in this decision invents the evidence that file would have held. The
only facts used below are the ones stated directly in the request: Hong Kong
retail runs a median 22% above UK In Bond, from 9 matched pairs, range -21%
to +46%, and the two named markets, `UK_IN_BOND` and `HK_RETAIL`. If a third
market or a different quality bar for single-source HK evidence was meant to
come from that file, it is still missing and still not guessed at here.

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

## An unrelated mismatch, noticed while verifying, not touched

`scripts/rerun_burgundy_proof.py` currently prints `READY 0 REVIEW 15
NO_MARKET 5`; `CLAUDE.md`'s own testing section still says to expect `READY
0 REVIEW 5 NO_MARKET 15`. Confirmed via `git stash` that this mismatch
exists identically on the last committed commit (`8e3cd9a`), before any of
this decision's or the three preceding fixes' changes — decision 0018
(derivation beyond Burgundy, same session, committed as `0ccbd62`) most
likely moved these counts and the doc was never updated to match. Not this
decision's to fix quietly; flagged here per the project's own house style
rather than corrected without saying so.

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
