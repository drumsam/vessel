# 0037 — human error messages everywhere, and one route to a buyer

**Status:** accepted, 21 October 2026. Doug, using the legacy buyer-offer
form on the pipeline page: `line b76ec9c8-672d-4fdf-a11c-cd2a9a0053e0 is
priced REVIEW and has not been acknowledged`. "That message is
unacceptable and it is the third time."

## The gap, part one: the engine's own vocabulary on a screen

`_offer_line` (`app/db/repo.py`) refused an unaccepted line with a string
built straight from `line_id` and `gate_reasons()` — a UUID and a flag or
state constant, concatenated. The API was behaving correctly; it was
explaining itself in a vocabulary no seller, buyer, or even the operator
reading it fast should ever have to parse. The same shape of leak turned
up everywhere else a repo function built its own error string from an id
or an enum value: VESSEL's mandates, listings and reservations; the LWIN
conflict resolution; auction evidence retraction; a benchmark comp
reinstatement; a worker job that stringifies straight into an RQ
traceback the frontend already unwraps and displays
(`web/app/deals/[dealId]/lines/page.jsx`'s `waitFor`). One fix would have
been the third instance of the same class of bug patched, not the class
itself fixed — Doug's own diagnosis, and the reason this decision audits
every error string the API can return to a screen in one pass rather
than the one he happened to hit.

## The fix, part one

> Every error a human sees must name the wine and the action. Never a
> UUID, never a state name, never a flag constant, anywhere a human can
> see it.

`app/db/repo.py` gains `gate_reason_phrase(pricing)`: one English clause
built from the real flags behind `requires_acknowledgement` — ONE_COMP
and WIDE_SPREAD-at-`comp_count==2` read the comp count directly ("rests
on one merchant", "rests on two merchants far enough apart to need a
look"), the rest come from two small phrase tables
(`_REVIEW_REASON_PHRASES`, `_EXPORT_GATE_PHRASES`) — never a flag
constant lowercased with underscores swapped for spaces, which is still
the constant, just quieter. `_wine_display_name(line, wine)` is the one
name every error about a line now uses to refer to it: producer, cuvée,
vintage where identity is approved, the seller's own raw wording
otherwise — never a line_id, never a wine_id.

`_offer_line` raises a new `LineNotReady(f"{name} {gate_reason_phrase(
pricing)}")` instead of a bare `Conflict`, and `create_buyer_offer`
collects every `LineNotReady` across a submission rather than stopping
at the first — "plural form when several" — before raising one combined
message (`_not_accepted_message`): Doug's own exact sentence at one line,
`"; "`-joined names and reasons with "none of these have been accepted"
at more than one. An unpriced line, a currency mismatch, and a line
outside the deal still fail fast and by themselves — those are different
failure classes, not the one Doug named, and batching them too would
have been scope he did not ask for.

The same discipline reaches every other raise site a screen can see:
VESSEL's `mandate_id`/`listing_id`/`reservation_id` interpolations are
gone, replaced either by a plain description needing no id at all ("this
listing could not be found") or by two small label tables
(`SETTLEMENT_MODE_LABELS`, `LISTING_STATE_LABELS` — the same pattern
`app/vessel/engine.py`'s own `MARKET_LABELS` already set) wherever a
state or a settlement mode has to be named. The LWIN conflict's "already
resolved as {resolution}" names "one wine under two names" or "two
different wines" instead of the raw `same_wine`/`different_wines` code.
Auction evidence retraction and a benchmark comp reinstatement no longer
quote the id of the row that already moved out from under the click.
Two worker-job `LookupError`s that stringify straight into an RQ
traceback the frontend already surfaces verbatim lose their `deal_id`/
`wine_id` too.

`web/lib/pricingReasons.js` is the one place the SAME logic lives in
this app's own JS — extracted from the Cellar Desk's "needs you" badge
(`reasonFor`, built 19 October 2026) so `web/app/deals/[dealId]/lines/
line.jsx`'s own "this price needs accepting" notice reads from it too,
rather than a second, incomplete flag-to-text mapping of its own
(`.replaceAll("_", " ").toLowerCase()` on exactly two hardcoded flags,
missing the third one decision 0033 added, and producing an empty
sentence whenever neither applied at all). Python and JS do not share
code across that boundary; they now say the same thing about the same
flags because the same discipline was applied to both, not because one
calls the other.

## The gap, part two: a second route to a buyer, with no gate in it

`issue.jsx` — Client, Terms, a checkbox per line, an Issue button — is
how Doug found this message at all. It predates the Cellar Desk, the
real offer document (decision 0034) and the shareable link (decision
0035), and it has no acceptance step: its own "needs sign-off first" tag
was informational, not a disabled button, so a gated line could be
ticked and issued anyway, straight into `_offer_line`'s refusal. "Doug
found it and reasonably assumed it was the way to send an offer" —
correctly; it was A way, just the one with the hole in it.

## The fix, part two

> There should be exactly ONE route from a cellar to a buyer, and it
> should be the one with the gate in it.

`issue.jsx` is deleted. The pipeline page's own "Buyer offers" section is
now a sentence and a link: *"There is exactly one route from here to a
buyer, and it isn't this page — it's the Cellar Desk, which chooses the
lines, gates on acceptance, and generates the client document and the
shareable link."* The read-only history of already-issued offers stays
exactly where it was — Doug's own instruction: leave the API and the
records alone, remove only the UI that could create one without a gate.
`POST /deals/{deal_id}/buyer-offers` is untouched and still callable; it
simply has no button anywhere that calls it any more.

The rest of the pipeline page (`web/app/deals/[dealId]/lines/`) was
re-read end to end looking for anything else that looks like a way to
send wine to a client. `line.jsx` has identity approval, price
acceptance (the gate itself — the Desk calls the exact same endpoint),
comp reinstatement and auction evidence entry: none of them issue
anything to a buyer. Nothing else moved.

## What this is not

Not a reopening of decision 0010's own claim logic, or of the
`buyer_offer`/`buyer_offer_line` schema — both untouched, both still
exactly what they were. Not a retreat from invariant 12: every gate
still gates exactly as before; only the words describing WHY changed.

Not a claim that `app/vessel/engine.py`'s own band/discount validation
messages (`CannotList`) needed this pass — they already named plain
values an operator chose from a dropdown (a band, a currency), never an
id or an enum code, and are untouched.

## Consequences

- `app/db/repo.py`: `gate_reason_phrase`, `_wine_display_name`,
  `LineNotReady`, `_not_accepted_message` (new); `_offer_line` and
  `create_buyer_offer` rewritten to use them; `gate_reasons` removed
  (its one caller is gone); five other raw-id Conflict/LookupError
  messages fixed in the same file.
- `app/vessel/repo.py`: `SETTLEMENT_MODE_LABELS`, `LISTING_STATE_LABELS`
  (new); nine raw-id or raw-state messages fixed across
  `commission_invoice`, `reserve_listing`, `submit_proof_of_payment`,
  `cancel_reservation`, `confirm_seller_receipt`, `record_payment`,
  `approve_mandate`.
- `app/api/main.py`, `app/api/vessel.py`: two remaining raw-value
  messages fixed (an LWIN resolution code, a listing state in caps).
- `app/auction/repo.py`, `app/worker/jobs.py`: four raw-id messages
  fixed.
- `web/lib/pricingReasons.js` (new): `gapPercent`, `gated`, `reasonFor`
  and its two phrase tables, extracted from
  `web/app/deals/[dealId]/page.jsx` so `line.jsx` reads the same
  function instead of its own incomplete one.
- `web/app/deals/[dealId]/lines/issue.jsx` deleted;
  `web/app/deals/[dealId]/lines/page.jsx` loses the `priced` variable it
  only existed to feed, and gains the one-sentence link to the Desk.
- `web/e2e/smoke.spec.mjs`: updated for both changes at once — the deal
  now lands on the Cellar Desk, not the pipeline page, so the test
  navigates there explicitly; `issueOffer()` drives
  `POST /deals/{id}/buyer-offers` directly (the one route left to reach
  it, now that there is no button), and a new assertion confirms the
  refusal names the wine and never a UUID or `NO_MARKET`. Not run in
  this session — it needs the full docker-compose/worker stack, which
  this machine does not have; reviewed for correctness against the
  current app shape, not executed.
- Tests: `tests/test_service.py` gains
  `test_gate_reason_phrase_never_leaks_a_flag_constant_or_a_bare_state_name`,
  `test_not_accepted_message_is_singular_at_one_line_and_plural_at_several`
  (both offline, pure functions) and
  `test_an_unaccepted_one_merchant_line_names_the_wine_never_a_uuid_or_a_flag`
  (Postgres); three existing tests that asserted the OLD leaking
  behaviour (`NEGATIVE_GP`/a raw state name/another wine's UUID in the
  response body) are corrected to assert the new human text and the
  absence of the old leak. Full suite: 472 passed offline (was 470; 173
  skipped), 645 passed against Postgres (was 642).
