"""Which lines may derive a comparable across case sizes, and what the operator is told.

Decision 0016. The pricing core does not know what Burgundy is and never will
(invariant 1), so it is told: `SellerLine.derive_units` is set here, from the
wine's region, before the benchmark runs.

The 5% case premium is **a working assumption, not a measurement**. Decision
0001 measured the real basis on live merchant data and found a case running from
17.3% below to 20.0% above the loose-bottle price of the same wine. Every place
a derived figure is shown says so, in words, because a number that looks
observed and is not is exactly the failure this system exists to prevent.
"""
from __future__ import annotations

from typing import Optional

from app.core.benchmark import DerivedComp
from app.core.flags import CASE_PREMIUM

#: Regions where a comparable may be derived across case sizes. Burgundy only,
#: by Doug's decision of 24 September 2026, and on the evidence of the control
#: set: refusing to compare 3x75 with 6x75 was costing us most of what we had.
#: Adding a region means measuring its basis first and recording a decision.
DERIVABLE_REGIONS = frozenset({"BURGUNDY_RED", "BURGUNDY_WHITE"})

#: What the operator reads beside any derived figure. Never abbreviated away.
PREMIUM_CAVEAT = (f"Case premium of {(CASE_PREMIUM - 1) * 100:.0f}% applied — "
                  "a working assumption, not a measurement.")


def derivation_allowed(register_key: Optional[str]) -> bool:
    """True when this wine's region permits derivation. Unknown region, or a
    wine with no region recorded, means no: the exact-unit rule of 0001."""
    return bool(register_key) and register_key in DERIVABLE_REGIONS


def derivation_note(derived: DerivedComp) -> str:
    """The sentence shown on a line priced from a derived comp.

    The source offer, its real unit and its real price are named, so the
    operator can always see what was actually offered.
    """
    source = derived.source
    unit = f"{source.pack_size}x{source.bottle_ml // 10}cl"
    sentence = (f"Derived from a {unit} at {source.price} from {source.merchant}: "
                f"{derived.offer.price} at "
                f"{derived.offer.pack_size}x{derived.offer.bottle_ml // 10}cl.")
    return f"{sentence} {PREMIUM_CAVEAT}" if derived.premium_applied else (
        f"{sentence} No premium applied: case to case.")
