# Adapter spec pack — five merchants

For Claude Code. Written 21 September 2026 from live investigation in the Cowork
session. Each section gives the route, the field mapping, every trap seen on live
data, and the regression tests to write **before** the adapter is called done.

Standing rules that apply to all five:

- `fetch()` is network only; `normalise()` is pure. Capture a real response into
  `tests/fixtures/` first.
- **Terms before extraction.** Read the website-use terms and `robots.txt` at
  build time and record the verdict in the adapter docstring. `robots.txt` is not
  a licence.
- Honest identifiable User-Agent with contact URL; parse `robots.txt` at runtime;
  honour `Crawl-delay`; never follow `/*blackhole` paths.
- Nothing here touches `app/core/`. If an adapter seems to need a core change,
  stop and raise it.
- Every rejection is emitted as `Rejected(reason=...)`, never dropped.

Build order recommendation: **Lea & Sandeman → Lay & Wheeler Trading → Albany →
Vinum → Fine + Rare**. The first two are verified end to end against live data this
week; Albany and Vinum need their feeds re-opened and confirmed (see each section);
Fine + Rare produces corroboration, not comps.

---

## 1. Lea & Sandeman — `lea_sandeman.py`

**Verdict:** terms page is conditions of sale only, no website-use restriction.
`robots.txt` disallows `/*page=*` and `/*term=*`, explicitly allows `/*?category=*`.
Note: the earlier collector brief listed L&S among merchants with an
anti-automation position; the 20 Sept read of terms + robots found none. Re-read
robots user-agent groups at build time and record which group our UA falls in.

**Route:** `GET https://www.leaandsandeman.co.uk/fine-wine.html?resultsPerPage=192`
One request, whole list (174 rows on 20 Sept), server-rendered HTML table.
**Never** add `page=` — the site's own "show 192" control does, and that pattern is
disallowed. **Never** collect product pages (duty-paid retail per bottle — see traps).

**Row shape (13 cells, 12 headers):**

| idx | content | maps to |
|---|---|---|
| 0 | Region | `raw.region` (also needed for Jero) |
| 1 | Colour | `raw.colour` |
| 2 | Vintage | `vintage` (int; reject NV/ranges unless NV → 1000) |
| 3 | Wine (UPPERCASE appellation + climat + producer) | `raw_title`; producer/cuvée split is the resolver's job |
| 4 | **unlabelled stock code** | `raw.stock_code` (offer id) |
| 5 | Pack | `pack_size`, `bottle_ml` |
| 6 | Qty | `offered_units` |
| 7 | Price (ex VAT) | `price` (Decimal) |
| 8 | inc VAT | ignore (keep in raw) |
| 9 | IB/DP | `duty_status` |
| 10 | Rating | raw |
| 11–12 | Qty input / Buy | ignore |

`stock_type=MERCHANT_STOCK`, `stock_type_basis="inferred"`, `price_kind=ASK`,
`currency=GBP`, `is_buyable=True` when the ADD control is present.

**Pack parsing:** `N x 75cl`, `N x 37.5cl`, `N x Mags` (1500), `N x DM` (3000),
`N x Neb` (15000? — **reject until confirmed**; L&S uses Neb for Nebuchadnezzar
15000ml but confirm on a live row), `N x Jero` — **3000ml if Region is Burgundy or
Champagne, 4500ml if Bordeaux; reject if region missing or other**.

**Traps → tests (house style):**

1. `test_lea_sandeman_maps_price_by_row_position_not_header` — 13 cells vs 12
   headers; header mapping reads `inc VAT` as price. 2021 Henri Germain Morgeot
   6×75 IB (stock code 44599): £435.00 ex VAT; the header-shifted read gives
   £542.74 (+24.8%).
2. `test_lea_sandeman_duty_status_is_per_row` — Volnay 1er Roncerets 2020 6×75
   appears twice: **DP £502.91, IB £485.00**. Only the IB row may emit an IB offer.
3. `test_lea_sandeman_jeroboam_depends_on_region` — Burgundy Jero = 3000ml;
   Bordeaux Jero = 4500ml; no region → Rejected.
4. `test_lea_sandeman_product_page_is_never_collected` — fixture a product page;
   `normalise()` must refuse it. £675.00/6×75 IB on list vs £68.95/btl DP on
   product page for the same wine.
5. `test_lea_sandeman_duplicate_rows_are_one_listing` — 2021 Germain Morgeot 6×75
   appears twice, identical (stock code 44599). Dedupe on stock code.
