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
