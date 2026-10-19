"use client";

import Link from "next/link";
import { Fragment, use, useCallback, useEffect, useState } from "react";
import { api, money } from "../../../lib/api";
import { wineLabel } from "../../../lib/wine";

/** Cellar Desk — the operator's own "what can I sell right now" view of a
 * deal, built from docs/research/cellar-desk-ui-spec.html (commit ad3c0dd).
 *
 * Every figure is read from the engine, never recomputed here: buyer_price_gbp,
 * seller_price_gbp and gp are set server-side only when a line's own pricing
 * basis is "buyer_discount" (decision 0017), so they are read as-is, never
 * derived from uk_reference in this file. The one exception is the "how far
 * apart" gap badge, which is informational commentary, not a price — the
 * REAL gate is comp_count/requires_acknowledgement, both read verbatim from
 * the API, never recomputed.
 *
 * Settlement is agency (decision 0022): the buyer pays the seller directly
 * and Doug invoices 8% commission. Nothing here ever implies the money
 * passes through this app — "Seller nets" and "Your commission, invoiced"
 * are the only labels used, on this screen and in the buyer preview alike.
 *
 * A thin (one-merchant) line is REVIEW under invariant 12: ONE_COMP is a
 * member of REVIEW_FLAGS (app/core/flags.py), so `requires_acknowledgement`
 * is already true for it with no extra logic here. Accepting it calls the
 * SAME /lines/{id}/pricing/acknowledge endpoint line.jsx already uses — no
 * new mechanism, per Doug's own instruction.
 *
 * Two states only, read from the engine, never invented here: a line is
 * either "ready to send" or it "needs you" (`gated`, below) — the exact
 * same boolean the gate itself uses, never a third tier computed from the
 * gap between two merchant-bests. An earlier version of this file DID
 * compute one, and read it as "WIDE_SPREAD is deliberately not a review
 * flag, so a two-merchant line 40% apart is READY, same as one 1.5%
 * apart" — correct for 3+ comps, wrong for exactly two (decision 0033,
 * found checking the real 9 October Champagne sweep by hand: four
 * two-comp lines were pricing AT OR ABOVE the cheapest ask actually
 * found while still carrying a "below market" claim). `WIDE_SPREAD` now
 * gates when `comp_count == 2`, and a new flag, `SELL_AT_OR_ABOVE_UK_
 * FLOOR`, catches the claim itself regardless of spread. Both are
 * already folded into `requires_acknowledgement` server-side, so `gated`
 * needs no changes here to read them correctly — READY on this sweep
 * fell from 11 to 7 the moment the engine was fixed, not this file.
 *
 * PER BOTTLE IS THE UNIT, everywhere a price is shown (Doug, 19 October
 * 2026): every money cell in the table is per-bottle HK$ first, GBP per
 * bottle underneath in small type, and the line total — bottles x
 * per-bottle — secondary and smaller in the same cell (`PriceCell`,
 * below). Before this, the primary figure was the line TOTAL, which made
 * a line un-checkable against what a merchant actually published: nobody
 * compares a case's worth of HK$ against a merchant's own per-bottle ask
 * in their head. `uk_reference`/`uk_floor`/`sell_price`/`buyer_price_gbp`/
 * `seller_price_gbp`/`gp` are already per-bottle figures from the engine
 * (this cellar's own lines are loose-bottle, pack_size 1 throughout — see
 * CLAUDE.md's own Justerini & Brooks note) — this file was multiplying by
 * quantity FIRST and showing only that, which is what buried the
 * per-bottle figure in the first place.
 *
 * The buyer-preview dialog is gone. It was always the wrong shape for the
 * thing actually sent to a client — a modal, not a document — and Doug
 * said so after asking to see the real document six times: "Keep the Desk
 * as the operator view... it was never the deliverable." The real
 * document is `/deals/{dealId}/offer` (decision 0034's `floor_saving_
 * claim`, read verbatim, never recomputed): this file only gets a
 * client-ready set of lines TO it, via the selected line ids and the
 * display rate in the query string.
 */

