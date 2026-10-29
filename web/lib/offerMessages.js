// WhatsApp message templates for a shared offer link (decision 0035/0036).
// Doug's own three drafts, verbatim structure, tokens substituted here —
// "use it as the default text rather than inventing copy." Every function
// here is pure: given the same lines and the same link, it always builds
// the same text. Doug edits freely in WhatsApp before sending; nothing
// here ever sends anything itself.
//
// The rules he gave "to enforce in code, not in the copy":
//   - a buyer message never touches seller_price_gbp, commission_gbp, cost
//     or margin — structurally true here, because no buyer builder ever
//     reads those fields, not because a check filters them out after.
//   - no message prints a percentage claim decision 0034 suppressed
//     (MIN_CLAIM_THRESHOLD_PCT, below) — never from an individual
//     suppressed line, and never averaged over a drop that contains one.
//   - never "0%".
//   - a rendered buyer-to-one-person message over ~600 characters drops
//     the top three lines to two.
import { wineLabel } from "./wine.js";

export const MAX_MESSAGE_LENGTH = 600;
//: Must match app/core/flags.py::MIN_CLAIM_THRESHOLD (as a percentage).
//: Decision 0034's own constant, not re-exported by the API, so this is
//: the one place the frontend keeps its own copy of the same number.
export const MIN_CLAIM_THRESHOLD_PCT = 5;

const FORBIDDEN_IN_BUYER_MESSAGE = [
  /seller[\s_]?net/i, /commission/i, /\bcost\b/i, /\bmargin\b/i,
  // supplier-attribution-spec.md: a new leak surface this assertion did
  // not know about yet -- a wrong supplier attribution outbound is a
  // commercial injury to Doug (which trader a parcel came from), the
  // same class of error as leaking cost, not a privacy nicety.
  /\bsupplier[\s_]?id\b/i, /\bsupplier\b/i, /contact[\s_]?name/i, /\bphone\b/i,
];

/** Decision 0035's own rule, checked again here rather than trusted: a
 * buyer message that somehow gained one of these words is a bug, and
 * fails loudly (so it is caught before anything is sent) rather than
 * quietly leaking it. */
export function assertBuyerSafe(message) {
  for (const re of FORBIDDEN_IN_BUYER_MESSAGE) {
    if (re.test(message)) throw new Error(`buyer message must not mention: ${re}`);
  }
  return message;
}

/** producer + cuvee + vintage, vintage omitted entirely for NV — not
 * printed as "NV", just absent, per Doug's own instruction. */
export function wineName(line, wines) {
  const label = wineLabel(line, wines);
  const vintage = label.vintage === "NV" ? "" : label.vintage;
  return [label.producer, label.cuvee, vintage].filter(Boolean).join(" ");
}

/** Up to `n` lines, highest offer price first, one per line: "Dom
 * Pérignon Vintage 2008 at HK$1,370 a bottle" — per bottle, never a line
 * total (Doug's own words, same discipline as the per-bottle-first
 * display this composer sits next to). */
export function topLines(ready, wines, priceFmt, n = 3) {
  return [...ready]
    .sort((a, b) => Number(b.pricing.buyer_price_gbp ?? b.pricing.sell_price)
                  - Number(a.pricing.buyer_price_gbp ?? a.pricing.sell_price))
    .slice(0, n)
    .map((l) => `${wineName(l, wines)} at ${priceFmt(Number(l.pricing.buyer_price_gbp ?? l.pricing.sell_price))} a bottle`);
}

/** Comma-separated names, no prices — for the group message, which names
 * every wine but no figure at all. */
export function wineNames(ready, wines) {
  return ready.map((l) => wineName(l, wines)).join(", ");
}

/** " Roughly N% under the cheapest I could find." or "" — omitted
 * entirely, not printed as 0%, whenever ANY selected line has no
 * printable claim under decision 0034 (floor_saving_claim is null), or
 * the blended figure itself is below the same threshold that suppresses
 * a single line. Never averages a suppressed line into the figure by
 * including it in the totals while pretending it has a claim. */
export function savingSentence(ready) {
  const anySuppressed = ready.some((l) => l.pricing.floor_saving_claim === null
                                        || l.pricing.floor_saving_claim === undefined);
  if (anySuppressed) return "";
  const totalFloor = ready.reduce((s, l) => s + Number(l.pricing.uk_floor) * l.quantity, 0);
  const totalOffer = ready.reduce(
    (s, l) => s + Number(l.pricing.buyer_price_gbp ?? l.pricing.sell_price) * l.quantity, 0);
  if (!totalFloor) return "";
  const pct = Math.round((1 - totalOffer / totalFloor) * 100);
  if (pct < MIN_CLAIM_THRESHOLD_PCT) return "";
  return ` Roughly ${pct}% under the cheapest I could find.`;
}

