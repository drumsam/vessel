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

## Resolved, 1 November 2026 (Doug)

1. **Bottle size** is recorded as 750ml only when the row's Wine-Searcher URL
   states it through its own `Xbottle_size` filter (`750`/`750ml`/`75cl`) —
   never because MrBridge normalised a price to 75cl. The value spellings are
   unconfirmed against a live filtered URL, so the rule fails closed: any
   other URL leaves the size unknown.
2. **Duty status** stays unknown, so the locked Floor rules keep this source
   out of Floor. Instead Pocket's MARKET row carries a quiet secondary line —
   `Wine-Searcher GBP 1,695 /btl · 6 offers · bond status not stated` — from
   the latest fresh (`MAX_OFFER_AGE_DAYS`) observation for exactly the line's
   wine, vintage and bottle size. It never sets Floor, never drives "% below
   market", never gates. Merchant approval controls Floor, not visibility, so
   the line shows from an unapproved merchant too.
3. **Multi-bottle listings** travel as a per-bottle EQUIVALENT (kind
   `BOTTLE_EQUIVALENT`, stored as an `INDICATION`, which the core's KIND
   screen keeps out of Floor whatever else is ever known), labelled
   "per-bottle equivalent of a 6-btl listing". Never multiplied back.
4. **Comte Liger-Belair**: Wine-Searcher's "Domaine du Comte Liger-Belair" is
   mapped to the register's producer in the converter, so every Liger-Belair
   wine resolves without dozens of per-wine aliases (a producer-only register
   alias is refused for a multi-wine producer, invariant 13). The canonical
   name is unchanged.

## Importer change (decision 0048)

A feed capture now claims coverage of its wine only when it carries an In
Bond ask — something that could set Floor. Otherwise a duty-unknown
Wine-Searcher row whose cheapest merchant is one we also collect directly
(Farr) would supersede that merchant's own In Bond price for the wine and
lift the Floor. Such rows are still stored and still feed the steer line.

## Revised, 1 November 2026 (Doug): no manual URL filtering

Requiring size-filtered Wine-Searcher URLs put manual work back into the
workflow. For the **steer line only**, MrBridge's normalised per-75cl figure
is now used whenever the wine and vintage resolve exactly and the row's
status is ok:

- **A real listing** (`CURRENT_LISTING` → an `offer`, shown `/btl`) only when
  the URL itself confirms 750ml AND the listing is one bottle.
- **Everything else is a 75cl EQUIVALENT** (`EQUIVALENT_75CL`), shown
  `/75cl eq`: stored as a retained reject (`EQUIVALENT_ONLY`) carrying its
  resolved wine and vintage, its acquisition source, and the full raw row
  (`bottlesPerUnit` included). It is never an offer, so the core never reads
  it: it cannot set Floor, drive "% below market" or touch a gate, and no
  bottle size is ever recorded for it — it is not evidence the listing was
  750ml. This replaces the earlier `BOTTLE_EQUIVALENT`-as-`INDICATION`
  route, which the core's indication check (no duty screen) would have shown
  as a 750ml indication on a loose-bottle line.

On Doug's real four-row export this gives `/75cl eq` steers for Rousseau
Chambertin 2023, DRC La Tâche 1996 and Leroy Clos de Vougeot 2001 (the last
"from a 6-btl listing"); La Romanée gives none until a vintage is present.
