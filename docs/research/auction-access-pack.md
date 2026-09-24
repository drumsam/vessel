# Auction access pack — Bonhams, Christie's, Heritage

24 September 2026. Doug: "Go after Bonhams, Christie's, Heritage, any auction we
see results."

**Nothing here has been sent.** Doug sends. Fill the `[brackets]` first.

## What we are asking for, in every case

The same six facts per lot, and nothing else:

> wine · vintage · bottle size · number of bottles in the lot · sale date ·
> hammer price (and the buyer's premium rate applied)

Not catalogue descriptions, not photographs, not condition prose — those are the
houses' copyright and we do not want them. Facts about what sold for how much,
with a link back to the lot page as the source of each record, for internal
pricing only, never republished.

Ask in this order, because that is the order of likely success:

1. **Bonhams** — its Conditions of Website Use carry no anti-automation clause,
   scope copyright to descriptions and photographs, and name an address for
   exactly this kind of request. The easiest ask in the set.
2. **Christie's** — UK, and we could not find their website terms at all, so we
   are asking rather than assuming. A trader with parcels to consign is a
   counterparty they want.
3. **Heritage** — their Website Use Agreement prohibits automated collection and
   restricts the site to personal use, so a licence or a feed is the *only*
   route. Worth asking; expect a commercial answer.

If a house says no, that is the end of it for that house: no workaround, no
scraping, no third-party mirror.

## The route that needs nobody's permission

While these sit in inboxes, the operator-entered evidence form is live (spec in
`auction-evidence-form-spec.md`). A person reading a public results page and
typing in six facts with the source URL is ordinary use of a public page, at any
house. For a thin line that is one or two lookups. Bonhams is already on the
allowed-house list; Christie's and Heritage go on it when their answers arrive.

---

## 1 · Bonhams

**To:** webmaster@bonhams.com
**Subject:** Request — use of factual wine auction results

Dear Bonhams,

Your Conditions of Website Use ask that requests to use material beyond the
permitted scope come to this address, so I am asking properly.

I run [company], a UK fine wine trader. We are building an internal pricing tool
that checks our own buying and selling against the market. We would like to
record factual results from your wine sales — wine, vintage, bottle size, lot
size, sale date, hammer price and the premium rate — as a cross-check.

We would not reproduce catalogue descriptions or photographs, would not publish
the data, and would link to the lot page as the source of every record.

Is that acceptable, and is there a preferred way to receive results — a feed, an
export, or a data licence? We would rather ask first.

We also buy and consign, and would be glad to discuss that separately.

Kind regards,
Doug [surname] · [company] · [phone]

---

## 2 · Christie's

**To:** Christie's Wine & Spirits, London
**Subject:** Wine results data, and consignment

Hello,

I run [company], a UK fine wine trader with Burgundy and Bordeaux parcels that
could suit your London and online sales, and I would welcome a conversation about
consigning.

Separately: we check our own pricing against auction outcomes. Is there a way for
a trade counterparty to access factual wine results — wine, vintage, bottle size,
lot size, sale date and hammer price — for internal use? I could not find your
website terms of use to check what you permit, so I am asking rather than
guessing. We have no interest in catalogue text or images.

Kind regards,
Doug [surname] · [company] · [phone]

---

## 3 · Heritage Auctions

**To:** Heritage Auctions, Wine department / data licensing
**Subject:** Licensing factual wine auction results

Hello,

I run [company], a UK fine wine trader. Your wine results archive is the
best-structured one we have seen, and your Website Use Agreement makes clear that
automated collection is not permitted — so this is a licensing question rather
than a technical one.

Is there a data licence, feed or export that would let us use factual results —
wine, vintage, bottle size, lot size, sale date, hammer price and premium rate —
inside our own internal pricing tool? Not republished, not resold, sourced back
to the lot page.

If there is a fee, I would be glad to hear it.

Kind regards,
Doug [surname] · [company] · [phone]

---

## 4 · The paid alternatives, if the houses say no

- **Wine Market Journal** — auction results across houses, sold as a subscription.
- **Wine-Searcher Pro** — auction and merchant pricing together.
- **iDealwine's estimate service** — their own results, licensed.
- **Liv-ex** — not auction, but live UK trade bids, offers and trades, which is
  closer to what the benchmark actually asks.

This data is a paid product across the industry *because* the houses restrict
direct reuse. Buying it is the normal route, not a consolation prize.

## When a house says yes

It becomes a source like any merchant: terms recorded in the adapter docstring,
a fixture captured, hammer and premium stored as separate explicit fields, mixed
lots and condition-annotated lots quarantined, and the house added to the closed
list in the auction evidence table. Auction remains a health check — it never
sets a UK Reference — unless Doug decides otherwise for NO_MARKET lines, which is
a separate decision with its own record.
