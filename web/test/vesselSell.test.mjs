import assert from "node:assert/strict";
import test from "node:test";
import {
  ceilToStep, divHalfEven, fmt, formatBp, fromQuote, inputText, markupBp, parsePounds,
  quoteLabel, sellFromMarkup, splitStatedPrice, stepBp, stepQuote, toMoney, toPence, toQuote,
  vsMarketBp,
} from "../lib/vesselSell.js";

const SALON = toPence("3995.00"); // GBP 3,995 /cs of 6

test("Salon: +8% on GBP 3,995 /cs is 4,314.60, quoted GBP 4,315 /cs (+8.0%)", () => {
  assert.equal(sellFromMarkup(SALON, 800), toPence("4315.00"));
  assert.equal(formatBp(markupBp(toPence("4315.00"), SALON)), "+8%");
  const gross = toPence("4315.00") - SALON;
  assert.equal(fmt(gross), "GBP 320");
  assert.equal(fmt(gross * 5), "GBP 1,600");
});

test("rounding is UP to the next whole 5 in the quote unit, never to nearest", () => {
  for (const [raw, quoted] of [["4314.60", "4315.00"], ["4320.00", "4320.00"],
                               ["719.10", "720.00"], ["721.00", "725.00"], ["720.01", "725.00"]]) {
    assert.equal(ceilToStep(toPence(raw)), toPence(quoted), raw);
  }
});

test("a per-bottle quote rounds the bottle price itself: GBP 665 /btl +8% is 720", () => {
  assert.equal(sellFromMarkup(toPence("665.00"), 800), toPence("720.00"));
});

test("stepping never lands back on the price already shown", () => {
  assert.equal(stepQuote(toPence("4320.00"), SALON, -1), toPence("4315.00"));
  assert.equal(stepQuote(toPence("4315.00"), SALON, -1), toPence("4275.00")); // 8% -> 4315 again, so 7%
  assert.equal(stepQuote(toPence("4315.00"), SALON, +1), toPence("4355.00")); // 9% = 4,354.55
});

test("a typed price parses exactly and is then rounded up to 5", () => {
  const typed = parsePounds("4,321");
  assert.equal(typed, 432100);
  assert.equal(ceilToStep(typed), 432500);
  assert.equal(parsePounds("3150.505"), null);
  assert.equal(parsePounds("31a0"), null);
});

test("ISO codes, never symbols; decimals only where the figure has them", () => {
  assert.equal(fmt(399500), "GBP 3,995");
  assert.equal(fmt(66583, "GBP"), "GBP 665.83");
  assert.equal(fmt(66583, "GBP", { whole: true }), "GBP 666");
  assert.equal(fmt(415000, "HKD"), "HKD 4,150");
  assert.ok(!/[£$€]/.test(fmt(399500)));
});

test("quote labels repeat the case size", () => {
  assert.equal(quoteLabel("case", 6), "/cs of 6");
  assert.equal(quoteLabel("case", 12), "/cs of 12");
  assert.equal(quoteLabel("bottle", 6), "/btl");
});

test("quote <-> per-commercial-unit conversion is exact for a whole quote", () => {
  assert.equal(fromQuote(toPence("720.00"), "bottle", 6), toPence("4320.00"));
  assert.equal(toQuote(toPence("4320.00"), "bottle", 6), toPence("720.00"));
  assert.equal(fromQuote(toPence("4315.00"), "case", 6), toPence("4315.00"));
});

test("£3,150 against a £3,400 market is 7.4% below it", () => {
  const bp = vsMarketBp(toPence("3150.00"), toPence("3400.00"));
  assert.equal(bp, 735);
  assert.equal(formatBp(bp, { signed: false }), "7.4%");
});

test("helpers keep their earlier contracts", () => {
  assert.equal(divHalfEven(5, 2), 2);
  assert.equal(divHalfEven(7, 2), 4);
  assert.equal(stepBp(1250, +1), 1300);
  assert.equal(toMoney(315005), "3150.05");
  assert.equal(inputText(315000), "3150");
  assert.equal(formatBp(markupBp(toPence("2786.00"), toPence("2800.00"))), "−0.5%");
});

test("a stated price prefills as a bare amount, its currency kept separately", () => {
  assert.deepEqual(splitStatedPrice("£3,995"), { amount: "3995", currency: "GBP" });
  assert.deepEqual(splitStatedPrice("GBP 19,500"), { amount: "19500", currency: "GBP" });
  assert.deepEqual(splitStatedPrice("2,800"), { amount: "2800", currency: null });
  assert.deepEqual(splitStatedPrice("€1,250.50"), { amount: "1250.50", currency: "EUR" });
  assert.deepEqual(splitStatedPrice("HK$41,500"), { amount: "41500", currency: "HKD" });
});
