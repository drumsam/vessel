#!/usr/bin/env python
"""Post a MrBridge Wine-Searcher export into VESSEL (decisions 0048, 0049).

    python scripts/post_mrbridge_batch.py ~/Downloads/dataset_....json --limit 5 --dry-run
    python scripts/post_mrbridge_batch.py ~/Downloads/dataset_....json --limit 5

Reads the export, converts it with app.feed.mrbridge (the same converter the
tests pin), and posts it to POST /market-evidence/batches in chunks. Prints
only the conversion overview and each import summary — never the feed token.
The token is read from MARKET_FEED_TOKEN, or from .env.feed-token at the repo
root (git-ignored, owner-only).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.feed import mrbridge  # noqa: E402

DEFAULT_API = "https://uk-fine-wine-pricer-api.vercel.app"
#: Well inside the importer's 5,000 cap and Vercel's 60s and 4.5MB limits.
CHUNK = 300


def feed_token() -> str:
    token = os.environ.get("MARKET_FEED_TOKEN", "").strip()
    path = ROOT / ".env.feed-token"
    if not token and path.exists():
        for line in path.read_text().splitlines():
            if line.startswith("MARKET_FEED_TOKEN="):
                token = line.split("=", 1)[1].strip()
    if not token:
        raise SystemExit("no feed token: set MARKET_FEED_TOKEN or create .env.feed-token")
    return token


def chunks(observations: list[dict], size: int = CHUNK) -> list[list[dict]]:
    return [observations[i:i + size] for i in range(0, len(observations), size)]


def overview(observations: list[dict]) -> list[str]:
    """One line per observation: what was read, with no prices hidden and no
    secret involved — so a dry run shows exactly what would be sent."""
    out = []
    for o in observations:
        out.append(" | ".join([
            str(o["raw"].get("inputValue")),
            f"{o['wine']['producer']} / {o['wine']['name']}",
            f"vintage {o['vintage']}",
            f"size {o['bottle_ml'] or 'not stated'}",
            f"{o['kind'].lower().replace('_', ' ')}",
            f"{o['currency']} {o['price']}",
            f"{o['merchant']['name']}",
            f"{o['raw'].get('offersCount')} offers",
        ]))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path, help="MrBridge dataset JSON")
    parser.add_argument("--limit", type=int, help="only the first N rows (start small)")
    parser.add_argument("--dry-run", action="store_true", help="convert and show; post nothing")
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()

    rows = json.loads(args.export.expanduser().read_text())
    if args.limit:
        rows = rows[:args.limit]
    batch, skipped = mrbridge.to_batch(rows)
    observations = batch["observations"]
    print(f"{len(rows)} rows read, {len(observations)} converted, {len(skipped)} skipped")
    for s in skipped:
        print(f"  skipped #{s['index']} {s['inputValue']!r}: {s['reason']}")
    for line in overview(observations):
        print(f"  {line}")
    if args.dry_run or not observations:
        print("dry run: nothing posted" if args.dry_run else "nothing to post")
        return

    import httpx
    headers = {"Authorization": f"Bearer {feed_token()}"}
    for n, part in enumerate(chunks(observations), start=1):
        r = httpx.post(f"{args.api}/market-evidence/batches", headers=headers, timeout=60,
                       json={"source": batch["source"], "observations": part})
        if r.status_code != 200:
            detail = r.json().get("detail") if r.headers.get("content-type", "").startswith(
                "application/json") else r.text[:200]
            raise SystemExit(f"chunk {n}: HTTP {r.status_code} — {detail}")
        print(f"chunk {n} imported:")
        print(json.dumps(r.json(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
