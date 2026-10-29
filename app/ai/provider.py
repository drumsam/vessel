"""Provider-independent AI interface.

Business logic calls the four capabilities below and nothing else. No module
outside `app/ai/` imports an SDK. Swap provider with environment variables:

    AI_PROVIDER=anthropic|openai|gemini
    AI_MODEL=<provider's model id>

Every call returns OUR dataclass, never the provider's response object, and the
caller records provenance to `ai_decision`. A provider's response structure must
never reach the database schema or the pricing core.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# ------------------------------------------------------------------ our schema

@dataclass(frozen=True)
class Provenance:
    provider: str
    model: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class IdentityProposal:
    """A PROPOSAL. Never authoritative. Must pass review_wine_identity() and then
    an operator or an existing alias before it becomes an approved wine_id."""
    producer: Optional[str]
    cuvee: Optional[str]
    vintage: Optional[int]
    bottle_ml: Optional[int]
    pack_size: Optional[int]
    reasoning: str
    provenance: Provenance


@dataclass(frozen=True)
class IdentityVerdict:
    """Adversarial review. Operational outcome only — no numeric confidence score."""
    approved: bool
    objections: list[str]
    provenance: Provenance


@dataclass(frozen=True)
class CompObjection:
    offer_id: str
    objection: str


@dataclass(frozen=True)
class CompReview:
    """The reviewer may REMOVE or FLAG a comp. It may never add a price."""
    remove: list[CompObjection]
    flag: list[CompObjection]
    provenance: Provenance


@dataclass(frozen=True)
class ConditionParse:
    flags: list[str]              # ConditionFlag names
    verbatim: str
    provenance: Provenance


@dataclass(frozen=True)
class InboundOfferProposal:
    """VESSEL Pocket's Screen 2 (CANDIDATE), build brief Phase 1b step 2. A
    PROPOSAL, same discipline as IdentityProposal, and never persisted —
    `app/api/inbound.py` returns it once, in the response to the call that
    produced it; a retry re-derives it from the stored raw record, never
    reconstructs it.

    Every field is None unless the source text or image states it
    explicitly. The model must never infer, estimate, compute or default
    a value -- "Packaging: unknown" is correct where the source is
    silent; a guessed "OWC" is the exact failure this exists to prevent.
    `asking_price`/`asking_currency` may only be populated from a figure
    literally present in the source, labelled as the seller's ask, never
    a figure the model thinks it inferred -- this dataclass carries no
    reference price, no buyer price, no margin, by construction: there
    is no field for one.

    `pack_size`/`quantity` are null TOGETHER whenever the commercial unit
    is genuinely ambiguous ("6 x ... OWC" reads as one case of six or six
    loose bottles, and a case priced against single-bottle comps is
    simply wrong -- decision 0028). `total_bottles` carries the one fact
    that IS clear in that case -- the bottle count -- so the fork the
    operator resolves is "which of these two", never "guess the rest
    too". Set `pack_size`/`quantity` directly only when the source is
    unambiguous about which commercial unit it means.

    `asking_basis` exists because a price with no unit is ambiguous by
    exactly the multiple pack_size would convert by: "GBP420" alone does
    not say whether that is per bottle, per case, or the lot. Populated
    only from an explicit word in the source ("a bottle", "the case", "in
    total") -- never inferred from quantity or pack_size, which would be
    exactly the guess this field exists to refuse.
    """
    category: str                         # 'wine' | 'whisky' | 'unknown'
    producer: Optional[str]
    cuvee: Optional[str]
    vintage: Optional[int]
    bottle_ml: Optional[int]
    pack_size: Optional[int]
    quantity: Optional[int]               # commercial UNITS, never bottles -- null with pack_size when ambiguous
    total_bottles: Optional[int]          # the literal bottle count, when the unit split is ambiguous
    bond_status: Optional[str]            # as stated: e.g. "UK In Bond", "Duty Paid"
    stock_location: Optional[str]         # as stated: e.g. "LCB"
    packaging: Optional[str]              # as stated, or None -- never guessed
    asking_price: Optional[str]           # literal figure read from the source, as a string
    asking_currency: Optional[str]
    asking_basis: Optional[str]           # 'per_bottle' | 'per_case' | 'total', only if stated
    reasoning: str
    provenance: Provenance


# ------------------------------------------------------------------- interface

class AIProvider(ABC):
    name: str

    @abstractmethod
    def resolve_wine_identity(self, raw_description: str, context: dict[str, Any]) -> IdentityProposal:
        ...

    @abstractmethod
    def review_wine_identity(self, raw_description: str, proposal: IdentityProposal,
                             context: dict[str, Any]) -> IdentityVerdict:
        ...

    @abstractmethod
    def review_comparables(self, line: dict[str, Any], accepted: list[dict[str, Any]],
                           rejected: list[dict[str, Any]]) -> CompReview:
        ...

    @abstractmethod
    def parse_condition(self, text: str) -> ConditionParse:
        ...

    @abstractmethod
    def propose_inbound_offer(self, raw_body: Optional[str],
                              raw_media: Optional[bytes],
                              media_mime: Optional[str]) -> InboundOfferProposal:
        ...


def get_provider() -> AIProvider:
    """Factory. The only place a provider name is resolved to an implementation."""
    name = os.environ.get("AI_PROVIDER", "anthropic").lower()
    model = os.environ.get("AI_MODEL", "")
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model)
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(model=model)
    if name == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(model=model)
    raise ValueError(f"unknown AI_PROVIDER {name!r}")
