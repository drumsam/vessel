// Dedicated fixture server: tests/support/market_evidence_server.py.
// Auth, canonical confirmation, Postgres, imports and UI are real; parser and
// merchant HTTP transport are fixtures. This never contacts a live source.
import { expect, test } from '@playwright/test';
import pg from 'pg';

test.skip(!process.env.POCKET_EVIDENCE_E2E, 'Requires the dedicated local fixture server');
const testDbUrl = new URL(process.env.E2E_DATABASE_URL || 'postgresql://localhost/none');
if (process.env.POCKET_EVIDENCE_E2E &&
    (!['localhost','127.0.0.1'].includes(testDbUrl.hostname) || !testDbUrl.pathname.endsWith('_e2e'))) {
  throw new Error('This fixture journey requires a disposable local *_e2e database');
}


test('Pocket confirms identity, shows separate rails, imports and refreshes existing evidence', async ({ page }) => {
  const database = new pg.Client({connectionString: process.env.E2E_DATABASE_URL});
  await database.connect();
  try {
    const { rows: [wine] } = await database.query("SELECT wine_id FROM wine WHERE producer='Domaine Armand Rousseau' LIMIT 1");
    await page.goto('/login');
    await page.fill('#username', 'e2e');
    await page.fill('#password', 'e2e-password');
    await page.getByRole('button', {name:'Sign in', exact:true}).click();
    await expect(page).toHaveURL(/\/pocket$/);
    // Reset through ordinary append/retraction semantics so a second run really
    // proves a new import and refresh, rather than seeing the first run's data.
    const {rows: lots} = await database.query('SELECT auction_evidence_id FROM auction_evidence WHERE retracted_at IS NULL');
    for (const lot of lots) {
      const result = await page.request.post(`/api/auction-evidence/${lot.auction_evidence_id}/retract`, {data:{reason:'Disposable fixture reset'}});
      expect(result.ok()).toBeTruthy();
    }
    const {rows: [empty]} = await database.query("INSERT INTO snapshot(captured_at,schema_version) VALUES(now(),'2') RETURNING snapshot_id");
    await database.query("INSERT INTO snapshot_merchant(snapshot_id,merchant_id,status,captured_at) VALUES($1,'bordeaux-index','ok',now())",[empty.snapshot_id]);

    await page.goto('/pocket');
    await page.fill('#paste', '2011 Rousseau Charmes-Chambertin, 1 bottle, GBP500 per bottle');
    await page.getByRole('button', {name:'Paste', exact:true}).click();
    await page.selectOption('#pwine', wine.wine_id);
    await page.getByRole('button', {name:'Fixture Supplier',exact:true}).click();
    await expect(page.getByRole('button',{name:'Confirm identity',exact:true})).toBeDisabled();
    await page.getByRole('checkbox').check();
    await page.getByRole('button',{name:'Confirm identity',exact:true}).click();
    await expect(page.getByRole('heading',{name:/Available market/})).toBeVisible();
    await expect(page.getByText('No currently eligible merchant asks found.',{exact:false})).toBeVisible();
    await expect(page.getByText(/walk.away|max.sell|headroom/i)).toHaveCount(0);
    await page.getByRole('button',{name:'Refresh Market',exact:true}).click();
    await expect(page.getByText('£650.00',{exact:true}).first()).toBeVisible();
    const csv = 'producer,wine,vintage,bottle_ml,bottles_in_lot,auction_house,sale_date,lot_ref,source_url,currency,amount,amount_basis\nDomaine Armand Rousseau,Charmes-Chambertin Grand Cru,2011,750,6,CHRISTIES,2026-01-01,browser-lot,https://www.christies.com/en/lot/example,GBP,600.00,HAMMER\n';
    await page.getByLabel(/Import Christie/).setInputFiles({name:'auction.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
    await expect(page.getByText(/1 lots · 1 with GBP/)).toBeVisible();
    await expect(page.getByRole('heading',{name:/Transaction market/})).toBeVisible();
    await expect(page.getByText(/1 written · 0 unresolved · 0 rejected · 0 duplicates/)).toBeVisible();
    await expect(page.getByText(/Hammer range: £100.00–£100.00 per bottle/)).toBeVisible();
    await expect(page.getByText('£650.00',{exact:true}).first()).toBeVisible();
    await expect(page.getByText(/days old/).first()).toBeVisible();
  } finally { await database.end(); }
});
