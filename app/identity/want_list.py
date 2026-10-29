"""The client want list: ten Burgundy producers, as identity rules.

`docs/research/want-list-producer-rules.md` is the spec this file builds,
verbatim — decision 0038. `docs/research/burgundy-target-producers.md` is
the reasoning behind it, not a second source of rules.

This is NOT the resolver's own exact wine_key lookup (`Registry.resolve`,
`resolver.py`): that matches a merchant's already-split producer/cuvee
text against the canonical table. This module answers a narrower,
upstream question — given a raw, unsplit blob of text (what a supplier
actually typed in a WhatsApp message), which of the ten want-list
producers, if any, does it plausibly name? It is a SUGGESTION only. It
never sets a wine_id and never bypasses the existing rule that a seller
line's identity is always approved by a named operator — Leroy's own
rule below ("always_review") is the sharpest version of that, not an
exception to it.

Same shape as the resolver's own structural exclusions
(`STRUCTURAL_EXCLUSIONS`, `PRODUCER_EXCLUSIONS`): a rule never collapses
two different things into one by being too permissive, and every
exclusion recorded here was named in the spec for a reason, not invented.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .resolver import norm

__all__ = ["WantListMatch", "WantListRule", "WANT_LIST_RULES", "match_want_list",
          "is_want_list_producer", "WANT_LIST_PRODUCER_KEYS"]


def _adjacent(tokens: list[str], first: str, second: str) -> bool:
    """True if `first` is immediately followed by `second` in `tokens`."""
    return any(tokens[i] == first and tokens[i + 1] == second for i in range(len(tokens) - 1))


@dataclass(frozen=True)
class WantListRule:
    producer: str
    #: True if this producer's own requirement is met for these tokens.
    requires: Callable[[list[str]], bool]
    #: Any one of these present means no match, whatever `requires` says.
    excludes: tuple[str, ...] = ()
    #: Domaine Leroy only: a clean match must still never auto-resolve.
    #: "Maison Leroy is a legitimate different market at a fraction of the
    #: price. Send it to review, always." (the spec, verbatim).
    always_review: bool = False
    #: The real-world producer(s) this match is most often actually
    #: confused with — previously only ever a code comment; made real
    #: data so the CANDIDATE screen can show the fork directly in its own
    #: wine list (grouped by producer), not only in a warning sentence
    #: above it. Always empty unless always_review is True: a rule with
    #: no confusable alternate has nothing to fork against.
    fork_with: tuple[str, ...] = ()


#: Ten canonical producers, confirmed by Doug for three (Leflaive,
#: d'Auvenay, Leroy — never the négociant in any of the three cases) and
#: taken as the top-tier reading for the other seven, per the spec's own
#: note: "Doug to correct any of these five if wrong" (the spec names
#: five as inference; all seven non-confirmed here carry the same status).
WANT_LIST_RULES: tuple[WantListRule, ...] = (
    WantListRule(
        "Domaine de la Romanée-Conti",
        requires=lambda t: _adjacent(t, "romanee", "conti") or "drc" in t,
        excludes=("liger",),
        # cuvée is a SEPARATE field and never implies DRC: Romanée-St-Vivant,
        # Richebourg, Échézeaux/Grands-Échézeaux, Corton and Montrachet are
        # all made by others too. Only Romanée-Conti and La Tâche are
        # monopoles. "liger" excludes Comte Liger-Belair's own, separate
        # La Romanée monopole.
    ),
    WantListRule(
        "Domaine Leroy",
        requires=lambda t: "leroy" in t,
        excludes=("maison", "negociant", "auvenay"),
        always_review=True,
        fork_with=("Maison Leroy",),
        # A bare "Leroy" must NOT auto-resolve. Maison Leroy is a legitimate
        # different market at a fraction of the price — the single most
        # expensive confusion in Burgundy, per the spec's own reasoning doc.
    ),
    WantListRule(
        "Domaine d'Auvenay",
        requires=lambda t: "auvenay" in t,
        excludes=(),
        # The token is unique, so this is safe on its own. "leroy" appearing
        # alongside is expected (same owner) and must not block the match —
        # Domaine Leroy's own rule already excludes on "auvenay", so the two
        # rules never collide in the direction that would mis-price a wine.
    ),
    WantListRule(
        "Domaine Jean-Yves Bizot",
        requires=lambda t: "bizot" in t,
        excludes=("bizouard",),
        # Coche-Bizouard: different family, different village, a fraction
        # of the price. A glance apart from "Bizot" in hand-typed text.
    ),
    WantListRule(
        "Domaine Georges Roumier",
        requires=lambda t: "roumier" in t and ("georges" in t or "christophe" in t),
        excludes=("herve", "laurent"),
        # Christophe Roumier is the winemaker AT Georges Roumier — same
        # estate, correct wine. Hervé and Laurent are different domaines.
        # A bare "Roumier" satisfies neither disjunct of `requires` and so
        # never matches at all here — it goes to review by failing closed,
        # not by a special case.
    ),
    WantListRule(
        "Domaine des Comtes Lafon",
        # Matches "Comtes Lafon" and "Comte Lafon" alike, per the spec's
        # own worked example.
        requires=lambda t: "lafon" in t and ("comte" in t or "comtes" in t),
        excludes=("heritiers", "macon", "dominique"),
        # Héritiers du Comte Lafon is the family's Mâcon estate — "comte"
        # alone is NOT sufficient, hence this exclusion is required, not
        # optional. Dominique Lafon is a separate négoce label.
    ),
    WantListRule(
        "Coche-Dury",
        requires=lambda t: "coche" in t and "dury" in t,
        excludes=("bizouard", "fabien"),
        # "Coche" alone is unpriceable and matches nothing here — Fabien
        # Coche is the renamed Coche-Bizouard estate, still not Coche-Dury.
    ),
    WantListRule(
        "Pierre-Yves Colin-Morey",
        requires=lambda t: ("pierre" in t and "yves" in t) or _adjacent(t, "colin", "morey")
                           or "pycm" in t,
        excludes=("marc", "philippe", "bruno", "joseph", "simon", "deleger"),
        # Do NOT use "morey" as a standalone required token: Morey-St-Denis
        # is an APPELLATION, so "Marc Colin, Morey-St-Denis" would falsely
        # match on that alone. The adjacent pair "colin morey" (comma- and
        # hyphen-stripped text can bring unrelated words adjacent) is why
        # the full Colin-sibling exclusion list is required, not optional.
    ),
    WantListRule(
        "Domaine Leflaive",
        requires=lambda t: "leflaive" in t,
        excludes=("olivier",),
        # Olivier Leflaive is a separate négociant house in the same
        # village at a small fraction of the price.
    ),
    WantListRule(
        "Domaine Armand Rousseau",
        requires=lambda t: "rousseau" in t and "armand" in t,
        excludes=(),
        # A bare "Rousseau" satisfies neither half of `requires` and so
        # never matches here — review by failing closed. Cuvée tier is
        # separately critical for this producer (Chambertin/Clos de Bèze >
        # Clos St-Jacques > Cazetiers/Lavaux St-Jacques/Charmes > village)
        # but cuvée identification is the resolver's own job, not this
        # module's: this file only ever answers "which producer".
    ),
    # ---- decision 0043: newly added, same discipline as the original ten ----
    WantListRule(
        "Comte Liger-Belair",
        requires=lambda t: _adjacent(t, "liger", "belair"),
        excludes=("thibault",),
        always_review=True,
        fork_with=("Thibault Liger-Belair",),
        # Thibault Liger-Belair is a DIFFERENT person's DIFFERENT domaine
        # (Nuits-St-Georges, makes Richebourg) — not a label of this one.
        # Doug's own instruction: a bare "Liger-Belair" defaults to Comte
        # but still goes to review, same shape as Leroy's own rule above.
    ),
    WantListRule(
        "Domaine Prieuré-Roch",
        # Stripping the accent from "Prieuré" leaves "prieure" (trailing e),
        # not "prieur" — a plain-ASCII typing of "Prieur-Roch" normalises
        # to "prieur" instead. Both are real, so both are checked.
        requires=lambda t: ("prieure" in t or "prieur" in t) and "roch" in t,
        excludes=("jacques",),
        # Domaine Jacques Prieur (Meursault/Beaune/Musigny) is a completely
        # different, unrelated domaine — already live in the WFS cellar's
        # own data (a Jacques Prieur Chambertin), so this collision is not
        # hypothetical.
    ),
    WantListRule(
        "Domaine Dujac",
        requires=lambda t: "dujac" in t,
        excludes=("fils", "pere"),
        always_review=True,
        fork_with=("Dujac Fils & Père",),
        # Dujac Fils & Père is the family's own négoce arm, materially
        # cheaper — same shape as the Leroy/Maison Leroy confusion. A bare
        # "Dujac" resolves to the domaine but is flagged, never silent.
    ),
    WantListRule(
        "Arnaud Ente",
        requires=lambda t: "ente" in t and "arnaud" in t,
        excludes=("benoit",),
        # Benoît Ente is Arnaud's brother, a separate domaine at its own
        # prices — same family name, different estate.
    ),
    WantListRule(
        "Domaine Robert Groffier",
        requires=lambda t: "groffier" in t,
        excludes=(),
    ),
    WantListRule(
        "Comte Georges de Vogüé",
        requires=lambda t: "vogue" in t,  # norm() strips the accent
        excludes=(),
        # Their young-vine Musigny is sold AS "Chambolle-Musigny 1er Cru",
        # not as Musigny — a pricing quirk to record, not a producer-match
        # ambiguity; cuvée identification stays the resolver's own job.
    ),
    WantListRule(
        "François Raveneau",
        requires=lambda t: "raveneau" in t,
        excludes=(),
    ),
    WantListRule(
        "Krug",
        requires=lambda t: "krug" in t,
        excludes=(),
        # Grande Cuvée's edition numbers and Rosé's own, separate edition
        # numbers are a cuvée/release-code question — resolver territory,
        # not a producer-matching ambiguity this module needs to settle.
    ),
    WantListRule(
        "Jacques Selosse",
        requires=lambda t: "selosse" in t,
        excludes=(),
        # Jacques Selosse and Anselme Selosse are the same estate (father
        # and son) — one rule, one canonical producer name, deliberately
        # not two.
    ),
    WantListRule(
        "Dom Pérignon",
        requires=lambda t: "perignon" in t,
        excludes=(),
        # P2/P3 (Plénitude) and Rosé/Rosé P2 are release codes on the same
        # wine, exactly like a Krug edition — resolver territory, not a
        # producer-matching ambiguity.
    ),
)

#: The canonical producer strings, normalised the same way
#: `app.identity.resolver.norm_producer` would read a wine's own stored
#: producer field — used by `is_want_list_producer` to flag an ALREADY
#: APPROVED wine, not to match raw text (that's `match_want_list`, which
#: reads the tokens of the raw text directly).
WANT_LIST_PRODUCER_KEYS: frozenset[str] = frozenset(norm(r.producer) for r in WANT_LIST_RULES)


@dataclass(frozen=True)
class WantListMatch:
    producer: str
    always_review: bool
    fork_with: tuple[str, ...] = ()


def match_want_list(raw_text: str) -> list[WantListMatch]:
    """Every want-list producer whose rule fires for this raw text. A
    SUGGESTION for the operator evaluating a single-line offer — never an
    identity, never auto-applied. Usually zero or one match; a list is
    returned rather than an Optional so an unexpected double match is
    visible rather than silently resolved by picking one."""
    tokens = norm(raw_text).split()
    return [WantListMatch(rule.producer, rule.always_review, rule.fork_with)
            for rule in WANT_LIST_RULES
            if rule.requires(tokens) and not any(x in tokens for x in rule.excludes)]


def is_want_list_producer(producer: str) -> bool:
    """True once a wine's own (already approved, already clean) producer
    field names one of the ten. Used to set `wine.want_list` at write
    time — this is an exact, normalised match against the canonical
    producer string, not the fuzzy raw-text matching `match_want_list`
    does; a wine's producer field is never ambiguous the way a supplier's
    raw text is."""
    return norm(producer) in WANT_LIST_PRODUCER_KEYS
