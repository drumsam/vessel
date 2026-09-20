# 0006 — A merchant-published LWIN cross-checks identity; it never resolves it

**Status:** accepted, 20 September 2026. Revisit when the Liv-ex LWIN database is imported.

## Context

Farr publishes LWIN-7 for Bordeaux and null for Burgundy grand cru. Using it
first would add real coverage: "Lafite Rothschild" has no comma, so the
cuvée-first split gives no cuvée and `wine_key` misses it, while the LWIN names
it exactly.

## Evidence

Measured against the live feed, 19 September 2026: 5,841 records, 2,993
carrying an LWIN-7. **Six LWIN-7 codes are used for more than one wine name.**

| LWIN-7 | Names | Verdict |
|---|---|---|
| 1038217 | Jadot Gevrey-Chambertin *Clos Saint Jacques* / *Lavaux Saint Jacques* | mapping error — different wines |
| 1083129 | Veuve Clicquot / Veuve Clicquot *Rosé* | mapping error |
| 1533073 | Giacosa Barolo *Rocche del Falletto* / the *Riserva* | mapping error |
| 1382958 | Henriques & Henriques *Verdelho* / *Verdelho Solera* | mapping error |
| 1099722 | Gaja *Barbaresco Costa Russi* / *Costa Russi* | **correct** — appellation change |
| 1174889 | Gaja *Barbaresco Sorì San Lorenzo* / *Sorì San Lorenzo* | **correct** — appellation change |

Four are the merchant mapping two wines onto one code. Two are the opposite:
the same wine listed under its old and new appellation, where the LWIN is right
and **our name key is wrong to split it**.

Jadot Clos Saint Jacques is £960 per six and Lavaux Saint Jacques is £520. One
priced off the other is an 85% error in whichever direction it falls.

## Decision

**A merchant-published LWIN may never resolve identity on its own.** The name
resolves, through the canonical key or an approved alias; the LWIN's job is to
disambiguate and cross-check.

- No name match, no identity, whatever the LWIN says. This is what stops a feed
  that carries only Veuve Clicquot Rosé from resolving it to the Brut, which
  nothing else in the record would contradict.
- Name and LWIN pointing at different wines is itself evidence: neither is used
  and the record stays unresolved.
- An LWIN a merchant uses for more than one name in one capture is **not
  discarded**. It opens one row in `lwin_conflict` with the LWIN, every name
  the merchant printed against it, and the merchant. Discarding it would lose
  the Gaja depth.

An operator resolves each conflict as one of:

- **same wine** — approve an alias for the spelling that does not resolve yet.
  The identity guard rails still apply: an alias that would bridge a structural
  exclusion is refused, from the conflict queue as from anywhere else.
- **different wines** — record a `wine_exclusion` for the pair and mark that
  merchant's LWIN untrusted in `merchant_lwin_untrusted`. That is persisted, so
  the conflict does not reopen on every collection and the merchant's names
  then stand on their own.

## Why this way round

The LWIN in a merchant feed is the merchant's mapping of its own listing, not
the LWIN database. It is evidence about what the merchant thinks it is selling.
Evidence is worth keeping and worth cross-checking against; it is not an
approval.

## When to revisit

When the real Liv-ex LWIN database is imported, two cases become trustworthy on
their own and should be allowed to resolve without a name match:

1. a merchant LWIN whose canonical LWIN name matches the merchant's printed
   name, and
2. a merchant LWIN an operator has confirmed.

Both need the canonical database to compare against. Until then, name agreement
is required in every case.
