"""Identity resolution — the ONLY place producer and cuvee names are interpreted.

Everything hard lives here and nowhere else:
  * accents and diacritics
  * cuvee-first vs producer-first merchant naming
  * abbreviations ("Ch", "Dom", "Dne", "CSJ", "VV")
  * aliases ("Ruchottes-Chambertin" vs "Ruchottes-Chambertin Clos des Ruchottes")
  * structural exclusions (grand vin vs second wine; adjacent climats)

The pricing core never sees a producer or a cuvee. It receives an approved
`wine_id` or the record does not reach it.

Resolution order (spec section 2):
  1. the canonical wine table, by normalised key, cross-checked against the
     merchant's LWIN where it publishes one
  2. the canonical wine table, by normalised key
  3. controlled aliases
  4. an AI proposal, which must then pass an independent AI verification
     and is still only ever a PROPOSAL

Anything unresolved returns None. None means REVIEW, never a guess.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------- normalisation


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str) -> str:
    s = strip_accents((s or "").lower())
    for ch in "-–—'’.,()":
        s = s.replace(ch, " ")
    return " ".join(s.split())


_PRODUCER_PREFIX = {
    "ch": "chateau", "chat": "chateau", "chateau": "chateau",
    "dom": "domaine", "dne": "domaine", "dom.": "domaine", "domaine": "domaine",
    "m": "maison", "maison": "maison",
}


def norm_producer(s: str) -> str:
    parts = norm(s).split()
    if parts and parts[0] in _PRODUCER_PREFIX:
        parts[0] = _PRODUCER_PREFIX[parts[0]]
    return " ".join(parts)


def wine_key(producer: str, cuvee: str) -> str:
    """Fallback identity when LWIN is absent. For Burgundy this is the PRIMARY
    key: Farr publishes LWIN for Bordeaux and null for Burgundy grand cru."""
    return f"{norm_producer(producer)}|{norm(cuvee)}"


# ------------------------------------------------------------------- guard rails

#: Pairs that must NEVER collapse into one another. Asserted in tests.
#: A single collapse is a catastrophic mispricing, not a cosmetic slip.
STRUCTURAL_EXCLUSIONS: list[tuple[str, str]] = [
    # Bordeaux grand vin vs second wine
    ("chateau lafite rothschild|grand vin", "chateau lafite rothschild|carruades"),
    ("chateau mouton rothschild|grand vin", "chateau mouton rothschild|petit mouton"),
    ("chateau latour|grand vin", "chateau latour|les forts de latour"),
    ("chateau margaux|grand vin", "chateau margaux|pavillon rouge"),
    # Burgundy adjacent climats and lieux-dits
    ("domaine armand rousseau|chambertin grand cru",
     "domaine armand rousseau|chambertin clos de beze grand cru"),
    ("domaine armand rousseau|charmes chambertin grand cru",
     "domaine armand rousseau|mazoyeres chambertin grand cru"),
    ("domaine armand rousseau|clos de la roche grand cru",
     "domaine armand rousseau|gevrey chambertin 1er cru clos saint jacques"),
    ("domaine de la romanee conti|echezeaux grand cru",
     "domaine de la romanee conti|grands echezeaux grand cru"),
    ("domaine comte georges de vogue|musigny grand cru cuvee vieilles vignes",
     "domaine comte georges de vogue|musigny blanc"),
    ("domaine comte georges de vogue|musigny grand cru cuvee vieilles vignes",
     "domaine comte georges de vogue|bourgogne blanc"),
    ("jacques frederic mugnier|musigny grand cru",
     "jacques frederic mugnier|bonnes mares grand cru"),
]


@dataclass(frozen=True)
class CanonicalWine:
    wine_id: str
    producer: str
    cuvee: str
    lwin7: Optional[str] = None


@dataclass(frozen=True)
class Alias:
    """A controlled alias, created by an operator correction or by a reviewed
    AI proposal. Every alias records who approved it and when."""
    key: str                    # normalised wine_key
    wine_id: str
    approved_by: str
    approved_at: str
    note: str = ""


class Registry:
    """In-memory view of the canonical wine table plus controlled aliases.
    The production implementation reads both from Postgres."""

    def __init__(self, wines: list[CanonicalWine], aliases: list[Alias] | None = None):
        self._by_key: dict[str, str] = {}
        self._by_lwin7: dict[str, str] = {}
        for w in wines:
            self._by_key[wine_key(w.producer, w.cuvee)] = w.wine_id
            if w.lwin7:
                self._by_lwin7[str(w.lwin7)] = w.wine_id
        for a in (aliases or []):
            self._by_key.setdefault(a.key, a.wine_id)

    def resolve(self, producer: str, cuvee: str, lwin7: str | None = None) -> Optional[str]:
        """The name resolves; the LWIN only ever cross-checks it.

        A merchant-published LWIN NEVER resolves identity on its own. It is the
        merchant's mapping of its own listing, not the LWIN database: Farr's
        live feed on 2026-09-19 published 1083129 for both Veuve Clicquot and
        Veuve Clicquot Rosé, so a feed carrying only the Rosé would resolve it
        to the Brut with nothing to contradict it.

        So: no name, no identity. If the name resolves and the LWIN resolves to
        a DIFFERENT wine, that disagreement is itself evidence and neither is
        used. See docs/decisions/0006-merchant-lwin-policy.md; when the real
        LWIN database is imported this can be revisited.
        """
        return self._agree(self._lwin(lwin7), self._by_key.get(wine_key(producer, cuvee)))

    def resolve_candidate(self, producer_text: str, cuvee_text: str,
                          lwin7: str | None = None) -> Optional[str]:
        """Merchant-agnostic entry point.

        Some merchants (Goedhuis) put producer and cuvee in one string with no
        separator. When `producer_text` is empty we try the whole string as a
        combined field against the registry's combined index.
        """
        if producer_text:
            return self.resolve(producer_text, cuvee_text, lwin7)
        return self._agree(self._lwin(lwin7), self._combined(cuvee_text))

    def _lwin(self, lwin7: str | None) -> Optional[str]:
        return self._by_lwin7.get(str(lwin7)) if lwin7 else None

    def _combined(self, text: str) -> Optional[str]:
        combined = norm(text)
        for key, wid in self._by_key.items():
            p, _, c = key.partition("|")
            if p and c and p in combined and c in combined:
                return wid
        return None

    @staticmethod
    def _agree(by_lwin: Optional[str], by_name: Optional[str]) -> Optional[str]:
        if by_name is None:
            return None                      # a LWIN alone never resolves
        if by_lwin and by_lwin != by_name:
            return None                      # the merchant contradicts itself
        return by_name


def collided_lwins(candidates: list[tuple[Optional[str], str, str]]) -> dict[str, list[str]]:
    """LWIN-7s a merchant uses for more than one wine name in the same capture,
    mapped to those names.

    `candidates` is [(lwin7, producer_text, cuvee_text), ...]. A collision is
    NOT evidence that the merchant is wrong. In Farr's 2026-09-19 feed four of
    six collisions are mapping errors (Jadot Clos Saint Jacques vs Lavaux Saint
    Jacques; Veuve Clicquot vs Rosé; Giacosa Rocche del Falletto vs the
    Riserva; H&H Verdelho vs Verdelho Solera) and two are not: Gaja's Costa
    Russi and Sorì San Lorenzo appear as both "Barbaresco X" and "X" because
    the wine changed appellation. There the LWIN is right and our name key is
    wrong to split them.

    So a collision is routed to an operator, who decides which it is. Discarding
    the LWIN would lose real depth on the Gaja pattern.
    Differences of accent, case and punctuation are not a collision.
    """
    seen: dict[str, dict[str, str]] = {}           # lwin7 -> {wine_key: printed name}
    for lwin7, producer_text, cuvee_text in candidates:
        if lwin7:
            printed = " / ".join(x for x in (producer_text, cuvee_text) if x)
            seen.setdefault(lwin7, {}).setdefault(wine_key(producer_text, cuvee_text), printed)
    return {lwin7: sorted(names.values()) for lwin7, names in seen.items() if len(names) > 1}
