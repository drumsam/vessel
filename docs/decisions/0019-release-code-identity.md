# 0019 — A release code is part of identity, not decoration

**Status:** accepted, 5 October 2026. From a live cellar: 41 Krug lines across
Grande Cuvée 156ᵉ to 169ᵉ, 454 bottles.

## Context

Krug's Grande Cuvée is non-vintage, but it is released in **numbered
editions**, and each one trades at its own level — the market does not treat
156ᵉ Édition the way it treats 169ᵉ. LWIN's NV convention (vintage 1000)
cannot see this at all: it collapses every edition of an NV wine into one
product, because vintage is the only thing LWIN uses to distinguish bottlings
of a cuvée. Also live in the same cellar: Bollinger "PN VZ16", Henri Giraud
"MV13" / "MV15", Eric Rodez "NV – 2018" — the same phenomenon, embedded release
codes in NV naming, appearing across several houses.

Pricing a 156ᵉ line off a 169ᵉ comp (or the reverse) would not be a bad
comparable. It would be comparing two different products that happen to share
a name, which is precisely the failure the identity layer exists to prevent —
no different in kind from pricing a grand vin off its second wine.

## Decision

**`release_code` becomes a third segment of `wine_key`, only when present.**
`wine_key(producer, cuvee, release_code=None)` returns the familiar
`producer|cuvee` for every wine that has never needed a code — which is almost
every wine in the system, and nothing about them changes — and
`producer|cuvee|release_code` for one that does. Two editions of the same
cuvée are, structurally, two different keys, hence two different wine_ids,
with no special-case logic anywhere else.

**A codeless candidate fails closed, by construction, not by a check.** A
wine registered with a release code is never stored under the bare
`producer|cuvee` key — only under its own three-part key. So a candidate with
`release_code=None` computes the bare key, which the registry has no entry
for whenever any edition exists, and `resolve()` returns `None`: straight to
the identity queue. This needed no new guard rail, no exclusion list and no
runtime check for "is this producer+cuvée combination ambiguous" — the same
dict lookup that has always driven this resolver does it, because the key
space itself makes an edition and its own bare name two different things. It
is the same structural instinct this codebase already prefers over a
convention everywhere else (the export gate, the vintage band's flags): make
the wrong state unrepresentable in the key, rather than catching it after the
fact.

**Extraction is a proposal, never an approval, exactly like every other split
this module does.** `split_release_code(text)` reads the ordinal-edition
spellings actually seen — "156e", "156ème", "156th", each optionally followed
by "Édition"/"Edition" — and separates the base cuvée from the number:
`"Grande Cuvée 156ème Édition"` → `("Grande Cuvée", "156")`. It changes
nothing about how a `wine_id` gets approved: the result still has to resolve
against the canonical table or an alias, through the registry, exactly as a
plain producer/cuvée split does today. An operator approves a new edition's
canonical record the first time it is seen, the same as for any new wine.

**The match is anchored to the end of the string, on purpose.** Krug writes
the edition as the last thing in the name, in every live spelling seen. A
Bordeaux classification — "3ème Cru Classé" — also contains an ordinal number,
but with more text after it. Anchoring to the end means the classification
case simply never matches: there is text after the number, so the pattern
cannot reach end-of-string there, and `split_release_code` returns the text
unchanged. This is deliberately narrower than "strip any ordinal number" —
a false strip here would invent an identity split nobody approved, silently
renaming every third growth's cuvée to "Cru Classé". Tested directly
(`test_a_bordeaux_classification_number_is_never_mistaken_for_an_edition`).

**MV13, PN VZ16 and "NV – 2018" need no extraction at all.** Each is already
a complete, distinct cuvée name with no shared base underneath it — unlike
Krug's "Grande Cuvée", which recurs across fourteen editions, nothing here
recurs. Two different code strings are already two different `wine_key`s with
zero new mechanism. `release_code` stays available if a producer is ever
found reusing one base cuvée name across several such codes, Krug-fashion, but
nothing in the brief's examples beyond Krug actually has that shape, so
nothing beyond `wine_key`'s existing behaviour was built for them.

## Consequences

- `app/core/` is untouched. Identity — all of it, release codes included —
  resolves before the core ever sees a line; the core still receives only an
  approved `wine_id`, per invariant 1.
- Schema: `wine.release_code` (nullable text), migration 0015.
  `wine_key` keeps its UNIQUE constraint — nothing about uniqueness changed,
  since the key itself now has three possible segments instead of two.
- `CanonicalWine`, `Alias` (via its existing `key` field), `Candidate` and
  `Registry.resolve`/`resolve_candidate` all gained an optional
  `release_code`. `Registry._combined` (the Goedhuis-style, producer-less
  path) was rewritten to split on every `|` rather than the first one, so a
  release-coded wine is reachable through a combined field too — tested
  directly rather than left as an untested side effect of a three-part key.
- Console: the wine picker in `web/app/deals/[dealId]/line.jsx` and
  `web/app/queue/page.jsx` shows the code in parentheses, so 156ᵉ and 169ᵉ
  read as two distinct choices rather than one entry appearing twice.
- Not done in this decision: wiring `split_release_code` into any specific
  merchant adapter's `normalise()`. That needs a live capture of a Champagne
  house's listing — Bordeaux Index, Farr or another adapter actually showing
  Krug, Bollinger, Giraud or Rodez — which this session does not have on
  hand. House style here is a captured fixture before a trap becomes a
  regression test; inventing one would be exactly the kind of guess this
  decision exists to refuse. The mechanism is built and tested at the
  resolver level, ready for the first adapter that needs it.
