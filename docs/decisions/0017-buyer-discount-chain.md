# 0017 — The market chain: buyer price, then seller receives

**Status:** accepted, 5 October 2026. Doug's model, from a live cellar: 561
lines, 3,544 bottles, Hong Kong bond, private seller.

## Context

The pricer already took a target margin and a line discount, but both priced
off a single flat number: `Sell = UK Reference × (1 − discount)`. That
conflates two different transactions into one. In this business there are
always two sides of one deal:

    UK market reference (per bottle)      M
    buyer price            = M × 0.80      (trade buyers move parcels 20% below market)
    seller receives        = buyer × 0.92  (our 8% margin on the sale)
                           = M × 0.736

A trade buyer **purchases** below market; the seller we are brokering for
**sells** below that again. One is a sale, the other a purchase, and treating
them as one flat discount hides where the margin actually lives — on £500,000
of buyer-side sales that is £460,000 to sellers and £40,000 of margin, and
nothing in the old model named either number.

The sharper gap: most lines of a private cellar arrive with **nothing** —no
manual price, no line margin, no line discount, and usually no deal margin
either, because nobody has agreed a cost yet. Before this decision, such a
line simply could not be priced: `_basis()` raised `CannotPrice`. That is the
common case for this kind of deal, not the exception.

## Decision

**`buyer_discount` is a new, lowest-precedence basis.** Precedence becomes:

    manual price > line margin > line discount > deal margin > the market chain

The chain fires only when none of the first four apply **and** a UK Reference
exists — exactly the case that used to fail outright. It is additive: every
existing basis behaves exactly as before, byte for byte, which is why every
pre-existing pricing test still passes unchanged.

**The chain reuses `sell_price`/`cost_gbp`, not new primitives.** `sell_price`
is, and was already, the price charged to the buyer (`buyer_offer_line` —
literally an offer *to a buyer*); `cost_gbp` is, and was already, what we pay
to acquire the stock. The chain simply computes both together from one
reference instead of requiring the operator to supply `cost` and a
margin/discount separately:

    buyer_price_gbp  = round(M × (1 − BUYER_DISCOUNT))
    seller_price_gbp = round(buyer_price_gbp × (1 − MARGIN_ON_SALE))
    sell_price = buyer_price_gbp ; cost_gbp = seller_price_gbp

Nothing downstream — GP, gross margin, the four commercial flags, the export
gate, the buyer document — had to change to understand this basis. It is
telling that this *never* produces `NEGATIVE_GP`, `COST_ABOVE_UK_REFERENCE` or
`SELL_ABOVE_UK_REFERENCE`: both prices derive from one chain, so by
construction the seller price and the buyer price are always below Reference,
and the fee is always positive. `DEEP_DISCOUNT` still fires if a deal sets a
buyer discount deeper than the threshold — that is still worth a look, and the
mechanism needed no change at all.

**`buyer_price_gbp`/`seller_price_gbp` are named, GENERATED columns**, not
independent writes: `CASE WHEN price_basis = 'buyer_discount' THEN sell_price
END`. The two numbers the brief asked to "appear on the line" can never drift
from the figures the rest of the system already audits, because structurally
they are not separate figures — this is the same discipline this codebase
already uses for the export gate and the vintage band's flags, applied here.

**`BUYER_DISCOUNT = 0.20`, `MARGIN_ON_SALE = 0.08`**, in `app/pricing/pricer.py`
— outside `app/core/`, like everything else in this decision. Both are
per-**deal** overridable (never per-line — Doug's spec), stored on `deal` and
echoed onto every `pricing_result` that used them, so a reprice is a diff
against what was actually used, not a new guess.

**A stray `cost` is not consulted by this basis.** A line can carry a `cost`
figure for other reasons (what the seller once paid, say) without it driving
the chain: the chain always derives the seller price from the market
reference. If an operator wants a known cost to set the price, that is what
`line_margin`/`global_margin` are for, and they still outrank the chain.

## What this is not

This is not a general-purpose "default discount" — it fires only as a last
resort, and only when the more specific bases (a known cost, an explicit
override) are absent. It does not change the meaning of any existing basis,
and it adds no new app/core invariant: `app/core/` is untouched by this
decision, as it was by none of the pricing step's work before it.

## Consequences

- Schema: `deal.buyer_discount`, `deal.margin_on_sale` (nullable numeric(6,4));
  `pricing_result.buyer_discount`, `.margin_on_sale` (nullable, the values
  actually used) and `.buyer_price_gbp`/`.seller_price_gbp` (GENERATED);
  `price_basis` CHECK extended with `'buyer_discount'`. Migration 0014.
- Tests: `tests/test_pricing.py` (the pure function — precedence, defaults,
  overrides, the four commercial flags never misfiring except DEEP_DISCOUNT,
  bounds, the £500,000 worked example) and three pipeline tests in
  `tests/test_service.py` (a bare-reference line pricing end to end, a deal
  override recorded and flowing to the issued document, and a known cost still
  outranking the chain through the API).
- The console (`web/app/upload.jsx`, `web/app/deals/[dealId]/line.jsx`) shows
  both settings at upload and both prices on a chain-priced line, named
  "buyer pays" / "seller receives", never as a bare "sell"/"cost".
