"""Identity resolution — the ONLY place producer and cuvee names are interpreted.

Everything hard lives here and nowhere else:
  * accents and diacritics
  * cuvee-first vs producer-first merchant naming
  * abbreviations ("Ch", "Dom", "Dne", "CSJ", "VV")
  * aliases ("Ruchottes-Chambertin" vs "Ruchottes-Chambertin Clos des Ruchottes")
  * structural exclusions (grand vin vs second wine; adjacent climats)
  * non-vintage release codes (Krug's numbered Grande Cuvée editions; decision 0019)

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

import re
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

#: "Dom" before these second words is the monastic title ("Dom Pierre
#: Pérignon"), never an abbreviation of "Domaine" — expanding it would read
#: "Dom Pérignon" as "Domaine Pérignon". Harmless only by accident today
#: (normalisation runs symmetrically on both sides of every match), and
#: wrong the moment a merchant writes "Dom. Pérignon" meaning an actual
#: Domaine, or a real "Domaine Pérignon" is ever registered. Champagne
#: sweep, 9 October 2026 — 136 bottles rode on this reading correctly.
_DOM_IS_A_TITLE_BEFORE = {"perignon"}


def norm_producer(s: str) -> str:
    parts = norm(s).split()
    if parts and parts[0] in _PRODUCER_PREFIX:
        if not (parts[0] == "dom" and len(parts) > 1 and parts[1] in _DOM_IS_A_TITLE_BEFORE):
            parts[0] = _PRODUCER_PREFIX[parts[0]]
    return " ".join(parts)


#: A trailing ordinal edition number: "156e", "156ème", "156th", each optionally
#: followed by the word Edition/Édition. Anchored to the END of the string on
#: purpose — Krug writes the edition as the LAST thing in the cuvée, and so
#: does every live spelling seen. A classification like "3ème Cru Classé" has
#: more text after the number, so the anchor refuses it: this is intentionally
#: narrower than "any ordinal number", because a false strip here invents an
#: identity split nobody approved.
_EDITION_RE = re.compile(
    r"\s*(\d{1,3})\s*(?:ème|eme|ième|ieme|e|th|rd|nd|st)\.?\s*(?:[EÉ]dition)?\s*$",
    re.IGNORECASE)

#: The same edition, word-first: "Grande Cuvee Edition 162" — confirmed live
#: on Bordeaux Index's own regular listing feed, 9 October 2026, where one
#: card ("KRU1621000BT") names the edition this way while every sibling card
#: for the SAME cuvee uses the number-first form above ("Krug, Grande Cuvee
#: 161eme Edition") — one merchant, two orderings, in the same feed.
_EDITION_WORD_FIRST_RE = re.compile(r"\s*[EÉ]dition\s+(\d{1,3})\s*$", re.IGNORECASE)

#: A MARKET-release year, not an edition — the Krug edition problem's mirror
#: image, found in Burgundy (decision 0043). Confirmed live: Berry Bros
#: prints "Vosne-Romanée Aux Brulées 2021 Release" and "... 24 Release" on
#: ordinary Domaine Leroy cuvées whose real vintage (2009, 2014, ...) is
#: recorded elsewhere entirely — the tag says only WHEN the bottle reached
#: the market, not that this is a different wine. Stripped and DISCARDED,
#: never returned as a release_code: promoting it would fragment one wine's
#: identity by whichever year it happened to ship, and the register's own
#: un-suffixed row (built without knowing a future release year) would then
#: never match a live listing that carries one.
_MARKET_RELEASE_RE = re.compile(r"\s*(?:\d{4}|\d{2})\s+Release\b\s*$", re.IGNORECASE)


def split_release_code(text: str) -> tuple[str, Optional[str]]:
    """Pull a release/edition number out of a cuvée string, if one is there.

    "Grande Cuvée 156ème Édition" -> ("Grande Cuvée", "156"). "Grande Cuvée
    169e" -> ("Grande Cuvée", "169"). "Grande Cuvee Edition 162" -> ("Grande
    Cuvee", "162"). "156th" alone -> ("", "156"). "Vosne-Romanée Aux Brulées
    2021 Release" -> ("Vosne-Romanée Aux Brulées", None) — a market-release
    year is noise, discarded before an edition is ever looked for (see
    `_MARKET_RELEASE_RE`). No match -> the text unchanged, release_code None.

    This is a PROPOSAL, exactly like producer/cuvee splitting elsewhere in
    this module (decision 0019): it only shapes what goes into `wine_key`. The
    resolver still requires the result to match or alias to an approved
    canonical wine before any wine_id is used, and an operator approves a new
    edition's canonical record the first time it is seen, same as any new
    wine. Henri Giraud's "MV13" and Bollinger's "PN VZ16" are NOT this pattern
    — each is already a complete, distinct cuvée name with no shared base to
    split from, so wine_key tells them apart with no change here.
    """
    text = _MARKET_RELEASE_RE.sub("", text or "")
    match = _EDITION_RE.search(text) or _EDITION_WORD_FIRST_RE.search(text)
    if not match:
        return text.strip(), None
    remainder = " ".join((text[:match.start()] + text[match.end():]).split())
    return remainder, match.group(1)


def wine_key(producer: str, cuvee: str, release_code: Optional[str] = None) -> str:
    """Fallback identity when LWIN is absent. For Burgundy this is the PRIMARY
    key: Farr publishes LWIN for Bordeaux and null for Burgundy grand cru.

    `release_code` is part of identity, not decoration (decision 0019): Krug's
    Grande Cuvée 156ème Édition and 169ème Édition trade at their own levels,
    and LWIN's NV convention (vintage 1000) collapses every edition into one
    product. A release code appends a third segment, so an edition is simply a
    different key from the bare cuvée — no wine with a code is ever registered
    under the bare `producer|cuvee` key, which is what makes a codeless
    candidate fail closed to the identity queue rather than guessing one: see
    Registry below.
    """
    base = f"{norm_producer(producer)}|{norm(cuvee)}"
    return f"{base}|{norm(release_code)}" if release_code else base


# ------------------------------------------------------------------- guard rails

#: Pairs that must NEVER collapse into one another. Asserted in tests.
#: A single collapse is a catastrophic mispricing, not a cosmetic slip.
STRUCTURAL_EXCLUSIONS: list[tuple[str, str]] = [
    # Bordeaux grand vin vs second wine
    ("chateau lafite rothschild|grand vin", "chateau lafite rothschild|carruades"),
    ("chateau mouton rothschild|grand vin", "chateau mouton rothschild|petit mouton"),
    ("chateau latour|grand vin", "chateau latour|les forts de latour"),
    ("chateau margaux|grand vin", "chateau margaux|pavillon rouge"),
    # Burgundy adjacent climats and lieux-dits, and one domaine's two Épenots:
    # Courcel holds the Grand Clos des Épenots monopole and Les Grands Épenots
    # is a different parcel. Both answer to [courcel, epenots]
    # (control-set report, 21 September 2026).
    ("domaine de courcel|pommard 1er cru grand clos des epenots",
     "domaine de courcel|pommard 1er cru les grands epenots"),
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


#: Producers that must never be read as one another, whatever the cuvée.
#: A wine_key pair cannot express these: the confusion is in the name of the
#: domaine itself, so it would need one pair per cuvée they both make. Every
#: one of these was seen in a live merchant sweep (control-set report,
#: 21 and 23 September 2026), and each would price one grower's wine off
#: another's.
PRODUCER_EXCLUSIONS: list[tuple[str, str]] = [
    ("domaine rossignol trapet", "domaine nicolas rossignol"),
    ("domaine y clerget", "domaine christian clerget"),
    ("domaine comte liger belair", "domaine thibault liger belair"),
    ("domaine claude dugat", "domaine dugat py"),
    ("domaine remi jobard", "domaine antoine jobard"),
    ("domaine remi jobard", "domaine francois jobard"),
    ("domaine stephane magnien", "domaine michel magnien"),
    ("domaine stephane magnien", "domaine frederic magnien"),
    ("domaine stephane magnien", "domaine henri magnien"),
    ("domaine jean marc boillot", "domaine henri boillot"),
    ("domaine joseph colin", "domaine philippe colin"),
    ("domaine joseph colin", "domaine pierre yves colin morey"),
    ("domaine anne gros", "domaine anne francoise gros"),
]


def producers_excluded(one: str, other: str) -> bool:
    """True when these two producers are a recorded confusion. Compared on the
    normalised producer, so "Dom. Dugat-Py" and "Domaine Dugat Py" are one."""
    a, b = norm_producer(one), norm_producer(other)
    return any({a, b} == {norm_producer(x), norm_producer(y)}
               for x, y in PRODUCER_EXCLUSIONS)


@dataclass(frozen=True)
class CanonicalWine:
    wine_id: str
    producer: str
    cuvee: str
    lwin7: Optional[str] = None
    #: An edition/release within the cuvée that trades at its own level — Krug
    #: "156", Henri Giraud "MV13". None for a wine that has never needed one.
    #: Part of the identity key (see wine_key). Decision 0019.
    release_code: Optional[str] = None


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
            self._by_key[wine_key(w.producer, w.cuvee, w.release_code)] = w.wine_id
            if w.lwin7:
                self._by_lwin7[str(w.lwin7)] = w.wine_id
        for a in (aliases or []):
            self._by_key.setdefault(a.key, a.wine_id)

    def resolve(self, producer: str, cuvee: str, lwin7: str | None = None,
               release_code: str | None = None) -> Optional[str]:
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

        `release_code` is looked up EXACTLY as given (decision 0019): a
        candidate with no code computes the bare `producer|cuvee` key, which
        is never the key of a wine that has a code, so it resolves to None —
        fail closed to the identity queue, never to a guessed edition.
        """
        key = wine_key(producer, cuvee, release_code)
        return self._agree(self._lwin(lwin7), self._by_key.get(key))

    def resolve_candidate(self, producer_text: str, cuvee_text: str,
                          lwin7: str | None = None,
                          release_code: str | None = None) -> Optional[str]:
        """Merchant-agnostic entry point.

        Some merchants (Goedhuis) put producer and cuvee in one string with no
        separator. When `producer_text` is empty we try the whole string as a
        combined field against the registry's combined index.
        """
        if producer_text:
            return self.resolve(producer_text, cuvee_text, lwin7, release_code)
        return self._agree(self._lwin(lwin7), self._combined(cuvee_text, release_code))

    def _lwin(self, lwin7: str | None) -> Optional[str]:
        return self._by_lwin7.get(str(lwin7)) if lwin7 else None

    def _combined(self, text: str, release_code: str | None = None) -> Optional[str]:
        combined = norm(text)
        wanted_code = norm(release_code) if release_code else None
        for key, wid in self._by_key.items():
            parts = key.split("|")
            if len(parts) not in (2, 3):
                continue
            p, c = parts[0], parts[1]
            code = parts[2] if len(parts) == 3 else None
            if code != wanted_code:
                continue
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
