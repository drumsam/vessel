# 0023 — Operator-entered auction evidence: Bonhams, Christie's, Heritage, Zachys

**Status:** accepted, 7 October 2026. Builds the auction layer CLAUDE.md has
named as "not built yet" since this file began; follows
`docs/research/auction-evidence-form-spec.md` closely, with two corrections
this session has already made twice elsewhere, and one deliberate widening
of the spec's own closed house list, made explicitly rather than quietly.

## What Doug asked, and what was already on record

Doug: "I still want to be able to access prices from auctions: heritage,
christies, zachys etc. we should find a way to pull those in." Before
writing any code, the existing research was read: `auction-access-pack.md`
(24 September), `auction-evidence-form-spec.md` (21 September) and
`auction-coverage-test.md` (24 September) had already answered most of
this question three weeks earlier.

The finding, reported before building anything: **Heritage's and Zachys's
own terms restrict use to personal/non-commercial use**, and the spec's
own reasoning is explicit that "hand-entry for a commercial pricer is
still commercial use" — so its closed list named only `BONHAMS` and
`CHRISTIES`, by name excluding `SOTHEBYS`, `HERITAGE`, `ZACHYS`, `ACKER`
and `IDEALWINE`. `CLAUDE.md`'s own collector-politeness rule says the same
thing about a stated anti-automation position: ask for a licence, don't
route around it.

Doug's answer, asked for directly rather than assumed: **build it anyway**,
over that finding, said out loud rather than done quietly. That is what
this decision builds — hand-entry for all four houses, never a scraper for
any of them. The distinction matters: Heritage's terms additionally and
separately prohibit *automated* collection outright, which a scraper would
breach in a way hand-entry does not. Nothing in this codebase scrapes any
of the four houses' sites; nothing in this decision changes that. Adding a
fifth house, or building an actual feed/licence-based adapter for any of
them, needs its own decision — this one is deliberately only as wide as
what was asked for.

## Two corrections, same two this session has already made twice

1. **`auction_evidence_id uuid`, not `bigserial`.** Every other table in
   this schema is `uuid` — decision 0020 made this exact correction for
   `seller_offer`/`seller_offer_line` three weeks ago. The spec was
   written before that correction; it is applied here too.
2. **`entered_by`/`retracted_by` are `operator_id`, from the session, not
   `text`.** The spec predates an operator session existing to source them
   from. Invariant 14 (decision 0009) is explicit: who did something is
   the server's answer, never the caller's, and a body naming someone else
   is a 422. `app/api/main.py`'s new routes take `entered_by`/`retracted_by`
   from `current_operator`, exactly like every other audited write in this
   codebase.

## `auction_result` (0001_baseline): found, not touched

Schema.sql already had an `auction_result` table — full hammer/premium/
quarantine columns, created in the frozen baseline migration, imported by
nothing anywhere in `app/`, `tests/` or `docs/`. It predates all three
research documents this decision follows and appears to be an earlier,
superseded design for the same idea. `0001_baseline` is frozen, so it was
not dropped; it stays, dead, next to the table actually built. Flagged
here per the project's own house style — a contradiction reported, not
fixed quietly.

## The rule this must not break

Auction evidence is a health check. It never sets, moves or substitutes
for the UK Floor, Reference or Median, and it never appears on a client
document. `app/auction/` is its own package, read by its own module, and
nothing under `app/core/` or `app/pricing/` imports it —
`test_auction_evidence_never_reaches_benchmark` proves that by walking the
AST of every file in both directories, not by convention.

Per-bottle normalisation (a 6-bottle lot at £3,000 hammer shown as £500/btl)
is permitted in the health check only, computed at read time in
`app/auction/evidence.py`, and there is no column anywhere to persist it —
`test_per_bottle_figure_is_not_persisted_or_exported` checks the actual row
shape, not just intent.

## The two Python guards, backed by the database

Same discipline as every gated write built this session (VESSEL's
single-source HK reference, its AGENCY/PRINCIPAL split): a clear Python
exception first, a structural constraint behind it.

