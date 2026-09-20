"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api, format, money, rate } from "../../../lib/api";

/** An offer as it was issued. These figures are the ones that were sent; they
 *  do not change when the market does.
 *
 *  A line may only carry a market claim where there is a UK Reference to claim
 *  against AND the price is below it, so the two kinds of line are printed in
 *  two tables. A line without a claim has no "UK market" cell to leave blank —
 *  the column does not exist for it at all (decision 0010). The data makes this
 *  hard to get wrong: the API sends market_claim only where a claim exists.
 */
export default function OfferPage({ params }) {
  const { offerId } = use(params);
  const [offer, setOffer] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get(`/buyer-offers/${offerId}`).then(setOffer).catch((e) => setError(e.message));
  }, [offerId]);

  if (!offer) return <p className="muted">{error || "Loading…"}</p>;

  const claimed = offer.lines.filter((line) => line.market_claim);
  const costPlus = offer.lines.filter((line) => !line.market_claim);

  const Row = ({ line }) => (
    <>
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
    </>
  );

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

      {claimed.length > 0 && (
        <>
          <h2>Priced against the UK market</h2>
          <div className="card scroll">
            <table>
              <thead>
                <tr>
                  <th>#</th><th>Wine</th><th>Format</th>
                  <th className="num">Qty</th><th className="num">Unit</th>
                  <th className="num">Total</th>
                  <th className="num">UK Market</th><th className="num">Below UK Market</th>
                </tr>
              </thead>
              <tbody>
                {claimed.map((line) => (
                  <tr key={line.line_no}>
                    <Row line={line} />
                    <td className="num">{money(line.market_claim.uk_reference, offer.currency)}</td>
                    <td className="num">{rate(line.market_claim.below_reference)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: 13 }}>
              UK Market is the second-lowest In Bond offer across{" "}
              {Math.min(...claimed.map((l) => l.market_claim.comp_count))}+ approved UK merchants,
              measured {new Date(claimed[0].market_claim.as_of).toLocaleDateString("en-GB")}.
            </p>
          </div>
        </>
      )}

      {costPlus.length > 0 && (
        <>
          <h2>Priced without a UK market comparison</h2>
          <div className="card scroll">
            <table>
              <thead>
                <tr>
                  <th>#</th><th>Wine</th><th>Format</th>
                  <th className="num">Qty</th><th className="num">Unit</th>
                  <th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {costPlus.map((line) => (
                  <tr key={line.line_no}><Row line={line} /></tr>
                ))}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: 13 }}>
              No UK market comparison is offered on these lines.
            </p>
          </div>
        </>
      )}

      <div className="card">
        <table>
          <tbody>
            <tr>
              <td><strong>Total</strong></td>
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
