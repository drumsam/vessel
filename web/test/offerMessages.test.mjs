import assert from "node:assert/strict";
import test from "node:test";
import {
  assertBuyerSafe, buyerGroupMessage, buyerIndividualMessage, heldSentence,
  MAX_MESSAGE_LENGTH, savingSentence, sellerMessage, sellerTotals, topLines, wineName, wineNames,
} from "../lib/offerMessages.js";

const WINES = new Map([
  ["dp", { producer: "Dom Pérignon", cuvee: "Vintage" }],
  ["cristal", { producer: "Louis Roederer", cuvee: "Cristal" }],
  ["krug", { producer: "Krug", cuvee: "Grande Cuvée" }],
]);

const hk = (gbp) => "HK$" + Math.round(gbp * 10).toLocaleString("en-GB");

function line(id, { wine_id, vintage, quantity = 6, floor, offer, floorSavingClaim,
                    seller, gp, compCount = 2 } = {}) {
  return {
    line_id: id, wine_id, vintage, quantity,
    pricing: {
      uk_floor: String(floor), buyer_price_gbp: String(offer), sell_price: String(offer),
      floor_saving_claim: floorSavingClaim === undefined ? null : floorSavingClaim,
      seller_price_gbp: seller !== undefined ? String(seller) : null,
      gp: gp !== undefined ? String(gp) : null,
      comp_count: compCount, uk_reference: String(offer), sell_currency: "GBP",
    },
  };
}

test("wineName omits the vintage entirely for NV, never prints the word", () => {
  const nv = line("a", { wine_id: "krug", vintage: 1000 });
  assert.equal(wineName(nv, WINES), "Krug Grande Cuvée");
  const vintage = line("b", { wine_id: "dp", vintage: 2008 });
  assert.equal(wineName(vintage, WINES), "Dom Pérignon Vintage 2008");
});

test("topLines sorts by per-bottle offer price, highest first, and is per bottle never a total", () => {
  const a = line("a", { wine_id: "dp", vintage: 2008, offer: 132, floor: 162, quantity: 46 });
  const b = line("b", { wine_id: "cristal", vintage: 2005, offer: 169, floor: 194, quantity: 24 });
  const out = topLines([a, b], WINES, hk, 3);
  assert.deepEqual(out, [
    "Louis Roederer Cristal 2005 at HK$1,690 a bottle",
    "Dom Pérignon Vintage 2008 at HK$1,320 a bottle",
  ]);
});

test("wineNames is comma-separated with no prices at all", () => {
  const a = line("a", { wine_id: "dp", vintage: 2008, offer: 132, floor: 162 });
  const b = line("b", { wine_id: "cristal", vintage: 2005, offer: 169, floor: 194 });
  const names = wineNames([a, b], WINES);
  assert.equal(names, "Dom Pérignon Vintage 2008, Louis Roederer Cristal 2005");
  assert.ok(!names.includes("HK$") && !/\d/.test(names.replace(/2008|2005/g, "")));
});

test("savingSentence is omitted whenever any selected line has no printable claim", () => {
  const ok = line("a", { floor: 200, offer: 150, floorSavingClaim: "0.25" });
  const suppressed = line("b", { floor: 150, offer: 148, floorSavingClaim: null });
  assert.notEqual(savingSentence([ok]), "");
  assert.equal(savingSentence([ok, suppressed]), "");
});

test("savingSentence is omitted when the blended figure itself is under the threshold, and never prints 0%", () => {
  // Individually each line's own claim would be non-null (not exercised here,
  // this is specifically the BLENDED figure across the drop) landing under 5%.
  const a = line("a", { floor: 100, offer: 97, floorSavingClaim: "0.03" });
  const text = savingSentence([a]);
  assert.equal(text, "");
  assert.ok(!text.includes("0%"));
});

test("savingSentence reports the real blended percentage, never an average of per-line percentages", () => {
  const a = line("a", { floor: 200, offer: 150, floorSavingClaim: "0.25", quantity: 10 });
  const b = line("b", { floor: 100, offer: 90, floorSavingClaim: "0.10", quantity: 1 });
  // blended = 1 - (10*150 + 1*90) / (10*200 + 1*100) = 1 - 1590/2100 = 24.28...% -> 24%
  assert.equal(savingSentence([a, b]), " Roughly 24% under the cheapest I could find.");
});

test("heldSentence counts only ONE_COMP lines outside the shared set, and is omitted at zero", () => {
  const shared = line("shared", { floor: 200, offer: 150, compCount: 2 });
  const heldOne = line("held1", { floor: 100, offer: 90, compCount: 1 });
  const heldTwo = line("held2", { floor: 50, offer: 45, compCount: 1 });
  const notPriced = { line_id: "np", pricing: {} };

  assert.equal(heldSentence([shared], ["shared"]), "");
  assert.equal(
    heldSentence([shared, heldOne], ["shared"]),
    "1 more line only had one merchant quoting, so I'd rather hold it than price it off a single source.");
  assert.equal(
    heldSentence([shared, heldOne, heldTwo, notPriced], ["shared"]),
    "2 more lines only had one merchant quoting, so I'd rather hold those than price them off a single source.");
});

