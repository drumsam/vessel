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
    #: One of the ten client want-list producers (decision 0038), set once
    #: at creation from the producer field alone.
    want_list: bool = False


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
    #: Where the cellar physically sits (decision 0036) — free text, read by
    #: the shared-offer-link message composer; omitted entirely, never
    #: guessed, where it is null.
    city: Optional[str] = None
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


class WantListMatchIn(_In):
    text: str = Field(min_length=1)


class WantListMatchOut(_Out):
    producer: str
    always_review: bool
    fork_with: list[str] = []


class EvaluationCompIn(_In):
    """One comparable price Doug found and is naming the source of — not a
    merchant this app necessarily has an adapter for (decision 0039).
    wine_id/vintage come from the evaluation itself, not from here, so a
    mismatched paste cannot attach evidence to the wrong wine."""
    merchant: str = Field(min_length=1)
    price: PositiveMoney
    currency: Currency
    bottle_ml: int = Field(gt=0)
    pack_size: int = Field(ge=1)
    duty_status: Literal["IB", "DP", "UNKNOWN"] = "IB"
    price_kind: Literal["ASK", "BID", "LAST_TRADE", "INDICATION"] = "ASK"
    is_buyable: bool = True
    offered_units: Optional[int] = Field(default=None, ge=1)
    source_url: Optional[str] = None
    captured_at: Optional[datetime] = None


class EvaluateOfferIn(_In):
    """The single box: what Doug was offered, and the market prices he
    found for it. Goes through exactly the same screens a scraped offer
    would (decision 0039) — no fast path, no trusted-operator bypass."""
    raw_description: str = Field(min_length=1)
    wine_id: UUID
    vintage: int
    bottle_ml: int = Field(gt=0)
    pack_size: int = Field(ge=1)
    quantity: int = Field(ge=1)
    asking_price: PositiveMoney
    asking_currency: Currency
    comps: list[EvaluationCompIn] = Field(min_length=1)


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
    #: Decision 0034: (1 - sell_price/uk_floor), computed here once and only
    #: once — never recomputed client-side, never derived from uk_reference.
    #: None whenever there is no Floor to measure against, OR the saving is
    #: real but below MIN_CLAIM_THRESHOLD: a line that cannot carry a
    #: percentage claim looks identical, over the API, to one with no Floor
    #: at all. It can still be sold; it just cannot be advertised as a
    #: discount. See app/core/flags.py::claims_a_saving.
    floor_saving_claim: Optional[Decimal] = None


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
    #: decision 0038. True only once wine_id is approved AND that wine is
    #: one of the ten client want-list producers — read from the wine,
    #: not the line, but surfaced here so a screen never has to join it
    #: separately.
    want_list: bool = False
    want_list_acknowledged_by: Optional[OperatorRef] = None
    want_list_acknowledged_at: Optional[datetime] = None


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
    city: Optional[str] = None
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
    role: Literal["comparable", "merchant_best", "cross_unit", "indication",
                 "bid", "last_trade", "rejected"]
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
    #: indication, bid or last_trade only: how far that figure sat from the
    #: Reference, and how many merchants an indication says it aggregated.
    #: Context, never a price.
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
    #: last_trade only, on the page to show: a historical fact's own date is
    #: what makes it checkable rather than assumed current (decision 0026).
    captured_at: Optional[datetime] = None
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


class OfferLinkIn(_In):
    """Decision 0035. Which lines a shareable public link covers, and which
    of the two safe views it shows — never guessed, never defaulted."""
    line_ids: list[UUID] = Field(min_length=1)
    kind: Literal["buyer", "seller"]
    fx_rate: Optional[Decimal] = Field(default=None, gt=0)


class OfferLinkOut(_Out):
    token: str
    kind: Literal["buyer", "seller"]
    expires_at: datetime


class PublicOfferLineOut(_Out):
    """One line of a shared public offer. seller_price_gbp/commission_gbp
    are only ever set by the server for a kind == "seller" link
    (app/offerlink/repo.py::build_public_payload) — absent, not null, on a
    buyer-kind one. No field here names the deal, the seller, or a cost."""
    line_id: UUID
    producer: str
    cuvee: str
    vintage: Optional[int]
    bottle_ml: Optional[int]
    quantity: int
    uk_floor: Optional[Money]
    uk_reference: Optional[Money]
    offer_price_gbp: Money
    floor_saving_claim: Optional[Decimal] = None
    comp_count: int
    price_basis: str
    buyer_discount: Optional[Decimal] = None
    as_of: Optional[datetime] = None
    comps: list[CompOut] = []
    seller_price_gbp: Optional[Money] = None
    commission_gbp: Optional[Money] = None


class PublicOfferOut(_Out):
    kind: Literal["buyer", "seller"]
    fx_rate: Optional[Decimal] = None
    expires_at: datetime
    lines: list[PublicOfferLineOut]


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


