# 0030 — Berry Bros. & Rudd adapter

**Status:** accepted, 11 October 2026. The eighth verified adapter. Second of
the three houses Doug asked to be investigated for UK breadth, one at a time
(decision 0023 was the first). Follows "Adding a merchant adapter"
(`CLAUDE.md`): official feed > plain HTTP > Playwright, a real fixture,
`fetch()`/`normalise()`, a regression test per trap, registered in a
migration.

## Permission

Doug knows the team and told the collector fetching pricing is fine,
additive to — never a substitute for — what the site's own robots.txt
already allows. *Contact name: TODO — ask Doug for the person's name at BBR
before the first live collection run, and record it here.*

## Investigated live, not assumed

`robots.txt`: `Allow: /` with a handful of path disallows (cart, checkout,
my-account, search), `Crawl-delay: 10`, and the first `Visit-time:
0200-0700` (UTC) directive seen anywhere in this fleet — `app/worker/
politeness.py` already reads it (built investigating this merchant, before
this adapter existed) and `check_robots()` refuses a fetch outside the
window. This adapter does not loosen that: Doug's permission is additive
comfort, never an override, and the window is enforced unchanged. The
terms page was checked for an anti-automation clause; none was found.

Twelve real producer pages were captured and read by hand before writing a
line of adapter code (`producer-<id>-<slug>`, ids and slugs read from the
merchant's own `sitemap-category.xml`, never guessed — a differently-
numbered `producer-3506-charles-heidsieck` also resolves but returns
`nbHits: 19912`, an unfiltered or mis-filtered catalogue, and is kept only
as a committed negative example, never used for real collection).

## The real price is not in the HTML, and not in the page's own JSON-LD either

A product page's `<script type="application/ld+json">` `ProductGroup` block
shows `lowPrice: 0, highPrice: 0, offerCount: 0` on every page checked — a
stale placeholder. The real data is `window.__NUXT__=...`, a minified
devalue-style JS expression, not JSON: it has to be evaluated, not parsed.
`extract_hits()` locates the assignment, bounds it at the closing
`</script>`, and evaluates it in a throwaway Node subprocess behind a bare
`global.window = {}` shim — the first adapter in this fleet with a non-
Python runtime dependency, flagged to Doug before building further; he did
not object. Nothing else about the adapter touches Node: `fetch()` stays
network-only, `normalise()` stays pure, same contract as every other
adapter.

## One producer page, every edition currently offered — with a hard ceiling

A producer page server-renders only the FIRST page of its own Algolia
results. Confirmed live: Krug's own page returns 24 of `nbHits: 58` — the
24 newest editions, missing exactly the 156th–168th editions this cellar
holds. `?page=1` on the URL does not reach a second page (confirmed: the
server-rendered state is still page 0). `fetch()` raises
`ProducerPageTruncated` rather than return a silently partial page — the
caller cannot narrow a producer page the way a narrower search term
narrows LiveTrade's. Fully covered on page 0, no gap at all: Henri Giraud
(8/8), Eric Rodez (8/8), Taittinger (20/20), Savart (24/24), Charles
Heidsieck (13/13, correct slug only). Not fully covered: Krug (24/58), Dom
Pérignon (24/55), Louis Roederer (24/41), Bollinger (24/59), Pol Roger
(24/41), Pierre Peters (24/32) — incomplete for this merchant until BBR's
own Algolia search-only API key is found (searched for, not located: the
application id `IR8IZWC7D2` is on the page, no API key).

## Each hit's own `purchase_options[]` is the real ladder — the top-level fields are one entry, repeated

