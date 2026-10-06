"use client";

// VESSEL screen 2 — the drop. SOLD listings stay on the page, greyed, for
// the life of the drop: social proof, a reason to act, and validation of
// the price, in three words.
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, money } from "../../../../lib/api";

const SOLD_STATES = new Set(["PAID", "TRANSFERRING", "SETTLED"]);

function soldIn(listing) {
  if (!listing.sold_at || !listing.listed_at) return null;
  const minutes = Math.round(
    (new Date(listing.sold_at) - new Date(listing.listed_at)) / 60000);
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} hr`;
  return `${Math.round(minutes / (60 * 24))} days`;
}

export default function Drop() {
  const { dropId } = useParams();
  const [listings, setListings] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get(`/vessel/drops/${dropId}`).then(setListings).catch((e) => setError(e.message));
  }, [dropId]);

  if (error) return <div className="notice bad">{error}</div>;
  if (!listings) return <p className="muted">Loading…</p>;

  return (
    <div style={{ maxWidth: 900, margin: "4vh auto" }}>
      <h1>This week&rsquo;s drop</h1>
      <div className="row">
        {listings.map((l) => {
          const sold = SOLD_STATES.has(l.state);
          return (
            <div className="card grow" key={l.listing_id}
                 style={{ minWidth: 260, opacity: sold ? 0.5 : 1 }}>
              <strong>
                {l.display_producer} {l.display_wine}
                {l.release_code ? ` (${l.release_code})` : ""} {l.vintage}
              </strong>
              <div className="muted">{l.bottles} bottles · {l.stock_location.replace("_", " ")}</div>
              <div style={{ marginTop: 8 }}>
                {l.reference_label} {money(l.market_reference, l.currency)}
              </div>
              <div>
                <strong>{money(l.vessel_price, l.currency)}</strong>
                {l.percentage_claim_pct &&
                  <span className="muted"> · {(Number(l.percentage_claim_pct) * 100).toFixed(0)}% below market</span>}
              </div>
              {sold ? (
                <p className="tag stop" style={{ marginTop: 10 }}>
                  SOLD{soldIn(l) ? ` in ${soldIn(l)}` : ""}
                </p>
              ) : (
                <Link href={`/vessel/listings/${l.listing_id}`}>
                  <button type="button" style={{ marginTop: 10 }}>View</button>
                </Link>
              )}
            </div>
          );
        })}
      </div>
      {listings.length === 0 && <p className="muted">Nothing in this drop yet.</p>}
    </div>
  );
}
