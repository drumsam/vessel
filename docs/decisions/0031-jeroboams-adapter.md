# 0031 — Jeroboams adapter

**Status:** accepted, 16 October 2026. The tenth verified adapter. Third of
the three houses Doug asked to be investigated for UK breadth (0023 was
Justerini & Brooks, 0030 Berry Bros. & Rudd). Follows "Adding a merchant
adapter" (`CLAUDE.md`): official feed > plain HTTP > Playwright, a real
fixture, `fetch()`/`normalise()`, a regression test per trap, registered in
a migration.

## Investigated live, not assumed — both conditions Doug named, before building

`robots.txt`: `Allow: /` with ordinary path disallows (cart, checkout,
account, wishlist, `/graphql`), explicit `Allow:` carve-outs for query
strings on faceted/paginated listing routes, and a blanket `Disallow: /*?*`
for everything else that isn't carved out — no `Crawl-delay`, no
`Visit-time`. `/about-us/terms-and-conditions-of-sale` was fetched and read
in full (52KB of real text, not an empty shell) and searched for "robot",
"scrape", "crawl", "automat", "bot", "spider", "data mining" — none present.
Both conditions Doug's instruction required before building this one
("check robots.txt and terms BEFORE building — if either forbids automated
collection, a verbal permission does not override a published prohibition")
are satisfied. `/graphql` is disallowed and is not touched, even though it
almost certainly carries richer data than the rendered pages.

## Plain JSON this time, not a JS expression to evaluate

A product page is server-rendered Next.js, same framework family as
Justerini & Brooks, but the real data sits in `<script id="__NEXT_DATA__">`
as standard JSON — `json.loads`, no Node subprocess, unlike Berry Bros. &
Rudd's `window.__NUXT__`. `extract_product()` reads
`props.pageProps.initialProduct` and `props.pageProps.initialUniqueItems`.

## Two page shapes for the same catalogue, and duty status read from the data, never the URL

An In Bond listing (`attribute_set_id: 11`, "ib-" URL prefix) is a
configurable product: `initialUniqueItems` carries a USELESS zero-price
"-MAIN" placeholder (`case_size`/`bottle_size`/`volume` all null — it fails
the SIZE screen on its own, no special-casing needed) alongside one or more
REAL priced variants. A duty-paid retail listing (`attribute_set_id: 10`, no
"ib-" prefix) is a plain simple product — a flat price straight on
`initialProduct`, no `"-MAIN"` split. Both shapes can carry an
`initialUniqueItems` entry, and the reliable signal between them is the
`sku` itself: `...IB` (optionally followed by a UUID, confirmed live on a
second, independently-listed stock lot of the identical commercial unit) is
In Bond; a bare numeric `sku` is duty paid. Confirmed live: the SAME wine
(Krug Grande Cuvée 173ème Édition) is published as both an "ib-" page and a
separate, non-"ib-" retail page — fetching the wrong one by mistake still
comes out right, because `normalise()` never reads the URL for duty status,
only the `sku` suffix. `test_duty_status_is_read_from_the_sku_suffix_never_
the_url_prefix` asserts this directly.

## The actual find: a real loose bottle, back vintage, In Bond

`ib-2012-henri-giraud-argonne-rose-...0100750` lists `case_size: "1 x
Bottle"`, a single 750ml bottle, In Bond, £1,531 — not a case divided down,
a genuinely quoted single-bottle price. Every UK merchant adapter built so
far for this project — Farr, Goedhuis, Lea & Sandeman, Bordeaux Index,
FINE+RARE, Lay & Wheeler Trading, Justerini & Brooks, Berry Bros. & Rudd —
sells this cellar's back-vintage Champagne almost exclusively by the case
(`docs/research/uk-trade-current-releases-vs-back-vintage-cellars.md`).
Jeroboams' own catalogue is the first source that reliably does not. This
is the reason the adapter was worth building, not an incidental find among
many.

## A real float-noise price, caught centrally, not here

A duty-paid listing's own flat price is sometimes `204.999996` or
`45.948001` — float noise, not a price anyone printed, the exact same shape
as Farr's own float32 defect `whole_pence()` was built for. This adapter
does not special-case it: the Decimal is passed through unchanged, and
`app.worker.jobs`'s own ingest path already calls `whole_pence()` on every
adapter's output and refuses `NOT_WHOLE_PENCE` centrally.

## Name order is unreliable either way — the same lesson as Justerini & Brooks, independently re-confirmed

`name` sometimes leads with the producer ("2012 Henri Giraud, Argonne Rose")
and sometimes with the cuvée ("2002 Vintage Brut, Champagne Krug"; "N.V.
Grande Cuvee 173eme Edition, Champagne Krug") — confirmed live across
producers in the fixture, no pattern reliable enough to assume either way,
independently of J&B's own `familyName` finding (decision pending for J&B)
on a completely different merchant. `parse_cuvee()` checks both comma
segments against the product's own clean `producer` field (read from
`item_attribute`, with a fallback to the top-level `producer` field and a
vintage parsed from `name`'s own leading token for the plain duty-paid
shape, which carries neither `item_attribute` nor a readable vintage label
at all) and keeps whichever segment does not match; neither matching keeps
the whole string rather than inventing a split.

## A named mixed lot, not an inferred one

`ib-2008-krug-soloist-orchestra-assortment-case-...` bundles several
distinct Krug single-vineyard cuvées under one SKU. Nothing in the data
(`mixed_products`, `case_only`) flags this structurally — both are null on
every record checked, this one included. The name itself does:
`lw_trading.py`'s own `mixed`/`assort(ment)` regex catches it here too,
unchanged, confirming the pattern generalises rather than being a
LW-Trading-specific heuristic.

## No per-producer search endpoint — the sitemap is the merchant's own index

Unlike Bordeaux Index, FINE+RARE or Lay & Wheeler Trading, Jeroboams
publishes no endpoint that answers a producer term. What it publishes is a
static, complete `product-sitemap*.xml` naming every product by a slug that
already contains the producer's name as readable text. `product_paths` is
resolved from that sitemap once, outside this adapter — the same discipline
Justerini & Brooks' own `producer_paths` already established (decision
0011: search keys come from the merchant's own index, never guessed) — and
`fetch()` takes the resolved list directly, with no `search_keys()` method
on the adapter itself, matching J&B's own precedent exactly.

## What this is not

No change to `app/core/`. No Playwright, no Node subprocess — this page's
own `__NEXT_DATA__` is plain JSON. No attempt to reach `/graphql`, disallowed
and left untouched even though it likely holds richer data. No special
handling for `en_primeur` — every record checked carried `null`, and this
cellar holds no En Primeur futures to need it; built when a real one is
found, not before.

## Consequences

- `app/adapters/jeroboams.py` (new): `extract_product()` (the thin,
  untested-by-name JSON shim, same convention as every other adapter's own
  `extract_cards`/`extract_hits`), `parse_bottle_volume()`,
  `parse_case_size()`, `parse_vintage_label()`,
  `producer_and_vintage_label()`, `parse_cuvee()`, `fetch()`, `normalise()`.
- `app/worker/jobs.py`: registered in `TARGETED` as `"jeroboams"` via a new
  `_by_product_paths` call helper (the shared `(adapter, params, vintage)`
  shape does not fit a plain list of exact product paths any existing
  helper already handles; `vintage` is accepted and ignored, since each
  path already names one exact product).
- Migration `0025_jeroboams`: registers the new merchant id (data only — no
  schema.sql change).
- `tests/fixtures/jeroboams-2026-10-16.json`: real, captured
  `initialUniqueItems` entries from six product pages — every price, sku
  and listing id is a real Jeroboams listing read live, not constructed.
- Tests: `tests/test_jeroboams.py` — 17 tests against the real fixture and
  one hand-built edge case (no producer).
- Live collection against this merchant needs no visit-window wait (none
  stated) — the next live sweep can include it immediately.
