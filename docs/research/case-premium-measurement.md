# The 5% case premium, measured

24 September 2026. Data: `case-premium-measurement.json` (27 paired observations).

Claude Code ended decision 0016 by saying the 5% "should be replaced by a
measured basis once we hold enough paired same-day observations of one wine in
two units". We can hold them today, so I went and got them.

## Method

Bordeaux Index publishes loose bottles and cases of the same wine, in the same
card, in the same response. That is the paired same-day observation the decision
asked for, and it needs no assumptions about timing or market drift.

Thirty Burgundy producer pages (24 returned stock), 512 wine cards. Kept only
**In Bond, 750ml** offers of the same wine and vintage. For each wine and pack
size: `ratio = (best case price ÷ pack size) ÷ best loose-bottle price`.

27 usable pairs across 12 domaines, vintages 1999–2020.

## Result: the premium is zero

| | |
|---|---|
| Median ratio | **1.0000** |
| Mean ratio | 0.9737 |
| Exactly at parity | 10 of 27 |
| Within ±5% | 16 of 27 |
| Below 0.95 | 7 |
| Above 1.05 | 4 |
| Range | 0.7038 → 1.1525 |
| 10th–90th percentile | 0.8184 → 1.0639 |

**Bordeaux Index prices a case at the same per-bottle rate as a loose bottle in
the majority of cases**, and when it differs, it is slightly more often *cheaper*
per bottle in the case, not dearer. Ten pairs are identical to the penny, which
says the merchant is pricing per bottle and multiplying.

Examples at each end:

- **Parity**: 2013 Mugneret-Gibourg Vosne-Romanée — £225 loose, and £225 a bottle
  in 2s, 6s and 12s alike.
- **Case cheaper**: 2014 Lignier-Michelot Clos de la Roche — £175 loose against
  £123.17 a bottle in six (−30%). 2007 Fourrier Clos Saint-Jacques — £559 against
  £434.42 in twelve (−22%).
- **Case dearer**: 2006 Roumier Chambolle Les Cras — £600 loose against £691.50
  in six (+15%). 2005 Dujac Clos de la Roche, +6.7%.

## What it means for decision 0016

**The +5% is the wrong adjustment.** It is not wrong by much at the centre — the
measured centre is 0% and 5% is inside the noise — but it is wrong in a specific
way: it biases every derived figure *upward*, and a derived figure that is too
high raises the UK Reference, which is the direction that makes us overpay and
lets us overprice a client. Parity has no such bias.

Recommendation: **set `CASE_PREMIUM = Decimal("1.00")`** and keep everything else
about 0016 exactly as built. Record the measured distribution beside it.

Two things this does **not** change, and both should stay:

1. **`DERIVED_FROM_CASE` must keep forcing review.** The spread is the real
   finding: a quarter of the pairs sit more than 5% from parity and the tails run
   to −30% and +15%. Whatever constant we choose, a derived figure can be a long
   way out on any individual wine. The flag is the safeguard, not the constant.
2. **Exact-unit comps still rank first.** Nothing here argues for trusting a
   derived figure over a real one.

## Honest limits

- **One merchant.** These are all Bordeaux Index, and several are LiveTrade
  listings from different sellers on one platform. A merchant that hand-prices
  cases separately could look different.
- **I tried to get a second and could not.** Goedhuis Waddesdon: 8,750 variants,
  2,194 In Bond 750ml rows, and exactly **one** wine listed in both loose and
  case form. Merchants that sell only by the case cannot answer this question.
- **27 pairs is small**, and Burgundy only.
- This measures *within one merchant*. Decision 0001's original −17.3%/+20.0%
  range measured *across* merchants, which mixes pricing policy with genuine
  market spread. The two are not in conflict: within a merchant, cases and loose
  are usually the same price per bottle; across merchants, everything varies.

## What would settle it

Every adapter that meets a wine in two units on the same day should record the
pair. After a few hundred observations across five or six merchants the constant
stops being a judgement call. That is a small addition to the collection step and
worth doing while the traffic is happening anyway.
