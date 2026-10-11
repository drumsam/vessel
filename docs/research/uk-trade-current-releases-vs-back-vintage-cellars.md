# The UK trade publishes current releases in cases; this cellar is back-vintage, loose-bottle

**Status:** finding, 10-11 October 2026, from the Champagne sweep (seven
original adapters, nine-ten October) and the loose-bottle pool audit it
prompted (Justerini & Brooks, eleven October). Not a failure of coverage —
a property of what UK merchants' public pages actually carry, confirmed
independently at four unrelated sources. Doug: "write it up as a research
doc, because it is the thing that justifies everything below" (trade
lists, Liv-ex).

## The cellar

`docs/research/cellar-wfs-normalised.csv`: 84 Champagne lines, 62 distinct
products, mostly 2002-2016, almost entirely single bottles (`pack_size=1`)
rather than original cases. Krug Grande Cuvée alone — editions 156ᵉ
through 169ᵉ, 454 bottles — is the largest single position.

## What four independent sources actually carry, checked against this cellar's own vintages

| Source | Mechanism checked | Single-bottle (1×75cl) rows for THIS cellar's wines, this cellar's vintages |
|---|---|---|
| Farr Vintners | Whole-book JSON feed, one record per stated size | 0 |
| Goedhuis Waddesdon | Shopify catalogue, pack size is in the product title itself | 0 |
| Lea & Sandeman | Whole-book HTML list | 0 — wrote zero Champagne offers for this cellar at all |
| Justerini & Brooks | Server-rendered family pages, both a case pool and a loose pool read separately | 1 of ~30 recovered offers (Dom Pérignon Vintage 2008) |

Bordeaux Index and Bordeaux Index LiveTrade are the exception, and the
reason is informative rather than contradictory: BI's listing and its
LiveTrade marketplace are a live two-sided exchange, not a retail
catalogue — a seller can list a single bottle of a 2008 vintage at any
time because the platform is peer-to-peer, not "what BI chose to stock."
That is a different kind of source from the other four, and it is the one
that already carries most of this sweep's depth (`docs/decisions/0027`).

## The loose-bottle audit that surfaced this

Asked directly: "does each source distinguish loose-bottle stock from
case stock, do our adapters read it, and how much of that distinction is
sitting unread in data we already captured?" Answer, source by source:
six of seven original adapters already separate loose from case
correctly and always have — Farr publishes two separate JSON records for
two pack sizes, Goedhuis puts the pack size in the product title (a
separate Shopify product, not a variant), Lea & Sandeman and LW Trading
read one row/attribute per listing. There was no parsing gap to fix. The
absence in the table above is the market's, not the adapters'.

J&B, investigated afterwards specifically because the audit raised the
question, confirmed the SAME wall from a different angle: of roughly
thirty recovered offers across eleven producers, the vintages on offer
right now are overwhelmingly NOT this cellar's vintages (Taittinger Blanc
de Blancs Comtes de Champagne 2011-2015 against this cellar's 2004-2008;
Pol Roger Sir Winston Churchill 1998/2012/2018 against 2002/2004; Cristal
1999-2018 against 2005-2007). One match, Dom Pérignon 2008, moved a line
to READY. Everywhere else, the wine simply is not the current release.

## What this means for the two routes forward

**Adding more public-facing UK merchants will keep hitting the same
wall.** A retail catalogue site shows what it has decided to stock right
now, and the UK fine wine trade's retail shelf turns over towards current
releases — which is exactly what a catalogue site is built to sell. A
2002-2016 cellar, in loose bottles, is a different shape of inventory
than what these sites are built to show, independent of how many more of
them are added.

Two routes actually address it, in the order Doug set:

1. **Trade lists from Doug's own relationships** (Berry Bros. & Rudd,
   Jeroboams, and whoever else). A trade list is dealer pricing, not a
   retail catalogue — back-vintages a public page never carries, quoted
   per bottle already, with no staleness window because it is a file
   someone sent, not a page that might have moved on. See
   `docs/research/trade-list-import-format.md` for the shape asked for.
2. **Liv-ex.** Prices back-vintages properly, per-bottle-equivalent by
   construction, and is the single reference point this cellar's own
   shape needs rather than a catalogue of what happens to be newly
   released. Scoped, not built: `docs/research/liv-ex-api-scoping.md`.

## What this is not

Not a verdict that public merchant pages are useless — Bordeaux Index's
own two-sided exchange already carries real depth for exactly the reason
a retail catalogue would not (it is not a catalogue), and the regular
listing/search adapters still matter for whatever current-release stock
this cellar does hold. It is a finding about WHICH kind of source answers
THIS cellar's specific shape, not a general claim about UK merchant data.
