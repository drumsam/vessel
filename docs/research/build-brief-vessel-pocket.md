# Build brief — VESSEL Pocket, Cellar, Ops

27 October 2026. Architecture agreed with Doug over
`architecture-vessel-pocket.md` plus his fulfilment refinement.

**Read this whole file before writing code.** The scope boundaries matter more
than the features — most of this brief is about what not to build.

---

## The shape

**One engine. Three surfaces.**

| Surface | Device | Flow |
|---|---|---|
| **VESSEL Pocket** | phone | IN → EVALUATE → OFFER → CONFIRM |
| **VESSEL Cellar** | laptop | IMPORT → REVIEW → PRICE → APPROVE → OFFER |
| **VESSEL Ops** | either | the post-confirmation queue |

Identity, evidence, pricing and commercial maths are shared and unchanged.
Pocket is a **new narrow surface over the existing system**, not a new system.

The primary job is the small high-value mobile trade: one or two wines, arriving
by WhatsApp or photo while Doug is moving. Cellar work stays on a laptop.

---

## Phase 1a — HOSTING. Nothing else matters first.

The app runs on `localhost` via `desk.sh`. Doug is mobile. **He physically
cannot use what exists.** Every feature below is theoretical until this is done.

- API and web on a small managed host
- **Managed Postgres, smallest PAID tier, not free** — decision 0032 has the
  reasoning: two to three deals a year means dormancy is the normal state, and
  free projects get reclaimed. Doug supplies the `DATABASE_URL`; do not create
  accounts.
- A real domain, HTTPS, the existing operator auth
- `desk.sh` and embedded Postgres stay as the local dev and demo path. The
  banner already prints the database host — keep that, it is how Doug knows
  whether he is looking at demo data or a real cellar.

No code changes should be needed: the app already selects its database on
`DATABASE_URL` alone. If anything resists, say what rather than working around
it.

Report the URL and confirm the first `evidence_backup.py` dump against the
managed instance, per 0032.

---

## Phase 1b — VESSEL Pocket

### Reuse the existing objects. Do not fork the engine.

A Pocket trade is a `deal` with one or two `seller_line`s and a different
surface. **Do not create a parallel `trade` table.** Forking the data model is
exactly what "one engine, three surfaces" exists to prevent.

### Screen 1 — NEW

Three buttons and nothing else: **Paste · Photo · Upload**.

No deal creation form, no client record first, no mandatory metadata.
**Capture first, structure afterwards.**

New table, and the raw record is sacred:

```
inbound_offer
  inbound_offer_id   uuid pk
  received_at        timestamptz not null
  channel            text not null        -- 'paste' | 'photo' | 'upload'
  raw_body           text                 -- VERBATIM, never normalised
  raw_media          bytea                -- the photo or file exactly as sent
  media_mime         text
  parsed_at          timestamptz
  parse_state        text not null        -- 'pending'|'parsed'|'unparseable'
  parse_error        text
  deal_id            uuid references deal -- set once it becomes a deal
```

Same discipline as `seller_line.raw_row`: the original is never destroyed. A bad
parse is re-parsed, never reconstructed. **A photo is also provenance** — keep
it attached to the line for the life of the trade and make it available on the
outbound offer.

### Screen 2 — CANDIDATE

AI reads the inbound material and proposes structured fields:

> Domaine de la Romanée-Conti · Richebourg Grand Cru · 2015 · 3 × 75cl ·
> UK In Bond · LCB · Seller ask £2,800/bottle · **Packaging: unknown**

Rules, all of them hard:

- **The AI proposes a `Candidate`, never an `Offer`.** It goes through the same
  `registry.resolve_candidate`, the same want-list gate, the same vintage-band
  check as every other line. `app/core/` is untouched.
- **The AI never produces a price.** Not a reference, not a buyer price, not an
  estimate. It may read a seller's stated ask out of the text, labelled as the
  seller's ask.
- **Absent information stays absent.** "Packaging: unknown", never a guessed
  "OWC". A field the source did not state must render as unknown.
- **A parse failure must not look like a clean read.** Decision 0040's rule
  applies: `unparseable` is a third state, visually distinct, and it blocks.

### THE PHOTO GATE — the most dangerous thing in this build

Image-to-identity is materially less reliable than text-to-identity, and a
label photo of a want-list wine is exactly where the 5–20× error lives.

- For any of the **twenty want-list producers**, a photo-derived identity
  **must never auto-resolve**. Manual confirmation is required and
  **technically enforced** — the next screen is unreachable until Doug
  acknowledges. Decision 0038's gate already does this; wire the photo path to
  it.
- **A confidence score must not override the gate.** Do not add a threshold
  above which it is skipped. There is no such threshold.
- Show the photo next to the proposed identity so Doug is confirming against
  the label, not against the AI's prose.

### Screen 3 — EVALUATE

Facts, then stop:

> **DRC Richebourg 2015** · 3 × 75cl · UK IB · LCB
>
> Seller ask **£8,400** (£2,800/bt)
> Market reference **£10,200** (£3,400/bt)
> **17.6% below reference**
> Evidence: 4 current sources · read 27 Oct
>
> [ VIEW EVIDENCE ]   [ PASS ]   [ HOLD ]   [ CREATE OFFER ]

**NO verdict language.** No "looks attractive", no "good buy", no traffic
lights, no score. The engine states evidence; Doug judges. He said it himself:
that boundary is valuable, and a system that renders an opinion and is wrong
once never gets trusted again.

Per-bottle figures primary, line totals secondary — same as the Cellar Desk
after decision 0034.

### Screen 4 — CREATE OFFER, and this needs its own commercial rule

