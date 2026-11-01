"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { LOADING, failed, fetchInto, ok, refreshInto } from "../lib/fetchState";
import { TradeRow } from "./trade-row";

/** The supplier and client registers (decision 0050): commercial memory,
 * not a CRM. One searchable list, one record with its aliases and the few
 * defaults that save typing, and the trades it appears on. Nothing here is
 * required to trade — both are created inline, from a name, while trading. */

export const KINDS = {
  suppliers: {
    title: "Suppliers", one: "supplier", base: "/suppliers", list: "/suppliers?all=true",
    id: "supplier_id", tradeKey: "supplier_id", countLabel: ["offer", "offers"],
    fields: [
      ["contact_name", "Contact"], ["phone", "Phone"], ["email", "Email"],
      ["default_currency", "Default currency", "ISO code, e.g. GBP"],
      ["usual_stock_location", "Usual location", "e.g. LCB"],
      ["usual_bond_status", "Usual bond", "e.g. UK In Bond"],
      ["payment_terms", "Payment terms", "e.g. 30 days"],
      ["notes", "Notes", null, true],
    ],
  },
  clients: {
    title: "Clients", one: "client", base: "/clients", list: "/clients",
    id: "client_id", tradeKey: "client_id", countLabel: ["confirmed trade", "confirmed trades"],
    fields: [
      ["contact_name", "Contact"], ["phone", "Phone"], ["email", "Email"],
      ["default_currency", "Default currency", "ISO code, e.g. HKD"],
      ["delivery_notes", "Delivery notes", null, true],
      ["payment_terms", "Payment terms", "e.g. 7 days"],
      ["notes", "Notes", null, true],
    ],
  },
};

export function RegisterList({ kind }) {
  const k = KINDS[kind];
  const [rows, setRows] = useState(LOADING);
  const [q, setQ] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [adding, setAdding] = useState(ok(null));
  const load = useCallback(() => fetchInto(setRows, api.get(k.list)), [k.list]);
  useEffect(() => { load(); }, [load]);

  async function add(e) {
    e.preventDefault();
    if (!name.trim()) return;
    setAdding(LOADING);
    try {
      await api.post(k.base, { name: name.trim(), phone: phone.trim() || null });
      setName("");
      setPhone("");
      setAdding(ok(null));
      load();
    } catch (err) {
      setAdding(failed(err));
    }
  }

  const needle = q.trim().toLowerCase();
  const shown = rows.status === "ok" ? rows.data.filter((r) => !needle
    || [r.name, r.contact_name, r.phone, r.email].some((v) => v && v.toLowerCase().includes(needle))) : [];

  return (
    <>
      <h1>{k.title}</h1>
      <div className="row" style={{ marginTop: 12 }}>
        <div className="grow">
          <label htmlFor="rq">Search</label>
          <input id="rq" type="search" value={q} placeholder={`Name, contact, phone or email`}
                 onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>

      {rows.status === "loading" && <p className="muted">Loading…</p>}
      {rows.status === "error" && <div className="notice bad">Couldn&apos;t load {k.title.toLowerCase()} ({rows.error}).</div>}
      {rows.status === "ok" && (
        rows.data.length === 0 ? <p className="muted">No {k.title.toLowerCase()} yet.</p>
          : shown.length === 0 ? <p className="muted">No {k.one} matches &ldquo;{q}&rdquo;.</p> : (
            <div className="card tlist" style={{ marginTop: 12 }}>
              {shown.map((r) => (
                <Link key={r[k.id]} href={`${k.base}/${r[k.id]}`} className="reg-row">
                  <span>
                    <strong>{r.name}</strong>
                    {!r.active && <span className="tag plain" style={{ marginLeft: 6 }}>inactive</span>}
                    <span className="muted t-small" style={{ display: "block" }}>
                      {[r.contact_name, r.phone, r.default_currency].filter(Boolean).join(" · ") || "No details yet"}
                    </span>
                  </span>
                  <span className="muted t-small">{r.last_used_at ? `last ${new Date(r.last_used_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}` : ""}</span>
                </Link>
              ))}
            </div>
          )
      )}

      <form onSubmit={add} className="card" style={{ marginTop: 16 }}>
        <div className="pocket-label" style={{ marginBottom: 8 }}>ADD A {k.one.toUpperCase()}</div>
        <div className="row">
          <div className="grow">
            <label htmlFor="rname">Name</label>
            <input id="rname" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grow">
            <label htmlFor="rphone">Phone (optional)</label>
            <input id="rphone" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
          <button type="submit" disabled={!name.trim() || adding.status === "loading"}>
            {adding.status === "loading" ? "Adding…" : "Add"}
          </button>
        </div>
        {adding.status === "error" && <div className="notice bad" style={{ marginTop: 10 }}>{adding.error}</div>}
      </form>
    </>
  );
}

const blank = (v) => (v == null ? "" : String(v));

