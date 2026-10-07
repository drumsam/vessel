# 0026 — A bid and a last trade are evidence, never a price

**Status:** accepted, 8 October 2026. A locked `app/core/` change, built
from the three things `docs/research/bi-livetrade-champagne-findings.md`
named for the pricing core, after Doug confirmed a bid/offer pair from BI
LiveTrade currently enters as neither — the adapter does not read that
page at all — and asked, specifically, to get this right.

## What the research found

Bordeaux Index LiveTrade is a two-sided marketplace: a best bid, a lowest
offer, a last executed trade with its date, sometimes a full bid ladder.
Krug 167ᵉ: bid £908, last trade £904, offer £977 — a 7.6% spread straddling
a recent trade, a real liquid market. Krug 162ᵉ: bid £660 against an offer
of £1,596 on the same 6×75cl listing — a 142% spread, "two people a long
way apart," not a market a midpoint could honestly summarise.

"A bid is executable demand and better evidence than an ask" — a real
counterparty has committed to it, where an ask is only ever an aspiration.
That is a genuine change in what kind of fact this system can hold about a
wine, not just a new merchant to read.

## Nothing changes about what prices a line

`PriceKind.BID` and `PriceKind.LAST_TRADE` already existed in
`app/core/enums.py`; nothing ever constructed either. The hard screen
already required `price_kind is PriceKind.ASK` to be comparable at all
(`app/core/benchmark.py`'s `_screen`), so a correctly-tagged `BID` was
already structurally excluded from Floor, Reference and Median before this
decision touched anything — exactly the guarantee that already protects
`INDICATION` (decision 0013). This decision does not relax that screen. It
adds two new predicates, `_is_bid`/`_is_last_trade`, built as close
mirrors of `_is_indication`, so a bid or a last trade that matches the
line's wine, vintage and format is caught on its way to `Rejection` and
kept as corroboration instead — never the other way around.

## Three differences from an indication, each deliberate

1. **Duty status is checked.** An indication is never stock, so duty
   status does not apply to it. A bid or a last trade is concrete — BI's
   own are explicitly "In Bond, GBP, Original Case, Pristine" — so both
   predicates require `DutyStatus.IN_BOND`, the same screen an ASK faces.
2. **Buyability is not checked, for the opposite reason an indication
   skips it.** An indication skips buyability because it is never stock.
   A bid skips it because it is demand — the opposite direction from
   stock on offer — so "is this buyable" does not describe it either way.
3. **A last trade is not screened for freshness at all.** "It should
   carry its date so staleness is visible" — the research's own words.
   BI's Krug GC 1×150cl last traded in January 2025; the point is to show
   that, with its date, not to apply the 14-day `MAX_OFFER_AGE_DAYS` window
   and silently drop almost every last trade that exists, which is what
   would happen if trades were held to the same cadence as a live ask. A
   bid IS a currently-standing order, so it keeps the ordinary freshness
   check — an old bid may no longer stand.

## The wide-spread flag: what it actually guards

Nothing in this codebase averages a bid and an offer into anything — there
was no midpoint calculation to refuse. The read of "refuse wide spreads
rather than averaging them" built here is the one that matches reality:
`TWO_SIDED_WIDE_SPREAD` (informational, not in `REVIEW_FLAGS`, same
footing as `WIDE_SPREAD` itself) fires when a single merchant's own best
bid and their own ask for the same wine, vintage and format disagree by
more than `WIDE_SPREAD_THRESHOLD` — the existing 0.25 constant, reused
rather than inventing a new number, since it already answers "is this
spread wide enough to be worth naming" everywhere else in this file. Krug
162ᵉ's 142% trips it; 167ᵉ's 7.6% does not. The flag exists so an operator
reading a bid's variance never mistakes it for a market that's confirming
itself when the same source's own two numbers disagree this much — not to
gate anything, because nothing here was ever priced from either figure.

## What was built

- `app/core/flags.py`: `Flag.TWO_SIDED_WIDE_SPREAD`, not added to
  `REVIEW_FLAGS`.
- `app/core/benchmark.py`: `BidEvidence`/`LastTradeEvidence` (mirroring
  `IndicationEvidence`); `_is_bid`/`_is_last_trade`; `result.bids`/
  `result.last_trades`, populated in both the `NO_MARKET` early return and
  the success path, exactly where `result.indications` already is;
  `with_variance` generalised to take an evidence class and an offer list
  rather than being indication-specific.
- Migration `0021_bid_last_trade`: widens `benchmark_comp.role`'s CHECK to
  admit `'bid'`/`'last_trade'`, verified against the live constraint name
  before writing the migration. `schema.sql` updated to match, confirmed
  byte-equivalent by catalog diff.
- `app/db/repo.py`: `save_benchmark()` stores a bid/last-trade row exactly
  as it already stores an indication row — same function, same shape, two
  more lines.
- `app/api/schemas.py`: `CompOut.role` admits the two new values;
  `CompOut.captured_at` added (it was already in the stored snapshot, just
  never declared on the response model) so a last trade's own date reaches
  the screen that is supposed to show it.
- `web/app/deals/[dealId]/line.jsx`: bid and last-trade rows rendered
  beside cross-unit and indication evidence, each labelled "not priced,"
  the last trade's own date shown beside its variance.
- Tests: 13 new in `tests/test_traps.py` (pure, offline) — mirroring the
  existing indication tests exactly where the rule is the same (never the
  Reference, corroboration with variance, excluded for any mismatched
  wine/vintage/format/currency/duty) and adding the three genuine
  differences: a stale last trade still shown, a stale bid refused, and
  both the tripped and the untripped case for `TWO_SIDED_WIDE_SPREAD`,
  using Krug 162ᵉ and 167ᵉ's own real numbers. 361 offline (was 348), 522
  with Postgres (was 508).

## What this is not

No BI LiveTrade adapter. `_is_bid`/`_is_last_trade` are proven correct
against hand-built `Offer` objects, the same way `_is_indication` was
proven correct before FINE+RARE's adapter existed to produce real ones —
nothing here reads `.bid-button`/`.offer-button`/`.bids` from a live page.
A persistence round-trip through `save_benchmark`/`run_comps` was not
given its own new end-to-end test: the code path is a structural copy of
the already-end-to-end-tested `INDICATION` path (`test_an_indication_is_
kept_as_corroboration_and_prices_nothing`), and building a synthetic one
would have meant hand-constructing `offer` table rows with real `offer_pk`
UUIDs outside the resolver that normally produces them — exactly the kind
of fixture a real adapter should supply, not a test standing in for one.
That coverage belongs with the LiveTrade adapter itself, when it exists.
