# 0002 — Does market comparability require sufficient offered quantity?

**Status:** decided for now, deliberately revisitable. 19 September 2026.

## The question

The seller has 6 bottles. The only UK In Bond comp is one merchant offering one
bottle at £610.

- As a **market benchmark** — "what is this wine worth per bottle in the UK
  trade right now" — that comp is perfectly valid. Depth of stock is not part of
  the question.
- As an **executable replacement or liquidation value** for the whole parcel —
  "what could a buyer actually pay to replace these 6 bottles" — it is not.
  One bottle does not price six.

These are different questions and the same number cannot answer both.

## Decision

`REQUIRE_QUANTITY_COVER = False` in `app/core/flags.py`.

Offered quantity does **not** affect comparability. An offer of one bottle is a
valid comp for a six-bottle line.

Where no merchant-best covers the seller's quantity, the line carries the
informational flag `QUANTITY_SHORTFALL`. That flag is **not** in `REVIEW_FLAGS`:
it is shown to the operator as context, it does not gate the line.

## Why this way round

The product's stated purpose is a UK market benchmark used to set a discount, not
a liquidation bid. Gating on quantity would send most Burgundy lines to review
for a reason that is not actually a pricing error.

## When to revisit

Flip `REQUIRE_QUANTITY_COVER` to `True` if the business starts quoting firm bids
for whole parcels rather than per-bottle offers. The screen is already written
(`Reject.NO_QUANTITY`) and covered by tests; the flag is the only switch.

Do not solve this by quietly changing what `QUANTITY_SHORTFALL` does. If the
answer changes, change the decision record.
