"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { LOADING, fetchInto, refreshInto } from "../lib/fetchState";
import { TradeRow, openHref, whenText } from "./trade-row";

/** The Workbench (decision 0050), the operating engine — not an exceptions
 * console. It answers five questions only: what needs my attention, what is
 * ready for me, what is out with clients, what is confirmed, what happened.
 * Every next step is a human action; raw messages, evidence and audit stay
 * one level deeper, and a review queue appears only when something is in it. */
export default function Workbench() {
  const [wb, setWb] = useState(LOADING);
  const load = useCallback(() => fetchInto(setWb, api.get("/workbench")), []);
  const refresh = useCallback(() => refreshInto(setWb, api.get("/workbench")), []);
  useEffect(() => { load(); }, [load]);

  return (
    <>
      <section className="card wb-new">
        <div>
          <h1 style={{ margin: 0 }}>New offer</h1>
          <p className="muted" style={{ margin: "2px 0 0" }}>Paste, photo or upload a supplier&rsquo;s message.</p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <Link href="/pocket" className="button">New offer</Link>
          <Link href="/trades" className="button quiet">Load a cellar list</Link>
        </div>
      </section>

      {wb.status === "loading" && <p className="muted">Loading…</p>}
      {wb.status === "error" && (
        <div className="notice bad">
          Couldn&apos;t load the Workbench ({wb.error}).{" "}
          <button type="button" className="small" onClick={load}>Retry</button>
        </div>
      )}
      {wb.status === "ok" && <Sections wb={wb.data} onChanged={refresh} />}
    </>
  );
}

function Sections({ wb, onChanged }) {
  const c = wb.review_counts;
  const technical = [
    c.cellar_lines > 0 && `Review ${c.cellar_lines} cellar line${c.cellar_lines === 1 ? "" : "s"}`,
    c.lwin_conflicts > 0 && `Resolve ${c.lwin_conflicts} LWIN conflict${c.lwin_conflicts === 1 ? "" : "s"}`,
    c.alias_suggestions > 0 && `Approve ${c.alias_suggestions} wine spelling${c.alias_suggestions === 1 ? "" : "s"}`,
  ].filter(Boolean);

  return (
    <>
      <Section title="To review" items={wb.to_review} onChanged={onChanged}
               extra={technical.length > 0 && (
                 <div className="wb-technical">
                   {technical.map((t) => <Link key={t} href="/queue">{t}</Link>)}
                 </div>
               )} />
      <Section title="Ready to price" items={wb.ready_to_price} onChanged={onChanged} />
      <Section title="Offers out" items={wb.offers_out} onChanged={onChanged} />
      <Section title="Confirmed" items={wb.confirmed} onChanged={onChanged} />

      <h2>Recent activity</h2>
      {wb.recent.length === 0 ? <p className="muted">Nothing yet.</p> : (
        <div className="card wb-recent">
          {wb.recent.map((a) => (
            <Link key={`${a.inbound_offer_id}-${a.when}`} href={openHref(a.inbound_offer_id)}>
              <span>{a.text}</span>
              <span className="muted">{whenText(a.when)}</span>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

function Section({ title, items, extra, onChanged }) {
  return (
    <>
      <h2>{title}{items.length > 0 && <span className="muted wb-count"> {items.length}</span>}</h2>
      {extra}
      {items.length === 0 && !extra ? <p className="muted">None.</p> : items.length > 0 && (
        <div className="card tlist">
          {items.map((t) => <TradeRow key={t.inbound_offer_id} t={t} onChanged={onChanged} />)}
        </div>
      )}
    </>
  );
}
