# The offer book — design

30 October 2026. Written from Doug's description: *six offers a day from
different people, logged; some sell elsewhere and have to be retired; sell
prices recorded; tombstones composed from them and pasted to the right people;
and a database rather than a refetch every time.*

**This adds one table and changes nothing in the pricing core.** But it moves
where the product lives.

---

## What changes

The build brief models one journey: `inbound_offer → deal`. One offer arrives,
is evaluated, becomes a trade or does not.

What Doug actually does is hold a **book**: thirty or so live offers at any
moment, from eight to ten suppliers, each with an ask, an age and a status,
some of which die without him doing anything. He works *from* the book — picks
lines out of it, prices them, assembles a message, sends it to whoever wants
that kind of wine.

So the shape becomes:

```
inbound_offer  →  THE BOOK  →  outbound selection  →  deal
   (capture)      (lives)        (compose)          (trade)
```

The book is the screen he opens most. Pocket's single-offer flow is how lines
*enter* it, not the whole product.

---

## The insight that makes this more than a list

Every offer he receives is a **datapoint on what a wine costs in the trade**.
Every sale is a datapoint on what it fetches. He is already generating, by
doing his job, precisely the evidence that public merchant pages cannot give
him — and we measured that gap: seven UK merchants reached two independent
sources on 11 of 52 Champagne targets, and his twenty Burgundy producers do not
appear on merchant pages at all.

**His own book is the pricing source for the wines the market will not price.**

But only if the three kinds of evidence are kept apart, because they answer
different questions:

| Class | What it is | What it tells him |
|---|---|---|
| **merchant** | public retail asks (exists today) | what a buyer could pay elsewhere — the ceiling |
| **supplier** | what he is offered, trade level (new) | what he can buy at — the entry |
| **executed** | his own confirmed sales (from `fulfilment`) | what actually clears |

**These must never be pooled into one Floor.** A supplier offering £420 a
bottle and a merchant listing at £600 are not two observations of one price;
they are opposite sides of the same trade. Mixing them would corrupt the Floor
and quietly break decision 0033, which forbids offering at or above it.

The walk-away test then uses two of them properly: the **merchant Floor** sets
the ceiling, and **supplier history** says whether an ask is good by his own
standards rather than the market's.

---

## Schema — one table

```
supplier_offer
  supplier_offer_id  uuid PRIMARY KEY DEFAULT gen_random_uuid()
  inbound_offer_id   uuid REFERENCES inbound_offer(inbound_offer_id)
                       -- provenance: the raw message this came from
  supplier_id        uuid NOT NULL REFERENCES supplier(supplier_id)
  wine_id            uuid NOT NULL REFERENCES wine(wine_id)
  vintage            integer NOT NULL
  bottle_ml          integer NOT NULL
  pack_size          integer NOT NULL
  quantity           integer NOT NULL          -- units available
  bond_status        text
  stock_location     text
  packaging          text
  ask_amount         numeric(14,2) NOT NULL
  ask_currency       char(3) NOT NULL
  ask_basis          text NOT NULL             -- per_bottle|per_case|total
  received_at        timestamptz NOT NULL
  state              text NOT NULL DEFAULT 'open'
                       CHECK (state IN ('open','withdrawn','expired','converted'))
  state_changed_at   timestamptz
  state_note         text                      -- "sold elsewhere, James 30 Oct"
  created_by         uuid NOT NULL REFERENCES operator(operator_id)
```

**No derived per-bottle column.** Unit normalisation is the engine's job and
decision 0028 already governs it. Storing a second version of the price is how
the two drift apart.

**Executed prices need no table.** `fulfilment` already carries `buy_price`,
`sell_price` and `margin`. That is the third evidence class, and it is a query,
not a new structure.

---

## Lifecycle, and never deleting

```
open  →  withdrawn   (sold elsewhere, supplier pulled it)
      →  expired     (too old to still be real)
      →  converted   (became a deal)
```

**A retired offer is never deleted.** The line is dead; the datapoint is not.
"Dujac Clos de la Roche 2017 was offered at £420 on 30 October" stays true
whatever happened next, and in six months that is the evidence nobody else
has. Same discipline as voiding an invoice rather than editing it, and as the
auction evidence rows.

