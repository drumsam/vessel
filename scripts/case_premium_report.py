#!/usr/bin/env python
"""What the collected pairs say the case premium is.

    python scripts/case_premium_report.py
    python scripts/case_premium_report.py --bottle-ml 750

Every capture records each wine it met in two pack sizes (decision 0016). This
reads those pairs back and prints the number CASE_PREMIUM should be, per
merchant and overall.

Read it the way the measurement document does. The median is the candidate
constant. The spread is the reason a derived comparable is flagged whatever the
median says: on the 27 pairs this started from, a quarter sat more than 5% from
parity, with tails at -30% and +15%. A constant describes a merchant's pricing
policy; it never describes an individual wine.

Loose-against-case pairs only, because that is the ratio the constant is about.
Case-to-case derivation applies no premium at all, and its pairs are stored but
not counted here.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.flags import CASE_PREMIUM                     # noqa: E402
from app.db import repo                                     # noqa: E402
from app.db.connection import transaction                   # noqa: E402
from app.market.units import PREMIUM_EVIDENCE               # noqa: E402

#: Below this the sample is too small to move a constant that moves prices.
#: "After a few hundred observations across five or six merchants the constant
#: stops being a judgement call" — docs/research/case-premium-measurement.md.
ENOUGH_PAIRS = 300
ENOUGH_MERCHANTS = 5


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bottle-ml", type=int, default=750,
                    help="derivation is 750ml only, so this is what the constant is about")
    args = ap.parse_args()

    with transaction() as conn:
        rows = repo.case_premium_summary(conn, args.bottle_ml)

    if not rows:
        print("No paired observations yet. Every capture records them as it goes.")
        return

    merchants = [r for r in rows if r["merchant_id"]]
    [overall] = [r for r in rows if r["merchant_id"] is None] or [None]

    print(f"Loose-against-case pairs at {args.bottle_ml}ml\n")
    head = "{:<22} {:>6} {:>9} {:>9} {:>9} {:>9} {:>12}"
    print(head.format("MERCHANT", "PAIRS", "MEDIAN", "MEAN", "LOW", "HIGH", ">5% FROM 1"))
    print("-" * 82)
    for r in merchants + ([overall] if overall else []):
        print(head.format(
            r["merchant_id"] or "ALL", r["pairs"], f"{r['median']:.4f}", f"{r['mean']:.4f}",
            f"{r['low']:.4f}", f"{r['high']:.4f}",
            f"{r['beyond_5pct']} of {r['pairs']}"))

    if overall:
        print(f"\nCASE_PREMIUM is {CASE_PREMIUM}. These pairs say {overall['median']:.4f}.")
        if overall["median"] != CASE_PREMIUM:
            print("  They disagree. Changing the constant moves prices, so it is a "
                  "decision record and a pull request, not an edit.")
        print(f"  Measured from {overall['first_seen']:%Y-%m-%d} to "
              f"{overall['last_seen']:%Y-%m-%d}.")

    enough = overall and overall["pairs"] >= ENOUGH_PAIRS and len(merchants) >= ENOUGH_MERCHANTS
    print(f"\n{overall['pairs'] if overall else 0} pairs across {len(merchants)} merchant(s). "
          + ("Enough to settle the constant on evidence."
             if enough else
             f"Not yet enough — the bar is {ENOUGH_PAIRS} pairs across "
             f"{ENOUGH_MERCHANTS} merchants. Until then the constant rests on "
             f"{PREMIUM_EVIDENCE['pairs']} pairs from "
             f"{PREMIUM_EVIDENCE['merchant']} alone."))
    print("Whatever the median, a derived comparable stays flagged: the spread is "
          "about individual wines, and no constant fixes that.")


if __name__ == "__main__":
    main()
