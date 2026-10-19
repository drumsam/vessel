"use client";

import { use, useEffect, useState } from "react";
import { api, money } from "../../../lib/api";
import { clLabel, formatDate, listedAs } from "../../../lib/wine";

/** Decision 0035: the one document a buyer or a seller can open with no
 * operator session — a signed, unguessable, read-only, time-boxed link
 * generated from the Cellar Desk's own offer document
 * (/deals/{dealId}/offer). Everything here is read from `/public/offer-
 * links/{token}` exactly as the server built it: this file never decides
 * what is safe to show, it only renders what the API already decided —
 * a buyer-kind payload has no seller_price_gbp or commission_gbp key at
 * all (app/offerlink/repo.py), and nothing here names the deal or the
 * seller, because the API never sent either.
 */
export default function SharePage({ params }) {
  const { token } = use(params);
  const [offer, setOffer] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get(`/public/offer-links/${token}`).then(setOffer).catch((e) => setError(e.message));
  }, [token]);

  if (error) {
    return (
      <div className="offerdoc">
        <p className="mark">Vessel</p>
        <div className="notice bad">
          This link has expired or does not exist. Ask whoever sent it for a new one.
        </div>
      </div>
    );
  }
  if (!offer) return <div className="offerdoc"><p className="muted">Loading…</p></div>;

  const fx = offer.fx_rate;
  const hk = (gbp) => (fx ? "HK$" + Math.round(gbp * Number(fx)).toLocaleString("en-GB") : null);
  const isSeller = offer.kind === "seller";

  const totalBottles = offer.lines.reduce((s, l) => s + l.quantity, 0);
  const totalFloor = offer.lines.reduce((s, l) => s + Number(l.uk_floor ?? 0) * l.quantity, 0);
  const totalOffer = offer.lines.reduce((s, l) => s + Number(l.offer_price_gbp) * l.quantity, 0);
  const totalSave = totalFloor - totalOffer;
  const savePct = totalFloor ? Math.round((totalSave / totalFloor) * 100) : 0;
  const totalNet = isSeller
    ? offer.lines.reduce((s, l) => s + Number(l.seller_price_gbp ?? l.offer_price_gbp) * l.quantity, 0)
    : null;
  const totalCommission = isSeller
    ? offer.lines.reduce((s, l) => s + Number(l.commission_gbp ?? 0) * l.quantity, 0)
    : null;
  const captureDate = offer.lines.length
    ? formatDate([...offer.lines].map((l) => l.as_of).filter(Boolean).sort().slice(-1)[0])
    : null;

  const price = (gbp) => (hk(gbp) ? (
    <>{hk(gbp)}<span className="ogbp" style={{ display: "block" }}>£{Number(gbp).toFixed(2)} / bottle</span></>
  ) : (
    <>£{Number(gbp).toFixed(2)}<span className="oper">per bottle</span></>
  ));

  return (
    <div className="offerdoc">
      <p className="mark">Vessel</p>
      <h1>{offer.lines.length} line{offer.lines.length === 1 ? "" : "s"}, {isSeller ? "your consignment" : "a private offer"}</h1>
      {captureDate && <p className="sub">{isSeller ? "Current offer" : "Private offer"} · {captureDate} · open for 7 days</p>}

      <div className="to"><strong>{isSeller ? "What your wine is being offered at" : "Prepared for you"}</strong>
        {isSeller
          ? " Every price below is what a buyer would pay, and what you net after commission."
          : " Every price below is shown against the cheapest merchant offer we could find, with the " +
            "merchant named. Where a saving is too small to call a discount, we show the price and " +
            "say nothing else — still a real price, just not advertised as one."}
      </div>

      <h2>The wines</h2>
      {offer.lines.map((line) => {
        const comps = [...line.comps].sort((a, b) => Number(a.price) - Number(b.price));
        const savePctLine = line.floor_saving_claim !== null && line.floor_saving_claim !== undefined
          ? Math.round(Number(line.floor_saving_claim) * 100) : null;
        return (
          <article className="oline" key={line.line_id}>
            <div className="ohead">
              <div>
                <h3>{line.producer} <em>{line.cuvee}</em></h3>
                <p className="ometa">
                  {line.vintage === 1000 ? "NV" : line.vintage} · {line.quantity} bottle{line.quantity === 1 ? "" : "s"} ·{" "}
                  {line.bottle_ml ? clLabel(line.bottle_ml) : "75cl"} · In Bond
                </p>
              </div>
              <div className="oprice">
                {!isSeller && line.uk_floor && (
                  <p className="owas">{hk(Number(line.uk_floor)) || `£${Number(line.uk_floor).toFixed(2)}`} <span>best price we found</span></p>
                )}
                <p className="onow">{price(line.offer_price_gbp)}</p>
                {!isSeller && savePctLine !== null && <p className="osave">{savePctLine}% below</p>}
                <p className="otot">
                  {line.quantity} bottle{line.quantity === 1 ? "" : "s"} ·{" "}
                  <strong>{hk(Number(line.offer_price_gbp) * line.quantity)
                          || `£${(Number(line.offer_price_gbp) * line.quantity).toFixed(2)}`}</strong>
                </p>
                {isSeller && (
                  <>
                    <p className="otot">
                      Seller nets · <strong>{hk(Number(line.seller_price_gbp ?? line.offer_price_gbp) * line.quantity)
                              || money(Number(line.seller_price_gbp ?? line.offer_price_gbp) * line.quantity)}</strong>
                    </p>
                    <p className="otot">
                      Commission, invoiced · {hk(Number(line.commission_gbp ?? 0) * line.quantity)
                              || money(Number(line.commission_gbp ?? 0) * line.quantity)}
                    </p>
                  </>
                )}
              </div>
            </div>
            {!isSeller && comps.length > 0 && (
              <details>
                <summary>Where that price comes from</summary>
                <table className="oev">
                  <thead>
                    <tr><th>Merchant</th><th>Listed as</th><th className="n">Price</th>{fx && <th className="n">HK$</th>}</tr>
                  </thead>
                  <tbody>
                    {comps.map((c) => (
                      <tr key={c.merchant_offer_id}>
                        <td>{c.merchant}</td>
                        <td className="u">
                          {c.derived_from ? listedAs(c.derived_from.pack_size, c.derived_from.bottle_ml)
                                          : listedAs(c.pack_size, c.bottle_ml)}
                        </td>
                        <td className="n">
                          {c.derived_from
                            ? <>{money(c.derived_from.price)} case → {money(c.price)}/bottle</>
                            : <>{money(c.price)}/bottle</>}
                        </td>
                        {fx && <td className="n">{hk(Number(c.price))}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="oprov">
                  Read {line.as_of ? formatDate(line.as_of) : "recently"}, UK In Bond, excluding duty and VAT.
                  {fx && ` Converted at ${fx} HKD per GBP.`}
                </p>
              </details>
            )}
          </article>
        );
      })}

      {offer.lines.length > 1 && (
        <>
          <h2>The total</h2>
          <div className="ototals">
            <dl>
              <dt>{offer.lines.length} lines · {totalBottles} bottles</dt><dd></dd>
              {!isSeller && (
                <>
                  <dt>Best merchant prices we found, combined</dt>
                  <dd>{hk(totalFloor) || money(totalFloor)}</dd>
                  <dt className="bigl">Your price</dt>
                  <dd className="big">{hk(totalOffer) || money(totalOffer)}</dd>
                  <dt className="sv">You save</dt>
                  <dd className="sv">{(hk(totalSave) || money(totalSave))} · {savePct}%</dd>
                </>
              )}
              {isSeller && (
                <>
                  <dt className="bigl">Offered at</dt>
                  <dd className="big">{hk(totalOffer) || money(totalOffer)}</dd>
                  <dt>Seller nets</dt>
                  <dd>{hk(totalNet) || money(totalNet)}</dd>
                  <dt>Commission, invoiced</dt>
                  <dd>{hk(totalCommission) || money(totalCommission)}</dd>
                </>
              )}
            </dl>
          </div>
        </>
      )}

      {!isSeller && (
        <>
          <h2>How it works</h2>
          <ol>
            <li><strong>Tell us which lines you want.</strong> Reply, or message on WhatsApp. First to confirm takes the line.</li>
            <li><strong>You pay the seller directly.</strong> We send their bank details and the bond transfer
              instructions. VESSEL never holds your money — we invoice the seller a commission once the wine is yours.</li>
            <li><strong>The wine moves in bond.</strong> Warehouse to warehouse, typically within five working days.
              Transfer is at your cost and quoted before you commit.</li>
            <li><strong>Condition.</strong> Stated as declared by the owner and as seen by the warehouse. We do not
              claim a condition report we did not carry out.</li>
          </ol>
        </>
      )}

      <footer className="ofooter">
        <p>
          This link is valid until {formatDate(offer.expires_at)}; the UK market moves and we
          re-check before any sale completes.{fx && ` Converted at ${fx} HKD per GBP — confirm against your own rate.`}
          {" "}All prices In Bond, excluding duty and local taxes.
        </p>
        <p>VESSEL · a trading name of Invecta · wine@invecta.co</p>
      </footer>
    </div>
  );
}
