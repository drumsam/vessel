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
    """
    offer: Offer            # offer.wine_id is "" until identity approves one
    producer_text: str
    cuvee_text: str


class Adapter(Protocol):
    id: str                 # "farr"
    merchant: str           # "Farr Vintners"

    def fetch(self) -> Sequence[dict]:
        """Network only. Returns raw records exactly as the merchant published them."""

    def normalise(self, raw: dict) -> Candidate | Rejected:
        """Pure. No network, no clock, no randomness. Fixture-testable."""


def require(value: Optional[object], raw: dict, reason: Reject, detail: str = "") -> object:
    """Fail closed: a field that cannot be read is a rejection, never a guess."""
    if value is None:
        raise _RejectSignal(Rejected(raw=raw, reason=reason, detail=detail))
    return value


class _RejectSignal(Exception):
    def __init__(self, rejected: Rejected):
        self.rejected = rejected
        super().__init__(rejected.reason.value)
