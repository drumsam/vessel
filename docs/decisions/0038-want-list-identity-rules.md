# 0038 — the client want list: identity rules and a listing-side gate

**Status:** accepted, 24 October 2026. Builds
`docs/research/want-list-producer-rules.md` (the spec) verbatim, with the
reasoning in `docs/research/burgundy-target-producers.md`. Doug named this
"decision 0036" when he asked for it; that number was already taken in
this repo (the WhatsApp message templates, commit `a41c889`), and 0037
too (the human-error-messages decision, commit `4b7adb4`) — flagged
rather than silently renumbered into a collision, per the project's own
house style.

## The ask

Doug's biggest clients have a standing want list of ten Burgundy
producers, and he needs to evaluate inbound supplier offers fast. Six of
the ten names are ambiguous in a way worth 5–20×, which makes identity
rules load-bearing before any price is attached: paying Domaine Leroy
money for Maison Leroy wine, or declining a real Coche-Dury because the
offer just said "Coche", are both the same class of mistake the rest of
this system was never asked to prevent — the existing resolver matches
an already-split producer/cuvée against the canonical table; nothing in
this codebase judges a raw, unsplit blob of supplier text at all.

## The spec existed only once this session read it from the repo

Twice before this, a spec existed only in Doug's own chat message or
head and never in `docs/`: `hk-vs-uk-market-reference.md` on 7 October
(decision 0021 was built from figures quoted in a message, because the
document was never written down), and this exact want-list rule set,
first asked for with no file behind it at all. Both files now exist —
`want-list-producer-rules.md` and `burgundy-target-producers.md`,
committed by Doug directly (`61479b0`) once asked — and this decision is
built from them, not reconstructed from the fragments in his message.
"Twice is a pattern... assume a spec you cannot read does not exist, and
say so" is the rule going forward.

## The matcher: `app/identity/want_list.py`

Ten `WantListRule`s, each a `requires` predicate over normalised tokens
and an `excludes` list — "same form as the existing structural
exclusions" the spec itself asks for, though the resolver's own
`STRUCTURAL_EXCLUSIONS`/`PRODUCER_EXCLUSIONS` turned out to be exact
wine_key *pairs*, not a token DSL; no such raw-text matcher existed to
reuse, so this is new. `match_want_list(raw_text)` is a SUGGESTION only —
it never sets a `wine_id` and never bypasses the existing rule that a
seller line's identity is always approved by a named operator by hand.
Three rules the spec itself calls out for care:

- **Domaine Leroy**: `requires leroy`, `excludes maison, negociant,
  auvenay`, and `always_review = True` — unconditionally, even on a clean
  match. A bare "Leroy" must never auto-resolve: Maison Leroy is a
  legitimate, different market at a fraction of the price, the single
  most expensive confusion in Burgundy per the spec's own reasoning.
- **Domaine des Comtes Lafon**: `requires lafon AND (comte OR comtes)`,
  `excludes heritiers, macon, dominique` — "comte" alone is not
  sufficient; Héritiers du Comte Lafon is the family's own Mâcon estate,
  and the exclusion is required, not optional. (The spec's own worked
  example writes "Comtes Lafon"; the plural needed its own disjunct, not
  named explicitly in the spec text but required to match the spec's own
  example — caught by the test suite, not assumed.)
- **Pierre-Yves Colin-Morey**: `requires (pierre AND yves) OR
  colin-morey (adjacent) OR pycm`, explicitly NOT a bare "morey" token —
  Morey-St-Denis is an appellation, and punctuation-stripping during
  normalisation brings "colin" and "morey" adjacent even across a comma
  ("Marc Colin, Morey-St-Denis"), which is exactly why the full
  Colin-sibling exclusion list (`marc, philippe, bruno, joseph, simon,
  deleger`) is required rather than optional, not a belt-and-suspenders
  extra.

DRC's own rule encodes the spec's sharpest point about identity, not
price: `requires` an adjacent "romanee conti" pair or the "drc" shorthand,
`excludes liger` (Comte Liger-Belair's own, separate La Romanée
monopole) — and a cuvée name never implies DRC at all, by construction:
this module only ever answers "which producer," and Richebourg,
Romanée-St-Vivant, Échézeaux, Corton and Montrachet are all made by
others too. Only Romanée-Conti and La Tâche are monopoles. Armand
Rousseau's own note is the same shape one level down: a correct producer
match still says nothing about which of its five very different cuvée
tiers (Chambertin/Clos de Bèze down to village) is meant — this module
answers producer only, cuvée identification stays the resolver's job.

