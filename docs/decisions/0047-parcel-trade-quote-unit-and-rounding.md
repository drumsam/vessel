# 0047 — a parcel-trade quote is in the supplier's unit, rounded up to the next 5

**Status:** accepted, 31 October 2026, on Doug's instruction, after the first
real Pocket trade (Salon 2006, GBP 3,995 /cs of 6 from Vinum). A quote of
GBP 4,314.60 per case is not how the trade quotes, and a normalised
GBP 665.83 /btl is not what the supplier said.

## The quote unit

Every Pocket price — supplier, market, auction, VESSEL sell, gross — is shown
in the supplier's own commercial unit:

- stated per case, on a case line → `/cs of N`
- stated per bottle, or a single bottle → `/btl`
- stated as a total → the natural unit of the line (`/cs of N` for cases,
  `/btl` otherwise), with the total shown underneath

Storage does not change: `pricing_result` and `fulfilment` stay per commercial
unit (pack_size), exactly as before. Market and auction are converted to the
same unit so comparisons are like for like.

## The rounding rule

The VESSEL sell is rounded **up** to the next multiple of 5 in the quote unit
itself — the case price for a case quote, the bottle price for a bottle quote —
never a per-bottle equivalent rounded and multiplied back. 4,314.60 → 4,315;
4,320 → 4,320; 719.10 → 720; 721 → 725. Ceiling, not nearest.

- The default is supplier quote × (1 + `MIN_TRADE_MARGIN`), rounded up; the
  shown markup is that of the committed figure (Salon: GBP 4,315, +8.0%).
- A typed price is rounded up the same way. The server refuses to commit a
  VESSEL sell that is not a whole 5 in the quote unit.
- Gross is computed from the committed, rounded price.
- The supplier's price is never rounded: a decimal the supplier actually
  quoted is kept and shown as stated.

This narrows invariant 7 (every rounding point half-even to pence) for one
figure only, the parcel-trade VESSEL sell. Every other rounding rule is
unchanged. The Salon trade confirmed at GBP 4,320 before this rule is
untouched and valid (4,320 is itself a whole 5).

## Not changed

Currency is shown as an ISO code (`GBP 4,315`), never a symbol, in Pocket;
stored codes are unchanged. No migration.
