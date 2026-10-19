# 0035 — shareable public offer links

**Status:** accepted, 20 October 2026. Doug, on the real client document the
moment it existed: "how might I message them?" — a document nobody but the
operator can open is not a document a buyer or a seller can act on.

## The gap

`/deals/{dealId}/offer` sits behind the operator session, same as every
other screen in this app. A buyer has no account and never will; a seller
has no account either (VESSEL's own public routes have never required
one — decision 0025's own words). The real offer document decision 0034
built was real evidence and a real document, but it was still something
only Doug could look at.

## The fix

> A signed, unguessable, read-only, time-boxed public link for a chosen
> set of a deal's lines. No login for the buyer or the seller. It shows
> prices and evidence and nothing else — no seller identity, no cost; a
> buyer link never shows commission, a seller link may.

`shared_offer_link` (migration `0027_shared_offer_links`): a random
256-bit token (`secrets.token_urlsafe(32)`, `app/offerlink/repo.py`), the
deal, the exact `line_ids` it was cut for, which of the two views it
shows (`kind`), the display rate used, who made it and when, and when it
stops working (`expires_at`, 7 days, matching the document's own stated
validity window). No open-receipt or analytics column exists — Doug
asked for none, and none is here.

`create_link` refuses a line still gated under invariant 12
(`LineNotSendable`) and a line that is not actually one of the deal's own
(`LineNotInDeal`) — a public link given to someone outside this app IS an
export, and the same gate that stops the buyer export stops this. Two
endpoints: `POST /deals/{deal_id}/offer-links` (operator session,
creates), `GET /public/offer-links/{token}` (no session at all — the one
screen in the whole app a buyer or seller can open directly; an unknown
or expired token reads identically, a plain 404, so a stale link never
confirms to whoever is holding it that it once worked).

`build_public_payload` is where the actual safety rule lives: for a
`kind == "buyer"` link, the per-line dict it returns never gains a
`seller_price_gbp` or `commission_gbp` key at all — not a null one, the
key is never added. The key is only ever added for `kind == "seller"`.
`response_model_exclude_none=True` on the public route means the HTTP
response itself drops any field that IS null, so the two kinds are
indistinguishable in shape where they should be. Nothing in the payload
ever reads `deal.name` or `deal.seller`.

`floor_saving_claim` (decision 0034) is recomputed here from the same two
stored figures (`sell_price`, `uk_floor`) — it is not itself stored on
`pricing_result`, so the public payload computes it exactly the way
`_pricing_out` does, from `app/core/flags.py::claims_a_saving`, never a
second copy of the rule.

## The composer

A buyer or seller cannot be messaged with a document; they can be
messaged with a link. The Cellar Desk's own offer document
(`/deals/{dealId}/offer`) gained a "Share this offer" section: a kind
toggle, a "Generate link" button, the resulting URL with a copy button,
and a pre-filled, editable message naming the top three lines and their
per-bottle prices plus the link — opened on WhatsApp's own share sheet
via a `wa.me` link (decision 0025's exact mechanism, reused, not
reinvented) or copied as plain text for WeChat or a group chat. Doug
picks the recipient inside WhatsApp; nothing here reads his contacts or
sends on his behalf. The default message text is a factual placeholder,
not Doug's own drafted wording — he wrote three messages separately and
his words replace this default once given.

## A bug this found, in already-shipped code

`web/app/chrome.jsx`'s own public-path exclusion only governed what
rendered, not the redirect `useEffect` sitting above it — that effect
checked `session.status === "out"` and `pathname !== "/login"` alone, so
for ANY public page (VESSEL's own, a member's own, and now `/share/`) a
first-time visitor with no cookie at all got `router.replace("/login")`
fired out from under them the instant the session check came back "out",
which it always does with no cookie. Caught live, testing this feature
with a fresh, cookie-less browser context — the exact shape of visit a
real buyer or seller always is, and the one this file's own existing
manual testing had never exercised. Fixed once, centrally
(`isPublicPath()`), read by both the effect and the render, so the same
mistake cannot recur for a fourth public path.

## What this is not

Not a VESSEL table or route: `shared_offer_link` is its own, small,
standalone mechanism, reading `pricing_result` and `benchmark_run`
exactly as the Desk and the offer document already do. It does not touch
`app/vessel/`'s own listing/mandate tables, and nothing in `app/core/` or
`app/pricing/` changed.

Not a tracking or analytics feature. No open-receipt, no view count, no
IP log — Doug's own words, "no tracking, no open receipts, no analytics
on the link," and the schema has nowhere to put any of it even by
accident.

Not revocation. A link's only lifecycle is its expiry; a revoke
endpoint was not asked for and is not built. If a link needs to die early,
that is a follow-up decision, not an assumption made here.

## Consequences

- `app/db/schema.sql` + migration `0027_shared_offer_links`: new table
  `shared_offer_link`.
- `app/offerlink/repo.py` (new): `create_link`, `get_valid_link`,
  `build_public_payload`, `LineNotInDeal`, `LineNotSendable`.
- `app/api/schemas.py`: `OfferLinkIn`, `OfferLinkOut`,
  `PublicOfferLineOut`, `PublicOfferOut`.
- `app/api/main.py`: `POST /deals/{deal_id}/offer-links` (protected),
  `GET /public/offer-links/{token}` (public, `exclude_none`).
- `web/app/chrome.jsx`: the public-path check unified into
  `isPublicPath()`, read by the redirect effect as well as the render —
  fixes the same latent bug for `/vessel`, `/i/` and `/member` too.
- `web/app/deals/[dealId]/offer/page.jsx`: `ShareComposer` — kind toggle,
  link generation, WhatsApp share, copy text.
- `web/app/share/[token]/page.jsx` (new): the public, no-login document,
  buyer and seller variants.
- `web/lib/wine.js`: `clLabel`/`listedAs`/`formatDate` extracted (now
  shared by the operator offer page and the public one).
- Tests: `tests/test_offerlink.py` (new, 9 tests, Postgres) — a gated
  line refused, a line outside the deal refused, token round-trip, an
  expired link reading as not-found, the buyer payload's structural
  absence of seller/commission fields, the seller payload carrying them,
  and the same at the HTTP layer with a real anonymous `TestClient`.
  `tests/test_service.py`'s own
  `test_cost_above_the_reference_is_a_commercial_fact_not_a_gate` was
  found stale while running the full suite (asserted an exact
  acknowledgement-flags list that predated decision 0033's
  `SELL_AT_OR_ABOVE_UK_FLOOR`) and corrected, unrelated to this decision
  but found doing its own diligence. Full suite: 470 passed offline (was
  470, 9 new tests added but Postgres-only so skipped offline — 172
  skipped, was 163), 642 passed against Postgres.
