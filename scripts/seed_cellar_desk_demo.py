"""One-off: seed a small, real-shaped Cellar Desk deal for manual UI testing.

Not a fixture, not committed to any test suite -- a throwaway demo deal with
a thin (one-merchant) line, a strong (two merchants, <10% apart) line and an
"ok" (two merchants, >10% apart) line, matching the three badge tiers
docs/research/cellar-desk-ui-spec.html distinguishes. Run with DATABASE_URL
pointed at a real Postgres, then open the deal it prints in the browser.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.api.auth import hash_password
from app.db import repo
from app.db.connection import transaction
from app.worker import jobs

OPERATOR_USERNAME = "deskdemo"
OPERATOR_PASSWORD = "desk-demo-password"


def ensure_operator(conn) -> str:
    row = conn.execute("SELECT operator_id FROM operator WHERE username = %s",
                       (OPERATOR_USERNAME,)).fetchone()
    if row:
        return str(row["operator_id"])
    row = conn.execute(
        """INSERT INTO operator (username, display_name, password_hash, active)
           VALUES (%s, %s, %s, true) RETURNING operator_id""",
        (OPERATOR_USERNAME, "Desk Demo", hash_password(OPERATOR_PASSWORD))).fetchone()
    return str(row["operator_id"])


def ensure_wine(conn, producer: str, cuvee: str) -> str:
    key = f"{producer} | {cuvee}".lower().replace("-", " ").replace(",", " ")
    key = " ".join(key.split())
    row = conn.execute(
        """INSERT INTO wine (producer, cuvee, wine_key) VALUES (%s, %s, %s)
           ON CONFLICT (wine_key) DO UPDATE SET producer = EXCLUDED.producer
           RETURNING wine_id""", (producer, cuvee, key)).fetchone()
    return str(row["wine_id"])


def seed_snapshot(conn, captured_at: datetime, wines: list[tuple[str, int, list[tuple[str, str, str]]]]) -> None:
    """One snapshot, covering every merchant it mentions, same as a real sweep:
    repo._SOURCES_CTE picks each merchant's single LATEST snapshot_merchant row
    by captured_at, so a merchant's offers must all live in ONE snapshot or its
    earlier ones stop counting (the real, intentional rule — "an older capture
    is never used to resurrect a sold listing"). `wines`: [(wine_id, vintage,
    [(merchant_id, offer_id, price), ...]), ...].
    """
    snap = conn.execute(
        "INSERT INTO snapshot (captured_at, schema_version) VALUES (%s, 'deskdemo') "
        "RETURNING snapshot_id", (captured_at,)).fetchone()
    merchants_done: set[str] = set()
    for wine_id, vintage, offers in wines:
        for merchant_id, offer_id, price in offers:
            if merchant_id not in merchants_done:
                conn.execute(
                    """INSERT INTO snapshot_merchant (snapshot_id, merchant_id, status,
                                                      captured_at, offers_written)
                       VALUES (%s, %s, 'ok', %s, 1)""",
                    (snap["snapshot_id"], merchant_id, captured_at))
                merchants_done.add(merchant_id)
            conn.execute(
                """INSERT INTO offer (snapshot_id, offer_id, merchant_id, wine_id, vintage,
                                      bottle_ml, pack_size, price, currency, duty_status,
                                      price_kind, is_buyable, offered_units, captured_at)
                   VALUES (%s, %s, %s, %s, %s, 750, 1, %s, 'GBP', 'IB', 'ASK', true, 6, %s)""",
                (snap["snapshot_id"], offer_id, merchant_id, wine_id, vintage, price, captured_at))


def main() -> None:
    with transaction() as conn:
        operator_id = ensure_operator(conn)

        krug = ensure_wine(conn, "Krug", "Grande Cuvée 167ᵉ")
        dp08 = ensure_wine(conn, "Dom Pérignon", "Vintage")
        dp10 = ensure_wine(conn, "Dom Pérignon", "Vintage")

        deal = repo.create_deal(conn, {
            "name": "WFS Cellar · Champagne (desk demo)", "seller": "WFS",
            "source_file": None, "currency": "GBP", "target_margin": None,
            "buyer_discount": None, "margin_on_sale": None, "created_by": operator_id,
        }, [
            {"row_index": 0, "raw_description": "Krug Grande Cuvee 167e NV x48",
             "raw_row": {"raw": "Krug 167e NV x48"}, "quantity": 48,
             "cost": None, "cost_currency": None, "target_margin": None,
             "target_discount": None, "manual_price": None},
            {"row_index": 1, "raw_description": "Dom Perignon 2008 x46",
             "raw_row": {"raw": "Dom Perignon 2008 x46"}, "quantity": 46,
             "cost": None, "cost_currency": None, "target_margin": None,
             "target_discount": None, "manual_price": None},
            {"row_index": 2, "raw_description": "Dom Perignon 2010 x24",
             "raw_row": {"raw": "Dom Perignon 2010 x24"}, "quantity": 24,
             "cost": None, "cost_currency": None, "target_margin": None,
             "target_discount": None, "manual_price": None},
        ])
        deal_id = str(deal["deal_id"])
        lines = repo.deal_lines(conn, deal_id)
        by_index = {ln["row_index"]: ln for ln in lines}

        repo.set_line_identity(conn, str(by_index[0]["line_id"]), wine_id=krug, vintage=1000,
                               bottle_ml=750, pack_size=1, flags=[], source="operator",
                               approved_by=operator_id)
        repo.set_line_identity(conn, str(by_index[1]["line_id"]), wine_id=dp08, vintage=2008,
                               bottle_ml=750, pack_size=1, flags=[], source="operator",
                               approved_by=operator_id)
        repo.set_line_identity(conn, str(by_index[2]["line_id"]), wine_id=dp10, vintage=2010,
                               bottle_ml=750, pack_size=1, flags=[], source="operator",
                               approved_by=operator_id)

        seed_snapshot(conn, datetime.now(timezone.utc) - timedelta(minutes=5), [
            # thin: one merchant only
            (krug, 1000, [("bordeaux-index", "bi:desk-krug-167", "168.90")]),
            # strong: two merchants, 1.5% apart (matches the real sweep finding)
            (dp08, 2008, [("bordeaux-index", "bi:desk-dp08", "168.50"),
                         ("justerini-brooks", "jb:desk-dp08", "171.10")]),
            # ok: two merchants, ~24% apart
            (dp10, 2010, [("bordeaux-index", "bi:desk-dp10", "148.60"),
                         ("justerini-brooks", "jb:desk-dp10", "184.10")]),
        ])

    print(f"deal_id={deal_id}")
    jobs.benchmark_deal(deal_id)
    jobs.price_deal(deal_id, priced_by=operator_id)
    print(f"operator_username={OPERATOR_USERNAME}")


if __name__ == "__main__":
    main()
