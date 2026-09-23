# Mainstream-Burgundy control set — result

Run 21 September 2026. Locked `app/core/benchmark.py`, unmodified. Evidence and
scripts: `control/lines.js`, `*-result.json`, `run_control.py`,
`control-benchmark.json`.

## Why this run exists

The Rousseau / de Vogüé / Mugnier proof came back with thin depth (READY 0, REVIEW 5,
NO_MARKET 15). The open question was whether that was **the pricer** or **the
wines**: collector-tier back vintages only live with a few specialists. So we took
a mainstream list — Lea & Sandeman's entire live In Bond Burgundy, 70 distinct
wine / vintage / format lines, 2011–2022, all 750ml or larger formats, quality
producers — and priced it against every other merchant we can collect today.

## Headline

**The thin depth is the market, not the pricer.** Even for current-release,
widely-distributed Burgundy, the second UK merchant usually is not there.

| View | READY | REVIEW | NO_MARKET |
|---|---|---|---|
| **A.** L&S list priced as if an unrelated seller brought it (L&S counts as one merchant) | 8 | 62 | 0 |
| **B.** L&S *is* the seller (its own offer excluded) — the realistic view | **2** | **6** | **62** |

View B is the one that matters: if Lea & Sandeman offered us this list, the
pricer could produce a ready UK Reference for **2 of 70 lines**, a one-merchant
review for 6, and nothing for 62. That is the fail-closed answer, and it is
correct: we have no second price for those wines.

## Merchants searched

| Merchant | Method | Burgundy rows seen | Verified comps added |
|---|---|---|---|
| Farr Vintners | full list | 1,116 | **0** (holds different vintages) |
| Goedhuis Waddesdon | full catalogue | — | **4** (all brokered, SKU-declared) |
| Lay & Wheeler Trading | per-wine search | — | **1** confirmed · 1 rejected · 1 ambiguous |
| Bordeaux Index | 49 producer×vintage deep searches | 229 offer rows | **5** (13 listings) |

Five of the 70 lines' producers have no slug at Bordeaux Index at all (Barraud,
Tribut, Huguenot, Raquillet, Rémi Jobard).

## The lines with a market

| Line | Wine | L&S | Other merchants (best) | View B state |
|---|---|---|---|---|
| L68 | 2015 Clos des Lambrays 6×75 | 1,300 | Goedhuis 1,300 · L&W Trading 1,414 | **READY**, Ref 1,414 |
| L52 | 2018 Clos des Lambrays 6×75 | 1,200 | BI 1,125 · Goedhuis 1,250 | **READY**, Ref 1,250 |
| L10 | 2021 Clerget Échezeaux En Orveaux 6×75 | 795 | BI 862 | REVIEW (ONE_COMP) |
| L21 | 2020 Mugneret-Gibourg Vosne-Romanée 6×75 | 1,200 | BI 2,070 | REVIEW (ONE_COMP) |
| L30 | 2020 T. Liger-Belair NSG Les St Georges 6×75 | 600 | Goedhuis 695 | REVIEW (ONE_COMP) |
| L33 | 2020 Joseph Colin Chassagne blanc 6×75 | 280 | BI 372 | REVIEW (ONE_COMP) |
| L47 | 2019 Lignier-Michelot Faconnières 6×75 | 420 | BI 415 | REVIEW (ONE_COMP) |
| L61 | 2017 Faiveley NSG Damodes 6×75 | 445 | Goedhuis 350 | REVIEW (ONE_COMP) |

Every comp was checked by eye against the live L&S wording, re-read on 21 Sept.

## Findings that need a decision

### 1. With depth 2, "second-lowest" is the highest price — and it moved a lot

This is not a bug, but it is an invariant behaving in a way worth seeing on real
numbers. When exactly two merchants hold a wine, the Reference is the dearer
of the two. In view A three lines went READY with a wide spread:

| Line | Floor | Reference | Spread |
|---|---|---|---|
| L21 Mugneret-Gibourg Vosne 2020 | 1,200 | **2,070** | +72.5% |
| L33 Joseph Colin Chassagne 2020 | 280 | **372** | +32.9% |
| L61 Faiveley Damodes 2017 | 350 | **445** | +27.1% |

