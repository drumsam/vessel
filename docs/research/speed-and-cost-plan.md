# Speed and cost — the plan, with numbers

29 October 2026. Companion to `saas-review-2026-10-29.md`.

**File this to `docs/research/` when the Mac is back online.** It is a spec and
the protocol in `docs/research/README.md` applies: Code should not build from a
pasted excerpt.

---

## Part 1 — Cost. It is not where you think.

Current prices, per million tokens:

| Model | Input | Output | Cache read |
|---|---|---|---|
| Opus 5.5 | $4 | $20 | $0.20 |
| Sonnet 5.5 | $2 | $10 | $0.10 |
| **Haiku 5.5** | **$0.10** | **$0.50** | **$0.01** |

A WhatsApp parse is roughly 1,200 input tokens (system prompt, JSON schema and
the message) and 250 output.

| | Per parse | 500 parses/month |
|---|---|---|
| Sonnet 5.5 | $0.005 | **$2.50** |
| Haiku 5.5 | $0.00024 | **$0.12** |

**So the model is not the cost risk.** Even on Sonnet, five hundred offers a
month costs two pounds. A photo costs about a cent on Sonnet — images run up to
4,784 visual tokens — and a tenth of that on Haiku. At two or three cellars a
year plus parcels, this is noise.

### But switch the text path to Haiku anyway — for speed, not cost

Haiku 5.5 supports structured outputs, and a smaller model answers faster.
Since latency is the critical ask and cost is already negligible, the reason to
move is the two or three seconds, not the pennies.

**Split the two paths:**

- **Text → Haiku 5.5.** Pulling stated fields out of a line of text is well
  within it.
- **Photo → Sonnet 5.5.** Reading an accented French cuvée off a label in bad
  light is where the extra capability earns its keep, and the per-image cost is
  a cent.

The provider seam already takes a model per instance, so this is a parameter,
not a redesign.

### Decide it on evidence, not on my assertion

Run both models over the first twenty real inbound messages and compare field
by field: producer, cuvée, vintage, quantity, bottle size, bond status,
location, packaging, ask. Record which fields each got right, wrong, or
correctly left absent.

That eval costs pennies and settles the question permanently. If Haiku matches
Sonnet on the text path, keep it and write the decision record. If it drops a
field the register depends on, keep Sonnet and the £2 a month is the cheapest
insurance in the system.

### Three small savings worth taking

**Downscale photos before sending.** A label does not need twelve megapixels.
Resize to about 1,000px on the long edge: cheaper, and the upload is faster
from a phone on mobile data, which matters more than the tokens.

**Cache the system prompt.** The system prompt and schema are byte-identical
every call. Sonnet 5.5's cache minimum is 512 tokens and a read costs a
twentieth of the input price.

**Thinking is already off** (`between_tools`), which was the big one — thinking
tokens bill as output and this model generation has it on by default.

---

## Part 2 — Speed. Where the time actually is.

| Step | Now | After | How |
|---|---|---|---|
| Capture | 10–20s | ~3s | Share Sheet, home-screen app |
| AI parse | 3–5s | 1–2s | Haiku on the text path |
| Identity confirm | 30s+ | ~5s | Filter the dropdown to the proposed producer |
| **Pricing** | **~55s** | **~0s cached** | **Pre-fetch the register** |
| Offer out | — | ~5s | Step 5 |
| **Total** | **~110s** | **~15s** | |

The target is sixty seconds. One change does most of the work.

### The pre-fetch, concretely

`MAX_OFFER_AGE_DAYS` is 14: by the engine's own rule, merchant evidence stays
valid for a fortnight. And there is now a list of exactly which wines matter —
the 234-row register.

So collect evidence for the register on a schedule and have Pocket read what is
already there. A weekly sweep keeps every row inside seven days, comfortably
within the engine's own tolerance. **Nothing is bent: the collection simply
happens before the offer arrives instead of while Doug waits.**

**Architecture, and it needs no Redis.** The deployed API has no worker and
`redis: unavailable` is expected. Do not add a Redis dependency for this.

- A `collection_queue` table in Postgres: one row per wine, with
  `claimed_at`, `completed_at`, `last_error`.
- A Vercel Cron on the api project fires every few minutes, claims a small
  batch (five wines), collects, writes evidence, marks them done.
- `vercel.json` sets `maxDuration: 60` on the function, so a batch must finish
  inside that. Five wines will not at today's speed — size the batch to the
  measured per-wine time and let the queue take hours. 234 wines spread over
  four hours is roughly one request every nine seconds, which is also the
  politest possible crawl.
- That rate honours what `invecta.co/wine` promises merchants: slow, spaced,
  identified, `robots.txt` respected, off-peak. The published page is a
  commitment, and the sweep is the thing that either keeps or breaks it.

### Two more speed fixes on the uncached path

**Parallelise the adapters.** 55 seconds per wine across seven merchants
implies they run one after another. Run them concurrently and the per-wine time
falls to roughly the slowest single adapter — call it ten seconds. That is a
four- to five-fold improvement on every wine the cache has not covered.

**Stop asking merchants who never stock the wine.** The coverage work already
showed which merchants carry which producers, and that public UK merchant pages
do not list DRC, Leroy, d'Auvenay or Coche-Dury at all. A per-producer adapter
map turns seven calls into two or three — faster, and a third of the load on
merchants who were never going to have it.

### Fast by default, exact on demand

A cached price is a price that **was** true. The 14-day window encodes the
project's tolerance for that, and EVALUATE already shows the read date, which
is the honest version of caching — Doug can see the evidence is three days old.

But on a five-figure line he should be able to pay the ten seconds. Put a
**"re-check now"** control on EVALUATE that forces a live collection for that
one wine and replaces the cached evidence.

That is the right shape for the whole product: instant by default, exact when
the stake justifies it, and never pretending a cached figure is a live one.

---

## Order

1. Filter the dropdown. Hours, and it is the worst friction in the live flow.
2. Haiku on the text path, with the twenty-message eval behind it.
3. Parallelise the adapters. Biggest win per hour of work on the uncached path.
4. The `collection_queue` plus cron pre-fetch. The one that makes the target
   reachable.
5. The per-producer adapter map.
6. "Re-check now" on EVALUATE.
7. Share Sheet, manifest, icon.

Steps 1 and 3 are small and immediate. Step 4 is the one that changes the
product.

---

## One honest note on economics at scale

A crawl billed by function-seconds is the wrong shape for serverless. At 234
wines weekly it is trivial and not worth another thought. If the register ever
becomes thousands of wines swept daily, move the sweep to a cheap always-on box
and leave the API serverless. Noted so it is a known trade rather than a
surprise invoice.
