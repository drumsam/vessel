"""Request and response shapes.

Money crosses the API as a JSON *string* ("2353.10"), in both directions.
A JSON number has already been parsed to a binary float by the time anything
sees it, so a float is refused outright rather than converted. Responses go out
through these models, which serialise Decimal as a string; FastAPI's default
encoder would turn a bare Decimal into a float.

`Money` is the one money type, for input and output alike: whole pence, at most
14 digits, never a float. It never rounds; a third decimal place is a 422.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

from pydantic import (
    AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator)


def _refuse_float(v: Any) -> Any:
    if isinstance(v, float):
        raise ValueError('money must be sent as a string such as "2353.10", never a JSON number')
    return v


Money = Annotated[Decimal, BeforeValidator(_refuse_float),
                  Field(max_digits=14, decimal_places=2)]
PositiveMoney = Annotated[Money, Field(gt=0)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
LineFlag = Literal["NAME_REVIEW", "FORMAT_REVIEW", "DERIVED_FROM_CASE"]
IdentitySource = Literal["lwin", "alias", "operator", "ai_reviewed"]


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
    """The merchant's or seller's own spelling, approved by a named person.

    Either field may be empty, but not both: Farr prints producer-only names
    ("Lafite Rothschild", "Veuve Clicquot") that split into no cuvee at all, and
    Goedhuis puts the whole wine in one string with no producer.
    """
    producer_text: str = ""
    cuvee_text: str = ""
    source: Literal["operator", "ai_reviewed", "import"]
    approved_by: str = Field(min_length=1)
    note: Optional[str] = None

    @model_validator(mode="after")
    def _has_a_name(self) -> "AliasIn":
        if not (self.producer_text.strip() or self.cuvee_text.strip()):
            raise ValueError("an alias needs the merchant's producer or cuvee wording")
        return self


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
    cost: Optional[PositiveMoney] = None
    cost_currency: Optional[Currency] = None
    target_margin: Optional[Decimal] = Field(default=None, ge=0, lt=1)
    target_discount: Optional[Decimal] = Field(default=None, ge=0, lt=1)
    manual_price: Optional[PositiveMoney] = None

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
    #: The deal's global margin, used for any line with no margin or discount.
    target_margin: Optional[Decimal] = Field(default=None, ge=0, lt=1)
    created_by: str = Field(min_length=1)
    lines: list[LineIn] = Field(min_length=1)


class IdentityIn(_In):
    """Approved identity and format for a seller line, who approved it and how.
    `lwin` and `alias` are the automatic resolver's sources; an operator
    approving by hand, or accepting a reviewed AI proposal, says so here."""
    wine_id: UUID
    vintage: int = Field(ge=1000, le=2100)       # 1000 = NV
    bottle_ml: int = Field(gt=0)
    pack_size: int = Field(ge=1)
    source: Literal["operator", "ai_reviewed"]
    approved_by: str = Field(min_length=1)
    flags: list[LineFlag] = []


class IdentityHistoryOut(_Out):
    history_id: UUID
    prev_wine_id: Optional[UUID]
    prev_vintage: Optional[int]
    prev_bottle_ml: Optional[int]
    prev_pack_size: Optional[int]
    prev_flags: list[str]
    new_wine_id: UUID
    new_vintage: int
    new_bottle_ml: int
    new_pack_size: int
    new_flags: list[str]
    source: IdentitySource
    changed_by: str
    changed_at: datetime


class RunSummary(_Out):
    run_id: UUID
    as_of: datetime
    computed_at: datetime
    uk_floor: Optional[Money]
    uk_reference: Optional[Money]
    uk_median: Optional[Money]
    comp_count: int
    duplicate_listings: int
    flags: list[str]
    state: str
    #: How old the stalest merchant-best was at as_of (ISO 8601 duration).
    oldest_comp_age: Optional[timedelta]


#: What is known about a line's market, in one word, for the deal view.
#: NOT_SEARCHED is not NO_MARKET: nobody has looked yet. A line that has never
#: been searched has no benchmark run, so it cannot be priced or exported.
LineState = Literal["IDENTITY_NOT_APPROVED", "NOT_SEARCHED", "READY", "REVIEW", "NO_MARKET"]


class PricingOut(_Out):
    pricing_id: UUID
    run_id: UUID
    priced_at: datetime
    priced_by: str
    uk_floor: Optional[Money]
    uk_reference: Optional[Money]
    uk_median: Optional[Money]
    comp_count: int
    cost: Optional[Money]
    cost_currency: Optional[str]
    fx_rate: Optional[Decimal]
    fx_rate_date: Optional[date]
    fx_source: Optional[str]
    cost_gbp: Optional[Money]
    price_basis: Literal["manual", "line_margin", "line_discount", "global_margin"]
    target_margin: Optional[Decimal]
    discount: Optional[Decimal]
    deep_discount_threshold: Decimal
    sell_price: Optional[Money]
    sell_currency: str
    gp: Optional[Money]
    gross_margin: Optional[Decimal]
    flags: list[str]
    state: str


class PricingIn(_In):
    """`fx_rates` maps a cost currency to the rate used, its date and its source:
    {"USD": {"rate": "0.7412", "date": "2026-09-19", "source": "ECB"}}.
    The rate is GBP per one unit of that currency."""
    priced_by: str = Field(min_length=1)
    fx_rates: dict[Currency, dict[str, str]] = {}
    deep_discount_threshold: Optional[Decimal] = Field(default=None, ge=0, lt=1)


class LwinConflictOut(_Out):
    """One LWIN-7 a merchant used for more than one wine name."""
    conflict_id: UUID
    merchant_id: str
    lwin7: str
    names: list[str]
    first_seen_at: datetime
    last_seen_at: datetime
    resolution: Optional[Literal["same_wine", "different_wines"]]
    resolved_by: Optional[str]
    resolved_at: Optional[datetime]
    note: Optional[str]


class LwinAlias(_In):
    wine_id: UUID
    producer_text: str = ""
    cuvee_text: str = ""

    @model_validator(mode="after")
    def _has_a_name(self) -> "LwinAlias":
        if not (self.producer_text.strip() or self.cuvee_text.strip()):
            raise ValueError("an alias needs the merchant's producer or cuvee wording")
        return self


class LwinConflictResolution(_In):
    """same_wine: the names are one wine, so approve aliases for the spellings
    that do not resolve yet. different_wines: record the exclusion and stop
    trusting this merchant's LWIN, so the conflict does not come back."""
    resolution: Literal["same_wine", "different_wines"]
    resolved_by: str = Field(min_length=1)
    note: Optional[str] = None
    aliases: list[LwinAlias] = []
    exclude: Optional[list[UUID]] = Field(default=None, min_length=2, max_length=2)

    @model_validator(mode="after")
    def _matches_resolution(self) -> "LwinConflictResolution":
        if self.resolution == "same_wine" and not self.aliases:
            raise ValueError("same_wine needs the alias(es) that make the names one wine")
        if self.resolution == "different_wines" and not self.exclude:
            raise ValueError("different_wines needs the two wine ids to exclude")
        return self


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
    cost: Optional[Money]
    cost_currency: Optional[str]
    wine_id_source: Optional[IdentitySource]
    wine_id_approved_by: Optional[str]
    wine_id_approved_at: Optional[datetime]
    target_margin: Optional[Decimal]
    target_discount: Optional[Decimal]
    manual_price: Optional[Money]
    flags: list[str]
    line_state: LineState
    benchmark: Optional[RunSummary] = None
    pricing: Optional[PricingOut] = None


