"use client";

// VESSEL screens 4-5 — the hold, payment, and confirmation. One page, the
// content changes with the state: HELD shows the countdown and bank
// details, EXPIRED sends the buyer back, and the listing reading PAID
// shows the confirmation. Copy is exactly as specified: never "confirmed in
// minutes" — only "confirmed when funds are received".
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, money } from "../../../../lib/api";

function timeLeft(expiresAt) {
  const ms = new Date(expiresAt) - new Date();
  if (ms <= 0) return "0:00";
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function ReservationPage() {
  const { reservationId } = useParams();
  const [reservation, setReservation] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());

  function load() {
    api.get(`/vessel/reservations/${reservationId}`).then(setReservation)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [reservationId]);
  useEffect(() => {
    const id = setInterval(() => { setNow(Date.now()); load(); }, 15000);
    return () => clearInterval(id);
  }, [reservationId]);

  async function submitProof() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/vessel/reservations/${reservationId}/proof-of-payment`);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="notice bad">{error}</div>;
  if (!reservation) return <p className="muted">Loading…</p>;

  const paid = ["PAID", "TRANSFERRING", "SETTLED"].includes(reservation.listing_state);
  const expired = reservation.state === "EXPIRED" || reservation.state === "CANCELLED";

  return (
    <div style={{ maxWidth: 420, margin: "6vh auto" }} className="card">
      <h1 style={{ marginTop: 0 }}>
        {reservation.display_producer} {reservation.display_wine} {reservation.vintage}
      </h1>

      {paid ? (
        <>
          <h2 className="tag ready" style={{ display: "inline-block" }}>Yours</h2>
          <p>
            We will verify, arrange bond-to-bond transfer, and pay the seller once funds have
            cleared. Expect to hear from us about collection or onward storage within a few
            working days.
          </p>
        </>
      ) : expired ? (
        <>
          <p className="notice bad">
            This reservation has expired. The wine has gone back on sale — if it is still there,
            you are welcome to try again.
          </p>
        </>
      ) : (
        <>
          <p>Reserved for you · <strong>{timeLeft(reservation.expires_at)}</strong></p>
          <p>
            Pay {money(reservation.vessel_price, reservation.currency)} by FPS or bank transfer.
          </p>
          <div className="card" style={{ fontFamily: "ui-monospace, monospace" }}>
            <div>Reference <strong>{reservation.payment_reference}</strong> — must be quoted</div>
          </div>
          <p className="muted" style={{ fontSize: 13 }}>
            Your purchase is confirmed when funds are received. If payment does not arrive before
            the countdown ends, the wine goes back on sale.
          </p>
          {error && <div className="notice bad">{error}</div>}
          <button type="button" disabled={busy} onClick={submitProof}>
            I&rsquo;ve sent the payment
          </button>
        </>
      )}
    </div>
  );
}
