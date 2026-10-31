"use client";

import { useEffect, useState } from "react";
import { api, BASE } from "../../lib/api";
import { LOADING, ok, failed, fetchInto } from "../../lib/fetchState";
import { adminHandoff, quotePrice, supplierHandoff, tombstone } from "../../lib/pocketMessages";
import {
  ceilToStep, fmt, formatBp, fromQuote, inputText, markupBp, parsePounds, quoteLabel,
  splitStatedPrice, stepQuote, toMoney, toPence, toQuote, vsMarketBp,
} from "../../lib/vesselSell";

/** VESSEL Pocket, build brief Phase 1b step 2: Screen 1 (NEW) and Screen 2
 * (CANDIDATE). Capture first, structure afterwards — the only thing this
 * page's first screen asks for is the raw material itself.
 *
 * `create` is the one three-state object for the current candidate: `ok`
 * holds `{offer, proposal}` together, so there is no window where the
 * screen has a proposal but no idea which offer it belongs to, or the
 * reverse. A provider outage renders through the same `error` state
 * every other screen in this app uses for "couldn't check" (decision
 * 0040) — never a half-built candidate that looks like a clean parse.
 */
export default function PocketPage() {
  const [wines, setWines] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [pasteText, setPasteText] = useState("");
  const [create, setCreate] = useState(ok(null));
  // Only ever set when a create/reparse call fails WITH an id attached
  // (app/api/inbound.py structures the 502 that way on purpose) — the one
  // thing that lets this screen retry against the row that actually
  // captured the raw text, instead of resubmitting it as a new one.
  const [retryId, setRetryId] = useState(null);
  const EMPTY_CONFIRM_FORM = { wine_id: "", vintage: "", bottle_ml: "", pack_size: "",
    quantity: "", packaging: "", bond_status: "", stock_location: "",
    asking_price: "", asking_currency: "", asking_basis: "",
    want_list_ack: false, supplier_id: "" };
  const [confirmForm, setConfirmForm] = useState(EMPTY_CONFIRM_FORM);
  // Which fields in confirmForm came from the message versus are Doug's
  // own entry -- fixed at the moment the proposal arrives (Doug's own
  // correction, 29 Oct 2026): "never retype something the parser just
  // read correctly" applies to a STATED field; a SILENT one stays blank
  // with a one-tap default, and the two must look different on screen.
  const [stated, setStated] = useState({});
  // Set only when the commercial unit is genuinely ambiguous ("6 x ...
  // OWC") -- the literal bottle count the fork resolves between one case
  // of that many, or that many loose bottles. Never both at once.
  const [commercialFork, setCommercialFork] = useState(null);
  const [confirmState, setConfirmState] = useState(ok(null));
  // Screen 2's own filtered wine list (the proposed producer's wines, or
  // that plus its known fork, never the full 234) — fetched fresh for
  // each candidate. showAllWines is the deliberate escape hatch for when
  // the proposed producer is wrong.
  const [candidateGroups, setCandidateGroups] = useState(LOADING);
  const [showAllWines, setShowAllWines] = useState(false);
  // A trade reopened from the Offers out list — straight to its pricing
  // screen, since its identity is already confirmed.
  const [openOfferId, setOpenOfferId] = useState(null);

  useEffect(() => { api.get("/wines").then(setWines).catch(() => {}); }, []);
  const refreshSuppliers = () => api.get("/suppliers").then(setSuppliers).catch(() => {});
  useEffect(() => { refreshSuppliers(); }, []);

  const candidate = create.status === "ok" ? create.data : null;
  const offer = candidate?.offer;
  const proposal = candidate?.proposal;
  const matchedSupplierIds = candidate?.matched_supplier_ids || [];

  function startOver() {
    setCreate(ok(null));
    setRetryId(null);
    setPasteText("");
    setConfirmForm(EMPTY_CONFIRM_FORM);
    setStated({});
    setCommercialFork(null);
    setConfirmState(ok(null));
    setCandidateGroups(LOADING);
    setShowAllWines(false);
    setOpenOfferId(null);
  }

  // wine_id is never prefilled regardless of what follows: decision
  // 0038's gate means picking the actual wine is always a deliberate,
  // separate act. Everything else here follows one rule: a field the
  // message stated is filled in and marked "from message"; a field it
  // was silent on stays blank, marked "your entry" -- prefill-versus-
  // blank was never the point, stated-versus-silent is.
  useEffect(() => {
    if (proposal) {
      // pack_size null + total_bottles set = the commercial-unit fork
      // (decision 0028): present both readings as one-tap options,
      // choose neither automatically. pack_size set = unambiguous, both
      // pack_size and quantity come from the message together.
      const unambiguousUnit = proposal.pack_size != null;
      setCommercialFork(!unambiguousUnit && proposal.total_bottles != null
        ? proposal.total_bottles : null);
      setStated({
        vintage: proposal.vintage != null, bottle_ml: proposal.bottle_ml != null,
        pack_size: unambiguousUnit, quantity: unambiguousUnit,
        packaging: proposal.packaging != null, bond_status: proposal.bond_status != null,
        stock_location: proposal.stock_location != null,
        asking_price: proposal.asking_price != null, asking_basis: proposal.asking_basis != null,
      });
      const statedPrice = splitStatedPrice(proposal.asking_price);
      setConfirmForm((f) => ({
        ...f,
        vintage: proposal.vintage != null ? String(proposal.vintage) : "",
        bottle_ml: proposal.bottle_ml != null ? String(proposal.bottle_ml) : "",
        pack_size: unambiguousUnit ? String(proposal.pack_size) : "",
        quantity: unambiguousUnit ? String(proposal.quantity) : "",
        packaging: proposal.packaging || "",
        bond_status: proposal.bond_status || "",
        stock_location: proposal.stock_location || "",
        // The AI reports the literal figure as written, commas and all
        // ("2,800") -- stripped here so the field holds a value the
        // Money type can actually parse without Doug having to do it;
        // this is reformatting, not interpreting the figure.
        asking_price: statedPrice.amount,
        asking_currency: proposal.asking_currency || statedPrice.currency || "",
        asking_basis: proposal.asking_basis || "",
      }));
      setShowAllWines(false);
      const params = new URLSearchParams();
      if (proposal.producer) params.set("producer", proposal.producer);
      if (proposal.cuvee) params.set("cuvee", proposal.cuvee);
      fetchInto(setCandidateGroups, api.get(`/inbound-offers/candidate-wines?${params}`));
    }
  }, [proposal]);

  async function create_(body) {
    setCreate(LOADING);
    setRetryId(null);
    try {
      const data = await api.post("/inbound-offers", body);
      setCreate(ok(data));
    } catch (e) {
      setCreate(failed(e));
      setRetryId(e.detail?.inbound_offer_id || null);
    }
  }

  function submitPaste(event) {
    event.preventDefault();
    if (!pasteText.trim()) return;
    create_({ channel: "paste", raw_body: pasteText });
  }

  function submitFile(channel, file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const base64 = String(reader.result).split(",")[1];
      create_({ channel, raw_media_base64: base64, media_mime: file.type || "application/octet-stream" });
    };
    reader.readAsDataURL(file);
  }

  async function retry() {
    const id = retryId || offer?.inbound_offer_id;
    if (!id) return;
    setCreate(LOADING);
    setRetryId(null);
    try {
      const data = await api.post(`/inbound-offers/${id}/reparse`);
      setCreate(ok(data));
    } catch (e) {
      setCreate(failed(e));
      setRetryId(e.detail?.inbound_offer_id || id);
    }
  }

  async function confirmIdentity(event) {
    event.preventDefault();
    setConfirmState(LOADING);
    try {
      const updated = await api.post(`/inbound-offers/${offer.inbound_offer_id}/confirm-identity`, {
        wine_id: confirmForm.wine_id, vintage: Number(confirmForm.vintage),
        bottle_ml: Number(confirmForm.bottle_ml), pack_size: Number(confirmForm.pack_size),
        quantity: Number(confirmForm.quantity),
        packaging: confirmForm.packaging || null, bond_status: confirmForm.bond_status || null,
        stock_location: confirmForm.stock_location || null,
        asking_price: confirmForm.asking_price || null,
        asking_currency: confirmForm.asking_currency || null,
        asking_basis: confirmForm.asking_basis || null,
        want_list_ack: confirmForm.want_list_ack, supplier_id: confirmForm.supplier_id,
      });
      refreshSuppliers(); // most-recently-used ordering just changed
      setConfirmState(ok(updated));
      setCreate(ok({ ...candidate, offer: updated }));
    } catch (e) {
      setConfirmState(failed(e));
    }
  }

  const selectedWine = wines.find((w) => w.wine_id === confirmForm.wine_id);
  const needsWantListAck = !!selectedWine?.want_list;

  return (
    <div className="card">
      <h1 style={{ marginTop: 0 }}>Pocket</h1>

      {openOfferId ? (
        <PricingScreen offerId={openOfferId} onStartOver={startOver} />
      ) : !candidate ? (
        <>
          <NewScreen pasteText={pasteText} setPasteText={setPasteText} onPaste={submitPaste}
                    onPhoto={(f) => submitFile("photo", f)} onUpload={(f) => submitFile("upload", f)}
                    create={create} retryId={retryId} onRetry={retry} />
          <TradesList onOpen={setOpenOfferId} />
        </>
      ) : (
        <CandidateScreen offer={offer} proposal={proposal} wines={wines}
                         candidateGroups={candidateGroups} showAllWines={showAllWines}
                         setShowAllWines={setShowAllWines}
                         suppliers={suppliers} matchedSupplierIds={matchedSupplierIds}
                         onSupplierCreated={(sup) => { setSuppliers([sup, ...suppliers]);
                                                       setConfirmForm((f) => ({ ...f, supplier_id: sup.supplier_id })); }}
                         confirmForm={confirmForm} setConfirmForm={setConfirmForm}
                         stated={stated} setStated={setStated} commercialFork={commercialFork}
                         needsWantListAck={needsWantListAck} confirmState={confirmState}
                         onConfirm={confirmIdentity} onReparse={retry} onStartOver={startOver}
                         reparsing={create.status === "loading"} />
      )}
    </div>
  );
}

