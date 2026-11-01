"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { LOADING, fetchInto, refreshInto } from "../../lib/fetchState";
import Upload from "../upload";
import { TradeHead, TradeRow, whenText } from "../trade-row";

/** Every trade in one list (decision 0050): Pocket offers, each once, and
 * cellar lists — never the per-offer deal a Pocket offer keeps behind it.
 * Cards rather than a wide table, so a phone never scrolls sideways. */
export default function TradesPage() {
  const [trades, setTrades] = useState(LOADING);
  const [showUpload, setShowUpload] = useState(false);
  const load = useCallback(() => fetchInto(setTrades, api.get("/trades")), []);
  const refresh = useCallback(() => refreshInto(setTrades, api.get("/trades")), []);
  useEffect(() => { load(); }, [load]);

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h1>Trades</h1>
        <div className="row" style={{ gap: 8 }}>
          <Link href="/pocket" className="button small">New offer</Link>
          <button type="button" className="small quiet" onClick={() => setShowUpload(!showUpload)}>
            {showUpload ? "Close" : "Load a cellar list"}
          </button>
        </div>
      </div>
      {showUpload && <div style={{ marginTop: 12 }}><Upload onDone={refresh} /></div>}

      {trades.status === "loading" && <p className="muted">Loading…</p>}
      {trades.status === "error" && (
        <div className="notice bad">
          Couldn&apos;t load trades ({trades.error}).{" "}
          <button type="button" className="small" onClick={load}>Retry</button>
        </div>
      )}
      {trades.status === "ok" && (
        <>
          <h2>Offers</h2>
          {trades.data.pocket.length === 0 ? <p className="muted">No offers yet.</p> : (
            <div className="card tlist">
              <TradeHead />
              {trades.data.pocket.map((t) => <TradeRow key={t.inbound_offer_id} t={t} onChanged={refresh} />)}
            </div>
          )}

          <h2>Cellar lists</h2>
          {trades.data.cellars.length === 0 ? <p className="muted">No cellar lists yet.</p> : (
            <div className="card tlist">
              {trades.data.cellars.map((d) => (
                <div key={d.deal_id} className="trow">
                  <div className="t-what">
                    <Link href={`/deals/${d.deal_id}`} className="t-title">{d.name}</Link>
                    <div className="muted t-small">{d.lines} line{d.lines === 1 ? "" : "s"} · {whenText(d.when)}</div>
                  </div>
                  <div className="t-who t-small">{d.seller || <span className="muted">No seller named</span>}</div>
                  <div className="t-status">
                    <span className={d.ready ? "tag ready" : "tag"}>{d.ready} ready</span>
                  </div>
                  <div className="t-next t-small">
                    <Link href={`/deals/${d.deal_id}`} className="t-action">{d.next_action}</Link>
                  </div>
                  <div />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
