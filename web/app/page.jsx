"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import Upload from "./upload";

export default function DealsPage() {
  const [deals, setDeals] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api.get("/deals").then(setDeals).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  return (
    <>
      <h1>Deals</h1>
      <p className="sub">Load a seller&rsquo;s list, then work it through identity, market and price.</p>
      {error && <div className="notice bad">{error}</div>}

      <Upload onDone={load} />

      {deals === null ? <p className="muted">Loading…</p> : deals.length === 0 ? (
        <p className="muted">No deals yet.</p>
      ) : (
        <div className="card scroll">
          <table>
            <thead>
              <tr>
                <th>Deal</th><th>Seller</th>
                <th className="num">Lines</th><th className="num">Ready</th>
                <th className="num">Review</th><th className="num">No market</th>
                <th className="num">Waiting</th><th>Loaded by</th>
              </tr>
            </thead>
            <tbody>
              {deals.map((deal) => (
                <tr key={deal.deal_id}>
                  <td><Link href={`/deals/${deal.deal_id}`}>{deal.name}</Link></td>
                  <td className="muted">{deal.seller || "—"}</td>
                  <td className="num">{deal.lines}</td>
                  <td className="num">{deal.ready}</td>
                  <td className="num">{deal.review}</td>
                  <td className="num">{deal.no_market}</td>
                  <td className="num">{deal.identity_not_approved + deal.not_searched}</td>
                  <td className="muted">{deal.created_by?.display_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
