# Spec — vintage-neighbour sanity check (outlier detection)

For Claude Code. 23 September 2026. Doug's idea, tested against live Bordeaux
Index data before writing.

## The problem it solves

2020 Mugneret-Gibourg Vosne-Romanée village, 6×75 In Bond:
Lea & Sandeman £1,200 · Bordeaux Index £2,070. Two merchants, so the UK Reference
is the dearer one, and the line goes out ready to price off £2,070 — 72% above a
live UK ask.

Nothing in the pricing core can tell which of the two is wrong, because it only
ever sees one wine and one vintage.

## The evidence that the idea works

Bordeaux Index's own price curve for that exact wine and unit, captured live
23 September:

| Vintage | BI 6×75 In Bond |
|---|---|
| 2016 | £1,489 · £1,543 |
| 2017 | £1,489 · £1,520 |
| 2018 | £1,223 |
| 2019 | none |
| **2020** | **£2,070 · £2,074** |

The neighbours sit in a £1,223–£1,543 band. The 2020 six-pack is 34% above the
top of its own merchant's band for the same wine in the same format.

And a second signal from the same card — BI's own loose bottle:

| Vintage | BI 1×75 | implied per 6 |
|---|---|---|
| 2018 | £207 | £1,242 |
| 2020 | £197 | £1,182 |

BI prices a single 2020 bottle at £197 while pricing its six-pack at £345 a
bottle. In 2017 the same wine is coherent across formats (12×75 £235/btl, 6×75
£248/btl, 3×75 £235/btl). So the 2020 six-pack disagrees with its own merchant's
bottle price, its own merchant's neighbouring vintages, and the other merchant
in the market. Three independent reasons to distrust one number.

## What this is, and what it is not

It is a **sanity check on comps we already hold**. It is not a price source.

Hard rules:

1. A neighbouring vintage price **never** enters Floor, Reference or Median, never
   appears on a client document, and is never interpolated into a missing vintage.
2. No arithmetic across commercial units, ever. Vintage comparison is
   like-for-like: 6×75 against 6×75. The cross-format signal (§3b) is displayed
   as evidence, never converted into a comp.
3. No price is ever adjusted for vintage quality. A better or worse vintage
   **widens** the acceptance band; it never scales a number.
4. Nothing in `app/core/benchmark.py` changes. This lives in
   `app/market/vintage_band.py` and runs after the benchmark, on its result.

## The two checks

### 3a. Vintage-neighbour band

For a comp on line L (approved `wine_id`, vintage V, `bottle_ml`, `pack_size`):

1. Gather every stored offer for the **same `wine_id`**, **same `bottle_ml`**,
   **same `pack_size`**, In Bond, ASK, GBP, buyable, from **vintages of comparable
   quality** — see §4, which replaces the old ±3-year window. Exclude V itself.
2. Require **at least two distinct neighbour vintages**, each with at least one
   merchant. Fewer than two → `band = None`, no flag, and the operator sees
   "not enough neighbouring vintages to check". Silence, not a guess.
3. Per neighbour vintage take the **median of merchant-bests** (the same depth
   discipline as the benchmark). `band_low` = lowest of those, `band_high` =
   highest.
   The band is then tested against **every comparable**, not against
   merchant-bests: BI listed the 2020 Mugneret six-pack at £2,070 *and* £2,074,
   so excluding only the merchant-best promotes the next listing and achieves
   nothing. Found by Claude Code while wiring it; permanent regression test.
4. No tier widening and no quality adjustment: the neighbours are already
   quality-matched by §4, so the band is used as it stands.
5. A comp is a **high outlier** if `price > band_high × HIGH_MULTIPLE` (default
   1.35), a **low outlier** if `price < band_low × LOW_MULTIPLE` (default 0.65).
   Both constants live beside `WIDE_SPREAD_THRESHOLD`, both documented.

Neighbour offers may be up to 90 days old (comps are 14). Age is shown with the
band. A band built only from stale data is labelled as such.

### 3b. Same-vintage cross-format coherence

