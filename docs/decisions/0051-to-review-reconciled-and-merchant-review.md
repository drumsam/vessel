# 0051 — To Review reconciled, minimal merchant review, login lands on the Workbench

**Status:** accepted, 1 November 2026, on Doug's three corrections to decision
0050 before deployment. No pricing rule changes.

## Login lands on the Workbench

A successful sign-in goes to `/`, the Workbench, not `/pocket`. Pocket stays
in the nav and behind New Offer; `VESSEL` returns to the Workbench from
everywhere.

## To Review is one set

> If it counts as To Review on the Workbench, it appears on the To Review
> page. If it does not count, it does not appear there.

`app/inbound/repo.py::review_lines` is the one definition of the cellar lines
To Review holds — the review queue minus every deal a Pocket offer made for
itself (`pocket_deal_ids`, orphans included). `GET /review-queue` returns it
and the Workbench counts it, so the two cannot disagree. A Pocket offer's own
line is reviewed in Pocket, never on this page.

The To Review page (`/queue`) now lists exactly the Workbench's TO REVIEW:
Pocket offers needing identity, cellar lines, new merchants, LWIN conflicts
and wine spellings. Each section appears only when it has something in it
(or could not load — decision 0040, never shown as empty), and each Workbench
item links to its section. Lines show an action (Review identity, Check
market, Accept price, Check evidence), not a raw state or flag list.

## Merchant review

A merchant a market feed introduces is created unapproved (decision 0048) and
sets no Floor. To Review lists each one never reviewed, with its name, the
source(s) that introduced it (`snapshot_merchant.scope_params
.acquisition_source`) and how many observations are held (offers plus retained
rejections), and two actions:

- **APPROVE** — `merchant.approved = true`.
- **KEEP UNAPPROVED** — stays unapproved, leaves the list, and sits under a
  collapsed "Kept unapproved" from where it can still be approved later.

Both record who and when (`merchant.reviewed_by`/`reviewed_at`, migration
`0041_merchant_review`; the operator is the session's, invariant 14). Nothing
approves automatically. Approval changes nothing but the flag: whether a
merchant's evidence then contributes to Floor is decided by the core's
existing screens at the next benchmark (approval is read at resolve time, so
evidence already held and still fresh counts too, under the same screens —
In Bond, ASK, GBP, freshness, size). The MrBridge rows from 1 November are
stored as `EQUIVALENT_ONLY` rejects and never become offers, so approving
their merchants does not make them Floor evidence.

No CRM fields, no merchant admin, no scoring.

Production holds exactly four unapproved merchants, all from the first
MrBridge batch: wilkinson-vintners, farthinghoe-fine-wine, mann-fine-wine,
turville-valley-wines. Every merchant seeded by migration is approved.
