import assert from "node:assert/strict";
import test from "node:test";
import { adminHandoff, formatLine, quotePrice, supplierHandoff, tombstone } from "../lib/pocketMessages.js";

const SALON = {
  wineName: "Salon Cuvée S Le Mesnil Blanc de Blancs 2006", quantity: 5, pack_size: 6,
  bottle_ml: 750, bond_status: "in bond", stock_location: null, availability: "2 weeks",
  vesselSell: "4315.00", quoteUnit: "case",
};

const SALON_CONFIRMED = {
  supplier_name: "Vinum", buyer_name: "Client X",
  wine_name: "Salon Cuvée S Le Mesnil Blanc de Blancs 2006", quantity: 5, pack_size: 6,
  bottle_ml: 750, bond_status: "in bond", stock_location: null, availability: "2 weeks",
  currency: "GBP", supplier_price: "3995.00", vessel_sell_price: "4315.00", gross_total: "1600.00",
  quote_unit: "case",
};

test("the Salon tombstone repeats the case size in the price line", () => {
  assert.equal(tombstone(SALON),
    "Salon Cuvée S Le Mesnil Blanc de Blancs 2006\n5 × 6 × 75cl · in bond\nGBP 4,315 /cs of 6\n2 weeks");
});

test("bottle-priced stock prints /btl, from the per-case amount stored", () => {
  assert.ok(tombstone({ ...SALON, vesselSell: "4320.00", quoteUnit: "bottle" })
    .includes("GBP 720 /btl"));
  assert.equal(quotePrice("8500.00", "case", 12), "GBP 8,500 /cs of 12");
});

test("no tombstone carries a symbol, the supplier price or a market figure", () => {
  const text = tombstone(SALON);
  assert.ok(!/[£$€]/.test(text));
  assert.ok(!text.includes("3,995"));
  assert.ok(!/supplier|cost|margin/i.test(text));
});

test("availability is printed only when Doug stated it", () => {
  assert.ok(!tombstone({ ...SALON, availability: null }).includes("weeks"));
});

test("formatLine is the trade's own shorthand, Jeroboams included", () => {
  assert.equal(formatLine({ quantity: 5, pack_size: 6, bottle_ml: 750 }), "5 × 6 × 75cl");
  assert.equal(formatLine({ quantity: 1, pack_size: 1, bottle_ml: 3000 }), "1 × 300cl");
});

test("the supplier handoff names only the agreed supplier price, exactly as quoted", () => {
  const text = supplierHandoff(SALON_CONFIRMED);
  assert.ok(text.startsWith("CONFIRMED\n"));
  assert.ok(text.includes("Agreed GBP 3,995 /cs of 6"));
  assert.ok(!text.includes("4,315") && !text.includes("Client X"));
  assert.ok(supplierHandoff({ ...SALON_CONFIRMED, supplier_price: "3995.50" })
    .includes("GBP 3,995.50 /cs of 6"));
});

test("the admin handoff carries buy, sell and gross from the frozen record", () => {
  const text = adminHandoff(SALON_CONFIRMED);
  for (const part of ["Supplier: Vinum", "Buyer: Client X", "Buy: GBP 19,975", "Sell: GBP 21,575",
                      "Gross: GBP 1,600", "Stock: in bond", "Availability: 2 weeks", "invoice buyer"]) {
    assert.ok(text.includes(part), part);
  }
  assert.ok(!/[£$€]/.test(text));
});