export function RegisterDetail({ kind, id }) {
  const k = KINDS[kind];
  const [rec, setRec] = useState(LOADING);
  const [form, setForm] = useState({});
  const [save, setSave] = useState(ok(null));
  const [alias, setAlias] = useState("");
  const [trades, setTrades] = useState(LOADING);

  function adopt(r) {
    setRec(ok(r));
    setForm(Object.fromEntries(["name", ...k.fields.map(([f]) => f)].map((f) => [f, blank(r[f])])));
  }
  const load = useCallback(async () => {
    setRec(LOADING);
    try { adopt(await api.get(`${k.base}/${id}`)); } catch (e) { setRec(failed(e)); }
  }, [k.base, id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  useEffect(() => { fetchInto(setTrades, api.get("/trades")); }, []);

  async function patch(changes) {
    setSave(LOADING);
    try {
      adopt(await api.patch(`${k.base}/${id}`, changes));
      setSave(ok("Saved"));
    } catch (e) {
      setSave(failed(e));
    }
  }

  function submit(e) {
    e.preventDefault();
    const r = rec.data;
    const changes = {};
    for (const [f, v] of Object.entries(form)) {
      const next = v.trim() === "" ? null : (f === "default_currency" ? v.trim().toUpperCase() : v.trim());
      if (next !== (r[f] ?? null)) changes[f] = next;
    }
    if (changes.name === null) delete changes.name;
    if (Object.keys(changes).length) patch(changes);
  }

  async function addAlias(e) {
    e.preventDefault();
    if (!alias.trim()) return;
    try {
      adopt(await api.post(`${k.base}/${id}/aliases`, { alias: alias.trim() }));
      setAlias("");
    } catch (err) {
      setSave(failed(err));
    }
  }

  if (rec.status === "loading") return <p className="muted">Loading…</p>;
  if (rec.status === "error") return <div className="notice bad">Couldn&apos;t load this {k.one} ({rec.error}).</div>;
  const r = rec.data;
  const mine = trades.status === "ok" ? trades.data.pocket.filter((t) => t[k.tradeKey] === id) : [];

  return (
    <>
      <p style={{ margin: "0 0 8px" }}><Link href={k.base}>← {k.title}</Link></p>
      <h1>{r.name}</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        {r.trades} {k.countLabel[r.trades === 1 ? 0 : 1]}{!r.active && " · inactive"}
      </p>

      <form onSubmit={submit} className="card">
        <div className="reg-grid">
          <div>
            <label htmlFor="f-name">Name</label>
            <input id="f-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          {k.fields.map(([f, label, hint, long]) => (
            <div key={f} className={long ? "wide" : undefined}>
              <label htmlFor={`f-${f}`}>{label}</label>
              {long ? (
                <textarea id={`f-${f}`} rows={2} value={form[f]} placeholder={hint || undefined}
                          onChange={(e) => setForm({ ...form, [f]: e.target.value })} />
              ) : (
                <input id={`f-${f}`} value={form[f]} placeholder={hint || undefined}
                       onChange={(e) => setForm({ ...form, [f]: e.target.value })} />
              )}
            </div>
          ))}
        </div>
        <div className="row" style={{ marginTop: 12, alignItems: "center" }}>
          <button type="submit" disabled={save.status === "loading"}>
            {save.status === "loading" ? "Saving…" : "Save"}
          </button>
          <button type="button" className="quiet" onClick={() => patch({ active: !r.active })}>
            {r.active ? "Mark inactive" : "Mark active"}
          </button>
          {save.status === "ok" && save.data && <span className="muted">{save.data}</span>}
        </div>
        {save.status === "error" && <div className="notice bad" style={{ marginTop: 10 }}>{save.error}</div>}
      </form>

      <div className="card">
        <div className="pocket-label">ALSO KNOWN AS</div>
        <p className="muted t-small" style={{ margin: "4px 0 8px" }}>
          Spellings that should land on this {k.one}.
        </p>
        <div>{r.aliases.map((a) => <span key={a} className="tag">{a}</span>)}</div>
        <form onSubmit={addAlias} className="row" style={{ marginTop: 10 }}>
          <div className="grow">
            <input aria-label="New alias" value={alias} placeholder="Another spelling"
                   onChange={(e) => setAlias(e.target.value)} />
          </div>
          <button type="submit" className="small" disabled={!alias.trim()}>Add</button>
        </form>
      </div>

      <h2>Trades</h2>
      {trades.status === "loading" && <p className="muted">Loading…</p>}
      {trades.status === "error" && <div className="notice bad">Couldn&apos;t load trades ({trades.error}).</div>}
      {trades.status === "ok" && (mine.length === 0 ? <p className="muted">None yet.</p> : (
        <div className="card tlist">
          {mine.map((t) => <TradeRow key={t.inbound_offer_id} t={t}
                                     onChanged={() => refreshInto(setTrades, api.get("/trades"))} />)}
        </div>
      ))}
    </>
  );
}
