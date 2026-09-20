"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import * as XLSX from "xlsx";
import { api } from "../lib/api";
import { guessMapping, toLine, toLines } from "../lib/lines";

// The row -> line rules live in lib/lines.js and are covered by `npm test`:
// the seller's row is sent exactly as it was read, and money stays a string.
const FIELDS = [
  ["description", "Wine (as the seller wrote it)", true],
  ["quantity", "Quantity", true],
  ["cost", "Cost per unit", false],
];

export default function Upload({ onDone }) {
  const router = useRouter();
  const [rows, setRows] = useState(null);
  const [headers, setHeaders] = useState([]);
  const [mapping, setMapping] = useState({});
  const [meta, setMeta] = useState({ name: "", seller: "", currency: "GBP", target_margin: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function readFile(file) {
    setError(null);
    try {
      const workbook = XLSX.read(await file.arrayBuffer(), { cellDates: false });
      const sheet = workbook.Sheets[workbook.SheetNames[0]];
      // raw: false gives the text as displayed, so a price stays "2,353.10"
      // rather than becoming a float.
      const parsed = XLSX.utils.sheet_to_json(sheet, { defval: "", raw: false });
      if (!parsed.length) throw new Error("that sheet has no rows");
      const cols = Object.keys(parsed[0]);
      setRows(parsed);
      setHeaders(cols);
      setMapping(guessMapping(cols));
      setMeta((m) => ({ ...m, name: m.name || file.name.replace(/\.[^.]+$/, "") }));
    } catch (e) {
      setRows(null);
      setError(e.message);
    }
  }

  const line = (row, index) => toLine(row, index, mapping, meta.currency);
  const preview = rows ? rows.slice(0, 5).map(line) : [];
  const unnamed = rows ? rows.filter((r, i) => !line(r, i).raw_description).length : 0;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const lines = toLines(rows, mapping, meta.currency);
      const deal = await api.post("/deals", {
        name: meta.name,
        seller: meta.seller || null,
        currency: meta.currency,
        target_margin: meta.target_margin ? Number(meta.target_margin) / 100 : null,
        lines,
      });
      onDone?.();
      router.push(`/deals/${deal.deal_id}`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Load a seller&rsquo;s list</h2>
      {error && <div className="notice bad">{error}</div>}
      <div className="row">
        <div className="grow">
          <label htmlFor="file">Spreadsheet (.xlsx, .xls or .csv)</label>
          <input id="file" type="file" accept=".xlsx,.xls,.csv"
                 onChange={(e) => e.target.files[0] && readFile(e.target.files[0])} />
        </div>
      </div>

      {rows && (
        <>
          <div className="row" style={{ marginTop: 14 }}>
            <div className="grow">
              <label htmlFor="deal-name">Deal name</label>
              <input id="deal-name" value={meta.name}
                     onChange={(e) => setMeta({ ...meta, name: e.target.value })} />
            </div>
            <div className="grow">
              <label htmlFor="seller">Seller</label>
              <input id="seller" value={meta.seller}
                     onChange={(e) => setMeta({ ...meta, seller: e.target.value })} />
            </div>
            <div style={{ width: 110 }}>
              <label htmlFor="ccy">Cost currency</label>
              <input id="ccy" value={meta.currency} maxLength={3}
                     onChange={(e) => setMeta({ ...meta, currency: e.target.value.toUpperCase() })} />
            </div>
            <div style={{ width: 140 }}>
              <label htmlFor="margin">Deal margin %</label>
              <input id="margin" inputMode="decimal" placeholder="optional"
                     value={meta.target_margin}
                     onChange={(e) => setMeta({ ...meta, target_margin: e.target.value })} />
            </div>
          </div>

          <div className="row" style={{ marginTop: 14 }}>
            {FIELDS.map(([key, label, required]) => (
              <div className="grow" key={key}>
                <label htmlFor={`map-${key}`}>{label}{required ? "" : " (optional)"}</label>
                <select id={`map-${key}`} value={mapping[key] || ""}
                        onChange={(e) => setMapping({ ...mapping, [key]: e.target.value })}>
                  <option value="">—</option>
                  {headers.map((h) => <option key={h} value={h}>{h}</option>)}
                </select>
              </div>
            ))}
          </div>

          <p className="muted" style={{ fontSize: 13, marginTop: 14 }}>
            {rows.length} rows read. Every row is stored exactly as it appears in the
            file; the columns above only say what to read.
            {unnamed > 0 && ` ${unnamed} row(s) have no wine text and will be skipped.`}
          </p>

          <div className="scroll">
            <table>
              <thead>
                <tr><th>#</th><th>Wine</th><th className="num">Qty</th><th className="num">Cost</th></tr>
              </thead>
              <tbody>
                {preview.map((line) => (
                  <tr key={line.row_index}>
                    <td className="muted">{line.row_index + 1}</td>
                    <td className="verbatim">{line.raw_description || <span className="muted">— skipped —</span>}</td>
                    <td className="num">{line.quantity}</td>
                    <td className="num">{line.cost ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ marginTop: 14 }}>
            <button onClick={submit} disabled={busy || !meta.name || !mapping.description}>
              {busy ? "Loading…" : `Load ${rows.length - unnamed} lines`}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
