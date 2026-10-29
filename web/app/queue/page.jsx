"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, money } from "../../lib/api";
import { fetchInto, listStateMessage, LOADING } from "../../lib/fetchState";
import { Flags, StateTag } from "../state";

/** Everything waiting on a person: lines, LWIN conflicts, alias suggestions.
 * A queue that cannot load is never shown as an empty queue (decision 0040)
 * — "None open"/"None yet" is a checked, clear answer, not a default. */
export default function QueuePage() {
  const [lines, setLines] = useState([]);
  const [conflicts, setConflicts] = useState(LOADING);
  const [suggestions, setSuggestions] = useState(LOADING);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api.get("/review-queue").then(setLines).catch((e) => setError(e.message));
    fetchInto(setConflicts, api.get("/lwin-conflicts"));
    fetchInto(setSuggestions, api.get("/alias-suggestions"));
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

      <h2>LWIN conflicts {conflicts.status === "ok" ? `(${conflicts.data.length})` : ""}</h2>
      <QueueMessage state={conflicts} empty="None open." errorLabel="Couldn't load LWIN conflicts"
                    onRetry={load} />
      {conflicts.status === "ok" && conflicts.data.length > 0 &&
        conflicts.data.map((c) => <Conflict key={c.conflict_id} conflict={c} onDone={load} />)}

      <h2>Alias suggestions {suggestions.status === "ok" ? `(${suggestions.data.length})` : ""}</h2>
      <QueueMessage state={suggestions} empty="None yet." errorLabel="Couldn't load alias suggestions"
                    onRetry={load} />
      {suggestions.status === "ok" && suggestions.data.length > 0 && (
        <div className="card scroll">
          <table>
            <thead>
              <tr><th>Seller wording</th><th>Corrected to</th><th className="num">Times</th><th>By</th></tr>
            </thead>
            <tbody>
              {suggestions.data.map((s) => (
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

/** The one render of `listStateMessage` for this page's two list-shaped
 * states — "couldn't load" and "checked, empty" always come back as
 * different `{text, isError}` pairs (fetchState.test.mjs), so this can
 * never silently go back to the shape that merges them. */
function QueueMessage({ state, empty, errorLabel, onRetry }) {
  const msg = listStateMessage(state, { empty, errorLabel });
  if (!msg) return null;
  return (
    <p className={msg.isError ? "notice bad" : "muted"}>
      {msg.text}
      {msg.isError && <> <button type="button" className="small" onClick={onRetry}>Retry</button></>}
    </p>
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
                <option key={w.wine_id} value={w.wine_id}>
                  {w.producer} — {w.cuvee}{w.release_code ? ` (${w.release_code})` : ""}
                </option>
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