`withdrawn` needs one tap and a free-text note, because the note is where the
reason lives and the reason is sometimes commercially interesting — *"sold
elsewhere within the hour"* is information about the market.

**Expiry should be an age signal, not a deletion.** At six a day the book goes
stale fast. Show age on every line, sort by it, and mark anything past a
threshold as stale — but make Doug confirm. A system that silently retires a
line he could still have sold is worse than a cluttered list.

---

## The thirty-day question, answered precisely

Doug: *"No need to return a look up if we have a price that's within 30 days
old."*

Right instinct, and the number needs splitting in two, because two different
rules are hiding in it.

**For merchant evidence: 30 days is too long, and not by preference.**
`MAX_OFFER_AGE_DAYS` is 14 — the pricing core refuses to use a merchant offer
older than that. A cache window must be shorter than the staleness rule, or the
cache serves evidence the engine would reject. So the merchant cache TTL can be
anything up to 14 days and no more.

Raising it to 30 is possible, but it is a **pricing-core decision** with a
consequence: a month-old ask in a moving market produces a Floor that is
confidently wrong, and 0033 then prices against it. That needs a decision
record and a reason, not a config change.

**For his own book: 30 days is his call and it is defensible.** A supplier's
ask from three weeks ago still tells him what entry levels look like. This is
his data, about his own trade, used to inform his judgement rather than to set
a buyer-facing Floor. Different purpose, different tolerance.

So: **merchant cache ≤ 14 days, book history 30 days or longer, and the screen
always shows which it is reading and how old.**

---

## Composing outbound from the book

The thing he does every day, and the brief does not cover it: select several
lines, produce one message, paste it to a buyer.

- **Multi-select in the book.** Three or four lines, not one.
- **A buyer price per line**, entered by him on the `parcel_trade` basis from
  `buy-side-margin-test.md`. The walk-away price shows beside each field.
- **One tombstone block**, in the format decision 0036 already fixes, with the
  lines in the order he picked them.
- **One copy action**, then he pastes into the right WhatsApp thread himself.

**`assertBuyerSafe()` must cover the whole block, not each line in isolation.**
A multi-line message is a new leak surface: supplier names, his cost, his
margin, and the fact that two lines came from the same supplier. The existing
assertion checks a line; it needs to check a composition.

One more rule worth fixing now: a line that is `withdrawn` or `expired` must not
be composable into an outbound message. Offering a wine that is already gone is
the single most damaging thing this system could help him do.

---

## What this does to the speed problem

Doug is right that a database beats refetching, and it converges with the
pre-fetch plan from a different direction.

Together:

- **The register pre-fetch** keeps merchant evidence warm for the 234 wines his
  clients chase.
- **The book** accumulates trade-level evidence for the same wines, from his
  own flow, at no fetch cost at all.

After a few months the common case is that both are already in Postgres when an
offer arrives, and EVALUATE answers from local data. The network call becomes
the exception rather than the path.

---

## Not now

- **Buyer want-lists and matching.** "The right people" implies a mirror of the
  producer register, on the buyer side. It is the obvious next thing and it
  should wait until the book has been used: matching rules written before there
  is a book to match against would be guesses.
- **Automatic expiry.** Age signal first; see whether he wants it automated.
- **Supplier performance scoring.** Falls out of the data for free later.
- **Any supplier-facing surface.** They message him; they do not log in.

---

## Order of work

1. `supplier_offer` and its states; a confirmed inbound offer writes a row.
2. The book screen: open lines, sorted by age, with supplier, ask and
   age visible. One-tap withdraw with a note.
3. Multi-select plus the tombstone composer, with `assertBuyerSafe()` extended
   to the composition and withdrawn lines excluded.
4. Book history surfaced on EVALUATE: *"you were offered this wine twice before
   — £420 on 30 Oct, £455 on 12 Oct"* — clearly separated from merchant
   evidence, never pooled into the Floor.
5. Executed prices from `fulfilment` on the same panel, once there are any.

Step 4 is the one that compounds. It is also the one that makes the system
better the longer he uses it, which nothing else here does.
