// VESSEL Pocket's three outbound texts. Pure: same facts in, same text out.
// The tombstone goes to a buyer and passes assertBuyerSafe() like every
// other buyer message; the two handoffs go to the supplier and to admin and
// are built only from the frozen confirmation record.
import { assertBuyerSafe } from "./offerMessages.js";
import { divHalfEven, gbp, toPence } from "./vesselSell.js";

function size(bottleMl) {
  return `${bottleMl / 10}cl`;
}

/** "3 × 75cl" loose, "1 × 6 × 75cl" for cases — the trade's own shorthand. */
export function formatLine({ quantity, pack_size, bottle_ml }) {
  return pack_size === 1 ? `${quantity} × ${size(bottle_ml)}`
    : `${quantity} × ${pack_size} × ${size(bottle_ml)}`;
}

function unitPrice(unitPence, packSize) {
  return packSize === 1 ? `${gbp(unitPence)}/bt` : `${gbp(unitPence)}/case`;
}

/** Wine, line, where it is, the committed VESSEL sell price, and
 * availability only if Doug stated it — nothing else, and never the
 * supplier, the supplier price or any market figure. */
export function tombstone({ wineName, quantity, pack_size, bottle_ml, bond_status,
                            stock_location, availability, vesselSell }) {
  const where = [bond_status, stock_location].filter(Boolean).join(" · ");
  const lines = [
    wineName,
    [formatLine({ quantity, pack_size, bottle_ml }), where].filter(Boolean).join(" · "),
    unitPrice(toPence(vesselSell), pack_size),
    availability || null,
  ].filter(Boolean);
  return assertBuyerSafe(lines.join("\n"));
}

/** To the supplier, from the frozen record: the agreed supplier price only. */
export function supplierHandoff(f) {
  return [
    "CONFIRMED",
    "",
    f.wine_name,
    formatLine(f),
    "",
    `Agreed ${unitPrice(toPence(f.supplier_price), f.pack_size)}`,
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
    `Buy: ${gbp(buy)}`,
    `Sell: ${gbp(sell)}`,
    `Gross: ${gbp(toPence(f.gross_total))}`,
    ...(stock ? ["", `Stock: ${stock}`] : []),
    ...(f.availability ? [`Availability: ${f.availability}`] : []),
    "",
    "Action:",
    "invoice buyer",
    "confirm supplier",
    "arrange transfer",
  ].join("\n");
}

/** Per-bottle display of a per-unit amount (a case price / its pack size). */
export function perBottlePence(unitPence, packSize) {
  return divHalfEven(unitPence, packSize);
}
