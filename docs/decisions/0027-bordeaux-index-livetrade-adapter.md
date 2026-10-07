# 0027 — Bordeaux Index LiveTrade adapter

**Status:** accepted, 8 October 2026. The seventh verified adapter, and the
first to produce the `BID`/`LAST_TRADE` evidence decision 0026 built a place
for. Follows "Adding a merchant adapter" (`CLAUDE.md`): official feed > plain
HTTP > Playwright, a real fixture, `fetch()`/`normalise()`, a regression
test per trap, registered in a migration.

## Investigated live, not assumed

`docs/research/bi-livetrade-champagne-findings.md` read the marketplace
through a browser pane and described the DOM (`.bid-button`, `.offer-
button`, `Last trade: £X (DD/MM/YYYY)` in rendered text) and warned the
item page was client-rendered. Fetched live, 8 October 2026, with a plain
GET and an honest, non-browser User-Agent: `/livetrade/marketplace/krug`
is server-rendered — no Playwright needed — and every `.livetrade-item`
carries a `data-item="{...}"` attribute holding the complete record as
clean JSON: identity, format, duty status, and the full bid/offer/last-
trade picture, six times over (desktop/mobile/tablet × bid-button/offer-
button). Reading the attribute directly is both more reliable and less
code than parsing the rendered text the research's own method used, and it
is the exact lesson `/search/auto-complete-ajax` already taught: prefer
the structured answer the page computed for itself.

`robots.txt` was re-checked rather than trusted from memory: `/livetrade/
marketplace` is allowed, confirming the sibling adapter's own comment.

One item found in this fresh fetch — Krug Grande Cuvée Edition 162ème,
bid £660 against offer £1,596 — is the identical live pair the research
doc described three weeks later. Finding it again, unprompted, is the
adapter's own proof that decision 0026 was built for a real, persistent
situation, not a one-off reading; it is also now a committed regression
test (`test_the_krug_162_bid_offer_spread_matches_the_research_that_
prompted_0026`).

## One company, two pages — never two merchants

The adapter is registered under its own id, `bordeaux-index-livetrade`,
because it needs its own collection bookkeeping: a different search
mechanism (free text, not a slug), a different raw shape, its own
snapshot and LWIN-conflict tracking. But every `Offer` it produces is
published under `merchant_id = "bordeaux-index"` — the sibling adapter's
own row, not its own id.

This is a deliberate exception to migration `0002`'s own stated rule ("the
ids must equal each adapter's `id` attribute, because offers are written
with `merchant_id = adapter.id`"), and it is made because that rule's
purpose — one merchant, one identity — would otherwise be violated the
other way: LiveTrade and the regular fine-wine listing pages are one
company publishing two different views of its own book. Treating them as
two merchants would mean that the moment both pages happen to carry a
price for the same wine on the same day, depth reads 2 when it is really
one company quoting itself twice — exactly the "a merchant that lists the
same wine twice never becomes its own second comp" invariant (4), and the
same lesson invariant 17 already drew from FINE+RARE's own `merchantCount`
inflation, just arriving from the opposite direction. `test_every_offer_
is_published_under_the_sibling_merchant_id` asserts this directly, for
every item in the fixture.

## Up to three Candidates per item, never a ladder

Each raw record (one LiveTrade item) can yield the lowest offer (`ASK`),
the best bid (`BID`), and the last trade (`LAST_TRADE`) — the Adapter
contract's own "one raw record may yield several candidates," extended by
one more kind. The ladder beneath the best bid (sometimes six or eight
rungs deep) is read only to confirm rank 1 really is the extreme; it is
not emitted as additional evidence — the research that motivated this
adapter already established that the ladder is confirmatory, not
additional comps, and nothing about re-reading it here changes that.

## Two traps, both already named in the module's own docstring

1. **BI names the same wine two different ways, inside one JSON record.**
   `productName`: "Krug Grande Cuvee Edition 162" (number last).
   `lwinProductName`: "Krug, Grande Cuvee 162eme Edition" (number in the
   middle, producer comma-separated). This adapter reads
   `lwinProductName`, because it is comma-structured (matching this
   codebase's producer-first convention) and because `split_release_code`
   (decision 0019) already handles "162ème Édition" at the end of a
   string — which is exactly what stripping the producer from
   `lwinProductName` leaves behind, and exactly what `productName`'s
   "Edition 162" ordering does not.
2. **The search caps at 100 items with no pagination.** Confirmed live:
   `/livetrade/marketplace/krug` returns exactly 100 unique variants.
   `fetch()` raises `SearchTooBroad` when the cap is hit, rather than
   returning 100 items as if that were everything — silence past an
   unknown ceiling is exactly the kind of gap `CLAUDE.md` says to fail
   closed on, not paper over. The caller narrows the search term (e.g.
   "krug grande cuvee" instead of "krug").

## A gap found and fixed, not worked around

`Candidate.release_code` has existed since decision 0019, with a docstring
naming Krug's own editions as the reason. Nothing read it:
`app/worker/jobs.ingest()` called `registry.resolve_candidate(producer,
cuvee, lwin7)` with no fourth argument, for every adapter, always. This
adapter is the first to populate `release_code` at all, which is what
exposed the gap — fixed at the one call site rather than worked around
per-adapter, since the bug was never specific to LiveTrade: any adapter
that ever learns to split an edition number would have hit the same
silent no-op. `resolve_candidate`'s own fourth parameter now actually
receives what callers were already computing.

## What this is not

No `search_keys()` validation against a fixed slug list — LiveTrade
searches free text, and delegates to the sibling adapter's own producer
index (`BordeauxIndexAdapter.search_keys()`) rather than duplicating it,
since it is the same company's same producer list. No automated retry or
pagination past the 100-item cap — narrowing the search term is an
operator decision, not something to guess at. No change to `app/core/`:
`_is_bid`/`_is_last_trade` (decision 0026) already existed; this adapter
is the first real source for them, not a reason to revisit them.

## Consequences

- `app/adapters/bordeaux_index_livetrade.py` (new): `fetch()`,
  `normalise()`, `extract_livetrade_items()` (the thin, untested-by-name
  DOM shim, same convention as the sibling adapter's own `extract_cards`),
  `search_keys()` (delegated), `SearchTooBroad`.
- `app/worker/jobs.py`: registered in `TARGETED` as
  `"bordeaux-index-livetrade"`; the `ingest()` release-code fix, affecting
  every adapter.
- Migration `0022_bordeaux_index_livetrade`: registers the new merchant id
  (data only — no schema.sql change, matching migration `0002`'s own
  seed-data precedent).
- `tests/fixtures/bordeaux-index-livetrade-2026-10-08.html`: a trimmed,
  real response — four complete `.livetrade-item` blocks, unedited apart
  from being cut from the page's full 100.
- Tests: `tests/test_bi_livetrade.py` — 16 tests against the real fixture
  and two hand-built edge cases (no price at all; a scrambled offer list
  proving `min()`, not list order or a trusted `rank` field, decides the
  ask). 377 offline (was 361), 538 with Postgres (was 522).
