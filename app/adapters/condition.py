"""Merchant condition prose -> normalised ConditionFlag set.

Adapters call this and keep the original wording verbatim alongside the flags.
Pricing rules operate on flags; the operator and the buyer document see prose.

Patterns are anchored in strings observed live (see tests/fixtures/). Adding a
merchant means adding patterns here, never loosening the pricing rules.
"""
from __future__ import annotations

import re
from typing import FrozenSet

from app.core.enums import ConditionFlag as C

_PATTERNS: list[tuple[re.Pattern, C]] = [
    # "Non OWC" and "Not in original carton" must NOT read as ORIGINAL_CASE.
    (re.compile(r"(?<!non\s)(?<!non-)(?<!not\sin\s)(?:\boriginal\s+case\b|\bowc\b|\bocc\b)", re.I),
     C.ORIGINAL_CASE),
    (re.compile(r"\brepack(ed)?\b", re.I), C.REPACK),
    (re.compile(r"\bnon[\s-]*owc\b|\bnon[\s-]*oc\b|\bnot\s+in\s+original\s+carton\b"
                r"|\bno\s+original\s+(case|carton)\b", re.I), C.NO_ORIGINAL_CASE),
    (re.compile(r"\bnon[\s-]*pristine\b", re.I), C.NON_PRISTINE),
    (re.compile(r"\b(stained|scuffed|torn|damaged|bin[\s-]*soiled|nicked|marked)\s+labels?\b"
                r"|\blabels?\s+(stained|scuffed|torn|damaged)\b", re.I), C.LABEL_DAMAGE),
    (re.compile(r"\bbottom\s+neck\b|\btop\s+shoulder\b|\bupper\s+shoulder\b|\bmid\s+shoulder\b"
                r"|\blow\s+(fill|level)\b|\bullage[d]?\b|\b(ts|us|ms|bn)\b(?=\s|$)", re.I), C.LEVEL_ISSUE),
    (re.compile(r"\bexcellent\s+levels?\b|\bgood\s+levels?\b|\binto\s+neck\b|\bbase\s+of\s+neck\b", re.I), C.LEVEL_NOTED),
    (re.compile(r"\bcapsule[s]?\b|\bcork[s]?\b|\bwax\b", re.I), C.CAPSULE_OR_CORK),
    (re.compile(r"\bseepage\b|\bweeping\b|\bsigns\s+of\s+seepage\b", re.I), C.SIGNS_OF_SEEPAGE),
]


def normalise_condition(*parts: str | None) -> FrozenSet[C]:
    """Map one or more merchant condition strings onto normalised flags.

    LEVEL_ISSUE wins over LEVEL_NOTED when both match, because
    'excellent levels, ... stained labels' must not read as clean.
    """
    text = " ; ".join(p for p in parts if p)
    if not text.strip():
        return frozenset()
    found = {flag for pattern, flag in _PATTERNS if pattern.search(text)}
    # Negative statements win over positive ones when a merchant says both.
    if C.LEVEL_ISSUE in found:
        found.discard(C.LEVEL_NOTED)
    if C.NO_ORIGINAL_CASE in found:
        found.discard(C.ORIGINAL_CASE)
    return frozenset(found)


def condition_evidence(*parts: str | None) -> tuple[FrozenSet[C], str | None]:
    """(flags, verbatim wording). The general adapter rule: whenever any flag is
    read from merchant text, that text is kept word for word alongside it.

    Adapters whose condition field is pure condition prose (Farr's Variation,
    Bordeaux Index's CONDITION) may keep it even when no flag matches; this is
    the minimum, not the maximum.
    """
    flags = normalise_condition(*parts)
    text = " ; ".join(p for p in parts if p)
    return flags, (text if flags else None)
