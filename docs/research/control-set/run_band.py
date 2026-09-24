"""The vintage band over the 70-line control set: what it moves, and what it can't see.

`run_control.py` is the "before": the locked benchmark over the same verified
evidence, with `wine_id = line id`. That keying is why the band cannot act there
at all — every vintage of a wine is its own wine_id, so nothing has a
neighbouring vintage. This script fixes only that, and changes no evidence:

  * Identity spans vintages. Lines sharing the same required tokens and the same
    unit are one wine, which is what the tokens already mean ("a merchant record
    matches only if its normalised title contains EVERY required token"). The
    benchmark screens by vintage anyway, so no Floor, Reference or Median moves
    because of this — it only lets the band see the neighbours.
  * Colour comes from Lea & Sandeman's own list (the COLOUR cell of the captured
    HTML), never from a guess here. The register is keyed by region AND colour:
    2014 Burgundy is tier 3 red and tier 1 white. A line we cannot match to a
    list row has no colour, so it gets no band — the correct failure.

Run from this directory: python run_band.py
"""
from __future__ import annotations

import collections
import json
import re
import sys
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from app.adapters.lea_sandeman import dedupe_rows, parse_rows          # noqa: E402
from app.core.benchmark import benchmark                               # noqa: E402
from app.core.enums import DutyStatus, PriceKind, StockType            # noqa: E402
from app.core.models import Offer, SellerLine                          # noqa: E402
from app.identity.resolver import strip_accents                        # noqa: E402
from app.market.vintage_band import (                                  # noqa: E402
    band_flags, check_vintage_band, without_high_outliers)

NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)
COLOUR, VINTAGE, WINE = 1, 2, 3

LINE_RE = re.compile(r'\["(L\d+)",(\d+),(\d+),(\d+),\[(.*?)\],\[(.*?)\],(\d+)\]')


def tokens(field: str) -> list[str]:
    return [t.strip().strip('"') for t in field.split(",") if t.strip()]


def normalise(text: str) -> str:
    """Accents first, or "Épenots" never matches the token "epenots" — the same
    trap app/identity/resolver.py exists to handle."""
    return re.sub(r"[^a-z0-9 ]", " ", strip_accents(text).lower())


def read_lines() -> list[dict]:
    out = []
    for lid, v, pack, ml, req, exc, price in LINE_RE.findall((HERE / "lines.js").read_text()):
        out.append({"id": lid, "vintage": int(v), "pack": int(pack), "ml": int(ml),
                    "require": tokens(req), "exclude": tokens(exc), "ls": Decimal(price)})
    assert len(out) == 70, len(out)
    return out


def colours() -> dict[str, str]:
    """{line id: 'Red'|'White'} from Lea & Sandeman's own COLOUR cell."""
    rows = dedupe_rows(parse_rows(
        (ROOT / "tests/fixtures/lea-sandeman-list-2026-09-23.html").read_text()))
    found = {}
    for line in read_lines():
        matches = {r["cells"][COLOUR].strip() for r in rows
                   if r["cells"][VINTAGE].strip() == str(line["vintage"])
                   and all(t in normalise(r["cells"][WINE]) for t in line["require"])
                   and not any(t in normalise(r["cells"][WINE]) for t in line["exclude"])}
        if len(matches) == 1:                     # one colour or no colour: never a vote
            found[line["id"]] = matches.pop()
    return found


def register() -> dict[str, dict[int, int]]:
    import csv
    with (ROOT / "docs/research/vintage-tiers.csv").open(newline="", encoding="utf-8") as fh:
        out: dict[str, dict[int, int]] = collections.defaultdict(dict)
        for row in csv.DictReader(fh):
            out[row["region"]][int(row["vintage"])] = int(row["tier"])
    return dict(out)


def offer(merchant_id: str, merchant: str, line: dict, wine_id: str, price,
          stock_type=StockType.UNKNOWN, basis="inferred") -> Offer:
    return Offer(offer_id=f"{merchant_id}:{line['id']}:{price}", merchant_id=merchant_id,
                 merchant=merchant, wine_id=wine_id, vintage=line["vintage"],
                 bottle_ml=line["ml"], pack_size=line["pack"], price=Decimal(price),
                 currency="GBP", duty_status=DutyStatus.IN_BOND, price_kind=PriceKind.ASK,
                 is_buyable=True, offered_units=None, stock_type=stock_type,
                 stock_type_basis=basis, captured_at=NOW)


