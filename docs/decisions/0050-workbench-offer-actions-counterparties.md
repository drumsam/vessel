# 0050 — Workbench, offer actions, supplier and client registers

**Status:** accepted, 1 November 2026, on Doug's brief. No pricing rule
changes; `app/core/` and `app/pricing/` are untouched.

## Workbench

`/` is now the operator Workbench, reached from the `VESSEL` brand on every
operator page. Navigation is `VESSEL | Pocket | Trades | Suppliers | Clients`.
Sections: NEW OFFER, TO REVIEW, READY TO PRICE, OFFERS OUT, CONFIRMED, RECENT
ACTIVITY (`GET /workbench`).

The Workbench is the operating engine, not an exceptions console (Doug,
1 November 2026). The flow is INCOMING → IDENTITY → PRICE → OFFER → CONFIRMED
→ OPS → COMPLETE, and the page answers five questions only: what needs my
attention, what is ready for me, what is out with clients, what is confirmed,
what happened recently. "Exception", "Not searched" and the like are internal
states, seen only when drilling into a record.

- Every row's next step is a human action, shown as the one blue link on
  the row: Review identity · Read again · Complete details (no supplier
  price) · Check market (never evaluated) · Set price · Await client ·
  Arrange ops. Cellar lists: Review identity · Check market · Review prices
  · Make an offer.
- Recent activity is one line per offer — the last thing that happened to it.
- Each offer shows a title (the wine once confirmed, otherwise the first line
  of the message, at most 60 characters) — never the raw message. The message
  is one click deeper ("Message as received" in Pocket).
- Status and next action are **derived on read** from what the offer already
  records (`app/api/workbench.py::_status`), never stored — the same rule as
  line status (invariant 11).
- Cellar lines to review, LWIN conflicts and alias suggestions appear under
  TO REVIEW only when their count is above zero, worded as actions ("Review
  3 cellar lines"), each linking to the review page (`/queue`, no longer in
  the nav). There is no merchant-approval screen yet, so new unapproved
  merchants are not listed — a "Review merchant" item would lead nowhere.

## Trades

`/trades` (`GET /trades`) lists every live Pocket offer once and every cellar
list, as cards — WHAT | WHO | STATUS | NEXT ACTION — that stack on a phone, so
nothing scrolls sideways. The per-offer deal a Pocket offer keeps behind it is
not a cellar and is no longer listed (the "Pocket …" noise). Cellar upload
moved here.

## Offer actions

A three-dot menu on every offer row (Workbench, Trades, Pocket, a
counterparty's page):

- unconfirmed: **Edit · Share again · Duplicate · Delete**
- confirmed: **View · Share again · Duplicate**

**Delete** is a soft delete (`inbound_offer.discarded_at`/`discarded_by`,
`POST /inbound-offers/{id}/discard`) after a confirmation prompt. It hides the
offer everywhere and destroys nothing: raw message, wine, supplier, pricing
history and anything already shared stay. A confirmed trade can never be
deleted (409, and the menu does not offer it). A deleted offer refuses
identity, pricing and confirmation.

**Edit** reopens the existing workflow (`/pocket?open=<id>`): an offer with a
confirmed identity opens on its pricing screen, with "Edit details" reopening
the confirm form prefilled from its own confirmed facts. Re-confirming changes
the details; pricing then insists the market is checked again (existing rule).
The raw message is never edited. A confirmed trade stays frozen — the
fulfilment trigger and the API both refuse.

**Share again** opens the existing offer and its existing tombstone; nothing
new is created or priced.

**Duplicate** (`POST /inbound-offers/{id}/duplicate`) creates a new draft from
the same message, supplier and availability (`duplicated_from` records the
source). Its identity is not copied as confirmed: the form is prefilled from
the source, and the operator confirms afresh — the want-list gate included.

## Found in the browser check: duplicate Pocket deals

Two EVALUATEs at once (React's dev double effect; equally a double tap in
production) each read `deal_id` NULL and each created a deal, leaving an
orphan that listed as a cellar called "Pocket …" — the noise this phase was
asked to remove. `ensure_evaluation_line` now locks the offer row first, and a
Pocket deal is recognised by its line's `raw_row.inbound_offer_id` marker as
well as by the offer's `deal_id`, so orphans already in production stay out
of Trades and out of the Workbench's cellar count.

## Supplier and client registers

Commercial memory, not a CRM. Searchable lists and a detail page each
(`/suppliers`, `/clients`), with aliases and the trades they appear on.

- Supplier gains `default_currency`, `usual_stock_location`,
  `usual_bond_status`, `payment_terms`.
- New `client` (name unique, contact, email, phone, default currency, delivery
  notes, payment terms, notes, active) and `client_alias`.
- `fulfilment.client_id`: CONFIRM picks a client from chips (most recently
  traded first) or adds one inline from a name and phone. The frozen
  fulfilment still carries `buyer_name`, copied from the client's name at
  confirmation, so the record never changes when a client is renamed.
- Defaults are memory only: nothing here fills in or changes a trade's facts.

Migration `0040_counterparties`.

## Not built

Invoices, logistics, payments, admin documents, accounting, automated
searches, and Client Wants. Registered in `docs/backlog.md` with the rest of
the agreed later work.
