"""Seed the REAL Champagne sweep into a Cellar Desk deal -- not three
invented rows. The 30 lines this cellar's 9 October 2026 benchmark run
actually priced: real producers, real cuvées, real bottle counts, and
each line's real per-merchant GBP asking price, so the deterministic
engine derives its own floor/reference/comp_count exactly as it did live
-- nothing here hardcodes a result.

Source: docs/research/cellar-desk-ui-spec.html's own `ROWS` literal (the
interactive prototype Doug built against this same run), with each
`sources[].p` figure (published there already converted to HK$ for
display, confirmed by dividing every one-merchant line's figure by the
spec's own FX constant, 10.37, and finding it lands on that line's `ref`
to the penny) converted back to the real GBP price it started as. The
other 54 Champagne lines in docs/research/cellar-wfs-normalised.csv never
found a comparable at all (NO_MARKET) and are not part of this deal --
Cellar Desk only ever shows a priced line.

Expect, once benchmarked and priced: 3 lines READY (two merchants, within
10% of each other -- decision 0028), 27 in REVIEW (19 on one merchant,
8 on two merchants more than 10% apart), HK$881,577 of total market value
at the spec's own FX rate.

Idempotent, like scripts/seed_cellar_desk_demo.py (kept as-is, the fast
three-row fixture): reuses the deal by name rather than seeding a second
copy. Run with DATABASE_URL pointed at a real Postgres.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import repo
from app.db.connection import transaction
from app.worker import jobs
from seed_cellar_desk_demo import OPERATOR_PASSWORD, OPERATOR_USERNAME, ensure_operator, ensure_wine

DEAL_NAME = "WFS Cellar · Champagne"

LINES = [
    {"producer": "Krug", "cuvee": "Grande Cuvée 167ᵉ", "vintage": 1000, "bottles": 48, "bottle_ml": 750,
     "offers": [("bordeaux-index", "162.87")]},
    {"producer": "Dom Pérignon", "cuvee": "Vintage", "vintage": 2008, "bottles": 46, "bottle_ml": 750,
     "offers": [("bordeaux-index", "162.49"), ("justerini-brooks", "165.00")]},
    {"producer": "Krug", "cuvee": "Grande Cuvée 168ᵉ", "vintage": 1000, "bottles": 36, "bottle_ml": 750,
     "offers": [("bordeaux-index", "158.34")]},
    {"producer": "Krug", "cuvee": "Grande Cuvée 169ᵉ", "vintage": 1000, "bottles": 25, "bottle_ml": 750,
     "offers": [("bordeaux-index", "163.16")]},
    {"producer": "Louis Roederer", "cuvee": "Cristal", "vintage": 2005, "bottles": 24, "bottle_ml": 750,
     "offers": [("bordeaux-index", "194.79"), ("lw-trading", "211.86")]},
    {"producer": "Krug", "cuvee": "Grande Cuvée 164ᵉ", "vintage": 1000, "bottles": 24, "bottle_ml": 750,
     "offers": [("bordeaux-index", "292.48")]},
    {"producer": "Krug", "cuvee": "Grande Cuvée 166ᵉ", "vintage": 1000, "bottles": 24, "bottle_ml": 750,
     "offers": [("bordeaux-index", "162.20")]},
    {"producer": "Dom Pérignon", "cuvee": "Vintage", "vintage": 2010, "bottles": 24, "bottle_ml": 750,
     "offers": [("bordeaux-index", "143.30"), ("lw-trading", "177.53")]},
    {"producer": "Dom Pérignon", "cuvee": "Vintage", "vintage": 2004, "bottles": 18, "bottle_ml": 750,
     "offers": [("bordeaux-index", "138.86"), ("lw-trading", "176.47")]},
    {"producer": "Taittinger", "cuvee": "Comtes de Champagne Rosé", "vintage": 2009, "bottles": 15, "bottle_ml": 750,
     "offers": [("bordeaux-index", "116.68"), ("lw-trading", "131.34")]},
    {"producer": "Charles Heidsieck", "cuvee": "Blanc des Millénaires", "vintage": 2004, "bottles": 13, "bottle_ml": 750,
     "offers": [("bordeaux-index", "102.51")]},
    {"producer": "Henri Giraud", "cuvee": "Aÿ Grand Cru Argonne", "vintage": 2012, "bottles": 13, "bottle_ml": 750,
     "offers": [("bordeaux-index", "478.98")]},
    {"producer": "Krug", "cuvee": "Grande Cuvée 163ᵉ", "vintage": 1000, "bottles": 12, "bottle_ml": 750,
     "offers": [("bordeaux-index", "191.51")]},
    {"producer": "Krug", "cuvee": "Grande Cuvée 165ᵉ", "vintage": 1000, "bottles": 12, "bottle_ml": 750,
     "offers": [("bordeaux-index", "212.83")]},
    {"producer": "Dom Pérignon", "cuvee": "Vintage", "vintage": 2005, "bottles": 12, "bottle_ml": 750,
     "offers": [("bordeaux-index", "175.51")]},
    {"producer": "Dom Pérignon", "cuvee": "Vintage", "vintage": 2013, "bottles": 12, "bottle_ml": 750,
     "offers": [("bordeaux-index", "133.37")]},
    {"producer": "Dom Pérignon", "cuvee": "Rosé", "vintage": 2006, "bottles": 12, "bottle_ml": 750,
     "offers": [("bordeaux-index", "249.95"), ("lw-trading", "264.32")]},
    {"producer": "Louis Roederer", "cuvee": "Cristal", "vintage": 2006, "bottles": 12, "bottle_ml": 750,
     "offers": [("bordeaux-index", "154.19"), ("lw-trading", "196.34")]},
    {"producer": "Taittinger", "cuvee": "Comtes de Champagne", "vintage": 2004, "bottles": 12, "bottle_ml": 750,
     "offers": [("bordeaux-index", "116.68")]},
    {"producer": "Taittinger", "cuvee": "Comtes de Champagne", "vintage": 2007, "bottles": 12, "bottle_ml": 750,
     "offers": [("bordeaux-index", "96.62")]},
    {"producer": "Taittinger", "cuvee": "Comtes de Champagne", "vintage": 2008, "bottles": 12, "bottle_ml": 750,
     "offers": [("bordeaux-index", "142.33"), ("lw-trading", "200.00")]},
    {"producer": "Charles Heidsieck", "cuvee": "Blanc des Millénaires", "vintage": 2006, "bottles": 12, "bottle_ml": 750,
     "offers": [("bordeaux-index", "88.33"), ("lw-trading", "104.63")]},
    {"producer": "Louis Roederer", "cuvee": "Cristal", "vintage": 2007, "bottles": 6, "bottle_ml": 750,
     "offers": [("bordeaux-index", "158.34"), ("lw-trading", "189.97")]},
    {"producer": "Taittinger", "cuvee": "Comtes de Champagne", "vintage": 2005, "bottles": 6, "bottle_ml": 750,
     "offers": [("bordeaux-index", "91.71")]},
    {"producer": "Taittinger", "cuvee": "Comtes de Champagne", "vintage": 2006, "bottles": 6, "bottle_ml": 750,
     "offers": [("bordeaux-index", "94.99"), ("goedhuis", "149.18")]},
    {"producer": "Taittinger", "cuvee": "Comtes de Champagne Rosé", "vintage": 2011, "bottles": 6, "bottle_ml": 750,
     "offers": [("bordeaux-index", "140.98")]},
    {"producer": "Charles Heidsieck", "cuvee": "Blanc des Millénaires", "vintage": 1995, "bottles": 6, "bottle_ml": 750,
     "offers": [("bordeaux-index", "166.63")]},
    {"producer": "Pierre Peters", "cuvee": "Les Chétillons", "vintage": 2016, "bottles": 6, "bottle_ml": 750,
     "offers": [("bordeaux-index", "227.00")]},
    {"producer": "Taittinger", "cuvee": "Comtes de Champagne Rosé", "vintage": 2008, "bottles": 3, "bottle_ml": 750,
     "offers": [("bordeaux-index", "166.63")]},
    {"producer": "Louis Roederer", "cuvee": "Cristal", "vintage": 2006, "bottles": 1, "bottle_ml": 1500,
     "offers": [("bordeaux-index", "384.96")]},
]


def vintage_label(vintage: int) -> str:
    return "NV" if vintage == 1000 else str(vintage)


def main() -> None:
    with transaction() as conn:
        operator_id = ensure_operator(conn)

        existing = conn.execute("SELECT deal_id FROM deal WHERE name = %s",
                                (DEAL_NAME,)).fetchone()
        if existing is not None:
            print(f"deal_id={existing['deal_id']}")
            print(f"operator_username={OPERATOR_USERNAME}")
            return

        wine_ids = [ensure_wine(conn, ln["producer"], ln["cuvee"]) for ln in LINES]

        deal = repo.create_deal(conn, {
            "name": DEAL_NAME, "seller": "WFS",
            "source_file": "docs/research/cellar-wfs-normalised.csv", "currency": "GBP",
            "target_margin": None, "buyer_discount": None, "margin_on_sale": None,
            "created_by": operator_id,
        }, [
            {"row_index": i,
             "raw_description": f"{ln['producer']} {ln['cuvee']} {vintage_label(ln['vintage'])} x{ln['bottles']}",
             "raw_row": {"producer": ln["producer"], "cuvee": ln["cuvee"],
                        "vintage": vintage_label(ln["vintage"]), "bottles": ln["bottles"]},
             "quantity": ln["bottles"], "cost": None, "cost_currency": None,
             "target_margin": None, "target_discount": None, "manual_price": None}
            for i, ln in enumerate(LINES)
        ])
        deal_id = str(deal["deal_id"])
        by_index = {row["row_index"]: row for row in repo.deal_lines(conn, deal_id)}

        for i, ln in enumerate(LINES):
            repo.set_line_identity(conn, str(by_index[i]["line_id"]), wine_id=wine_ids[i],
                                   vintage=ln["vintage"], bottle_ml=ln["bottle_ml"], pack_size=1,
                                   flags=[], source="operator", approved_by=operator_id)

        # One snapshot, every merchant it mentions covered once -- same
        # reasoning as seed_cellar_desk_demo.seed_snapshot: a merchant's
        # offers must all live in one snapshot or an earlier one stops
        # counting (repo._SOURCES_CTE picks each merchant's single latest
        # snapshot_merchant row).
        captured_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        snap = conn.execute(
            "INSERT INTO snapshot (captured_at, schema_version) VALUES (%s, 'desk-real') "
            "RETURNING snapshot_id", (captured_at,)).fetchone()
        merchants_done: set[str] = set()
        offer_seq = 0
        for i, ln in enumerate(LINES):
            for merchant_id, price in ln["offers"]:
                if merchant_id not in merchants_done:
                    conn.execute(
                        """INSERT INTO snapshot_merchant (snapshot_id, merchant_id, status,
                                                          captured_at, offers_written)
                           VALUES (%s, %s, 'ok', %s, 1)""",
                        (snap["snapshot_id"], merchant_id, captured_at))
                    merchants_done.add(merchant_id)
                offer_seq += 1
                conn.execute(
                    """INSERT INTO offer (snapshot_id, offer_id, merchant_id, wine_id, vintage,
                                          bottle_ml, pack_size, price, currency, duty_status,
                                          price_kind, is_buyable, offered_units, captured_at)
                       VALUES (%s, %s, %s, %s, %s, %s, 1, %s, 'GBP', 'IB', 'ASK', true, 6, %s)""",
                    (snap["snapshot_id"], f"{merchant_id}:desk-real-{offer_seq}", merchant_id,
                     wine_ids[i], ln["vintage"], ln["bottle_ml"], price, captured_at))

    print(f"deal_id={deal_id}")
    jobs.benchmark_deal(deal_id)
    jobs.price_deal(deal_id, priced_by=operator_id)
    print(f"operator_username={OPERATOR_USERNAME}")


if __name__ == "__main__":
    main()
