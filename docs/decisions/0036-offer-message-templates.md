# 0036 — the real WhatsApp message templates, and `deal.city`

**Status:** accepted, 21 October 2026. Follows directly from decision
0035's own placeholder: "the default message text below is a factual
placeholder, not Doug's own wording — he drafted three messages
separately." He then did.

## The templates

Three, not two: decision 0035 built one message per link `kind` (buyer,
seller). Doug's own drafts split the buyer message again, by audience —
a buyer messaged alone reads differently from a buyer group, which gets
no per-bottle price and no top lines at all, only the wine names and the
link. `web/lib/offerMessages.js` holds all three, verbatim structure,
tokens substituted:

- **Buyer, to one person** — names up to three lines by offer price,
  highest first, per bottle (never a line total), then the link, the
  "check me in thirty seconds" line, an optional blended saving sentence,
  and the validity window.
- **Buyer, to a group** — every wine named, no price anywhere, the link,
  a sentence about the evidence being on every line, and a call to reply.
- **Seller** — bottle count, net, the blended commission rate, the link,
  an optional sentence naming how many OTHER lines are being held back
  for being single-sourced, and a sign-off.

## The rules, enforced in code, not the copy

Doug's own instruction. Each is a property of the CODE, checked here,
not a hope about the words:

- A buyer message never reads `seller_price_gbp`, `commission_gbp`, cost
  or margin — `buyerIndividualMessage`/`buyerGroupMessage` have no branch
  that touches those fields, so there is nothing to leak by construction.
  `assertBuyerSafe()` is a second, independent check: a regex scan for
  "seller net", "commission", "cost", "margin" run on the FINISHED
  string before it is ever shown, so a future edit that accidentally
  introduces one of those words fails loudly instead of shipping quietly.
- No percentage claim prints where decision 0034 would have suppressed
  it. `savingSentence()` omits itself entirely — not "0%", not a
  rounding-away of a small number — whenever ANY selected line's own
  `floor_saving_claim` is null, or the figure for the WHOLE blended drop
  (computed from the real totals, never averaged from individual
  percentages) falls under the same `MIN_CLAIM_THRESHOLD` that would
  suppress one line. The buyer-group template never had a percentage
  token to begin with.
- A message over roughly 600 characters (these go to WhatsApp, not an
  inbox) drops from three top lines to two, automatically, before it is
  ever shown.

## `deal.city`

Every template references `{city}` as if it were already a fact on the
deal. It never was — `deal` had `name` and `seller`, nothing describing
where the cellar sits. Decision 0036 adds `deal.city`, nullable free
text, entered once by the operator at deal creation
(`DealIn.city`/`DealOut.city`, migration `0028_deal_city`). A deal that
predates the column, or where the operator left it blank, reads null —
every caller treats that as "omit the mention" ("a cellar" rather than
"a {blank} cellar"), never as something to guess. Both seed scripts
(`scripts/seed_cellar_desk_demo.py`, `scripts/seed_cellar_desk_real.py`)
now set it to "Hong Kong", matching what this cellar already is
everywhere else in this file.

## What this is not

Not a reopening of decision 0035's own safety design — the structural
absence of seller/commission fields from a buyer-kind public payload is
unchanged; this decision only supplies the real wording and a second,
independent guard on top of it.

Not a general "deal metadata" feature. `city` was added because three
message templates named it as an existing fact; nothing else on `deal`
changed, and no UI to edit it after creation was built — if that is
needed, it is a separate, later decision.

## Consequences

- `app/db/schema.sql` + migration `0028_deal_city`: `deal.city`, nullable.
- `app/db/repo.py::create_deal` writes it; `app/api/schemas.py`'s
  `DealIn`/`DealOut` carry it.
- `scripts/seed_cellar_desk_demo.py`, `scripts/seed_cellar_desk_real.py`:
  seed `city = "Hong Kong"`.
- `web/lib/offerMessages.js` (new): `wineName`, `topLines`, `wineNames`,
  `savingSentence`, `heldSentence`, `sellerTotals`, `assertBuyerSafe`,
  `buyerIndividualMessage`, `buyerGroupMessage`, `sellerMessage`.
- `web/app/deals/[dealId]/offer/page.jsx`: `ShareComposer` gains a
  buyer-only "to one person" / "to a group" toggle alongside the
  existing buyer/seller kind toggle, and calls the new builders instead
  of its own inline placeholder text.
- Tests: `web/test/offerMessages.test.mjs` (new, 13 tests) — NV vintage
  omission, per-bottle sort order, the suppression rule at both the
  per-line and blended level, the held-line count, the commission
  percentage from real totals, `assertBuyerSafe` actually throwing, and
  the 600-character drop to two lines. `npm test`: 18 passed (was 5).
  Full suite: 470 passed offline (172 skipped), 642 passed against
  Postgres — unchanged in count from decision 0035, confirming the new
  column broke nothing already covered.
- Verified live against the real 30-line Champagne sweep via `desk.sh`
  (fresh rebuild, migrations `0027`/`0028` applied from a clean
  database): all three templates render with real figures, the saving
  sentence correctly omits itself on this drop (two of the seven ready
  lines have a suppressed claim), and the seller message correctly
  counts the 19 other one-merchant lines held back.
