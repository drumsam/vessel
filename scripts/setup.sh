#!/usr/bin/env bash
set -euo pipefail
cd /workspace/vessel
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m services.market_data init
