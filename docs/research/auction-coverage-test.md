# Would auction data fill the coverage gap? — a measured test

24 September 2026. Doug's challenge: "If you were scraping data from auction
houses this wouldn't be happening." Worth testing rather than arguing, so I
tested it.

## Method

Twelve of the 62 control-set lines that came back NO_MARKET, chosen to span the
list: cheap young whites, mid-priced village reds, premiers crus, grands crus,
and the one mature wine on the list. For each, a public web search for that exact
wine and vintage appearing as an auction lot — any house, any country, any
platform. Search results only: no auction site was crawled, and the five houses
whose terms forbid this use were not fetched.

Then the same search for two wines from the earlier collector-tier proof set, as
a control.

## Result: 2 clear hits out of 12

| Line | Wine | Vintage | Found at auction? |
|---|---|---|---|
| L01 | Barraud Pouilly-Fuissé Les Crays | 2022 | No — iDealwine holds 2000 and 2016 |
| L06 | Moreau-Naudet Chablis Montmains | 2021 | No |
| L11 | Joseph Colin Saint-Aubin Compendium | 2021 | No |
| L38 | Dugat-Py Gevrey Lavaux Saint-Jacques | 2019 | No |
| L17 | Anne Gros Chambolle Combe d'Orveau | 2020 | **Yes** — iDealwine, 3 bottles |
| L43 | Mugneret-Gibourg Vosne-Romanée | 2019 | No — WineBid holds 2004, 2005, 2018 mag; another house 2013 |
| L47 | Lignier-Michelot Morey Faconnières | 2019 | No |
| L53 | Domaine des Lambrays Morey Les Loups | 2018 | **Yes** — iDealwine, 3 bottles |
| L57 | Hubert Lamy Saint-Aubin Clos de la Chatenière | 2018 | Partial — an iDealwine price-estimate page exists, implying past sales |
| L59 | Raquillet Mercurey Les Naugues | 2018 | No — WineBid holds 2013 |
| L23 | Joseph Drouhin Puligny-Montrachet | 2020 | No |
| L70 | Maume Mazis-Chambertin | 2011 | No — iDealwine holds 1994, 1999, 2003; WineBid 2005 |

**Two clear, one partial, nine nothing.** And the pattern inside the misses is
consistent: the *producer* is often at auction, but in older vintages. Auction
sells what has been in someone's cellar for a decade, not what a merchant is
releasing this year.

## The control: collector tier is a different world

| Wine | Vintage | Found |
|---|---|---|
| Armand Rousseau Chambertin | 2000, 2010 | **Bonhams**, named lots (twelve bottles, six bottles) |
| Armand Rousseau Charmes-Chambertin | 2011 | **Unicorn Auctions**, 3 bottles |
| Comte Georges de Vogüé Musigny VV | 1993 | **Sotheby's**, 3 magnums |
| Armand Rousseau (various) | — | iDealwine, HDH published results |

Two searches, four named houses, immediate hits — including Bonhams, whose terms
permit factual use and which is UK-based.

## What this means

**Doug is right, for the half of the business he was probably thinking about.**
The Rousseau / de Vogüé / Mugnier proof came back READY 0, REVIEW 5, NO_MARKET 15
because those wines barely trade through merchants — they trade at auction. For
that tier, auction evidence is not a nice-to-have, it is *the* market, and its
absence is why that run looked so thin.

**And it would not have saved this list.** Young, small-grower, modestly-priced
Burgundy in trade cases does not reach the auction room. At two clear hits in
twelve, auction would take the control set from 8 priced lines to perhaps 10.

**Even the hits would not produce a comparable.** Both are **3-bottle lots on a
French platform**, sold duty-paid in France. The seller's lines are 6×75 UK In
Bond. Different unit, different market, different tax basis — so under our own
rules they are auction evidence, never a UK Reference. They would inform an
operator; they would not price a line.

**One more thing the searches showed.** A query for Dugat-Py's Lavaux
Saint-Jacques returned **Claude Dugat's** Lavaux Saint-Jacques at the top —
a different producer, similar name, very different price. That is the identity
trap the resolver exists for, appearing unprompted in the first page of results.
Any auction ingestion would meet it constantly, because auction catalogues
abbreviate producer names far more aggressively than merchant lists do.

## Recommendation

Split the problem, because it is two problems:

1. **Collector tier** — pursue auction evidence properly. Bonhams first, since
   its terms permit factual results and its own terms name the address to ask
   (draft ready, unsent). Then a licensed source: Wine Market Journal or
   Wine-Searcher's auction data, which exists precisely because the houses
   restrict direct reuse.
2. **Trade parcels like this one** — auction will not help. Coverage has to come
   from merchants: Corney & Barrow, Justerini & Brooks, Berry Bros, Lay & Wheeler
   retail, and above all Liv-ex, which shows who holds what in the UK In Bond
   market the benchmark actually asks about.

And measure Bordeaux before drawing conclusions about the business: this test,
and the control set behind it, are both from the most fragmented region in the
wine trade.

## Sources

- [Bonhams — Chambertin 2000, Domaine Armand Rousseau (12)](https://www.bonhams.com/auction/27501/lot/289/chambertin-2000-domaine-armand-rousseau-12/)
- [Bonhams — Chambertin 2010, Domaine Armand Rousseau (6)](https://www.bonhams.com/auctions/23373/lot/946/)
- [Sotheby's — Musigny Vieilles Vignes 1993, Comte Georges de Vogüé (3 mag)](https://www.sothebys.com/en/buy/auction/2026/finest-rarest-wines/musigny-cuvee-vieilles-vignes-1993-comte-georges)
- [Unicorn Auctions — Armand Rousseau Charmes-Chambertin 2011 (3 bottles)](https://www.unicornauctions.com/auction/7073836c-02e4-49f4-839d-5dd89bd28971/lot/73de5f4d-e6d6-40f8-8f88-9eb7e622cf0a)
- [iDealwine — Anne Gros Combe d'Orveau 2020 (3 bottles)](https://www.idealwine.com/en/buy-a-wine/B2249166-4301-3-bottles-Chambolle-Musigny-La-Combe-dOrveau-Anne-Gros-2020-Red)
- [iDealwine — Lambrays Les Loups 2018 (3 bottles)](https://www.idealwine.com/en/buy-a-wine/B2265342-4009-3-bottles-Morey-Saint-Denis-1er-Cru-Les-Loups-Domaine-des-Lambrays-2018-Red)
- [iDealwine — Hubert Lamy Clos de la Chatenière 2018 price estimate](https://www.idealwine.com/en/wine-prices/122405-2018-Bottle-Burgundy-Saint-Aubin-Premier-Cru-Clos-de-la-Chateniere-Vieilles-Vignes-Hubert-Lamy-white)
- [WineBid — Mugneret-Gibourg Vosne-Romanée 2018 magnum](https://www.winebid.com/BuyWine/Item/Auction/1424533/2018-Domaine-Georges-Mugneret-Mugneret-Gibourg-Vos~)
- [WineBid — François Raquillet Mercurey Les Naugues 2013](https://www.winebid.com/BuyWine/Item/Auction/1188828/-)
