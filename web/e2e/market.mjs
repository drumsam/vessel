// Seeds a fixed market straight into Postgres, so the smoke test never depends
// on what a merchant happens to be listing today. Two wines: one that Farr and
// Bordeaux Index both offer (a real market), and one that nobody offers, which
// is what a NO_MARKET line is made of.
import pg from "pg";

export const SEARCHED = "Charmes-Chambertin Grand Cru";   // two merchants offer it
export const UNSEARCHED = "Clos de la Roche Grand Cru";   // nobody does
export const PRODUCER = "Domaine Armand Rousseau";
export const VINTAGE = 2011;

const OFFERS = [
  { merchant: "farr", price: "610.00", offer_id: "farr:e2e-1" },
  { merchant: "bordeaux-index", price: "650.00", offer_id: "bi:e2e-1" },
];

export async function seedMarket(databaseUrl) {
  const client = new pg.Client({ connectionString: databaseUrl });
  await client.connect();
  try {
    await client.query("BEGIN");
    const wines = {};
    for (const cuvee of [SEARCHED, UNSEARCHED]) {
      const key = `${PRODUCER} | ${cuvee}`.toLowerCase().replace(/[-,]/g, " ")
        .replace(/\s+/g, " ").replace(" | ", "|");
      const { rows } = await client.query(
        `INSERT INTO wine (producer, cuvee, wine_key) VALUES ($1, $2, $3)
         ON CONFLICT (wine_key) DO UPDATE SET producer = EXCLUDED.producer
         RETURNING wine_id`, [PRODUCER, cuvee, key]);
      wines[cuvee] = rows[0].wine_id;
    }

    const { rows: [snapshot] } = await client.query(
      `INSERT INTO snapshot (captured_at, schema_version) VALUES (now(), 'e2e')
       RETURNING snapshot_id`);
    for (const offer of OFFERS) {
      await client.query(
        `INSERT INTO snapshot_merchant (snapshot_id, merchant_id, status, captured_at,
                                        offers_written)
         VALUES ($1, $2, 'ok', now(), 1)`, [snapshot.snapshot_id, offer.merchant]);
      await client.query(
        `INSERT INTO offer (snapshot_id, offer_id, merchant_id, wine_id, vintage, bottle_ml,
                            pack_size, price, currency, duty_status, price_kind, is_buyable,
                            offered_units, captured_at)
         VALUES ($1, $2, $3, $4, $5, 750, 1, $6, 'GBP', 'IB', 'ASK', true, 6, now())`,
        [snapshot.snapshot_id, offer.offer_id, offer.merchant, wines[SEARCHED], VINTAGE,
         offer.price]);
    }
    await client.query("COMMIT");
    return wines;
  } catch (e) {
    await client.query("ROLLBACK");
    throw e;
  } finally {
    await client.end();
  }
}
