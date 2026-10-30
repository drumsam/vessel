"use client";

import { useEffect, useState } from "react";
import { api, BASE, money } from "../../lib/api";
import { LOADING, ok, failed, fetchInto } from "../../lib/fetchState";

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
  const [candidateGroups, setCandidateGroups] = useState(ok([]));
  const [showAllWines, setShowAllWines] = useState(false);
  // Screen 3: existing cached merchant and auction evidence, without a recommendation. Fetched
  // automatically the moment identity is confirmed -- this IS the next
  // screen, not a separate action Doug has to remember to trigger.
  const [evaluate, setEvaluate] = useState(ok(null));
  // speed-and-cost-plan.md's "Collect now": one wine, synchronous. A
  // separate three-state object from `evaluate` itself, since a stale
  // collect result must never look like it belongs to a later fetch --
  // but a successful run also replaces `evaluate` with the fresh facts
  // it produced, so the screen always shows one consistent picture.
  const [collectNow, setCollectNow] = useState(ok(null));

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
    setCandidateGroups(ok([]));
    setShowAllWines(false);
    setEvaluate(ok(null));
    setCollectNow(ok(null));
  }

  function runEvaluate(offerId) {
    fetchInto(setEvaluate, api.post(`/inbound-offers/${offerId}/evaluate`));
  }

  async function runCollectNow(offerId) {
    setCollectNow(LOADING);
    try {
      const data = await api.post(`/inbound-offers/${offerId}/collect-now`);
      setCollectNow(ok(data.collected));
      setEvaluate(ok(data.evaluation));
    } catch (e) {
      setCollectNow(failed(e));
    }
  }

  // Fires once, the moment confirmation sets identity_confirmed_at --
  // EVALUATE is the next screen, not a separate action to remember.
  useEffect(() => {
    if (offer?.identity_confirmed_at) runEvaluate(offer.inbound_offer_id);
  }, [offer?.identity_confirmed_at]);

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
        asking_price: proposal.asking_price ? proposal.asking_price.replace(/,/g, "") : "",
        asking_currency: proposal.asking_currency || "",
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

      {!candidate ? (
        <NewScreen pasteText={pasteText} setPasteText={setPasteText} onPaste={submitPaste}
                  onPhoto={(f) => submitFile("photo", f)} onUpload={(f) => submitFile("upload", f)}
                  create={create} retryId={retryId} onRetry={retry} />
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
                         reparsing={create.status === "loading"}
                         evaluate={evaluate}
                         onRetryEvaluate={() => runEvaluate(offer.inbound_offer_id)}
                         collectNow={collectNow}
                         onCollectNow={() => runCollectNow(offer.inbound_offer_id)} />
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
                          confirmState, onConfirm, onReparse, onStartOver, reparsing,
                          evaluate, onRetryEvaluate, collectNow, onCollectNow }) {
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

      <div className="card" style={{ background: "#faf8f6" }}>
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
            Seller ask: {proposal.asking_price} {proposal.asking_currency || ""}
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
              <label htmlFor="pask">Seller ask <StatedTag stated={stated.asking_price} /></label>
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
          <EvaluateScreen evaluate={evaluate} onRetry={onRetryEvaluate}
                         collectNow={collectNow} onCollectNow={onCollectNow} />
          <div style={{ marginTop: 12 }}>
            <button type="button" onClick={onStartOver}>Start another</button>
          </div>
        </>
      )}
    </>
  );
}

/** Screen 3, EVALUATE: facts, then stop. No verdict anywhere here — no
 * "good buy", no score, no traffic light; Doug compares the ask with
 * the walk-away price himself.
 *
 * "No Floor, no walk-away" is the PRIMARY state this is built around,
 * not an error path (Doug's own framing, 29 Oct 2026): merchant
 * evidence on the 20 want-list producers is measurably thin to absent,
 * so this will be the common case, not the edge case. It renders
 * through the calm `.notice`, never `.notice.bad` — a screen that
 * looks broken when it is working correctly will not get trusted. The
 * genuinely couldn't-check case (the request itself failed) is the one
 * that gets the error styling and a Retry, per decision 0040. */