function NewScreen({ pasteText, setPasteText, onPaste, onPhoto, onUpload, create, retryId, onRetry }) {
  const loading = create.status === "loading";
  return (
    <>
      <p className="muted">Paste, photo, or upload — nothing else is required to start.</p>

      {create.status === "error" && (
        <div className="notice bad">
          Couldn&apos;t read this ({create.error}).
          {retryId && (
            <>{" "}<button type="button" className="small" onClick={onRetry} disabled={loading}>
              {loading ? "Retrying…" : "Retry"}
            </button></>
          )}
        </div>
      )}

      <form onSubmit={onPaste} className="row" style={{ alignItems: "flex-start" }}>
        <div className="grow">
          <label htmlFor="paste">Paste</label>
          <textarea id="paste" rows={4} placeholder="Paste the message, exactly as it arrived"
                    value={pasteText} onChange={(e) => setPasteText(e.target.value)} />
        </div>
        <button type="submit" disabled={loading || !pasteText.trim()}>
          {loading ? "Reading…" : "Paste"}
        </button>
      </form>

      <div className="row" style={{ marginTop: 10 }}>
        <label className="small" style={{ cursor: "pointer" }}>
          <input type="file" accept="image/*" capture="environment" style={{ display: "none" }}
                 disabled={loading}
                 onChange={(e) => onPhoto(e.target.files?.[0])} />
          <span className="tag">Photo</span>
        </label>
        <label className="small" style={{ cursor: "pointer" }}>
          <input type="file" style={{ display: "none" }} disabled={loading}
                 onChange={(e) => onUpload(e.target.files?.[0])} />
          <span className="tag">Upload</span>
        </label>
        {loading && <span className="muted">Reading…</span>}
      </div>
    </>
  );
}

/** "from message" versus "your entry" -- the visual distinction Doug's
 * own correction asked for. Omitted entirely before a value exists to
 * tag (e.g. the fork hasn't been resolved yet), rather than guessing. */
function StatedTag({ stated }) {
  return (
    <span className={stated ? "tag ready" : "tag plain"}
          style={{ marginLeft: 6, fontSize: 10, verticalAlign: "middle" }}>
      {stated ? "from message" : "your entry"}
    </span>
  );
}