6. `test_lea_sandeman_mazoyeres_labelled_as_charmes_goes_to_review` — "CHARMES
   CHAMBERTIN 'Aux Mazoyères' Grand Cru Virgile Lignier-Michelot" must not
   auto-resolve to either Charmes or Mazoyères; resolver → NAME_REVIEW.
7. `test_lea_sandeman_courcel_grand_clos_is_not_les_grands_epenots` (resolver) —
   see control-set report.

---

## 2. Lay & Wheeler Trading — `lw_trading.py`

**Verdict:** separate estate from `laywheeler.com` (which blocks us and must not be
touched). `robots.txt`: `Crawl-delay: 10`, names Scrapy / node-fetch /
FirecrawlAgent as blocked, defines `/*blackhole` traps. Our UA is none of those.

**Route:** WooCommerce Store API
`GET https://laywheelertrading.com/wp-json/wc/store/v1/products?search=<producer>&per_page=100&page=<n>`
Deep search by producer term. 10s between requests.

**Mapping:**

- `name` → `raw_title` (e.g. "2015 Domaine des Lambrays, Clos des Lambrays Grand Cru 6x75cl")
- `prices.price` → **minor units**: `Decimal(price) / 10**prices.currency_minor_unit`;
  assert `prices.currency_code == "GBP"`.
- `attributes[]` → read by **name**, not position: `Duty Status`, `Availability`,
  pack/size, vintage. `duty_status` from `Duty Status` only.
- `Availability`: `Immediate` → `stock_type_basis="inferred"`; `Future Arrival` →
  keep as buyable ASK but record in `raw.availability` (operator context).
- `is_in_stock` / `is_purchasable` → `is_buyable` (both must be true).
- `sku` → `raw.sku` only.

**Traps → tests:**

1. `test_lw_trading_price_is_minor_units` — `"141400"` with minor unit 2 is
   £1,414.00; reading it as pounds is a 100× error.
2. `test_lw_trading_paginates_past_100` — Faiveley and Drouhin both returned
   exactly 100 on page 1. Fetch until a page returns < per_page; a fixture with
   `X-WP-TotalPages: 2` must yield both pages' rows.
3. `test_lw_trading_two_sku_schemes_identity_from_attributes` —
   `LXSIB104029020150600750` (LWIN7+vintage+pack+size) and
   `hub-VS10135589-6-IB-13287647`. Identity and format come from attributes; SKU
   is never parsed for pricing fields. An LWIN found in the SKU is a *proposal*
   to the resolver and never resolves alone.
4. `test_lw_trading_courcel_les_grands_epenots_rejected_for_grand_clos` — 2019
   Courcel "Les Grands Epenots" 6×75 must not match a Grand Clos des Épenots line.
5. `test_lw_trading_coeur_du_roy_tres_vieilles_vignes_goes_to_review` — Dugat-Py
   2020 "Coeur du Roy Très Vieilles Vignes" £765 vs seller "Coeur de Roy":
   NAME_REVIEW, not auto-approved.

---

## 3. Albany Vintners — `albany.py`

**Verdict (3 Sept, re-verify):** `robots.txt` explicitly **allows** `/api/ai/`
with a comment pointing crawlers to it. Sanctioned feed.

**Route:** poll `https://www.albanyvintners.com/api/ai/index.json` for
`lastUpdated`; fetch `.../api/ai/wines.json` only on change (~1,263 wines).

**Mapping:** `price_gbp_per_case` → `price` for `pack_size` × `bottle_ml`;
**assert `price_basis == "in_bond_gbp_per_case"`** — any other value → Rejected
(DUTY or UNKNOWN basis, never assumed). `stock_band` low/medium/high →
`offered_units=None`, band in `raw`. `availability` → `is_buyable`.
`lwin7`/`lwin11` → resolver proposals only. `stock_type_basis="inferred"`.

**Traps → tests:**

1. `test_albany_rejects_unknown_price_basis` — mutate fixture basis to
   `"duty_paid_gbp_per_bottle"`; expect Rejected.
2. `test_albany_price_is_per_case_not_per_bottle` — a 6×75 at £1,200 stays £1,200
   for a 6×75 line and is UNIT-rejected against 1×75.
3. `test_albany_banded_stock_is_not_a_quantity` — `stock_band: "low"` →
   `offered_units is None`.

