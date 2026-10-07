"use client";

import { useCallback, useEffect, useState } from "react";
import { api, format, money, rate } from "../../../lib/api";
import { Flags } from "../../state";

/** One line, opened: its evidence, its identity, and its price. */
export default function LineDetail({ lineId, line, onChange }) {
  const [run, setRun] = useState(null);
  const [wines, setWines] = useState([]);
  const [auctionHealth, setAuctionHealth] = useState(null);
  const [auctionLots, setAuctionLots] = useState([]);
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
    api.get(`/lines/${lineId}/auction-health`).then(setAuctionHealth).catch(() => setAuctionHealth(null));
    api.get(`/lines/${lineId}/auction-evidence`).then(setAuctionLots).catch(() => setAuctionLots([]));
  }, [lineId]);
  useEffect(load, [load]);

  async function addAuctionEvidence(body) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/lines/${lineId}/auction-evidence`, body);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function retractAuctionEvidence(auctionEvidenceId) {
    const reason = window.prompt("Why is this lot being retracted? Kept, not deleted.");
    if (!reason) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/auction-evidence/${auctionEvidenceId}/retract`, { reason });
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

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

      <AuctionEvidence health={auctionHealth} lots={auctionLots} busy={busy}
                       onAdd={addAuctionEvidence} onRetract={retractAuctionEvidence} />
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


const AUCTION_HOUSES = ["BONHAMS", "CHRISTIES", "HERITAGE", "ZACHYS"];

const AUCTION_FORM_DEFAULT = {
  auction_house: "BONHAMS", sale_date: "", lot_ref: "", source_url: "",
  bottles_in_lot: "", currency: "GBP", amount: "", amount_basis: "HAMMER",
  premium_rate: "", fx_rate: "", fx_source: "", is_mixed_lot: false,
  condition_notes: "", condition_flagged: false,
};

/** A health check, never a price (decision 0023): hand-entered from a
 *  public results page, with a mandatory source URL. Never a scraper. */