# ------------------------------------------------------------ VESSEL Pocket

InboundChannel = Literal["paste", "photo", "upload"]
InboundCategory = Literal["wine", "whisky", "unknown"]
ParseState = Literal["pending", "parsed", "unparseable"]


class InboundOfferIn(_In):
    """Screen 1, NEW: paste, photo, or upload. Capture first, structure
    afterwards — nothing else is required to land this."""
    channel: InboundChannel
    raw_body: Optional[str] = None
    raw_media_base64: Optional[str] = None
    media_mime: Optional[str] = None

    @model_validator(mode="after")
    def _has_something(self) -> "InboundOfferIn":
        if not self.raw_body and not self.raw_media_base64:
            raise ValueError("raw_body or raw_media_base64 is required")
        return self


class InboundOfferOut(_Out):
    inbound_offer_id: UUID
    received_at: datetime
    channel: InboundChannel
    parse_state: ParseState
    parse_error: Optional[str] = None
    category: Optional[InboundCategory] = None
    confirmed_wine_id: Optional[UUID] = None
    confirmed_vintage: Optional[int] = None
    confirmed_bottle_ml: Optional[int] = None
    confirmed_pack_size: Optional[int] = None
    confirmed_quantity: Optional[int] = None
    confirmed_packaging: Optional[str] = None
    confirmed_bond_status: Optional[str] = None
    confirmed_stock_location: Optional[str] = None
    confirmed_asking_price: Optional[Money] = None
    confirmed_asking_currency: Optional[str] = None
    confirmed_asking_basis: Optional[Literal["per_bottle", "per_case", "total"]] = None
    identity_confirmed_by: Optional[OperatorRef] = None
    identity_confirmed_at: Optional[datetime] = None
    deal_id: Optional[UUID] = None
    has_media: bool = False
    #: supplier-attribution-spec.md: nullable here (capture is never
    #: blocked) but required by ConfirmIdentityIn below.
    supplier_id: Optional[UUID] = None


class InboundOfferProposalOut(_Out):
    """Screen 2, CANDIDATE: the AI's structured proposal. Never persisted
    as such — this is the response to the one call that produced it;
    confirming or correcting it happens through ConfirmIdentityIn, which
    writes a real, operator-attributed fact, never this object verbatim."""
    category: InboundCategory
    producer: Optional[str] = None
    cuvee: Optional[str] = None
    vintage: Optional[int] = None
    bottle_ml: Optional[int] = None
    pack_size: Optional[int] = None
    quantity: Optional[int] = None
    #: The literal bottle count when pack_size/quantity are null because
    #: the commercial unit is genuinely ambiguous ("6 x ... OWC") — the
    #: fork the operator resolves, never guessed as one or the other.
    total_bottles: Optional[int] = None
    bond_status: Optional[str] = None
    stock_location: Optional[str] = None
    packaging: Optional[str] = None
    asking_price: Optional[str] = None
    asking_currency: Optional[str] = None
    #: Only ever set from an explicit word in the source — never inferred
    #: from quantity or pack_size. Null here on a multi-bottle line is a
    #: blocking ambiguity at confirm time, not a detail.
    asking_basis: Optional[Literal["per_bottle", "per_case", "total"]] = None
    reasoning: str
    #: Want-list producer names `match_want_list` suggests against the
    #: AI's own proposed producer text — a UI hint only (decision 0038):
    #: the real gate is checked again, authoritatively, against
    #: `wine.want_list` when the operator actually confirms a wine_id.
    want_list_hint: list[str] = []


class InboundOfferWithProposalOut(_Out):
    offer: InboundOfferOut
    proposal: InboundOfferProposalOut
    #: Deterministic pre-highlight only (supplier-attribution-spec.md) —
    #: never the model's: matched against supplier_alias via norm(), not
    #: proposed by the AI, which has no supplier field by construction.
    matched_supplier_ids: list[UUID] = []


class SupplierIn(_In):
    """The quick-add chip's own two-field form — name and phone only;
    the rest of the record can be filled in later or never."""
    name: str = Field(min_length=1)
    phone: Optional[str] = None


class SupplierOut(_Out):
    supplier_id: UUID
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    active: bool
    #: Most-recently-used ordering for the chip row; null if never picked.
    last_used_at: Optional[datetime] = None


class CandidateWineGroupOut(_Out):
    """Screen 2's own filtered wine list, grouped by producer — the
    proposed producer's wines, or that plus its known real-world fork
    (bare "Leroy" also returns a "Maison Leroy" group) when the matcher's
    always_review fires. Empty when no producer was proposed at all."""
    producer: str
    is_fork_alternate: bool
    wines: list[WineOut]