function CandidateScreen({ offer, proposal, wines, candidateGroups, showAllWines, setShowAllWines,
                          suppliers, matchedSupplierIds, onSupplierCreated,
                          confirmForm, setConfirmForm, stated, setStated, commercialFork,
                          needsWantListAck,
                          confirmState, onConfirm, onReparse, onStartOver, reparsing }) {
  const confirmed = !!offer.identity_confirmed_at;

  if (offer.category === "whisky") {
    return (
      <div className="notice">
        Whisky — not priced by VESSEL. Captured for your records.
        <div style={{ marginTop: 10 }}>
          <button type="button" onClick={onStartOver}>Start over</button>
        </div>
      </div>
    );
  }

  if (offer.parse_state === "unparseable") {
    return (
      <div className="notice bad">
        Couldn&apos;t identify a wine or whisky offer here
        {proposal?.reasoning ? `: ${proposal.reasoning}` : "."}
        <div style={{ marginTop: 10 }}>
          <button type="button" className="small" onClick={onReparse} disabled={reparsing}>
            {reparsing ? "Retrying…" : "Retry"}
          </button>{" "}
          <button type="button" className="small" onClick={onStartOver}>Start over</button>
        </div>
      </div>
    );
  }

  return (
    <>
      {offer.has_media && (
        // Screen 2's own rule: show the photo next to the proposed identity,
        // so confirmation happens against the label, not the AI's prose.
        <img src={`${BASE}/inbound-offers/${offer.inbound_offer_id}/media`}
             alt="captured" style={{ maxWidth: "100%", maxHeight: 320, borderRadius: 8, marginBottom: 12 }} />
      )}

      <div className="card" style={{ background: "var(--bg)" }}>
        <strong>{proposal.producer || "(producer not stated)"}</strong> · {proposal.cuvee || "(cuvée not stated)"}
        {proposal.vintage ? ` · ${proposal.vintage}` : ""}
        <div className="muted" style={{ marginTop: 4 }}>
          {proposal.total_bottles
            ? `${proposal.total_bottles} bottles, case or loose unclear`
            : proposal.quantity ? `${proposal.quantity} × ` : ""}
          {proposal.bottle_ml ? `${proposal.bottle_ml}ml` : "size: unknown"}
          {" · "}{proposal.bond_status || "bond status: unknown"}
          {" · "}{proposal.stock_location || "location: unknown"}
          {" · packaging: "}{proposal.packaging || "unknown"}
        </div>
        {proposal.asking_price && (
          <div style={{ marginTop: 4 }}>
            Supplier price: {proposal.asking_price} {proposal.asking_currency || ""}
            {proposal.asking_basis ? ` (${proposal.asking_basis.replace("_", " ")})`
              : " — no basis stated"}
          </div>
        )}
        {/* Accurate, but the longest text on the card and the least
           important thing on it (Doug's own framing) -- demoted below
           every fact above it, smaller and lighter than "muted" itself. */}
        <div className="muted" style={{ fontSize: 11, marginTop: 8, opacity: 0.75 }}>
          {proposal.reasoning}
        </div>
      </div>

      {!confirmed ? (
        <form onSubmit={onConfirm} className="card" style={{ marginTop: 12 }}>
          <h2 style={{ marginTop: 0 }}>Confirm identity</h2>
          <p className="muted" style={{ fontSize: 13 }}>
            A proposal, never an identity — pick the exact wine yourself.
          </p>
          <div className="row">
            <div className="grow">
              <div className="row" style={{ alignItems: "baseline", gap: 8 }}>
                <label htmlFor="pwine" style={{ marginBottom: 0 }}>Wine</label>
                <button type="button" className="small quiet"
                        onClick={() => setShowAllWines(!showAllWines)}>
                  {showAllWines ? "Show proposed producer only" : "Show all wines"}
                </button>
              </div>
              <WineSelect wines={wines} candidateGroups={candidateGroups} showAllWines={showAllWines}
                         value={confirmForm.wine_id}
                         onChange={(wineId) => setConfirmForm({ ...confirmForm, wine_id: wineId,
                                                                want_list_ack: false })} />
            </div>
            <div style={{ width: 110 }}>
              <label htmlFor="pvintage">Vintage <StatedTag stated={stated.vintage} /></label>
              <input id="pvintage" inputMode="numeric" required value={confirmForm.vintage}
                     onChange={(e) => setConfirmForm({ ...confirmForm, vintage: e.target.value })} />
            </div>
            <div style={{ width: 130 }}>
              <label htmlFor="pml">Bottle ml <StatedTag stated={stated.bottle_ml} /></label>
              <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                <input id="pml" inputMode="numeric" value={confirmForm.bottle_ml}
                       onChange={(e) => setConfirmForm({ ...confirmForm, bottle_ml: e.target.value })} />
                {/* A tap-to-fill convenience for the silent case only --
                   never an auto-fill: the value has to be Doug's own
                   assertion, not the system's inference, the day a
                   magnum arrives. */}
                {!stated.bottle_ml && (
                  <button type="button" className="small quiet"
                          onClick={() => setConfirmForm({ ...confirmForm, bottle_ml: "750" })}>
                    750
                  </button>
                )}
              </div>
            </div>
            {!commercialFork && (
              <>
                <div style={{ width: 90 }}>
                  <label htmlFor="ppack">Pack <StatedTag stated={stated.pack_size} /></label>
                  <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                    <input id="ppack" inputMode="numeric" value={confirmForm.pack_size}
                           onChange={(e) => setConfirmForm({ ...confirmForm, pack_size: e.target.value })} />
                    {!stated.pack_size && (
                      <button type="button" className="small quiet"
                              onClick={() => setConfirmForm({ ...confirmForm, pack_size: "1" })}>
                        1
                      </button>
                    )}
                  </div>
                </div>
                <div style={{ width: 90 }}>
                  <label htmlFor="pqty">Quantity <StatedTag stated={stated.quantity} /></label>
                  <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                    <input id="pqty" inputMode="numeric" value={confirmForm.quantity}
                           onChange={(e) => setConfirmForm({ ...confirmForm, quantity: e.target.value })} />
                    {!stated.quantity && (
                      <button type="button" className="small quiet"
                              onClick={() => setConfirmForm({ ...confirmForm, quantity: "1" })}>
                        1
                      </button>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>

          {commercialFork && (
            // The commercial unit is a FORK, not a guess (decision 0028):
            // "6 x ... OWC" reads as one case of six or six loose
            // bottles, and a case priced against single-bottle comps is
            // simply wrong. Present both, pick neither automatically --
            // same discipline as the Leroy/want-list fork.
            <div className="notice" style={{ marginTop: 10 }}>
              <div style={{ marginBottom: 6 }}>
                {commercialFork} bottles stated — case or loose is not clear. Which is it?
              </div>
              <div className="row" style={{ gap: 8 }}>
                <button type="button"
                        className={confirmForm.pack_size === String(commercialFork) ? "small" : "small quiet"}
                        onClick={() => { setConfirmForm({ ...confirmForm, pack_size: String(commercialFork), quantity: "1" });
                                        setStated((s) => ({ ...s, pack_size: false, quantity: false })); }}>
                  1 case of {commercialFork}
                </button>
                <button type="button"
                        className={confirmForm.pack_size === "1" && confirmForm.quantity === String(commercialFork) ? "small" : "small quiet"}
                        onClick={() => { setConfirmForm({ ...confirmForm, pack_size: "1", quantity: String(commercialFork) });
                                        setStated((s) => ({ ...s, pack_size: false, quantity: false })); }}>
                  {commercialFork} loose bottles
                </button>
              </div>
            </div>
          )}

          <div className="row" style={{ marginTop: 10 }}>
            <div className="grow">
              <label htmlFor="ppackaging">Packaging <StatedTag stated={stated.packaging} /></label>
              <input id="ppackaging" value={confirmForm.packaging} placeholder="e.g. OWC"
                     onChange={(e) => setConfirmForm({ ...confirmForm, packaging: e.target.value })} />
            </div>
            <div className="grow">
              <label htmlFor="pbond">Bond status <StatedTag stated={stated.bond_status} /></label>
              <input id="pbond" value={confirmForm.bond_status} placeholder="e.g. UK In Bond"
                     onChange={(e) => setConfirmForm({ ...confirmForm, bond_status: e.target.value })} />
            </div>
            <div className="grow">
              <label htmlFor="ploc">Location <StatedTag stated={stated.stock_location} /></label>
              <input id="ploc" value={confirmForm.stock_location} placeholder="e.g. LCB"
                     onChange={(e) => setConfirmForm({ ...confirmForm, stock_location: e.target.value })} />
            </div>
          </div>

          <div className="row" style={{ marginTop: 10 }}>
            <div style={{ width: 130 }}>
              <label htmlFor="pask">Supplier price <StatedTag stated={stated.asking_price} /></label>
              <input id="pask" inputMode="decimal" value={confirmForm.asking_price}
                     onChange={(e) => setConfirmForm({ ...confirmForm, asking_price: e.target.value })} />
            </div>
            <div style={{ width: 90 }}>
              <label htmlFor="pcur">Currency</label>
              <input id="pcur" value={confirmForm.asking_currency}
                     onChange={(e) => setConfirmForm({ ...confirmForm, asking_currency: e.target.value.toUpperCase() })} />
            </div>
            <div className="grow">
              <label htmlFor="pbasis">Basis <StatedTag stated={stated.asking_basis} /></label>
              <select id="pbasis" value={confirmForm.asking_basis}
                      onChange={(e) => setConfirmForm({ ...confirmForm, asking_basis: e.target.value })}>
                <option value="">—</option>
                <option value="per_bottle">Per bottle</option>
                <option value="per_case">Per case</option>
                <option value="total">Total</option>
              </select>
            </div>
          </div>
          {askBasisMissing(confirmForm) && (
            // A price with no basis on a multi-bottle line is ambiguous
            // by exactly the multiple the commercial unit would convert
            // it by -- blocking here too, not only server-side.
            <div className="notice bad" style={{ marginTop: 8, fontSize: 13 }}>
              A price on more than one bottle needs a basis (per bottle, per case, or total) —
              that figure is ambiguous by exactly the multiple it would otherwise convert by.
            </div>
          )}

          <SupplierPicker suppliers={suppliers} matchedSupplierIds={matchedSupplierIds}
                         value={confirmForm.supplier_id}
                         onChange={(id) => setConfirmForm({ ...confirmForm, supplier_id: id })}
                         onCreated={onSupplierCreated} />

          {needsWantListAck && (
            // THE PHOTO GATE, decision 0038: no confidence score anywhere
            // overrides this. Unticked by construction on every wine change.
            <div className="notice bad" style={{ marginTop: 10 }}>
              <label style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                <input type="checkbox" checked={confirmForm.want_list_ack}
                       onChange={(e) => setConfirmForm({ ...confirmForm, want_list_ack: e.target.checked })} />
                <span>
                  <strong>{selectedWineName(wines, confirmForm.wine_id)}</strong> is on the client
                  want list — easily confused with a cheaper namesake. I have checked this against
                  {offer.has_media ? " the photo" : " the source"} myself.
                </span>
              </label>
            </div>
          )}

          {confirmState.status === "error" && (
            <div className="notice bad" style={{ marginTop: 10 }}>{confirmState.error}</div>
          )}

          <div style={{ marginTop: 12 }}>
            <button type="submit"
                    disabled={confirmState.status === "loading" || !confirmForm.wine_id
                             || !confirmForm.bottle_ml || !confirmForm.pack_size
                             || !confirmForm.quantity || !confirmForm.supplier_id
                             || askBasisMissing(confirmForm)
                             || (needsWantListAck && !confirmForm.want_list_ack)}>
              {confirmState.status === "loading" ? "Confirming…" : "Confirm identity"}
            </button>
          </div>
        </form>
      ) : (
        <>
          <div className="notice good" style={{ marginTop: 12 }}>
            Identity confirmed by {offer.identity_confirmed_by?.display_name}.
            {offer.supplier_id && (
              <> From {suppliers.find((sp) => sp.supplier_id === offer.supplier_id)?.name || "—"}.</>
            )}
          </div>
          <PricingScreen offerId={offer.inbound_offer_id} onStartOver={onStartOver} />
        </>
      )}
    </>
  );
}

/** speed-and-cost-plan.md's "Collect now", kept deliberately small: one
 * wine, synchronous, every targeted adapter that already has a search
 * key for its producer. Lists exactly what each merchant returned —
 * 'ok' (found something, or looked and found nothing — still a real,
 * checked answer), 'failed' (couldn't look, the error itself shown),
 * or 'skipped' (never attempted, with the reason) — decision 0004's
 * own three states, surfaced here rather than collapsed into one
 * generic "done". Not the pre-fetch, not a queue: this is the proof
 * slice, before any of that is built. */
function CollectNowPanel({ collectNow, onCollectNow }) {
  const loading = collectNow.status === "loading";
  return (
    <div style={{ marginTop: 10 }}>
      <button type="button" className="small" onClick={onCollectNow} disabled={loading}>
        {loading ? "Collecting…" : "Collect now"}
      </button>
      {collectNow.status === "error" && (
        <p className="notice bad" style={{ marginTop: 8, fontSize: 13 }}>
          Couldn&apos;t collect ({collectNow.error}).
        </p>
      )}
      {collectNow.status === "ok" && collectNow.data && (
        <table style={{ marginTop: 8 }}>
          <tbody>
            {collectNow.data.map((r) => (
              <tr key={r.merchant_id}>
                <td className="muted">{r.merchant_id}</td>
                <td>
                  {r.outcome === "ok" && (
                    <span className="tag ready">
                      {r.offers_written} written{r.offers_rejected ? `, ${r.offers_rejected} rejected` : ""}
                    </span>
                  )}
                  {r.outcome === "failed" && <span className="tag stop">{r.error}</span>}
                  {r.outcome === "skipped" && <span className="tag plain">{r.reason}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function selectedWineName(wines, wineId) {
  const w = wines.find((x) => x.wine_id === wineId);
  return w ? `${w.producer} — ${w.cuvee}` : "";
}

/** Mirrors app/api/inbound.py's own server-side check exactly, so this
 * blocks in the UI before ever reaching the 422: a price with no basis
 * is ambiguous by exactly the multiple the commercial unit would
 * convert it by, on any line of more than one bottle. */
function askBasisMissing(form) {
  const units = Number(form.pack_size) * Number(form.quantity);
  return !!form.asking_price && !form.asking_basis && units > 1;
}

/** supplier-attribution-spec.md: a chip row, not a dropdown — 8-10
 * suppliers fit a phone as one-tap chips, most-recently-used first
 * (the order `GET /suppliers` already returns). Nothing pre-selected,
 * even when `matchedSupplierIds` highlights one or two: Doug still taps,
 * exactly as with the wine list. The AI never touches this -- the
 * highlight comes from a deterministic alias match against raw_body,
 * computed server-side and handed back once, never from the model. */
function SupplierPicker({ suppliers, matchedSupplierIds, value, onChange, onCreated }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submitNew(event) {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const sup = await api.post("/suppliers", { name: name.trim(), phone: phone.trim() || null });
      onCreated(sup);
      setAdding(false);
      setName("");
      setPhone("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ marginTop: 10 }}>
      <label style={{ marginBottom: 6 }}>Supplier — who this came from</label>
      <div className="row" style={{ gap: 8 }}>
        {suppliers.map((sp) => {
          const selected = value === sp.supplier_id;
          const matched = matchedSupplierIds.includes(sp.supplier_id);
          return (
            <button key={sp.supplier_id} type="button"
                    className={selected ? "small" : "small quiet"}
                    style={matched && !selected ? { borderColor: "var(--ocean)" } : undefined}
                    onClick={() => onChange(selected ? "" : sp.supplier_id)}>
              {sp.name}
            </button>
          );
        })}
        <button type="button" className="small quiet" onClick={() => setAdding(!adding)}>
          + new supplier
        </button>
      </div>

      {adding && (
        // Not a <form>: this sits inside the confirm-identity form, and a
        // nested form's Add submitted the outer one natively — reloading
        // the page and losing the capture.
        <div className="row" style={{ marginTop: 8, alignItems: "flex-end" }}>
          <div className="grow">
            <label htmlFor="sup_name">Name</label>
            <input id="sup_name" required value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submitNew(e); }} />
          </div>
          <div className="grow">
            <label htmlFor="sup_phone">Phone</label>
            <input id="sup_phone" value={phone} onChange={(e) => setPhone(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submitNew(e); }} />
          </div>
          <button type="button" className="small" onClick={submitNew} disabled={busy || !name.trim()}>
            {busy ? "Adding…" : "Add"}
          </button>
        </div>
      )}
      {error && <p className="notice bad" style={{ fontSize: 13 }}>{error}</p>}
    </div>
  );
}

/** Screen 2's own filtered list: the proposed producer's wines only,
 * closest cuvée first, grouped by producer so an always_review fork
 * (bare "Leroy") is visible as two groups in the list itself, not only
 * in the warning text. 234 unfiltered options trains an operator to
 * grab the first plausible row, which undermines the want-list
 * acknowledgement rather than reinforcing it -- so this is the default,
 * and "show all wines" is the explicit escape hatch, never silent. */
function WineSelect({ wines, candidateGroups, showAllWines, value, onChange }) {
  const groups = candidateGroups.status === "ok" ? candidateGroups.data : [];
  const hasFilteredGroups = groups.length > 0 && groups.some((g) => g.wines.length > 0);

  // Never the full register by default while matching is unfinished or
  // failed: a tap in that window could pick a materially wrong wine. Only
  // the explicit "Show all wines" reaches it then.
  if (!showAllWines && candidateGroups.status !== "ok") {
    return (
      <select id="pwine" required disabled value="">
        <option value="">
          {candidateGroups.status === "loading" ? "Matching wines…"
            : "Couldn't match wines — use Show all wines"}
        </option>
      </select>
    );
  }

  if (showAllWines || !hasFilteredGroups) {
    return (
      <select id="pwine" required value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {wines.map((w) => (
          <option key={w.wine_id} value={w.wine_id}>
            {w.producer} — {w.cuvee}{w.want_list ? " (want list)" : ""}
          </option>
        ))}
      </select>
    );
  }

  return (
    <select id="pwine" required value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">—</option>
      {groups.map((g) => (
        <optgroup key={g.producer} label={g.is_fork_alternate ? `${g.producer} (not on the want list)` : g.producer}>
          {g.wines.length === 0 ? (
            <option value="__none__" disabled>(none registered)</option>
          ) : g.wines.map((w) => (
            <option key={w.wine_id} value={w.wine_id}>{w.cuvee}</option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

function wineTitle(v) {
  return [v.producer, v.cuvee, v.vintage === 1000 ? null : v.vintage].filter(Boolean).join(" ");
}

function shortDate(iso) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function monthYear(iso) {
  return new Date(iso).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
}

/** Offers out and confirmed trades, newest first — the way back to a trade
 * when the buyer replies hours later. */
function TradesList({ onOpen }) {
  const [trades, setTrades] = useState(LOADING);
  useEffect(() => { fetchInto(setTrades, api.get("/pocket/trades")); }, []);
  if (trades.status === "loading") return null;
  if (trades.status === "error") {
    return <p className="notice bad" style={{ marginTop: 16 }}>Couldn&apos;t load your offers ({trades.error}).</p>;
  }
  if (!trades.data.length) return null;
  const label = { OFFERED: "Offer out", CONFIRMED: "Confirmed", COMPLETE: "Complete" };
  return (
    <div style={{ marginTop: 20 }}>
      <h2 style={{ marginTop: 0 }}>Offers</h2>
      {trades.data.map((t) => (
        <button key={t.inbound_offer_id} type="button" className="pocket-trade"
                onClick={() => onOpen(t.inbound_offer_id)}>
          <span className="grow">
            <strong>{t.wine_name}</strong>
            <span className="muted"> · {t.quantity} × {t.pack_size > 1 ? `${t.pack_size} × ` : ""}{t.bottle_ml / 10}cl</span>
            <span className="muted" style={{ display: "block", fontSize: 13 }}>
              {quotePrice(t.vessel_sell, t.quote_unit, t.pack_size, "GBP", { whole: true })}
              {t.buyer_name ? ` · ${t.buyer_name}` : ""}{` · ${shortDate(t.priced_at)}`}
            </span>
          </span>
          <span className={t.state === "OFFERED" ? "tag" : "tag ready"}>{label[t.state]}</span>
        </button>
      ))}
    </div>
  );
}

/** Copy, or the phone's own share sheet (WhatsApp, Messages, mail…). We
 * never send anything ourselves. */
function ShareButtons({ text, disabled }) {
  const [done, setDone] = useState(null);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setDone("Copied");
    } catch {
      setDone("Couldn't copy — select the text above");
    }
  }
  async function share() {
    if (!navigator.share) return copy();
    try {
      await navigator.share({ text });
    } catch (e) {
      if (e?.name !== "AbortError") setDone("Couldn't open sharing");
    }
  }
  return (
    <div className="row" style={{ gap: 8, marginTop: 8, alignItems: "center" }}>
      <button type="button" className="quiet" onClick={copy} disabled={disabled}>COPY</button>
      <button type="button" onClick={share} disabled={disabled}>SHARE</button>
      {done && <span className="muted" style={{ fontSize: 13 }}>{done}</span>}
    </div>
  );
}

function PriceRow({ label, value, sub, children, open, onToggle }) {
  return (
    <div className="pocket-row">
      <button type="button" className="pocket-row-head" onClick={onToggle} disabled={!onToggle}>
        <span className="pocket-label">{label}</span>
        <span className="pocket-value">{value}</span>
        {sub && <span className="pocket-sub">{sub}</span>}
      </button>
      {open && children && <div className="pocket-detail">{children}</div>}
    </div>
  );
}

/** The pricing screen: SUPPLIER, MARKET, AUCTION, then VESSEL SELL — the one
 * number Doug sets, by % or by typing it, the two always in step. Every
 * figure is shown in the supplier's own quote unit (/btl or /cs of N,
 * decision 0047) with an ISO currency code; the API stores and checks per
 * commercial unit. A VESSEL sell is always a whole 5 in the quote unit,
 * rounded UP. Gates that would need an accept are previewed here and decided
 * by the server at CREATE OFFER. */
function PricingScreen({ offerId, onStartOver }) {
  const [view, setView] = useState(LOADING);
  const [collect, setCollect] = useState(ok(null));
  const [sell, setSell] = useState(null);          // in the quote unit, pence, a whole 5
  const [sellText, setSellText] = useState("");    // in the quote unit, as typed
  const [availability, setAvailability] = useState("");
  const [create, setCreate] = useState(ok(null));
  const [gate, setGate] = useState(null);
  const [buyer, setBuyer] = useState("");
  const [confirm, setConfirm] = useState(ok(null));
  const [complete, setComplete] = useState(ok(null));
  const [openRow, setOpenRow] = useState(null);

  function setSellQuote(quotePence) {
    setSell(quotePence);
    setSellText(inputText(quotePence));
  }

  function adopt(data, { keepSell = false } = {}) {
    setView(ok(data));
    const start = data.committed?.vessel_sell ?? data.default_vessel_sell;
    if (start != null && !(keepSell && sell != null)) {
      setSellQuote(toQuote(toPence(start), data.quote_unit, data.pack_size));
    }
    if (!keepSell) setAvailability(data.availability || "");
  }

  async function load() {
    setView(LOADING);
    try {
      adopt(await api.post(`/inbound-offers/${offerId}/evaluate`));
    } catch (e) {
      setView(failed(e));
    }
  }
  useEffect(() => { load(); }, [offerId]);

  async function runCollect() {
    setCollect(LOADING);
    try {
      const data = await api.post(`/inbound-offers/${offerId}/collect-now`);
      setCollect(ok(data.collected));
      adopt(data.evaluation, { keepSell: true });
    } catch (e) {
      setCollect(failed(e));
    }
  }

  async function createOffer(accept, unit, pack) {
    setCreate(LOADING);
    setSellText(inputText(sell));
    try {
      const data = await api.post(`/inbound-offers/${offerId}/offer`, {
        vessel_sell: toMoney(fromQuote(sell, unit, pack)),
        availability: availability.trim() || null, accept });
      setGate(null);
      setCreate(ok(true));
      adopt(data, { keepSell: true });
      setAvailability(data.availability || "");
    } catch (e) {
      if (e.status === 409 && e.detail?.needs_accept) {
        setGate(e.message);
        setCreate(ok(null));
      } else {
        setCreate(failed(e));
      }
    }
  }

  async function confirmTrade() {
    setConfirm(LOADING);
    try {
      adopt(await api.post(`/inbound-offers/${offerId}/confirm`, { buyer_name: buyer.trim() }),
            { keepSell: true });
      setConfirm(ok(true));
    } catch (e) {
      setConfirm(failed(e));
    }
  }

  async function markComplete(fulfilmentId) {
    setComplete(LOADING);
    try {
      await api.post(`/fulfilments/${fulfilmentId}/complete`);
      setComplete(ok(true));
      load();
    } catch (e) {
      setComplete(failed(e));
    }
  }

  if (view.status === "loading") {
    return <p className="muted" style={{ marginTop: 12 }}>Checking the market…</p>;
  }
  if (view.status === "error") {
    return (
      <div className="notice bad" style={{ marginTop: 12 }}>
        Couldn&apos;t check the market ({view.error}).{" "}
        <button type="button" className="small" onClick={load}>Retry</button>
      </div>
    );
  }
  const v = view.data;
  if (!v) return null;
  const pack = v.pack_size;
  const unit = v.quote_unit;
  const label = quoteLabel(unit, pack);
  const cur = v.supplier_currency || "GBP";
  const title = wineTitle(v);
  const lineText = `${v.quantity} × ${pack > 1 ? `${pack} × ` : ""}${v.bottle_ml / 10}cl`;
  const where = [v.bond_status, v.stock_location].filter(Boolean).join(" · ");
  // Quote-unit figures for display; comparisons and arithmetic run per
  // commercial unit, exactly as the server stores them.
  const quoteOf = (unitPence) => toQuote(unitPence, unit, pack);
  const perBottleToQuote = (bottlePence) => (unit === "case" ? bottlePence * pack : bottlePence);
  const units = unit === "case" ? `${v.quantity} cs` : `${v.quantity * pack} btl`;

  if (v.fulfilment) {
    return <ConfirmedTrade f={v.fulfilment} complete={complete} onComplete={markComplete}
                           onStartOver={onStartOver} />;
  }

  const supplierUnit = v.ask ? toPence(v.ask.per_unit) : null;
  const supplierQuote = v.supplier_quote != null ? toPence(v.supplier_quote) : null;
  const floorUnit = v.market ? toPence(v.market.floor_per_unit) : null;
  const sellUnit = sell != null ? fromQuote(sell, unit, pack) : null;
  const bp = supplierUnit && sellUnit != null ? markupBp(sellUnit, supplierUnit) : null;
  const minBp = Math.round(Number(v.min_trade_margin) * 10000);
  const grossUnit = supplierUnit != null && sellUnit != null ? sellUnit - supplierUnit : null;
  const vsMarket = floorUnit && sellUnit != null ? vsMarketBp(sellUnit, floorUnit) : null;
  const committed = v.committed;
  const dirty = committed && (toPence(committed.vessel_sell) !== sellUnit
                              || (availability.trim() || null) !== (v.availability || null));
  const canCreate = sell != null && sell > 0 && create.status !== "loading";
  const typed = parsePounds(sellText);
  const roundsTo = typed != null && typed > 0 && ceilToStep(typed) !== typed ? ceilToStep(typed) : null;

  const warnings = [];
  if (floorUnit && sellUnit != null && sellUnit >= floorUnit) warnings.push("At or above the market price — needs your accept.");
  if (supplierUnit && sellUnit != null && sellUnit < supplierUnit) warnings.push("Below the supplier price — needs your accept.");
  // Four market states, never collapsed (decision 0040/0046): evidence
  // found, checked and none found, never checked, and a check that failed.
  const marketMissing = !v.market;
  const collectFailed = collect.status === "error"
    || (collect.status === "ok" && collect.data?.length > 0
        && collect.data.every((r) => r.outcome !== "ok"));
  if (marketMissing) {
    warnings.push("No current market evidence — you'll be asked to proceed without it.");
  } else if (v.market_note) {
    warnings.push(`The market ${v.market_note} — needs your accept.`);
  }

  const offerText = committed && tombstone({
    wineName: title, quantity: v.quantity, pack_size: pack, bottle_ml: v.bottle_ml,
    bond_status: v.bond_status, stock_location: v.stock_location,
    availability: v.availability, vesselSell: committed.vessel_sell, quoteUnit: unit });

  return (
    <div className="pocket">
      <div className="pocket-head">
        <div className="pocket-producer">{v.producer}</div>
        <div className="pocket-wine">{[v.cuvee, v.vintage === 1000 ? "NV" : v.vintage].filter(Boolean).join(" ")}</div>
        <div className="muted">{lineText}{where ? ` · ${where}` : ""}</div>
        {v.packaging && <div className="muted">{v.packaging}</div>}
      </div>

      <PriceRow label="SUPPLIER"
                value={supplierQuote != null ? `${fmt(supplierQuote, cur)} ${label}` : "No price recorded"}
                sub={v.ask ? `${fmt(toPence(v.ask.total), cur)} · ${units}` : "Start over to add the supplier's price"} />

      {v.market ? (
        <PriceRow label="MARKET" value={`${fmt(quoteOf(floorUnit), "GBP", { whole: true })} ${label}`}
                  sub={`${v.market.comp_count} source${v.market.comp_count === 1 ? "" : "s"}`
                       + (v.market.checked_at ? ` · checked ${shortDate(v.market.checked_at)}` : "")}
                  open={openRow === "market"}
                  onToggle={() => setOpenRow(openRow === "market" ? null : "market")}>
          {v.market.comps.map((c) => (
            <div key={c.merchant} className="pocket-comp">
              <span>{c.merchant}</span>
              <span>{fmt(perBottleToQuote(toPence(c.per_bottle)), "GBP", { whole: true })}
                {c.captured_at ? ` · ${shortDate(c.captured_at)}` : ""}</span>
            </div>
          ))}
          {v.walk_away && (
            <p className="muted" style={{ fontSize: 13, margin: "8px 0 0" }}>
              Walk-away {fmt(quoteOf(toPence(v.walk_away.walk_away)), "GBP", { whole: true })} {label} — the
              most you can pay and still make {formatBp(minBp, { signed: false })} selling 5% under market.
            </p>
          )}
          <CollectNowPanel collectNow={collect} onCollectNow={runCollect} />
        </PriceRow>
      ) : (
        <PriceRow label="MARKET"
                  value={collectFailed ? "Couldn't check"
                         : v.state === "NO_MARKET" ? "No current market evidence found" : "Not checked"}
                  sub={collectFailed ? "the collection failed — not the same as no market"
                       : v.state === "NO_MARKET" ? `${v.checked_merchants.length} merchants checked` : null}
                  open={openRow === "market"}
                  onToggle={() => setOpenRow(openRow === "market" ? null : "market")}>
          {v.state === "NO_MARKET" && (
            <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>Checked: {v.checked_merchants.join(", ")}</p>
          )}
          <CollectNowPanel collectNow={collect} onCollectNow={runCollect} />
        </PriceRow>
      )}

      <PriceRow label="AUCTION"
                value={v.auction?.median_per_bottle
                  ? `${fmt(perBottleToQuote(toPence(v.auction.median_per_bottle)), "GBP", { whole: true })} ${label}`
                  : "None on record"}
                sub={v.auction ? `${v.auction.lot_count} lot${v.auction.lot_count === 1 ? "" : "s"}`
                                 + (v.auction.latest_sale_date ? ` · ${monthYear(v.auction.latest_sale_date)}` : "")
                               : null} />

      <div className="pocket-sell">
        <div className="pocket-label">VESSEL SELL</div>
        <div className="pocket-sell-price">
          <span className="pocket-currency">GBP</span>
          <input inputMode="decimal" aria-label={`VESSEL sell price ${label}`} value={sellText}
                 onChange={(e) => {
                   setSellText(e.target.value);
                   const p = parsePounds(e.target.value);
                   if (p != null && p > 0) setSell(ceilToStep(p));
                 }}
                 onBlur={() => { if (sell != null) setSellText(inputText(sell)); }} />
          <span className="muted">{label}</span>
        </div>
        {roundsTo != null && (
          <div className="muted" style={{ fontSize: 13 }}>→ {fmt(roundsTo, "GBP")} {label}</div>
        )}
        <div className="pocket-stepper">
          <button type="button" className="quiet" aria-label="lower markup" disabled={bp == null}
                  onClick={() => setSellQuote(stepQuote(sell, supplierQuote, -1))}>−</button>
          <span>{bp == null ? "—" : formatBp(bp)}</span>
          <button type="button" className="quiet" aria-label="raise markup" disabled={bp == null}
                  onClick={() => setSellQuote(stepQuote(sell, supplierQuote, +1))}>+</button>
        </div>
        {grossUnit != null && (
          <div className="pocket-gross">
            <div><strong>{fmt(quoteOf(grossUnit), "GBP", { whole: true })} {unit === "case" ? "/cs" : "/btl"} gross</strong></div>
            <div>{fmt(grossUnit * v.quantity, "GBP", { whole: true })} total</div>
          </div>
        )}
        {vsMarket != null && (
          <div className="pocket-vs">
            {vsMarket === 0 ? "At market" : `${formatBp(Math.abs(vsMarket), { signed: false })} ${vsMarket > 0 ? "below" : "above"} market`}
          </div>
        )}
        {bp != null && bp < minBp && (
          <div className="muted" style={{ fontSize: 13 }}>Below your usual {formatBp(minBp)}.</div>
        )}
        {warnings.map((w) => <div key={w} className="pocket-warn">{w}</div>)}
      </div>

      <div style={{ marginTop: 12 }}>
        <label htmlFor="pavail">Availability (optional)</label>
        <input id="pavail" value={availability} placeholder="e.g. Available now · ETA 3 weeks"
               onChange={(e) => setAvailability(e.target.value)} />
      </div>

      {create.status === "error" && <div className="notice bad" style={{ marginTop: 10 }}>{create.error}</div>}
      {gate && (
        <div className="notice bad" style={{ marginTop: 10 }}>
          {gate}
          <div style={{ marginTop: 8 }}>
            <button type="button" onClick={() => createOffer(true, unit, pack)} disabled={!canCreate}>
              {marketMissing ? "Proceed without current market evidence" : "Accept and create offer"}
            </button>
          </div>
        </div>
      )}

      {(!committed || dirty) && !gate && (
        <div className="pocket-actions">
          <button type="button" className="quiet" onClick={onStartOver}>PASS</button>
          <button type="button" onClick={() => createOffer(false, unit, pack)} disabled={!canCreate}>
            {create.status === "loading" ? "Creating…" : committed ? "UPDATE OFFER" : "CREATE OFFER"}
          </button>
        </div>
      )}

      {committed && (
        <div className="card" style={{ marginTop: 14 }}>
          <div className="pocket-label">OFFER</div>
          <pre className="pocket-message">{offerText}</pre>
          {dirty && <p className="notice" style={{ fontSize: 13 }}>Price changed — update the offer before sharing.</p>}
          <ShareButtons disabled={dirty} text={offerText} />

          <div style={{ marginTop: 16 }}>
            <label htmlFor="pbuyer">Buyer said yes? Who</label>
            <input id="pbuyer" value={buyer} placeholder="Buyer name"
                   onChange={(e) => setBuyer(e.target.value)} />
            {confirm.status === "error" && <div className="notice bad" style={{ marginTop: 8 }}>{confirm.error}</div>}
            <button type="button" style={{ marginTop: 8, width: "100%" }}
                    disabled={dirty || !buyer.trim() || confirm.status === "loading"}
                    onClick={confirmTrade}>
              {confirm.status === "loading" ? "Confirming…"
                : `CONFIRM at ${quotePrice(committed.vessel_sell, unit, pack, "GBP", { whole: true })}`}
            </button>
          </div>
        </div>
      )}

      {committed && (
        <div style={{ marginTop: 12 }}>
          <button type="button" className="quiet" onClick={onStartOver}>Back to Pocket</button>
        </div>
      )}
    </div>
  );
}

/** CONFIRMED: the frozen record and the two handoffs, copy or share. */
function ConfirmedTrade({ f, complete, onComplete, onStartOver }) {
  return (
    <div className="pocket">
      <div className="notice good" style={{ marginTop: 12 }}>
        <strong>CONFIRMED</strong> · {f.buyer_name} · {f.wine_name}
        {f.state === "COMPLETE" && " · complete"}
      </div>

      <div className="card">
        <div className="pocket-label">TO SUPPLIER · {f.supplier_name}</div>
        <pre className="pocket-message">{supplierHandoff(f)}</pre>
        <ShareButtons text={supplierHandoff(f)} />
      </div>

      <div className="card">
        <div className="pocket-label">TO ADMIN</div>
        <pre className="pocket-message">{adminHandoff(f)}</pre>
        <ShareButtons text={adminHandoff(f)} />
      </div>

      {f.state === "OPEN" && (
        <div style={{ marginBottom: 12 }}>
          <button type="button" className="quiet" onClick={() => onComplete(f.fulfilment_id)}
                  disabled={complete.status === "loading"}>
            Mark trade complete
          </button>
          {complete.status === "error" && <div className="notice bad" style={{ marginTop: 8 }}>{complete.error}</div>}
        </div>
      )}
      <button type="button" onClick={onStartOver}>Back to Pocket</button>
    </div>
  );
}
