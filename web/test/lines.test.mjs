import assert from "node:assert/strict";
import test from "node:test";
import { guessMapping, money, toLine, toLines } from "../lib/lines.js";

const MAPPING = { description: "Wine", quantity: "Qty", cost: "Cost" };

test("the seller's row is kept exactly as it was read", () => {
  const row = { Wine: "  Rousseau Charmes 2011  ", Qty: "6", Cost: "£480.00", Notes: "in bond" };
  const line = toLine(row, 0, MAPPING);
  assert.equal(line.raw_row, row);                       // the same object, untouched
  assert.deepEqual(line.raw_row, {
    Wine: "  Rousseau Charmes 2011  ", Qty: "6", Cost: "£480.00", Notes: "in bond" });
  assert.equal(line.raw_description, "Rousseau Charmes 2011");
});

test("money stays a string of whole pence, never a float", () => {
  assert.equal(money("£2,353.10"), "2353.10");
  assert.equal(money("480"), "480.00");
  assert.equal(money("1.5"), "1.50");
  assert.equal(money(""), null);
  assert.equal(money("0"), null);
  assert.equal(money("POA"), null);
  assert.equal(money("308.329986"), null);               // Farr's float32 shape
  assert.equal(typeof toLine({ Wine: "x", Qty: "1", Cost: "480" }, 0, MAPPING).cost, "string");
});

test("a row with no wine text is skipped, not invented", () => {
  const rows = [{ Wine: "Rousseau Charmes 2011", Qty: "6", Cost: "" },
                { Wine: "   ", Qty: "12", Cost: "100" },
                { Wine: "Musigny 2009", Qty: "", Cost: "" }];
  const lines = toLines(rows, MAPPING);
  assert.deepEqual(lines.map((l) => l.raw_description),
                   ["Rousseau Charmes 2011", "Musigny 2009"]);
  assert.equal(lines[1].quantity, 1);                    // unreadable quantity -> 1
  assert.equal(lines[0].cost, undefined);                // no cost column value, no cost
});

test("quantity reads through the seller's punctuation", () => {
  assert.equal(toLine({ Wine: "x", Qty: "12 bottles" }, 0, MAPPING).quantity, 12);
  assert.equal(toLine({ Wine: "x", Qty: "1,200" }, 0, MAPPING).quantity, 1200);
});

test("columns are guessed from the header row", () => {
  assert.deepEqual(guessMapping(["Lot", "Wine Description", "No. of Bottles", "Cost GBP"]),
                   { description: "Wine Description", quantity: "No. of Bottles", cost: "Cost GBP" });
  assert.deepEqual(guessMapping(["A", "B"]), { description: "", quantity: "", cost: "" });
});
