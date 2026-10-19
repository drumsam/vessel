// Shared between the Cellar Desk (web/app/deals/[dealId]/page.jsx) and the
// pipeline's own line detail (web/app/deals/[dealId]/lines/line.jsx):
// why a line needs a person, in plain words.
//
// Extracted so the two never say different things about the same flags —
// a flag added or renamed in app/core/flags.py now has exactly one place
// in this app's own JS to update, not two that can quietly drift apart.
// This mirrors app/db/repo.py's own `gate_reason_phrase` (independently,
// not by sharing code across the Python/JS boundary) for the one place
// outside either screen that still has to explain the same thing: an
// error string the API returns when an unaccepted line is sent anyway.

export function gapPercent(floor, reference) {
  if (!floor || !reference) return null;
  const f = Number(floor), r = Number(reference);
  if (!f) return null;
  return Math.round(((r - f) / f) * 1000) / 10;
}

export function gated(line) {
  return !!(line.pricing?.requires_acknowledgement && !line.pricing?.acknowledgement);
}

/** Evidence-quality and identity flags that gate (REVIEW_FLAGS in
 * app/core/flags.py), each mapped to a short human phrase — ONE_COMP and
 * WIDE_SPREAD-at-two-comps are handled separately in `reasonFor` because
 * they need the comp count/gap, not a fixed phrase. QUANTITY_SHORTFALL is
 * deliberately not here: it never gates on its own (REQUIRE_QUANTITY_COVER
 * is False), so it is only ever appended as context onto another reason. */
export const BENCHMARK_FLAG_PHRASES = {
  DERIVED_FROM_CASE: "case divided",
  CONDITION_REVIEW: "condition flagged",
  STOCK_BASIS_UNCONFIRMED: "stock basis unconfirmed",
  NAME_REVIEW: "name needs confirming",
  FORMAT_REVIEW: "format needs confirming",
  COMP_EXCLUDED_VINTAGE_BAND: "a dear comp excluded",
  LOW_COMP_OUT_OF_BAND: "a cheap comp flagged",
};

/** Commercial flags (app/pricing/pricer.py) that also gate export
 * (EXPORT_GATE_FLAGS, app/db/repo.py) even when the benchmark itself is
 * READY with plenty of agreement -- a line can need a person for a
 * reason that has nothing to do with how many merchants were found. */
export const PRICING_FLAG_PHRASES = {
  NEGATIVE_GP: "would lose money",
  SELL_ABOVE_UK_REFERENCE: "priced above market",
  SELL_AT_OR_ABOVE_UK_FLOOR: "not actually below market",
};

/** The reason a gated line needs a person, in the engine's own flags, in
 * plain words -- never a flag constant on screen, and never a badge with
 * no reason visible (Doug, 19 October 2026: "He should never have to
 * ask"; 21 October 2026: "Never a UUID, never a state name, never a flag
 * constant, anywhere a human can see it"). Doesn't decide whether a line
 * gates -- `gated`, above, already reads that straight from the server --
 * only explains a decision already made, from the same flags the server
 * used to make it. */
export function reasonFor(line) {
  if (!gated(line)) return null;
  const b = line.benchmark, p = line.pricing;
  const bFlags = new Set(b?.flags || []);
  const pFlags = new Set(p?.flags || []);
  const parts = [];

  if (b?.state === "NO_MARKET") {
    parts.push("no merchant found");
  } else if (p.comp_count === 1) {
    parts.push("1 merchant");
  } else if (p.comp_count === 2 && bFlags.has("WIDE_SPREAD")) {
    const gap = gapPercent(p.uk_floor, p.uk_reference);
    parts.push(gap !== null ? `2 merchants, ${gap}% apart` : "2 merchants, far apart");
  }

  for (const [flag, phrase] of Object.entries(BENCHMARK_FLAG_PHRASES)) {
    if (bFlags.has(flag)) parts.push(phrase);
  }
  if (bFlags.has("QUANTITY_SHORTFALL")) parts.push("fewer bottles");
  for (const [flag, phrase] of Object.entries(PRICING_FLAG_PHRASES)) {
    if (pFlags.has(flag)) parts.push(phrase);
  }

  return parts.length ? parts.join(" · ") : "needs a look";
}
