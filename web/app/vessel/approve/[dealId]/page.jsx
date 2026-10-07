"use client";

// VESSEL screen 1 — seller approval. No login: reachable by the link, the
// same simplification the specs leave open rather than built here.
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, money } from "../../../../lib/api";

const REASON_LABEL = {
  NO_MARKET: "no UK market", THIN_EVIDENCE: "thin evidence",
  BELOW_MINIMUM_VALUE: "below our minimum line value",
  IDENTITY_PENDING: "identity still being confirmed", BETTER_HELD: "held for a later drop",
};

export default function SellerApproval() {
  const { dealId } = useParams();
  const [data, setData] = useState(null);
  const [moved, setMoved] = useState({});          // listing_id -> true (MOVE) | false (KEEP)
  const [name, setName] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get(`/vessel/deals/${dealId}/recommended`).then((d) => {
      setData(d);
      setMoved(Object.fromEntries(d.listings.map((l) => [l.listing_id, true])));
    }).catch((e) => setError(e.message));
  }, [dealId]);

  if (error) return <div className="notice bad">{error}</div>;
  if (!data) return <p className="muted">Loading…</p>;
  if (result) return <Approved result={result} />;

  const listings = data.listings;
  const byCurrency = {};
  for (const l of listings) {
    if (moved[l.listing_id]) byCurrency[l.currency] = (byCurrency[l.currency] || 0) + Number(l.seller_net);
  }

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      const move_line_ids = listings.filter((l) => moved[l.listing_id]).map((l) => l.line_id);
      const keep_line_ids = listings.filter((l) => !moved[l.listing_id]).map((l) => l.line_id);
      const mandate = await api.post(`/vessel/deals/${dealId}/approve`,
        { move_line_ids, keep_line_ids, approved_by_name: name });
      setResult(mandate);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: "4vh auto" }}>
      <h1>{listings.length} wines we think we can move</h1>
      <p>
        Estimated net to you{" "}
        {Object.entries(byCurrency).map(([c, v]) =>
          <strong key={c} style={{ marginRight: 10 }}>{money(v.toFixed(2), c)}</strong>)}
      </p>
      {error && <div className="notice bad">{error}</div>}

      {listings.map((l) => (
        <div className="card" key={l.listing_id} style={{ marginBottom: 10 }}>
          <div className="row">
            <div className="grow">
              <strong>{l.display_producer} {l.display_wine}{l.release_code ? ` (${l.release_code})` : ""} {l.vintage}</strong>
              <div className="muted">{l.bottles} bottles</div>
              <div style={{ marginTop: 6 }}>
                {l.reference_label} {money(l.market_reference, l.currency)}
                {" · "}{l.source_count} {l.source_count === 1 ? "source" : "sources"}
              </div>
              <div>You receive <strong>{money(l.seller_net, l.currency)}</strong></div>
            </div>
            <button type="button"
                    className={moved[l.listing_id] ? "" : "small"}
                    onClick={() => setMoved({ ...moved, [l.listing_id]: !moved[l.listing_id] })}>
              {moved[l.listing_id] ? "✓ Move" : "Keep"}
            </button>
          </div>
        </div>
      ))}

      <div className="card">
        <label htmlFor="name">Your name, to approve</label>
        <input id="name" value={name} onChange={(e) => setName(e.target.value)} required
               style={{ marginBottom: 10 }} />
        <p className="muted" style={{ fontSize: 13 }}>
          VESSEL may market the wines ticked &ldquo;Move&rdquo; for 30 days at a price of no less
          than the amount shown against each line. The buyer pays you directly, in full, on
          collection; VESSEL invoices you an 8% commission on each wine once it sells, rather than
          holding any part of the sale ourselves. We handle release timing, presentation and price
          positioning within that. We&rsquo;ll tell you what sold, when, and what didn&rsquo;t. You
          warrant that the wine is yours to sell, free of any charge or encumbrance, and agree to
          its remaining in bonded storage while it is listed.
        </p>
        <button type="button" disabled={busy || !name.trim()} onClick={approve}>
          Approve {listings.filter((l) => moved[l.listing_id]).length} wines
        </button>
      </div>

      {Object.keys(data.excluded_counts || {}).length > 0 && (
        <p className="muted" style={{ fontSize: 13 }}>
          Why not the rest:{" "}
          {Object.entries(data.excluded_counts)
            .map(([reason, n]) => `${n} ${REASON_LABEL[reason] || reason.toLowerCase()}`)
            .join(" · ")}
        </p>
      )}
    </div>
  );
}

function Approved({ result }) {
  return (
    <div style={{ maxWidth: 560, margin: "10vh auto" }} className="card">
      <h2>Approved</h2>
      <p>Thank you, {result.approved_by_name}. We&rsquo;ll take it from here.</p>
      {(result.estimate || []).map((row) => (
        <p key={row.currency}>
          {row.lines} line(s), estimated net {money(row.net_total, row.currency)}
        </p>
      ))}
    </div>
  );
}
