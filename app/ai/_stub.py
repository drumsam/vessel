"""Shared base for providers that are named but not implemented yet.

get_provider() must fail legibly, with the provider name and what to do, not on
an ImportError. No vendor SDK is imported here or in any stub.
"""
from __future__ import annotations

from typing import Any, NoReturn

from .provider import AIProvider


class NotImplementedProvider(AIProvider):
    name = "unimplemented"

    def __init__(self, model: str = "") -> None:
        self._fail()

    def _fail(self) -> NoReturn:
        raise NotImplementedError(
            f"AI_PROVIDER={self.name!r} is not implemented yet: "
            f"app/ai/{self.name}_provider.py is a stub. Implement the four capabilities "
            "there, returning the dataclasses in app/ai/provider.py. Nothing in the "
            "pricing path depends on an AI provider.")

    def resolve_wine_identity(self, raw_description: str, context: dict[str, Any]):
        self._fail()

    def review_wine_identity(self, raw_description: str, proposal, context: dict[str, Any]):
        self._fail()

    def review_comparables(self, line: dict[str, Any], accepted: list, rejected: list):
        self._fail()

    def parse_condition(self, text: str):
        self._fail()
