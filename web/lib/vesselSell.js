// The VESSEL Sell calculator. Integer pence and basis points throughout, so
// the % and the £ stay in sync with no float ever touching a price; rounding
// is half-even to the penny, the same rule app/pricing/pricer.py uses. The
// server re-derives everything from the committed sell price — this only
// drives the screen while Doug adjusts it.

/** "3150.00" (or a number of pounds as a string) → 315000. */
export function toPence(money) {
  const [pounds, pence = "0"] = String(money).split(".");
  const sign = pounds.startsWith("-") ? -1 : 1;
  return sign * (Math.abs(Number(pounds)) * 100 + Number(pence.padEnd(2, "0").slice(0, 2)));
}

/** 315000 → "3150.00", the string shape money crosses the API in. */
export function toMoney(pence) {
  const sign = pence < 0 ? "-" : "";
  const p = Math.abs(pence);
  return `${sign}${Math.floor(p / 100)}.${String(p % 100).padStart(2, "0")}`;
}

/** n / d to the nearest integer, ties to even. d > 0. */
export function divHalfEven(n, d) {
  const sign = n < 0 ? -1 : 1;
  const a = Math.abs(n);
  const q = Math.floor(a / d);
  const r = a - q * d;
  const twice = 2 * r;
  const up = twice > d || (twice === d && q % 2 === 1);
  return sign * (up ? q + 1 : q);
}

/** Supplier price plus a markup in basis points (800 = +8%). */
export function sellFromMarkup(supplierPence, bp) {
  return divHalfEven(supplierPence * (10000 + bp), 10000);
}

/** (V - S) / S in basis points — markup on supplier, never gross margin. */
export function markupBp(sellPence, supplierPence) {
  return divHalfEven((sellPence - supplierPence) * 10000, supplierPence);
}

/** One whole percentage point up or down, snapping to whole points first:
 * +12.5% steps to +13% / +12%, +8% to +9% / +7%. */
export function stepBp(bp, direction) {
  if (direction > 0) return Math.floor(bp / 100) * 100 + 100;
  return Math.ceil(bp / 100) * 100 - 100;
}

/** (M - V) / M in basis points: positive is below market. */
export function vsMarketBp(sellPence, marketPence) {
  return divHalfEven((marketPence - sellPence) * 10000, marketPence);
}

/** 1250 → "+12.5%", 800 → "+8%", -50 → "−0.5%". */
export function formatBp(bp, { signed = true } = {}) {
  const tenths = divHalfEven(bp, 10);
  const abs = Math.abs(tenths);
  const text = `${Math.floor(abs / 10)}${abs % 10 ? `.${abs % 10}` : ""}%`;
  if (!signed) return text;
  return `${tenths < 0 ? "−" : "+"}${text}`;
}

/** 315000 → "£3,150"; 315050 → "£3,150.50". Display only. */
export function gbp(pence) {
  const sign = pence < 0 ? "-" : "";
  const p = Math.abs(pence);
  const pounds = String(Math.floor(p / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const rest = p % 100;
  return `${sign}£${pounds}${rest ? `.${String(rest).padStart(2, "0")}` : ""}`;
}

/** What Doug types for a price — "3150", "3,150", "£3,150.50" — in pence,
 * or null while it isn't a price yet. Never more than two decimals. */
export function parsePounds(text) {
  const cleaned = String(text).replace(/[£,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  return toPence(cleaned);
}

/** The editable text for a pence amount: no symbol, no commas. */
export function inputText(pence) {
  return pence % 100 ? toMoney(pence) : String(Math.floor(pence / 100));
}

const SYMBOL_CURRENCY = { "£": "GBP", "€": "EUR", "$": "USD" };

/** The supplier price as the AI read it ("£3,995", "GBP 19,500") split into
 * the bare amount for the input and the currency the text itself named —
 * reformatting what was written, never interpreting the figure. */
export function splitStatedPrice(text) {
  const raw = String(text ?? "").trim();
  const code = raw.match(/\b([A-Z]{3})\b/)?.[1] ?? null;
  const hk = /HK\$/.test(raw);
  const symbol = [...raw].find((ch) => ch in SYMBOL_CURRENCY);
  const amount = raw.replace(/\b[A-Z]{3}\b/g, "").replace(/HK(?=\$)/g, "").replace(/[£€$,\s]/g, "");
  return { amount, currency: code ?? (hk ? "HKD" : symbol ? SYMBOL_CURRENCY[symbol] : null) };
}