**Not yet done this week:** the Albany feed could not be re-opened overnight (the
cloud proxy refuses the host and the browser pane needs Doug's site approval).
First job: capture a fresh fixture and confirm the field list is unchanged.

---

## 4. Vinum Fine Wines — `vinum.py`

**Verdict:** main site robots names a blocklist (incl. Scrapy) and
`Crawl-delay: 10`, and the collector brief records an anti-automation position.
The merchant publishes its own stock export on a separate host — collect **that**
file only; do not crawl `vinumfinewines.com`. Better still: ask Vinum for the
trade feed (draft in the outreach pack).

**Route:** `GET https://extranet.hub.wine/xlsx/vinum` (also `/html/vinum`),
~2,392 products. Once per day.

**Columns:** `Country | Region | Vintage | Name | Type | Pack | Avail. | Qty | Price | Score`

**Mapping:** `Pack` → pack/ml (`6x75cl`); `Qty` → `offered_units` (exact);
`Avail.` Immediate / Future Arrival → raw; `Price` → `price` **with
`duty_status=UNKNOWN` until confirmed** — the column is unlabelled. `UNKNOWN`
is rejected by the core (`Reject.DUTY`), so the adapter is safe to ship before
confirmation: it contributes nothing until Vinum confirms the basis in writing
or a live page cross-check is committed as a fixture.

**Traps → tests:**

1. `test_vinum_unlabelled_price_is_duty_unknown` — every row → `DutyStatus.UNKNOWN`
   until a config flag `VINUM_PRICE_BASIS_CONFIRMED=IB` is set with a decision
   record reference.
2. `test_vinum_pack_string_parsing` — `6x75cl`, `12x75cl`, `1x150cl`, `3x150cl`.
3. `test_vinum_is_one_of_three_uk_vinums` — merchant registered as Vinum Fine
   Wines Ltd, `vinumfinewines.com`; name-only matches to other "Vinum" firms are
   refused at registration.

---

## 5. Fine + Rare — `fine_rare.py` (INDICATION only)

**Verdict (20 Sept):** terms are conditions of sale only; `robots.txt` disallows
`/golive`, `/search`, `/login`, `/register`, `/cart`, `/checkout` and **names
Anthropic's crawler as allowed**. Sitemap published.

**Decision (Doug, 20 Sept):** F+R is pure brokerage across European merchants.
A price there does not show stock exists. It is a steer, not a comp.

**Route:** `/sitemap-producers.xml` (19,655 producers) → product URLs from
`/sitemap-products-{1..9}.xml` filtered by slug `<vintage>-<cuvée>-<producer>`
→ `GET /product/<id>/<slug>`, parse the `__NEXT_DATA__` JSON. No browser.

**Mapping:** `unitPrice` → `price`; `productMarketInfo.unit/unitSize` → must be
`cl` / `75` for a bottle price; `listingCount`, `merchantCount` → raw.
**`price_kind = PriceKind.INDICATION`** for every row. Add the enum member if the
repo does not have it; the existing `Reject.KIND` screen already excludes it from
the benchmark, so no core logic changes. Surface as a corroboration column.

**Traps → tests:**

1. `test_fine_rare_is_never_a_comp` — an F+R row with a lower price than any
   merchant must not change Floor/Reference/Median; it appears in rejections as
   `KIND`.
2. `test_fine_rare_quantity_zero_is_not_parsed_as_stock` — every variant carries
   `quantity: 0` with `listingCount > 0`; no quantity is inferred.
3. `test_fine_rare_assortment_is_mixed_lot` — slugs containing `assort` /
   `assortment` → `is_mixed_lot=True`
   (e.g. `2012-assortment-case-3xruchottes-3xmazy-6xgevrey-chambertin`).
4. `test_fine_rare_duplicate_catalogue_entries` — 2013 Ruchottes Clos des
   Ruchottes appears under three ids and three name forms; the resolver must map
   all three to one wine and the adapter must emit them as one merchant.

---

## Also for the Bordeaux Index adapter (existing)

From the control-set run, two changes to `fetch()` and one test each:

1. `test_bordeaux_index_404_on_known_slug_is_empty` — `/fine-wine/all?producer=domaine_des_lambrays&vintage=1990`
   returns 404. Validate slugs against `/filters.xml`; a 404 for a known slug is
   zero rows; a 404 for an unknown slug is an error.
2. `test_bordeaux_index_producer_has_multiple_slugs` — Clerget, Dugat-Py,
   Faiveley (×3), Stéphane Magnien, Maume each have more than one slug; deep search
   unions them.
