# Referral mechanics in detail, and a five-year economic model

7 October 2026. Part one is how a referral physically works, screen by screen.
Part two is the economics with light operations across Asia.

Every figure in part two is illustrative on stated assumptions. The assumptions
are written down so you can argue with each one.

---

# Part one · How a buyer actually refers someone

## The moment

A member has just bought. The confirmation screen says the wine is theirs — and
directly below it:

> **You have one invitation.**
>
> Someone who'd appreciate this. They skip the waitlist, and when they buy for
> the first time you both get first look on the next three drops.
>
> **[ Invite by WhatsApp ]**   **[ Copy link ]**

One tap. No form, no "enter your friend's email", no address-book permission
request.

## What the WhatsApp tap does

It opens WhatsApp's own share sheet with the message pre-written and the link
already in it — plain `https://wa.me/?text=…`, which works on iOS, Android and
desktop with no integration and no API approval:

> I use VESSEL to buy wine from private cellars — properly priced, with the
> merchant evidence shown on every line. Members can invite one person. Here's
> mine: vssl.co/i/8K2M4P

The member picks the contact themselves, inside WhatsApp. **We never see their
contacts and never send anything on their behalf.** That matters more in this
market than in any other: this is a crowd that will not forgive a platform that
messages their friends.

**Copy link** gives the same URL for WeChat, Signal, iMessage, LINE, or a group
chat. Hong Kong collectors live in WhatsApp and WeChat groups; the link has to be
paste-able anywhere, and the attribution has to work from a pasted link, not just
from our button.

## What the invited person sees

`vssl.co/i/8K2M4P` is a page, not a signup form:

> **James Wu has invited you to VESSEL.**
>
> Wine from private cellars. Priced against live merchant offers, with the
> evidence shown on every line.
>
> **This Thursday:** 31 lines from two Hong Kong cellars. Burgundy grand cru,
> mature Bordeaux, Champagne. From HK$780 a bottle, 17–34% below local retail.
>
> Recently: *Confuron Romanée St-Vivant 2018, 6 bottles — sold in 14 minutes.
> Taittinger Comtes 2006, 12 bottles — 2 hours. Montrose 2003, 6 bottles — same
> day.*
>
> **[ Accept invitation ]**  ·  about a minute

Three things on that page do the work: **the referrer's name**, so it's a person
vouching rather than a brand advertising; **what's actually in Thursday's drop**,
so there's something to want; and **proof that things sell**, so it reads as a
market rather than a shop window.

## Accepting — sixty seconds

1. **Mobile number.** Not email. One-time code. The number is the account.
2. **Name, and city.**
3. **How they store wine** — one optional line, and it quietly tells us whether
   this person is also a future seller.
4. In. They see Thursday's drop immediately.

**Payment details are verified at first purchase, not at signup.** Asking for
bank details before someone has seen a wine they want is where these funnels die.

## How credit is attributed

- The code is in the link; the invited person's **phone number** is the identity,
  so nobody can be referred twice.
- Attribution is **first-touch and permanent**. Whoever invited them keeps the
  credit for life, even if someone else's link arrives later.
- The reward fires **only when the invited member's first purchase is confirmed
  paid** — Whatnot's rule, and the reason you accumulate buyers instead of
  tourists.
- **One invitation at a time.** Consumed when accepted; replaced after a quarter,
  or immediately when the new member's first purchase clears, as the thank-you.
- **Both sides are told.** The referrer gets *"Sarah joined and bought. You both
  have first look on the next three drops."* That message is what produces the
  second referral, and it costs nothing.

## Fraud and taste controls

- Invitations are **private links, never public codes** — nothing to post in a
  forum, nothing to appear on a voucher site. This is also what protects the
  price claim: "17% below market" cannot become "17% below market plus whatever
  code I can find".
- **Every new member is reviewed before the first purchase clears.** Quiet, not a
  committee: who they are, the number is real, payment comes from their own
  account.
- **One invitation per member per quarter.** Nobody becomes an affiliate.
- **A member answers for their guest.** If an invitee doesn't pay, reserves and
  abandons repeatedly, or publicly resells our lines, the inviter's invitation
  right pauses. Say this out loud — it's what makes a sponsored club behave like
  one.
- **Two members claiming the same person:** first accepted link wins, and the
  loser's invitation is returned to them unused. No arbitration, no appeal.
- **Self-referral:** same phone, same payment instrument, or same household
  address as the referrer → reward withheld, invitation not returned.

## The seller side, which matters more

Supply is the constraint, so the seller introduction is a heavier mechanism and a
conversation rather than a tap. On the seller's own approval screen, immediately
after they confirm a mandate:

