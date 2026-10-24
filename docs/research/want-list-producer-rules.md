# The want list, as identity rules

23 October 2026. Confirmed by Doug: **Domaine** Leflaive, **Domaine** d'Auvenay,
**Domaine** Leroy — not the négociant in any of the three cases.

The remaining five are taken as the top-tier reading, because a client chasing
Domaine Leroy and d'Auvenay is not chasing Hervé Roumier. **Doug to correct any
of these five if wrong.**

---

## The ten canonical producers

| # | Canonical producer | Doug's shorthand | Confirmed |
|---|---|---|---|
| 1 | Domaine de la Romanée-Conti | DRC | by tier |
| 2 | **Domaine Leroy** | Leroy | **yes, explicitly** |
| 3 | **Domaine d'Auvenay** | D'Auvenay | **yes, explicitly** |
| 4 | Domaine Jean-Yves Bizot | Bizot | by tier |
| 5 | Domaine Georges Roumier | Roumier | by tier |
| 6 | Domaine des Comtes Lafon | Lafon | by tier |
| 7 | Coche-Dury | Coche | by tier |
| 8 | Pierre-Yves Colin-Morey | PYCM | by tier |
| 9 | **Domaine Leflaive** | Leflaive | **yes, explicitly** |
| 10 | Domaine Armand Rousseau | Rousseau | by tier |

---

## Match rules

Same form as the existing structural exclusions (the Courcel `clos` requirement,
the `parde` exclusion). `require` tokens must all be present; any `exclude`
token present means no match. Case- and accent-insensitive.

```
DRC
  require   romanee-conti                 (as an adjacent pair, not two loose tokens)
  or        drc
  exclude   liger                         # Comte Liger-Belair owns LA Romanée
  note      cuvée is a SEPARATE field. A cuvée name never implies DRC:
            Richebourg, Romanée-St-Vivant, Échézeaux, Grands-Échézeaux,
            Corton and Montrachet are all made by others.
            ONLY Romanée-Conti and La Tâche are monopoles.

DOMAINE LEROY
  require   leroy
  exclude   maison, negociant, auvenay
  note      a BARE "Leroy" with no qualifier must NOT auto-resolve.
            Maison Leroy is a legitimate different market at a fraction
            of the price. Send it to review, always.

DOMAINE D'AUVENAY
  require   auvenay
  exclude   —
  note      the token is unique, so this is safe. "leroy" appearing
            alongside is expected (same owner) and must not block the match.

JEAN-YVES BIZOT
  require   bizot
  exclude   bizouard                      # Coche-Bizouard, different family

GEORGES ROUMIER
  require   roumier AND (georges OR christophe)
  exclude   herve, laurent
  note      Christophe Roumier is the winemaker AT Georges Roumier — same
            estate, correct wine. Hervé and Laurent are different domaines.
            A bare "Roumier" goes to review.

COMTES LAFON
  require   lafon AND comte                # matches "Comtes Lafon" and "Comte Lafon"
  exclude   heritiers, macon, dominique
  note      Héritiers du Comte Lafon is the family's Mâcon estate — the
            "comte" token alone is NOT sufficient, hence the exclusion.
            Dominique Lafon is a separate négoce label.

COCHE-DURY
  require   coche AND dury
  exclude   bizouard, fabien
  note      "Coche" alone is unpriceable. Review, don't guess.

PIERRE-YVES COLIN-MOREY
  require   (pierre AND yves) OR colin-morey (adjacent pair) OR pycm
  exclude   marc, philippe, bruno, joseph, simon, deleger
  warning   do NOT use "morey" as a standalone required token.
            Morey-St-Denis is an APPELLATION, so "Marc Colin, Morey-St-Denis"
            would falsely match. The pair must be adjacent or the first
            name present.
  note      PYCM also bottles under a négoce arm which prices differently.
            Capture it if the label shows it.

DOMAINE LEFLAIVE
  require   leflaive
  exclude   olivier
  note      Olivier Leflaive is a separate négociant house in the same
            village at a small fraction of the price. Given the money,
            flag this producer for acknowledgement even when it resolves.

ARMAND ROUSSEAU
  require   rousseau AND armand
  exclude   —
  note      a bare "Rousseau" goes to review.
            CUVÉE TIER IS CRITICAL here and the gaps are wide:
              Chambertin / Clos de Bèze  >  Clos St-Jacques
              >  Cazetiers / Lavaux St-Jacques / Charmes  >  Gevrey village
            "Rousseau Gevrey 2015" is five different wines. Never price
            without the cuvée.
```

---

## The policy that matters more than the rules

**On this list, resolve-and-flag — never resolve silently.**

Every line matching a want-list producer should require an operator
acknowledgement once, even when identity resolves cleanly and even when two
merchants agree. The reason is asymmetry: the downside of mistaking Maison
Leroy for Domaine Leroy, or Olivier for Domaine Leflaive, is a 5–20× error on a
line worth thousands. The cost of one extra click is nothing.

Implement as a `want_list` boolean on the producer record, and treat it as a
gating condition in its own right — not a new review flag inside the pricing
core, but a listing-side requirement, the same way decision 0025's invite gate
sits outside the engine.

---

## What this does NOT solve

The rules stop the wrong wine being priced. They do not produce a price.

For these ten producers the merchant route is likely to be very thin — they are
allocated, they sell on release, and a public catalogue shows current stock
rather than the market. Auction results are the real evidence here, which is
what the Wine Market Journal trial is for.

So: these rules are necessary and not sufficient. Build them because a wrong
identity is unrecoverable; find the data separately.
