# VESSEL Market Data

A small Python/SQLite evidence subsystem for VESSEL Pocket. It records original source evidence and serves cached merchant, transaction and optional liquidity summaries. It never recommends a price or makes a buying decision.

The repository was empty when this subsystem was built. Pocket and the canonical VESSEL identity service are **not present**. No parallel identity taxonomy or fuzzy matcher is provided: the default resolver preserves imports as unresolved evidence, and these rows never enter market summaries. Live feeds, licensed data and production deployment require integration.

## Run locally

Python 3.12 or later:

```sh
cd /workspace/vessel
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m services.market_data init
.venv/bin/python -m pytest -q
.venv/bin/python -m services.market_data serve
```

The internal API binds to `127.0.0.1:8765`. It is intended for trusted local use. Put authentication and a production HTTP gateway in front before making it accessible to other machines. Data lives in ignored `var/market-data.sqlite3`; processes need restarting on a restored machine.

## Import auction evidence

```sh
.venv/bin/python -m services.market_data import-auction examples/auction.csv --source example-auction
```

The example is explicitly fictional and stays unresolved. Run against a separate database when exploring examples (`--db var/example.sqlite3` before the subcommand). Reimporting identical evidence is idempotent. Both CSV and XLSX are supported; unsupported formats and bad rows are reported, with nonzero exit status for partial or failed imports. Source runs persist counts and status. A written unresolved row is valid evidence, not a rejected row.

See [the service contract](docs/market-data.md) for integration and evidence semantics, and [coverage planning](docs/coverage.md) for Core onboarding.