> **Know another cellar?**
>
> If someone you introduce sells through VESSEL, we pay you **1% of their
> proceeds** — and we cover their transfer and storage costs, so it costs them
> nothing to find out what their cellar is worth.
>
> **[ Introduce someone ]** — give us a name and a number, we'll take it from here

**We make the approach, not them.** The referrer never has to sell anything to a
friend, which is the whole reason this works at this end of the market. On a
£200,000 cellar the 1% is £2,000 against roughly £16,000 of our margin — for
supply we'd otherwise spend two months finding.

## The storage-facility route, which costs nothing

Every seller is asked which warehouse they use, and we record it. Collectors who
store in the same building know each other. One happy seller at a facility is a
warm introduction to five more, and the sentence that travels is specific:
**"42 lines, £46,000, paid in eleven days, I ticked boxes."** Not "great
service". Ask each seller for permission to use their numbers; most will give it.

## Tracking, deliberately minimal

Five fields: `invite_code`, `inviter_id`, `invitee_phone`, `accepted_at`,
`first_purchase_at`. Three numbers from them:

- invitations sent
- share accepted
- share of accepted who buy within 60 days

That is the entire referral analytics layer. Nothing else gets built until one of
those three numbers is disappointing and we need to know why.

---

# Part two · The five-year model

## Per cellar, which is the only unit that matters

A cellar is presented. Part of it is listable — evidence rule plus curation.
Listed wine sells at the VESSEL price. We take 8% of what sells.

**On year-three assumptions:**

| | |
|---|---:|
| Cellar market value presented | £900,000 |
| Listed (35%) | £315,000 |
| At VESSEL price (−18%) | £258,300 |
| Sold (75% sell-through) | £193,725 |
| **Seller receives** | **£178,227** |
| **VESSEL revenue (8%)** | **£15,498** |
| Variable cost | £4,029 |
| **Contribution per cellar** | **£11,469** |

For scale: the Hong Kong cellar already in hand is 561 lines and roughly 3,544
bottles, and the lines I priced averaged £268 a bottle. A £900k average presented
value is the right order of magnitude for the sellers you describe — but it is
the single assumption most worth checking against the first ten cellars, because
revenue moves with it one-for-one.

## Years one to five

No inventory ever owned, no debt, referral-led growth, third-party operations in
every market.

| Year | Cellars | Market presented | Listed | Sold | Revenue | Gross | Fixed | **EBIT** | Margin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 24 | £21.6m | £5.4m | £2.8m | £225k | £166k | £114k | **£52k** | 23% |
| 2 | 60 | £54.0m | £16.2m | £9.2m | £735k | £544k | £296k | **£248k** | 34% |
| 3 | 120 | £108m | £37.8m | £23.2m | £1.86m | £1.38m | £575k | **£801k** | 43% |
| 4 | 216 | £194m | £73.9m | £47.2m | £3.78m | £2.80m | £925k | **£1.87m** | 50% |
| 5 | 336 | £302m | £121m | £79.3m | £6.35m | £4.70m | £1.32m | **£3.38m** | 53% |

**Assumptions, stated:**

- Cellars per month: 2 → 5 → 10 → 18 → 28.
- Average cellar presented: £900k throughout.
- Listed share: 25% → 40%, improving as merchant sources and a second reference
  market are added.
- Discount: 20% → 18%, tightening as the HK reference lets us price closer.
- Sell-through: 65% → 80%, improving as the buyer room grows.
- Take: **8%**, flat, all five years.

**Variable cost, 2.1% of sold value:** payments 0.2%, logistics 0.5%,
third-party operations 1.0%, insurance 0.1%, seller referrals 0.28%.

**Fixed cost:** people (1 → 3 → 6 → 10 → 14), software, market data including
Liv-ex, compliance and audit, and marketing that stays small precisely because
growth is referral-led. Marketing is £8k in year one and £180k in year five —
under 3% of revenue. If that line has to grow to 15%, the referral engine has
failed and the model is a different one.

## The headcount number to defend

| Year | People | Revenue | Per head | Cellars per head |
|---|---:|---:|---:|---:|
| 1 | 1 | £225k | £225k | 24 |
| 2 | 3 | £735k | £245k | 20 |
| 3 | 6 | £1.86m | £310k | 20 |
| 4 | 10 | £3.78m | £378k | 22 |
| 5 | 14 | £6.35m | £453k | 24 |

**Twenty cellars per person per year** — one a fortnight each. It only holds if
ingestion, pricing, offer-document generation and payment matching are genuinely
automated, which is exactly what has been built. If a person can in practice only
carry ten, headcount doubles and the margin roughly halves. This is the operating
metric to instrument from cellar one: **person-hours per cellar from spreadsheet
received to drop live.**

