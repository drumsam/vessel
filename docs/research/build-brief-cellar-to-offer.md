# Build brief — from inventory to client offer

5 October 2026. Written from a live cellar: 561 lines, 3,544 bottles, Hong Kong
bond, private seller. For Claude Code. Priorities in order; each is a decision
record of its own.

## The commercial chain, which the pricer must express

Doug's model, confirmed:

```
UK market reference (per bottle)      M
buyer price            = M × 0.80      (trade buyers move parcels 20% below market)
seller receives        = buyer × 0.92  (our 8% margin on the sale)
                       = M × 0.736
```

On £500,000 of sales that is £460,000 to sellers and £40,000 of margin. The
pricer already takes a target margin; what it does not yet do is model the
**buyer discount as a separate, named step**. Both numbers must appear on the
line: what the buyer pays, and what the seller gets. One is a sale, the other is
a purchase, and conflating them hides where the margin lives.

`settings`: `BUYER_DISCOUNT = Decimal("0.20")`, `MARGIN_ON_SALE = Decimal("0.08")`,
both per-deal overridable, both recorded on the issued offer so a reprice is
auditable.

## 1 · Stock location and landed cost

The cellar is in **Hong Kong bond**. Our whole benchmark is **UK In Bond**. Those
are different markets, and nothing in the schema knows the difference.

- Add `stock_location` to the deal and the line: `UK_BOND`, `HK_BOND`,
  `EU_BOND`, `DUTY_PAID_UK`, `OTHER`, with the warehouse recorded as text.
- `DutyStatus.IN_BOND` keeps meaning "duty suspended", not "in the UK".
- Add a per-deal **landed cost** (freight, insurance, in-warding, per bottle or
  per case, entered by the operator) and show the seller price gross and net of
  it. Never bury it in the margin: a line can be profitable on paper and a loss
  after £3 a bottle of freight.
- The buyer offer states where the stock lies and who pays to move it.

## 2 · Loose-bottle cellars: derivation beyond Burgundy

This cellar is single bottles. Merchants sell cases. Decision 0016 bridges that
**for Burgundy only**, so a third of this cellar — 84 Champagne lines, 59
Bordeaux — comes back NO_MARKET on unit grounds.

Doug's instruction, 5 October: *don't worry about case pricing, use whatever we
can find.* So:

- Extend derivation to **all regions** at the measured Burgundy parity
  (`CASE_PREMIUM = 1.00`), with the same guardrails: `DERIVED_FROM_CASE` gates,
  exact-unit comps rank first, and the operator sees the source unit and price.
- Keep **large formats and halves out**, both directions, as now.
- Keep recording pairs per region (`case_premium_pair` already does this). The
  Burgundy number is measured; Bordeaux and Champagne are assumed until the
  report says otherwise, and the console should say which is which.

## 3 · Non-vintage and edition identity

41 Krug lines across **Grande Cuvée 156ᵉ to 169ᵉ**. The edition is the wine:
each trades at its own level, and LWIN's NV convention (vintage 1000) collapses
them into one product. Also live in this cellar: Bollinger "PN VZ16", Henri
Giraud "MV13" / "MV15", Eric Rodez "NV – 2018".

- Add `release_code` to the wine identity (text, nullable), part of the
  identity key alongside producer, cuvée, vintage and size.
- A seller line with `vintage = 1000` and no release code **cannot resolve** to a
  wine that has one. Fail closed to the identity queue.
- Parse from the seller's own wording, propose, never auto-approve: `156e`,
  `156ème`, `156th`, `MV13`, `PN VZ16` are the live spellings.

## 4 · The client deliverable

A published draft is at the artifact Doug has — treat it as the design target,
not as decoration. What makes it work, and what the exporter must produce:

- **Both numbers per line**: market £/bottle and seller £/bottle, with the line
  total. Nothing presented as a market price unless a merchant offer backs it.
- **Evidence count per line**, visibly. One source reads "1 source" and the
  document says the line is indicative. This is the `ONE_COMP` flag made
  client-facing rather than hidden in the operator console.
- **Named exclusions**: what is not priced and why — lines with no UK market,
  large formats, editions pending. A seller trusts a document that says what it
  cannot do.
- **The method, in four steps**, in the seller's language. Identity, live
  merchant offers, lowest comparable sets the market, then discount and fee.
- **Validity and re-quote**: seven days, then re-priced. Store the settings used
  so the reprice is a diff, not a new guess.
- **Condition basis stated**: professional storage, sound bottles, re-quoted if
  found otherwise.

Export as HTML (web link) and PDF. The buyer sheet is the mirror: buyer price per
bottle, quantity, location, and the market reference it sits below.

## 5 · Deal workflow at 561 lines

The console was built around a parcel, not a cellar. At this size the operator
needs:

- **Value-ordered queue.** Price the lines that carry the money first. Two lines
  of this cellar hold 103 bottles of Comte Liger-Belair; 34 lines of de Vogüé
  hold 316. Sort the work by bottles × best available evidence, not by row order.
- **Bulk identity approval** with per-line confidence, so 400 Burgundy lines do
  not need 400 clicks — approve the confident ones in a batch, queue the rest.
- **Partial offers.** A deal must issue with some lines priced and some marked
  "no market", because that is the honest state of most cellars.
- **Duplicate lines stay separate.** 39 lines here repeat a wine and vintage at a
  different quantity; they are separate lots, not a merge.

## 6 · Confidence by region, up front

From the two control sets: Bordeaux prices on evidence for 36% of lines and
Burgundy for 4%. An operator should see that before starting a cellar, not
discover it line by line. Show per-deal: lines, bottles, and expected coverage by
region from the last control run.

## Suggested order

1. The chain (§0) and the client deliverable (§4) — this is what earns the fee.
2. Derivation beyond Burgundy (§2) — unlocks a third of this cellar.
3. Release-code identity (§3) — unlocks the Krug run, 454 bottles.
4. Stock location and landed cost (§1) — correctness on every cross-border deal.
5. Workflow at scale (§5), then region confidence (§6).

`app/core/` changes needed: the unit screen for §2 (approved) and nothing else.
Everything in §0, §1, §3, §4 lives outside the core.
