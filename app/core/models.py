"""Canonical records. These are the contract between adapters, identity resolution
and the pricing core.

Money is Decimal everywhere. There is no float in the pricing path.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import FrozenSet, Optional

from .enums import CommercialUnit, ConditionFlag, DutyStatus, PriceKind, StockType
from .flags import Flag

GBP = "GBP"


def unit_for(pack_size: int) -> CommercialUnit:
    """The ONLY place a commercial unit is derived. A pack of one is a bottle,
    whatever the merchant calls it — Bordeaux Index prints both 'Case (1 x 75cl)'
    and 'Bottle (75cl)' for the same commercial thing."""
    if pack_size < 1:
        raise ValueError("pack_size must be >= 1")
    return CommercialUnit.BOTTLE if pack_size == 1 else CommercialUnit.CASE


@dataclass(frozen=True)
class Offer:
    """One merchant offer, already normalised and already identity-resolved.

    `wine_id` is the approved canonical wine. If identity resolution could not
    approve one, the record does not become an Offer — it goes to rejects with
    UNRESOLVED_IDENTITY. The pricing core never re-derives identity from names.
    """
    offer_id: str
    merchant_id: str
    merchant: str

    wine_id: str                       # approved canonical id — the ONLY join key
    vintage: int                       # 1000 = NV (LWIN convention)
    bottle_ml: int
    pack_size: int

    price: Decimal                     # for ONE unit as defined by pack_size
    currency: str
    duty_status: DutyStatus
    price_kind: PriceKind

    is_buyable: bool                   # adapter-derived; see docs/adapter-contract.md
    offered_units: Optional[int]       # units available; None = not published

    stock_type: StockType = StockType.UNKNOWN
    stock_type_basis: str = "unknown"  # declared | inferred | unknown
    is_mixed_lot: bool = False

    condition_flags: FrozenSet[ConditionFlag] = frozenset()
    condition_notes: Optional[str] = None      # verbatim merchant wording, never inferred

    source_url: Optional[str] = None
    captured_at: Optional[datetime] = None
    raw: dict = field(default_factory=dict)    # original record, for audit and re-parsing

    @property
    def unit(self) -> CommercialUnit:
        return unit_for(self.pack_size)


@dataclass(frozen=True)
class SellerLine:
    """One line of the seller's list, after identity has been proposed, verified
    and approved. `raw_description` is never destroyed."""
    line_id: str
    raw_description: str

    wine_id: str
    vintage: int
    bottle_ml: int
    pack_size: int
    quantity: int                      # units the seller is offering

    cost: Optional[Decimal] = None
    cost_currency: Optional[str] = None

    #: Flags set upstream of the benchmark and persisted on the line
    #: (NAME_REVIEW, FORMAT_REVIEW, DERIVED_FROM_CASE). benchmark() unions them
    #: into the result. They may only ever move a line towards review; see
    #: docs/decisions/0005-inherited-line-flags.md.
    inherited_flags: FrozenSet[Flag] = frozenset()

    @property
    def unit(self) -> CommercialUnit:
        return unit_for(self.pack_size)
