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


# --------------------------------------------------------------- operators


class SignIn(_In):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class OperatorOut(_Out):
    operator_id: UUID
    username: str
    display_name: str
    active: bool


class OperatorRef(_Out):
    """Who did something. The id is what is stored; the name is for display and
    may change without rewriting history."""
    operator_id: UUID
    username: str
    display_name: str


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
    #: An edition within the cuvée that trades at its own level — Krug's
    #: Grande Cuvée 156e, Henri Giraud's MV13. Part of identity (0019).
    release_code: Optional[str] = None


class WineOut(_Out):
    wine_id: UUID
    producer: str
    cuvee: str
    region: Optional[str]
    colour: Optional[str]
    lwin7: Optional[str]
    release_code: Optional[str] = None
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
    note: Optional[str] = None

    #: Required to create a producer-only alias when the producer has more than
    #: one canonical wine: name the target again, deliberately.
    confirm_target: Optional[UUID] = None

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
    approved_by: OperatorRef
    approved_at: datetime
    note: Optional[str]
    #: No cuvee: this alias catches every listing printed under the producer
    #: alone, so it is operator-only and audited as a set.
    is_producer_only: bool


# ------------------------------------------------------------ deals, lines


class LineIn(_In):
    row_index: int = Field(ge=0)
    raw_description: str = Field(min_length=1)
    #: The seller's original row, verbatim. Required and non-empty: the parser
    #: runs in the browser, so this is where "never destroy the original seller
    #: description" is enforced for everyone.
    raw_row: dict[str, Any] = Field(min_length=1)
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
    #: The market chain (decision 0017): what a trade buyer pays below the UK
    #: Reference, and our fee on that buyer price. Null means the settings in
    #: app/pricing/pricer.py (20% / 8%). Per-deal only, never per-line.
    buyer_discount: Optional[Decimal] = Field(default=None, ge=0, lt=1)
    margin_on_sale: Optional[Decimal] = Field(default=None, ge=0, lt=1)
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
    changed_by: OperatorRef
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


AuctionHouse = Literal["BONHAMS", "CHRISTIES", "HERITAGE", "ZACHYS"]
AmountBasis = Literal["HAMMER", "BUYER_PREMIUM_INCLUSIVE"]


class AuctionEvidenceIn(_In):
    """One lot, hand-entered from a public results page. wine_id, vintage
    and bottle_ml come from the line's own approved identity server-side —
    this form does not carry them, so a mismatched paste cannot attach
    evidence to the wrong wine."""
    auction_house: AuctionHouse
    sale_date: date
    lot_ref: str = Field(min_length=1)
    source_url: str = Field(min_length=1, pattern=r"^https://")
    bottles_in_lot: int = Field(gt=0)
    currency: Currency
    amount: PositiveMoney
    amount_basis: AmountBasis
    premium_rate: Optional[Decimal] = Field(default=None, gt=0, lt=1)
    fx_rate: Optional[Decimal] = Field(default=None, gt=0)
    fx_source: Optional[str] = None
    is_mixed_lot: bool = False
    condition_notes: Optional[str] = None
    condition_flagged: bool = False


class AuctionEvidenceOut(_Out):
    auction_evidence_id: UUID
    wine_id: UUID
    vintage: int
    bottle_ml: int
    bottles_in_lot: int
    auction_house: str
    sale_date: date
    lot_ref: str
    source_url: str
    currency: str
    amount: Money
    amount_basis: str
    premium_rate: Optional[Decimal]
    #: Absent when the lot is non-GBP and no FX rate was given — never
    #: estimated, shown to the operator as "FX unavailable".
    hammer_gbp: Optional[Money]
    fx_rate: Optional[Decimal]
    fx_source: Optional[str]
    is_mixed_lot: bool
    condition_notes: Optional[str]
    condition_flagged: bool
    quarantined: bool
    entered_by: OperatorRef
    entered_at: datetime
    retracted_at: Optional[datetime]
    retracted_by: Optional[OperatorRef]
    retraction_reason: Optional[str]


class AuctionRetractIn(_In):
    reason: str = Field(min_length=1)


class AuctionHealthOut(_Out):
    """The read side (spec): a count, a median, a date range and the source
    links — never a figure that could be mistaken for a price."""
    lot_count: int
    median_per_bottle_gbp: Optional[Money]
    earliest_sale_date: Optional[date]
    latest_sale_date: Optional[date]
    source_urls: list[str]
    flag: Optional[Literal["AUCTION_BELOW_REFERENCE"]]
    note: Optional[str]


class AcknowledgementOut(_Out):
    ack_id: UUID
    flags: list[str]
    #: The benchmark state accepted along with them: NO_MARKET and REVIEW gate
    #: too, because they are about whether we measured a market at all (0010).
    state: str
    acknowledged_by: OperatorRef
    acknowledged_at: datetime
    note: Optional[str]


class AcknowledgementIn(_In):
    note: Optional[str] = None