## What "light ops across Asia" means concretely

VESSEL stays a pricing and software business. Everything physical is somebody
else's.

| Function | Who | Cost shape |
|---|---|---|
| Bonded storage | existing warehouses — HK, Singapore, Tokyo | pass-through, seller or buyer pays |
| Inspection, condition photos | warehouse staff, per line | ~£3–6 a line |
| Bond-to-bond transfer, delivery | local logistics partner | ~0.5% of value, mostly buyer-paid |
| Payments | local rails — FPS in HK, PayNow in Singapore | ~0.2% |
| KYC / AML | third-party verification provider | ~£2–4 a member |
| Tax and compliance | local advisers, retained | fixed, in overheads |
| Inventory risk | **nobody — we never own the wine** | zero |

**Entering a market is three relationships, not an office:** a bonded warehouse,
a logistics partner, a payment rail. Hong Kong is the base. Singapore in year 2,
Tokyo in year 3, Seoul and Taipei across years 4–5.

Each market adds supply *and* demand at the same time, which is why both listed
share and sell-through improve as the business grows rather than degrading. It is
also the main argument for Asia over Europe: the cellars and the buyers are in
the same time zone, the same WhatsApp groups, and — in Hong Kong — the same
duty-free bond.

## Sensitivity — year 3 EBIT (£k)

| Cellars/mo ↓ · Listed share → | 20% | 25% | 30% | 35% | 40% |
|---|---:|---:|---:|---:|---:|
| **5** | −182 | −83 | +15 | +113 | +211 |
| **8** | +54 | +211 | +369 | +526 | +683 |
| **10** | +211 | +408 | +605 | **+801** | +998 |
| **15** | +605 | +900 | +1,194 | +1,489 | +1,784 |
| **20** | +998 | +1,391 | +1,784 | +2,177 | +2,571 |

Two things this says plainly.

**Listed share is worth as much as deal flow.** At ten cellars a month, moving
from 25% to 35% listed is worth £393k of EBIT — the same as finding five more
cellars every month. More merchant sources, the HK reference set, and the
vintage-band check are therefore not housekeeping. They are the second-biggest
lever in the business, and they are cheaper to pull than supply.

**Below roughly eight cellars a month, this doesn't support a six-person team.**
The year-three shape needs ten. Which means the referral engine and the 1% seller
introduction fee are not nice-to-haves — they are what makes year three exist.

## What breaks it

- **Average cellar size.** At £400k rather than £900k, revenue halves. Measure it
  across the first ten cellars before believing year three.
- **Sell-through.** 50% instead of 75% removes a third of revenue. This is the
  number drop quality and curation control, and the one the bands exist to move.
- **The 8%.** If buyers or sellers push it to 5%, year-five EBIT falls by roughly
  £2.4m. Price conviction is a P&L line, not a brand preference.
- **Identity and approval time.** The one irreducible human step. Ten minutes of
  judgement per listed line makes twenty cellars a head impossible.
- **A compliance stop.** Holding buyer funds across two jurisdictions without
  advice is the only risk on this list that ends the business rather than slowing
  it. It needs your adviser before the first sale, not after.
- **HK reference mis-set.** We measured Hong Kong at a median +22% over UK In
  Bond on nine pairs. If that holds across 40–60 pairs, every price so far is
  conservative and the seller is being underpaid by roughly 20%. That is upside,
  but it is upside we should bank deliberately rather than discover.

## The honest summary

Years one and two are a good living for a very small team: **£52k then £248k of
EBIT, with no inventory, no debt and no funding round.** Year three is where it
becomes a business — £1.86m of revenue, £801k of EBIT, six people.

Years four and five turn on two questions only:

1. Can one person process a cellar in half a fortnight?
2. Does the room of buyers grow as fast as the supply?

The first is an engineering answer and most of it is already built. The second is
what part one of this document is for.

---

## Sources for the referral mechanics

- [Monzo golden tickets — Tom Blomfield](https://tomblomfield.com/post/691384431502557184/monzo-growth)
- [Whatnot buyer referral programme](https://help.whatnot.com/hc/en-us/articles/4407952429581-Buyer-Referral-Program)
- [Whatnot seller referral programme](https://help.whatnot.com/hc/en-us/articles/4645129783181-Seller-Referral-Program)
- [Robinhood's waitlist as a referral lever — First1000](https://www.first1000.co/blog/robinhood)
- [Soho House halts new members in London, New York, LA](https://thepointsguy.com/news/soho-house-membership-halt/)
- [WhatsApp click-to-chat / pre-filled share links](https://faq.whatsapp.com/5913398998672934)