class DealOut(_Out):
    deal_id: UUID
    name: str
    seller: Optional[str]
    source_file: Optional[str]
    currency: Optional[str]
    target_margin: Optional[Decimal]
    created_by: str
    created_at: datetime
    lines: list[LineOut]


# ------------------------------------------------------ snapshots and jobs


class SnapshotIn(_In):
    merchant_ids: Optional[list[str]] = None
    is_demo: bool = False


class TargetedSnapshotIn(_In):
    """Search one merchant for the producer of `wine_id` in `vintage`.
    `params` are the merchant's own search terms (Bordeaux Index: producer_slug)."""
    merchant_id: str
    wine_id: UUID
    vintage: int = Field(ge=1000, le=2100)
    params: dict[str, str]
    is_demo: bool = False


class SnapshotMerchantOut(_Out):
    merchant_id: str
    status: Literal["ok", "failed"]
    captured_at: datetime
    scope_producer_key: Optional[str]
    scope_vintage: Optional[int]
    scope_params: dict[str, Any]
    offers_written: int
    offers_rejected: int
    error: Optional[str]


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
    merchants: list[SnapshotMerchantOut]


class BenchmarkIn(_In):
    """Benchmark as of this instant (default: now). Freshness is measured
    against it and only captures at or before it are used."""
    as_of: Optional[AwareDatetime] = None

    @field_validator("as_of")
    @classmethod
    def _not_future(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v > datetime.now(timezone.utc):
            raise ValueError("as_of may not be in the future")
        return v


class JobOut(BaseModel):
    job_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None


# --------------------------------------------------------------- benchmark


class CompOut(_Out):
    """One offer as the benchmark saw it, read from the run itself. offer_pk is
    null once the snapshot it came from has been pruned; nothing else changes."""
    role: Literal["comparable", "merchant_best", "cross_unit", "rejected"]
    reject_reason: Optional[str]
    offer_pk: Optional[UUID]
    merchant_id: str
    merchant: str
    merchant_offer_id: str
    vintage: int
    bottle_ml: int
    pack_size: int
    price: Money
    #: cross_unit only: price / pack_size as computed by the core. Display
    #: arithmetic, not money: it is never rounded and never priced.
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
    captured_at: Optional[datetime]


class RunSourceOut(_Out):
    """The capture a merchant contributed. snapshot_id is null once pruned."""
    merchant_id: str
    snapshot_id: Optional[UUID]
    captured_at: datetime


class RunOut(RunSummary):
    line_id: UUID
    sources: list[RunSourceOut]
    comps: list[CompOut]
