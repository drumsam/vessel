# 0043 — the want-list wine register

**Status:** accepted, 27 October 2026. Doug: "minimum lookup. The
register must be complete enough that when a supplier offers him a wine,
the resolver matches it first time and he types nothing." "STORE IT
PROPERLY — not as a CSV in docs/."

## What this is

Decision 0038 built the want list as IDENTITY RULES — ten producer-match
rules in `app/identity/want_list.py`, and `wine.want_list` /
`seller_line.want_list_ack_by`/`_at` to gate a line once a wine's own
producer field names one of them. It said nothing about which WINES those
producers actually make. This decision is the data for that structure:
twenty producers now (the original ten plus ten Doug added — seven more
Burgundy, three Champagne), and every cuvée found for each one, stored in
`wine` itself rather than left in a document nobody's code reads.

`docs/research/want-list-wines.csv` (Doug's own first pass, commit
`24d60f1` — 67 rows, six producers, 13 flagged UNVERIFIED) stays. It is
the seed input and the audit trail — reviewed as a pull request, same
discipline as `vintage-tiers.csv` — not replaced. `scripts/
load_want_list_wines.py` is the new thing: it reads the CSV and writes
`wine`, idempotently, one row per `wine_key`. The CSV is where a person
argues with a row; the database is where the resolver reads one.

## The ten new producers, and the six new identity traps

Burgundy: Domaine Dujac, Robert Groffier, Comte Liger-Belair, Domaine
Prieuré-Roch, Arnaud Ente, Comte Georges de Vogüé, François Raveneau.
Champagne: Krug, Jacques Selosse, Dom Pérignon.

Four of the ten carry the same shape of confusion decision 0038 already
named for Leroy/Maison Leroy and Comtes Lafon/Héritiers — a second,
unrelated business sharing a name, at a different price — and got the
same treatment in `app/identity/want_list.py`:

- **Comte Liger-Belair** (owns La Romanée) vs **Thibault Liger-Belair**
  (Nuits-St-Georges, unrelated, makes Richebourg) — `requires` the
  adjacent pair, `excludes thibault`, and — Doug's own instruction —
  `always_review`, same as Leroy: a bare "Liger-Belair" defaults to
  Comte but is never auto-resolved silently.
- **Domaine Prieuré-Roch** (Henry-Frédéric Roch) vs **Domaine Jacques
  Prieur** (Meursault/Beaune/Musigny, unrelated) — `requires prieur(e)
  AND roch`, `excludes jacques`. Not hypothetical: the WFS cellar already
  holds a real Jacques Prieur Chambertin. Found while writing the rule:
  stripping the accent from "Prieuré" leaves "prieure" (trailing e), not
  "prieur" — a plain-ASCII typing normalises to "prieur" instead. Both
  are checked; neither alone would have been enough.
- **Domaine Dujac** vs **Dujac Fils & Père** (the family's own négoce
  arm, materially cheaper) — `requires dujac`, `excludes fils, pere`,
  `always_review` — the Leroy shape again, a bare "Dujac" resolves to
  the domaine but is still flagged.
- **Arnaud Ente** vs his brother **Benoît Ente** (a separate domaine) —
  `requires ente AND arnaud`, `excludes benoit`.

The other six (Groffier, de Vogüé, Raveneau, Krug, Jacques Selosse, Dom
Pérignon) match on their own name alone — nothing else on the want list
collides with any of them.

## What stayed out of `app/identity/want_list.py`, on purpose

Three more traps Doug named are cuvée/release-code questions, not
producer-matching ambiguities — this module only ever answers "which
producer," exactly as decision 0038 already drew that line for DRC and
Armand Rousseau:

- **Krug Rosé has its own, separate edition-number sequence** from
  Grande Cuvée's — confirmed live on krug.com (18e-29e for Rosé, 172e-
  174e for Grande Cuvée at research time, two independent counters).
  Needs no new code: `wine_key` already separates them, because `cuvee`
  text ("Rosé" vs "Grande Cuvée") is already part of the key. Krug Clos
  du Mesnil, Clos d'Ambonnay, Vintage and Collection are vintage-dated
  with no edition at all — also just a fact to record, not a rule.
