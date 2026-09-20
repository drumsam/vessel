"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api, format, money } from "../../../lib/api";

/** An offer as it was issued. These figures are the ones that were sent; they
 *  do not change when the market does. */
export default function OfferPage({ params }) {
  const { offerId } = use(params);
  const [offer, setOffer] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get(`/buyer-offers/${offerId}`).then(setOffer).catch((e) => setError(e.message));
  }, [offerId]);

  if (!offer) return <p className="muted">{error || "Loading…"}</p>;

  return (
    <>
      <p className="muted" style={{ marginBottom: 4 }}>
        <Link href={`/deals/${offer.deal_id}`}>← Deal</Link>
      </p>
      <h1>Offer to {offer.client}</h1>
      <p className="sub">
        Issued {new Date(offer.issued_at).toLocaleString("en-GB")} by {offer.issued_by?.display_name}
        {offer.terms ? ` · ${offer.terms}` : ""}
      </p>

      <div className="card scroll">
        <table>
          <thead>
            <tr>
              <th>#</th><th>Wine</th><th>Format</th>
              <th className="num">Qty</th><th className="num">Unit</th><th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {offer.lines.map((line) => (
              <tr key={line.line_no}>
                <td className="muted">{line.line_no}</td>
                <td>
                  {line.description}
                  {line.condition_notes && (
                    <div className="muted verbatim">{format(line.condition_notes)}</div>
                  )}
                </td>
                <td className="muted">{line.pack_size}×{line.bottle_ml / 100}cl</td>
                <td className="num">{line.quantity}</td>
                <td className="num">{money(line.unit_price, offer.currency)}</td>
                <td className="num">{money(line.line_total, offer.currency)}</td>
              </tr>
            ))}
            <tr>
              <td colSpan={5} className="num"><strong>Total</strong></td>
              <td className="num"><strong>{money(offer.total, offer.currency)}</strong></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: 13 }}>
        These are the figures as issued. Re-pricing a line later does not change this document.
      </p>
    </>
  );
}
