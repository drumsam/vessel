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

  async function reinstate(exclusion) {
    const reason = window.prompt(
      `Put ${exclusion.merchant}'s ${money(exclusion.price)} back into the benchmark?\n` +
      "Say why — it is kept with your name.");
    if (!reason) return;
    setBusy(true);
    setError(null);
    try {
      setRun(await api.post(`/comp-exclusions/${exclusion.exclusion_id}/reinstate`, { reason }));
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
  const variance = (value) =>
    value === null || value === undefined
      ? "—"
      : `${Number(value) > 0 ? "+" : ""}${(Number(value) * 100).toFixed(1)}%`;

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
                <option key={w.wine_id} value={w.wine_id}>
                  {w.producer} — {w.cuvee}{w.release_code ? ` (${w.release_code})` : ""}
                </option>
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
          {pricing.price_basis === "buyer_discount" ? (
            <>
              <p>
                Buyer pays {money(pricing.buyer_price_gbp, pricing.sell_currency)} · Seller
                receives {money(pricing.seller_price_gbp, pricing.sell_currency)} · our fee{" "}
                {money(pricing.gp)} ({rate(pricing.margin_on_sale)} of the buyer price)
              </p>
              <p className="muted" style={{ fontSize: 13 }}>
                Priced from the market chain: UK Reference {money(pricing.uk_reference)} ·
                buyer discount {rate(pricing.buyer_discount)} · our fee on the buyer price{" "}
                {rate(pricing.margin_on_sale)}. One is a sale, the other a purchase.
              </p>
            </>
          ) : (
            <p>
              {money(pricing.sell_price, pricing.sell_currency)} on {pricing.price_basis.replaceAll("_", " ")}
              {" · "}GP {money(pricing.gp)} ({rate(pricing.gross_margin)})
              {pricing.fx_rate && ` · FX ${pricing.fx_rate} ${pricing.cost_currency}/GBP on ${pricing.fx_rate_date} (${pricing.fx_source})`}
            </p>
          )}
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
          {(run.same_price_notes || []).map((n) => (
            <p key={n.price} className="notice" style={{ fontSize: 13 }}>
              {n.merchants.join(" and ")} both ask {money(n.price)}
              {n.any_brokered ? ", and one of them is broking" : ""} — this may be one
              parcel listed twice. Both are counted; it is worth a look.
            </p>
          ))}
          <VintageBand band={run.vintage_band} onReinstate={reinstate} busy={busy} />
          <div className="scroll">
            <table>
              <thead>
                <tr><th>Merchant</th><th className="num">Price</th><th>Format</th><th>Condition</th><th>Used</th></tr>
              </thead>
              <tbody>
                {[...byRole("merchant_best"), ...byRole("cross_unit"),
                  ...byRole("indication"), ...byRole("rejected")].map((c, i) => (
                  <tr key={`${c.role}-${c.offer_pk || i}`}>
                    <td>{c.merchant}</td>
                    <td className="num">
                      {money(c.price, c.currency)}
                      {c.per_bottle && <div className="muted">{money(Number(c.per_bottle).toFixed(2))}/btl</div>}
                      {c.derived_from && <div className="muted">derived</div>}
                    </td>
                    <td className="muted">
                      {c.pack_size}×{c.bottle_ml / 100}cl {c.vintage}
                      {c.derived_from && (
                        <div className="muted">
                          really {c.derived_from.pack_size}×{c.derived_from.bottle_ml / 100}cl
                          {" "}at {money(c.derived_from.price)}
                        </div>
                      )}
                    </td>
                    <td className="muted verbatim">{format(c.condition_notes)}</td>
                    <td>
                      {c.role === "merchant_best" && c.derived_from ? (
                        <>
                          <span className="tag review">priced, derived</span>
                          <div className="muted">{c.derived_from.note}</div>
                        </>
                      ) : c.role === "merchant_best" ? <span className="tag ready">priced</span>
                        : c.role === "cross_unit" ? <span className="tag">shown, not priced</span>
                        : c.role === "indication" ? (
                          <>
                            <span className="tag">indication, not priced</span>
                            <div className="muted">
                              {variance(c.variance_vs_reference)} vs Reference
                              {c.merchant_count
                                ? `, ${c.merchant} reports ${c.merchant_count} sellers`
                                : ""}
                            </div>
                          </>
                        ) : <span className="tag plain">{c.reject_reason}</span>}
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


/** The vintage-neighbour sanity check. Evidence about the comps, never a price:
 *  nothing here is a number we would ever quote a client. */
function VintageBand({ band, onReinstate, busy }) {
  if (!band) return null;
  const excluded = band.excluded || [];
  const open = excluded.filter((x) => !x.reinstated_at);
  const put_back = excluded.filter((x) => x.reinstated_at);

  return (
    <div style={{ marginTop: 12 }}>
      <h3 style={{ marginBottom: 6 }}>Neighbouring vintages</h3>
      {band.band_low ? (
        <p className="muted" style={{ fontSize: 13 }}>
          {band.unit.replace("x", "×")}: this wine&apos;s{" "}
          {band.neighbours.map((n) => `${n.vintage}${n.tier ? ` (tier ${n.tier})` : ""}`).join(", ")}{" "}
          sit between {money(band.band_low)} and {money(band.band_high)}
          {band.neighbours.some((n) => n.stale) ? " (some of it older than the comp window)" : ""}.
          {band.note ? ` ${band.note}.` : ""}
          {" "}Vintages are matched by quality, not by how near they are.
        </p>
      ) : (
        <p className="muted" style={{ fontSize: 13 }}>{band.note || "No band."}</p>
      )}

      {open.map((x) => (
        <div key={x.exclusion_id} className="notice bad" style={{ fontSize: 13 }}>
          {x.merchant} at {money(x.price)} was left out: {Number(x.band_multiple).toFixed(2)}×
          the {money(x.band_edge)} edge of its own neighbouring vintages.
          <div style={{ marginTop: 8 }}>
            <button className="small" disabled={busy} onClick={() => onReinstate(x)}>
              Put it back
            </button>
          </div>
        </div>
      ))}

      {(band.low_outliers || []).map((o) => (
        <div key={o.offer_id || o.merchant} className="notice" style={{ fontSize: 13 }}>
          {o.merchant} at {money(o.price)} is well below the band, and has been kept.
          A cheap comp is often the true price — dropping it would push the Reference up.
          Decide it yourself.
        </div>
      ))}

      {(band.format_incoherent || []).map((d, i) => (
        <p key={i} className="muted" style={{ fontSize: 13 }}>
          {d.merchant} disagrees with itself: {money(d.other_per_bottle)}/btl in{" "}
          {d.other_unit.replace("x", "×")} against {money(d.comp_per_bottle)}/btl in{" "}
          {d.comp_unit.replace("x", "×")}. Shown as evidence; neither is priced from.
        </p>
      ))}

      {put_back.map((x) => (
        <p key={x.exclusion_id} className="muted" style={{ fontSize: 13 }}>
          {x.merchant} at {money(x.price)} was put back by{" "}
          {x.reinstated_by?.display_name || "an operator"} on{" "}
          {new Date(x.reinstated_at).toLocaleDateString("en-GB")} — {x.reinstated_reason}
        </p>
      ))}
    </div>
  );
}
