# Liv-ex — scoping, not building

**Status:** scoping only, 11 October 2026, per Doug: "Do the scoping
write-up now… Subscription tier, auth, rate limits, fields returned, and
whether it fits the existing merchant contract or needs its own evidence
type." No API has been called. Everything below marked "needs confirming"
is general market knowledge about how Liv-ex's data products are
structured, not a verified reading of current API documentation —
exactly the distinction this codebase's own "investigate live, don't
assume" discipline draws everywhere else, applied here to the one source
nobody has actually looked at yet. Before any build: get the real API
docs from Liv-ex under the subscription Doug takes out, and re-scope
against them, the same way every adapter in this fleet was built from a
live response, never a guess.

## Why Liv-ex, after everything else

`docs/research/uk-trade-current-releases-vs-back-vintage-cellars.md`:
every UK retail-catalogue source checked shows current releases, and
this cellar is 2002-2016. Liv-ex is structurally a different kind of
source — a professional trading exchange for EXACTLY the back-vintage,
secondary-market wine this cellar holds, not a shop window for new
releases. It also prices **per-bottle-equivalent by construction**
(Liv-ex's whole purpose is comparing wines across case formats on one
footing), which sidesteps decision 0016/0028's case-derivation machinery
entirely for whatever it covers — not because the derivation is wrong,
but because there would be nothing left to derive.

## What is reasonably well known

- **Liv-ex is a trade-only exchange.** Access to trade ON it (placing
  bids/offers, seeing the live order book) requires exchange membership,
  which is a different commercial relationship from a market-data
  subscription. Doug is already a real trade participant, which is the
  route to exchange access specifically — separate from whatever a pure
  data API needs.
- **Liv-ex separately licenses market data** (historically via products
  named around the "Fine Wine 100/1000" indices and per-wine valuations)
  to parties who want pricing without being an exchange member —
  wineries, insurers, auction houses, and similar. This is the more
  likely route for what this system needs: a per-wine, per-vintage,
  per-format reference figure, not a seat on the exchange itself.
- **The core data product is a valuation, not a specific merchant's
  ask.** Liv-ex's own "Mid Price" (or whatever the current product calls
  it) is a blended market figure computed FROM trading and bid/offer
  activity across the exchange's members — not one merchant's own stock
  at one merchant's own price. That distinction is the whole reason this
  needs its own scoping rather than being assumed to slot into the
  existing adapter contract (see below).

## What needs confirming directly, before any design decision

1. **Subscription tier.** What a market-data licence costs, what it
   covers (which wines, how far back, bottle-equivalent only or also raw
   trade/bid-offer detail), and whether Champagne and the other regions
   this cellar holds are in scope at the tier Doug would take.
2. **Auth.** API key, OAuth, IP allowlisting, or a combination — and
   whether credentials are per-application or per-seat.
3. **Rate limits.** Whether this is a live-query API (pull a wine on
   demand) or a bulk feed (a nightly file of everything licensed) — this
   changes the whole shape of the integration, from "a `Targeted` adapter
   like Bordeaux Index" to "a file import like the trade lists
   (`docs/research/trade-list-import-format.md`)," and only Liv-ex's own
   documentation answers it.
4. **Fields actually returned.** At minimum expected: LWIN or equivalent
   identity code, wine name, vintage, format (bottle/pack size), currency,
   the valuation figure itself, and — if the tier includes it — the
   underlying bid/offer or last-trade levels individual members placed,
   not just the blended figure. Whether a release-code concept exists for
   anything like Krug's numbered editions (unlikely, but decision 0019
   exists because assuming "no such thing" once was already wrong once).

## Does it fit the existing merchant contract, or need its own evidence type

**Provisional answer, to be confirmed against the real fields returned:**
probably **its own evidence type**, not a `Merchant`/`Offer` row.

The existing contract (`app/adapters/base.Adapter`) models ONE merchant's
OWN stock at ONE merchant's OWN stated price — which is exactly what
`PriceKind.ASK` means, and exactly what Floor/Reference/Median are built
from (invariant 4: "Floor = lowest merchant-best"). A blended market
valuation is not that, for the same reason a FINE+RARE indication is not
that (decision 0013) and a BI LiveTrade bid is not that (decision 0026):
it is a number ABOUT the market, not a number FROM a specific seller.
Forcing it into the `Offer` model as if it were one more merchant's ask
would be exactly the kind of invented substitute CLAUDE.md's opening line
refuses — "Never invent, estimate or silently substitute a market
price."

If the licensed data turns out to include the underlying individual
bid/offer/last-trade levels (not just the blended valuation), THOSE
specific rows could plausibly be modelled as `BidEvidence`/
`LastTradeEvidence` under a `merchant_id` of `"liv-ex"`, exactly as BI
LiveTrade's own bid/offer ladder is today (decision 0026) — corroboration
that is shown and never prices. The blended Mid-Price-style figure itself
would still need a genuinely new evidence type: a named MARKET REFERENCE,
sitting beside the benchmark the way `app/market/` already sits beside
`app/core/` — informing a person, never a figure the core produced.
Decision 0021 (VESSEL's named reference markets, `UK_IN_BOND`/
`HK_RETAIL`) is the nearest existing shape this could extend, though
VESSEL and the direct-purchase business share no table on purpose
(`CLAUDE.md`), so this would be its OWN reference, not a reuse of VESSEL's.

## What this is not

Not a build. Not an assumption that Liv-ex's API still looks like
whatever this scoping describes by the time a subscription is actually
in hand — the first real action once access exists is the same live
investigation every other source in this fleet got, fixture captured,
traps found and tested, before a single line of integration code. Not a
reason to delay the trade lists, which need nothing from Liv-ex and can
arrive first.
