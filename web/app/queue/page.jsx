"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, money } from "../../lib/api";
import { Flags, StateTag } from "../state";

/** Everything waiting on a person: lines, LWIN conflicts, alias suggestions. */
export default function QueuePage() {
  const [lines, setLines] = useState([]);
  const [conflicts, setConflicts] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api.get("/review-queue").then(setLines).catch((e) => setError(e.message));
    api.get("/lwin-conflicts").then(setConflicts).catch(() => {});
    api.get("/alias-suggestions").then(setSuggestions).catch(() => {});
  }, []);
  useEffect(load, [load]);

  function waitingFor(line) {
    if (line.line_state === "IDENTITY_NOT_APPROVED") return "an approved identity";
    if (line.line_state === "NOT_SEARCHED") return "a merchant search";
    if (line.requires_acknowledgement && !line.acknowledged) return "the price to be accepted";
    if (line.line_state === "REVIEW") return "the evidence to be checked";
    if (line.line_state === "NO_MARKET") return "nothing — no merchant offers it";
    return "review";
  }

  return (
    <>
      <h1>Exceptions</h1>
      <p className="sub">Everything a person has to decide, across every deal.</p>
      {error && <div className="notice bad">{error}</div>}

      <h2>Lines ({lines.length})</h2>
      {lines.length === 0 ? <p className="muted">Nothing waiting.</p> : (
        <div className="card scroll">
          <table>
            <thead>
              <tr><th>Deal</th><th>Seller wording</th><th>State</th><th>Waiting for</th>
                  <th className="num">Reference</th><th className="num">Sell</th></tr>
            </thead>
            <tbody>
              {lines.map((line) => (
                <tr key={line.line_id}>
                  <td><Link href={`/deals/${line.deal_id}`}>{line.deal_name}</Link></td>
                  <td>
                    <div className="verbatim">{line.raw_description}</div>
                    <Flags flags={line.benchmark_flags} tone="review" />
                    <Flags flags={line.line_flags} tone="review" />
                  </td>
                  <td><StateTag state={line.line_state} /></td>
                  <td className="muted">{waitingFor(line)}</td>
                  <td className="num">{money(line.uk_reference)}</td>
                  <td className="num">{money(line.sell_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>LWIN conflicts ({conflicts.length})</h2>
      {conflicts.length === 0 ? <p className="muted">None open.</p> :
        conflicts.map((c) => <Conflict key={c.conflict_id} conflict={c} onDone={load} />)}

      <h2>Alias suggestions ({suggestions.length})</h2>
      {suggestions.length === 0 ? <p className="muted">None yet.</p> : (
        <div className="card scroll">
          <table>
            <thead>
              <tr><th>Seller wording</th><th>Corrected to</th><th className="num">Times</th><th>By</th></tr>
            </thead>
            <tbody>
              {suggestions.map((s) => (
                <tr key={s.normalised + s.wine_id}>
                  <td className="verbatim">{s.seller_text}</td>
                  <td>{s.producer} — {s.cuvee}</td>
                  <td className="num">{s.line_ids.length}</td>
                  <td className="muted">{s.changed_by.map((o) => o.display_name).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: 13 }}>
            The same wording corrected to the same wine more than once. Turning one into an
            alias is your call: you choose the producer and cuvée wording it should carry.
          </p>
        </div>
      )}
    </>
  );
}

function Conflict({ conflict, onDone }) {
  const [wines, setWines] = useState([]);
  const [choice, setChoice] = useState({});
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.get("/wines").then(setWines).catch(() => {}); }, []);

  async function resolve(resolution) {
    setBusy(true);
    setError(null);
    try {
      const body = { resolution, note: note || null };
      if (resolution === "same_wine") {
        body.aliases = conflict.names.map((name) => {
          const [producer_text, cuvee_text = ""] = name.split(" / ");
          return { wine_id: choice[name], producer_text, cuvee_text };
        }).filter((a) => a.wine_id);
      } else {
        body.exclude = [...new Set(Object.values(choice))].slice(0, 2);
      }
      await api.post(`/lwin-conflicts/${conflict.conflict_id}/resolve`, body);
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      {error && <div className="notice bad">{error}</div>}
      <p style={{ marginTop: 0 }}>
        <strong>{conflict.merchant_id}</strong> uses LWIN-7 <strong>{conflict.lwin7}</strong> for{" "}
        {conflict.names.length} different names. Is that one wine under two names, or two wines?
      </p>
      {conflict.names.map((name) => (
        <div className="row" key={name} style={{ marginBottom: 8 }}>
          <div className="grow verbatim">{name}</div>
          <div className="grow">
            <select value={choice[name] || ""}
                    onChange={(e) => setChoice({ ...choice, [name]: e.target.value })}>
              <option value="">which wine is this?</option>
              {wines.map((w) => (
                <option key={w.wine_id} value={w.wine_id}>{w.producer} — {w.cuvee}</option>
              ))}
            </select>
          </div>
        </div>
      ))}
      <div className="row">
        <div className="grow">
          <label htmlFor={`note-${conflict.conflict_id}`}>Note</label>
          <input id={`note-${conflict.conflict_id}`} value={note}
                 onChange={(e) => setNote(e.target.value)} />
        </div>
        <button className="quiet" disabled={busy} onClick={() => resolve("same_wine")}>
          One wine — approve alias
        </button>
        <button disabled={busy} onClick={() => resolve("different_wines")}>
          Different wines — exclude
        </button>
      </div>
    </div>
  );
}
