# VESSEL architecture — built around the actual job

> **Editorial note added on filing, 27 October 2026 — not Doug's text.**
> This document is Doug's own architecture review and is canonical on intent.
> Two points were refined by him *after* it was written, and the build brief
> (`build-brief-vessel-pocket.md`) carries the final form:
>
> 1. **There is no `CLOSED` state.** The state list ends
>    `... → OFFERED → CONFIRMED`. `CLOSED` was dropped because nobody whose
>    job it is would ever set it.
> 2. **A single `fulfilment` record is in scope**, created automatically on
>    CONFIRMED — not the invoice and shipment engines rejected below. VESSEL
>    *records* an invoice number and a transfer reference; it does not
>    generate an invoice or instruct a transfer.
>
> Where this document and the build brief differ, **the build brief wins.**

**Doug's review, 27 October 2026. This supersedes
`architecture-review-2026-10-27.md`**, which gave too much weight to
administration, large-cellar workflows and downstream operations.

---

## The job, in one line

VESSEL should let Doug take almost anything that arrives on his phone and turn
it into a checked, priced, buyer-ready wine offer in about a minute.

Not a CRM. Not an ERP. Not accounting software. Not a logistics platform.
**A commercial decision and execution tool.**

Most offers are **one or two high-value wines or parcels**, arriving while he is
moving around — usually WhatsApp, sometimes a photograph, sometimes text,
occasionally a spreadsheet. The workflow is
**receive → understand → check → price → decide → offer**, and all of it should
be possible from a phone.

Large cellars are different: slower, more analytical, and they can stay on a
laptop.

---

## The core remains untouched

**Identity.** Keep protecting against commercially dangerous ambiguity —
domaine versus maison, cuvée, vineyard, bottle size, vintage, Krug edition, Dom
Pérignon plénitude, and the other structural traps. The purpose is not academic
precision; it prevents a five-figure mistake.

**Pricing.** The deterministic core stays exactly as designed: evidence from
named sources, Floor / Reference / Median, commercial-unit equality, Decimal
money, source dates, vintage sanity checks, review flags, decision records.
**AI must not invent or determine the commercial price.**

**Evidence.** Every price stays traceable. That is the difference between *"I
reckon this is worth £X"* and *"here is why £X is sensible"*. The outward offer
can be extremely short precisely because the evidence sits underneath it.

---

## IN — the input edge

The first screen needs almost nothing: **Paste · Photo · Upload**.

No deal creation form. No client record first. No mandatory metadata.
**Capture first, structure afterwards.**

## AI belongs at this edge, and only here

The AI reads the incoming material and proposes:

> **Domaine de la Romanée-Conti** · Richebourg Grand Cru · 2015 · 3 × 75cl ·
> UK In Bond · LCB · Seller ask £2,800/bottle · Packaging: unknown

Doug should not type that again. But it remains a **candidate**, and it then
passes through the deterministic identity and pricing system.

If identity is uncertain: **"Check required — I found two possible
identities."** If information is absent: **"Packaging unknown"**, never a
guessed "OWC".

**The AI's job is to eliminate typing. It does not eliminate judgement.**

---

## EVALUATE — the screen that earns the product

> **DRC Richebourg 2015** · 3 × 75cl · UK IB · LCB
>
> Seller asks **£8,400** · Market reference **£10,200** · **18% below**
> Evidence: 4 current sources
>
> [ VIEW EVIDENCE ]  [ CREATE OFFER ]

Four things visible in seconds: what is it, what am I asked to pay, what does
the market say, do I like the trade. Everything else is secondary.

**Doug remains the commercial filter** — Pass, Hold, or Create Offer. The
system does not automatically turn every inbound wine into an offer.

---

## OUT — brutally simple

Large buyers know wine. They do not need tasting notes, stories, critic scores
or promotional copy.

> **DRC Richebourg 2015**
> 3 × 75cl · UK IB · LCB
> £3,350/bt · £10,050
> Available now

Optional private link underneath. One tap: **Copy** or **Share**, then Doug
picks the WhatsApp conversation. Done.

**Short outside, deep inside.** The link can quietly hold exact identity,
location, packaging, provenance, market evidence, condition, photographs,
validity and terms. The buyer never has to open it. The surface stays
**wine + quantity + location + price + availability**.

