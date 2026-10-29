# Supplier attribution — spec

29 October 2026. Requested by Doug: *"If I upload or copy paste I need to tell
the system who it's from. That way if it sells I know who to go back to —
critical when I have 8-10 suppliers."*

**This is a prerequisite for step 6, not an enhancement.** The CONFIRM screen
in `build-brief-vessel-pocket.md` renders `Buyer: X · Seller: Y` and generates
a seller handoff message. **Y does not exist.** `inbound_offer` has no source
field, and there is no counterparty entity in the schema. So CONFIRM cannot be
completed as specified until this is built.

---

## What exists today, and why it is not enough

- `inbound_offer` — no source attribution of any kind.
- `deal.seller` — free text. Correct for a cellar mandate, where one seller is
  typed once by the operator. Wrong for recurring counterparties: "Vinum",
  "vinum wines", "Vinum Ltd" and "James at Vinum" become four suppliers, and
  "who do I go back to" returns a fuzzy answer.
- `member` — buyers. A different side of the trade with a different lifecycle
  (invite codes, login codes, drops). Do not overload it.
- `seller_introduction` — referral leads under a mandate. Not a trading
  counterparty.

---

## Schema

Two new tables and one column. Nothing existing changes.

```
supplier
  supplier_id    uuid PRIMARY KEY DEFAULT gen_random_uuid()
  name           text NOT NULL UNIQUE      -- canonical, as Doug types it once
  contact_name   text                      -- "James"
  phone          text                      -- the WhatsApp number, as received
  email          text
  notes          text
  active         boolean NOT NULL DEFAULT true
  created_by     uuid NOT NULL REFERENCES operator(operator_id)
  created_at     timestamptz NOT NULL DEFAULT now()

supplier_alias                             -- for deterministic matching
  supplier_id    uuid NOT NULL REFERENCES supplier(supplier_id)
  alias          text NOT NULL             -- normalised via norm()
  PRIMARY KEY (supplier_id, alias)
```

And on `inbound_offer`:

```
  supplier_id    uuid REFERENCES supplier(supplier_id)
```

**Nullable in the table, required by the API.** Capture must never be blocked —
the raw record is sacred and is written before anything else happens. But
`POST /inbound-offers/{id}/confirm-identity` must refuse without a
`supplier_id`, exactly as it already refuses without `want_list_ack`. Same
enforcement point, same shape, same reason: the cheap moment to capture this is
now, and it can never be recovered later.

### Naming, and why not `counterparty`

`supplier` names what it is. A supplier may one day also be a buyer, and
`member` may one day merge with this — but generalising before that is needed
is how an unused abstraction gets built. One asset, one side, one table.

---

## Where it goes in the flow — the CANDIDATE screen, not NEW

NEW stays three buttons. No supplier field there: the brief's rule is capture
first, structure afterwards, and adding a required pick to the fastest screen
breaks it.

Put the supplier pick on **CANDIDATE**, which is where the dead time already
is. The model call takes one to three seconds. Doug taps the supplier while it
runs, so the attribution costs **zero** added time.

**A chip row, not a dropdown.** With 8-10 suppliers, tappable chips ordered
most-recently-used first are one tap and fit a phone. A `+ new supplier` chip
opens a two-field inline form — name and phone — and nothing else; the rest of
the record can be filled in later or never.

---

## Deterministic pre-highlight. The model must not touch this.

A pasted WhatsApp message often names the sender: *"Hi Doug, James at Vinum
here"*. Match `raw_body` against `supplier_alias` using the existing `norm()`
from `identity/resolver.py` — the same normaliser the wine register uses, not a
reimplementation.

- A single alias match → highlight that chip. **Pre-select nothing.** Doug
  still taps, exactly as with the wine list.
- Two or more matches → highlight both, no ordering preference.
- No match → no highlight. He taps.

**The AI never proposes a supplier.** Not as a field, not in `reasoning`, not
as a hint. `InboundOfferProposal` must gain no supplier field — the dataclass's
own docstring rule applies: there is no field for it, by construction.

Two reasons. Counterparty identity is commercially sensitive in a way a cuvée
is not: a wrong supplier attribution sends a confirmation to the wrong trader
and leaks that a competitor's parcel is moving. And unlike a wine, there is no
register of all suppliers in the world to check an inference against — only
Doug knows.

When Doug adds a supplier, capture one or two aliases alongside the name, so
matching improves with use rather than requiring a backfill.

---

## The leak surface this creates

`assertBuyerSafe()` (decision 0036) forbids seller identity in any outbound
message. A supplier field is a **new way to leak it**, and the assertion does
not know about it yet.

- Add `supplier`, `supplier_id`, `contact_name` and `phone` to what
  `assertBuyerSafe()` refuses.
- Add them to the signed share-link payload exclusions (decision 0035).
- Add a test that a share link and a buyer message for an inbound-sourced deal
  contain no supplier field, by name or by value.

A buyer learning which supplier a parcel came from is a commercial injury to
Doug, not a privacy nicety. It is the same class of error as leaking cost.

---

## What attribution is worth beyond re-contact

Doug's stated reason is the first of three, and the other two are free once the
field exists.

**1. Re-contact on sale.** The stated need, and the one that blocks CONFIRM.

**2. Double-offering detection.** With 8-10 suppliers, two will eventually
offer the same parcel. Supplier plus wine, vintage and quantity makes that
visible. Without attribution it is invisible — and offering the same three
bottles to two buyers as though they were six is a reputational problem, not a
bookkeeping one. Worth a soft warning at CREATE OFFER: *"a line for this wine
and vintage is already open from another supplier."*

**3. Margin by supplier.** Once every inbound offer carries a supplier and
every confirmed trade carries a margin, *"which suppliers give me the best
entry prices"* is a query rather than a memory. That is the commercial
intelligence that makes this worth more than a notepad.

**It only ever works retrospectively if the data was captured from the start.**
Which is the argument for building it before the first real deal, not after.

---

## Not now

- Merging `supplier` with `member`.
- Migrating `deal.seller` to `supplier_id`. The existing free text stays,
  same discipline as `deal.city`: never backfilled, and a null means "omit the
  mention", not "a blank to fill in". Worth doing when a cellar mandate and a
  parcel trade need to share one counterparty list — not before.
- Supplier terms, payment details, credit limits, performance scoring.
- Any supplier-facing surface. Suppliers message Doug; they do not log in.

---

## Order of work

1. `supplier` + `supplier_alias` + `inbound_offer.supplier_id` (migration).
2. The API refusal at `confirm-identity`, mirroring `want_list_ack`.
3. The chip row on CANDIDATE, with `+ new supplier` inline.
4. Deterministic alias pre-highlight via `norm()`.
5. `assertBuyerSafe()` and share-link exclusions, with the test.
6. The double-offer warning at CREATE OFFER — after step 4 of the build brief,
   not before.
