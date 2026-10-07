# 0022 — VESSEL settles as agency: the buyer pays the seller, VESSEL invoices

**Status:** accepted, 7 October 2026. Narrows decision 0020 — does not
replace it. Doug has decided VESSEL is a side business (two to three
cellars a year, worked over a few weekends), not a company to grow; the
five-year growth model and the referral/club mechanics docs added alongside
it are parked, not pursued, and nothing in this codebase was built against
them (checked: no referral, invitation, waitlist, membership-cap or buyer-
ranking code exists anywhere in `app/` or `web/`).

## The one structural change that matters

At this scale Doug invoices a commission rather than holding buyer funds:
the buyer pays the seller directly, in full, and VESSEL bills 8% on
completed sales afterward. This removes the client-money and
two-jurisdiction compliance problem entirely — the only thing that could
have stopped VESSEL launching at all — by making VESSEL never a custodian
of anyone's money.

`settlement_mode` ('AGENCY' default, or 'PRINCIPAL') is a term of the
**mandate**, not of a listing or a line: a mandate answers "on what terms am
I selling your wine", and how the buyer's money reaches the seller is
exactly that kind of term. Every listing under one mandate settles the same
way, so this is one column on `vessel_mandate`, never duplicated per line
(migration `0018_vessel_agency_settlement`).

PRINCIPAL is the mode decision 0020 originally and implicitly assumed
(`record_payment` recording VESSEL as having received the buyer's funds,
before paying the seller `seller_net`). It is kept, structurally legal, and
**unused and untested until someone needs it** — no test in this codebase
exercises a PRINCIPAL mandate's money flow, only that the column accepts
the value and that `record_payment`'s own matching logic (reference,
amount, currency) still works when a mandate explicitly opts into it.

## Which "seller_offer" — resolved, not guessed

Doug's own first draft of this instruction said "add `settlement_mode` to
`seller_offer`", and then corrected himself once the ambiguity was raised:
`seller_offer`/`seller_offer_line` (`docs/research/offer-document-spec.md`)
is the **direct-purchase** business — VESSEL buys the cellar outright at
`buyer_discount`/`margin_on_sale` and resells, principal trading by
definition. Putting an agency/principal switch on that table would have
been incoherent: it is already principal, structurally, in its own pricing
chain. `settlement_mode` belongs on `vessel_mandate` instead — VESSEL's own
existing seller-facing commitment — and that is what this decision builds.

`docs/research/offer-document-spec.md` is marked **SUPERSEDED — PRINCIPAL
MODEL, NOT BUILT** at its own top, pointing here, so nobody builds
`seller_offer`/`seller_offer_line` later "for tidiness." They are not to be
built unless Doug asks for them by name — the direct-purchase business they
describe is not one he has decided to run.

## The structural guarantee, and why it is a trigger, not a CHECK

The instruction asked for enforcement "the same as you did for the
single-source HK reference" — that one was a same-table CHECK
(`vessel_listing_single_source_needs_band`), because `reference_market`,
`source_count` and `vintage_band_passed` all live on one row of
`vessel_listing`. "No code path should be able to reach a 'we hold the
money' state from an AGENCY mandate" is not a same-table invariant: it
spans `vessel_payment` (is this payment MATCHED to a reservation) ->
`vessel_reservation` (which listing) -> `vessel_listing` (which mandate) ->
`vessel_mandate` (its `settlement_mode`). Postgres CHECK constraints cannot
see across tables.

A trigger is this schema's own established answer to exactly that gap, used
three times already: `vessel_forbid_mandate_mutation`,
`vessel_forbid_price_change_once_approved`,
`vessel_forbid_reference_mutation`. `vessel_forbid_payment_match_for_agency`
is a fourth, not a new pattern: `BEFORE INSERT OR UPDATE` on
`vessel_payment`, joining through to the mandate, raising if
`matched_reservation_id` is being set and that mandate's `settlement_mode`
is `'AGENCY'`. It is safe against the lookup going stale because
`vessel_mandate` is itself immutable once written (decision 0020's own
trigger) — a mandate's `settlement_mode` can never change after the row is
created.

`app/vessel/repo.record_payment()` also refuses in Python first
(`AgencyMandate`, with a message naming the right function to call
instead) — not because the trigger is insufficient, but because a 409 with
a clear reason beats a raw database exception surfacing to an operator.
The trigger is the backstop for any path that reaches the `INSERT` some
other way, proven directly in
`test_database_forbids_a_payment_match_to_an_agency_reservation`, which
bypasses `record_payment` entirely.

## Who confirmed, and when — never a boolean

The AGENCY fulfilment path needed its own function, since `record_payment`
is specifically "VESSEL asserting it received funds" and that assertion
must be impossible here. `app/vessel/repo.confirm_seller_receipt()` is the
seller (via an operator who spoke to them — sellers have no account system,
same as the rest of VESSEL) confirming the buyer paid them directly:
`vessel_reservation.seller_confirmed_at`/`seller_confirmed_by` are set
together or not at all (`vessel_reservation_seller_confirmation_complete`
CHECK), never a flag with no trace of who said so. The reservation moves to
`FULFILLED` and the listing to `PAID`, exactly as `record_payment`'s
PRINCIPAL path does — the two are mutually exclusive by mandate, never by
listing or by line, and a mandate's own mode decides which function is
even reachable for every reservation under it.

## The commission invoice: per mandate, not per sale

