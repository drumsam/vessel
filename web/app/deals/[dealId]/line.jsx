"use client";

import { useCallback, useEffect, useState } from "react";
import { api, format, money, rate } from "../../../lib/api";
import { Flags } from "../../state";

/** One line, opened: its evidence, its identity, and its price. */
export default function LineDetail({ lineId, line, onChange }) {
  const [run, setRun] = useState(null);
  const [wines, setWines] = useState([]);
  const [identity, setIdentity] = useState({
    wine_id: line?.wine_id || "", vintage: line?.vintage || "",
    bottle_ml: line?.bottle_ml || 750, pack_size: line?.pack_size || 1,
    source: "operator", flags: line?.flags || [],
  });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get(`/lines/${lineId}/benchmark`).then(setRun).catch(() => setRun(null));
    api.get("/wines").then(setWines).catch(() => {});
  }, [lineId]);
  useEffect(load, [load]);

  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.put(`/lines/${lineId}/identity`, {
        ...identity,
        vintage: Number(identity.vintage),
        bottle_ml: Number(identity.bottle_ml),
        pack_size: Number(identity.pack_size),
      });
      onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function acknowledge() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/lines/${lineId}/pricing/acknowledge`, { note: null });
      onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const pricing = line?.pricing;
  const comps = run?.comps || [];
  const byRole = (role) => comps.filter((c) => c.role === role);

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{line?.raw_description}</h2>
      {error && <div className="notice bad">{error}</div>}

      <form onSubmit={save}>
        <div className="row">
          <div className="grow">
            <label htmlFor="wine">Approved wine</label>
            <select id="wine" value={identity.wine_id} required
                    onChange={(e) => setIdentity({ ...identity, wine_id: e.target.value })}>
              <option value="">—</option>
              {wines.map((w) => (
                <option key={w.wine_id} value={w.wine_id}>{w.producer} — {w.cuvee}</option>
              ))}
            </select>
          </div>
          <div style={{ width: 100 }}>
            <label htmlFor="vintage">Vintage</label>
            <input id="vintage" inputMode="numeric" value={identity.vintage} required
                   onChange={(e) => setIdentity({ ...identity, vintage: e.target.value })} />
          </div>
          <div style={{ width: 100 }}>
            <label htmlFor="ml">Bottle ml</label>
            <input id="ml" inputMode="numeric" value={identity.bottle_ml}
                   onChange={(e) => setIdentity({ ...identity, bottle_ml: e.target.value })} />
          </div>
          <div style={{ width: 90 }}>
            <label htmlFor="pack">Pack</label>
            <input id="pack" inputMode="numeric" value={identity.pack_size}
                   onChange={(e) => setIdentity({ ...identity, pack_size: e.target.value })} />
          </div>
          <div style={{ width: 150 }}>
            <label htmlFor="source">Approved as</label>
            <select id="source" value={identity.source}
                    onChange={(e) => setIdentity({ ...identity, source: e.target.value })}>
              <option value="operator">operator</option>
              <option value="ai_reviewed">reviewed AI proposal</option>
            </select>
          </div>
          <button type="submit" disabled={busy}>Save identity</button>
        </div>
        <p className="muted" style={{ fontSize: 13 }}>
          Saved as {line?.wine_id_approved_by?.display_name || "nobody yet"}
          {line?.wine_id_approved_at ? ` on ${new Date(line.wine_id_approved_at).toLocaleString("en-GB")}` : ""}.
          Your name is taken from your session.
        </p>
      </form>

      {pricing && (
        <>
          <h2>Price</h2>
          <p>
            {money(pricing.sell_price, pricing.sell_currency)} on {pricing.price_basis.replaceAll("_", " ")}
            {" · "}GP {money(pricing.gp)} ({rate(pricing.gross_margin)})
            {pricing.fx_rate && ` · FX ${pricing.fx_rate} ${pricing.cost_currency}/GBP on ${pricing.fx_rate_date} (${pricing.fx_source})`}
          </p>
          <Flags flags={pricing.flags} tone="review" />
          {pricing.requires_acknowledgement && (
            pricing.acknowledgement ? (
              <p className="muted">
                Accepted by {pricing.acknowledgement.acknowledged_by.display_name} on{" "}
                {new Date(pricing.acknowledgement.acknowledged_at).toLocaleString("en-GB")}
                {pricing.acknowledgement.note ? ` — ${pricing.acknowledgement.note}` : ""}.
              </p>
            ) : (
              <div className="notice bad" style={{ marginTop: 10 }}>
                This price is {pricing.flags.filter((f) => ["NEGATIVE_GP", "SELL_ABOVE_UK_REFERENCE"].includes(f))
                  .map((f) => f.replaceAll("_", " ").toLowerCase()).join(" and ")}.
                It cannot be sent to a buyer until you accept it.
                <div style={{ marginTop: 8 }}>
                  <button className="small" onClick={acknowledge} disabled={busy}>Accept this price</button>
                </div>
              </div>
            )
          )}
        </>
      )}

      <h2>Market evidence</h2>
      {!run ? <p className="muted">Not benchmarked yet.</p> : (
        <>
          <p>
            Floor {money(run.uk_floor)} · Reference {money(run.uk_reference)} ·
            Median {money(run.uk_median)} · {run.comp_count} merchant(s)
            {run.oldest_comp_age ? ` · oldest comp ${run.oldest_comp_age.replace("P", "").toLowerCase()} old` : ""}
          </p>
          <Flags flags={run.flags} tone="review" />
          <p className="muted" style={{ fontSize: 13 }}>
            Searched: {run.sources.map((s) => s.merchant_id).join(", ") || "nobody"} ·
            as of {new Date(run.as_of).toLocaleString("en-GB")}
          </p>
          <div className="scroll">
            <table>
              <thead>
                <tr><th>Merchant</th><th className="num">Price</th><th>Format</th><th>Condition</th><th>Used</th></tr>
              </thead>
              <tbody>
                {[...byRole("merchant_best"), ...byRole("cross_unit"), ...byRole("rejected")].map((c, i) => (
                  <tr key={`${c.role}-${c.offer_pk || i}`}>
                    <td>{c.merchant}</td>
                    <td className="num">
                      {money(c.price, c.currency)}
                      {c.per_bottle && <div className="muted">{money(Number(c.per_bottle).toFixed(2))}/btl</div>}
                    </td>
                    <td className="muted">{c.pack_size}×{c.bottle_ml / 100}cl {c.vintage}</td>
                    <td className="muted verbatim">{format(c.condition_notes)}</td>
                    <td>
                      {c.role === "merchant_best" ? <span className="tag ready">priced</span>
                        : c.role === "cross_unit" ? <span className="tag">shown, not priced</span>
                        : <span className="tag plain">{c.reject_reason}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
