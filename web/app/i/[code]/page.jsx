"use client";

// VESSEL referral landing page (decision 0025). No login: reachable by the
// link, the same discipline VESSEL's own buyer- and seller-facing screens
// already use. Three things, in order: who invited you, what's in the
// cellar, recent real sales — never fabricated, omitted when there is
// nothing real to show.
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, money } from "../../../lib/api";

export default function InviteLanding() {
  const { code } = useParams();
  const router = useRouter();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    api.get(`/invites/${code}`).then(setData).catch((e) => setError(e.message));
  }, [code]);

  if (error) return <div className="notice bad" style={{ margin: "4vh auto", maxWidth: 480 }}>{error}</div>;
  if (!data) return <p className="muted" style={{ margin: "4vh auto", maxWidth: 480 }}>Loading…</p>;

  if (data.already_accepted) {
    return (
      <div style={{ maxWidth: 480, margin: "10vh auto" }} className="card">
        <p>This invitation has already been used.</p>
      </div>
    );
  }

  if (accepting) return <AcceptForm code={code} onDone={(member) => router.replace(`/member/${member.member_id}`)} />;

  return (
    <div style={{ maxWidth: 480, margin: "6vh auto" }}>
      <h1>{data.inviter_first_name} has invited you to VESSEL.</h1>

      {data.cellar && (
        <p>
          {data.cellar.region ? `${data.cellar.region} — ` : ""}
          {data.cellar.listing_count} wine{data.cellar.listing_count === 1 ? "" : "s"} available
          {data.cellar.price_from && `, from ${money(data.cellar.price_from, data.cellar.currency)}`}.
        </p>
      )}

      {data.recent_sales.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ marginTop: 0 }}>Recently sold</h2>
          {data.recent_sales.map((s, i) => (
            <p key={i} className="muted" style={{ fontSize: 14 }}>
              {s.display_producer} {s.display_wine} {s.vintage}
              {s.days_to_sell !== null && ` — sold in ${s.days_to_sell} day${s.days_to_sell === 1 ? "" : "s"}`}
            </p>
          ))}
        </div>
      )}

      <button type="button" style={{ marginTop: 20 }} onClick={() => setAccepting(true)}>
        Accept invitation
      </button>
    </div>
  );
}

function AcceptForm({ code, onDone }) {
  const [phone, setPhone] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otp, setOtp] = useState("");
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [storageNote, setStorageNote] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function sendCode(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/members/request-code", { phone });
      setOtpSent(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function accept(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.post(`/invites/${code}/accept`,
        { phone, otp_code: otp, name, city, storage_note: storageNote.trim() || null });
      onDone(result.member);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 420, margin: "10vh auto" }} className="card">
      <h2 style={{ marginTop: 0 }}>Accept invitation</h2>
      {error && <div className="notice bad">{error}</div>}
      <form onSubmit={otpSent ? accept : sendCode}>
        <label htmlFor="phone">Mobile number</label>
        <input id="phone" required placeholder="+44..." value={phone} disabled={otpSent}
               onChange={(e) => setPhone(e.target.value)} style={{ marginBottom: 10 }} />
        {otpSent && (
          <>
            <label htmlFor="otp">Code we just sent you</label>
            <input id="otp" required inputMode="numeric" value={otp}
                   onChange={(e) => setOtp(e.target.value)} style={{ marginBottom: 10 }} />
            <label htmlFor="name">Name</label>
            <input id="name" required value={name} onChange={(e) => setName(e.target.value)}
                   style={{ marginBottom: 10 }} />
            <label htmlFor="city">City</label>
            <input id="city" required value={city} onChange={(e) => setCity(e.target.value)}
                   style={{ marginBottom: 10 }} />
            <label htmlFor="storage">How do you store wine? (optional)</label>
            <input id="storage" value={storageNote} onChange={(e) => setStorageNote(e.target.value)}
                   style={{ marginBottom: 10 }} />
          </>
        )}
        <button type="submit" disabled={busy}>{otpSent ? "Accept" : "Send me a code"}</button>
      </form>
    </div>
  );
}