function gapPercent(floor, reference) {
  if (!floor || !reference) return null;
  const f = Number(floor), r = Number(reference);
  if (!f) return null;
  return Math.round(((r - f) / f) * 1000) / 10;
}

function gated(line) {
  return !!(line.pricing?.requires_acknowledgement && !line.pricing?.acknowledgement);
}

/** Evidence-quality and identity flags that gate (REVIEW_FLAGS in
 * app/core/flags.py), each mapped to a short human phrase — ONE_COMP and
 * WIDE_SPREAD-at-two-comps are handled separately in `reasonFor` because
 * they need the comp count/gap, not a fixed phrase. QUANTITY_SHORTFALL is
 * deliberately not here: it never gates on its own (REQUIRE_QUANTITY_COVER
 * is False), so it is only ever appended as context onto another reason. */
const BENCHMARK_FLAG_PHRASES = {
  DERIVED_FROM_CASE: "case divided",
  CONDITION_REVIEW: "condition flagged",
  STOCK_BASIS_UNCONFIRMED: "stock basis unconfirmed",
  NAME_REVIEW: "name needs confirming",
  FORMAT_REVIEW: "format needs confirming",
  COMP_EXCLUDED_VINTAGE_BAND: "a dear comp excluded",
  LOW_COMP_OUT_OF_BAND: "a cheap comp flagged",
};

/** Commercial flags (app/pricing/pricer.py) that also gate export
 * (EXPORT_GATE_FLAGS, app/db/repo.py) even when the benchmark itself is
 * READY with plenty of agreement -- a line can need a person for a
 * reason that has nothing to do with how many merchants were found. */
const PRICING_FLAG_PHRASES = {
  NEGATIVE_GP: "would lose money",
  SELL_ABOVE_UK_REFERENCE: "priced above market",
  SELL_AT_OR_ABOVE_UK_FLOOR: "not actually below market",
};

/** The reason a gated line needs a person, in the engine's own flags, in
 * plain words -- never a flag constant on screen, and never a badge with
 * no reason visible (Doug, 19 October 2026: "He should never have to
 * ask"). Doesn't decide whether a line gates -- `gated`, above, already
 * reads that straight from the server -- only explains a decision already
 * made, from the same flags the server used to make it. */
function reasonFor(line) {
  if (!gated(line)) return null;
  const b = line.benchmark, p = line.pricing;
  const bFlags = new Set(b?.flags || []);
  const pFlags = new Set(p?.flags || []);
  const parts = [];

  if (b?.state === "NO_MARKET") {
    parts.push("no merchant found");
  } else if (p.comp_count === 1) {
    parts.push("1 merchant");
  } else if (p.comp_count === 2 && bFlags.has("WIDE_SPREAD")) {
    const gap = gapPercent(p.uk_floor, p.uk_reference);
    parts.push(gap !== null ? `2 merchants, ${gap}% apart` : "2 merchants, far apart");
  }

  for (const [flag, phrase] of Object.entries(BENCHMARK_FLAG_PHRASES)) {
    if (bFlags.has(flag)) parts.push(phrase);
  }
  if (bFlags.has("QUANTITY_SHORTFALL")) parts.push("fewer bottles");
  for (const [flag, phrase] of Object.entries(PRICING_FLAG_PHRASES)) {
    if (pFlags.has(flag)) parts.push(phrase);
  }

  return parts.length ? parts.join(" · ") : "needs a look";
}

/** Per-bottle HK$ primary, GBP/bottle small, line total secondary and
 * smaller — same cell, every money column. `onClick` (optional) keeps the
 * Market column's existing evidence-toggle behaviour. */
function PriceCell({ perBottleGbp, quantity, hk, onClick }) {
  const inner = (
    <>
      <div className="pb">{hk(Number(perBottleGbp))}</div>
      <div className="pbgbp muted">£{Number(perBottleGbp).toFixed(2)} / btl</div>
      <div className="pbtot muted">{quantity} btl{quantity === 1 ? "" : "s"} · {hk(Number(perBottleGbp) * quantity)}</div>
    </>
  );
  if (onClick) return <button className="ev pcell" onClick={onClick}>{inner}</button>;
  return <div className="pcell">{inner}</div>;
}