- **The house must be on the closed list.** `record_auction_evidence()`
  raises `InvalidAuctionEvidence` naming this decision; the database's own
  `auction_evidence_house_known` CHECK is the backstop for any path that
  skips it (`test_house_not_in_allowed_list_is_refused` proves both).
- **An inclusive price needs a premium rate.** A 25% premium read as
  hammer is a 25% error. Refused in Python
  (`derive_hammer_gbp`/`InvalidAuctionEvidence`) and by
  `auction_evidence_inclusive_needs_rate`.
- **A missing FX rate is not refused — the figure is simply absent.** "No
  FX source for the date → store nothing converted, show 'FX unavailable',
  never estimate" (spec, verbatim). `hammer_gbp` stays `NULL`; the lot is
  still recorded and still counts toward `lot_count`, it just cannot
  contribute to the median.
- **Rows are immutable except for retraction.** A new trigger,
  `auction_evidence_forbid_mutation`, refuses any `UPDATE` once
  `retracted_at` is set, and refuses a change to any fact column even
  before that — the only legal `UPDATE` is setting the three retraction
  columns together, once. A mistake is retracted, with a reason, and
  re-entered.

## The health check

`app/auction/evidence.auction_health()` is pure — given already-filtered
lots and the line's current UK Reference per bottle, it returns a lot
count, a median per-bottle hammer in GBP, a date range, the source URLs,
and `AUCTION_BELOW_REFERENCE` when the median sits more than 10% below the
Reference. That flag is informational only — deliberately not added to
`app.core.flags.REVIEW_FLAGS`, the single definition of what forces
review, matching that module's own stated rule that commercial/
informational flags never go in it. If the line has no UK Reference, the
note says plainly "No UK market. Auction evidence is not a price,"
whether there are lots to show as context or not.

`app/auction/repo.line_auction_health()` reads the window (`sale_date`
within 24 months) from the seller line's own approved identity —
`wine_id`/`vintage`/`bottle_ml` — never re-typed into the form, so hand
entry cannot attach evidence to the wrong wine by a paste error.

## What was built

- Migration `0019_auction_evidence`; `schema.sql` updated to match,
  verified byte-equivalent by catalog diff.
- `app/auction/evidence.py` (pure): `derive_hammer_gbp`,
  `per_bottle_hammer_gbp`, `auction_health`, `ALLOWED_HOUSES`,
  `InvalidAuctionEvidence`.
- `app/auction/repo.py`: `record_auction_evidence`, `retract_auction_evidence`,
  `evidence_for_wine`, `line_auction_health`.
- `app/api/main.py`: `POST`/`GET /lines/{line_id}/auction-evidence`,
  `POST /auction-evidence/{id}/retract`, `GET /lines/{line_id}/auction-health`.
- `app/api/schemas.py`: `AuctionEvidenceIn`/`Out`, `AuctionRetractIn`,
  `AuctionHealthOut`.
- `web/app/deals/[dealId]/line.jsx`: an "Auction evidence" section on every
  line — the health summary, the entered lots with retract, and the
  hand-entry form (house, sale date, lot ref, source URL, lot size, amount
  + currency + basis, premium % when inclusive, FX rate/source when
  non-GBP, mixed lot, condition noted + note), opened the same way the
  spec asks: from a line, reached via the review queue's existing link
  into the deal page.
- Tests: `tests/test_auction.py` — 10 offline (pure derivation, the health
  check, the static AST import check) and 8 against Postgres (the two
  CHECK backstops, mixed-lot quarantine, the export shape, retraction,
  the closed-list refusal, Heritage/Zachys proven allowed by hand-entry
  only, and the line-level health read). 337 offline (was 327), 485 with
  Postgres (was 467).

## What this is not

No scraper, browser extension, bookmarklet or bulk import for any of the
four houses — the spec's own "out of scope" section, unchanged. No licensed
feed integration (Wine Market Journal, Wine-Searcher, Liv-ex) — a separate
decision if Doug wants one. No change to `REVIEW_FLAGS`, to the benchmark,
or to anything a client document prints from. No automated collection from
Heritage specifically, whose terms prohibit it outright and separately
from the personal-use restriction this decision overrides.
