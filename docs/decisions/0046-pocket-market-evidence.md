# 0046 — Pocket reports evidence; Doug decides

Approved brief: docs/research/market-data-integration-milestone.md.

For Pocket's inbound evaluation only, this supersedes the walk-away and margin
recommendations in buy-side-margin-test.md and the market-weakness blocking
behavior. Seller ask, canonical identity, want-list/photo acknowledgement and
supplier confirmation remain. Identity uncertainty blocks; missing/stale/thin
pricing evidence is informational. No new offer workflow is introduced.
Sell-side pricing, export/market-claim safeguards and the locked core are unchanged.

Postgres, existing snapshots/rejects, canonical registry, auction_evidence and
benchmark history are authoritative. No standalone prototype code is merged.

A nullable benchmark_run.evidence_key records a fingerprint of benchmark inputs
and policy. It permits persisted-result reuse without changing benchmark math.
The fingerprint includes line identity/quantity/review flags, wine region,
vintage tiers, source captures, resolved offers, reinstatement decisions and
14/90-day eligibility boundaries. A policy change must bump the cache policy.
The key is written in the same transaction that creates its run. Concurrent
Pocket evaluations serialize on the inbound row. Reconfirmation invalidates the
bound line identity and its cached result; market review flags are not identity
blocks. Old source evidence remains auditable but never a current eligible Floor.

Auction imports add raw_evidence and import_key to the active auction table.
The active-event unique index excludes retracted rows. Original amounts/bases
are retained; identical events are skipped, conflicting facts require retraction
and review. Only the existing Christie's source is supported for this milestone.
Unresolved imports use offer_reject with the existing registered source and an
explicit import envelope; re-resolution routes these envelopes to auction
persistence, never through the merchant ASK path. Failed/unresolved batch captures
are not successful merchant inventory captures, so cannot hide merchant stock.

The transaction rail uses active auction_evidence only, not adapter LAST_TRADE
rows. Auction dates, lot quantities, currency, basis and source links remain
explicit; no transaction price becomes a merchant Floor. No data is fetched
by evaluation. Existing collect_now is the explicit refresh mechanism.
