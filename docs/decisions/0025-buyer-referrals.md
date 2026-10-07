# 0025 — Buyer referrals, the smallest version that works

**Status:** accepted, 7 October 2026. Overrides, specifically and by name,
the "stand down on VESSEL, no new features" instruction that followed
decision 0022: Doug decided growing the buyer list is the one thing left
before deal one, and said so directly rather than letting the override
happen by drift.

## Why it is small, and what that ruled out

At two to three cellars a year and roughly twenty buyers, every mechanic
has to still make sense at that size. Named explicitly, and not built:
waitlist positions, status tiers, membership caps, cash credits, buyer
ranking, the Thursday drop cadence, "My Cellar", or anything else from the
parked five-year growth and club document. The reason this list is in the
decision record rather than left to be inferred: so nobody adds any of it
back later "out of tidiness," which is the exact failure mode Doug named.

## `member`: VESSEL's first buyer account

VESSEL has never had a buyer identity (decision 0020's own admission: "no
login exists for sellers or buyers... not a developer's call"). A
referral programme cannot exist without one — there has to be somewhere
to record who invited whom, and whose first purchase unlocks what. `member`
is the smallest version of that: phone-identified (E.164, checked by
regex in Python and by a database `CHECK` behind it), no password. A
one-time code proves the phone belongs to whoever is accepting an invite;
nothing persists afterward the way an operator's session does. The member
reaches their own page again by the link they were handed at acceptance —
the same "no login beyond an unguessable link" discipline VESSEL's own
public routes already use, extended exactly as far as this feature needs
it to go and no further.

**Existing buyers are not addressed.** The roughly twenty buyers VESSEL
already has did not arrive through an invite, so nothing in this decision
gives them a `member` row. This is a real, named gap, not a silent one:
building a parallel bootstrap mechanism for them was not asked for, and
inventing one risked exactly the kind of unprompted scope this feature was
told to avoid. If Doug wants the existing list folded in, that is a
follow-up, not an assumption made here.

## Where `member.first_purchase_at` came from

Doug's five-field schema put `first_purchase_at` on `invite` only. Rule 1
("`invite_available` flips true when a member's first purchase confirms")
has to be true for every member, including the one not referred by
anyone — and `invite.first_purchase_at` only exists for a member who
arrived via a specific invite. `member.first_purchase_at` was added
because the rule as stated cannot be implemented without it, not as an
unprompted addition: a member's own first purchase unlocks their own next
invite; `invite.first_purchase_at` answers the separate question of
whether the person a specific invite brought in bought, which is what
pays that invite's inviter.

## The mechanics, each a constraint or a guard

- **One invitation at a time** — `invite_one_open_per_inviter`, a partial
  unique index on `(inviter_id) WHERE accepted_at IS NULL`. `_grant_next_invite`
  (`app/member/repo.py`) is written to be idempotent — it checks for an
  open row before creating one — but the index is the actual guarantee,
  the same relationship VESSEL's own `vessel_one_live_reservation_per_listing`
  already has to its own calling code.
- **Phone is the identity** — `UNIQUE` on `invite.invitee_phone` and on
  `member.phone`.
- **First touch, permanent** — checked in Python
  (`accept_invite`: a phone already a member, or already the invitee on
  another invite, raises `AlreadyClaimed` before anything is written) and
  backed by the two `UNIQUE` constraints for any path that skips the
  check. A refused acceptance never touches the invite row it was aimed
  at — "returns to them unused" is true by construction, not by an extra
  step: nothing is written until every check has passed.
- **Reward on completed purchase, never on signup** —
  `confirm_first_purchase` is called from exactly one place: the VESSEL
  route that confirms a sale (see below), never from acceptance.
- **The reward is access, not money** — `early_access_until`, 48 hours,
  set on both the inviter and the invitee when a referral's first
  purchase confirms. No credit, no balance, nothing resembling currency
  exists anywhere in this schema.
- **Self-referral refused** — `check_self_referral` compares the
  accepting phone to the inviter's own and raises before the OTP is even
  checked. **Simplified from the brief on purpose:** the brief describes
  "accept, but withhold the reward, and do not return the invite" as a
  three-way outcome; this implementation refuses the acceptance outright,
  which reaches the same end state (no self-referral ever produces a
  reward) through one guard instead of three. **Not implemented at all:**
  "same payment instrument." VESSEL does not capture or fingerprint a
  payment instrument anywhere — payments are matched by reference, amount
  and currency (decision 0020), never a card or account number — so there
  is nothing in this system to check that signal against. Flagged rather
  than faked.

## Where it touches VESSEL, and where it deliberately does not

`confirm_first_purchase` is called from `app/api/vessel.py`'s
`confirm-seller-receipt` route, immediately after `repo.confirm_seller_receipt`
itself — the one place a VESSEL sale actually confirms under the AGENCY
model this business runs on (decision 0022). Nothing inside `app/vessel/`
was touched: that package is exactly as decision 0022 left it, and the
"keep it, nothing further" instruction about VESSEL proper still holds.
Most values of `buyer_contact` are not phone numbers, or are phone numbers
nobody ever became a member with, and `confirm_first_purchase` is a quiet,
tested no-op for every one of them — this does not change how an ordinary
VESSEL sale behaves in any way a non-member buyer would notice.

## The seller introduction: captured, not automated

"Know another cellar?" on the mandate approval screen captures a name and
a phone against `captured_on_mandate_id` — the introducer's own mandate —
and nothing else. `resulting_mandate_id` exists on `seller_introduction`
for an operator to set by hand, later, only if and when the lead becomes a
seller in their own right; nothing here searches for or guesses at that
match, because there is no reliable way to connect a name-and-phone
capture today to a mandate that might not exist for months. Paying the 1%
is, for the same reason, a manual step reading this table — not a trigger
on `commission_invoice()`, which is scoped to one mandate's own completed
sales and has no natural place to pay out to a *different*, earlier
mandate's seller. Doug makes the approach; nothing here contacts the lead.

## The landing page and the share button

`/i/<code>` is server-rendered in the order specified: the inviter's first
name, the current drop's real region/count/price-from
(`current_cellar_summary`, joined through `seller_line`/`wine` for
region — nothing on `vessel_listing` itself names a region), and up to
three real `SOLD` listings with days-to-sell computed from the fulfilling
reservation, exactly as the drop page's own `sold_at` is already computed
(decision 0020). Both sections are omitted outright when there is nothing
real behind them — never a placeholder, never an invented figure.

The WhatsApp share button and the "Copy link" fallback are built
client-side only: the backend does not know its own public domain, so
`MemberOut` returns the raw invite code and the member's own page
(`web/app/member/[memberId]/page.jsx`) builds the `https://.../i/<code>`
URL from `window.location.origin` and composes the `wa.me` link in the
browser. No contacts are read, nothing is sent on anyone's behalf — the
button only ever opens WhatsApp's own share sheet.

## Consequences

- Migration `0020_member_referrals`: `member`, `member_login_code`,
  `invite`, `seller_introduction`, and `vessel_mandate.storage_facility`.
  `schema.sql` updated to match, verified byte-equivalent by catalog diff.
- `app/notify/provider.py` (new): the SMS seam, `ConsoleNotifier` the only
  provider wired up — no real SMS account exists to point this at yet.
- `app/member/engine.py` (pure) and `app/member/repo.py` (persistence):
  phone/OTP/invite-code generation and validation; `request_login_code`/
  `verify_login_code` (single-use, three attempts, ten minutes);
  `accept_invite`; `confirm_first_purchase`; `create_seller_introduction`;
  `current_cellar_summary`/`recent_sales` for the landing page;
  `referral_funnel` for the one read-only report asked for.
- `app/api/member.py`/`member_schemas.py` (new, public router):
  `POST /members/request-code`, `GET /invites/{code}`,
  `POST /invites/{code}/accept`, `GET /members/{member_id}`.
- `app/api/vessel.py`: `confirm_seller_receipt` now also calls
  `confirm_first_purchase`; two new operator routes,
  `POST /vessel/mandates/{id}/seller-introductions` and
  `GET /vessel/analytics/referrals`; `approve_mandate`/`ApproveMandateIn`/
  `MandateOut` carry `storage_facility` through.
- `web/app/i/[code]/page.jsx` (new): the landing page and the four-field
  accept form. `web/app/member/[memberId]/page.jsx` (new): the member's
  own page, the share button, the copy-link fallback.
  `web/app/vessel/approve/[dealId]/page.jsx`: the storage-facility field
  and the post-approval "Introduce someone" flow.
  `web/app/chrome.jsx`: `/i/*` and `/member/*` exempted from the operator
  sign-in gate, same mechanism as `/vessel/*`.
- Tests: `tests/test_member.py` — 6 offline (pure) and 13 against
  Postgres, including the partial unique index proven by a direct,
  repo-bypassing `INSERT`, self-referral and first-touch-permanent each
  leaving the targeted invite row completely untouched, the OTP lockout
  burning its own row within the attempt that exhausts it, and a
  completed referral rewarding both sides while creating exactly the
  three invite rows the mechanics actually produce (the original, the
  invitee's own, and the inviter's reward) — asserted precisely rather
  than assumed. 347 offline (was 341), 508 with Postgres (was 489).