We already collect cross-unit evidence and refuse to price it. Use it here:
if the same merchant offers the same wine and vintage in another format, and its
implied per-bottle figure differs from the comp's implied per-bottle figure by
more than `FORMAT_INCOHERENCE` (default 30%), record
`MERCHANT_FORMAT_INCOHERENT` against that comp.

The implied per-bottle figures exist **only inside this check's output**. They are
not stored on an offer, not exported, and not shown as a price — they are shown
as "BI: £197/btl loose vs £345/btl in six" so the operator can see the disagreement.

## 4. Quality-matched neighbours (replaces the ±3-year window)

Doug's rule, and it is the right one: **an ordinary vintage prices near another
ordinary vintage even five years away; a great vintage never prices like an
ordinary one.** Proximity in years is a poor proxy for comparability. Quality is
the proxy, and years only break ties.

Selection, in order:

1. Candidate vintages: same `wine_id`, same unit, within **±8 years** of V
   (drift beyond that is real), excluding V.
2. Look up the tier of V and of each candidate in `vintage_tier`, keyed by the
   wine's region and colour (`BURGUNDY_RED`, `BURGUNDY_WHITE`, …).
3. Keep candidates of the **same tier**. If that leaves fewer than two vintages,
   widen once to **tier ±1**. Never wider: a tier-1 vintage is never compared
   with tier 3 or worse.
4. If the register has no tier for V or for every candidate, **no band, no flag**,
   and the operator sees "no vintage quality data for this wine's region". Silence,
   never a guess.
5. Prefer the nearest years when more than six candidates qualify, keeping the
   six closest. Years break ties; they do not decide membership.

### The register

`docs/research/vintage-tiers.csv` ships with the repo: 58 rows covering Burgundy
red and white, 1995–2023, on a 1–5 scale (1 = great, 5 = weak). Table shape:

```sql
CREATE TABLE vintage_tier (
    region      text     NOT NULL,          -- 'BURGUNDY_RED', 'BURGUNDY_WHITE', ...
    vintage     integer  NOT NULL,
    tier        smallint NOT NULL CHECK (tier BETWEEN 1 AND 5),
    tier_label  text     NOT NULL,          -- great | excellent | solid | ordinary | weak
    sources     text     NOT NULL,          -- which published charts were consulted
    note        text     NULL,
    set_by      text     NOT NULL,
    set_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (region, vintage)
);
```

Loaded by `scripts/load_vintage_tiers.py` from the CSV — Doug's call: maintained
as a file in the repo, reviewed together, not a console screen. Changing a tier
is a pull request, which is the right amount of friction for something that moves
prices.

**How the tiers were derived, and why we store our own number.** Three published
charts were read for red (Wine Spectator Côte de Nuits, Wine Spectator Côte de
Beaune, Burgundy Report's 20-point chart) and two for white (Wine Spectator
Burgundy whites, Burgundy Report). Each source was ranked within itself, and our
tier is the consensus of those rankings — **our own derived rating**, not a copy
of anyone's chart. The source names are recorded per row; their scores are not
reproduced. That keeps us clear of republishing someone else's vintage database
and it makes disagreement visible: where sources diverge, the note says so.

Coverage gap to close next: Bordeaux (left and right bank), Champagne, Rhône
north and south, Piedmont and Tuscany. Until a region is in the register, the
band check simply stays quiet for it.

## 5. What happens to an outlier — the asymmetry that matters

**Doug asked for the outlier to be kicked out. Auto-exclusion is safe in exactly
one direction, and I'd hold the line there:**

- **High outlier → excluded automatically**, line flagged
  `COMP_EXCLUDED_VINTAGE_BAND` (a review flag). Excluding a dear comp moves the
  Reference **down**: we pay less and we sell lower. Both are the conservative
  direction, and the line goes to a human anyway.
- **Low outlier → never excluded automatically.** It is flagged
  `LOW_COMP_OUT_OF_BAND` (also a review flag) and the operator decides. Removing
  a cheap comp pushes the Reference **up**, which makes us overpay and lets us
  overprice a client. That is the failure this system exists to prevent, and no
  automatic rule should be able to cause it. Often the cheap comp is the true
  signal — a merchant clearing stock is a real price.

