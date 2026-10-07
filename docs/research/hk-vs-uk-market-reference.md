# Hong Kong vs UK: which market is "market"?

6 October 2026. Measured, not assumed. Live data: Altaya Wines (HK retail, 2,871
listings read in full) against Bordeaux Index (UK In Bond, per-vintage queries).
FX GBP→HKD 10.37 — **confirm this against your bank rate**, every figure below
scales with it.

## Method

Altaya is a Hong Kong fine wine retailer with a public catalogue and prices in
HKD, duty-free (Hong Kong abolished wine duty in 2008). Bordeaux Index publishes
UK In Bond offers in GBP. For nine wines both markets hold the **same wine, same
vintage, 750ml**, with damaged-label listings excluded.

This is HK **retail** against UK **In Bond trade** — different levels of the
chain, which is the point: it's what a Hong Kong buyer pays locally versus what
the wine costs at UK trade.

## Result: Hong Kong sits about 22% above UK In Bond

| Wine | HK retail | UK In Bond | UK at HK$ | HK premium |
|---|---:|---:|---:|---:|
| Ch. Montrose 1989 | 3,900 | £478.75 | 4,965 | **−21%** |
| Ch. Montrose 2003 | 1,490 | £125.83 | 1,305 | +14% |
| Clos des Lambrays 2019 | 4,300 | £354.67 | 3,678 | +17% |
| Ch. Cheval Blanc 2018 | 5,500 | £362.50 | 3,759 | **+46%** |
| Ch. Cheval Blanc 2021 | 3,900 | £276.67 | 2,869 | +36% |
| Confuron, Romanée St-Vivant 2016 | 5,950 | £437.83 | 4,540 | +31% |
| Confuron, Romanée St-Vivant 2018 | 4,900 | £387.50 | 4,018 | +22% |
| Bernstein, Chambertin 2016 | 6,980 | £636.67 | 6,602 | +6% |
| Bernstein, Clos de Bèze 2015 | 5,950 | £425.67 | 4,414 | +35% |

**Median +22%. Mean +21%. Range −21% to +46%.**

Eight of nine are above UK. The exception, Montrose 1989, is a mature Bordeaux
where UK depth is better than Hong Kong's — which is itself a useful signal about
where each market is strong.

## What this means for the first drop

Pricing at 20% below the **UK** reference lands, on these numbers, at a **24% to
45% discount to Hong Kong retail**:

| Wine | VESSEL price (UK ref −20%) | HK retail | Below local |
|---|---:|---:|---:|
| Cheval Blanc 2018 | 3,007 | 5,500 | **45%** |
| Bernstein Clos de Bèze 2015 | 3,531 | 5,950 | 41% |
| Cheval Blanc 2021 | 2,295 | 3,900 | 41% |
| Confuron RSV 2016 | 3,632 | 5,950 | 39% |
| Confuron RSV 2018 | 3,215 | 4,900 | 34% |
| Clos des Lambrays 2019 | 2,942 | 4,300 | 32% |
| Montrose 2003 | 1,044 | 1,490 | 30% |
| Bernstein Chambertin 2016 | 5,282 | 6,980 | 24% |
| Montrose 1989 | 3,972 | 3,900 | −2% |

Three consequences, in order of how much money they're worth:

**1. We are leaving roughly 20% on the table for the seller.** A Hong Kong buyer
comparing to what they can actually buy locally sees a 30–45% discount. They
would act at 25% below local — which is still a strong deal — and the seller
would net materially more. On the Hong Kong cellar's 42 recommended lines that
difference is tens of thousands of pounds.

**2. The bands should be set against the buyer's own market.** v4's three bands
are right; the reference they discount from should be the market the buyer buys
in. For an HK buyer: discount from the HK reference. For a UK buyer: UK In Bond.
Same engine, two reference sets.

**3. Mature Bordeaux is the exception.** Montrose 1989 is cheaper in Hong Kong
than in the UK. Those lines should be sold into the UK, not locally — and the
same logic says prestige Burgundy and Champagne should be sold into Asia.
Routing by market, not just by buyer.

## What to do with it

- **Build a second reference set.** Altaya alone is a usable HK anchor today: a
  public catalogue, 2,871 listings, clean Shopify JSON, one request. Kerry Wines
  and Madison next, then the HK auction results for depth.
- **Store the market on the listing.** Already in the Code brief: FX rate and
  evidence market recorded at the moment of pricing. This is why.
- **Treat the HK premium as evidence, not a mark-up.** The claim on the page
  stays "X% below market" with the market named: *"34% below the best Hong Kong
  retail offer we can find."* That is a stronger and more honest sentence than
  the UK version, and it is checkable by the buyer in thirty seconds — which is
  exactly the behaviour we want.
- **Nine pairs is a direction, not a constant.** Before setting bands off it, run
  the same comparison across 40–60 pairs with Kerry and Madison added. A day's
  work, and it is the difference between a 22% rule of thumb and a number per
  region.

## Caveats, stated

- Retail against trade: Altaya is a shop, Bordeaux Index's In Bond offers are
  closer to wholesale. Part of the 22% is simply the retail margin, and a private
  HK buyer cannot buy at UK In Bond without freight, transfer and time — which is
  precisely the friction VESSEL removes and gets paid for.
- One HK source. Altaya is reputable but single, and the same single-source
  caution we apply to UK evidence applies here.
- Nine pairs. Small, and the spread (−21% to +46%) is wide enough that per-wine
  evidence will always beat an average.
- FX at 10.37 from a public rate, not your bank's.

## Sources

- [Altaya Wines](https://www.altayawines.com) — HK retail catalogue, read 6 October 2026
- [Bordeaux Index](https://bordeauxindex.com) — UK In Bond offers, per-vintage queries, 6 October 2026
- [GBP/HKD rate reference](https://pluang.com/en/tools/currency-converter/gbp-hkd)