test("sellerTotals computes the blended commission percentage from real totals", () => {
  const a = line("a", { offer: 150, seller: 138, gp: 12, quantity: 2 });   // 24 gp / 300 offer = 8%
  const { commissionPct, totalNet, totalOffer } = sellerTotals([a]);
  assert.equal(commissionPct, 8);
  assert.equal(totalOffer, 300);
  assert.equal(totalNet, 276);
});

test("assertBuyerSafe throws on a message that mentions a forbidden word", () => {
  assert.throws(() => assertBuyerSafe("your seller net is HK$1,000"));
  assert.throws(() => assertBuyerSafe("after my commission"));
  assert.doesNotThrow(() => assertBuyerSafe("a perfectly ordinary buyer message"));
});

test("assertBuyerSafe throws on a supplier field name or value -- the new leak surface", () => {
  // supplier-attribution-spec.md: a wrong supplier attribution outbound
  // is a commercial injury to Doug, the same class of error as cost.
  assert.throws(() => assertBuyerSafe("supplier_id: abc-123"));
  assert.throws(() => assertBuyerSafe("the supplier is Vinum"));
  assert.throws(() => assertBuyerSafe("contact_name: James"));
  assert.throws(() => assertBuyerSafe("phone: +44 7700 900000"));
});

test("the buyer-individual message carries Doug's own structure and never a seller/commission word", () => {
  const a = line("a", { wine_id: "dp", vintage: 2008, offer: 132, floor: 162, floorSavingClaim: "0.1876" });
  const msg = buyerIndividualMessage({
    ready: [a], wines: WINES, city: "Hong Kong", link: "https://x/share/tok",
    expiryDays: 7, priceFmt: hk,
  });
  assert.ok(msg.includes("1 line out of a Hong Kong cellar"));
  assert.ok(msg.includes("Full list: https://x/share/tok"));
  assert.ok(msg.includes("Open 7 days."));
  assert.ok(!/seller[\s_]?net|commission|\bcost\b|\bmargin\b/i.test(msg));
});

test("the buyer-individual message drops to two lines past ~600 characters", () => {
  const long = (id, wid) => line(id, { wine_id: wid, vintage: 2008, offer: 132, floor: 162 });
  const wines = new Map([
    ["w1", { producer: "A Very Long Producer Name Indeed", cuvee: "An Extremely Long Cuvée Name" }],
    ["w2", { producer: "Another Very Long Producer Name", cuvee: "Another Extremely Long Cuvée" }],
    ["w3", { producer: "Yet Another Very Long Producer", cuvee: "Yet Another Long Cuvée Name" }],
  ]);
  const ready = [long("a", "w1"), long("b", "w2"), long("c", "w3")];
  const msg = buyerIndividualMessage({
    ready, wines, city: "Hong Kong", link: "https://example.com/share/" + "x".repeat(40),
    expiryDays: 7, priceFmt: hk,
  });
  assert.ok(msg.length <= MAX_MESSAGE_LENGTH || msg.split("\n").filter((l) => l.includes(" at HK$")).length <= 2);
});

test("the buyer-group message names every wine, no price, no saving claim, no forbidden word", () => {
  const a = line("a", { wine_id: "dp", vintage: 2008, offer: 132, floor: 162, quantity: 46 });
  const b = line("b", { wine_id: "cristal", vintage: 2005, offer: 169, floor: 194, quantity: 24 });
  const msg = buyerGroupMessage({ ready: [a, b], wines: WINES, city: "Hong Kong", link: "https://x/share/tok" });
  assert.ok(msg.includes("Dom Pérignon Vintage 2008, Louis Roederer Cristal 2005"));
  assert.ok(msg.includes("70 bottles"));
  assert.ok(!msg.includes("HK$"));
  assert.ok(!/seller[\s_]?net|commission|\bcost\b|\bmargin\b/i.test(msg));
});

test("the seller message carries net, commission, and the held-back count", () => {
  const shared = line("shared", { offer: 150, seller: 138, gp: 12, quantity: 2, compCount: 2 });
  const held = line("held", { offer: 90, compCount: 1 });
  const msg = sellerMessage({
    ready: [shared], dealLines: [shared, held], sharedLineIds: ["shared"],
    link: "https://x/share/tok", priceFmt: hk,
  });
  assert.ok(msg.includes("1 of your line is ready to go out"));
  assert.ok(msg.includes("after my 8%"));
  assert.ok(msg.includes("1 more line only had one merchant quoting"));
  assert.ok(msg.includes("Say the word and I'll send it."));
});
