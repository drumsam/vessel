// Turning a spreadsheet row into a deal line. Pure, so it can be tested with
// `npm test` — the parser runs in the browser, but the rule it has to obey is
// the project's oldest: the seller's original row is never destroyed.

export const COLUMN_GUESSES = {
  description: ["wine", "description", "item", "lot"],
  quantity: ["qty", "quantity", "bottles", "units"],
  cost: ["cost", "price", "ask"],
};

export function guessMapping(headers) {
  const lower = headers.map((h) => String(h).toLowerCase());
  const pick = (candidates) => {
    for (const candidate of candidates) {
      const index = lower.findIndex((h) => h.includes(candidate));
      if (index >= 0) return headers[index];
    }
    return "";
  };
  return Object.fromEntries(
    Object.entries(COLUMN_GUESSES).map(([field, candidates]) => [field, pick(candidates)]));
}

/**
 * One line, ready to POST.
 *
 * `raw_row` is the row object exactly as it was read: no trimming, no renaming,
 * no dropped columns. The mapping only says which column to READ.
 *
 * Money stays a string all the way to the API, which refuses a JSON number.
 * "£2,353.10" becomes "2353.10" — the same pence, never a float.
 */
export function toLine(row, index, mapping, currency = "GBP") {
  const text = (column) => (column ? String(row[column] ?? "") : "");
  const quantity = parseInt(text(mapping.quantity).replace(/[^\d]/g, ""), 10);
  const cost = money(text(mapping.cost));
  return {
    row_index: index,
    raw_description: text(mapping.description).trim(),
    raw_row: row,
    quantity: Number.isFinite(quantity) && quantity > 0 ? quantity : 1,
    ...(cost ? { cost, cost_currency: currency } : {}),
  };
}

/** "£2,353.10" -> "2353.10"; "" or unreadable -> null. Never rounds. */
export function money(value) {
  const cleaned = String(value).replace(/[^\d.]/g, "");
  if (!cleaned || !/^\d*\.?\d*$/.test(cleaned) || Number(cleaned) <= 0) return null;
  const [pounds, pence = ""] = cleaned.split(".");
  if (pence.length > 2) return null;          // not whole pence: let a person look
  return `${pounds || "0"}.${pence.padEnd(2, "0")}`;
}

export function toLines(rows, mapping, currency = "GBP") {
  return rows.map((row, index) => toLine(row, index, mapping, currency))
             .filter((line) => line.raw_description);
}
