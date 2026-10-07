# Cellar profile — WFS_260900

Read 5 October 2026. Private seller, trusted source, 8% margin on sales.
Source file: `260900_WFS.xlsx`, one sheet, 582 rows.
Normalised: `cellar-normalised.csv` (561 lines, every original cell preserved in
`raw_row`).

## What it is

**561 lines · 3,544 bottles · 97 producers · vintages 1982–2022.**

An inventory, not an offer list. Six columns: producer, wine, colour, size,
vintage, bottles. No prices, no duty status, no condition, no packaging, no
storage location. The sheet's own total (3,544) matches ours, so nothing is lost
in reading it.

### Region mix, by bottles

| Region | Lines | Bottles | Share |
|---|---|---|---|
| **Burgundy** | 400 | 2,290 | **65%** |
| Champagne | 84 | 855 | 24% |
| Bordeaux | 59 | 300 | 8% |
| Italy | 14 | 82 | 2% |
| Rhône · Spain | 4 | 17 | <1% |

### Where the bottles sit

| Bottles | Lines | Producer |
|---|---|---|
| 454 | 41 | Krug |
| 316 | 40 | Comte Georges de Vogüé |
| 213 | 38 | Roche de Bellene |
| 136 | 10 | Dom Pérignon |
| 129 | 34 | Méo-Camuzet Frère et Sœurs |
| 128 | 18 | Faiveley |
| 113 | 16 | Jean-Jacques Confuron |
| 103 | 2 | **Comte Liger-Belair** |
| 103 | 15 | Hudelot-Noëllat |
| 89 | 20 | Leflaive |

Two lines of Comte Liger-Belair holding 103 bottles is worth looking at closely —
that domaine runs from about £150 to several thousand a bottle depending on the
cuvée, so those two lines alone could be a large share of the cellar's value.

By decade: 2010s 354 lines, 2000s 74, 2020s 60, 1990s 18, 1980s 7. Mostly
current-to-recent, not an old collector's cellar.

## The three things that decide whether this prices

### 1. It is a loose-bottle cellar, and merchants sell cases

Every line is single bottles (`B`), except 15 magnums and 4 halves. Our rule is
exact commercial-unit equality, so a merchant's 6-pack is not a comparable for a
single bottle — unless the Burgundy derivation from decision 0016 applies.

That rule is **Burgundy only**. So:

- **Burgundy, 400 lines, 65% of the bottles — covered.** Case prices convert to
  loose at measured parity, flagged for review.
- **Champagne (84 lines) and Bordeaux (59 lines) — not covered.** They will come
  back NO_MARKET on unit grounds even where three merchants hold the wine.

**This is the decision to make first.** Either we extend derivation beyond
Burgundy, or a third of the cellar cannot be priced from merchant evidence. I'd
extend it — but measured per region, not assumed: I can run the same paired-price
measurement I did for Burgundy against Bordeaux and Champagne at Bordeaux Index
and report the real ratio before we set a constant.

### 2. Forty-eight lines have no usable vintage

45 are NV Champagne and 3 are coded releases:

- **Krug Grande Cuvée 156ᵉ and 157ᵉ** — 41 Krug lines, and the edition number is
  the identity. 156ᵉ and 157ᵉ are different products at different prices; LWIN's
  NV convention (vintage 1000) collapses them. The edition has to live in the
  identity, or every Krug line in the cellar prices as one thing.
- **Bollinger "PN VZ16"**, **Henri Giraud "MV13" / "MV15"** — multi-vintage
  cuvées where the code is the release.
- Eric Rodez "NV – 2018", Krug "157ᵉ", Savart "NV": base-year and edition
  markers in free text.

Champagne is 24% of the bottles here, so this is not an edge case to defer.

### 3. Nineteen lines are magnums or halves

Policy excludes large formats and halves from 750ml comparables in both
directions, so these will be NO_MARKET unless same-format comps exist. Correct,
and worth saying out loud because magnums usually carry a premium the seller will
expect.

## Smaller things found

- **39 duplicate line keys** — same producer, wine, vintage and size listed twice
  (Calon Ségur 1995 appears as 4 bottles and 6 bottles; Montrose 1999; Arlaud
  Charmes 2018; Comte Armand Clos des Épeneaux 2020). Probably different storage
  or acquisition lots. Each needs its own line in the deal, not merging.
- **27 single-bottle lines**, and 95 lines of 12 or more. Quantity matters for a
  buy offer: a single bottle of something is harder to place than a case.
- Producer names use the seller's own shorthand (`Dmn`, `Dom`, `Msn`, `Ch.`) and
  one wine column doubles as an appellation (`St.Emilion`) — the identity
  resolver will need to read producer and wine together, not separately.
- 15 lines are named only as "Chambertin Grand Cru" with the domaine in the
  producer column (Bouchard, Van Canneyt, Jacques Prieur, Jadot, Bernstein,
  Roche de Bellene, Trapet). Those are seven different wines sharing one cuvée
  name — exactly the case the structural identity layer exists for.

## What I need from you

1. **Duty status.** In Bond or duty paid, and if In Bond, which warehouse. It
   changes the price basis for every line and the pricer rejects UNKNOWN.
2. **Condition and packaging.** Loose bottles from a private cellar: any OWC,
   any labels or levels noted, and is there a condition report?
3. **Storage history** — professionally stored throughout, or domestic?
4. **Whether to extend case-to-bottle derivation beyond Burgundy** (see §1). My
   recommendation: measure Bordeaux and Champagne first, then set it per region.

## The margin

8% on sales: we sell at the market reference and buy at **reference × 0.92**.
On a line where the UK Reference is £1,000 a bottle, the offer to the seller is
£920. The pricer already takes a target margin and will show gross profit per
line, with the export gate catching anything negative or above market.

## Suggested order

1. Answer the four questions above.
2. I measure the Bordeaux and Champagne case-to-bottle ratios (one afternoon of
   live data, same method as the Burgundy measurement).
3. I dry-run the top 60 lines by likely value — de Vogüé, Comte Liger-Belair,
   Méo-Camuzet, Leflaive, Krug, Dom Pérignon, the Bordeaux first growths — and
   report depth and indicative prices per line.
4. Claude Code builds the Champagne/Bordeaux derivation and the Krug edition
   identity rule.
5. The whole file goes through the app, and we compare its numbers to mine. That
   is the first real test of the system, and this cellar is a good one for it.
