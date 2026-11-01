"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { fetchInto, listStateMessage, LOADING } from "../../lib/fetchState";
import { TradeRow } from "../trade-row";

/** To Review (decision 0051): exactly what the Workbench's TO REVIEW counts —
 * Pocket offers, cellar lines, new merchants, LWIN conflicts and wine
 * spellings — and nothing it does not. Each section appears only when it has
 * something in it; a list that could not load says so and is never shown as
 * an empty one (decision 0040). */
export default function QueuePage() {
  const [wb, setWb] = useState(LOADING);
  const [lines, setLines] = useState(LOADING);
  const [merchants, setMerchants] = useState(LOADING);
  const [conflicts, setConflicts] = useState(LOADING);
  const [suggestions, setSuggestions] = useState(LOADING);

  const load = useCallback(() => {
    fetchInto(setWb, api.get("/workbench"));
    fetchInto(setLines, api.get("/review-queue"));
    fetchInto(setMerchants, api.get("/merchants/review"));
    fetchInto(setConflicts, api.get("/lwin-conflicts"));
    fetchInto(setSuggestions, api.get("/alias-suggestions"));
  }, []);
  useEffect(load, [load]);

  function action(line) {
    if (line.line_state === "IDENTITY_NOT_APPROVED") return "Review identity";
    if (line.line_state === "NOT_SEARCHED") return "Check market";
    if (line.requires_acknowledgement && !line.acknowledged) return "Accept price";
    if (line.line_state === "REVIEW") return "Check evidence";
    return "Review";
  }

  const all = [wb, lines, merchants, conflicts, suggestions];
  const loading = all.some((x) => x.status === "loading");
  const offers = wb.status === "ok" ? wb.data.to_review : [];
  const nothing = !loading && all.every((x) => x.status === "ok")
    && offers.length + lines.data.length + merchants.data.to_review.length
       + conflicts.data.length + suggestions.data.length === 0;

  return (
    <>
      <h1>To review</h1>
      <p className="sub">Everything waiting on your decision.</p>
      {loading && <p className="muted">Loading…</p>}
      {nothing && <p className="muted">Nothing to review.</p>}

      <Section id="offers" title="Offers" state={wb} count={offers.length} errorLabel="Couldn't load offers"
               onRetry={load}>
        <div className="card tlist">
          {offers.map((t) => <TradeRow key={t.inbound_offer_id} t={t} onChanged={load} />)}
        </div>
      </Section>

      <Section id="lines" title="Cellar lines" state={lines} count={lines.data?.length}
               errorLabel="Couldn't load cellar lines" onRetry={load}>
        <div className="card tlist">
          {lines.data?.map((line) => (
            <div key={line.line_id} className="trow">
              <div className="t-what">
                <span className="t-title">{line.raw_description}</span>
                <div className="muted t-small">{line.deal_name}</div>
              </div>
              <div className="t-who t-small muted">Qty {line.quantity}</div>
              <div />
              <div className="t-next t-small">
                <Link href={`/deals/${line.deal_id}/lines`} className="t-action">{action(line)}</Link>
              </div>
              <div />
            </div>
          ))}
        </div>
      </Section>

      <Section id="merchants" title="New merchants" state={merchants}
               count={merchants.data?.to_review.length} errorLabel="Couldn't load merchants" onRetry={load}>
        <p className="muted t-small" style={{ marginTop: 0 }}>
          Introduced by a market feed. Their prices are kept but set no Floor until you approve them.
        </p>
        <div className="card tlist">
          {merchants.data?.to_review.map((m) => <Merchant key={m.merchant_id} m={m} onDone={load} />)}
        </div>
      </Section>
      {merchants.status === "ok" && merchants.data.kept_unapproved.length > 0 && (
        <details style={{ marginBottom: 16 }}>
          <summary className="muted t-small" style={{ cursor: "pointer" }}>
            Kept unapproved ({merchants.data.kept_unapproved.length})
          </summary>
          <div className="card tlist" style={{ marginTop: 8 }}>
            {merchants.data.kept_unapproved.map((m) => <Merchant key={m.merchant_id} m={m} kept onDone={load} />)}
          </div>
        </details>
      )}

      <Section id="lwin" title="LWIN conflicts" state={conflicts} count={conflicts.data?.length}
               errorLabel="Couldn't load LWIN conflicts" onRetry={load}>
        {conflicts.data?.map((c) => <Conflict key={c.conflict_id} conflict={c} onDone={load} />)}
      </Section>

      <Section id="spellings" title="Wine spellings to approve" state={suggestions}
               count={suggestions.data?.length} errorLabel="Couldn't load wine spellings" onRetry={load}>
        <div className="card scroll">
          <table>
            <thead>
              <tr><th>Seller wording</th><th>Corrected to</th><th className="num">Times</th><th>By</th></tr>
            </thead>
            <tbody>
              {suggestions.data?.map((s) => (
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
      </Section>
    </>
  );
}

/** A section shows when it has something to decide, or when it could not
 * load — never as an empty heading. */
function Section({ id, title, state, count, errorLabel, onRetry, children }) {
  if (state.status === "loading") return null;
  if (state.status === "error") {
    return (
      <>
        <h2 id={id}>{title}</h2>
        <QueueMessage state={state} empty="" errorLabel={errorLabel} onRetry={onRetry} />
      </>
    );
  }
  if (!count) return null;
  return (
    <>
      <h2 id={id}>{title} <span className="muted wb-count">{count}</span></h2>
      {children}
    </>
  );
}

/** APPROVE or KEEP UNAPPROVED (decision 0051). Never automatic. */
function Merchant({ m, kept = false, onDone }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function decide(approve) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/merchants/${encodeURIComponent(m.merchant_id)}/review`, { approve });
      onDone();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }
  return (
    <div className="reg-row" style={{ alignItems: "center", flexWrap: "wrap" }}>
      <span>
        <strong>{m.name}</strong>
        <span className="muted t-small" style={{ display: "block" }}>
          {m.sources.length ? m.sources.join(", ") : "Source not recorded"}
          {" · "}{m.observations} observation{m.observations === 1 ? "" : "s"} held
        </span>
        {error && <span className="notice bad t-small" style={{ display: "block", marginTop: 6 }}>{error}</span>}
      </span>
      <span className="row" style={{ gap: 8 }}>
        <button type="button" className="small" disabled={busy} onClick={() => decide(true)}>APPROVE</button>
        {!kept && (
          <button type="button" className="small quiet" disabled={busy} onClick={() => decide(false)}>
            KEEP UNAPPROVED
          </button>
        )}
      </span>
    </div>
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