`WIDE_SPREAD` is deliberately non-gating (`flags.py`: "with two or more
independent merchants the Reference is sound"). At depth ≥ 3 that reasoning
holds — the Reference sits inside the distribution. **At depth 2 it does not**:
the Reference *is* the tail. L21 would have gone out READY with a UK Reference
72% above a live ask from a named UK merchant.

I have not changed `app/core`. Proposal for Doug's decision:
`WIDE_SPREAD` forces review **only when depth = 2**. One-line change in
`benchmark.py`/`flags.py`, plus a regression test named for L21. This tightens,
never loosens, so it is consistent with fail-closed.

### 2. Brokered offers can be the same parcel as another merchant's stock

L68: Goedhuis (brokered, SKU `-BR-`) at **£1,300.00**, Lea & Sandeman at
**£1,300.00** — to the penny. Two listings, possibly one parcel.

**This is not a mark against brokers.** Much of the trade brokes now, a brokered
offer is a real offer, and it is often the only visible price on a thin wine. The
point is narrower: identical prices may be one parcel seen twice, so counting
them as two merchants overstates how many places the wine can actually be bought.

Operator note only, never gating: "same price as another merchant — may be the
same parcel". The comp stays in the benchmark.

Related, and it matters for the outlier check: on platforms where the holder sets
the price, asking prices skew high. That is another reason the vintage-band check
auto-excludes only *dear* outliers and never cheap ones.

### 3. Case-size mismatches are common and the rule held

Four lines had the right wine in the wrong unit and were correctly rejected
(decision 0001). The instructive one: **L57 Hubert Lamy Clos de la Chatenière
2018** — L&S 12×75 at £1,000, BI 6×75 at £585. Naive doubling says BI is £1,170,
17% dearer; the per-bottle arithmetic would have been silently invented. The
other three were magnum-only or 3-pack offers (L09, L52, L68).

### 4. Coeur de Roy (L31) remains an operator question

L&W Trading lists Dugat-Py "Coeur du Roy **Très Vieilles Vignes**" at £765;
L&S lists "Coeur de Roy". Dugat-Py bottles both. Not counted.

## New traps for the adapter layer

1. **Bordeaux Index returns HTTP 404 for an empty filtered search.** Verified:
   `producer=domaine_des_lambrays&vintage=1990` → 404 while the producer page is
   200. `raise_for_status()` in the current `fetch()` would make every empty
   vintage an error; blanket-treating 404 as empty cannot tell a dead slug from an
   empty vintage. Fix: validate slugs against `/filters.xml`, then treat 404 on a
   known slug as zero rows.
2. **BI producer slugs are not one-per-domaine.** `christian_clerget` +
   `domaine_christian_clerget`; `bernard_dugat-py` + `dugat-py`;
   `domaine_faiveley` + `faiveley` + `joseph_faiveley`; two Stéphane Magnien,
   two Maume. Deep search must query every slug mapped to a producer and union.
3. **Courcel "Grand Clos des Épenots" ≠ "Les Grands Épenots".** BI holds only
   the latter; L&W Trading had it for 2019. Both would have been false comps on
   tokens `[courcel, epenots]`. Structural exclusion pair for the resolver.
4. **One merchant, seven prices.** BI LiveTrade had 2018 Clos des Lambrays at
   seven prices from £1,125 to £1,800 (+60%). Merchant-best handled it.
5. **Lea & Sandeman duplicate rows** — 2021 Germain Morgeot appears twice,
   identical. Harmless under merchant-best; worth a dedupe in `normalise()`.

Identity traps seen across the sweep (all for the resolver's exclusion list):
Rossignol-Trapet vs Nicolas Rossignol · Y. Clerget vs Christian Clerget · Comte
vs Thibault Liger-Belair · Claude Dugat vs Dugat-Py · Rémi vs Antoine/François
Jobard · Stéphane vs other Magniens · Jean-Marc vs Henri Boillot · Joseph vs other
Colins · Anne Gros vs Anne-Françoise Gros · Grands-Échezeaux vs Échezeaux ·
Combe d'Orveau (Anne Gros) vs Combe d'Orveau (Faiveley).

## What this says about coverage

Four merchants plus the seller is not enough for mainstream Burgundy. The
remaining candidates, in expected-yield order for this kind of list: **Lay &
Wheeler retail** (distinct from Trading), **Justerini & Brooks**, **Corney &
Barrow**, **Berry Bros**, **Albany**, **Vinum**, and Fine + Rare as corroboration
only (INDICATION). Liv-ex remains the single largest gain — it is the one source
built to answer "who else holds this".

---

## Addendum — Albany and Vinum added, 23 September 2026

Both feeds were read in full after Doug approved the two sites.

**Albany Vintners** (`/api/ai/wines.json`, 1,279 wines, robots explicitly allows
`/api/ai/`): **one comp** — 2020 Thibault Liger-Belair NSG Les St Georges 6×75
at £690 In Bond. That takes L30 to three merchants and it is now READY in both
views.

**Vinum Fine Wines** (`extranet.hub.wine/html/vinum`, 2,474 rows, 1,186 Burgundy):
**zero comps.** Their Burgundy is older and grander — Jayer, Truchot, Comte
Liger-Belair, Faiveley grands crus — with nothing in this parcel's vintages and
formats. One near miss (Lamy Chatenière 2018 in 3×150, wrong format).

Revised result:

| View | READY | REVIEW | NO_MARKET |
|---|---|---|---|
| A. L&S counts as a merchant | 8 | 62 | 0 |
| **B. L&S is the seller** | **3** | **5** | **62** |

Six merchants, and mainstream Burgundy still prices for three lines in seventy.

New traps: Vinum can print **two prices in one cell** (`£760 / £700`) — parse as
a list and reject an ambiguous row rather than taking the first; `Avail.` carries
a newline inside "Future Arrival". Albany's catalogue holds three unrelated
Magniens (Henri/Charles, Michel, Frédéric) and no Stéphane, plus Pierre-Yves
Colin-Morey and Philippe Colin but no Joseph Colin — the identity traps, live.

Both feeds also produced **vintage-band evidence** for the new outlier check:
Albany 2017 Lamy Chatenière 12×75 £1,550 and 2017 T. Liger-Belair Les St Georges
£660; Vinum 2015 Mugneret-Gibourg Vosne village 6×75 £1,590, which sits with BI's
2016 £1,489 and 2018 £1,223 and against the 2020 £2,070.
