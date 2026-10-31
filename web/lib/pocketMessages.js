// VESSEL Pocket's three outbound texts. Pure: same facts in, same text out.
// The tombstone goes to a buyer and passes assertBuyerSafe() like every
// other buyer message; the two handoffs go to the supplier and to admin and
// are built only from the frozen confirmation record. Every price is in the
// supplier's quote unit with an ISO code, never a symbol (decision 0047).
import { assertBuyerSafe } from "./offerMessages.js";
import { fmt, quoteLabel, toPence, toQuote } from "./vesselSell.js";

function size(bottleMl) {
  return `${bottleMl / 10}cl`;
}

/** "3 × 75cl" loose, "5 × 6 × 75cl" for cases — the trade's own shorthand. */
export function formatLine({ quantity, pack_size, bottle_ml }) {
  return pack_size === 1 ? `${quantity} × ${size(bottle_ml)}`
    : `${quantity} × ${pack_size} × ${size(bottle_ml)}`;
}

/** "GBP 4,315 /cs of 6" from a per-commercial-unit amount. */
export function quotePrice(unitAmount, unit, packSize, currency = "GBP", opts = {}) {
  return `${fmt(toQuote(toPence(unitAmount), unit, packSize), currency, opts)} ${quoteLabel(unit, packSize)}`;
}

/** Wine, line, where it is, the committed VESSEL sell price in the supplier's
 * own unit, and availability only if Doug stated it — never the supplier,
 * the supplier price or any market figure. */
export function tombstone({ wineName, quantity, pack_size, bottle_ml, bond_status,
                            stock_location, availability, vesselSell, quoteUnit,
                            currency = "GBP" }) {
  const where = [bond_status, stock_location].filter(Boolean).join(" · ");
  const lines = [
    wineName,
    [formatLine({ quantity, pack_size, bottle_ml }), where].filter(Boolean).join(" · "),
    quotePrice(vesselSell, quoteUnit, pack_size, currency, { whole: true }),
    availability || null,
  ].filter(Boolean);
  return assertBuyerSafe(lines.join("\n"));
}

/** To the supplier, from the frozen record: the agreed supplier price, exactly
 * as quoted — a supplier's own decimals are never rounded away. */
export function supplierHandoff(f) {
  return [
    "CONFIRMED",
    "",
    f.wine_name,
    formatLine(f),
    "",
    `Agreed ${quotePrice(f.supplier_price, f.quote_unit, f.pack_size, f.currency)}`,
    "",
    "Please hold stock.",
    "Transfer details to follow.",
  ].join("\n");
}

/** To admin: both sides and the gross, from the frozen record. */
export function adminHandoff(f) {
  const buy = toPence(f.supplier_price) * f.quantity;
  const sell = toPence(f.vessel_sell_price) * f.quantity;
  const stock = [f.stock_location, f.bond_status].filter(Boolean).join(" · ");
  return [
    "NEW CONFIRMED TRADE",
    "",
    `Supplier: ${f.supplier_name}`,
    `Buyer: ${f.buyer_name}`,
    "",
    f.wine_name,
    formatLine(f),
    "",
    `Buy: ${fmt(buy, f.currency)}`,
    `Sell: ${fmt(sell, f.currency, { whole: true })}`,
    `Gross: ${fmt(toPence(f.gross_total), f.currency, { whole: true })}`,
    ...(stock ? ["", `Stock: ${stock}`] : []),
    ...(f.availability ? [`Availability: ${f.availability}`] : []),
    "",
    "Action:",
    "invoice buyer",
    "confirm supplier",
    "arrange transfer",
  ].join("\n");
}
