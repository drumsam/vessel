"use client";

// VESSEL screen 3 — the wine page. Wine, price, proof, buy, in that order,
// no scrolling needed on a phone. Evidence expands on tap.
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, money } from "../../../../lib/api";

export default function WinePage() {
  const { listingId } = useParams();
  const router = useRouter();
  const [listing, setListing] = useState(null);
  const [error, setError] = useState(null);
  const [showEvidence, setShowEvidence] = useState(false);
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get(`/vessel/listings/${listingId}`).then(setListing).catch((e) => setError(e.message));
  }, [listingId]);

  async function buy() {
    setBusy(true);
    setError(null);
    try {
      const reservation = await api.post(`/vessel/listings/${listingId}/buy`,
        { buyer_contact: contact });
      router.push(`/vessel/reservations/${reservation.reservation_id}`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="notice bad">{error}</div>;
  if (!listing) return <p className="muted">Loading…</p>;

  const canBuy = listing.state === "LISTED";

  return (
    <div style={{ maxWidth: 480, margin: "4vh auto" }}>
      <h1>
        {listing.display_producer} {listing.display_wine}
        {listing.release_code ? ` (${listing.release_code})` : ""}
      </h1>
      <p className="muted">
        {listing.vintage} · {listing.bottles} bottles · {listing.bottle_ml}ml ·{" "}
        {listing.stock_location.replace("_", " ")}
      </p>

      <div className="card">
        <p className="muted" style={{ marginBottom: 2 }}>{listing.reference_label}</p>
        <p style={{ margin: 0 }}>{money(listing.market_reference, listing.currency)}</p>
        <h2 style={{ margin: "10px 0 0" }}>{money(listing.vessel_price, listing.currency)}</h2>
        {listing.percentage_claim_pct && (
          <p className="muted" style={{ marginTop: 2 }}>
            {(Number(listing.percentage_claim_pct) * 100).toFixed(0)}% below current market
          </p>
        )}
      </div>

      <p>
        {listing.condition_notes || "Professionally stored"} · VESSEL verified
      </p>

      <button type="button" className="small" onClick={() => setShowEvidence(!showEvidence)}>
        {showEvidence ? "Hide evidence" : "See the evidence"}
      </button>
      {showEvidence && (
        <div className="card" style={{ marginTop: 8, fontSize: 13 }}>
          <p>{listing.source_count} independent UK merchant source(s).</p>
          {listing.provenance_notes && <p className="muted">{listing.provenance_notes}</p>}
          {listing.derived && (
            <p className="muted">
              Priced from a comparable case offer, not this exact pack size.
            </p>
          )}
        </div>
      )}

      {error && <div className="notice bad">{error}</div>}

      {canBuy ? (
        <div style={{ marginTop: 18 }}>
          <label htmlFor="contact">Email or phone, to hold this for you</label>
          <input id="contact" value={contact} onChange={(e) => setContact(e.target.value)}
                 style={{ marginBottom: 10 }} />
          <button type="button" disabled={busy || !contact.trim()} onClick={buy}>
            BUY — {money(listing.vessel_price, listing.currency)}
          </button>
        </div>
      ) : (
        <p className="notice" style={{ marginTop: 18 }}>
          {listing.state === "RESERVED" ? "Reserved — someone is paying for this now."
            : listing.state === "PAID" || listing.state === "TRANSFERRING"
              || listing.state === "SETTLED" ? "Sold."
            : "Not yet available."}
        </p>
      )}
    </div>
  );
}
