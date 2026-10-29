"use client";

import { useEffect, useState } from "react";
import { api, money } from "../../lib/api";
import { blocksAction, fetchInto, ok } from "../../lib/fetchState";
import { gapPercent } from "../../lib/pricingReasons";
import { Flags } from "../state";

const EMPTY_COMP = {
  merchant: "", price: "", currency: "GBP", bottle_ml: 750, pack_size: 1,
  duty_status: "IB", price_kind: "ASK", is_buyable: true, source_url: "",
};

const EMPTY_FORM = {
  raw_description: "", wine_id: "", vintage: "", bottle_ml: 750, pack_size: 1,
  quantity: 1, asking_price: "", asking_currency: "GBP",
};

const EMPTY_NEW_WINE = { producer: "", cuvee: "", region: "", colour: "" };

/** The single box (decision 0039): what Doug was offered, and the market
 * prices he found for it, each source named. One line, priced synchronously
 * — no merchant adapter, no job queue. Every comp goes through exactly the
 * same screens a scraped offer would: same Offer model, same vintage-band
 * check, same Floor/Reference/Median. There is no sell-side here — "is this
 * a good price" is a display comparison against the asking price, computed
 * the same way `gapPercent` already compares Floor and Reference elsewhere
 * in this app, never a new pricing rule. */
