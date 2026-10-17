# 0032 — durable evidence storage: managed Postgres, insurance off the laptop

**Status:** accepted, 17 October 2026. Doug asked directly, after Cellar
Desk's own local dev story (decision pending, `scripts/desk.sh`) raised the
obvious next question: where does the *real* evidence live, given one
laptop, two to three cellars a year, and nobody who wants to administer a
database. (Numbered 0032, not 0030 as first suggested — 0030 and 0031 were
already taken by the Berry Bros. & Rudd and Jeroboams adapters.)

## The decision

**A managed Postgres instance is the primary store for real deals and real
evidence.** Not a self-run one, and not versioned dumps in the repo as the
primary mechanism. The app already only wants a `DATABASE_URL`; pointing it
at a managed instance instead of a local one is zero code change.

Dumps-in-git was considered and rejected as the *primary* mechanism for one
decisive reason: a dump still needs a Postgres to restore into, so it
defers the administration question rather than removing it. Git also
doesn't diff binary dumps sensibly, so a repo of them only grows.

## Refinement 1 — the smallest PAID tier, not free

Doug's cadence makes dormancy the normal state: two to three deals a year,
so the database sits untouched for months at a stretch. Free tiers at
providers like Neon and Supabase *suspend* on inactivity, which costs
nothing to recover from — but free **projects** at the same providers get
*reclaimed* after prolonged inactivity, and eleven quiet months between
deals is exactly that pattern.

The entire point of this store is that in eighteen months Doug can show a
buyer why a bottle was priced at £162 on 9 October 2026. A tier that may be
reclaimed cannot carry that promise. The smallest **paid** tier of a
managed Postgres provider is the floor, stated here explicitly so nobody
"saves money" by downgrading it later without re-reading why it's paid.

## Refinement 2 — the dump goes off the laptop

A `pg_dump`-equivalent taken after each deal closes is real insurance, but
only if it is a second copy on a second machine. A second file on the same
disk is not a second copy. Doug's laptop already runs Dropbox, so the dump
goes into a Dropbox-synced path —
`~/Library/CloudStorage/Dropbox/Workspace_Archive/UK_Fine_Wine_Pricer_Backups/`,
alongside this project's other archival material there (`Wine_Inventory_
Photos`, `Citadel_Decks_HiRes`) — never into the repo and never into a
local-only folder. `scripts/evidence_backup.py dump <DATABASE_URL>` writes
there by default, with a timestamped filename, so the right place is the
easy place rather than one more thing to remember.

## Refinement 3 — the restore was tested, not assumed

An untested backup is not a backup, and this project has twice been bitten
by assuming a capability worked without checking (the FUSE mount, `docker
compose`). Tested directly, 17 October 2026: dumped the local embedded
Postgres (seeded with the Cellar Desk demo deal — a real `offer`,
`benchmark_run`, `benchmark_comp` and `pricing_result` shape, not a toy),
ran migrations against a fresh scratch database, restored into it, and
compared row-for-row:

```
table                  source   restored
offer                       5          5   OK
benchmark_run               3          3   OK
benchmark_comp             14         14   OK
pricing_result              3          3   OK
deal                        1          1   OK
seller_line                 3          3   OK
wine                        2          2   OK
merchant                   10         10   OK
snapshot                    1          1   OK
snapshot_merchant           2          2   OK
```

`pricing_result.sell_price` round-tripped as the exact same `Decimal`
values, never through a float, and `buyer_price_gbp`/`seller_price_gbp`/`gp`
(GENERATED columns, decision 0017) recomputed identically on the restored
side rather than being copied — confirming they are still computed, not
stored twice. Full command sequence and the restore's own counts are in
`scripts/evidence_backup.py`'s module docstring.

## No pg_dump, no psql — a logical dump in pure Python

Doug's machine has no system Postgres client tools at all, and
embedded-postgres (the package `scripts/desk.sh` already drives) ships only
`postgres`/`initdb`/`pg_ctl` — no `pg_dump`, no `pg_restore`. `scripts/
evidence_backup.py` uses `psycopg` alone (already a dependency) to dump
every table, in foreign-key dependency order read from the schema itself,
as JSON Lines. `Decimal` is tagged (`{"__decimal__": "162.83"}`) so it comes
back as a `Decimal`, never a float, on restore — the same discipline
invariant 7 states for the pricing core itself, extended to the one place
outside it that also touches money. Generated columns are never written to
the dump and never inserted on restore; Postgres computes them both times.

## The clean separation this gives, stated so it stays true

- **embedded-postgres stays the LOCAL dev and demo database.** That is what
  `scripts/desk.sh` drives; losing it costs nothing, and it never holds a
  real deal.
- **The managed instance holds real deals and real evidence.** Doug sets it
  up himself and provides the `DATABASE_URL` — this project does not create
  accounts or sign anything up on his behalf.
- **Everything selects between them on `DATABASE_URL` alone.** Already true
  before this decision; no code change needed for it to stay true.

`scripts/desk.sh`'s own banner prints which database it is driving —
`localhost:5432/pricer_desk (local demo data — never a real cellar)` —
every time it runs, not just the first, so Doug is never left unsure
whether he's looking at demo data or a real cellar.

## What this is not

Not a decision about *which* managed provider — Doug is choosing and
provisioning that himself. Not a change to any table, migration, or the
pricing core. Not a replacement for `scripts/desk.sh`'s own embedded
Postgres, which keeps its separate, narrower job.

## Consequences

- `scripts/evidence_backup.py` (new): `dump`/`restore` subcommands,
  foreign-key-ordered table traversal, `DEFAULT_BACKUP_DIR` pointed at the
  Dropbox path above.
- `scripts/desk.mjs`: banner now prints the database host/name line.
- No schema, migration or `app/` change.
- Pending: Doug provisions the managed instance and hands over its
  `DATABASE_URL`. Once that happens, the post-deal dump becomes a real
  operational step (run `scripts/evidence_backup.py dump <DATABASE_URL>`
  after closing a deal) rather than a tested-but-unused mechanism.