/** "N more lines only had one merchant quoting..." — counts priced lines
 * of the SAME deal that are outside this particular shared set and are
 * gated on exactly one merchant (ONE_COMP). Omitted entirely at n == 0. */
export function heldSentence(dealLines, sharedLineIds) {
  const shared = new Set(sharedLineIds);
  const n = dealLines.filter((l) => l.pricing?.sell_price && l.pricing?.uk_reference
                                   && !shared.has(l.line_id) && l.pricing.comp_count === 1).length;
  if (n === 0) return "";
  return `${n} more line${n === 1 ? "" : "s"} only had one merchant quoting, so I'd rather hold ` +
         `${n === 1 ? "it" : "those"} than price ${n === 1 ? "it" : "them"} off a single source.`;
}

export function sellerTotals(ready) {
  const totalBottles = ready.reduce((s, l) => s + l.quantity, 0);
  const totalOffer = ready.reduce(
    (s, l) => s + Number(l.pricing.buyer_price_gbp ?? l.pricing.sell_price) * l.quantity, 0);
  const totalNet = ready.reduce(
    (s, l) => s + Number(l.pricing.seller_price_gbp ?? l.pricing.sell_price) * l.quantity, 0);
  const totalCommission = ready.reduce((s, l) => s + Number(l.pricing.gp ?? 0) * l.quantity, 0);
  const commissionPct = totalOffer ? Math.round((totalCommission / totalOffer) * 100) : 0;
  return { totalBottles, totalOffer, totalNet, totalCommission, commissionPct };
}

function cityPhraseIndividual(city) {
  return city ? `a ${city} cellar` : "a cellar";
}

function cityPhraseGroup(city) {
  return city ? `one ${city} cellar` : "one cellar";
}

/** "N lines out of a {city} cellar..." — to one person, Doug's first
 * template. Drops to the top TWO lines, not three, once the full message
 * would run past MAX_MESSAGE_LENGTH: these go to WhatsApp, not an inbox. */
export function buyerIndividualMessage({ ready, wines, city, link, expiryDays, priceFmt }) {
  const n = ready.length;
  const saving = savingSentence(ready);
  const build = (topN) => [
    `${n} line${n === 1 ? "" : "s"} out of ${cityPhraseIndividual(city)} I'm handling — single owner, ` +
      `professionally stored, all In Bond here.`,
    topLines(ready, wines, priceFmt, topN).join("\n"),
    `Full list: ${link}`,
    `Every price shows the merchants behind it and what they're charging, so you can check me in ` +
      `thirty seconds.${saving}`,
    `First to confirm takes the line. Open ${expiryDays} day${expiryDays === 1 ? "" : "s"}.`,
  ].filter(Boolean).join("\n\n");

  const full = build(3);
  return assertBuyerSafe(full.length > MAX_MESSAGE_LENGTH ? build(2) : full);
}

/** "Champagne from one {city} cellar..." — to a group, Doug's second
 * template. No top lines, no per-bottle price, no saving claim at all:
 * just the wine names and the link, evidence lives behind it. */
export function buyerGroupMessage({ ready, wines, city, link }) {
  const n = ready.length;
  const totalBottles = ready.reduce((s, l) => s + l.quantity, 0);
  const message = [
    `Champagne from ${cityPhraseGroup(city)}, In Bond. ${wineNames(ready, wines)}. ` +
      `${totalBottles} bottle${totalBottles === 1 ? "" : "s"}.`,
    link,
    `Prices are set against live merchant offers and the evidence is on every line — you'll see ` +
      `exactly who I'm pricing against. Not a round-number discount; the real figure per wine, some ` +
      `better than others.`,
    `Reply here with the lines you want.`,
  ].filter(Boolean).join("\n\n");
  return assertBuyerSafe(message);
}

/** Doug's third template, for the seller: net and commission, never
 * another buyer's name or another seller's cellar (both out of scope by
 * construction — this only ever reads the one deal the operator is on). */
export function sellerMessage({ ready, dealLines, sharedLineIds, link, priceFmt }) {
  const n = ready.length;
  const { totalBottles, totalNet, commissionPct } = sellerTotals(ready);
  const held = heldSentence(dealLines, sharedLineIds);
  return [
    `${n} of your line${n === 1 ? "" : "s"} ${n === 1 ? "is" : "are"} ready to go out — ${totalBottles} bottle` +
      `${totalBottles === 1 ? "" : "s"}, ${priceFmt(totalNet)} to you after my ${commissionPct}%. ` +
      `Here's exactly what the buyers see, including every merchant price I'm using: ${link}`,
    held,
    `Say the word and I'll send it.`,
  ].filter(Boolean).join("\n\n");
}
