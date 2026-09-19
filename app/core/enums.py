"""Closed vocabularies. Nothing in the pricing core accepts free text."""
from __future__ import annotations
from enum import Enum


class DutyStatus(str, Enum):
    IN_BOND = "IB"
    DUTY_PAID = "DP"
    UNKNOWN = "UNKNOWN"


class PriceKind(str, Enum):
    ASK = "ASK"
    BID = "BID"
    LAST_TRADE = "LAST_TRADE"


class CommercialUnit(str, Enum):
    BOTTLE = "BOTTLE"
    CASE = "CASE"


class StockType(str, Enum):
    MERCHANT_STOCK = "MERCHANT_STOCK"
    CLIENT_STOCK = "CLIENT_STOCK"
    BROKERED = "BROKERED"
    MARKETPLACE = "MARKETPLACE"
    UNKNOWN = "UNKNOWN"


class ConditionFlag(str, Enum):
    """Normalised condition. Adapters map merchant prose onto these and ALSO keep
    the original wording verbatim in `condition_notes`."""
    ORIGINAL_CASE = "ORIGINAL_CASE"      # OWC/OCC/individual OWC — positive, not a defect
    REPACK = "REPACK"                    # re-boxed; ordinary in the loose-bottle trade
    NO_ORIGINAL_CASE = "NO_ORIGINAL_CASE"  # "Non OWC", "Non OC", "not in original carton"
    NON_PRISTINE = "NON_PRISTINE"        # merchant's own non-pristine marker
    LABEL_DAMAGE = "LABEL_DAMAGE"        # stained / scuffed / torn / bin-soiled labels
    LEVEL_ISSUE = "LEVEL_ISSUE"          # ullage below top shoulder, bottom neck, etc.
    LEVEL_NOTED = "LEVEL_NOTED"          # level mentioned and stated as good
    CAPSULE_OR_CORK = "CAPSULE_OR_CORK"
    SIGNS_OF_SEEPAGE = "SIGNS_OF_SEEPAGE"


class State(str, Enum):
    READY = "READY"
    REVIEW = "REVIEW"
    NO_MARKET = "NO_MARKET"


class Reject(str, Enum):
    """Why a candidate offer did not become a comparable. Every rejection is kept."""
    WINE = "different canonical wine"
    VINTAGE = "different vintage"
    SIZE = "different bottle size"
    UNIT = "different commercial unit"
    DUTY = "not In Bond"
    KIND = "not an ASK"
    CURRENCY = "not priced in GBP"
    NOT_BUYABLE = "not buyable"
    NO_QUANTITY = "no units offered"
    NON_POSITIVE_PRICE = "placeholder or non-positive price"
    MIXED_LOT = "mixed lot"
    UNRESOLVED_IDENTITY = "no approved canonical wine id"