const FILTERS = [
  ["all", "Everything"],
  ["ready", "Ready to send"],
  ["needs", "Needs you"],
];

export default function CellarDesk({ params }) {
  const { dealId } = use(params);
  const [deal, setDeal] = useState(null);
  const [wines, setWines] = useState(new Map());
  const [sel, setSel] = useState(new Set());
  const [open, setOpen] = useState(null);
  const [evidence, setEvidence] = useState({});
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("all");
  const [sortKey, setSortKey] = useState("mkt");
  const [sortDir, setSortDir] = useState(-1);
  const [fx, setFx] = useState("10.37");

  const load = useCallback(() => {
    api.get(`/deals/${dealId}`).then((d) => {
      setDeal(d);
      setSel((prev) => (prev.size ? prev : new Set(
        d.lines.filter((l) => l.pricing?.sell_price).map((l) => l.line_id))));
    }).catch((e) => setError(e.message));
    api.get("/wines").then((ws) => setWines(new Map(ws.map((w) => [w.wine_id, w]))))
      .catch(() => {});
  }, [dealId]);
  useEffect(load, [load]);

  async function toggleEvidence(lineId) {
    if (open === lineId) { setOpen(null); return; }
    setOpen(lineId);
    if (!evidence[lineId]) {
      try {
        const run = await api.get(`/lines/${lineId}/benchmark`);
        setEvidence((prev) => ({ ...prev, [lineId]: run }));
      } catch (e) {
        setEvidence((prev) => ({ ...prev, [lineId]: { error: e.message } }));
      }
    }
  }

  async function accept(lineId) {
    setBusy(lineId);
    setError(null);
    try {
      await api.post(`/lines/${lineId}/pricing/acknowledge`, { note: null });
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (!deal) return <p className="muted">{error || "Loading…"}</p>;

  const priced = deal.lines.filter((l) => l.pricing?.sell_price && l.pricing?.uk_reference);
  const rows = priced.filter((l) => {
    if (filter === "ready") return !gated(l);
    if (filter === "needs") return gated(l);
    return true;
  }).sort((a, b) => {
    const key = (l) => {
      if (sortKey === "wine") return wineLabel(l, wines).producer + wineLabel(l, wines).cuvee;
      if (sortKey === "bottles") return l.quantity;
      if (sortKey === "mkt") return Number(l.pricing.uk_reference) * l.quantity;
      if (sortKey === "ves") return Number(l.pricing.buyer_price_gbp ?? l.pricing.sell_price) * l.quantity;
      return 0;
    };
    const x = key(a), y = key(b);
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * sortDir;
  });

  const selected = priced.filter((l) => sel.has(l.line_id));
  const blocking = selected.filter(gated);
  const totalMkt = selected.reduce((s, l) => s + Number(l.pricing.uk_reference) * l.quantity, 0);
  const totalOffer = selected.reduce(
    (s, l) => s + Number(l.pricing.buyer_price_gbp ?? l.pricing.sell_price) * l.quantity, 0);
  const totalNet = selected.reduce(
    (s, l) => s + Number(l.pricing.seller_price_gbp ?? l.pricing.sell_price) * l.quantity, 0);
  const totalFee = selected.reduce((s, l) => s + Number(l.pricing.gp ?? 0) * l.quantity, 0);
  const totalBottles = selected.reduce((s, l) => s + l.quantity, 0);
  const hk = (gbp) => "HK$" + Math.round(gbp * Number(fx || 1)).toLocaleString("en-GB");
  const offerHref = `/deals/${dealId}/offer?lines=${[...sel].join(",")}&fx=${encodeURIComponent(fx)}`;

  function downloadCsv() {
    const header = "wine,vintage,bottles,market_gbp,offer_gbp,seller_nets_gbp,commission_gbp,merchants,gap_pct\n";
    const body = selected.map((l) => {
      const label = wineLabel(l, wines);
      const gap = gapPercent(l.pricing.uk_floor, l.pricing.uk_reference) ?? 0;
      return [
        `"${label.producer} ${label.cuvee}"`, label.vintage || l.vintage, l.quantity,
        (Number(l.pricing.uk_reference) * l.quantity).toFixed(2),
        (Number(l.pricing.buyer_price_gbp ?? l.pricing.sell_price) * l.quantity).toFixed(2),
        (Number(l.pricing.seller_price_gbp ?? l.pricing.sell_price) * l.quantity).toFixed(2),
        (Number(l.pricing.gp ?? 0) * l.quantity).toFixed(2),
        l.pricing.comp_count, gap,
      ].join(",");
    }).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([header + body], { type: "text/csv" }));
    a.download = `${deal.name.replace(/\W+/g, "-").toLowerCase()}-offer.csv`;
    a.click();
  }

  return (
    <>
      <p className="muted" style={{ marginBottom: 4 }}>
        <Link href="/">← Deals</Link>
      </p>
      <h1>Cellar Desk</h1>
      <p className="sub" style={{ marginTop: -8 }}>
        {deal.name} · <Link href={`/deals/${dealId}/lines`}>Pipeline details →</Link>
      </p>
      <p className="sub">
        {priced.length} priced line{priced.length === 1 ? "" : "s"} of {deal.lines.length} ·
        {" "}<strong>{sel.size}</strong> selected · display rate HK$
        <input className="fxinput" value={fx} onChange={(e) => setFx(e.target.value)} /> per £1
      </p>
      <p className="agency">
        Agency settlement (decision 0022): <strong>the buyer pays the seller directly</strong> and
        Doug invoices 8% of the sale as commission. VESSEL never holds the money.
        &ldquo;Seller nets&rdquo; is the offer price less that commission.
      </p>

      {error && <div className="notice bad">{error}</div>}

      {priced.length >= 10 && (
        <div className="bar">
          {FILTERS.map(([key, label]) => (
            <button key={key} className={`pill ${filter === key ? "on" : ""}`}
                    onClick={() => setFilter(key)}>{label}</button>
          ))}
        </div>
      )}

      <div className="card scroll">
        <table>
          <thead>
            <tr>
              <th style={{ width: 24 }}></th>
              <th onClick={() => sortBy("wine")} className="sortable">Wine</th>
              <th className="num sortable" onClick={() => sortBy("bottles")}>Btls</th>
              <th className="num sortable" onClick={() => sortBy("mkt")}>Market</th>
              <th className="num sortable" onClick={() => sortBy("ves")}>Offer price</th>
              <th className="num">Seller nets</th>
              <th className="num">Your 8%</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((line) => {
              const label = wineLabel(line, wines);
              const p = line.pricing;
              const isOpen = open === line.line_id;
              const isGated = gated(line);
              const checked = sel.has(line.line_id);
              return (
                <Fragment key={line.line_id}>
                  <tr className={checked ? "" : "off"}>
                    <td>
                      <input type="checkbox" checked={checked} onChange={() => {
                        setSel((prev) => {
                          const next = new Set(prev);
                          next.has(line.line_id) ? next.delete(line.line_id) : next.add(line.line_id);
                          return next;
                        });
                      }} />
                    </td>
                    <td>
                      <div className="w">{label.producer} <em>{label.cuvee}</em> {label.vintage}</div>
                      <div className="muted" style={{ fontSize: 12 }}>{line.raw_description}</div>
                    </td>
                    <td className="num">{line.quantity}</td>
                    <td className="num">
                      <PriceCell perBottleGbp={p.uk_reference} quantity={line.quantity} hk={hk}
                                 onClick={() => toggleEvidence(line.line_id)} />
                    </td>
                    <td className="num w">
                      <PriceCell perBottleGbp={p.buyer_price_gbp ?? p.sell_price} quantity={line.quantity} hk={hk} />
                    </td>
                    <td className="num">
                      <PriceCell perBottleGbp={p.seller_price_gbp ?? p.sell_price} quantity={line.quantity} hk={hk} />
                    </td>
                    <td className="num">
                      <PriceCell perBottleGbp={p.gp ?? 0} quantity={line.quantity} hk={hk} />
                    </td>
                    <td>
                      <span className={`tag ${isGated ? "stop" : "ready"}`}>
                        {isGated ? reasonFor(line) : "Ready"}
                      </span>
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="evrow">
                      <td colSpan={8}>
                        {!evidence[line.line_id] && <span className="muted">Loading…</span>}
                        {evidence[line.line_id]?.error && (
                          <span className="muted">Could not load evidence: {evidence[line.line_id].error}</span>
                        )}
                        {evidence[line.line_id] && !evidence[line.line_id].error && (
                          <>
                            <strong>Read {new Date(evidence[line.line_id].as_of).toLocaleDateString("en-GB")}, UK In Bond, per bottle</strong>
                            {p.comp_count >= 2 && (() => {
                              const gap = gapPercent(p.uk_floor, p.uk_reference);
                              const gapText = gap !== null ? `, ${gap}% apart` : "";
                              // Decision 0033: with exactly two comps the spread is not
                              // merely informational — Reference is the dearer of the
                              // two, so a wide enough gap gates on its own (WIDE_SPREAD)
                              // and, win or lose that gate, can still make the "below
                              // market" claim itself false (SELL_AT_OR_ABOVE_UK_FLOOR).
                              // With three or more it stays exactly what it always was.
                              return (
                                <div className="muted" style={{ fontSize: 12.5, margin: "2px 0 6px" }}>
                                  {p.comp_count} merchants{gapText} — {p.comp_count === 2
                                    ? (isGated
                                        ? "exactly two, and the spread here is itself why this line needs you."
                                        : "exactly two, close enough that this line is still ready to send.")
                                    : "informational; three or more merchants is enough to send regardless of spread."}
                                </div>
                              );
                            })()}
                            <table>
                              <tbody>
                                {evidence[line.line_id].comps
                                  .filter((c) => c.role === "merchant_best")
                                  .map((c) => (
                                    <tr key={c.merchant_offer_id}>
                                      <td className="sub2">{c.merchant}</td>
                                      <td className="sub2 num"><strong>{money(c.price)}</strong></td>
                                    </tr>
                                  ))}
                              </tbody>
                            </table>
                            {isGated && (
                              <div className="gate">
                                <strong>{reasonFor(line)}.</strong>{" "}
                                This line is REVIEW (invariant 12) until a named operator
                                looks at it — it cannot reach a buyer until then.
                                <button className="accept" disabled={busy === line.line_id}
                                        onClick={() => accept(line.line_id)}>
                                  {busy === line.line_id ? "Accepting…" : "Accept this price"}
                                </button>
                              </div>
                            )}
                          </>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="foot">
        <dl>
          <div><dt>Selected</dt><dd>{sel.size} lines · {totalBottles} btls</dd></div>
          <div><dt>Market value</dt><dd>{hk(totalMkt)} <span className="gbp">£{Math.round(totalMkt).toLocaleString()}</span></dd></div>
          <div><dt>Offer price</dt><dd>{hk(totalOffer)}</dd></div>
          <div><dt>Seller nets</dt><dd>{hk(totalNet)}</dd></div>
          <div><dt>Your commission, invoiced</dt><dd className="big">{hk(totalFee)}</dd></div>
        </dl>
        {blocking.length > 0 && (
          <div className="warn">
            <strong>{blocking.length} selected line{blocking.length > 1 ? "s" : ""} rest{blocking.length > 1 ? "" : "s"} on
            one merchant and {blocking.length > 1 ? "have" : "has"} not been accepted.</strong>{" "}
            Nothing goes to a buyer until {blocking.length > 1 ? "they're" : "it's"} looked at —
            click the market price to see the evidence and accept.
          </div>
        )}
        <div className="act">
          <Link href={blocking.length > 0 ? "#" : offerHref}
                className={`go ${blocking.length > 0 ? "disabled" : ""}`}
                aria-disabled={blocking.length > 0}
                onClick={(e) => { if (blocking.length > 0) e.preventDefault(); }}>
            Prepare client offer document →
          </Link>
          <button className="quiet" disabled={blocking.length > 0} onClick={downloadCsv}>
            Download as CSV
          </button>
        </div>
      </div>
    </>
  );

  function sortBy(key) {
    setSortDir(sortKey === key ? -sortDir : -1);
    setSortKey(key);
  }
}