function AuctionEvidence({ health, lots, busy, onAdd, onRetract }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(AUCTION_FORM_DEFAULT);
  const [formError, setFormError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    if (!form.source_url.trim()) {
      setFormError("Source URL is required — evidence without a source cannot be checked.");
      return;
    }
    if (form.amount_basis === "BUYER_PREMIUM_INCLUSIVE" && !form.premium_rate) {
      setFormError("Premium rate is required when the price includes buyer's premium.");
      return;
    }
    setFormError(null);
    await onAdd({
      auction_house: form.auction_house, sale_date: form.sale_date, lot_ref: form.lot_ref,
      source_url: form.source_url, bottles_in_lot: Number(form.bottles_in_lot),
      currency: form.currency, amount: form.amount, amount_basis: form.amount_basis,
      premium_rate: form.amount_basis === "BUYER_PREMIUM_INCLUSIVE"
        ? String(Number(form.premium_rate) / 100) : null,
      fx_rate: form.currency === "GBP" ? null : (form.fx_rate || null),
      fx_source: form.currency === "GBP" ? null : (form.fx_source || null),
      is_mixed_lot: form.is_mixed_lot, condition_notes: form.condition_notes || null,
      condition_flagged: form.condition_flagged,
    });
    setForm(AUCTION_FORM_DEFAULT);
    setOpen(false);
  }

  const longPaste = form.condition_notes.length > 280;

  return (
    <div style={{ marginTop: 12 }}>
      <h2>Auction evidence</h2>
      <p className="muted" style={{ fontSize: 13 }}>
        A health check, not a price — it never sets, moves or substitutes for the Floor,
        Reference or Median, and never appears on a client document.
      </p>

      {health && (
        health.lot_count === 0 ? (
          <p className="muted">{health.note || "No auction evidence entered for this wine yet."}</p>
        ) : (
          <>
            <p>
              {health.lot_count} lot(s) · median {money(health.median_per_bottle_gbp)}/btl hammer
              {health.earliest_sale_date && health.latest_sale_date && (
                health.earliest_sale_date === health.latest_sale_date
                  ? ` · ${health.earliest_sale_date}`
                  : ` · ${health.earliest_sale_date} to ${health.latest_sale_date}`
              )}
            </p>
            {health.note && <p className="muted">{health.note}</p>}
            {health.flag && (
              <p className="notice" style={{ fontSize: 13 }}>
                Median auction hammer sits more than 10% below the UK Reference — advice,
                never a gate and never a price.
              </p>
            )}
          </>
        )
      )}

      {lots.length > 0 && (
        <div className="scroll" style={{ marginTop: 8 }}>
          <table>
            <thead>
              <tr>
                <th>House</th><th>Sale date</th><th>Lot</th><th className="num">Bottles</th>
                <th className="num">Hammer GBP</th><th>Source</th><th></th>
              </tr>
            </thead>
            <tbody>
              {lots.map((l) => (
                <tr key={l.auction_evidence_id} style={{ opacity: l.retracted_at ? 0.5 : 1 }}>
                  <td>{l.auction_house}</td>
                  <td>{l.sale_date}</td>
                  <td>{l.lot_ref}{l.quarantined && <div className="muted">quarantined</div>}</td>
                  <td className="num">{l.bottles_in_lot}</td>
                  <td className="num">{l.hammer_gbp ? money(l.hammer_gbp) : "FX unavailable"}</td>
                  <td><a href={l.source_url} target="_blank" rel="noreferrer">lot page</a></td>
                  <td>
                    {l.retracted_at ? (
                      <span className="muted" style={{ fontSize: 12 }}>
                        retracted by {l.retracted_by?.display_name} — {l.retraction_reason}
                      </span>
                    ) : (
                      <button type="button" className="small" disabled={busy}
                              onClick={() => onRetract(l.auction_evidence_id)}>
                        Retract
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!open ? (
        <button type="button" className="small" style={{ marginTop: 8 }} onClick={() => setOpen(true)}>
          Add auction evidence
        </button>
      ) : (
        <form onSubmit={submit} className="card" style={{ marginTop: 8 }}>
          {formError && <div className="notice bad">{formError}</div>}
          <div className="row">
            <div>
              <label htmlFor="house">House</label>
              <select id="house" value={form.auction_house}
                      onChange={(e) => setForm({ ...form, auction_house: e.target.value })}>
                {AUCTION_HOUSES.map((h) => <option key={h} value={h}>{h}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="sale_date">Sale date</label>
              <input id="sale_date" type="date" required value={form.sale_date}
                     onChange={(e) => setForm({ ...form, sale_date: e.target.value })} />
            </div>
            <div className="grow">
              <label htmlFor="lot_ref">Lot ref</label>
              <input id="lot_ref" required value={form.lot_ref}
                     onChange={(e) => setForm({ ...form, lot_ref: e.target.value })} />
            </div>
          </div>
          <label htmlFor="source_url">Source URL</label>
          <input id="source_url" type="url" required placeholder="https://..."
                 value={form.source_url}
                 onChange={(e) => setForm({ ...form, source_url: e.target.value })} />

          <div className="row" style={{ marginTop: 10 }}>
            <div style={{ width: 110 }}>
              <label htmlFor="bottles">Lot size (btl)</label>
              <input id="bottles" inputMode="numeric" required value={form.bottles_in_lot}
                     onChange={(e) => setForm({ ...form, bottles_in_lot: e.target.value })} />
            </div>
            <div style={{ width: 110 }}>
              <label htmlFor="currency">Currency</label>
              <input id="currency" required value={form.currency}
                     onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} />
            </div>
            <div className="grow">
              <label htmlFor="amount">Amount</label>
              <input id="amount" inputMode="decimal" required value={form.amount}
                     onChange={(e) => setForm({ ...form, amount: e.target.value })} />
            </div>
            <div>
              <label htmlFor="basis">Basis</label>
              <select id="basis" value={form.amount_basis}
                      onChange={(e) => setForm({ ...form, amount_basis: e.target.value })}>
                <option value="HAMMER">Hammer</option>
                <option value="BUYER_PREMIUM_INCLUSIVE">Including premium</option>
              </select>
            </div>
            {form.amount_basis === "BUYER_PREMIUM_INCLUSIVE" && (
              <div style={{ width: 110 }}>
                <label htmlFor="premium">Premium %</label>
                <input id="premium" inputMode="decimal" required value={form.premium_rate}
                       onChange={(e) => setForm({ ...form, premium_rate: e.target.value })} />
              </div>
            )}
          </div>

          {form.currency !== "GBP" && (
            <div className="row" style={{ marginTop: 10 }}>
              <div>
                <label htmlFor="fx_rate">FX rate to GBP</label>
                <input id="fx_rate" inputMode="decimal" value={form.fx_rate}
                       onChange={(e) => setForm({ ...form, fx_rate: e.target.value })} />
              </div>
              <div className="grow">
                <label htmlFor="fx_source">FX source</label>
                <input id="fx_source" value={form.fx_source}
                       onChange={(e) => setForm({ ...form, fx_source: e.target.value })} />
              </div>
            </div>
          )}
          <p className="muted" style={{ fontSize: 12 }}>
            Leave FX blank if you don&rsquo;t have a rate for this date — the lot is still
            recorded, just not converted. Never a guess.
          </p>

          <div className="row" style={{ marginTop: 10 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <input type="checkbox" checked={form.is_mixed_lot}
                     onChange={(e) => setForm({ ...form, is_mixed_lot: e.target.checked })} />
              Mixed lot
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <input type="checkbox" checked={form.condition_flagged}
                     onChange={(e) => setForm({ ...form, condition_flagged: e.target.checked })} />
              Condition noted
            </label>
          </div>
          {form.is_mixed_lot && (
            <p className="muted" style={{ fontSize: 12 }}>
              Mixed lots are recorded but excluded from the health check.
            </p>
          )}

          <label htmlFor="condition_notes">Condition, in your own words</label>
          <textarea id="condition_notes" rows={2} value={form.condition_notes}
                    onChange={(e) => setForm({ ...form, condition_notes: e.target.value })} />
          {longPaste && (
            <p className="notice" style={{ fontSize: 12 }}>
              Record the facts in your own words. Catalogue descriptions are the auction
              house&rsquo;s copyright.
            </p>
          )}

          <div className="row" style={{ marginTop: 10 }}>
            <button type="submit" disabled={busy}>Save lot</button>
            <button type="button" className="small" disabled={busy}
                    onClick={() => { setOpen(false); setForm(AUCTION_FORM_DEFAULT); setFormError(null); }}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
