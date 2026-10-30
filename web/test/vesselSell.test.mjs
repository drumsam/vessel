import assert from "node:assert/strict";
import test from "node:test";
import {
  divHalfEven, formatBp, gbp, inputText, markupBp, parsePounds, sellFromMarkup, stepBp,
  toMoney, toPence, vsMarketBp,
} from "../lib/vesselSell.js";

const S = toPence("2800.00");

test("default +8% on a £2,800 supplier price is £3,024", () => {
  assert.equal(sellFromMarkup(S, 800), toPence("3024.00"));
  assert.equal(formatBp(markupBp(toPence("3024.00"), S)), "+8%");
});

test("stepping +8% to +10% moves the price to £3,080", () => {
  const bp = stepBp(stepBp(800, +1), +1);
  assert.equal(bp, 1000);
  assert.equal(sellFromMarkup(S, bp), toPence("3080.00"));
});

test("typing £3,150 recalculates the markup to +12.5%", () => {
  const v = parsePounds("3,150");
  assert.equal(v, 315000);
  assert.equal(markupBp(v, S), 1250);
  assert.equal(formatBp(1250), "+12.5%");
});

test("a fractional markup snaps to the next whole point either way", () => {
  assert.equal(stepBp(1250, +1), 1300);
  assert.equal(stepBp(1250, -1), 1200);
  assert.equal(stepBp(800, -1), 700);
});

test("£3,150 against a £3,400 market is 7.4% below it", () => {
  const bp = vsMarketBp(toPence("3150.00"), toPence("3400.00"));
  assert.equal(bp, 735);
  assert.equal(formatBp(bp, { signed: false }), "7.4%");
  assert.ok(vsMarketBp(toPence("3500.00"), toPence("3400.00")) < 0);
});

test("3 bottles at £350 gross is £1,050 total", () => {
  const gross = toPence("3150.00") - S;
  assert.equal(gbp(gross), "£350");
  assert.equal(gbp(gross * 3), "£1,050");
});

test("a price below the supplier's is a negative markup, not an error", () => {
  assert.equal(formatBp(markupBp(toPence("2786.00"), S)), "−0.5%");
});

test("rounding is half-even to the penny, the pricer's own rule", () => {
  assert.equal(divHalfEven(5, 2), 2);
  assert.equal(divHalfEven(7, 2), 4);
  assert.equal(divHalfEven(-5, 2), -2);
  assert.equal(sellFromMarkup(toPence("1.25"), 1000), toPence("1.38")); // 1.375 -> 1.38
  assert.equal(sellFromMarkup(toPence("1.15"), 1000), toPence("1.26")); // 1.265 -> 1.26
});

test("only a real price parses — never a guess at what was meant", () => {
  assert.equal(parsePounds("£3,150.50"), 315050);
  assert.equal(parsePounds("3150.505"), null);
  assert.equal(parsePounds("31a0"), null);
  assert.equal(parsePounds(""), null);
});

test("money round-trips as the API's own string shape", () => {
  assert.equal(toMoney(315005), "3150.05");
  assert.equal(toPence("3150.5"), 315050);
  assert.equal(inputText(315000), "3150");
  assert.equal(inputText(315050), "3150.50");
});

test("a stated price prefills as a bare amount, its currency kept separately", async () => {
  const { splitStatedPrice } = await import("../lib/vesselSell.js");
  assert.deepEqual(splitStatedPrice("£3,995"), { amount: "3995", currency: "GBP" });
  assert.deepEqual(splitStatedPrice("GBP 19,500"), { amount: "19500", currency: "GBP" });
  assert.deepEqual(splitStatedPrice("2,800"), { amount: "2800", currency: null });
  assert.deepEqual(splitStatedPrice("€1,250.50"), { amount: "1250.50", currency: "EUR" });
  assert.deepEqual(splitStatedPrice("HK$41,500"), { amount: "41500", currency: "HKD" });
  assert.equal(parsePounds(splitStatedPrice("£3,995").amount), 399500);
});
