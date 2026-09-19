"""Re-run the 20-wine Burgundy proof against the HARDENED core.

Reads the live evidence captured on 2026-09-19, resolves identity through the
registry (so the benchmark only ever sees approved wine_ids), and prints the
corrected states.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.benchmark import benchmark
from app.core.enums import DutyStatus, PriceKind, StockType
from app.core.models import Offer, SellerLine
from app.adapters.condition import normalise_condition
from app.identity.resolver import CanonicalWine, Registry, wine_key

EV = json.load(open(Path(__file__).parent.parent / "tests/fixtures/evidence-2026-09-19.json"))

R = "Domaine Armand Rousseau"
V = "Domaine Comte Georges de Vogue"
M = "Jacques-Frederic Mugnier"

CANON = [
    CanonicalWine("rou-chambertin", R, "Chambertin Grand Cru"),
    CanonicalWine("rou-beze", R, "Chambertin Clos de Beze Grand Cru"),
    CanonicalWine("rou-charmes", R, "Charmes-Chambertin Grand Cru"),
    CanonicalWine("rou-cdlr", R, "Clos de la Roche Grand Cru"),
    CanonicalWine("rou-ruchottes", R, "Ruchottes-Chambertin Grand Cru Clos des Ruchottes"),
    CanonicalWine("rou-gevrey", R, "Gevrey-Chambertin"),
    CanonicalWine("rou-lavaux", R, "Gevrey-Chambertin 1er Cru Lavaux Saint-Jacques"),
    CanonicalWine("vog-musigny-vv", V, "Musigny Grand Cru Cuvee Vieilles Vignes"),
    CanonicalWine("mug-musigny", M, "Musigny Grand Cru"),
]
# Controlled aliases: merchant spellings an operator has approved.
ALIASES = {
    wine_key(R, "Ruchottes-Chambertin Grand Cru"): "rou-ruchottes",   # Rousseau's monopole
    wine_key(V, "Musigny VV"): "vog-musigny-vv",
    wine_key(V, "Musigny Grand Cru"): "vog-musigny-vv",
}
REG = Registry(CANON)
for k, wid in ALIASES.items():
    REG._by_key.setdefault(k, wid)

offers: list[Offer] = []
unresolved = []
for i, o in enumerate(EV["offers"]):
    wid = REG.resolve(o["producer"], o["cuvee"])
    if wid is None:
        unresolved.append((o["merchant"], o["producer"], o["cuvee"]))
        continue
    offers.append(Offer(
        offer_id=f"{o['merchant'][:4].lower()}:{i}",
        merchant_id=o["merchant"].lower().replace(" ", "-"),
        merchant=o["merchant"],
        wine_id=wid,
        vintage=int(o["vintage"]),
        bottle_ml=int(o["ml"]),
        pack_size=int(o["pack"]),
        price=Decimal(str(o["price"])),
        currency=o["ccy"],
        duty_status=DutyStatus(o["duty"]),
        price_kind=PriceKind(o["kind"]),
        is_buyable=o.get("available", True) is not False and (o.get("qty") is None or o["qty"] > 0),
        offered_units=o.get("qty"),
        stock_type=StockType[o["stock_type"]] if o.get("stock_type") else StockType.UNKNOWN,
        stock_type_basis="unconfirmed" if o.get("stock_note") else "inferred",
        condition_flags=normalise_condition(o.get("cond")),
        condition_notes=o.get("cond"),
        source_url=o.get("url"),
    ))

SET = [
    ("Chambertin 2003 Armand Rousseau", "rou-chambertin", 2003, 2),
    ("Chambertin 2005 Armand Rousseau", "rou-chambertin", 2005, 2),
    ("Chambertin 2009 Armand Rousseau", "rou-chambertin", 2009, 3),
    ("Chambertin 2011 Armand Rousseau", "rou-chambertin", 2011, 4),
    ("Chambertin 2012 Armand Rousseau", "rou-chambertin", 2012, 2),
    ("Chambertin Clos de Beze 2003", "rou-beze", 2003, 1),
    ("Chambertin Clos de Beze 2009", "rou-beze", 2009, 4),
    ("Chambertin Clos de Beze 2012", "rou-beze", 2012, 1),
    ("Charmes-Chambertin 2005", "rou-charmes", 2005, 3),
    ("Charmes-Chambertin 2011", "rou-charmes", 2011, 6),
    ("Charmes-Chambertin 2012", "rou-charmes", 2012, 6),
    ("Clos de la Roche 2005", "rou-cdlr", 2005, 1),
    ("Clos de la Roche 2011", "rou-cdlr", 2011, 4),
    ("Clos de la Roche 2013", "rou-cdlr", 2013, 3),
    ("Ruchottes CdR 2013", "rou-ruchottes", 2013, 2),
    ("Ruchottes CdR 2014", "rou-ruchottes", 2014, 2),
    ("Musigny 2002 De Vogue", "vog-musigny-vv", 2002, 2),
    ("Musigny 2005 De Vogue", "vog-musigny-vv", 2005, 3),
    ("Musigny 2009 De Vogue", "vog-musigny-vv", 2009, 6),
    ("Musigny 2009 Mugnier", "mug-musigny", 2009, 6),
]

print(f"offers normalised: {len(offers)}   unresolved identities: {len(unresolved)}")
for u in unresolved:
    print("   UNRESOLVED:", u)
print()

hdr = "{:<4} {:<34} {:>5} {:>9} {:>9} {:>9}  {:<10} {:<28} {}"
print(hdr.format("ID", "WINE (loose 75cl bottle)", "COMPS", "FLOOR", "REF", "MEDIAN",
                 "STATE", "FLAGS", "X-UNIT"))
print("-" * 140)
ready = review = nomkt = 0
for i, (raw, wid, vintage, qty) in enumerate(SET, 1):
    ln = SellerLine(f"L{i}", raw, wid, vintage, 750, 1, qty)
    r = benchmark(ln, offers)
    f = lambda x: "-" if x is None else f"£{x:,.0f}"
    xs = ", ".join(f"{c.offer.pack_size}x@£{c.per_bottle:,.0f}/btl" for c in r.cross_unit) or "-"
    print(hdr.format(ln.line_id, raw[:34], r.comp_count, f(r.uk_floor), f(r.uk_reference),
                     f(r.uk_median), r.state.value,
                     ",".join(sorted(x.value for x in r.flags))[:28], xs[:40]))
    ready += r.state.value == "READY"
    review += r.state.value == "REVIEW"
    nomkt += r.state.value == "NO_MARKET"

print(f"\nREADY {ready}   REVIEW {review}   NO_MARKET {nomkt}")

# --- sensitivity: what if the seller's parcel were 6-packs rather than loose? ---
print("\nIf the same wines were offered as 6x75cl cases instead of loose bottles:")
hdr2 = "{:<4} {:<32} {:>5} {:>5}  {:>9} {:>9}  {}"
print(hdr2.format("ID", "WINE", "BTL", "6PK", "FLOOR", "REF", "MERCHANTS"))
print("-" * 120)
d1 = d2 = 0
for i, (raw, wid, vintage, qty) in enumerate(SET, 1):
    b = benchmark(SellerLine(f"L{i}", raw, wid, vintage, 750, 1, qty), offers)
    c = benchmark(SellerLine(f"L{i}", raw, wid, vintage, 750, 6, 1), offers)
    d1 += b.comp_count >= 2
    d2 += c.comp_count >= 2
    f = lambda x: "-" if x is None else f"£{x:,.0f}"
    ms = ", ".join(sorted({o.merchant.split()[0] for o in c.merchant_bests})) or "-"
    print(hdr2.format(f"L{i}", raw[:32], b.comp_count, c.comp_count,
                      f(c.uk_floor), f(c.uk_reference), ms))
print(f"\ndepth >= 2 merchants — bottle unit: {d1}/20   6-pack unit: {d2}/20")
