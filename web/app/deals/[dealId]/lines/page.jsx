"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { use } from "react";
import { api, format, money, rate } from "../../../../lib/api";
import { Flags, StateTag } from "../../../state";
import LineDetail from "./line";

/** Poll a queued job until it stops running, then hand back its result. */
async function waitFor(jobId) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const job = await api.get(`/jobs/${jobId}`);
    if (job.status === "finished") return job;
    if (["failed", "stopped", "canceled"].includes(job.status)) {
      throw new Error(job.error?.split("\n").filter(Boolean).pop() || `job ${job.status}`);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error("the job is still running; check back shortly");
}

export default function DealPage({ params }) {
  const { dealId } = use(params);
  const [deal, setDeal] = useState(null);
  const [offers, setOffers] = useState([]);
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);
  const [workerUp, setWorkerUp] = useState(true); // optimistic until /health says otherwise

  const load = useCallback(() => {
    api.get(`/deals/${dealId}`).then(setDeal).catch((e) => setError(e.message));
    api.get(`/deals/${dealId}/buyer-offers`).then(setOffers).catch(() => {});
    // Collect/Benchmark/Price all queue an RQ job; without a worker running
    // (scripts/desk.sh deliberately starts none — Cellar Desk only reads
    // prices that already exist) they would queue a job nothing ever picks
    // up. A button that cannot succeed should not be pressable.
    api.get("/health").then((h) => setWorkerUp(h.redis === "ok")).catch(() => setWorkerUp(false));
  }, [dealId]);
  useEffect(load, [load]);

  async function run(label, start) {
    setBusy(label);
    setError(null);
    setNote(null);
    try {
      const { job_id } = await start();
      const job = await waitFor(job_id);
      setNote(describe(label, job.result));
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  function describe(label, result) {
    if (!result) return `${label} finished`;
    if (label === "Benchmark") {
      const skipped = [...(result.unapproved_identity || []), ...(result.no_coverage || [])];
      return `Benchmarked ${Object.keys(result.runs || {}).length} line(s)` +
        (skipped.length ? `; ${skipped.length} skipped (identity or no capture covering them)` : "");
    }
    if (label === "Price") {
      const skipped = result.skipped || [];
      return `Priced ${Object.keys(result.priced || {}).length} line(s)` +
        (skipped.length ? `; skipped ${skipped.map((s) => s.reason).join(", ")}` : "");
    }
    return `${label} finished`;
  }

  if (!deal) return <p className="muted">{error || "Loading…"}</p>;

  return (
    <>
      <p className="muted" style={{ marginBottom: 4 }}><Link href={`/deals/${dealId}`}>← Cellar Desk</Link></p>
      <h1>{deal.name}</h1>
      <p className="sub">
        {format(deal.seller)} · loaded by {deal.created_by?.display_name} ·{" "}
        {deal.lines.length} lines{deal.target_margin ? ` · deal margin ${rate(deal.target_margin)}` : ""}
      </p>

      {error && <div className="notice bad">{error}</div>}
      {note && <div className="notice good">{note}</div>}
      {!workerUp && (
        <div className="notice bad">
          No worker is reachable, so Collect/Benchmark/Price would queue a job
          nothing picks up — disabled until one is.
        </div>
      )}

      <div className="card row">
        <button disabled={!!busy || !workerUp}
                onClick={() => run("Collect", () => api.post("/snapshots", {}))}>
          {busy === "Collect" ? "Collecting…" : "Collect merchant offers"}
        </button>
        <button disabled={!!busy || !workerUp} className="quiet"
                onClick={() => run("Benchmark", () => api.post(`/deals/${dealId}/benchmark`, {}))}>
          {busy === "Benchmark" ? "Benchmarking…" : "Benchmark"}
        </button>
        <button disabled={!!busy || !workerUp} className="quiet"
                onClick={() => run("Price", () => api.post(`/deals/${dealId}/pricing`, {}))}>
          {busy === "Price" ? "Pricing…" : "Price"}
        </button>
      </div>

      <div className="card scroll">
        <table>
          <thead>
            <tr>
              <th>#</th><th>Seller wording</th><th>State</th>
              <th className="num">Qty</th><th className="num">Cost</th>
              <th className="num">UK Reference</th><th className="num">Sell</th>
              <th className="num">GM</th><th></th>
            </tr>
          </thead>
          <tbody>
            {deal.lines.map((line) => (
              <tr key={line.line_id}>
                <td className="muted">{line.row_index + 1}</td>
                <td>
                  <div className="verbatim">{line.raw_description}</div>
                  <Flags flags={line.flags} tone="review" />
                  {line.pricing?.requires_acknowledgement && !line.pricing.acknowledgement && (
                    <span className="tag stop">needs sign-off</span>
                  )}
                </td>
                <td><StateTag state={line.line_state} /></td>
                <td className="num">{line.quantity}</td>
                <td className="num">{money(line.cost, line.cost_currency || "GBP")}</td>
                <td className="num">{money(line.benchmark?.uk_reference)}</td>
                <td className="num">{money(line.pricing?.sell_price)}</td>
                <td className="num">{rate(line.pricing?.gross_margin)}</td>
                <td className="num">
                  <button className="small quiet"
                          onClick={() => setOpen(open === line.line_id ? null : line.line_id)}>
                    {open === line.line_id ? "Close" : "Open"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && <LineDetail lineId={open} onChange={load}
                           line={deal.lines.find((l) => l.line_id === open)} />}

      <h2>Buyer offers</h2>
      <p className="muted">
        There is exactly one route from here to a buyer, and it isn&apos;t this page — it&apos;s{" "}
        <Link href={`/deals/${dealId}`}>the Cellar Desk</Link>, which chooses the lines, gates on
        acceptance, and generates the client document and the shareable link. This page cannot
        send wine to anyone.
      </p>
      {offers.length > 0 && (
        <div className="card scroll">
          <table>
            <thead>
              <tr><th>Client</th><th>Issued</th><th>By</th><th className="num">Lines</th><th className="num">Total</th></tr>
            </thead>
            <tbody>
              {offers.map((offer) => (
                <tr key={offer.buyer_offer_id}>
                  <td><Link href={`/offers/${offer.buyer_offer_id}`}>{offer.client}</Link></td>
                  <td className="muted">{new Date(offer.issued_at).toLocaleString("en-GB")}</td>
                  <td className="muted">{offer.issued_by?.display_name}</td>
                  <td className="num">{offer.lines.length}</td>
                  <td className="num">{money(offer.total, offer.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
