# 0048 — source-agnostic market-evidence import

**Status:** accepted, 31 October 2026, on Doug's instruction. "VESSEL consumes
trusted structured market evidence. Acquisition is a separate concern."

## What it is

`POST /market-evidence/batches` accepts one batch of structured observations
from any provider: a licensed feed, Liv-ex, a merchant's own list converted to
JSON. `app/feed/importer.py` turns each observation into an adapter `Candidate`
and runs it through `app.worker.jobs.ingest` unchanged: the canonical resolver,
the whole-pence check, `offer` / `offer_reject`. The locked core then decides,
exactly as for any adapter, what may set Floor. No new pricing store, no new
identity model, no provider-specific code.

- **Identity** is VESSEL's own. A provider's `wine_id` claim is only ever a
  cross-check: if VESSEL resolves the text differently, the observation is a
  `WINE` reject. LWIN is cut to LWIN-7 and, as everywhere, only cross-checks.
- **Acquisition source** is kept on every offer (`raw.acquisition_source`),
  separate from the real merchant.
- **Merchants** map onto the register by normalised name, so "Farr Vintners
  Ltd" is `farr`, never a second Farr (invariant 3). Hybrid approval rule:
  an existing approved merchant counts at once; an existing unapproved one
  keeps its state; a genuinely new one is created **unapproved** — its
  evidence is stored and visible but sets no Floor until someone approves it.
- **Unknowns** follow the existing rules: unknown duty is stored and excluded
  from Floor; a current listing is for sale unless it says out of stock; a
  historic price is kept as a retained reject, never a live ask; a price must
  be a decimal string, never a JSON number.
- **Auth** is one narrow bearer token, `MARKET_FEED_TOKEN` (at least 32
  characters, set on the hosting platform). It can write market evidence and
  nothing else. Unset, the route answers 503.
- **Batches** of up to 5,000 observations land whole or not at all (one
  transaction); the summary reports written, rejected by reason, merchants
  mapped / created / unapproved, and observations with no merchant (handed
  back by position — there is nothing to attribute them to).

## The evidence-selection change

The market check uses each merchant's latest capture covering the wine. A
merchant search covers every wine of a producer in a vintage, so its capture
is scoped (producer, vintage). A feed reports only the wines it was asked
about; scoped the same way, Farr's feed row for Rousseau Chambertin 2015
became Farr's latest capture for all Rousseau 2015, and Farr's whole-book
Clos de Bèze 2015 stopped counting — proved in `tests/test_feed_import.py`
before the fix. `snapshot_merchant.scope_wine_id` (migration
`0039_feed_scope_wine`) narrows a feed capture to its one wine. NULL keeps
every existing capture exactly as before. This changes evidence selection in
`app/db/repo.py`, not `app/core/`.

Each merchant × wine group is its own snapshot, because `snapshot_merchant`
holds one capture per merchant per snapshot.

## Not built

Queues, provider-specific adapters, scheduling, an approval screen for new
merchants (approve in the database for now).
