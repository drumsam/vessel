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
