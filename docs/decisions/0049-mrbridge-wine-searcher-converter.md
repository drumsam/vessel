# 0049 — MrBridge Wine-Searcher dataset converter

**Status:** accepted (converter), 1 November 2026, on Doug's instruction.
Three questions below are open and decide whether this source can steer
MARKET; until they are answered it is stored evidence only.

## What it is

`app/feed/mrbridge.py` turns a MrBridge Wine-Searcher dataset (the Apify
Actor `mrbridge/wine-searcher-scraper-from-list`, run by Doug outside VESSEL)
into a decision-0048 batch, source `wine-searcher-via-mrbridge`. VESSEL never
calls or controls the Actor. The data is a third-party scrape of
Wine-Searcher, whose own robots.txt and bot detection refuse automated
access; Doug has chosen to use it and holds that account and terms risk.

It passes on only what a row states. From the real dataset
(`tests/fixtures/mrbridge/dataset_2026-11-01.json`): the cheapest current
offer's amount, currency and merchant, `bottlesPerUnit`, `offersCount`,
vintage (null on a generic wine page), wine and winery names. It does NOT
state the bottle size, the duty status, or any offer but the cheapest; those
stay unknown. The amount is normalised per 75cl, so a multi-bottle listing's
own price (2001 Leroy: 3,333.33 × 6 = 19,999.98, not a printed price) is
never reconstructed.

Identity is VESSEL's: the winery is always passed as the producer (the
resolver's producer-less substring mode would let "…Chambertin Clos de Beze"
match plain Chambertin), and a name that does not resolve exactly fails
closed to the alias queue. On the real rows three of four resolve; Comte
Liger-Belair's Wine-Searcher winery name differs from the register's.

## Result under today's rules

No row sets Floor: three lack a bottle size, one (La Romanée) a vintage. All
four are stored with their reasons and raw data (`offersCount` kept); their
merchants are created unapproved (decision 0048).

## Open

1. **Bottle size.** Not in the output; prices are per-75cl equivalents.
2. **Duty status.** Not in the output; Floor requires UK In Bond (invariant 5).
3. **Multi-bottle listings.** Only a divided, rounded per-bottle figure exists.
