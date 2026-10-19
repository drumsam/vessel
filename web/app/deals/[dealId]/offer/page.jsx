"use client";

import Link from "next/link";
import { Suspense, use, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, money, rate } from "../../../../lib/api";
import { clLabel, formatDate, listedAs, wineLabel } from "../../../../lib/wine";
import { buyerGroupMessage, buyerIndividualMessage, sellerMessage } from "../../../../lib/offerMessages";

/** The real client offer document — decision 0034, replacing the Cellar
 * Desk's own buyer-preview modal. "Get it from Doug — vessel-client-
 * offer.html": this page matches that spec's structure, but every figure
 * is generated from `pricing_result` and a line's own benchmark run, never
 * invented or laid out by hand. The Desk chooses which lines; this page is
 * what actually gets sent to a client, and the two are deliberately kept
 * apart (Doug: "the Desk... was never the deliverable").
 *
 * Every percentage save is `pricing.floor_saving_claim`, read verbatim —
 * computed once, server-side, against Floor, never Reference, and already
 * null (so no badge at all, same as a line with no Floor) wherever the
 * real saving is too small to advertise (MIN_CLAIM_THRESHOLD). This file
 * never recomputes it.
 *
 * Where a merchant's own ask was derived across case sizes
 * (`derived_from`, decision 0016/0018), the evidence table shows the RAW
 * case price and pack size exactly as that merchant listed it, alongside
 * the per-bottle figure it was divided into — never just the result, per
 * Doug's own instruction: "the client must see that derivation."
 */

function provenance(p, run, fx) {
  const floor = money(p.uk_floor);
  const derivedComps = run.comps.filter((c) => c.role === "merchant_best" && c.derived_from);
  const read = `Read ${formatDate(run.as_of)}, UK In Bond, excluding duty and VAT. Converted at ${fx} HKD per GBP.`;
  let basis;
  if (p.comp_count < 2) {
    basis = `Only one UK merchant was found offering this wine. The price shown is set directly ` +
      `against that single ask, ${floor} — there is no second source to check it against, which is ` +
      `why this line needed a name before it could be sent.`;
  } else if (p.price_basis === "buyer_discount") {
    const ref = money(p.uk_reference);
    basis = `Our price is set from the second-lowest of these — ${ref} — less ${rate(p.buyer_discount)}, ` +
      `then checked to sit below the lowest, which is ${floor}. The saving shown is measured against ` +
      `that lowest price, not the reference.`;
  } else {
    basis = `Our price here is ${money(p.sell_price)} a bottle, shown against the lowest of these — ` +
      `${floor} — the real cheapest ask found, never an average.`;
  }
  const derivedNote = derivedComps.length
    ? " One of these merchants lists this wine by the case; the per-bottle figure above is that case " +
      "price divided, not estimated — shown both ways below."
    : "";
  return `${read} ${basis}${derivedNote}`;
}

/** Decision 0035. "A document he can't send is just a document" — the one
 * link a buyer or a seller can actually open with no login, and the
 * pre-filled WhatsApp text to put it in front of them, exactly the
 * wa.me mechanism decision 0025 already built (web/app/member/[memberId]/
 * page.jsx), reused rather than reinvented.
 *
 * The three message bodies are Doug's own drafted wording
 * (web/lib/offerMessages.js), not invented here — this component only
 * supplies the real figures the tokens stand for. The rules he gave "to
 * enforce in code, not in the copy" live in that file, not this one:
 * a buyer message structurally cannot reach a seller/commission/cost/
 * margin figure, and no percentage prints where decision 0034 suppressed
 * it, individually or blended.
 */
