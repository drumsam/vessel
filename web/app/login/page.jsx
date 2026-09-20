"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/session", { username, password });
      router.replace("/");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: "12vh auto" }}>
      <h1>UK Fine Wine Pricer</h1>
      <p className="sub">Sign in to continue.</p>
      <form className="card" onSubmit={submit}>
        {error && <div className="notice bad">{error}</div>}
        <div style={{ marginBottom: 12 }}>
          <label htmlFor="username">Operator</label>
          <input id="username" autoComplete="username" value={username}
                 onChange={(e) => setUsername(e.target.value)} required />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label htmlFor="password">Password</label>
          <input id="password" type="password" autoComplete="current-password"
                 value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="muted" style={{ fontSize: 13 }}>
        Forgotten your password? An admin sets a new one; there is no self-service reset.
      </p>
    </div>
  );
}
