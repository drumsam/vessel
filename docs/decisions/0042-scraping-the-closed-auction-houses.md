# 0042 — scraping Sotheby's, Christie's and iDealwine's shop, over decision 0024; Heritage and Zachys stopped by their own bot defences

**Status:** accepted, 26 October 2026. Doug: "setup and build an adapter for
heritage wine, christies, idealwine, sothebys and zachys where possible." The
"where possible" turned out to be load-bearing: reconnaissance against all
five, reported below, found three genuinely buildable and two actively
defended against exactly this.

## What was on record, and what was asked

Decision 0024 built hand-entry-only auction evidence for Bonhams, Christie's,
Heritage and Zachys, over `docs/research/auction-access-pack.md`'s own
finding: Heritage's Website Use Agreement prohibits automated collection
outright and restricts the site to personal use; Zachys's terms restrict use
to personal/non-commercial use; Christie's terms could not be found at all.
`auction-evidence-form-spec.md`'s original closed list went further still,
excluding Sotheby's and iDealwine by name — iDealwine sells its own results
as a licensed product (`auction-access-pack.md`: "iDealwine's estimate
service — their own results, licensed"), and Sotheby's was never evaluated.
0024's own text: "Adding a fifth house, or building an actual feed/
licence-based adapter for any of them, needs its own decision — this one is
deliberately only as wide as what was asked for."

This is that decision, for five houses — the three 0024 confined to
hand-entry (Christie's, Heritage, Zachys; Bonhams' own terms carry no
anti-automation clause and are untouched by this) plus the two never
evaluated for any access at all (Sotheby's, iDealwine).

Flagged to Doug before writing any code, the same way 0024 flagged its own
finding before building anything: Heritage's and Zachys's terms prohibit or
restrict exactly this, Christie's and Sotheby's terms are unknown, and
iDealwine sells the data this would collect for free. Three options were
put to him — hand-entry extension (no scraping), pursue a licence first, or
build real scrapers over that finding. **His answer: build real scrapers
anyway**, said out loud rather than assumed or done quietly — his own words,
echoing exactly how 0024 itself was built over its research's finding.

## What this does not change

- `app/auction/` (decision 0024) is untouched. Hand-entered evidence for
  Bonhams, Christie's, Heritage and Zachys stays exactly as it is — a
  person reading a public lot page and typing six facts in, with a source
  URL. That path keeps working regardless of what this decision builds.
- **Collector politeness is not optional just because the ToS objection is
  being overridden.** Honest, identifiable `User-Agent` with a contact URL
  (`app.adapters.http.user_agent()`), never impersonating a browser,
  `robots.txt` parsed per host at runtime via `app/worker/politeness.py`,
  `Crawl-delay` respected, aggressive caching, no blackhole trap paths.
  Overriding "you may not automate this" is Doug's call to make for his own
  business; scraping rudely on top of that is a separate, needless risk
  this project has never taken with any merchant.
- **The pricing core's rule for a sale result does not change, and cannot
  be made to change for these houses' sake.** Invariant 5: a completed sale
  (`LAST_TRADE` — "money that actually changed hands") is never Floor,
  Reference or Median, however much better the evidence is than an
  ordinary ask; it is kept as corroboration, with its variance against the
  Reference, same treatment `bordeaux-index-livetrade` (decision 0027)
  already gives a last trade. A hammer price is a `LAST_TRADE`. `app/core/`
  is locked; nothing here asks it to treat a hammer price otherwise.
- Not a claim that Sotheby's or Christie's or any of these five has said
  yes to anything. Decision 0024's own line stands: a technical ability to
  collect is not a licence to, and this decision is Doug choosing to accept
  that exposure for his own company, not a finding that it carries none.

## What reconnaissance actually found

Before writing any adapter code, all five houses were investigated —
robots.txt, actual terms of use where findable, and a real sold-lot or
listing page fetched with a plain, honestly-identified HTTP client. The
finding split the five into two very different categories, reported to
Doug before building anything, same discipline as every step before this
one:

**Genuinely buildable — a written restriction, nothing technical stopping a
plain HTTP fetch:**

- **Sotheby's.** robots.txt blocks no lot, search or buy page — only PDF
  exports, a style guide and an internal API. No scraping/automated-access
  clause found in its privacy policy or Conditions of Business for Buyers
  (no separate general "terms of use" page could be located at all).
  `/en/buy/auction/{year}/{sale-slug}/{lot-slug}` is plain server-rendered
  HTML; the full sale record — realised price, currency, close date — is
  in the page's own Next.js/Apollo JSON, no JavaScript execution required.
- **Christie's.** robots.txt disallows the search UI itself
  (`/search`, `/searchresults.aspx`) but not `/en/lot/lot-{id}` pages,
  which are also plain server-rendered HTML carrying `price_realised` in
  an inline JSON blob plus a schema.org JSON-LD block. Christie's separate
  "online-only" platform (`onlineonly.christies.com.cn`) intermittently
  returned the same DataDome challenge Heritage returns on every request —
  this adapter reads `/en/lot/` only, and does not touch the online-only
  platform.
- **iDealwine's direct shop.** Its fixed-price "buy now" listings
  (`/en/buy-wine`, `/en/buy-a-wine/...`) are an ordinary public e-commerce
  catalogue — robots.txt disallows only the API, the account area and
  login, and nothing in its terms addresses this data at all. Plain
  server-rendered HTML, JSON-LD plus an embedded Sylius/React-Query JSON
  with price, stock, vintage, format and even UK-specific post-Brexit
  customs-fee figures. This needed no override at all — it is an ordinary
  merchant adapter, the same category as every other one in this fleet.

**Not built — an active technical defence, not only a written one:**

- **Heritage.** Every request — robots.txt included — returned a DataDome
  bot-detection challenge page (`captcha-delivery.com`), not real content.
  Zero bytes of actual page data were obtained.
- **Zachys.** The retail site (`www.zachys.com`) is an ordinary Shopify
  store with no auction data at all. The actual auction platform
  (`auction.zachys.com`) returned a client-side proof-of-work JavaScript
  puzzle on every request, including its own robots.txt, with
  `X-Robots-Tag: noindex, nofollow` on top. Same result: zero bytes of
  real content.

Put to Doug directly: defeating either of those two would mean building
something that passes a deployed CAPTCHA or solves a proof-of-work
challenge designed specifically to stop non-browser clients — a
materially different and more serious act than scraping against written
terms, which is the question decision 0024 and this decision's own first
half already settled. **Doug's answer: drop both** rather than build
bypass tooling — not a change of heart on the ToS question, a different
question entirely, about active circumvention rather than broken rules.

Also put to him: iDealwine's actual historical auction/estimate data —
separate from the shop above — sits behind a login wall, and its terms
separately and explicitly claim database rights over "current
estimations, historic estimations, wine notes and comments" by name,
which is the exact licensed product `auction-access-pack.md` already
named. **His answer: shop side only.** The gated estimate data is not
pursued by this decision.

So: three adapters, not five. iDealwine's shop needed no override at all;
Sotheby's and Christie's are where decision 0024's override actually
applies.

## What this does change

Three new merchant-style adapters under `app/adapters/` — Sotheby's,
Christie's, iDealwine — following the same investigate → fixture →
`fetch()`/`normalise()` → test → register discipline as every adapter
before them (`CLAUDE.md`, "Adding a merchant adapter"). Sotheby's and
Christie's lots are completed auction sales: `LAST_TRADE`, never Floor,
Reference or Median, per invariant 5. iDealwine's shop listings are
ordinary standing asks: `ASK`, like any other merchant in the fleet,
screened the same way.

**Said plainly, not left to be discovered later: under the current
invariants, none of what these three capture becomes a visible pricing
comparable.** Both auction-house screens require `DutyStatus.IN_BOND`,
and nothing in an auction catalogue states that routinely. Christie's own
lot pages do sometimes carry an "Offered in bond" footnote naming a
specific lot explicitly — confirmed live on the Cheval-Blanc 2003
fixture — but reading it was simplified away on Doug's own instruction
("not worry about a few pennies either way, move it along"): all three
adapters emit `DutyStatus.UNKNOWN` unconditionally. Every result lands as
a plain, retained DUTY rejection: real evidence, visible to an operator in
a line's own rejected-comps table, never a comp. iDealwine's shop
separately prices in EUR, not GBP, confirmed by what the page actually
renders rather than assumed from its own `priceByCountry` table, so it
would fail the CURRENCY screen too even if duty cleared. None of this is
a flaw to fix: it is the locked core correctly refusing to treat a
non-UK-In-Bond sale as comparable to this benchmark's own market, exactly
as it already refuses for every other adapter's out-of-scope evidence.
Bringing the price in — the collection, not the classification — was the
actual point of this round of adapters; the classification work (a real,
confirmed, parseable "Offered in bond" signal on at least one house) is
left for a future decision if the pennies ever turn out to matter.

## Consequences

- This file.
- Three adapters, built one at a time: `app/adapters/sothebys.py`,
  `app/adapters/christies.py`, `app/adapters/idealwine.py` — each
  investigated and built from a real captured fixture, not guessed
  (Justerini & Brooks' flight chunks, Berry Bros' `window.__NUXT__`,
  Jeroboams' `__NEXT_DATA__` were each found the same way, before a line
  of `normalise()` was written).
- Heritage and Zachys: not built. Revisit only if either ever offers a
  real feed or licence, or if Doug chooses to drive a real browser
  session past the challenge himself — this decision does not build
  anything that does that automatically.
- `tests/fixtures/`: one real, captured response per house built —
  `sothebys-krug-1985-2026-10-26.html`, `christies-cheval-blanc-2003-
  2026-10-26.html`, `idealwine-sylvain-pataille-2023-2026-10-26.html`.
- `tests/test_sothebys.py`, `tests/test_christies.py`,
  `tests/test_idealwine.py` (46 tests total) — a dedicated file per
  adapter, same convention as every adapter built since Jeroboams; a
  regression test for every live-data trap found per house.
- The `merchant` table: three new rows, migrations `0030_sothebys`,
  `0031_christies`, `0032_idealwine`.
- `app/worker/jobs.py`: all three registered in `TARGETED`, each reading
  caller-supplied lot/product paths (`_by_lot_paths`, new;
  `_by_product_paths`, reused) — none has a usable live search, confirmed
  per house, so none guesses one.
