# Contract and integration

## Identity boundary

Implement `IdentityResolver.resolve(candidate: dict) -> MarketUnit | None` using the existing authoritative VESSEL identity service. The service must validate producer, cuvée, vintage, bottle format, pack quantity, release/edition and want-list safeguards. Ambiguity returns `None`; never trust a source-provided `wine_id` alone. `wine_id` must distinguish canonical editions/releases. No producer strings or aliases are matched inside Market Data.

Inject the resolver into `Store(path, resolver)` or provide a factory with `--resolver your_package:factory` before the CLI subcommand. `resolve-pending` retries unresolved evidence after integration without discarding raw evidence. For PACK auction totals the resolver must confirm quantity and size; absent information stays unresolved. Market and tax context must be explicit. No FX, tax conversion, buyer-premium estimation or price invention occurs.

All `Candidate` records include source ID/type, decimal price, uppercase currency, BOTTLE/PACK basis, supported price type, timezone-aware observation timestamp, source reference, optional URL, original evidence and identity hints. A BOTTLE price is multiplied by the canonical pack size for the reference's exact unit. PACK prices are already totals for that unit. All returned prices are decimal strings, never binary floats. Observation IDs in summaries provide provenance through the observations endpoint. Evidence is retained indefinitely; only resolution metadata can change.

The exact key is `wine_id, vintage, bottle_ml, pack_size, market, tax_status, currency`. Currency is deliberately part of the key. Use `NV` explicitly for non-vintage identities. A missing reference returns null prices and zero counts, not a guessed market price.

## Pocket API

All endpoints return JSON. Pocket only needs this contract or the equivalent `reference(store, unit)` service call.

- `GET /health` checks database connectivity.
- `GET /v1/reference?<exact-key-fields>` returns cached evidence rails with dynamic ages.
- `GET /v1/observations?<exact-key-fields>` returns original observations for audit.
- `GET /v1/unresolved` provides the identity-integration queue.
- `GET /v1/source-runs` returns source-run status and counts.
- `POST /v1/refresh` accepts an exact-key JSON object and queues a coalesced request; returns 202. It does not claim collection is complete.

Example query after canonical integration:

```sh
curl --get http://127.0.0.1:8765/v1/reference \
  --data-urlencode wine_id=canonical-id --data-urlencode vintage=2015 \
  --data-urlencode bottle_ml=750 --data-urlencode pack_size=6 \
  --data-urlencode market=UK --data-urlencode tax_status=IB --data-urlencode currency=GBP
```

References contain `unit`, `policy`, `generated_at`, `merchant`, `transactions` and `liquidity`. Merchant fields include floor, median, observation count, distinct source count, newest timestamp, oldest included timestamp and observation IDs. Transaction buckets are separate for AUCTION_HAMMER, AUCTION_ALL_IN, LAST_TRADE and VESSEL_TRADE; each has latest result, low/high, median, count and provenance. Do not merge these buckets in Pocket. Liquidity includes best bid/offer, spread, each side's timestamp and observation ID. No live executability is implied when old bid/offer evidence is displayed.

Each monetary rail has `age` and `oldest_age`, containing `as_of`, `age_days`, and `freshness`. Liquidity ages are per side. Ages use elapsed whole UTC days: 0–14 fresh, 15–30 usable, 31–90 stale, 91+ historical. This resolves the brief's overlapping 90-day boundary. Cache generation time is not the observation time. Stale evidence remains visible, including old liquidity, and Pocket can queue REFRESH MARKET.

## Summary policy v1

Merchant evidence includes asks and live offers. Only the latest observation per source/reference/type is summarized; all originals remain stored. Sources must use stable listing references. Merchant count is listing count; source_count is distinct source count. Median is across included listings, not a source-weighted valuation. Source runs do not imply a complete inventory; absence from a later feed does not establish withdrawal. Withdrawn/sold listing lifecycle integration is a future requirement for live inventory accuracy.

Transaction events are retained separately by source/reference/type/time so reusing a lot number in another sale does not erase older results. Corrected prices for the same event replace the earlier price in the summary while both originals remain auditable. Transaction range/median currently cover all retained events, not a rolling recent-only window; oldest included age exposes that scope. No automatic expiry or outlier removal occurs. These are evidence summaries, not fair value.

SQLite caches references and invalidates the exact unit atomically on writes or resolution. Cache rebuilding serializes with writers to avoid a stale write racing invalidation. WAL mode supports the small single-machine workload; pagination, distributed workers and a server database can follow actual usage needs.

## Collection and refresh

A collector has `source_id` and `collect(unit) -> Iterable[Candidate]`. Each adapter owns transport, permission and schema parsing. Prefer licensed feeds, permitted structured collection, files, and assisted imports. No browser scraping or Liv-ex commercial assumptions are included. `StructuredFeed(source_id, path)` is a JSONL file adapter using the universal Candidate shape. A future Liv-ex adapter uses the same interface without changing Pocket.

Register exact canonical units using `store.set_universe(unit, 'CORE', 'A')`; priorities A/B/C schedule 7/14/30-day refreshes. Discovery is on demand only. `store.request_refresh(unit)` queues any exact unit, and `refresh(store, collectors)` processes queued/due units. Promotion simply updates universe membership. Priority changes collection timing only.

Use a replaceable external timer, for example hourly, to invoke:

```sh
.venv/bin/python -m services.market_data --resolver identity_bridge:factory refresh \
  --collector permitted_feed_a:factory --collector permitted_feed_b:factory
```

These names are integration examples, not installed adapters. Run one worker at a time; distributed claims, per-source retry backoff and worker crash recovery are not implemented. Each source failure is isolated and recorded. Invalid candidate rows count as rejected; identical observations count as duplicates rather than rejects. Raw private exception messages are not stored as source errors. A partial/failed run leaves the unit due; empty successful source responses are recorded as successful checks, without inventing observations. Refresh requests remain queued until a worker with configured collectors completes successfully. No collectors are silently assumed to be operational.

## Auction input

CSV UTF-8 headers or the active XLSX sheet use:

`sale_date, lot, producer, wine, vintage, bottle_ml, format, quantity, release, edition, hammer, all_in_price, currency, market, tax_status, auction_house, source_reference, source_url`

Fields are optional where genuinely absent, but ingestion needs a sale date, source_reference or lot, a currency, and at least one supplied positive hammer/all-in total. Use ISO dates or timezone-aware timestamps; date-only sale records use UTC midnight. Use unformatted decimal amounts (no currency symbols/thousand separators). Unknown format/quantity/identity context may be retained unresolved. Both supplied hammer and all-in values become separate observations with the full original row. They are never inferred from each other. The CLI source ID should identify the auction house/feed; source references should uniquely identify sale and lot. PDF/AI parsing is not implemented.

## Current limits

There is no Pocket application, canonical identity database, real licensed source, scheduler daemon, external deployment, or recommendation engine in this repository. No live market coverage is claimed. The brief upload ends at `infer transaction` in section 17; no missing continuation has been assumed. The implementation can be developed and tested locally now; production identity and source wiring remain explicit integration tasks.
