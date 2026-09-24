"""Mainstream-Burgundy control set: run the LOCKED benchmark over verified evidence.

Seller list = Lea & Sandeman live In Bond Burgundy (70 lines). Identity for every
comp below was verified by eye against the L&S wording; wine_id = line id is the
manual identity approval for this control run. Nothing here touches app/core.

Two views:
  A. "as an unrelated seller's list" - L&S counts as one approved merchant.
  B. "L&S as the seller"            - L&S's own offer excluded (the realistic
                                       view if L&S were selling to us).
"""
import json, sys, re
from decimal import Decimal
from datetime import datetime, timezone
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3]))
from app.core.benchmark import benchmark
from app.core.models import Offer, SellerLine
from app.core.enums import DutyStatus, PriceKind, StockType

src = open("lines.js").read()
LINES = [(m[0], int(m[1]), int(m[2]), int(m[3]), Decimal(m[4]))
         for m in re.findall(r'\["(L\d+)",(\d+),(\d+),(\d+),\[.*?\],\[.*?\],(\d+)\]', src)]
assert len(LINES) == 70, len(LINES)
NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)

def off(mid, name, line, price, stype=StockType.UNKNOWN, basis="inferred"):
    lid, v, p, ml, _ = line
    return Offer(offer_id=f"{mid}:{lid}:{price}", merchant_id=mid, merchant=name, wine_id=lid,
                 vintage=v, bottle_ml=ml, pack_size=p, price=Decimal(price), currency="GBP",
                 duty_status=DutyStatus.IN_BOND, price_kind=PriceKind.ASK, is_buyable=True,
                 offered_units=None, stock_type=stype, stock_type_basis=basis, captured_at=NOW)

byid = {l[0]: l for l in LINES}
ext = {}
for m in json.load(open("goedhuis-result.json"))["matches"]:
    if m.get("eligible"):
        ext.setdefault(m["line"], []).append(off("goedhuis", "Goedhuis Waddesdon", byid[m["line"]], m["price"], StockType.BROKERED, "declared"))
for m in json.load(open("lwt-result.json"))["confirmed"]:
    ext.setdefault(m["line"], []).append(off("lwt", "Lay & Wheeler Trading", byid[m["line"]], str(m["price_gbp"])))
for m in json.load(open("albany-result.json"))["confirmed"]:
    ext.setdefault(m["line"], []).append(off("albany", "Albany Vintners", byid[m["line"]], m["price"]))
for m in json.load(open("bi-result.json"))["confirmed"]:
    for p in m["listings"]:
        ext.setdefault(m["line"], []).append(off("bi", "Bordeaux Index", byid[m["line"]], p))

rows = []
for line in LINES:
    lid, v, p, ml, ls = line
    sl = SellerLine(line_id=lid, raw_description=lid, wine_id=lid, vintage=v, bottle_ml=ml, pack_size=p, quantity=1)
    others = ext.get(lid, [])
    A = benchmark(sl, [off("ls", "Lea & Sandeman", line, str(ls))] + others)
    B = benchmark(sl, others)
    rows.append(dict(line=lid, vintage=v, unit=f"{p}x{ml}", ls=str(ls),
        A_state=A.state.value, A_depth=A.comp_count, A_floor=str(A.uk_floor), A_ref=str(A.uk_reference),
        A_flags=sorted(f.value for f in A.flags), A_bests=[f"{o.merchant}:{o.price}" for o in A.merchant_bests],
        A_dupes=A.duplicate_listings,
        B_state=B.state.value, B_depth=B.comp_count, B_ref=str(B.uk_reference) if B.uk_reference else None,
        B_flags=sorted(f.value for f in B.flags)))

json.dump(rows, open("control-benchmark.json", "w"), indent=1)
from collections import Counter
for view in "AB":
    print(view, dict(Counter(r[f"{view}_state"] for r in rows)), dict(Counter(r[f"{view}_depth"] for r in rows)))
for r in rows:
    if r["A_depth"] > 1 or r["B_depth"] > 0:
        print(r["line"], r["vintage"], r["unit"], "A:", r["A_state"], r["A_depth"], "ref", r["A_ref"], r["A_bests"], r["A_flags"], "| B:", r["B_state"], r["B_depth"], r["B_ref"], r["B_flags"])