class ConfirmIdentityIn(_In):
    """Screen 2's actual job: confirm or correct the AI's proposal against
    a real, already-approved wine. want_list_ack is required — and
    checked against wine.want_list, not against anything the caller
    claims — whenever that wine is one of the twenty (decision 0038);
    the photo gate never has a confidence threshold that skips it.

    supplier_id has no default and is Optional nowhere in this class —
    required by the type system itself, not by application logic, the
    same "capture never blocked, confirmation always is" shape
    want_list_ack uses one level up (supplier-attribution-spec.md).

    quantity is commercial UNITS (as pack_size defines them), never
    bottles — resolving the "one case of six or six loose bottles" fork
    means setting pack_size and quantity together, deliberately, never
    guessed by this app. packaging/bond_status/stock_location are free
    text and optional: useful record-keeping, never a gate. asking_price/
    _currency/_basis are optional here too — a line with no stated price
    has nothing to confirm — but `app/api/inbound.py` refuses this call
    outright when a price exists, the line is more than one bottle, and
    asking_basis is null: that ambiguity is worth exactly the multiple
    pack_size would convert the figure by, never confirmed silently."""
    wine_id: UUID
    vintage: int = Field(ge=1000, le=2100)
    bottle_ml: int = Field(gt=0, default=750)
    pack_size: int = Field(ge=1, default=1)
    quantity: int = Field(ge=1, default=1)
    packaging: Optional[str] = None
    bond_status: Optional[str] = None
    stock_location: Optional[str] = None
    asking_price: Optional[Money] = None
    asking_currency: Optional[Currency] = None
    asking_basis: Optional[Literal["per_bottle", "per_case", "total"]] = None
    want_list_ack: bool = False
    supplier_id: UUID


# ------------------------------------------------------------- EVALUATE (0040)

class AskOut(_Out):
    """The confirmed ask, converted to the line's own commercial unit
    (same basis uk_floor is in), plus the two display shapes every
    other screen in this app already uses."""
    per_unit: Money
    per_bottle: Money
    total: Money


class WalkAwayOut(_Out):
    """buy-side-margin-test.md. All four money fields per the line's own
    commercial unit except the _per_bottle pair, which exist for display
    only — decision 0034's own "per-bottle figures primary" convention."""
    uk_floor: Money
    uk_floor_per_bottle: Money
    max_sell: Money
    walk_away: Money
    walk_away_per_bottle: Money


class EvaluateOut(_Out):
    """Screen 3, EVALUATE: facts, then stop. No verdict field exists here
    by construction — there is nothing to render a traffic light from.

    `state=None` is the one state above every other: no run could even
    be attempted (vanishingly rare — it means no merchant anywhere has
    ever had a resolved capture). `NO_MARKET` — thin-to-absent evidence
    on these 20 producers specifically — is the PRIMARY, expected state
    this screen is built around, not an error path; `checked_merchants`
    names exactly what was looked at and found nothing, so the screen
    never looks broken when it is working correctly."""
    deal_id: UUID
    line_id: UUID
    state: Optional[Literal["NOT_SEARCHED", "NO_MARKET", "REVIEW", "READY"]] = None
    as_of: Optional[datetime] = None
    comp_count: int = 0
    flags: list[str] = []
    #: Populated only when state == NO_MARKET — the merchants this run
    #: actually consulted, named, not a bare "nothing found".
    checked_merchants: list[str] = []
    ask: Optional[AskOut] = None
    walk_away: Optional[WalkAwayOut] = None
    #: walk_away.walk_away - ask.per_unit. Negative means the ask is
    #: ABOVE walk-away; positive is headroom below it.
    headroom: Optional[Money] = None
    headroom_per_bottle: Optional[Money] = None
    margin_at_ask_pct: Optional[Decimal] = None
    #: Shown only when the ask is above walk-away — what a sell would
    #: have to be to still hit MIN_TRADE_MARGIN at this ask.
    required_sell_for_margin: Optional[Money] = None
    exceeds_floor: Optional[bool] = None
    blocks_create_offer: bool = True
    block_reason: Optional[str] = None


class CollectResultOut(_Out):
    """One merchant's outcome from a "Collect now" run — decision 0004's
    own three states, named plainly: 'ok' (looked; offers_written may
    still be 0 — looked and found nothing), 'failed' (couldn't look,
    `error` says why), or 'skipped' (never attempted, `reason` says
    why — not approved, not a search-only merchant, or no search key
    for this producer)."""
    merchant_id: str
    outcome: Literal["ok", "failed", "skipped"]
    reason: Optional[str] = None
    offers_written: int = 0
    offers_rejected: int = 0
    error: Optional[str] = None


class CollectNowOut(_Out):
    """speed-and-cost-plan.md's "Collect now": one wine, synchronous,
    every targeted merchant queried, then the same facts /evaluate
    itself would show — one result shape either way."""
    collected: list[CollectResultOut]
    evaluation: EvaluateOut
