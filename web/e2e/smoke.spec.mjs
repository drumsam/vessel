// The operator's whole day, in one pass: sign in, upload a seller's list,
// approve identities, benchmark, price, sign off what gates, issue an offer.
//
// There is exactly one route from a cellar to a buyer in the browser —
// the Cellar Desk — ever since decision 0037 removed the pipeline page's
// own Client+Terms+checkboxes form (`issue.jsx`): it predated the Desk,
// the offer document and the share links, and had no acceptance step at
// all. The buyer_offer API and its records are untouched, so this test
// still drives `POST /deals/{id}/buyer-offers` directly where it needs
// to (`issueOffer`, below) to keep covering what that document itself
// may say — just never through a browser button, because there isn't
// one any more.
//
// Every assertion here is a rule that has already gone wrong once, or that
// would rot silently if it did:
//   * signing in must land on the deals page (a stale session check bounced it
//     back to /login);
//   * a line still gated must refuse the issue with a message naming the
//     WINE and the reason, in plain English — never the UUID, never the
//     bare state name (decision 0037, found live: "line b76ec9c8-...-...
//     is priced REVIEW and has not been acknowledged" was the error an
//     operator actually saw);
//   * a line with no UK Reference must carry no market claim anywhere on the
//     client document (decision 0010);
//   * NO_MARKET and REVIEW must stop an export until a named operator accepts.
import { expect, test } from "@playwright/test";
import * as fs from "node:fs";
import * as os from "node:os";
import path from "node:path";
import * as XLSX from "xlsx";
import { PRODUCER, SEARCHED, UNSEARCHED, VINTAGE, seedMarket } from "./market.mjs";

// the ESM build needs fs injected to write a file; the CJS build already has it
if (typeof XLSX.set_fs === "function") XLSX.set_fs(fs);

const OPERATOR = { username: process.env.E2E_USER || "e2e",
                   password: process.env.E2E_PASSWORD || "e2e-password" };
const DATABASE_URL = process.env.E2E_DATABASE_URL;
const API_URL = process.env.E2E_API_URL || "http://localhost:8077";

test.skip(!DATABASE_URL, "E2E_DATABASE_URL is not set; see e2e/README.md");

/** `POST /deals/{id}/buyer-offers` directly: the one route left to create a
 * buyer_offer record now that issue.jsx is gone (decision 0037). Uses
 * `page.request`, which shares the signed-in browser context's own
 * cookies, so no credential is handled by this file at all. */
async function issueOffer(page, dealId, client, lineIds) {
  return page.request.post(`${API_URL}/deals/${dealId}/buyer-offers`, {
    data: { client, currency: "GBP", lines: lineIds.map((line_id) => ({ line_id })) },
  });
}

function sellerList(directory) {
  const file = path.join(directory, "seller-list.xlsx");
  const sheet = XLSX.utils.aoa_to_sheet([
    ["Wine", "No. of Bottles", "Cost per bottle"],
    [`${SEARCHED} ${VINTAGE} Rousseau`, 1, "£480.00"],
    [`${UNSEARCHED} ${VINTAGE} Rousseau`, 1, "£900.00"],
  ]);
  const book = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(book, sheet, "Offer");
  XLSX.writeFile(book, file);
  return file;
}

async function approveIdentity(page, row, cuvee) {
  await row.getByRole("button", { name: "Open" }).click();
  const option = page.locator("#wine option", { hasText: cuvee }).first();
  await page.selectOption("#wine", await option.getAttribute("value"));
  await page.fill("#vintage", String(VINTAGE));
  await page.fill("#ml", "750");
  await page.fill("#pack", "1");
  await page.getByRole("button", { name: "Save identity" }).click();
  await expect(page.getByText(/Saved as /)).toBeVisible();
  await row.getByRole("button", { name: "Close" }).click();
}

async function runJob(page, name) {
  await page.getByRole("button", { name, exact: true }).click();
  await expect(page.locator(".notice")).toBeVisible({ timeout: 90_000 });
  return (await page.locator(".notice").textContent()).trim();
}