def main() -> None:
    lines = read_lines()
    by_id = {line["id"]: line for line in lines}
    colour_of = colours()
    tiers = register()

    # Identity that spans vintages: same required tokens, same unit, one wine.
    wine_of, members = {}, collections.defaultdict(list)
    for line in lines:
        key = (tuple(line["require"]), tuple(line["exclude"]), line["pack"], line["ml"])
        wine_of[line["id"]] = "w:" + "|".join(line["require"]) + f":{line['pack']}x{line['ml']}"
        members[wine_of[line["id"]]].append(line["id"])

    offers = collections.defaultdict(list)
    for line in lines:
        offers[line["id"]].append(
            offer("ls", "Lea & Sandeman", line, wine_of[line["id"]], str(line["ls"])))
    for match in json.load((HERE / "goedhuis-result.json").open())["matches"]:
        if match.get("eligible"):
            line = by_id[match["line"]]
            offers[line["id"]].append(offer("goedhuis", "Goedhuis Waddesdon", line,
                                            wine_of[line["id"]], match["price"],
                                            StockType.BROKERED, "declared"))
    for match in json.load((HERE / "lwt-result.json").open())["confirmed"]:
        line = by_id[match["line"]]
        offers[line["id"]].append(offer("lwt", "Lay & Wheeler Trading", line,
                                        wine_of[line["id"]], str(match["price_gbp"])))
    for match in json.load((HERE / "albany-result.json").open())["confirmed"]:
        line = by_id[match["line"]]
        offers[line["id"]].append(offer("albany", "Albany Vintners", line,
                                        wine_of[line["id"]], match["price"]))
    for match in json.load((HERE / "bi-result.json").open())["confirmed"]:
        line = by_id[match["line"]]
        for price in match["listings"]:
            offers[line["id"]].append(offer("bi", "Bordeaux Index", line,
                                            wine_of[line["id"]], price))

    everything = [o for group in offers.values() for o in group]

    moved, banded, quiet = [], [], collections.Counter()
    before_states, after_states = collections.Counter(), collections.Counter()
    for line in lines:
        seller = SellerLine(line_id=line["id"], raw_description=line["id"],
                            wine_id=wine_of[line["id"]], vintage=line["vintage"],
                            bottle_ml=line["ml"], pack_size=line["pack"], quantity=1)
        run = benchmark(seller, everything, as_of=NOW)
        before_states[run.state.value] += 1
        was = (run.state.value, run.uk_reference)

        colour = colour_of.get(line["id"])
        key = f"BURGUNDY_{colour.upper()}" if colour else None
        check = check_vintage_band(seller, run.comparables, neighbour_offers=everything,
                                   other_format_offers=everything, as_of=NOW,
                                   tiers=tiers.get(key))
        flags = band_flags(check)
        if flags or check.high_outliers:
            seller = replace(seller, inherited_flags=flags)
            kept = without_high_outliers(everything, check) if check.high_outliers else everything
            run = benchmark(seller, kept, as_of=NOW)
        after_states[run.state.value] += 1

        if check.ran:
            banded.append((line, check, run))
        else:
            quiet[(check.note or "no note").split("(")[0].strip()] += 1
        if (run.state.value, run.uk_reference) != was:
            moved.append((line, was, (run.state.value, run.uk_reference), check))

    print(f"70 control lines · colour read from the L&S list for {len(colour_of)} of them\n")
    print("state, before the band:", dict(before_states))
    print("state, after the band: ", dict(after_states))
    print(f"\nlines with a band: {len(banded)}")
    for reason, n in quiet.most_common():
        print(f"  quiet on {n:>2}: {reason}")

    if banded:
        print("\nThe bands that were computed:")
        for line, check, run in banded:
            neighbours = ",".join(f"{n.vintage}(t{n.tier})" for n in check.neighbours)
            print(f"  {line['id']} {line['vintage']} {'/'.join(line['require'])[:34]:<34} "
                  f"comps {run.comp_count} ref {run.uk_reference} · "
                  f"band £{check.band_low}-£{check.band_high} from {neighbours}")

    print(f"\nlines the band moved: {len(moved)}")
    for line, was, now, check in moved:
        print(f"  {line['id']}: {was[0]} ref {was[1]} -> {now[0]} ref {now[1]}")
        for ref in check.high_outliers:
            print(f"       excluded {ref.merchant} £{ref.price} "
                  f"({ref.multiple:.2f}x the £{ref.edge} edge)")
        for ref in check.low_outliers:
            print(f"       flagged low {ref.merchant} £{ref.price} (kept)")


if __name__ == "__main__":
    main()
