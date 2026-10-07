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
from app.vessel.engine import market_claim_sentence
from app.vessel.engine import reference_label as _reference_label

VesselCurrency = Literal["HKD", "GBP"]
Band = Literal["STRONG", "NORMAL", "CLEARANCE"]
StockLocation = Literal["HK_BOND", "UK_BOND", "EU_BOND", "DUTY_PAID_HK", "OTHER"]
ReferenceMarket = Literal["UK_IN_BOND", "HK_RETAIL"]


class LineChoiceIn(_In):
    line_id: UUID
    band: Band = "NORMAL"
    discount: Optional[Decimal] = Field(default=None, ge=0, lt=1)
    reference_market: ReferenceMarket = "UK_IN_BOND"
    #: Required when reference_market is HK_RETAIL: there is no adapter for
    #: this market yet, so the operator enters what they found by hand.
    hk_reference_price: Optional[Decimal] = Field(default=None, gt=0)
    hk_source_count: Optional[int] = Field(default=None, ge=1)
    hk_evidence: list[str] = []


class RecommendIn(_In):
    currency: VesselCurrency = "HKD"
    fx_hkd_per_gbp: Optional[Decimal] = Field(default=None, gt=0)
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
    fx_hkd_per_gbp: Optional[Decimal]
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

    #: Named, never implicit (decision 0020 revision, 7 October 2026).
    reference_market: ReferenceMarket
    reference_id: Optional[UUID] = None

    #: Display convenience, derived rather than stored: "Market reference" or
    #: "Indicative reference" (market-qualified for anything other than
    #: UK_IN_BOND) depending on source_count — the evidence claim rule made
    #: visible rather than left for the template to work out.
    reference_label: str = ""

    #: "34% below the best Hong Kong retail offer we can find" — None
    #: exactly when percentage_claim_pct is None (invariant 15: absent, not
    #: blank). Composed server-side so every screen prints the same words.
    market_claim: Optional[str] = None

    @model_validator(mode="after")
    def _set_reference_label(self) -> "ListingOut":
        if not self.reference_label:
            self.reference_label = _reference_label(self.reference_market, self.source_count)
        if self.market_claim is None:
            self.market_claim = market_claim_sentence(
                self.reference_market, self.percentage_claim_pct)
        return self


class RecommendOut(_Out):
    listings: list[ListingOut]
    excluded_counts: dict[str, int]


SettlementMode = Literal["AGENCY", "PRINCIPAL"]


class ApproveMandateIn(_In):
    move_line_ids: list[UUID] = Field(min_length=1)
    keep_line_ids: list[UUID] = []
    approved_by_name: str = Field(min_length=1)
    window_days: int = Field(default=30, gt=0)
    #: A term of the mandate (decision 0022): AGENCY is the only mode
    #: actually used — PRINCIPAL is accepted but untested.
    settlement_mode: SettlementMode = "AGENCY"
    #: "Ask every seller which warehouse they use" (decision 0025) — one
    #: field, no logic, operator-read only.
    storage_facility: Optional[str] = None


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
    settlement_mode: SettlementMode
    storage_facility: Optional[str] = None
    estimate: list[MandateNetOut] = []


class ConfirmSellerReceiptIn(_In):
    confirmed_by: str = Field(min_length=1)


class CommissionInvoiceLineOut(_Out):
    listing_id: UUID
    display_producer: str
    display_wine: str
    vintage: int
    release_code: Optional[str]
    currency: str
    vessel_price: Money
    seller_net: Money
    commission: Money


class CommissionInvoiceTotalOut(_Out):
    currency: str
    commission_total: Money


class CommissionInvoiceOut(_Out):
    mandate_id: UUID
    lines: list[CommissionInvoiceLineOut]
    totals: list[CommissionInvoiceTotalOut]


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
    seller_confirmed_at: Optional[datetime] = None
    seller_confirmed_by: Optional[str] = None


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


class ReservationNeedingConfirmationOut(_Out):
    """The operator's queue: HELD, past its one proof-of-payment extension,
    unresolved by payment either way."""
    reservation_id: UUID
    listing_id: UUID
    state: str
    payment_reference: str
    held_at: datetime
    expires_at: datetime
    proof_submitted_at: Optional[datetime]
    display_producer: str
    display_wine: str
    vintage: int
    vessel_price: Money
    currency: str


class SellThroughRowOut(_Out):
    band: str
    region: Optional[str]
    listed: int
    sold: int
    sell_through_pct: Decimal
    median_time_to_sell: Optional[timedelta]
