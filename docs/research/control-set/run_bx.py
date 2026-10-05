"""Bordeaux control set: locked benchmark over verified evidence, 26 Sep 2026.
Seller list = Lea & Sandeman live In Bond Bordeaux (50 lines). Identity verified by eye.
View A: L&S counts as one merchant. View B: L&S is the seller, excluded."""
import json, sys
from decimal import Decimal
from datetime import datetime, timezone
sys.path.insert(0, "/home/claude/repo")
from app.core.benchmark import benchmark
from app.core.models import Offer, SellerLine
from app.core.enums import DutyStatus, PriceKind, StockType

LINES = json.load(open("bx-lines.json"))
byid = {l[0]: l for l in LINES}
NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)

EV = {
 "farr":        {"B03":300,"B09":212,"B29":395,"B31":330,"B39":90,"B42":300},
 "albany":      {"B01":205,"B02":147,"B03":260,"B09":230,"B10":325,"B11":260,"B12":130,"B13":160,
                 "B15":129,"B24":245,"B27":680,"B33":165,"B44":510},
 "vinum":       {"B04":325,"B10":200},
 "goedhuis":    {"B35":740,"B39":90,"B48":900},
 "bi":          {"B01":207,"B02":146,"B03":259,"B04":298,"B10":175,"B11":250,"B13":200,"B15":127,
                 "B19":500,"B22":628,"B24":300,"B27":415,"B28":238,"B29":399,"B31":317,"B33":195,
                 "B34":398,"B38":546,"B42":295,"B43":244,"B44":500,"B45":321,"B48":885,"B50":556},
}
NAMES = {"farr":"Farr Vintners","albany":"Albany Vintners","vinum":"Vinum Fine Wines",
         "goedhuis":"Goedhuis Waddesdon","bi":"Bordeaux Index","ls":"Lea & Sandeman"}

def off(mid, lid, price, stype=StockType.UNKNOWN, basis="inferred"):
    _, v, p, ml = byid[lid][1], byid[lid][1], byid[lid][2], byid[lid][3]
    return Offer(offer_id=f"{mid}:{lid}", merchant_id=mid, merchant=NAMES[mid], wine_id=lid,
                 vintage=byid[lid][1], bottle_ml=ml, pack_size=p, price=Decimal(str(price)),
                 currency="GBP", duty_status=DutyStatus.IN_BOND, price_kind=PriceKind.ASK,
                 is_buyable=True, offered_units=None, stock_type=stype, stock_type_basis=basis,
                 captured_at=NOW)

rows = []
for L in LINES:
    lid, v, p, ml, ls = L[0], L[1], L[2], L[3], L[6]
    sl = SellerLine(line_id=lid, raw_description=L[8], wine_id=lid, vintage=v,
                    bottle_ml=ml, pack_size=p, quantity=1)
    others = []
    for mid, m in EV.items():
        if lid in m:
            st = (StockType.BROKERED, "declared") if mid == "goedhuis" else (StockType.UNKNOWN, "inferred")
            others.append(off(mid, lid, m[lid], *st))
    A = benchmark(sl, [off("ls", lid, ls)] + others)
    B = benchmark(sl, others)
    rows.append(dict(line=lid, name=L[8], unit=f"{p}x{ml}", ls=ls,
        A_state=A.state.value, A_depth=A.comp_count, A_ref=str(A.uk_reference), A_floor=str(A.uk_floor),
        A_flags=sorted(f.value for f in A.flags),
        B_state=B.state.value, B_depth=B.comp_count, B_ref=str(B.uk_reference) if B.uk_reference else None,
        B_flags=sorted(f.value for f in B.flags),
        bests=[f"{o.merchant}:{o.price}" for o in A.merchant_bests]))
json.dump(rows, open("bx-benchmark.json","w"), indent=1)
from collections import Counter
for view in "AB":
    print(view, dict(Counter(r[f"{view}_state"] for r in rows)), "depth", dict(sorted(Counter(r[f"{view}_depth"] for r in rows).items())))
print()
for r in rows:
    if r["B_depth"] >= 1:
        print(f'{r["line"]} {r["ls"]:>5} {r["B_state"]:<9} d{r["B_depth"]} ref {r["B_ref"] or "-":>7} {",".join(r["B_flags"]) or "-":<28} {r["name"][:34]:<34} {r["bests"]}')
