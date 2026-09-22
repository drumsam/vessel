# 0011 — Two collection modes: the sweep, and the search

**Status:** accepted, 20 September 2026.

## Context

Bordeaux Index was recorded as a merchant whose collection "fails". It does not.
BI can only be queried per producer and vintage, so it can never take part in a
whole-book sweep, and treating it as a bulk source that happens to error was a
miscategorisation. It is a **deep-search source**, which is what the pipeline's
DEEP MERCHANT SEARCH stage was always for: sweep first, then search the gaps.

The dress rehearsal made the cost of the miscategorisation plain. Farr and
Goedhuis swept 10,510 records and produced seven usable offers, all in formats
the seller did not hold, so all twenty lines came back `NO_MARKET` — while BI,
the merchant that actually lists loose bottles, was never asked.

## Decision

**Two modes, both writing ordinary captures.**

- **The sweep** (`collect_snapshot`): merchants whose whole offer book can be
  fetched. Farr, Goedhuis.
- **The search** (`deep_search`): merchants that answer per producer and
  vintage. Given a deal, it takes the lines that came back thin — fewer than
  `min_comps` merchants, or never searched — reduces them to distinct
  (producer, vintage) pairs, and asks each search-only merchant about those and
  nothing else.

Each search is its own capture with its own `captured_at`, scoped to that
producer and vintage, and resolves exactly like any other (decision 0004). A
targeted capture covers that producer in that vintage and nothing else, so it
never masks a gap elsewhere.

**Search keys are read, never guessed.** `merchant_search_key` maps a merchant
and a normalised producer to that merchant's own search terms. The slug form is
not guessable: `producer=domaine_armand_rousseau` works at Bordeaux Index and
`domaine-armand-rousseau` is a 404 — the rehearsal lost a whole search to
exactly that. BI publishes its own producer index in its sitemap
(`/filters.xml`), and `learn_search_keys` reads it into the table. An operator
can set a key by hand. A missing key is a recorded skip, never an attempt at a
likely-looking string.

**A 404 means two different things, and they are not read alike.** A known
producer with nothing in a vintage is zero rows: searched, nothing found. A slug
the merchant does not publish is our mistake and raises `UnknownProducerSlug`,
because treating it as an empty answer is how a search silently reports no
market. Every slug is checked against the merchant's index before it is used.

**A producer may be published under several slugs**, and they are searched
together and de-duplicated. Searching one of them would halve that producer's
depth; counting a wine listed under both twice would invent depth.

## Consequence

- The earlier REVIEW 5 comes back legitimately: a sweep for Farr and Goedhuis,
  then a search of the thin lines at BI, gives loose-bottle depth that the
  sweep alone cannot.
- A merchant added later declares which mode it belongs to by which registry it
  is listed in (`WHOLE_BOOK` or `TARGETED` in `app/worker/jobs.py`). Asking a
  search-only merchant to sweep is refused with that reason, not attempted.
- Deep search is per deal, because "thin" is a property of the lines being
  priced, not of the market in the abstract.
