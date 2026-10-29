#!/usr/bin/env bash
# The one command: sets up whatever's missing, then opens Cellar Desk.
#
#   scripts/desk.sh            reuse existing demo data (or seed it, first run)
#   scripts/desk.sh --reseed   drop the demo deals and seed them fresh
#
# No Docker, no psql, no Postgres.app required -- see scripts/desk.mjs for
# why and how. Safe to run more than once: it only sets up what's missing
# and reuses what's already there.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import app" 2>/dev/null; then
  echo "Setting up the Python environment…"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -e ".[dev]"
fi

if [ ! -d web/node_modules ]; then
  echo "Installing dependencies (this only happens once)…"
  (cd web && npm install --no-audit --no-fund --silent)
fi

# scripts/desk.mjs imports "embedded-postgres" as an ES module, and ESM
# resolution does not honour NODE_PATH (that is a require()-only, legacy
# mechanism) -- it walks up from scripts/ looking for a node_modules
# directory, same as any other import, so a symlink to web's is enough and
# needs no special-casing in desk.mjs itself.
if [ ! -L scripts/node_modules ]; then
  ln -sf ../web/node_modules scripts/node_modules
fi

exec node scripts/desk.mjs "$@"