- **Dom Pérignon's Plénitude scheme** (Vintage/"P1" unmarked, P2, P3;
  Rosé and Rosé P2) is a release code on one cuvée, exactly like a Krug
  edition (decision 0019) — "Vintage P2 2002" is a real, confirmed
  wording (and so is "P2 Vintage 2002"; word order is not fixed). The
  register holds ONE row for "Vintage" and ONE for "Rosé", the scheme
  described in `notes`, never a separate row per Plénitude — a live
  offer carrying "P2" still goes through ordinary identity resolution
  and gets its own wine row the first time it is seen, same as any new
  edition.
- **Jacques Selosse's NV cuvées are identified by disgorgement date**
  more often than by vintage — confirmed live in three shapes: a full
  date, a bare disgorgement year ("NV Jacques Selosse Initial (2022
  Disgorgement)"), and a "base vintage + disgorgement date" compound for
  the lieux-dits ("base 17 disg Jan 24"). No parser was built for this:
  no real listing sample was gathered in enough volume to be confident
  of the format rather than guessing it, and Doug asked for the register,
  not a new resolver capability. Recorded as a gap, not papered over.

One fact recorded, not "fixed": **Comte Georges de Vogüé's young-vine
Musigny is sold as "Chambolle-Musigny 1er Cru,"** never labelled
Musigny — confirmed on the estate's own tech sheet ("Musigny in short
trousers," their words). It prices far above an ordinary Chambolle 1er
Cru from anyone else. The register's own row says so; nothing here
reclassifies it, per Doug's own instruction.

One alias confirmed live and loaded: **Berry Bros prints "Mazy-
Chambertin"** for Armand Rousseau's Mazis-Chambertin — the register's
own row (which had stored the wrong, BBR spelling as its canonical
cuvée) is corrected, and `scripts/load_want_list_wines.py
--alias-operator <username>` loads the alias into `wine_alias` (`source
= 'import'`) so a live BBR offer still resolves. `approved_by` is a real
operator looked up by username, never invented — decision 0009's own
rule, applied to a script same as an HTTP request.