class AliasSuggestionOut(_Out):
    """Seller wording an operator has resolved to the same wine more than once."""
    seller_text: str
    normalised: str
    wine_id: UUID
    producer: str
    cuvee: str
    line_ids: list[UUID]
    corrections: int
    changed_by: list[OperatorRef]
    last_changed_at: datetime


class PricingOut(_Out):
    pricing_id: UUID
    run_id: UUID
    priced_at: datetime
    priced_by: OperatorRef
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
    price_basis: Literal["manual", "line_margin", "line_discount", "global_margin",
                         "buyer_discount"]
    target_margin: Optional[Decimal]
    discount: Optional[Decimal]
    deep_discount_threshold: Decimal
    sell_price: Optional[Money]
    sell_currency: str
    #: Set only when price_basis == "buyer_discount" (decision 0017): the two
    #: settings actually used, and the same two prices — sell_price/cost_gbp —
    #: under names that cannot be misread. One is a sale, the other a purchase.
    buyer_discount: Optional[Decimal] = None
    margin_on_sale: Optional[Decimal] = None
    buyer_price_gbp: Optional[Money] = None
    seller_price_gbp: Optional[Money] = None
    gp: Optional[Money]
    gross_margin: Optional[Decimal]
    flags: list[str]
    state: str
    #: True when a gating flag (NEGATIVE_GP, SELL_ABOVE_UK_REFERENCE) is present:
    #: this price cannot reach a buyer offer until an operator accepts it.
    requires_acknowledgement: bool
    acknowledgement: Optional[AcknowledgementOut] = None


class PricingIn(_In):
    """`fx_rates` maps a cost currency to the rate used, its date and its source:
    {"USD": {"rate": "0.7412", "date": "2026-09-19", "source": "ECB"}}.
    The rate is GBP per one unit of that currency."""
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
    resolved_by: Optional[OperatorRef]
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
    wine_id_approved_by: Optional[OperatorRef]
    wine_id_approved_at: Optional[datetime]
    target_margin: Optional[Decimal]
    target_discount: Optional[Decimal]
    manual_price: Optional[Money]
    flags: list[str]
    line_state: LineState
    benchmark: Optional[RunSummary] = None
    pricing: Optional[PricingOut] = None


class DealSummaryOut(_Out):
    deal_id: UUID
    name: str
    seller: Optional[str]
    currency: Optional[str]
    target_margin: Optional[Decimal]
    created_by: OperatorRef
    created_at: datetime
    lines: int
    identity_not_approved: int
    not_searched: int
    ready: int
    review: int
    no_market: int


class ReviewQueueOut(_Out):
    """A line waiting on a person, and what it is waiting for."""
    line_id: UUID
    deal_id: UUID
    deal_name: str
    row_index: int
    raw_description: str
    quantity: int
    wine_id: Optional[UUID]
    line_flags: list[str]
    line_state: LineState
    benchmark_flags: list[str] = []
    uk_reference: Optional[Money]
    sell_price: Optional[Money]
    pricing_flags: list[str] = []
    requires_acknowledgement: bool = False
    acknowledged: bool = False


class DealOut(_Out):
    deal_id: UUID
    name: str
    seller: Optional[str]
    source_file: Optional[str]
    currency: Optional[str]
    target_margin: Optional[Decimal]
    #: The market chain settings as stored, null meaning "the defaults" —
    #: echoed back so the console can show what a line will actually use.
    buyer_discount: Optional[Decimal]
    margin_on_sale: Optional[Decimal]
    created_by: OperatorRef
    created_at: datetime
    lines: list[LineOut]


# ------------------------------------------------------ snapshots and jobs


class SnapshotIn(_In):
    merchant_ids: Optional[list[str]] = None
    is_demo: bool = False


class SearchKeyIn(_In):
    """How this merchant is asked about one producer, in the merchant's own
    terms. Recorded, never guessed: see decision 0010."""
    producer_key: str = Field(min_length=1)
    params: dict[str, str]
    note: Optional[str] = None


class SearchKeyOut(_Out):
    merchant_id: str
    producer_key: str
    params: dict[str, Any]
    source: Literal["merchant_index", "operator"]
    set_by: OperatorRef
    set_at: datetime
    note: Optional[str]


class DeepSearchIn(_In):
    """Search the gaps of one deal: lines with fewer than `min_comps` merchants."""
    min_comps: int = Field(default=2, ge=1, le=10)
    merchant_ids: Optional[list[str]] = None


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


class DerivedFromOut(_Out):
    """What a derived comparable was derived from. Never a price of its own:
    the operator always sees what the merchant actually offered."""
    merchant_id: str
    merchant: str
    price: Money
    pack_size: int
    bottle_ml: int
    basis: str                       # the arithmetic, in words
    premium_applied: bool
    #: Whether CASE_PREMIUM is measured for this wine's region, or carried
    #: over from Burgundy as a working assumption (decision 0018). None on
    #: runs computed before this existed.
    measured: Optional[bool] = None
    note: str                        # the sentence shown beside the figure


