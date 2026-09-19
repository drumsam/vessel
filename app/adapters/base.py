"""Adapter contract.

`fetch` is the only method that touches the network. `normalise` is pure and is
tested against committed fixtures with no network at all. Every adapter ships
with fixtures captured from a real response.

An adapter never decides whether an offer becomes a benchmark. It produces
normalised candidates; identity resolution attaches an approved `wine_id`; the
deterministic benchmark disposes.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Protocol, Sequence

from app.core.enums import Reject
from app.core.models import Offer


@dataclass(frozen=True)
class Rejected:
    """A raw record that could not be normalised. Never silently dropped."""
    raw: dict
    reason: Reject
    detail: str = ""


@dataclass(frozen=True)
class Candidate:
    """A normalised offer that does not yet carry an approved canonical wine id.

    `producer_text` / `cuvee_text` are the merchant's own words. They are the
    INPUT to identity resolution and are never read by the pricing core.

    `lwin7` is the merchant's published LWIN-7, as a string, or None. It is a
    claim by the merchant, not an approval: identity resolution decides whether
    to believe it (see Registry.resolve).

    Contract: if the offer carries any condition flag, `condition_notes` must hold
    the merchant's own wording the flag was read from. A flag without its prose
    cannot be checked by an operator or shown to a buyer.
    """
    offer: Offer            # offer.wine_id is "" until identity approves one
    producer_text: str
    cuvee_text: str
    lwin7: Optional[str] = None

    def __post_init__(self) -> None:
        if self.offer.condition_flags and not (self.offer.condition_notes or "").strip():
            raise ValueError(
                f"{self.offer.offer_id}: condition flags "
                f"{sorted(f.value for f in self.offer.condition_flags)} without the "
                "merchant's wording in condition_notes")


class Adapter(Protocol):
    id: str                 # "farr"
    merchant: str           # "Farr Vintners"

    def fetch(self) -> Sequence[dict]:
        """Network only. Returns raw records exactly as the merchant published them."""

    def normalise(self, raw: dict) -> Candidate | Rejected | list[Candidate | Rejected]:
        """Pure. No network, no clock, no randomness. Fixture-testable.

        One raw record may yield several candidates (a Bordeaux Index card
        carries one row per pack and duty status)."""


def whole_pence(price: Optional[Decimal]) -> bool:
    """True if `price` is an exact number of pence. Farr's feed publishes some
    prices as float32 noise (308.329986 for WineId 230806 on 2026-09-19). That
    is not a price anyone printed, and rounding it would be an estimate."""
    return price is not None and price == price.quantize(Decimal("0.01"))


def require(value: Optional[object], raw: dict, reason: Reject, detail: str = "") -> object:
    """Fail closed: a field that cannot be read is a rejection, never a guess."""
    if value is None:
        raise _RejectSignal(Rejected(raw=raw, reason=reason, detail=detail))
    return value


class _RejectSignal(Exception):
    def __init__(self, rejected: Rejected):
        self.rejected = rejected
        super().__init__(rejected.reason.value)
