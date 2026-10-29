"""Shared evidence contract. Money is Decimal; no FX or implicit unit conversion."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Protocol
import json

PRICE_TYPES = {"MERCHANT_ASK", "LIVE_BID", "LIVE_OFFER", "LAST_TRADE",
               "AUCTION_HAMMER", "AUCTION_ALL_IN", "VESSEL_TRADE"}

def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class MarketUnit:
    wine_id: str
    vintage: str  # NV is explicit; release/edition must be encoded in canonical wine_id.
    bottle_ml: int
    pack_size: int
    market: str
    tax_status: str
    currency: str

    def __post_init__(self):
        if not all(isinstance(v, str) and v.strip() for v in
                   (self.wine_id, self.vintage, self.market, self.tax_status)):
            raise ValueError("Exact canonical market unit required")
        if any(type(v) is not int or v < 1 for v in (self.bottle_ml, self.pack_size)):
            raise ValueError("Bottle and pack sizes must be positive integers")
        if len(self.currency) != 3 or not self.currency.isupper() or not self.currency.isalpha():
            raise ValueError("Currency must be a three-letter uppercase code")

    def key(self):
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


class IdentityResolver(Protocol):
    """Adapter to VESSEL's authoritative resolver; return None if unsafe/ambiguous.

    Validate all identity attributes, including release, edition and safeguards.
    Never implement fuzzy matching or a parallel taxonomy here.
    """
    def resolve(self, candidate: dict) -> MarketUnit | None: ...


class UnresolvedIdentity:
    def resolve(self, candidate):
        return None


@dataclass
class Candidate:
    source_id: str
    source_type: str
    price: Decimal
    currency: str
    price_basis: str  # BOTTLE or PACK; PACK requires exact pack quantity on resolution.
    price_type: str
    observed_at: str
    source_reference: str
    raw_evidence: dict
    identity: dict = field(default_factory=dict)
    source_url: str | None = None

    def validate(self):
        try:
            self.price = Decimal(str(self.price))
        except InvalidOperation as exc:
            raise ValueError("Invalid price") from exc
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("Price must be finite and positive")
        if self.price_type not in PRICE_TYPES or self.price_basis not in {"BOTTLE", "PACK"}:
            raise ValueError("Unknown price type or price basis")
        if len(self.currency) != 3 or not self.currency.isalpha() or not self.currency.isupper():
            raise ValueError("Currency must be a three-letter uppercase code")
        observed = timestamp(self.observed_at)
        if observed > utcnow():
            raise ValueError("Observation cannot be in the future")
        self.observed_at = observed.isoformat()
        if not self.source_id.strip() or not self.source_type.strip() or not self.source_reference.strip():
            raise ValueError("Source identity and reference required")
        if not isinstance(self.raw_evidence, dict) or not self.raw_evidence:
            raise ValueError("Original evidence required")
        if not isinstance(self.identity, dict):
            raise ValueError("Identity hints must be an object")
        json.dumps(self.raw_evidence, allow_nan=False)
