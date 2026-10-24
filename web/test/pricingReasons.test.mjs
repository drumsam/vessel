import assert from "node:assert/strict";
import test from "node:test";
import { gated, reasonFor, wantListGated } from "../lib/pricingReasons.js";

function line({ compCount, benchmarkFlags = [], pricingFlags = [], floor, reference,
               gatedOverride = true, wantList = false, wantListAckAt = null } = {}) {
  return {
    want_list: wantList, want_list_acknowledged_at: wantListAckAt,
    benchmark: { flags: benchmarkFlags, state: compCount === 0 ? "NO_MARKET" : "REVIEW" },
    pricing: {
      comp_count: compCount, flags: pricingFlags, uk_floor: floor, uk_reference: reference,
      requires_acknowledgement: gatedOverride, acknowledgement: gatedOverride ? null : {},
    },
  };
}

test("a line that is not gated has no reason at all", () => {
  const l = line({ compCount: 3, gatedOverride: false });
  assert.equal(gated(l), false);
  assert.equal(reasonFor(l), null);
});

test("ONE_COMP alone reads as '1 merchant', Doug's own example shape", () => {
  const l = line({ compCount: 1, benchmarkFlags: ["ONE_COMP"] });
  assert.equal(reasonFor(l), "1 merchant");
});

test("ONE_COMP plus DERIVED_FROM_CASE reads as both, joined", () => {
  const l = line({ compCount: 1, benchmarkFlags: ["ONE_COMP", "DERIVED_FROM_CASE"] });
  assert.equal(reasonFor(l), "1 merchant · case divided");
});

test("ONE_COMP plus QUANTITY_SHORTFALL reads as 'fewer bottles'", () => {
  const l = line({ compCount: 1, benchmarkFlags: ["ONE_COMP", "QUANTITY_SHORTFALL"] });
  assert.equal(reasonFor(l), "1 merchant · fewer bottles");
});

test("WIDE_SPREAD at exactly two comps names the gap percentage", () => {
  const l = line({ compCount: 2, benchmarkFlags: ["WIDE_SPREAD"], floor: "100", reference: "157" });
  assert.equal(reasonFor(l), "2 merchants, 57% apart");
});

test("an evidence-quality flag with no shape reason reads alone, no merchant count", () => {
  const l = line({ compCount: 3, benchmarkFlags: ["STOCK_BASIS_UNCONFIRMED"] });
  assert.equal(reasonFor(l), "stock basis unconfirmed");
});

test("a commercial gate flag reads even when the benchmark itself is agreeing", () => {
  const l = line({ compCount: 3, pricingFlags: ["SELL_AT_OR_ABOVE_UK_FLOOR"] });
  assert.equal(reasonFor(l), "not actually below market");
});

test("a want-list line gates even when pricing is fully READY and agreeing", () => {
  const l = line({ compCount: 3, gatedOverride: false, wantList: true });
  assert.equal(wantListGated(l), true);
  assert.equal(gated(l), true);
  assert.equal(reasonFor(l), "want list");
});

test("a want-list line stops gating once acknowledged, independent of pricing", () => {
  const l = line({ compCount: 3, gatedOverride: false, wantList: true,
                   wantListAckAt: "2026-10-24T00:00:00Z" });
  assert.equal(wantListGated(l), false);
  assert.equal(gated(l), false);
  assert.equal(reasonFor(l), null);
});

test("a want-list line that is ALSO pricing-gated shows both reasons", () => {
  const l = line({ compCount: 1, benchmarkFlags: ["ONE_COMP"], wantList: true });
  assert.equal(reasonFor(l), "1 merchant · want list");
});

test("every phrase this module can produce is free of the flag constants behind it", () => {
  const cases = [
    line({ compCount: 1, benchmarkFlags: ["ONE_COMP"] }),
    line({ compCount: 2, benchmarkFlags: ["WIDE_SPREAD"], floor: "100", reference: "157" }),
    line({ compCount: 3, benchmarkFlags: ["STOCK_BASIS_UNCONFIRMED"] }),
    line({ compCount: 3, pricingFlags: ["NEGATIVE_GP"] }),
  ];
  for (const l of cases) {
    const reason = reasonFor(l);
    for (const flag of [...l.benchmark.flags, ...l.pricing.flags]) {
      assert.ok(!reason.includes(flag), `${reason} leaked ${flag}`);
    }
  }
});
