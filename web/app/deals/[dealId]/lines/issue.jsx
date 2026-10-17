"use client";

import { useEffect, useState } from "react";
import { api, money } from "../../../../lib/api";

/** Issue an offer. The API refuses any line that is unpriced or unaccepted, so
 *  the whole document stops rather than quietly losing a line. */
export default function IssueOffer({ deal, priced, onIssued }) {
  const [client, setClient] = useState("");
  const [terms, setTerms] = useState("");
  const [chosen, setChosen] = useState(() => new Set(priced.map((l) => l.line_id)));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // Pricing arrives after this component first renders, so the initial state
  // above is empty on the run that matters. Without this the offer form sits
  // there saying "Issue 0 line(s)" with every line unticked.
  const pricedIds = priced.map((line) => line.line_id).join(",");
  useEffect(() => {
    setChosen(new Set(pricedIds ? pricedIds.split(",") : []));
  }, [pricedIds]);

  function toggle(lineId) {
    const next = new Set(chosen);
    next.has(lineId) ? next.delete(lineId) : next.add(lineId);
    setChosen(next);
  }

  async function issue() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/deals/${deal.deal_id}/buyer-offers`, {
        client,
        currency: "GBP",
        terms: terms || null,
        lines: [...chosen].map((line_id) => ({ line_id })),
      });
      setClient("");
      setTerms("");
      onIssued();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!priced.length) {
    return <p className="muted">Nothing is priced yet, so there is nothing to offer.</p>;
  }

  return (
    <div className="card">
      {error && <div className="notice bad">{error}</div>}
      <div className="row">
        <div className="grow">
          <label htmlFor="client">Client</label>
          <input id="client" value={client} onChange={(e) => setClient(e.target.value)} />
        </div>
        <div className="grow">
          <label htmlFor="terms">Terms</label>
          <input id="terms" placeholder="e.g. In Bond, ex-London City Bond"
                 value={terms} onChange={(e) => setTerms(e.target.value)} />
        </div>
        <button onClick={issue} disabled={busy || !client || chosen.size === 0}>
          {busy ? "Issuing…" : `Issue ${chosen.size} line(s)`}
        </button>
      </div>
      <div className="scroll" style={{ marginTop: 12 }}>
        <table>
          <thead>
            <tr><th></th><th>Line</th><th className="num">Qty</th><th className="num">Unit</th><th></th></tr>
          </thead>
          <tbody>
            {priced.map((line) => {
              const blocked = line.pricing.requires_acknowledgement && !line.pricing.acknowledgement;
              return (
                <tr key={line.line_id}>
                  <td>
                    <input type="checkbox" style={{ width: 18 }} checked={chosen.has(line.line_id)}
                           onChange={() => toggle(line.line_id)} />
                  </td>
                  <td className="verbatim">{line.raw_description}</td>
                  <td className="num">{line.quantity}</td>
                  <td className="num">{money(line.pricing.sell_price)}</td>
                  <td>{blocked && <span className="tag stop">needs sign-off first</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