function EvaluateScreen({ evaluate, onRetry, collectNow, onCollectNow }) {
  // Keep the import report while refreshing evidence; the upload control itself
  // unmounts during the loading render.
  const [importResult, setImportResult] = useState(ok(null));
  if (evaluate.status === "loading") return <p>Reading stored market evidence…</p>;
  if (evaluate.status === "error") return (
    <div className="notice bad">Couldn&apos;t check the market ({evaluate.error}). <button onClick={onRetry}>Retry</button></div>
  );
  const data = evaluate.data;
  if (!data) return null;
  const m = data.merchant;
  const t = data.transactions;
  const dated = (a) => a ? `${a.days} days old · ${a.label} · captured ${new Date(a.captured_at).toLocaleDateString()}` : "No dated evidence";
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <h2>Market evidence</h2>
      {data.ask && <p>Seller ask: {data.ask.currency || "Currency not stated"} {data.ask.currency ? money(data.ask.amount, data.ask.currency) : data.ask.amount} · {data.ask.basis || "basis not stated"} · {data.ask.quantity} × {data.ask.pack_size} bottles</p>}
      {data.collection_state === "CHECK_FAILED" && <p className="notice bad">Some sources couldn&apos;t be checked. Any retained evidence is dated below.</p>}
      {data.state === "NOT_SEARCHED" && <p>No successful covering collection for this wine yet.</p>}
      {data.state === "NO_MARKET" && <p>No currently eligible merchant asks found. Older or excluded evidence may still exist.</p>}
      <h3>Available market · UK In Bond · GBP</h3>
      <p>{m?.pack_size} × {m?.bottle_ml} ml per commercial unit</p>
      <dl>
        <dt>Merchant floor</dt><dd>{m?.floor == null ? "No current floor" : money(m.floor)}</dd>
        <dt>Merchant median</dt><dd>{m?.median == null ? "No current median" : money(m.median)}</dd>
        <dt>Sources</dt><dd>{m?.source_count || 0} distinct merchant(s)</dd>
        <dt>Newest evidence</dt><dd>{dated(m?.newest)}</dd>
        <dt>Oldest included evidence</dt><dd>{dated(m?.oldest)}</dd>
      </dl>
      {!!data.flags.length && <p className="muted">Evidence notes: {data.flags.join(", ")}. Pricing-data weakness does not decide the trade.</p>}
      {m?.evidence.map((e, i) => <p key={i} className="muted">
        {e.merchant}: {e.currency} {money(e.price, e.currency)} · {e.pack_size} × {e.bottle_ml} ml
        {e.derived_from && <strong> · Derived evidence — {e.derived_from.note || e.derived_from.basis}</strong>}
        {e.source_url && <> · <a href={e.source_url} target="_blank" rel="noreferrer">Source</a></>}
      </p>)}
      {!!m?.historical.length && <details><summary>Historical merchant evidence · not a current Floor</summary>
        {m.historical.map((e, i) => <p key={i}>{e.merchant}: {e.currency} {money(e.price, e.currency)} · captured {e.captured_at} · {e.pack_size} × {e.bottle_ml} ml</p>)}
      </details>}
      <h3>Transaction market · auction evidence</h3>
      <p>{t?.count || 0} lots · {t?.priced_count || 0} with GBP hammer normalization · {t?.window_days} day window</p>
      {t?.count > 0 && <>
        <p>Hammer range: {money(t.low_per_bottle_gbp)}–{money(t.high_per_bottle_gbp)} per bottle · median {money(t.median_per_bottle_gbp)}</p>
        <p>Latest sale {t.latest_sale_date} · {t.age_days} days old. Oldest included sale {t.oldest_sale_date}.</p>
        <p className="muted">Auction context only; never included in merchant Floor or Median.</p>
        {t.evidence.map((e) => <p key={e.auction_evidence_id}>{e.sale_date} · {e.currency} {e.amount} · {e.amount_basis} · {e.bottles_in_lot} bottles · <a href={e.source_url} target="_blank" rel="noreferrer">Lot source</a></p>)}
      </>}
      {t?.quarantined_count > 0 && <p>{t.quarantined_count} quarantined lots excluded from this summary.</p>}
      {data.blocks_create_offer && <p className="notice bad">{data.block_reason}</p>}
      <AuctionImportPanel onImported={onRetry} result={importResult} setResult={setImportResult} />
      <CollectNowPanel collectNow={collectNow} onCollectNow={onCollectNow} />
      {data.collection.map((c) => <p key={c.merchant_id} className="muted">{c.name}: {c.status === "failed" ? "couldn’t check" : "checked"} · {new Date(c.captured_at).toLocaleString()}</p>)}
    </div>
  );
}

function AuctionImportPanel({ onImported, result, setResult }) {
  async function upload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 2000000) { setResult(failed("File exceeds 2 MB")); return; }
    setResult(LOADING);
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (const byte of bytes) binary += String.fromCharCode(byte);
      const response = await api.post("/auction-imports", { filename: file.name, content_base64: btoa(binary) });
      setResult(ok(response));
      onImported();
    } catch (error) { setResult(failed(error.message)); }
    event.target.value = "";
  }
  return <div>
    <label>Import Christie&apos;s auction CSV/XLSX (2 MB maximum) <input type="file" accept=".csv,.xlsx" disabled={result.status === "loading"} onChange={upload} /></label>
    {result.status === "loading" && <p>Importing evidence…</p>}
    {result.status === "error" && <p className="notice bad">Couldn&apos;t import: {result.error}</p>}
    {result.status === "ok" && result.data && <p>{result.data.written} written · {result.data.unresolved} unresolved · {result.data.rejected} rejected · {result.data.duplicates} duplicates. {result.data.errors.map(e => `Row ${e.row}: ${e.error}`).join("; ")}</p>}
  </div>;
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
        {loading ? "Collecting…" : "Refresh Market"}
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
                    style={matched && !selected ? { borderColor: "var(--ready)" } : undefined}
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
        <form onSubmit={submitNew} className="row" style={{ marginTop: 8, alignItems: "flex-end" }}>
          <div className="grow">
            <label htmlFor="sup_name">Name</label>
            <input id="sup_name" required value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grow">
            <label htmlFor="sup_phone">Phone</label>
            <input id="sup_phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
          <button type="submit" className="small" disabled={busy || !name.trim()}>
            {busy ? "Adding…" : "Add"}
          </button>
        </form>
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