"At two to three deals a year nobody wants an invoice per bottle." One
invoice per mandate (`app/vessel/repo.commission_invoice()`), listing every
line that reached a completed-sale state (`PAID`, `TRANSFERRING`,
`SETTLED`) with its `vessel_price`, `seller_net`, and the commission —
`vessel_price - seller_net`, read off the two figures already on the row
rather than independently recomputed as `vessel_price * 0.08`, so
commission and `seller_net` always sum to exactly `vessel_price` with no
second rounding path (invariant 7: exactly four places round, and this is
not a fifth). Grouped and totalled by currency, same discipline as the
existing `mandate_estimate()`: nothing is stored on the invoice, so it can
never disagree with the listings it was computed from. Refuses outright
for a PRINCIPAL mandate — there is nothing to invoice when VESSEL already
kept its fee before paying the seller.

No PDF or HTML rendering was built. `commission_invoice()` is the data a
document would be built from — the same kind of generator-shaped function
`offer-document-spec.md` describes for the (superseded, not-built) other
business — exposed as `GET /vessel/mandates/{mandate_id}/commission-invoice`
for an operator to read or hand to an accountant. Building an actual
rendered document remains the open, project-wide design question CLAUDE.md
already names; nothing here resolves it, and nothing here needed to.

## What this does not do

Per the scope decision, none of the following were built, and nothing
already working was removed to make room for not building them: referrals,
invitations, membership caps or waitlists, the Thursday drop cadence or any
scheduled release, buyer ranking from behaviour, "My Cellar", or a
background scheduler for reservation expiry. The reservation machinery,
the proof-of-payment cap, and the operator confirmation queue from decision
0020/0021 stand as built.

## Consequences

- Migration `0018_vessel_agency_settlement`: `vessel_mandate.settlement_mode`
  (`NOT NULL DEFAULT 'AGENCY'`, `CHECK IN ('AGENCY','PRINCIPAL')`);
  `vessel_reservation.seller_confirmed_at`/`seller_confirmed_by` with their
  pairing CHECK; the `vessel_forbid_payment_match_for_agency` trigger on
  `vessel_payment`. `schema.sql` updated to match, verified byte-equivalent
  by catalog diff.
- `app/vessel/engine.commission_due()` (pure): the exact complement of
  `seller_net`.
- `app/vessel/repo.py`: `approve_mandate()` takes `settlement_mode` (default
  AGENCY) and selects between two mandate texts — the AGENCY wording
  states the real mechanism ("the buyer pays you directly... VESSEL
  invoices you an 8% commission"), replacing language that assumed VESSEL
  paid the seller a net amount; the PRINCIPAL text is preserved verbatim
  from before this decision. New: `confirm_seller_receipt()`,
  `commission_invoice()`, `AgencyMandate`. `record_payment()` gained the
  Python-side guard.
- `app/api/vessel.py`/`vessel_schemas.py`: `ApproveMandateIn.settlement_mode`;
  new operator-only routes `POST /vessel/reservations/{id}/confirm-seller-receipt`
  and `GET /vessel/mandates/{id}/commission-invoice`; `record_payment`'s
  route now translates `AgencyMandate` to a 409.
- `web/app/vessel/approve/[dealId]/page.jsx`: the shown terms paragraph
  rewritten to describe agency settlement honestly — no settlement-mode
  selector was added, since PRINCIPAL has no live caller to choose it.
- `docs/research/offer-document-spec.md`: marked SUPERSEDED at the top,
  pointing here.
- Tests: 9 new in `tests/test_vessel.py` (1 offline, 8 against Postgres) —
  the AGENCY default, the full confirm-seller-receipt fulfilment path, the
  named-confirmer requirement, refusing a second confirmation, the Python
  guard and the database trigger both refusing a payment match under
  AGENCY (two separate tests, proving the backstop independently of the
  guard it backs up), the per-mandate commission invoice excluding a line
  not yet sold, and refusing an invoice for a PRINCIPAL mandate. Two
  pre-existing tests were re-scoped rather than broken by the new default:
  `test_unmatched_payment_does_not_confirm_a_sale` now creates its fixture
  under `settlement_mode="PRINCIPAL"` explicitly, since it is testing
  `record_payment`'s own reference/amount/currency matching logic, which
  is only reachable under that mode now; `test_sold_listing_stays_visible_in_drop`
  now reaches PAID via `confirm_seller_receipt`, the path a sale actually
  takes under the mode every real listing uses. 327 offline (up from 326),
  467 with Postgres (up from 458).

## The READY/REVIEW/NO_MARKET question, answered

Asked separately: whether `CLAUDE.md`'s stale Burgundy-proof counts hid a
real regression, specifically whether `READY` had dropped from a non-zero
number. Checked by walking the commit history in a disposable
`git worktree` and running `scripts/rerun_burgundy_proof.py` at each
commit: **`READY` is 0 in every commit checked, before and after decision
0018** — derivation never reduces ready lines, because a derived
comparable always carries `DERIVED_FROM_CASE` (a review flag, invariant 9),
never `READY`. The `REVIEW 5 -> REVIEW 15` / `NO_MARKET 15 -> NO_MARKET 5`
flip happened at commit `2ecb7a2` — **decision 0016** (Burgundy comps
across case sizes), a full session before decision 0018 existed; 0018
(derivation beyond Burgundy) left these 20 Burgundy lines' own counts
untouched, since Burgundy was already covered. Full detail and the
commit-by-commit table are in decision 0021, which this question was
originally raised against. `CLAUDE.md` already read correctly
(`REVIEW 15 NO_MARKET 5`) by the time this was checked; only the overall
`pytest` pass/skip counts were stale, and are corrected in this decision's
own commit.