---

## Images are native to the workflow

Because offers are often one or two expensive wines, photographs matter more
than previously assumed.

**Photo → VESSEL parses label → proposes identity → Doug confirms → pricing
engine evaluates.** The original image stays attached to the trade, and the
outbound offer can carry it where useful. One or several images per line is
enough — no photography management.

---

## One engine, two workflows

| Large cellar — laptop | Small trade — phone |
|---|---|
| spreadsheet import | paste / photo |
| bulk identity resolution | check |
| pricing coverage, review flags | price |
| Cellar Desk, seller analysis | offer |

Same identity, pricing and evidence engine underneath. **Not one universal
interface.**

---

## Stop the product at confirmation

Do not build invoice or shipment tables. Once a buyer says yes, VESSEL captures
**CONFIRMED** plus buyer, wine, quantity, price, date, location and any
instruction — then Doug shares it with whoever handles administration, who
raises the invoice and arranges transfer with existing tools.

> **CONFIRMED** · Client ABC · DRC Richebourg 2015 · 3 × 75cl · £10,050 ·
> UK IB · LCB   [ SHARE CONFIRMATION ]

No reason exists today for VESSEL to recreate invoicing, accounting, warehouse
or logistics software. If administration becomes the bottleneck, integrate then.

## So the states stay tiny

**INBOUND → EVALUATED → OFFERED → CONFIRMED → CLOSED**

Do not confuse commercial state with every operational event after the deal.

*(See the editorial note at the top: `CLOSED` was subsequently dropped, and a
single `fulfilment` record added. The build brief is authoritative.)*

---

## The three actions

**NEW** (something arrived — paste / photo / upload) →
**EVALUATE** (what is it, what's the ask, what's the market, do I like it) →
**OFFER** (what do I sell it for — create, share).

That is VESSEL on the move.

---

## Deployment is still Phase 1

Localhost remains the first blocker. It should be hosted, authenticated, backed
by managed Postgres, securely reachable from Doug's phone, and responsive for
NEW → EVALUATE → OFFER. **This does not require rebuilding the Cellar Desk for
mobile** — the mobile work is a new narrow surface over the same system.

## Input channels — do not over-build

Phase one: **paste text, upload file, take/upload photo.** That covers most real
situations. Then observe behaviour. Later, only if eliminating copy/paste
materially helps: iOS Share to VESSEL, inbound email, WhatsApp Business API,
automatic attachment ingestion.

**The first objective is not zero taps. It is getting from inbound wine to
commercial decision extremely quickly.**

---

## The operating target

Inbound message → evaluated trade: **under 30 seconds.**
Evaluated trade → outbound offer: **under another 30 seconds.**
So **inbound → buyer-ready in under a minute.**

An ambiguous Leroy, Krug edition or other identity exception is allowed to take
longer. **The system should never sacrifice correctness to hit the time target.**

---

## What to build now — Phase 1, VESSEL Pocket

Deploy the existing engine, then build mobile:

1. **New** — paste, photo, upload
2. **Candidate** — AI structured interpretation, confirm / correct identity
3. **Evaluate** — seller ask, reference, evidence strength, commercial difference
4. **Create Offer** — buyer price, total, margin, create
5. **Share** — concise WhatsApp tombstone, optional evidence link
6. **Confirm** — mark buyer acceptance, generate simple admin handoff

**Phase 2, only after Phase 1 has been used:** buyer history, recent contacts,
one-tap reuse of previous buyers, iPhone Share to VESSEL, better photo
extraction, inbound email parsing, offer expiry.

**Not now:** invoice engine, shipment engine, accounting, warehouse software,
WhatsApp Business API, CRM, buyer preference engine, automated broking,
complicated deal workflows, redesign of the pricing core, full mobile Cellar
Desk.

---

## Product test

Every proposed feature must answer at least one:

- Does this help Doug understand an incoming wine faster?
- Does this improve pricing confidence?
- Does this make creating an offer faster?
- Does this reduce the chance of a costly mistake?
- Does this get the offer in front of a buyer faster?

If not, it probably does not belong in VESSEL Pocket.

---

## The architecture in one line

**Anything in → checked commercial decision → anything out.**

The sophistication belongs underneath. The experience should feel almost
trivial.