A hit's top-level `purchase_mode`/`stock_origin`/`prices`/`case_size`/
`bottle_volume` are only the ONE variant Algolia promoted as that hit's
headline. `purchase_options` is the complete list for the same wine, and
every top-level hit's own fields reappear inside its own `purchase_options`
unchanged (confirmed: zero top-level skus absent from some hit's nested
list, across every page captured). Reading only the top level would miss
real depth: one Taittinger 2013 hit alone carried 8 nested listings,
including a 300cl Jeroboam format never promoted to any top-level hit on
the page at all — 1,118 nested purchase_options read across twelve pages
against 20 top-level hits on the richest single page. `fetch()` reads
`purchase_options` exclusively and dedupes by `bbx_listing_id` (a specific
seller's specific listing) or, for a BBR-direct entry with no listing id,
by `(sku, purchase_mode)` — the same listing is nested, verbatim, inside
every top-level hit for that wine.

## Two stock origins, one merchant — direct and the Rudd's own exchange

`stock_origin` is `"BBR"` (Berry Bros' own held stock) or `"BBX"` (its own
live peer-to-peer exchange, each listing carrying its own
`bbx_listing_id`). Both are Berry Bros. & Rudd publishing its own book two
ways — the same "one company, two surfaces" reading already established
for Bordeaux Index LiveTrade (decisions 0026/0027). Unlike LiveTrade,
there is no second adapter id to reconcile here: BBR and BBX are read by
the same fetch, on the same page, by this one adapter, so there was never
a second `merchant_id` to collapse — `stock_origin` only chooses
`StockType` (`MERCHANT_STOCK` / `MARKETPLACE`), never a separate comp.
`test_bbx_in_bond_is_the_same_merchant_as_bbr_direct_never_a_second_comp`
asserts this directly.

## Price field selection is keyed by purchase_mode, never by case_size

Confirmed across every nested `purchase_option` collected (1,118 records,
zero exceptions): `purchase_mode == "In Bond"` always populates
`price_per_case_exact` — the price for the whole `case_size`-bottle pack,
so `pack_size = case_size`, even when `case_size == 1` (a single Jeroboam
is still "a case of one", confirmed on a real 300cl listing priced at
£990 via the case field, not the bottle field). `purchase_mode ==
"Delivery"` (BBR's duty-paid retail channel) always populates
`price_per_bottle_exact` instead, for ONE bottle regardless of the SKU's
own `case_size` — so `pack_size = 1` for that mode, never `case_size`.
Reading `case_size` instead of `purchase_mode` to choose the price field
would have read a Delivery case six times too cheap.

Every "Delivery" record still becomes a `Candidate`, at
`DutyStatus.DUTY_PAID` — proposed here, rejected by the deterministic
core's hard screen (invariant 5), same discipline `lw_trading.py` already
gives a recognised-but-not-in-bond duty status. This adapter never pre-
filters a duty status itself.

## Producer and cuvée text, read around two merchant inconsistencies

BBR's own `producer` field is sometimes bare ("Krug") and sometimes
prefixed ("Champagne Taittinger") — confirmed live, no pattern by
producer that would let the prefix be assumed either way — so
`parse_cuvee()` strips a leading "Champagne " from both `name` and
`producer` only when actually present, never assumed. BBR appends a
generic ", Brut" to almost every listing's `name`; stripping it blindly
would also strip the real, distinct "Extra Brut" sweetness descriptor
(no leading comma of its own), so only a standalone trailing ", Brut"
clause is removed — `test_cuvee_parsing_does_not_strip_extra_brut_as_
if_it_were_the_generic_suffix` guards this directly. Krug's own edition
numbering ("Grande Cuvée, 173ème Édition") is read by
`app.identity.resolver.split_release_code` (decision 0019), same as every
other adapter; the comma before the edition number is cleaned off the
remaining cuvée text rather than left dangling.

## What this is not

No change to `app/core/`. No Playwright: the Node subprocess reads a
state blob already present in the plain-HTTP response, not a rendered
DOM. No attempt to reach BBR's full catalogue for the six producers whose
page is truncated — `ProducerPageTruncated` is raised and left for the
Algolia key, not worked around with a guess at a second page. No change
to `app/worker/politeness.py` beyond what investigating this merchant
already prompted (recorded separately, ahead of this adapter).

## Consequences

- `app/adapters/berry_bros_rudd.py` (new): `extract_hits()` (the Node
  subprocess shim, untested by name, same convention as every other
  adapter's own thin DOM shim), `parse_bottle_volume()`, `parse_cuvee()`,
  `fetch()`, `normalise()`, `ProducerPageTruncated`.
- `app/worker/jobs.py`: registered in `TARGETED` as `"berry-bros-rudd"`
  via a new `_by_producer_slugs` call helper (the shared
  `(adapter, params, vintage)` shape does not fit a single producer-slug
  sequence any of the existing helpers already handle).
- Migration `0024_berry_bros_rudd`: registers the new merchant id (data
  only — no schema.sql change).
- `tests/fixtures/berry-bros-rudd-2026-10-11.json`: real, captured
  `purchase_options` entries from two producer pages (Taittinger, fully
  covered; Krug, individual real hits read directly despite the page's
  own truncation) — every price, sku and listing id is a real BBR
  listing read live, not constructed.
- Tests: `tests/test_berry_bros_rudd.py` — 18 tests against the real
  fixture and a handful of hand-built edge cases (unrecognised purchase
  mode, unrecognised stock origin, unreadable size, zero price, no
  producer).
- Live collection against this merchant must wait for the 0200–0700 UTC
  visit window; building and testing the adapter code does not.