**Do not reuse decision 0017's chain.** That is `reference × 0.80` for selling
someone else's cellar on commission. A parcel trade is economically different:
Doug buys at X and sells at Y, and the margin is on his cost.

Add a second pricing basis — `parcel_trade` alongside the existing
`buyer_discount` — in which **Doug enters or approves the buyer price** and the
system computes the consequences:

> Seller ask £8,400 · Market reference £10,200 · Market gap 17.6%
>
> Buyer price  [ £______ ]
>
> Gross spread £_____ · Gross margin ____%

The system may not derive the buyer price from a discount to reference under
this basis. Later, with history, it could suggest a range from Doug's own past
trades — not now, and never by leaking the cellar discount logic in.

**The guards still apply.** Decision 0033 (never at or above the Floor) and
0034 (claims measured against the Floor, suppressed under 5%) hold regardless
of basis. A parcel trade cannot be offered above a price the buyer can already
find.

### Screen 5 — SHARE

The outbound tombstone, brutally short:

> **DRC Richebourg 2015**
> 3 × 75cl · UK IB · LCB
> £3,350/bt · £10,050
> Available now

One tap: **Copy** or **Share**, via the `wa.me` mechanism from decision 0025.
Doug picks the conversation inside WhatsApp. We never send anything.

Optional private link beneath it, reusing decision 0035's signed share links:
exact identity, location, packaging, provenance, evidence, condition, the
photographs, validity, terms. **Short outside, deep inside.** The buyer never
has to open it.

`assertBuyerSafe()` from decision 0036 applies to every outbound message:
no cost, no commission, no margin, no seller identity.

### Screen 6 — CONFIRM

Pressing CONFIRMED does exactly three things:

1. **The deal becomes commercially immutable.** No price or quantity edit
   after this. Corrections are a void-and-reissue, same rule as the auction
   evidence rows.
2. **A fulfilment record is created automatically.**
3. **A handoff message is generated** for the seller and for admin.

> **CONFIRMED** · DRC Richebourg 2015 · 3 × 75cl · £10,050
> Buyer: X · Seller: Y · Stock: LCB / UK IB
> [ NOTIFY SELLER ]   [ SEND TO ADMIN ]

Seller message, copy-to-clipboard, Doug sends it himself:

> Confirmed on 3 x Richebourg 2015 at £2,800/bt. Please hold stock pending
> transfer instructions.

---

## Commercial states — four, and CONFIRMED is terminal

```
INBOUND → EVALUATED → OFFERED → CONFIRMED
```

**There is no CLOSED.** It would rot, because nobody whose job it is would ever
set it. Commercial life ends at CONFIRMED; operational life begins in Ops.

---

## Phase 1c — VESSEL Ops. Deliberately boring.

```
fulfilment
  fulfilment_id        uuid pk
  deal_id              uuid not null references deal
  state                text not null
     -- TO_INVOICE → AWAITING_PAYMENT → PAID → TRANSFER_INSTRUCTED → COMPLETE
  buyer                text
  seller               text
  buy_price            numeric(14,2)
  sell_price           numeric(14,2)
  margin               numeric(14,2)
  invoice_number       text          -- RECORDED, not generated
  invoice_sent_on      date
  payment_received_on  date
  warehouse            text
  transfer_reference   text          -- RECORDED, not instructed
  completed_on         date
  notes                text
  created_at           timestamptz not null
```

**The distinction that matters: VESSEL is the control layer, not the service.**

- It records `Invoice sent: INV-2026-184`. It does **not** generate an invoice.
- It records `LCB transfer instructed, ref LCB239182`. It does **not** instruct
  the transfer.

No accounting, no PDF generation, no warehouse integration, no payment
provider. One list an administrator can work from, where each state corresponds
to a real job somebody is actually doing — which is why these states will get
updated and `CLOSED` would not have been.

Created automatically on CONFIRMED. Visible as a simple queue, usable on a
phone or a laptop.

---

## The operating target

**Unambiguous ordinary offer: inbound to evaluated in under 30 seconds.**
Evaluated to outbound offer: under another 30.

An ambiguous Leroy, a Krug edition, a photo of a want-list wine — all allowed
to be slower, and the slowdown should read as reassurance rather than lag. Say
so on screen: *"checking which Leroy"* is a better message than a spinner.

**Never sacrifice correctness to hit the target.** The want-list gate fires
every time on those twenty producers by design, so those wines will never hit
30 seconds. That is the system working.

---

## NOT NOW. Explicitly out of scope.

Invoice generation · shipment engine · accounting · warehouse integration ·
WhatsApp Business API · inbound email parsing · iOS Share sheet · CRM · buyer
preference engine · automated broking · offer expiry · any new merchant
adapter · a mobile Cellar Desk · any change to the pricing core.

Several of these are good ideas for Phase 2. None of them is Phase 1, and the
reason to hold them is that **Doug has not used Phase 1 yet** and his behaviour
should decide what comes next.

---

## The product test — apply it to anything you are tempted to add

- Does it help Doug understand an incoming wine faster?
- Does it improve pricing confidence?
- Does it make creating an offer faster?
- Does it reduce the chance of a costly mistake?
- Does it get the offer in front of a buyer faster?

If not, it does not belong in Pocket.

---

## Order of work

1. Hosting. Report the URL.
2. `inbound_offer` + NEW + CANDIDATE, with the photo gate enforced.
3. EVALUATE, facts only.
4. The `parcel_trade` basis + CREATE OFFER.
5. SHARE, reusing 0025 and 0035.
6. CONFIRM + `fulfilment` + the handoff messages.
7. Ops queue.

Stop after each and report. Doug will be using this daily, so his reaction to
step 3 should shape step 4.