test("a seller's list becomes a buyer offer", async ({ page }, testInfo) => {
  await seedMarket(DATABASE_URL);
  const file = sellerList(fs.mkdtempSync(path.join(os.tmpdir(), "pricer-e2e-")));

  await test.step("sign in lands on the deals page", async () => {
    await page.goto("/login");
    await page.fill("#username", OPERATOR.username);
    await page.fill("#password", OPERATOR.password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { name: /Load a seller/ })).toBeVisible();
  });

  let dealId;
  await test.step("the seller's spreadsheet is read and loaded", async () => {
    await page.setInputFiles("#file", file);
    await expect(page.locator("#deal-name")).toBeVisible();
    await expect(page.locator("#map-description")).toHaveValue("Wine");
    await expect(page.locator("#map-quantity")).toHaveValue("No. of Bottles");
    const name = `E2E ${testInfo.testId}`;
    await page.fill("#deal-name", name);
    await page.fill("#margin", "25");
    await page.getByRole("button", { name: /Load 2 lines/ }).click();
    // Lands on the Cellar Desk, the default view of a deal; the pipeline
    // work below (identity, benchmark, price, accept) is one click further,
    // at /deals/{id}/lines, same as an operator has to go looking for it.
    await expect(page).toHaveURL(/\/deals\/[0-9a-f-]+$/);
    dealId = new URL(page.url()).pathname.split("/").pop();
    await page.goto(`/deals/${dealId}/lines`);
    await expect(page.getByRole("heading", { name })).toBeVisible();
  });

  const rows = page.locator("tbody tr");

  await test.step("identities are approved", async () => {
    await expect(rows.first()).toContainText("Identity not approved");
    await approveIdentity(page, rows.nth(0), SEARCHED);
    await approveIdentity(page, rows.nth(1), UNSEARCHED);
    // Approved, but nobody has searched for them yet: not the same as no market.
    await expect(rows.first()).toContainText("Not searched");
  });

  await test.step("benchmark and price", async () => {
    expect(await runJob(page, "Benchmark")).toContain("Benchmarked 2 line(s)");
    expect(await runJob(page, "Price")).toContain("Priced 2 line(s)");
    // One line has a market, the other was searched and has none.
    await expect(rows.nth(0)).toContainText("Ready");
    await expect(rows.nth(1)).toContainText("No market");
    await expect(rows.nth(0)).toContainText("£650.00");      // the UK Reference
  });

  let lineIds;
  await test.step("the no-market line cannot be offered unsigned", async () => {
    await expect(rows.nth(1)).toContainText("needs sign-off");
    const deal = await (await page.request.get(`${API_URL}/deals/${dealId}`)).json();
    lineIds = deal.lines.map((l) => l.line_id);

    // There is no button for this on any screen any more (decision 0037) —
    // issue.jsx is gone — so the gate is driven directly, the one route
    // left to reach create_buyer_offer at all.
    const refused = await issueOffer(page, dealId, "A Merchant Ltd", lineIds);
    expect(refused.status()).toBe(409);
    const body = await refused.text();
    expect(body).toContain(UNSEARCHED);           // names the wine
    expect(body).not.toContain("NO_MARKET");       // never the bare state
    expect(body).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/);  // never a UUID
  });

  await test.step("a named operator accepts it", async () => {
    await rows.nth(1).getByRole("button", { name: "Open" }).click();
    await page.getByRole("button", { name: "Accept this price" }).click();
    await expect(page.getByText(/Accepted by /)).toBeVisible();

    const issued = await issueOffer(page, dealId, "A Merchant Ltd", lineIds);
    expect(issued.status(), await issued.text()).toBe(201);
    await page.reload();
    await expect(page.getByRole("link", { name: "A Merchant Ltd" })).toBeVisible();
  });

  await test.step("the document claims a market only where there is one", async () => {
    await page.getByRole("link", { name: "A Merchant Ltd" }).click();
    await expect(page.getByRole("heading", { name: /Offer to A Merchant Ltd/ })).toBeVisible();

    const claimed = page.locator("table").filter({ hasText: SEARCHED });
    await expect(claimed).toContainText("£650.00");          // UK Market
    await expect(claimed).toContainText("Below UK Market");

    // The cost-priced line sits in its own table, which has no UK Market column
    // at all: not blank, not zero, absent.
    const costPlus = page.locator("table").filter({ hasText: UNSEARCHED });
    await expect(costPlus).not.toContainText("UK Market");
    await expect(page.getByText("No UK market comparison is offered on these lines"))
      .toBeVisible();
    await expect(page.getByText(PRODUCER).first()).toBeVisible();
  });
});
