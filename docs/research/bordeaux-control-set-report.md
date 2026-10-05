# Bordeaux control set — the coverage question, answered

Run 26 September 2026. Locked `app/core/benchmark.py`, unmodified.
Evidence: `control-set/bx-lines.json`, `bx-interim.json`, `bx-benchmark.json`, `run_bx.py`.

## Why

The Burgundy control set came back with almost no market: priced 8 lines of 70
with six merchants searched. The open question was whether that is **the wine
trade** or **Burgundy**. Same method, same seller, different region.

Seller list: Lea & Sandeman's live In Bond **Bordeaux** — 50 distinct
wine/vintage/format lines, 2011–2022. Searched: Farr Vintners (5,693 rows),
Albany (1,279 wines), Vinum (2,456 rows), Goedhuis Waddesdon (17,331 variants),
Bordeaux Index (38 producer pages, 603 cards). Every comp verified by eye.

## Headline: it was Burgundy

| | Burgundy | Bordeaux |
|---|---|---|
| Lines | 70 | 50 |
| **READY** (priced on two independent merchants) | 3 · 4% | **18 · 36%** |
| REVIEW (one merchant) | 5 · 7% | 10 · 20% |
| NO_MARKET | 62 · 89% | 22 · 44% |
| Lines with any evidence | 8 · 11% | **28 · 56%** |

Both figures are the realistic view — Lea & Sandeman treated as the seller, its
own price excluded. Counting L&S as a merchant, Bordeaux is 28 READY of 50.

**Nine times the ready rate, five times the coverage.** The pricer was never the
problem and neither was the method; Burgundy is simply a market of thousands of
tiny growers, and Bordeaux is a few hundred châteaux everybody stocks.

## The prices agree, too

Depth is only half of it. In Bordeaux the independent merchants largely confirm
each other, which is what makes a Reference meaningful:

| Line | Wine | L&S | Others | Spread |
|---|---|---|---|---|
| B01 | Lagrange 2022 | 210 | Albany 205 · BI 207 | 2% |
| B03 | Canon 2021 | 270 | BI 259 · Albany 260 · Farr 300 | 16% |
| B09 | Dom. de Chevalier 2020 | 230 | Farr 212 · Albany 230 | 8% |
| B29 | Le Gay 2019 | 390 | Farr 395 · BI 399 | 2% |
| B31 | Léoville Barton 2019 | 335 | BI 317 · Farr 330 | 6% |
| B42 | Léoville Barton 2018 | 300 | BI 295 · Farr 300 | 2% |
| B44 | Haut-Bailly 2016 | 510 | BI 500 · Albany 510 | 2% |

Compare the Burgundy equivalents: +72%, +33%, +27%. Six Bordeaux lines agree
inside 2%. That is a market with a price, not a collection of opinions.

## Where it still disagrees, and why that matters

**B10 La Gaffelière 2020** — L&S £170 · BI £175 · Vinum £200 · **Albany £325**.
Four merchants, three clustered, one 91% above the floor. Vinum's own title says
"Premier Grand Cru Classé B", so this is the same wine, not a name collision.
This is exactly what the vintage-band check was built for — and **it cannot run,
because the register holds only Burgundy**. That is now the strongest argument for
extending it: Bordeaux is where the depth is, so it is where an outlier does
damage.

**B27 Le Dôme 2019** — BI £415 · L&S £510 · Albany £680 (+64%).
**B43 Beau-Séjour Bécot 2018** — BI £244 against L&S £370, i.e. the seller is
34% above the only other merchant. **B45 Ormes de Pez 2016** — BI £321 against
L&S £380. Both are lines where we would be buying well, and both sit in review on
one comp, correctly.

## New traps found

1. **Goedhuis SKUs carry duty status and price basis independently**, and the
   combinations are not what you would guess. One wine, seven variants, five
   prices: `-IB-InBond-ExcVAT` (£90), `-IB-BR-90-InBond-ExcVAT` (£90, brokered),
   `-IB-Retail-IncVAT` (£127.84), `-DP-InBond-ExcVAT` (£106.53),
   `-DP-Retail-IncVAT` (£127.84), and more. **Filtering on `-IB-` alone captures
   duty-paid retail prices as In Bond.** The comparable is `IB` *and* `InBond`
   *and* `ExcVAT`. On L'Hêtre that is £90 against £127.84 — a 42% error.
   Availability also differs per variant: on all three matched wines the
   available In Bond variant was the **brokered** one.
2. **Second wines sit beside their grand vin in every catalogue.** Caught live:
   "La Parde de Haut Bailly" matching Haut-Bailly, and (from the earlier round)
   Louis Latour's Chevalier-Montrachet matching Domaine de Chevalier — a £2,300
   Burgundy white against a £230 Bordeaux red. Exclusions now cover Parde, Petite
   Église, Réserve de Léoville, Echo, Baron de Brane, Esprit, Virginie, Chapelle,
   Confidences.
3. **Bordeaux Index holds a misspelled duplicate producer slug**:
   `chateau_gran-puy-lacoste` alongside `chateau_grand-puy-lacoste`. Querying one
   of two would have halved that producer's depth. The union rule already built
   handles it — but only if the alias list includes the typo.
4. **Farr disambiguates in parentheses**: "Lagrange (St Julien)", the only thing
   separating it from Château Lagrange in Pomerol. The parenthetical is identity
   data, not noise.
5. **BI LiveTrade depth inside one merchant is wide in Bordeaux too**: eight
   listings of 2020 La Gaffelière from £175 to £248, seven of 2021 Canon from
   £259 to £536. Merchant-best handles it; a naive "first offer" read would not.

## What this changes

1. **Extend the vintage register to Bordeaux next.** The band check is the
   safeguard against exactly the La Gaffelière case, and it is silent outside
   Burgundy. Left and right bank, then Champagne and the Rhône.
2. **Report confidence by region.** A Bordeaux parcel can be priced on evidence;
   a Burgundy parcel usually cannot. The operator should see that distinction
   before starting, not discover it line by line.
3. **Coverage work is now clearly about Burgundy**, and the merchants that would
   help there are the Burgundy specialists plus Liv-ex — not more Bordeaux
   sources, which are already sufficient for a ready price on a third of lines.