Every automatic exclusion is recorded like a manual correction: the offer, the
band it failed, the multiple used, and a one-click "put it back" that re-runs
the benchmark and records who did it.

If the exclusion leaves one merchant, the line is `ONE_COMP` and reviewed. If it
leaves none, the line is `NO_MARKET`. Both are fine outcomes.

## 6. Output shape

```python
@dataclass(frozen=True)
class VintageBandCheck:
    wine_id: str
    vintage: int
    unit: str                      # "6x750" — display only
    band_low: Optional[Decimal]
    band_high: Optional[Decimal]
    neighbours: list[NeighbourVintage]     # vintage, median, merchant count, as_of
    high_outliers: list[OfferRef]
    low_outliers: list[OfferRef]
    format_incoherent: list[FormatDisagreement]
    tiers_available: bool
    note: Optional[str]            # why the check was not run
```

Attached to the run, not to the benchmark result. The buyer export never contains it.

## 7. Tests (house style — name the merchant, the wine, the size of the error)

1. `test_mugneret_gibourg_2020_six_pack_is_a_high_outlier` — the live figures
   above; BI £2,070 excluded, Reference falls from £2,070 to £1,200, and the line
   is REVIEW, not READY. This is the 72% error the check exists to catch.
2. `test_low_outlier_is_never_auto_excluded` — Goedhuis brokered 2017 Faiveley
   Damodes £350 against L&S £445: flagged, kept, Reference unchanged at £445.
3. `test_band_needs_two_neighbour_vintages` — one neighbour → no band, no flag.
4. `test_band_never_sets_a_price` — a line with no comps and three neighbour
   vintages stays `NO_MARKET`; no interpolation.
5. `test_no_cross_unit_arithmetic_in_band` — a 3×75 neighbour does not
   contribute to a 6×75 band.
6. `test_format_incoherence_is_evidence_not_a_comp` — BI 2020 loose £197 vs six
   at £345/btl: flag raised, no offer created, benchmark arithmetic unchanged.
7. `test_neighbours_are_quality_matched_not_just_near` — a 2004 Burgundy red
   line (tier 5) does not take 2005 (tier 1) as a neighbour even though it is one
   year away; a 2000 line (tier 4) does take 2011 and 2021 (tier 4) eight and
   nine years away — the nine-year one is out of window, so it is excluded and
   the test says why.
7b. `test_no_tier_means_no_band` — a region absent from `vintage_tier` produces
   no band, no flag, and a stated reason.
7c. `test_tier_widening_stops_at_one_step` — with fewer than two same-tier
   neighbours the band may use tier ±1 and never tier ±2.
7d. `test_band_runs_over_every_comparable_not_merchant_bests` — BI's 2020
   Mugneret pair (£2,070 and £2,074): both are excluded, and the Reference falls
   to £1,200 rather than to £2,074.
8. `test_excluded_comp_is_reinstatable_with_provenance`.
9. `test_export_contains_no_band_fields`.
10. `test_stale_neighbours_are_labelled` — neighbours older than 90 days → band
    still computed, `note` says so, flag still raised.

## 8. WIDE_SPREAD — decided

No separate depth-2 gating rule. Doug's decision, 24 September: a wide gap is
answered by comparing against quality-matched vintages, not by a second flag
that says only that the gap exists. `WIDE_SPREAD` stays as it is — informational,
non-gating — and the band check carries the weight.

Both band flags **do** gate (Doug, 24 September): `COMP_EXCLUDED_VINTAGE_BAND`
and `LOW_COMP_OUT_OF_BAND` go into `REVIEW_FLAGS` in `app/core/flags.py`, and the
three constants sit beside `WIDE_SPREAD_THRESHOLD`. This is the one approved
change to the locked core, and it only ever tightens: a line where a dear comp
was thrown out, or a cheap one looks wrong, always reaches a human — not only
when `ONE_COMP` happens to catch it.