Three of the ten (Leflaive, d'Auvenay, Leroy) are confirmed explicitly by
Doug — never the négociant in any of the three. The other seven are the
spec's own "top-tier reading," marked for Doug to correct if wrong; this
decision does not treat that distinction specially in code, because the
cost of a false match is the same whichever list a producer came from.

## The policy: `want_list`, and a gate `app/core/` never sees

> Every line matching a want-list producer should require an operator
> acknowledgement once, even when identity resolves cleanly and even
> when two merchants agree.

`wine.want_list boolean` (migration `0029_want_list`) is set once, at
`create_wine` time, from the producer field ALONE —
`app.identity.want_list.is_want_list_producer`, an exact normalised
match against the ten canonical strings, never the fuzzy raw-text
matcher a supplier's own wording needs. `seller_line.want_list_ack_by`/
`_at` are new, paired columns on the LINE itself, not on
`pricing_result`: "once... even when two merchants agree" means this
fact must survive a reprice, and `pricing_acknowledgement` is keyed to a
`pricing_id` that changes every time the price does. A new endpoint,
`POST /lines/{id}/want-list/acknowledge`
(`app.db.repo.acknowledge_want_list`), sets both columns; re-acknowledging
is harmless and just updates who and when.

Not a new flag in `app/core/flags.py`, not folded into
`requires_acknowledgement`'s own GENERATED expression — Doug's own words,
"a listing-side requirement, the same way decision 0025's invite gate
sits outside the engine." The check lives where decision 0037 already
put the equivalent pricing check: `_offer_line` (the legacy
`create_buyer_offer` path) and `offerlink.create_link` (decision 0035's
shareable link — the actual one route to a buyer now) both refuse a
want-list line with no acknowledgement, independently of whatever the
pricing flags say, using the exact same `LineNotReady`/batched-message
machinery decision 0037 built: *"Domaine Leroy Chambertin 2015 is on the
client want list and needs a one-time identity check"* — the wine named,
never a flag, never a UUID.

Surfaced on `LineOut.want_list`/`want_list_acknowledged_by`/`_at`, read
by the SAME `web/lib/pricingReasons.js` decision 0037 extracted — the
Cellar Desk's "needs you" badge, its gate box's new "Confirm this
identity" button, and the pipeline line detail's own notice box all read
`wantListGated(line)` rather than re-deriving it, so a want-list-only
line (fully READY on pricing, two merchants agreeing) correctly shows
"want list" rather than nothing, and correctly never shows the pricing
gate's own "Accept this price" button — a button that would have failed,
since pricing itself has nothing to accept.

## A bug this found, in decision 0037's own work

Auditing `offerlink.repo.create_link` for where to add the want-list
check surfaced the exact leak decision 0037 was supposed to close,
missed in that pass: `f"line {line_id} has not been priced"` and
`f"line {line_id} is still REVIEW and has not been accepted"`, both raw
UUIDs, both passed through to the public-facing endpoint unchanged.
Fixed in the same edit, using the same `wine_display_name`/
`gate_reason_phrase` helpers `_offer_line` already uses — renamed from
`_wine_display_name` to drop the leading underscore, since it is now
called across the `app.db`/`app.offerlink` module boundary.

## What this is not

Not the coverage test Doug's first message asked for — explicitly
superseded in his own follow-up: these wines arrive in ones and twos,
Doug prices them manually from his own Wine-Searcher account, and no new
adapters or Wine Market Journal integration are being built for this
list. The coverage test is optional, informational, idle-time-only.

Not a change to cuvée identification, which stays the resolver's own job
— this module only ever answers "which producer," never "which wine."

Not an auto-resolve path of any kind: `match_want_list`'s own callers
(the single-line evaluation screen, decision 0039) show it as a
suggestion; a seller line's identity is still always approved by a named
operator, exactly as every other seller line in this codebase already
required before this decision existed.

## Consequences

- `app/identity/want_list.py` (new): ten `WantListRule`s,
  `match_want_list`, `is_want_list_producer`, `WANT_LIST_PRODUCER_KEYS`.
- `app/db/schema.sql` + migration `0029_want_list`: `wine.want_list`;
  `seller_line.want_list_ack_by`/`_at`, paired.
- `app/db/repo.py`: `create_wine` sets `want_list`; new
  `acknowledge_want_list`; `wine_display_name` made public (renamed from
  `_wine_display_name`); `_offer_line` gains the want-list check.
- `app/offerlink/repo.py`: `create_link` gains the want-list check, and
  its own pre-existing raw-id leak is fixed in the same pass.
- `app/api/main.py`: `POST /lines/{id}/want-list/acknowledge`;
  `_line_out` surfaces `want_list`/`want_list_acknowledged_by`/`_at`.
- `app/api/schemas.py`: `WineOut.want_list`; `LineOut` gains the three
  new fields.
- `web/lib/pricingReasons.js`: `wantListGated`; `gated`/`reasonFor`
  extended to fold it in.
- `web/app/deals/[dealId]/page.jsx`: the Desk's gate box shows the right
  action (pricing accept, want-list confirm, or both) instead of always
  showing "Accept this price"; the wide-spread commentary no longer
  assumes a two-comp gated line is gated BY the spread, which is no
  longer always true; the footer's warning no longer claims every
  blocked line "rests on one merchant."
- `web/app/deals/[dealId]/lines/line.jsx`: a want-list notice box and
  "Confirm this identity" button, independent of the pricing section.
- Tests: `tests/test_want_list.py` (new) — 21 offline (every rule, the
  three named traps, `is_want_list_producer`), 6 against Postgres (the
  flag set at creation, the ack tied to the line surviving a reprice, the
  export gate on both routes, the human message). `web/test/
  pricingReasons.test.mjs` gains 3 tests for the new gate.
  `tests/test_service.py`'s own generic `_deal()` fixture defaults to
  "Domaine Armand Rousseau" — itself one of the ten — and now
  auto-acknowledges the want list so the ~10 unrelated existing tests
  that use it are undisturbed; two call sites that build their own
  identity approval directly do the same. Full suite: 493 passed offline
  (was 472; 179 skipped), 672 passed against Postgres (was 645).
- Verified live via `desk.sh` + Playwright against a real Domaine Leroy
  line, two agreeing merchants, fully priced and READY: the Desk badge
  reads "want list", the client-offer link is disabled, the gate box's
  "Confirm this identity" button clears it, and the pipeline line detail
  shows who confirmed it and when.