export default function EvaluatePage() {
  const [wines, setWines] = useState([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [creatingWine, setCreatingWine] = useState(false);
  const [newWine, setNewWine] = useState(EMPTY_NEW_WINE);
  const [comps, setComps] = useState([{ ...EMPTY_COMP }]);
  // decision 0038's safety gate: an unverified producer identity is worth
  // more than a fast screen, so "couldn't check" is a distinct, blocking
  // third state here, never collapsed into "checked, no match" (decision
  // 0040). checkWantList is also the retry action below.
  const [wantListCheck, setWantListCheck] = useState(ok([]));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  useEffect(() => { api.get("/wines").then(setWines).catch(() => {}); }, []);

  function checkWantList(text) {
    fetchInto(setWantListCheck, api.post("/identity/want-list-match", { text }));
  }

  useEffect(() => {
    const text = form.raw_description.trim();
    if (!text) { setWantListCheck(ok([])); return; }
    let current = true;
    const t = setTimeout(() => { if (current) checkWantList(text); }, 300);
    return () => { current = false; clearTimeout(t); };
  }, [form.raw_description]);

  function updateComp(i, patch) {
    setComps(comps.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  }

  function addComp() {
    setComps([...comps, { ...EMPTY_COMP, bottle_ml: form.bottle_ml, pack_size: form.pack_size,
                          currency: form.asking_currency }]);
  }

  function removeComp(i) {
    setComps(comps.filter((_, idx) => idx !== i));
  }

  async function createWine(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const wine = await api.post("/wines", {
        producer: newWine.producer, cuvee: newWine.cuvee,
        region: newWine.region || null, colour: newWine.colour || null,
      });
      setWines([...wines, wine]);
      setForm({ ...form, wine_id: wine.wine_id });
      setCreatingWine(false);
      setNewWine(EMPTY_NEW_WINE);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const line = await api.post("/evaluate", {
        raw_description: form.raw_description, wine_id: form.wine_id,
        vintage: Number(form.vintage), bottle_ml: Number(form.bottle_ml),
        pack_size: Number(form.pack_size), quantity: Number(form.quantity),
        asking_price: form.asking_price, asking_currency: form.asking_currency,
        comps: comps.map((c) => ({
          merchant: c.merchant, price: c.price, currency: c.currency,
          bottle_ml: Number(c.bottle_ml), pack_size: Number(c.pack_size),
          duty_status: c.duty_status, price_kind: c.price_kind, is_buyable: c.is_buyable,
          source_url: c.source_url || null,
        })),
      });
      // LineOut.benchmark (RunSummary) has no per-comp breakdown — that's
      // RunOut, the dedicated endpoint's own response, same split line.jsx
      // already lives with.
      const run = line.benchmark ? await api.get(`/lines/${line.line_id}/benchmark`) : null;
      setResult({ ...line, benchmark: run });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function startAnother() {
    setForm(EMPTY_FORM);
    setComps([{ ...EMPTY_COMP }]);
    setWantListCheck(ok([]));
    setResult(null);
    setError(null);
  }

  const wine = wines.find((w) => w.wine_id === form.wine_id);

  return (
    <>
      <h1>Evaluate an offer</h1>
      <p className="sub">
        One wine, priced manually from Wine-Searcher — no merchant adapter, no job queue.
        Each comp you name goes through exactly the same screens a scraped offer would.
      </p>
      {error && <div className="notice bad">{error}</div>}

      {result ? (
        <EvaluationResult line={result} askingPrice={form.asking_price}
                          onAnother={startAnother} />
      ) : (
        <form onSubmit={submit} className="card">
          <label htmlFor="raw_description">What you were offered, in your own words</label>
          <textarea id="raw_description" rows={2} required value={form.raw_description}
                    onChange={(e) => setForm({ ...form, raw_description: e.target.value })} />
          {wantListCheck.status === "error" ? (
            <div className="notice bad" style={{ fontSize: 13, marginTop: 6 }}>
              Couldn&apos;t verify this producer against the client want list ({wantListCheck.error}).
              On these producers an unverified identity is worth more than a fast screen —
              evaluating is blocked until this check succeeds.{" "}
              <button type="button" className="small"
                      onClick={() => checkWantList(form.raw_description.trim())}>
                Retry
              </button>
            </div>
          ) : wantListCheck.status === "ok" && wantListCheck.data.length > 0 && (
            <div className="notice" style={{ fontSize: 13, marginTop: 6 }}>
              {wantListCheck.data.map((m) => (
                <div key={m.producer}>
                  Looks like <strong>{m.producer}</strong> — on the client want list.
                  {m.always_review ? " Always needs a one-time identity check, even once priced." : ""}
                </div>
              ))}
              A suggestion only — pick the exact wine below yourself.
            </div>
          )}

          <div className="row" style={{ marginTop: 10 }}>
            <div className="grow">
              <label htmlFor="wine">Wine</label>
              <select id="wine" value={form.wine_id} required={!creatingWine}
                      disabled={creatingWine}
                      onChange={(e) => setForm({ ...form, wine_id: e.target.value })}>
                <option value="">—</option>
                {wines.map((w) => (
                  <option key={w.wine_id} value={w.wine_id}>
                    {w.producer} — {w.cuvee}{w.release_code ? ` (${w.release_code})` : ""}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ alignSelf: "flex-end" }}>
              <button type="button" className="small"
                      onClick={() => setCreatingWine(!creatingWine)}>
                {creatingWine ? "Cancel" : "Not in the list"}
              </button>
            </div>
          </div>

          {creatingWine && (
            <div className="card" style={{ marginTop: 8 }}>
              <div className="row">
                <div className="grow">
                  <label htmlFor="nw_producer">Producer</label>
                  <input id="nw_producer" required value={newWine.producer}
                         onChange={(e) => setNewWine({ ...newWine, producer: e.target.value })} />
                </div>
                <div className="grow">
                  <label htmlFor="nw_cuvee">Cuvée</label>
                  <input id="nw_cuvee" required value={newWine.cuvee}
                         onChange={(e) => setNewWine({ ...newWine, cuvee: e.target.value })} />
                </div>
                <div>
                  <label htmlFor="nw_region">Region</label>
                  <input id="nw_region" value={newWine.region}
                         onChange={(e) => setNewWine({ ...newWine, region: e.target.value })} />
                </div>
                <div>
                  <label htmlFor="nw_colour">Colour</label>
                  <input id="nw_colour" value={newWine.colour}
                         onChange={(e) => setNewWine({ ...newWine, colour: e.target.value })} />
                </div>
                <div style={{ alignSelf: "flex-end" }}>
                  <button type="button" className="small" disabled={busy} onClick={createWine}>
                    Add wine
                  </button>
                </div>
              </div>
            </div>
          )}

          <div className="row" style={{ marginTop: 10 }}>
            <div style={{ width: 100 }}>
              <label htmlFor="vintage">Vintage</label>
              <input id="vintage" inputMode="numeric" required value={form.vintage}
                     onChange={(e) => setForm({ ...form, vintage: e.target.value })} />
            </div>
            <div style={{ width: 100 }}>
              <label htmlFor="ml">Bottle ml</label>
              <input id="ml" inputMode="numeric" value={form.bottle_ml}
                     onChange={(e) => setForm({ ...form, bottle_ml: e.target.value })} />
            </div>
            <div style={{ width: 90 }}>
              <label htmlFor="pack">Pack</label>
              <input id="pack" inputMode="numeric" value={form.pack_size}
                     onChange={(e) => setForm({ ...form, pack_size: e.target.value })} />
            </div>
            <div style={{ width: 90 }}>
              <label htmlFor="qty">Quantity</label>
              <input id="qty" inputMode="numeric" value={form.quantity}
                     onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
            </div>
            <div className="grow">
              <label htmlFor="asking">Asking price</label>
              <input id="asking" inputMode="decimal" required value={form.asking_price}
                     onChange={(e) => setForm({ ...form, asking_price: e.target.value })} />
            </div>
            <div style={{ width: 90 }}>
              <label htmlFor="asking_ccy">Currency</label>
              <input id="asking_ccy" required value={form.asking_currency}
                     onChange={(e) => setForm({ ...form, asking_currency: e.target.value.toUpperCase() })} />
            </div>
          </div>

          <h2>Comparable prices found</h2>
          <p className="muted" style={{ fontSize: 13 }}>
            Name the source for each — Wine-Searcher aggregates many retailers; type whichever
            one you actually saw the price on.
          </p>
          {comps.map((c, i) => (
            <div key={i} className="row" style={{ marginTop: 8, alignItems: "flex-end" }}>
              <div className="grow">
                <label htmlFor={`comp_merchant_${i}`}>Merchant</label>
                <input id={`comp_merchant_${i}`} required value={c.merchant}
                       onChange={(e) => updateComp(i, { merchant: e.target.value })} />
              </div>
              <div style={{ width: 120 }}>
                <label htmlFor={`comp_price_${i}`}>Price</label>
                <input id={`comp_price_${i}`} inputMode="decimal" required value={c.price}
                       onChange={(e) => updateComp(i, { price: e.target.value })} />
              </div>
              <div style={{ width: 90 }}>
                <label htmlFor={`comp_currency_${i}`}>Currency</label>
                <input id={`comp_currency_${i}`} required value={c.currency}
                       onChange={(e) => updateComp(i, { currency: e.target.value.toUpperCase() })} />
              </div>
              <div style={{ width: 90 }}>
                <label htmlFor={`comp_ml_${i}`}>Bottle ml</label>
                <input id={`comp_ml_${i}`} inputMode="numeric" value={c.bottle_ml}
                       onChange={(e) => updateComp(i, { bottle_ml: e.target.value })} />
              </div>
              <div style={{ width: 80 }}>
                <label htmlFor={`comp_pack_${i}`}>Pack</label>
                <input id={`comp_pack_${i}`} inputMode="numeric" value={c.pack_size}
                       onChange={(e) => updateComp(i, { pack_size: e.target.value })} />
              </div>
              <div style={{ width: 110 }}>
                <label htmlFor={`comp_duty_${i}`}>Duty</label>
                <select id={`comp_duty_${i}`} value={c.duty_status}
                        onChange={(e) => updateComp(i, { duty_status: e.target.value })}>
                  <option value="IB">In Bond</option>
                  <option value="DP">Duty paid</option>
                  <option value="UNKNOWN">Unknown</option>
                </select>
              </div>
              <div style={{ width: 130 }}>
                <label htmlFor={`comp_kind_${i}`}>Kind</label>
                <select id={`comp_kind_${i}`} value={c.price_kind}
                        onChange={(e) => updateComp(i, { price_kind: e.target.value })}>
                  <option value="ASK">Ask</option>
                  <option value="BID">Bid</option>
                  <option value="LAST_TRADE">Last trade</option>
                  <option value="INDICATION">Indication</option>
                </select>
              </div>
              <div className="grow">
                <label htmlFor={`comp_url_${i}`}>Source URL</label>
                <input id={`comp_url_${i}`} value={c.source_url}
                       onChange={(e) => updateComp(i, { source_url: e.target.value })} />
              </div>
              <div>
                <button type="button" className="small" disabled={comps.length === 1}
                        onClick={() => removeComp(i)}>
                  Remove
                </button>
              </div>
            </div>
          ))}
          <button type="button" className="small" style={{ marginTop: 8 }} onClick={addComp}>
            Add another comp
          </button>

          <div style={{ marginTop: 16 }}>
            <button type="submit" disabled={busy || !form.wine_id || blocksAction(wantListCheck)}>
              {busy ? "Pricing…" : "Evaluate"}
            </button>
          </div>
        </form>
      )}
    </>
  );
}


/** The same Floor/Reference/Median an adapter-sourced line would show
 * (line.jsx's own "Market evidence" section) — reused, not reinvented,
 * plus the one thing this screen adds: the asking price against it. */
function EvaluationResult({ line, askingPrice, onAnother }) {
  const run = line.benchmark;
  // "comparable" is internal bookkeeping (every passing offer, before the
  // per-merchant-best dedup) -- redundant with merchant_best whenever a
  // merchant has one offer, and never shown on screen, same exclusion
  // line.jsx's own comp table already makes.
  const byRole = (role) => (run?.comps || []).filter((c) => c.role === role);
  const comps = [...byRole("merchant_best"), ...byRole("cross_unit"), ...byRole("bid"),
                ...byRole("last_trade"), ...byRole("indication"), ...byRole("rejected")];
  const gap = run ? gapPercent(run.uk_floor, askingPrice) : null;

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{line.raw_description}</h2>

      {line.want_list && (
        <p className="notice" style={{ fontSize: 13 }}>
          On the client want list — this producer is easily confused with a cheaper namesake
          (decision 0038). Double-check the identity before acting on this.
        </p>
      )}

      {!run ? (
        <p className="notice bad">No market found — nobody approved offers this wine. NO_MARKET.</p>
      ) : (
        <>
          <p>
            Asking {money(askingPrice)} vs Floor {money(run.uk_floor)} · Reference{" "}
            {money(run.uk_reference)} · Median {money(run.uk_median)} · {run.comp_count} merchant(s)
          </p>
          {gap !== null && (
            <p className={gap <= 0 ? "notice" : "notice bad"} style={{ fontSize: 14 }}>
              {gap <= 0
                ? `Asking price is ${Math.abs(gap)}% below the cheapest ask found — worth pursuing.`
                : `Asking price is ${gap}% above the cheapest ask found — not a bargain at this price.`}
            </p>
          )}
          <Flags flags={run.flags} tone="review" />
          <div className="scroll" style={{ marginTop: 8 }}>
            <table>
              <thead>
                <tr><th>Merchant</th><th className="num">Price</th><th>Format</th><th>Used</th></tr>
              </thead>
              <tbody>
                {comps.map((c, i) => (
                  <tr key={`${c.role}-${c.offer_pk || i}`}>
                    <td>{c.merchant}</td>
                    <td className="num">{money(c.price, c.currency)}</td>
                    <td className="muted">{c.pack_size}×{c.bottle_ml / 100}cl {c.vintage}</td>
                    <td>
                      {c.role === "merchant_best" ? <span className="tag ready">priced</span>
                        : c.role === "rejected" ? <span className="tag plain">{c.reject_reason}</span>
                        : <span className="tag">{c.role.replaceAll("_", " ")}, not priced</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div style={{ marginTop: 16 }}>
        <button type="button" onClick={onAnother}>Evaluate another</button>
      </div>
    </div>
  );
}
