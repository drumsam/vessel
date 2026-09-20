# 0008 — The buyer-export gate, and producer-only aliases

**Status:** accepted, 20 September 2026.

## Two gates, not one list

`REVIEW_FLAGS` is about **evidence quality**: can we believe this benchmark.
Commercial flags are about **the trade**: do we want to do it at this price.
Putting the second into the first would mean a thin margin made us doubt the
market data, which is not what happened. So they are separate gates, and
`REVIEW_FLAGS` is unchanged.

## What gates an export

A `pricing_result` carrying either of these cannot reach a buyer offer until a
named operator has accepted it, with a timestamp:

- **`NEGATIVE_GP`** — the sell price is below cost.
- **`SELL_ABOVE_UK_REFERENCE`** — the client-facing document says "% below UK
  market". Publishing it while the price is above the Reference is a false
  claim, which is a different class of problem from a thin margin.

These stay context and never gate:

- **`COST_ABOVE_UK_REFERENCE`** — buying badly is a commercial fact, not a false
  claim. It also cannot occur alone: buying above market leaves selling above
  market or selling at a loss, and both gate on their own account.
- **`DEEP_DISCOUNT`** — selling below market is the product. Gating on it would
  gate every line, and a warning that fires on everything trains operators to
  click through, exactly as `REPACK` would have (README, review gating).

## Enforced by keys, not by convention

The same structural chain as NOT_SEARCHED, so no code path can forget it:

- `pricing_result.requires_acknowledgement` is a **generated** column over the
  flags, so it cannot drift from them.
- `pricing_result` has `UNIQUE (pricing_id, requires_acknowledgement)`, and
  `buyer_offer_line` carries `(pricing_id, pricing_requires_ack)` as a foreign
  key into it. An export cannot claim a price needs no acknowledgement when it
  does.
- `CHECK (NOT pricing_requires_ack OR ack_id IS NOT NULL)` requires the
  acknowledgement, and `(ack_id, pricing_id)` is a foreign key into
  `pricing_acknowledgement`, so it must be an acknowledgement **of that price**.
- One acknowledgement per `pricing_result`. Re-pricing produces a new result,
  which needs its own: an operator accepted a number, not a line.

## Producer-only aliases

An alias with no cuvée (`wine_key` ending in `|`) catches every listing a
merchant prints under that producer alone. It is needed — Farr prints "Lafite
Rothschild" with no cuvée at all — and it is the shape most likely to cause a
catastrophic mismatch, because Farr also prints both "Veuve Clicquot" and
"Veuve Clicquot Rosé" (see 0006).

Three rules:

1. **Operator only, never an AI proposal.** A database CHECK, not a code path.
2. **Refused where the producer has more than one canonical wine**, with a 409
   listing the candidates. The operator must name the target again in
   `confirm_target` to proceed: two deliberate statements, not one.
3. **Marked and auditable.** `wine_alias.is_producer_only` is generated from the
   key, and `GET /aliases?producer_only=true` is the audit view.

## Consequence

An operator can still sell below cost or above the market. They cannot do it
silently, and the record says who decided and when.
