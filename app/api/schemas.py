"""Request and response shapes.

Money crosses the API as a JSON *string* ("2353.10"), in both directions.
A JSON number has already been parsed to a binary float by the time anything
sees it, so a float is refused outright rather than converted. Responses go out
through these models, which serialise Decimal as a string; FastAPI's default
encoder would turn a bare Decimal into a float.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _refuse_float(v: Any) -> Any:
    if isinstance(v, float):
        raise ValueError('money must be sent as a string such as "2353.10", never a JSON number')
    return v


Money = Annotated[Decimal, BeforeValidator(_refuse_float),
                  Field(max_digits=14, decimal_places=2, gt=0)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# -------------------------------------------------------------- merchants


class MerchantOut(_Out):
    merchant_id: str
    name: str
    approved: bool
    notes: Optional[str]


# ------------------------------------------------------------------ wines


class WineIn(_In):
    producer: str = Field(min_length=1)
    cuvee: str = Field(min_length=1)
    region: Optional[str] = None
    colour: Optional[str] = None
    lwin7: Optional[str] = None


class WineOut(_Out):
    wine_id: UUID
    producer: str
    cuvee: str
    region: Optional[str]
    colour: Optional[str]
    lwin7: Optional[str]
    wine_key: str


class AliasIn(_In):
    """The merchant's or seller's own spelling, approved by a named person."""
    producer_text: str
    cuvee_text: str = Field(min_length=1)
    source: Literal["operator", "ai_reviewed", "import"]
    approved_by: str = Field(min_length=1)
    note: Optional[str] = None


class AliasOut(_Out):
    alias_id: UUID
    wine_key: str
    wine_id: UUID
    source: str
    approved_by: str
    approved_at: datetime
    note: Optional[str]


# ------------------------------------------------------------ deals, lines


class LineIn(_In):
    row_index: int = Field(ge=0)
    raw_description: str = Field(min_length=1)
    raw_row: dict[str, Any]
    quantity: int = Field(ge=1)
    cost: Optional[Money] = None
    cost_currency: Optional[Currency] = None

    @model_validator(mode="after")
    def _cost_has_currency(self) -> "LineIn":
        if (self.cost is None) != (self.cost_currency is None):
            raise ValueError("cost and cost_currency are given together or not at all")
        return self


class DealIn(_In):
    name: str = Field(min_length=1)
    seller: Optional[str] = None
    source_file: Optional[str] = None
    currency: Optional[Currency] = None
    created_by: str = Field(min_length=1)
    lines: list[LineIn] = Field(min_length=1)


class IdentityIn(_In):
    """Approved identity and format for a seller line."""
    wine_id: UUID
    vintage: int = Field(ge=1000, le=2100)       # 1000 = NV
    bottle_ml: int = Field(gt=0)
    pack_size: int = Field(ge=1)


class RunSummary(_Out):
    run_id: UUID
    snapshot_id: Optional[UUID]
    computed_at: datetime
    uk_floor: Optional[Decimal]
    uk_reference: Optional[Decimal]
    uk_median: Optional[Decimal]
    comp_count: int
    duplicate_listings: int
    flags: list[str]
    state: str


class LineOut(_Out):
    line_id: UUID
    row_index: int
    raw_description: str
    raw_row: dict[str, Any]
    wine_id: Optional[UUID]
    vintage: Optional[int]
    bottle_ml: Optional[int]
    pack_size: Optional[int]
    quantity: int
    cost: Optional[Decimal]
    cost_currency: Optional[str]
    benchmark: Optional[RunSummary] = None


class DealOut(_Out):
    deal_id: UUID
    name: str
    seller: Optional[str]
    source_file: Optional[str]
    currency: Optional[str]
    created_by: str
    created_at: datetime
    lines: list[LineOut]


# ------------------------------------------------------ snapshots and jobs


class SnapshotIn(_In):
    merchant_ids: Optional[list[str]] = None
    is_demo: bool = False


class SnapshotOut(_Out):
    snapshot_id: UUID
    captured_at: datetime
    schema_version: str
    is_demo: bool
    adapters_attempted: int
    adapters_succeeded: int
    offers_written: int
    offers_rejected: int
    failures: list[dict[str, Any]]


class BenchmarkIn(_In):
    snapshot_id: Optional[UUID] = None


class JobOut(BaseModel):
    job_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None


# --------------------------------------------------------------- benchmark


class CompOut(_Out):
    role: Literal["comparable", "merchant_best", "cross_unit", "rejected"]
    reject_reason: Optional[str]
    offer_pk: UUID
    merchant_id: str
    merchant: str
    merchant_offer_id: str
    vintage: int
    bottle_ml: int
    pack_size: int
    price: Decimal
    #: cross_unit only: price / pack_size, shown to the operator, never priced.
    per_bottle: Optional[Decimal] = None
    currency: str
    duty_status: str
    price_kind: str
    is_buyable: bool
    offered_units: Optional[int]
    stock_type: str
    stock_type_basis: str
    condition_flags: list[str]
    condition_notes: Optional[str]
    source_url: Optional[str]


class RunOut(RunSummary):
    line_id: UUID
    snapshot_failures: list[dict[str, Any]]
    comps: list[CompOut]
