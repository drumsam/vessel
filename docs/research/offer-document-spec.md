# Spec — the seller offer document

6 October 2026. Unblocks §4 of the cellar-to-offer brief. The rendered design
reference ships beside this file as `offer-sheet-reference.html` — open it, it is
the target. Published copy: the artifact titled **WFS Cellar Offer** in Doug's
gallery (an Artifact link cannot be fetched by Claude Code, which is why the HTML
is in the repo).

## What this is, and what it is not

A **seller-facing** document: what we will pay a private owner for their cellar,
with the market evidence beside every figure. It is a different object from
`buyer_offer`, which prices stock out to a trade buyer, and the two must not
share a table:

| | `buyer_offer` | `seller_offer` (new) |
|---|---|---|
| Reader | trade buyer | private owner / seller |
| Price shown | `buyer_price_gbp` | `seller_price_gbp`, with market reference |
| Direction | we sell | we buy |
| Evidence shown | market claim, gated by 0010 | per-line source count, always |
| Unpriced lines | excluded | **listed, with the reason** |

One deal can produce both. The seller offer comes first in time, and the numbers
must reconcile: `buyer_price_gbp` on the seller offer is the same figure the
buyer offer later issues, or the deal has drifted.

## Schema

```sql
CREATE TABLE seller_offer (
    seller_offer_id   bigserial PRIMARY KEY,
    deal_id           bigint      NOT NULL REFERENCES deal(deal_id),
    reference         text        NOT NULL,          -- the seller's own list ref, e.g. 'WFS 260900'
    seller_name       text        NULL,              -- shown only if the seller wants it
    stock_location    text        NOT NULL,          -- UK_BOND | HK_BOND | EU_BOND | DUTY_PAID_UK | OTHER
    warehouse         text        NULL,
    condition_basis   text        NOT NULL,          -- the stated assumption, verbatim on the document
    buyer_discount    numeric(5,4) NOT NULL,         -- as applied, from the deal
    margin_on_sale    numeric(5,4) NOT NULL,
    landed_cost_basis text        NULL,              -- 'per_bottle' | 'per_case' | NULL when not applicable
    landed_cost_gbp   numeric(14,2) NULL,            -- excluded from line prices, shown separately
    valid_days        integer     NOT NULL DEFAULT 7,
    issued_at         timestamptz NOT NULL DEFAULT now(),
    issued_by         text        NOT NULL,
    expires_at        timestamptz GENERATED ALWAYS AS
                        (issued_at + (valid_days || ' days')::interval) STORED,
    superseded_by     bigint      NULL REFERENCES seller_offer(seller_offer_id),
    CONSTRAINT landed_cost_complete CHECK (
        (landed_cost_basis IS NULL) = (landed_cost_gbp IS NULL))
);

CREATE TABLE seller_offer_line (
    seller_offer_line_id bigserial PRIMARY KEY,
    seller_offer_id   bigint      NOT NULL REFERENCES seller_offer(seller_offer_id) ON DELETE CASCADE,
    line_id           bigint      NOT NULL REFERENCES seller_line(line_id),
    display_producer  text        NOT NULL,          -- as the document prints it
    display_wine      text        NOT NULL,
    vintage           integer     NOT NULL,
    release_code      text        NULL,              -- 0019: '156e' and friends
    bottle_ml         integer     NOT NULL,
    bottles           integer     NOT NULL CHECK (bottles > 0),

    state             text        NOT NULL,          -- PRICED | NO_MARKET | FORMAT_EXCLUDED | IDENTITY_PENDING
    uk_reference_gbp  numeric(14,2) NULL,            -- per bottle, NULL unless PRICED
    seller_price_gbp  numeric(14,2) NULL,            -- per bottle
    buyer_price_gbp   numeric(14,2) NULL,            -- per bottle, for reconciliation
    line_total_gbp    numeric(14,2) NULL,

    source_count      integer     NOT NULL DEFAULT 0,
    derived           boolean     NOT NULL DEFAULT false,   -- 0016/0018 derivation used
    flags             text[]      NOT NULL DEFAULT '{}',
    exclusion_reason  text        NULL,              -- plain English, printed when not PRICED

    CONSTRAINT priced_has_numbers CHECK (
        (state <> 'PRICED') OR
        (uk_reference_gbp IS NOT NULL AND seller_price_gbp IS NOT NULL
         AND buyer_price_gbp IS NOT NULL AND line_total_gbp IS NOT NULL
         AND source_count >= 1)),
    CONSTRAINT unpriced_has_reason CHECK (
        (state = 'PRICED') OR exclusion_reason IS NOT NULL)
);
```

Those two CHECKs are the point of the table: **a priced line cannot exist without
a market figure and at least one source, and an unpriced line cannot exist
without a reason the seller can read.**

## Rules the document must obey

1. **Every price traces to an offer.** `uk_reference_gbp` comes from the
   benchmark, never from an operator's typing. If the benchmark has no
   reference, the line is `NO_MARKET` and prints the reason.
2. **`source_count` is printed per line**, as "1 source" or "3 sources". One
   source prints as indicative and the document header says the offer is a draft
   until a second merchant is found. This is `ONE_COMP` made honest to the seller
   rather than hidden in the console.
3. **Derived lines say so**, in the seller's words: "priced from a six-bottle
   case offer" (0016/0018), with the source unit named.
4. **Excluded lines are listed, not dropped.** Large formats, pending editions,
   identity queue, no market — each with its own sentence. A seller trusts a
   document that states its limits.
5. **Landed cost is never inside a line price.** It appears once, named, below
   the total.
6. **No market claim without a reference** — decision 0010 applies unchanged.
   The words "market" and "below market" cannot appear on a line whose
   `uk_reference_gbp` is NULL.
7. **Reissue, never edit.** A re-price creates a new `seller_offer` and sets
   `superseded_by` on the old one, so what the seller was shown is always
   recoverable.

## Export

Two renderings from the same data:

- **HTML**, the design in `offer-sheet-reference.html`: a measured single column,
  summary figures, the line table, the four-step method, the exclusions, the
  terms. Sendable as a link.
- **PDF**, same content, print layout.

The exporter owns no arithmetic. Every number it prints is already in
`seller_offer_line`.

## Copy that does the work

The headline numbers, from the live draft (34 lines of the Hong Kong cellar):
market £62,386 · offer £45,916 · **73.6% of market**. A seller will compute that
share themselves, so the document shows it openly, next to the method that earns
it. The four steps — identity, live merchant offers, lowest comparable sets the
market, then buyer discount and fee — are the product. Most brokers quote a
number and renegotiate after collection; this document is the opposite of that,
and it should read that way.

## What is still Doug's call

- Whether `seller_name` prints at all (default: no).
- Whether the market reference column is shown to every seller or only on request
  (default: shown — it is the reason the offer is credible).
- Logo, sender block and footer wording for the real firm.
