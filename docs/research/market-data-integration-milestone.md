Work in drumsam/vessel on the pricer branch, which contains the real VESSEL application. main contains a standalone Market Data prototype; do not merge it into pricer.

Implement the smallest integrated market-evidence milestone described below. The reconciliation plan is approved. Do not build another service, database, identity resolver, benchmark engine, source-health system or dashboard.

First read CLAUDE.md, README.md, docs/decisions/, and the relevant Pocket, auction and speed/cost specifications in docs/research/. Inspect current code before editing; the branch may have changed since the reconciliation.

Save this approved brief as docs/research/market-data-integration-milestone.md. Record how it supersedes earlier Pocket behavior where necessary.

AUTHORITATIVE EXISTING INFRASTRUCTURE

Reuse:
- Postgres and existing migrations.
- Canonical wine UUIDs, registry, aliases, release-code rules and want-list gates.
- Offer/Candidate contracts, offer_reject and existing re-resolution.
- Merchant adapters, merchant_search_key, snapshot and snapshot_merchant.
- Existing Floor / Reference / Median calculations and benchmark history.
- Active auction_evidence implementation.
- Existing Pocket evaluate and collect-now endpoints and UI.

Do not change app/core/benchmark.py or relax its invariants.
Do not modify the separate sell-side pricing/export safeguards.

APPROVED POCKET BEHAVIOR

Pocket’s market-evidence flow reports facts, not a buyer-price recommendation.

Remove walk-away, max-sell, headroom and margin-based commercial verdicts from this Pocket flow. Preserve seller asking-price facts.

Identity uncertainty and existing identity/want-list safeguards may block progression. Missing, thin or stale market evidence must be shown honestly and must not independently block Doug’s decision.

Preserve the distinction between:
- Not searched.
- Searched and found no evidence.
- Collection/check failed.

Inspect server-side enforcement and frontend behavior; changing a response flag alone is insufficient if another layer still imposes the same pricing-data block. Do not expand into building a new offer workflow.

FIRST MILESTONE

Demonstrate:
1. One existing canonical wine.
2. One existing merchant adapter with an established search key.
3. Merchant Floor, Median, distinct merchant count and evidence age from existing data/calculations.
4. One CSV/XLSX auction import into the existing Postgres evidence architecture.
5. Auction identity resolved through the existing canonical process.
6. Merchant and auction evidence displayed separately in existing Pocket.
7. Pocket normally reads a valid cached/persisted result.
8. Existing collect_now refreshes merchant evidence and updates the same response contract.
9. No duplicated identity, pricing, evidence-store or source-health infrastructure.

CACHE AND EVIDENCE

Use existing benchmark_run, benchmark_run_snapshot and benchmark_comp wherever suitable. A thin orchestration module is acceptable; duplicate benchmark arithmetic is not.

Define and test cache validity for identity/unit changes, source captures, review changes and freshness boundaries. Never resurrect a listing omitted from its merchant’s latest successful covering capture.

Expose source capture dates and auction sale dates. Evaluation time is not evidence freshness.

Keep the existing 14-day merchant benchmark eligibility rule. Older evidence may remain visible as clearly dated historical context; do not label it as a current eligible Floor.

Target cached local evidence lookup under 500 ms. Measure it and report the environment and limitations. Live collection occurs only through explicit refresh, never as a hidden consequence of an ordinary evidence read.

AUCTION IMPORT

Adapt the prototype’s useful CSV/XLSX parsing approach to existing VESSEL contracts. Do not copy its SQLite store, resolver, summary arithmetic or API.

Use existing auction validation, premium/FX handling, quarantine and operator attribution. Never invent missing prices, premium rates, FX rates, quantity or identity.

Preserve original row evidence. Unresolved input must stay unresolved in existing rejection infrastructure; never force-match it or create another unresolved queue. Inspect existing re-resolution behavior and extend it narrowly if needed.

Proposed minimal schema additions to auction_evidence:
- raw_evidence JSONB for the original row and import provenance.
- Nullable import_key with uniqueness for active imported source events.

Confirm whether existing fields can satisfy these needs before adding columns. Reimporting identical evidence must be idempotent. Conflicting facts for the same event require explicit review, not silent overwrite or double counting.

Update schema.sql, an additive migration and EXPECTED_HEAD_REVISION together if schema changes are needed. Respect immutable/retraction semantics and migration revision-length rules.

Do not revive the unused auction_result table. Do not blindly combine auction_evidence with adapter-produced LAST_TRADE records: avoid counting the same sale twice. Keep auction facts out of merchant Floor/Reference/Median.

DELIVERY AND VALIDATION

Work on an integration branch based on pricer, preserving existing changes. Do not force-push, merge into main, deploy or modify production data.

Use existing fixtures and disposable test databases. Never run destructive database tests against the deployed database.

Add meaningful regression tests for:
- Identity ambiguity and release/edition separation.
- Exact units and currencies.
- Merchant-best rather than listing-weighted summaries.
- Raw provenance and duplicate/conflicting auction imports.
- Auction/merchant separation.
- Cache invalidation and source freshness.
- Weak market evidence remaining informational.
- Existing identity blocks remaining enforced.
- Existing collect_now and Pocket behavior.
- No regression in sell-side pricing/export safeguards.

Run relevant backend, migration, frontend and journey tests. Distinguish passed, failed, skipped and unrun checks. If live data or deployed access is unavailable, validate with existing fixtures and clearly report that limitation.

Do not add collectors, Liv-ex integration, Core coverage, a scheduler or a dashboard.

Finish with the changed files, schema changes, test results, measured cache performance, remaining limitations and simple Mac instructions for viewing the integrated results in existing Pocket.

If inspection reveals that this design cannot safely fit existing infrastructure, stop before implementing a conflicting architecture and explain the specific blocker.