function ShareComposer({ dealId, lineIds, fx, ready, wines, dealLines, city }) {
  const [kind, setKind] = useState("buyer");
  const [style, setStyle] = useState("individual");   // buyer only: individual | group
  const [link, setLink] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [copiedLink, setCopiedLink] = useState(false);
  const [copiedText, setCopiedText] = useState(false);

  const priceFmt = (gbp) => fx ? "HK$" + Math.round(gbp * Number(fx)).toLocaleString("en-GB")
                                : money(gbp);

  function composeText(url, expiresAt) {
    const expiryDays = Math.max(1, Math.round((new Date(expiresAt) - new Date()) / 86400000));
    if (kind === "seller") {
      return sellerMessage({ ready, dealLines, sharedLineIds: lineIds, link: url, priceFmt });
    }
    return style === "group"
      ? buyerGroupMessage({ ready, wines, city, link: url })
      : buyerIndividualMessage({ ready, wines, city, link: url, expiryDays, priceFmt });
  }

  async function generate() {
    setBusy(true);
    setError(null);
    setCopiedLink(false);
    setCopiedText(false);
    try {
      const body = { line_ids: lineIds, kind, fx_rate: fx || null };
      const result = await api.post(`/deals/${dealId}/offer-links`, body);
      const url = `${window.location.origin}/share/${result.token}`;
      setLink({ url, expiresAt: result.expires_at });
      setText(composeText(url, result.expires_at));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2>Share this offer</h2>
      <p className="muted" style={{ fontSize: 13.5 }}>
        A signed, read-only link — no login needed, open for 7 days. The buyer view never shows
        cost or commission; the seller view may show commission, never the rest of the cellar.
      </p>
      <div className="bar" style={{ marginBottom: 10 }}>
        <button className={`pill ${kind === "buyer" ? "on" : ""}`} onClick={() => setKind("buyer")}>
          For the buyer
        </button>
        <button className={`pill ${kind === "seller" ? "on" : ""}`} onClick={() => setKind("seller")}>
          For the seller
        </button>
      </div>
      {kind === "buyer" && (
        <div className="bar" style={{ marginBottom: 10 }}>
          <button className={`pill ${style === "individual" ? "on" : ""}`} onClick={() => setStyle("individual")}>
            Message: to one person
          </button>
          <button className={`pill ${style === "group" ? "on" : ""}`} onClick={() => setStyle("group")}>
            Message: to a group
          </button>
        </div>
      )}
      <button className="quiet" disabled={busy} onClick={generate}>
        {busy ? "Generating…" : link ? "Generate a new link" : "Generate link"}
      </button>
      {error && <div className="notice bad" style={{ marginTop: 10 }}>{error}</div>}
      {link && (
        <div className="card" style={{ marginTop: 12, padding: 14 }}>
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <input readOnly value={link.url} style={{ flex: 1 }} onFocus={(e) => e.target.select()} />
            <button className="small" onClick={() => {
              navigator.clipboard?.writeText(link.url);
              setCopiedLink(true);
            }}>{copiedLink ? "Copied" : "Copy link"}</button>
          </div>
          <textarea rows={7} style={{ width: "100%", font: "inherit" }}
                    value={text} onChange={(e) => setText(e.target.value)} />
          <div className="act" style={{ marginTop: 10 }}>
            <button className="go"
                    onClick={() => window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank")}>
              Share on WhatsApp
            </button>
            <button className="quiet" onClick={() => {
              navigator.clipboard?.writeText(text);
              setCopiedText(true);
            }}>{copiedText ? "Copied" : "Copy text"}</button>
          </div>
        </div>
      )}
    </>
  );
}

function OfferDocument({ dealId }) {
  const search = useSearchParams();
  const lineIds = (search.get("lines") || "").split(",").filter(Boolean);
  const fx = search.get("fx") || "10.37";

  const [deal, setDeal] = useState(null);
  const [wines, setWines] = useState(new Map());
  const [runs, setRuns] = useState({});
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!dealId) return;
    api.get(`/deals/${dealId}`).then(setDeal).catch((e) => setError(e.message));
    api.get("/wines").then((ws) => setWines(new Map(ws.map((w) => [w.wine_id, w])))).catch(() => {});
  }, [dealId]);

  useEffect(() => {
    lineIds.forEach((id) => {
      api.get(`/lines/${id}/benchmark`)
        .then((run) => setRuns((prev) => ({ ...prev, [id]: run })))
        .catch((e) => setRuns((prev) => ({ ...prev, [id]: { error: e.message } })));
    });
    // lineIds is derived fresh from the URL on every render; re-fetching on
    // identity change (not a join of itself) would never settle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lineIds.join(",")]);

  if (!dealId) return <p className="muted">No deal given.</p>;
  if (error) return <div className="notice bad">{error}</div>;
  if (!deal) return <p className="muted">Loading…</p>;

  const lines = deal.lines.filter((l) => lineIds.includes(l.line_id));
  const ready = lines.filter((l) => runs[l.line_id] && !runs[l.line_id].error);
  const pending = lines.length !== ready.length;

  const hk = (gbp) => "HK$" + Math.round(gbp * Number(fx || 1)).toLocaleString("en-GB");

  const totalBottles = lines.reduce((s, l) => s + l.quantity, 0);
  const totalFloor = lines.reduce((s, l) => s + Number(l.pricing.uk_floor) * l.quantity, 0);
  const totalOffer = lines.reduce(
    (s, l) => s + Number(l.pricing.buyer_price_gbp ?? l.pricing.sell_price) * l.quantity, 0);
  const totalSave = totalFloor - totalOffer;
  const savePct = totalFloor ? Math.round((totalSave / totalFloor) * 100) : 0;
  const captureDate = ready.length
    ? formatDate(ready.map((l) => runs[l.line_id].as_of).sort().slice(-1)[0])
    : null;

  return (
    <div className="offerdoc">
      <div className="oactions">
        <Link href={`/deals/${dealId}`} className="quiet">← Back to Desk</Link>
        <button className="quiet" onClick={() => window.print()}>Print / save as PDF</button>
      </div>

      <p className="mark">Vessel</p>
      <h1>{lines.length} line{lines.length === 1 ? "" : "s"} from {deal.name}</h1>
      {captureDate && <p className="sub">Private offer · {captureDate} · open for 7 days</p>}

      <div className="to"><strong>Prepared for you</strong>
        Every price below is shown against the cheapest merchant offer we could find, with the
        merchant named. Where a saving is too small to call a discount, we show the price and say
        nothing else — still a real price, just not advertised as one.
      </div>

      {pending && <p className="muted">Loading evidence for {lines.length - ready.length} line(s)…</p>}

      <h2>The wines</h2>
      {ready.map((line) => {
        const p = line.pricing;
        const run = runs[line.line_id];
        const label = wineLabel(line, wines);
        const comps = run.comps.filter((c) => c.role === "merchant_best").sort((a, b) => Number(a.price) - Number(b.price));
        const floorPerBottle = Number(p.uk_floor);
        const offerPerBottle = Number(p.buyer_price_gbp ?? p.sell_price);
        const savePctLine = p.floor_saving_claim !== null && p.floor_saving_claim !== undefined
          ? Math.round(Number(p.floor_saving_claim) * 100) : null;
        return (
          <article className="oline" key={line.line_id}>
            <div className="ohead">
              <div>
                <h3>{label.producer} <em>{label.cuvee}</em></h3>
                <p className="ometa">
                  {label.vintage} · {line.quantity} bottle{line.quantity === 1 ? "" : "s"} ·{" "}
                  {line.bottle_ml ? clLabel(line.bottle_ml) : "75cl"} · Hong Kong, In Bond
                </p>
              </div>
              <div className="oprice">
                <p className="owas">{hk(floorPerBottle)} <span>best price we found</span></p>
                <p className="onow">{hk(offerPerBottle)}<span className="oper">per bottle</span></p>
                <p className="ogbp">£{offerPerBottle.toFixed(2)} / bottle</p>
                {savePctLine !== null && <p className="osave">{savePctLine}% below</p>}
                <p className="otot">
                  {line.quantity} bottle{line.quantity === 1 ? "" : "s"} ·{" "}
                  <strong>{hk(offerPerBottle * line.quantity)}</strong>
                </p>
              </div>
            </div>
            <details>
              <summary>Where that price comes from</summary>
              <table className="oev">
                <thead>
                  <tr><th>Merchant</th><th>Listed as</th><th className="n">Price</th><th className="n">HK$</th></tr>
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
                      <td className="n">{hk(Number(c.price))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="oprov">{provenance(p, run, fx)}</p>
            </details>
          </article>
        );
      })}

      {ready.length > 0 && (
        <>
          <h2>The total</h2>
          <div className="ototals">
            <dl>
              <dt>{lines.length} line{lines.length === 1 ? "" : "s"} · {totalBottles} bottles</dt><dd></dd>
              <dt>Best merchant prices we found, combined</dt><dd>{hk(totalFloor)}</dd>
              <dt className="bigl">Your price</dt><dd className="big">{hk(totalOffer)}</dd>
              <dt className="sv">You save</dt><dd className="sv">{hk(totalSave)} · {savePct}%</dd>
            </dl>
          </div>
          <p className="onote">
            <strong>Why the saving is {savePct}% and not a round 20%.</strong> We set our price at 20%
            below the second-lowest merchant offer on each line, then check it sits below the lowest.
            On deep lines that lands well under the market; on some lines here it lands only just under,
            or — where it would be too small to call a discount — we show no percentage at all. We show
            you the real figure per line rather than an average, because a number you can check in
            thirty seconds is worth more than a round one.
          </p>

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

          <ShareComposer dealId={dealId} lineIds={lineIds} fx={fx} ready={ready} wines={wines}
                        dealLines={deal.lines} city={deal.city} />

          <footer className="ofooter">
            <p>Prices read on {captureDate} and valid for 7 days from that date; the UK market moves and we
              re-check before any sale completes. Converted at {fx} HKD per GBP — confirm against your own
              rate. All prices In Bond, excluding duty and local taxes.</p>
            <p>VESSEL · a trading name of Invecta · wine@invecta.co</p>
          </footer>
        </>
      )}
    </div>
  );
}

export default function OfferPage({ params }) {
  const { dealId } = use(params);
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <OfferDocument dealId={dealId} />
    </Suspense>
  );
}
