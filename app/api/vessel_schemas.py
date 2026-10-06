"""Request and response shapes for VESSEL Private Sale. Money rules follow
app/api/schemas.py exactly: Decimal in, Decimal out, a JSON number is a 422.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import Field, model_validator

from app.api.schemas import Money, _In, _Out

VesselCurrency = Literal["HKD", "GBP"]
Band = Literal["STRONG", "NORMAL", "CLEARANCE"]
StockLocation = Literal["HK_BOND", "UK_BOND", "EU_BOND", "DUTY_PAID_HK", "OTHER"]


class LineChoiceIn(_In):
    line_id: UUID
    band: Band = "NORMAL"
    discount: Optional[Decimal] = Field(default=None, ge=0, lt=1)


class RecommendIn(_In):
    currency: VesselCurrency = "HKD"
    fx_rate: Optional[Decimal] = Field(default=None, gt=0)      # HKD per 1 GBP
    fx_source: Optional[str] = None
    fx_rate_date: Optional[date] = None
    stock_location: StockLocation = "HK_BOND"
    warehouse: Optional[str] = None
    line_choices: list[LineChoiceIn] = []
    held_back_line_ids: list[UUID] = []
    minimum_gbp: Optional[Decimal] = Field(default=None, ge=0)


class ListingOut(_Out):
    listing_id: UUID
    deal_id: UUID
    line_id: UUID
    mandate_id: Optional[UUID]
    drop_id: Optional[UUID]
    state: str
    display_producer: str
    display_wine: str
    vintage: int
    release_code: Optional[str]
    bottle_ml: int
    bottles: int
    stock_location: str
    warehouse: Optional[str]
    currency: str
    fx_rate: Optional[Decimal]
    fx_source: Optional[str]
    market_reference: Money
    band: str
    discount_applied: Decimal
    vessel_price: Money
    seller_net: Money
    source_count: int
    vintage_band_passed: bool
    derived: bool
    percentage_claim_pct: Optional[Decimal]
    created_at: datetime
    approved_at: Optional[datetime]
    listed_at: Optional[datetime]
    #: Set only by the drop-page read, from the fulfilling reservation.
    sold_at: Optional[datetime] = None

    #: Display convenience, derived rather than stored: "Market reference" or
    #: "Indicative reference" depending on source_count — the evidence claim
    #: rule made visible rather than left for the template to work out.
    reference_label: str = ""

    @model_validator(mode="after")
    def _set_reference_label(self) -> "ListingOut":
        if not self.reference_label:
            self.reference_label = (
                "Market reference" if self.source_count >= 2 else "Indicative reference")
        return self


class RecommendOut(_Out):
    listings: list[ListingOut]
    excluded_counts: dict[str, int]


class ApproveMandateIn(_In):
    move_line_ids: list[UUID] = Field(min_length=1)
    keep_line_ids: list[UUID] = []
    approved_by_name: str = Field(min_length=1)
    window_days: int = Field(default=30, gt=0)


class MandateNetOut(_Out):
    currency: str
    lines: int
    net_total: Money


class MandateOut(_Out):
    mandate_id: UUID
    deal_id: UUID
    mandate_text: str
    window_days: int
    approved_by_name: str
    approved_at: datetime
    estimate: list[MandateNetOut] = []


class DropIn(_In):
    label: str = Field(min_length=1)
    drop_date: date


class DropOut(_Out):
    drop_id: UUID
    label: str
    drop_date: date
    created_at: datetime


class AddToDropIn(_In):
    listing_ids: list[UUID] = Field(min_length=1)


class BuyIn(_In):
    buyer_contact: str = Field(min_length=1)


class ReservationOut(_Out):
    reservation_id: UUID
    listing_id: UUID
    state: str
    payment_reference: str
    held_at: datetime
    expires_at: datetime
    proof_submitted_at: Optional[datetime]


class ReservationWithListingOut(ReservationOut):
    """The payment screen's one read: what to pay, and whether it already
    has been — never fetched from the reservation and the listing at two
    different moments."""
    vessel_price: Money
    currency: str
    display_producer: str
    display_wine: str
    vintage: int
    bottles: int
    listing_state: str


class PaymentIn(_In):
    reference: str = Field(min_length=1)
    amount: Money
    currency: VesselCurrency
    received_at: datetime


class PaymentOut(_Out):
    payment_id: UUID
    reference: str
    amount: Money
    currency: str
    state: str
    matched_reservation_id: Optional[UUID]


class SellThroughRowOut(_Out):
    band: str
    region: Optional[str]
    listed: int
    sold: int
    sell_through_pct: Decimal
    median_time_to_sell: Optional[timedelta]
