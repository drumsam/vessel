// Shared between the Cellar Desk and the client offer document: a line's
// own wine, resolved through the approved wine_id when there is one, never
// re-parsed from raw_description — that parsing is the operator's own job,
// upstream of this.
export function wineLabel(line, wines) {
  const w = line.wine_id ? wines.get(line.wine_id) : null;
  if (!w) return { producer: line.raw_description, cuvee: "", vintage: "" };
  return {
    producer: w.producer, cuvee: w.cuvee,
    vintage: line.vintage === 1000 ? "NV" : String(line.vintage ?? ""),
  };
}

// Shared between the operator's own offer document (/deals/{id}/offer) and
// the public, no-login one (/share/{token}): how a merchant's own unit is
// described on the evidence table, from CompOut's own pack_size/bottle_ml —
// "6 x 75cl case" when it was a case, never just "75cl" on its own.
export function clLabel(bottleMl) {
  const cl = bottleMl / 10;
  return (Number.isInteger(cl) ? cl : cl.toFixed(1)) + "cl";
}

export function listedAs(packSize, bottleMl) {
  const unit = clLabel(bottleMl);
  return packSize === 1 ? `1 x ${unit}, In Bond` : `${packSize} x ${unit} case, In Bond`;
}

export function formatDate(iso) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}