class CompOut(_Out):
    """One offer as the benchmark saw it, read from the run itself. offer_pk is
    null once the snapshot it came from has been pruned; nothing else changes."""
    role: Literal["comparable", "merchant_best", "cross_unit", "indication", "rejected"]
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
    #: indication only: how far a brokerage's view sat from the Reference, and
    #: how many merchants it says it aggregated. Context, never a price.
    variance_vs_reference: Optional[Decimal] = None
    merchant_count: Optional[int] = None
    #: Set when `price` above was DERIVED across case sizes (decision 0016).
    #: The real offer is here: its unit, its price and the arithmetic in words,
    #: including that the 5% case premium is an assumption.
    derived_from: Optional[DerivedFromOut] = None
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


class BuyerOfferLineIn(_In):
    line_id: UUID
    quantity: Optional[int] = Field(default=None, ge=1)
    description: Optional[str] = None
    condition_notes: Optional[str] = None


class BuyerOfferIn(_In):
    client: str = Field(min_length=1)
    currency: Currency = "GBP"
    terms: Optional[str] = None
    lines: list[BuyerOfferLineIn] = Field(min_length=1)


class MarketClaimOut(_Out):
    """What a line may say about the UK market. It exists only where there is a
    UK Reference to say it against; a line without one has no claim at all, and
    the document has nothing to print. See decision 0010."""
    run_id: UUID
    as_of: datetime
    uk_reference: Money
    comp_count: int
    below_reference: Decimal


class BuyerOfferLineOut(_Out):
    line_no: int
    line_id: UUID
    pricing_id: UUID
    description: str
    vintage: int
    bottle_ml: int
    pack_size: int
    quantity: int
    unit_price: Money
    line_total: Money
    condition_notes: Optional[str]
    ack_id: Optional[UUID]
    market_claim: Optional[MarketClaimOut] = None


class BuyerOfferOut(_Out):
    buyer_offer_id: UUID
    deal_id: UUID
    client: str
    currency: str
    issued_at: datetime
    issued_by: OperatorRef
    terms: Optional[str]
    total: Money
    lines: list[BuyerOfferLineOut]


class RunSourceOut(_Out):
    """The capture a merchant contributed. snapshot_id is null once pruned."""
    merchant_id: str
    snapshot_id: Optional[UUID]
    captured_at: datetime


class NeighbourOut(_Out):
    """One neighbouring vintage of the same wine and unit. Evidence about the
    comps, never a comp: no figure here can become a Floor, a Reference or a
    Median, and none of it reaches a client document."""
    vintage: int
    median: Money
    merchants: int
    stale: bool
    #: 1 = great, 5 = weak, from the shipped register. Absent on runs computed
    #: before the register existed.
    tier: Optional[int] = None
    newest_captured_at: Optional[datetime] = None


class BandOfferOut(_Out):
    offer_id: Optional[UUID]
    merchant_id: str
    merchant: str
    price: Money
    edge: Money                      # the band edge it failed, after widening
    multiple: Decimal                # price / edge, for the operator to see
    flag: str


class FormatDisagreementOut(_Out):
    """One merchant disagreeing with itself across formats. The per-bottle
    figures exist here and nowhere else: they are not stored on an offer, not
    exported, and never shown as a price."""
    merchant: str
    comp_unit: str
    comp_per_bottle: Money
    other_unit: str
    other_per_bottle: Money
    difference: Decimal
    flag: str


class ExclusionOut(_Out):
    """A comp the band dropped, and who put it back. Only a dear comp is ever
    dropped automatically; a cheap one is flagged and kept (spec 5)."""
    exclusion_id: UUID
    offer_pk: Optional[UUID]
    merchant: str
    price: Money
    flag: str
    band_edge: Money
    band_multiple: Decimal
    excluded_at: datetime
    reinstated_at: Optional[datetime] = None
    reinstated_by: Optional[OperatorRef] = None
    reinstated_reason: Optional[str] = None
    replacement_run_id: Optional[UUID] = None


class VintageBandOut(_Out):
    """The vintage-neighbour sanity check for a run. `band_low` and `band_high`
    are absent together when fewer than two neighbouring vintages were found:
    silence, not a guess."""
    unit: str
    band_low: Optional[Money]
    band_high: Optional[Money]
    neighbours: list[NeighbourOut] = []
    low_outliers: list[BandOfferOut] = []
    excluded: list[ExclusionOut] = []
    format_incoherent: list[FormatDisagreementOut] = []
    tiers_available: bool
    note: Optional[str] = None


class PriceCoincidenceOut(_Out):
    """Two merchants quoting one price to the penny — possibly one parcel seen
    twice. An operator note: it never gates and never changes depth."""
    price: Money
    merchants: list[str]
    any_brokered: bool
    flag: str
    note: str


class ReinstateIn(_In):
    """Putting an automatically excluded comp back. Who did it comes from the
    session, never from the caller."""
    reason: str = Field(min_length=1, max_length=500)


class RunOut(RunSummary):
    line_id: UUID
    sources: list[RunSourceOut]
    comps: list[CompOut]
    #: Absent on runs computed before the check existed.
    vintage_band: Optional[VintageBandOut] = None
    same_price_notes: list[PriceCoincidenceOut] = []
