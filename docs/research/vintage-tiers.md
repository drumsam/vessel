# Vintage quality register — Burgundy

Built 24 September 2026. Data: `vintage-tiers.csv` (same folder, 58 rows).

## Why it exists

The pricer needs to know which vintages are comparable. Doug's rule:

> An ordinary vintage prices near another ordinary vintage even five years apart.
> Stellar vintages are always priced differently.

So the vintage-band outlier check picks neighbours by **quality**, not by
proximity in years. This register is what makes that possible.

## Scale

| Tier | Label | Meaning |
|---|---|---|
| 1 | great | benchmark vintage, priced in its own class |
| 2 | excellent | strong, widely admired |
| 3 | solid | good, unremarkable, the middle of the distribution |
| 4 | ordinary | light, variable, or commercially unloved |
| 5 | weak | the years the trade discounts |

## Sources and method

Read for **red**: Wine Spectator's Côte de Nuits chart, Wine Spectator's Côte de
Beaune chart, and Burgundy Report's 20-point chart (average / best / worst).
Read for **white**: Wine Spectator's white Burgundy chart and Burgundy Report's
white table. Decanter's and Jancis Robinson's vintage guides were read as prose
for corroboration; their numeric ratings sit behind subscription and were not
used.

Each source was ranked within itself, then the tier is the consensus of those
rankings. **The stored number is ours, not theirs.** We record which charts were
consulted per row and do not reproduce their scores — that keeps us clear of
republishing someone else's vintage database, and it means a disagreement
between sources shows up as a note rather than being averaged away silently.

Where sources disagreed materially, the more conservative (lower) tier was taken,
because over-rating a vintage widens the acceptance band and lets a real outlier
through.

## Burgundy red

| Tier 1 | Tier 2 | Tier 3 | Tier 4 | Tier 5 |
|---|---|---|---|---|
| 2005 · 2015 · 2019 · 2022 | 1996 · 1999 · 2002 · 2009 · 2010 · 2012 · 2016 · 2020 · 2023 | 1995 · 1998 · 2001 · 2006 · 2008 · 2013 · 2014 · 2017 · 2018 | 1997 · 2000 · 2003 · 2007 · 2011 · 2021 | 2004 |

## Burgundy white

| Tier 1 | Tier 2 | Tier 3 | Tier 4 | Tier 5 |
|---|---|---|---|---|
| 1996 · 2002 · 2014 · 2022 | 1995 · 2005 · 2008 · 2010 · 2017 · 2019 · 2020 · 2023 | 2000 · 2004 · 2006 · 2007 · 2011 · 2012 · 2013 · 2016 · 2018 · 2021 | 1997 · 1998 · 1999 · 2001 · 2009 | 2003 |

Note the reds and whites diverge sharply in 2003 (heat, tier 4 red / tier 5
white), 2014 (tier 3 red / tier 1 white) and 2009 (tier 2 red / tier 4 white).
Keying the register by colour as well as region is not fussiness — it is the
difference between a sane band and a nonsense one.

## How it is used

Neighbour selection for the band check, in order: same wine and unit, within ±8
years, **same tier**; widen once to tier ±1 only if fewer than two vintages
qualify; never wider. No tier is ever used to scale a price — it only decides
which vintages may be compared.

## Maintenance

A file in the repo, loaded by `scripts/load_vintage_tiers.py`. Changing a tier is
a pull request. That is deliberate friction: a tier change moves which prices are
treated as outliers, so it should be visible in history and reviewed, not typed
into a screen at speed.

## What is missing

Bordeaux (left and right bank), Champagne, Rhône north and south, Piedmont,
Tuscany. Until a region is in this file the band check stays quiet for it, which
is the correct failure. Burgundy came first because it is where the depth problem
lives.

## Sources

- [Burgundy / Côtes de Nuits Reds — Wine Spectator](https://www.winespectator.com/vintage-charts/region/burgundy-cotes-de-nuits-reds)
- [Burgundy / Côtes de Beaune Reds — Wine Spectator](https://www.winespectator.com/vintage-charts/region/burgundy-cotes-de-beaune-reds)
- [Burgundy: Whites — Wine Spectator](https://www.winespectator.com/vintage-charts/region/burgundy-white)
- [A Burgundy Vintage Chart — Burgundy Report](https://www.burgundy-report.com/discover-burgundy/17-a-burgundy-vintage-chart/)
- [Red Burgundy Vintage Guide — Decanter](https://www.decanter.com/learn/vintage-guides/red-burgundy-117871/)
- [Burgundy Red Wine Vintage Chart — Jancis Robinson](https://www.jancisrobinson.com/learn/vintages/burgundy-red)
