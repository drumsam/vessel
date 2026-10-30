import assert from "node:assert/strict";
import test from "node:test";
import { adminHandoff, formatLine, supplierHandoff, tombstone } from "../lib/pocketMessages.js";

const LINE = {
  wineName: "Armand Rousseau Clos St Jacques 2015", quantity: 3, pack_size: 1, bottle_ml: 750,
  bond_status: "UK IB", stock_location: "LCB", availability: "Available now",
  vesselSell: "3150.00",
};

const FULFILMENT = {
  supplier_name: "ABC Wines", buyer_name: "Client X",
  wine_name: "Armand Rousseau Clos St Jacques 2015", quantity: 3, pack_size: 1, bottle_ml: 750,
  bond_status: "UK IB", stock_location: "LCB", availability: null,
  supplier_price: "2800.00", vessel_sell_price: "3150.00", gross_total: "1050.00",
};

test("the tombstone is four short lines carrying the committed VESSEL sell price", () => {
  assert.equal(tombstone(LINE),
    "Armand Rousseau Clos St Jacques 2015\n3 × 75cl · UK IB · LCB\n£3,150/bt\nAvailable now");
});

test("the tombstone never carries the supplier price or a market figure", () => {
  const text = tombstone(LINE);
  assert.ok(!text.includes("2,800") && !text.includes("3,400"));
  assert.ok(!/supplier|cost|margin/i.test(text));
});

test("availability is printed only when Doug stated it", () => {
  assert.ok(!tombstone({ ...LINE, availability: null }).includes("Available"));
});

test("a case line prints its unit as the trade writes it, priced per case", () => {
  assert.equal(formatLine({ quantity: 1, pack_size: 6, bottle_ml: 750 }), "1 × 6 × 75cl");
  assert.ok(tombstone({ ...LINE, quantity: 1, pack_size: 6, vesselSell: "18900.00" })
    .includes("£18,900/case"));
});

test("a Jeroboam prints as 300cl", () => {
  assert.equal(formatLine({ quantity: 1, pack_size: 1, bottle_ml: 3000 }), "1 × 300cl");
});

test("the supplier handoff names only the agreed supplier price", () => {
  const text = supplierHandoff(FULFILMENT);
  assert.ok(text.startsWith("CONFIRMED\n"));
  assert.ok(text.includes("Agreed £2,800/bt"));
  assert.ok(!text.includes("3,150") && !text.includes("Client X"));
});

test("the admin handoff carries buy, sell and gross from the frozen record", () => {
  const text = adminHandoff(FULFILMENT);
  for (const part of ["Supplier: ABC Wines", "Buyer: Client X", "Buy: £8,400", "Sell: £9,450",
                      "Gross: £1,050", "Stock: LCB · UK IB", "invoice buyer"]) {
    assert.ok(text.includes(part), part);
  }
});