One more trap confirmed exactly where Doug said to look: **Leroy prints
a market-release year or a 2-digit "Release" tag** on an ordinary cuvée
whose real vintage is recorded elsewhere — "Vosne-Romanée Aux Brulées
2021 Release" on what is actually a 2009 or 2014 wine, confirmed live on
Berry Bros. "The Krug edition problem appearing in Burgundy" — except
backwards: a Krug edition IS a different wine and must be split out and
kept; a Leroy release year is NOT a different wine and must be split out
and discarded. `app/identity/resolver.py::split_release_code` now strips
a trailing `"<year or 2-digit> Release"` tag before it ever looks for a
genuine edition suffix, discarding it — promoting it to a release_code
would have fragmented one wine's identity by whichever year it happened
to ship, and the register's own un-suffixed row would never have matched
a live listing that carries one. Reaches every existing caller
(`berry_bros_rudd.py`'s own `parse_cuvee`) with no change to that file at
all, because `split_release_code` is already the one place cuvée text
passes through.

## Collection, per Doug's own method

Producer's own site first, where found: Dujac, Robert Groffier, Comte
Georges de Vogüé, François Raveneau, Krug, Dom Pérignon (official site
blocked research by an age-gate; sourced from merchant corroboration
instead, flagged). Jean-Yves Bizot's own site (`domainebizot.com`) is
real but minimal — four cuvée names, no appellation/classification —
filled in from Sotheby's own wine blog and merchant lot pages, cited.
Jacques Selosse has no official site found at all; sourced from
Gault&Millau's winery page, Vinous and named merchants. Berry Bros &
Rudd producer pages, confirmed fetchable and not robots-disallowed
(`/producers` is the alphabetical index; `/search` is the one path
actually disallowed), where no usable site exists or to cross-check:
Comte Liger-Belair, Domaine Prieuré-Roch, Georges Roumier, Pierre-Yves
Colin-Morey ("Maison" on BBR's own taxonomy), Arnaud Ente.

**Dujac's own site confirmed the Fils & Père trap directly, on the same
domain**: négoce wines carry a distinct classification tag in the site's
own data ("Village Négoce Dujac Fils&Père" vs plain "Village") rather
than living on a separate site — and are excluded from this register
entirely, same precedent as Maison Leroy and Olivier Leflaive never
appearing in it either. Dujac's own wine list came from the site's own
JSON data feed (`dujac.com/ajaxify/view/wines`), found in its JS bundle
rather than guessed, since the page itself is client-rendered.

**Domaine d'Auvenay confirmed essentially web-absent**, exactly as Doug
said: not on BBR's own producer index (2,855 producer links checked,
zero matches), no official site. Twelve rows were still recoverable from
a French retailer with an actual d'Auvenay vintage-listing page
(lapassionduvin.com) plus independent merchant lot pages — a real,
if thin, result, not a guess padded out to look complete. One row
("Puligny-Montrachet En La Richarde") carries an unresolved conflict
between that source (reads as village) and a search snippet (claimed 1er
cru) — recorded as a conflict, not silently picked one way.

## What this does not do

Not a change to `app/core/`, `app/identity/resolver.py`'s own wine_key
logic, or decision 0038's gate — this is data plus two small, targeted
identity-matcher/parser additions, same shape as 0038 itself. Not a
disgorgement-date parser for Selosse — recorded as a gap. Not a
reconciliation of every disagreement found between sources (e.g. BBR
calling Comte Liger-Belair's "Aux Lavières" a 1er Cru against the
official site's own "village" — the official site's own word is kept,
the disagreement is in `notes`, not resolved by guessing).

## Consequences

- Migration `0033_want_list_wine_fields`: `wine.appellation`,
  `classification`, `monopole`, `source`, `notes` — nullable (monopole
  excepted, boolean default false). `app/db/schema.sql` updated to match,
  verified byte-equivalent against a fresh migration run.
- `scripts/load_want_list_wines.py` (new): idempotent CSV → `wine`
  loader, `ON CONFLICT (wine_key) DO UPDATE` — never overwrites
  `producer`/`cuvee`/`want_list` on a re-run, only the five new columns,
  so an operator's own correction to a live wine's text is never
  silently reverted by reloading the register. `--alias-operator` loads
  `ALIASES` (the Mazy/Mazis pair) into `wine_alias`. `want_list` is set
  via `is_want_list_producer`, never hardcoded, so a producer-name
  mismatch between this CSV and `app.identity.want_list` is a loud
  failure, not a silent gap in decision 0038's own gate.
- `docs/research/want-list-wines.csv`: grown from 67 rows/6 producers to
  228 rows across all 20 want-list producers; one row corrected (Armand
  Rousseau's Mazis-Chambertin, previously stored under BBR's own "Mazy"
  spelling). Every producer string in the CSV checked to match
  `app.identity.want_list`'s own canonical strings exactly, both by
  `is_want_list_producer` and by set equality — a mismatch here would be
  a silent gap in decision 0038's own gate, not just a cosmetic typo.
- `app/identity/want_list.py`: ten new `WantListRule`s (twenty total).
- `app/identity/resolver.py::split_release_code`: strips a market-release
  year/tag before looking for a genuine edition suffix.
- `tests/test_want_list.py`: two pre-existing tests updated (ten rules →
  twenty; the DRC/Liger-Belair test now asserts the new producer matches
  rather than asserting nothing does — decision 0038's own DRC exclusion
  still holds, the point of the original test), six new tests for the
  ten new rules and traps.
- `tests/test_traps.py`: one new test for the Leroy market-release-year
  strip.
- Verified: migration applied against a fresh database and against the
  live desk database; `load_want_list_wines.py` run twice confirmed
  idempotent (67 before/after on the second run); full offline suite
  green throughout.

## What was not completed in this pass

All 20 producers were completed; two gaps are worth naming directly
rather than leaving implicit:

- Jacques Selosse's six lieux-dits (Chemin de Châlons, Les Carelles,
  Les Chantereines, Sous le Mont, La Côte Faron, Le Bout du Clos) have
  their cuvée names and appellations confirmed but monopole status
  unconfirmed for all six — no source found either confirmed or denied
  another grower sharing the same named plot, and none of the six
  carries the legal "Clos" designation a true walled monopole (like
  Krug's Clos du Mesnil) would. Loaded with `monopole=unconfirmed`,
  which this script's own validation treats as `false` while keeping
  the word in `notes` — never silently promoted to a confirmed "no."
- Domaine Robert Groffier's register (BBR's current stock, 12 wines) is
  confirmed to be BBR's own *current e-commerce listing*, not a
  domaine-published full range — no official Groffier site could be
  found at all (the one domain that looked plausible resolves only to
  Google Workspace mail servers, no site). A real wine this domaine
  makes but is not currently stocked at BBR would not yet be in this
  register.
