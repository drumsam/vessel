"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { quotePrice } from "../lib/pocketMessages";

/** Shared by the Workbench, Trades and Pocket (decision 0050): one row per
 * offer — WHAT | WHO | STATUS | NEXT ACTION — and its three-dot menu. Status
 * and next action are the server's, derived from what the offer records;
 * nothing here decides either. */

export const STATUS_LABEL = {
  UNREADABLE: "Couldn't read",
  NEEDS_IDENTITY: "To review",
  WHISKY: "Whisky",
  READY_TO_PRICE: "Ready to price",
  OFFER_OUT: "Offer out",
  CONFIRMED: "Confirmed",
  COMPLETE: "Complete",
};

const CONFIRMED = new Set(["CONFIRMED", "COMPLETE"]);

export function openHref(id, extra = "") {
  return `/pocket?open=${id}${extra}`;
}

export function whenText(iso) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function lineText(t) {
  if (!t.quantity || !t.bottle_ml) return null;
  return `${t.quantity} × ${t.pack_size > 1 ? `${t.pack_size} × ` : ""}${t.bottle_ml / 10}cl`;
}

/** Unconfirmed: Edit · Share again · Duplicate · Delete. Confirmed: View ·
 * Share again · Duplicate — a confirmed trade is never deleted, and the
 * server refuses it too. */
export function OfferMenu({ item, onChanged }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const box = useRef(null);
  const confirmed = CONFIRMED.has(item.status);
  const offered = item.vessel_sell != null;

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  async function duplicate() {
    setBusy(true);
    setError(null);
    try {
      const copy = await api.post(`/inbound-offers/${item.inbound_offer_id}/duplicate`);
      router.push(openHref(copy.inbound_offer_id));
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  async function remove() {
    setOpen(false);
    if (!window.confirm(`Delete "${item.title}"? It disappears from your lists; `
                        + "the message, wine, supplier and anything already shared are kept.")) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/inbound-offers/${item.inbound_offer_id}/discard`);
      onChanged?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="menu" ref={box}>
      <button type="button" className="quiet menu-dots" aria-label={`Actions for ${item.title}`}
              aria-expanded={open} disabled={busy} onClick={() => setOpen(!open)}>
        ⋯
      </button>
      {open && (
        <div className="menu-list" role="menu">
          <Link role="menuitem" href={openHref(item.inbound_offer_id)}>
            {confirmed ? "View" : "Edit"}
          </Link>
          {offered ? (
            <Link role="menuitem" href={openHref(item.inbound_offer_id, "&share=1")}>Share again</Link>
          ) : (
            <span role="menuitem" aria-disabled="true" className="off" title="Nothing has been offered yet">
              Share again
            </span>
          )}
          <button type="button" role="menuitem" onClick={duplicate}>Duplicate</button>
          {!confirmed && (
            <button type="button" role="menuitem" className="danger" onClick={remove}>Delete</button>
          )}
        </div>
      )}
      {error && <div className="menu-error">{error}</div>}
    </div>
  );
}

export function TradeRow({ t, onChanged }) {
  const line = lineText(t);
  const price = t.vessel_sell != null && t.quote_unit
    ? quotePrice(t.vessel_sell, t.quote_unit, t.pack_size, "GBP", { whole: true }) : null;
  return (
    <div className="trow">
      <div className="t-what">
        <Link href={openHref(t.inbound_offer_id)} className="t-title">{t.title}</Link>
        <div className="muted t-small">
          {[line, price, whenText(t.when)].filter(Boolean).join(" · ")}
        </div>
      </div>
      <div className="t-who t-small">
        {t.supplier_id ? <Link href={`/suppliers/${t.supplier_id}`}>{t.supplier_name}</Link>
          : <span className="muted">No supplier yet</span>}
        {(t.client_id || t.buyer_name) && (
          <>
            <span className="muted"> → </span>
            {t.client_id ? <Link href={`/clients/${t.client_id}`}>{t.buyer_name}</Link> : t.buyer_name}
          </>
        )}
      </div>
      <div className="t-status">
        <span className={CONFIRMED.has(t.status) ? "tag ready" : "tag"}>{STATUS_LABEL[t.status]}</span>
      </div>
      <div className="t-next t-small">
        <Link href={openHref(t.inbound_offer_id, t.status === "OFFER_OUT" ? "&share=1" : "")}
              className="t-action">{t.next_action}</Link>
      </div>
      <OfferMenu item={t} onChanged={onChanged} />
    </div>
  );
}

export function TradeHead() {
  return (
    <div className="trow thead" aria-hidden="true">
      <div>What</div><div>Who</div><div>Status</div><div>Next action</div><div />
    </div>
  );
}
