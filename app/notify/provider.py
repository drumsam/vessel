"""Provider-independent SMS interface. Same discipline as app/ai/provider.py:
business logic calls `send_sms` and nothing else; no module outside
`app/notify/` imports a vendor SDK.

No real provider is wired up — there is no Twilio/Vonage/etc. account to
point this at yet. `ConsoleNotifier` is what every environment uses today:
it writes the message where an operator running the stack can see it,
same as a developer reading server logs. Swapping in a real provider
later means adding a class here and setting `SMS_PROVIDER`; nothing in
`app/member/` changes.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger("notify")


class SmsProvider(ABC):
    @abstractmethod
    def send_sms(self, phone: str, message: str) -> None: ...


class ConsoleNotifier(SmsProvider):
    """Logs the message instead of sending it. The only provider that
    exists today — a real one is a decision Doug has not made yet, not a
    gap this module is hiding."""

    def send_sms(self, phone: str, message: str) -> None:
        logger.info("SMS to %s: %s", phone, message)


_PROVIDERS = {"console": ConsoleNotifier}


def get_provider() -> SmsProvider:
    name = os.environ.get("SMS_PROVIDER", "console")
    try:
        return _PROVIDERS[name]()
    except KeyError:
        raise ValueError(f"unknown SMS_PROVIDER {name!r}; known: {sorted(_PROVIDERS)}")


def send_sms(phone: str, message: str) -> None:
    get_provider().send_sms(phone, message)
