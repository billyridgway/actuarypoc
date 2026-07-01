from __future__ import annotations

"""Engine capability metadata and assessment stubs.

This module defines shared types for describing what the projection
engine(s) can do, and how a given product model maps onto those
capabilities. The initial focus is UL, but the types are
product-agnostic so term and whole life can plug in later.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from actuarypoc.domain.life_product_models import BaseLifeProductModel


@dataclass
class EngineCapability:
    """Static description of a projection-engine capability.

    This is a purely declarative metadata record; it does not couple to
    any particular engine implementation.
    """

    capability_id: str
    product_type: str  # "term" | "whole" | "ul" | ...
    description: str


@dataclass
class CapabilityAssessmentItem:
    """Assessment of whether a capability is supported for a product.

    Status values are intentionally simple for v1:
    - "supported"   – engine can fully support this capability
    - "partial"     – engine can approximate but not fully support
    - "unsupported" – engine cannot support this capability yet
    """

    capability_id: str
    name: str
    status: str  # "supported" | "partial" | "unsupported"
    impact: str  # "high" | "medium" | "low"
    reason: str
    product_code: str
    product_type: str
    source_requirement_ids: List[str] = field(default_factory=list)
    source_requirement_text: Optional[str] = None
    source_document: Optional[str] = None
    source_reference: Optional[str] = None


# ---------------------------------------------------------------------------
# UL capability catalogue (initial draft)
# ---------------------------------------------------------------------------


_UL_CAPABILITIES: List[EngineCapability] = [
    EngineCapability(
        capability_id="UL_CAP_COI_TABLE_AGE_GENDER_CLASS",
        product_type="ul",
        description="COI rate tables by age, gender, risk class, and duration",
    ),
    EngineCapability(
        capability_id="UL_CAP_SURRENDER_FIXED_SCHEDULE",
        product_type="ul",
        description="Fixed surrender charge schedule by duration",
    ),
    EngineCapability(
        capability_id="UL_CAP_LEVEL_POLICY_FEE",
        product_type="ul",
        description="Level per-policy / per-period policy fee",
    ),
]


def get_ul_capabilities() -> List[EngineCapability]:
    """Return the static UL capability catalogue.

    Future work: this may come from config or a registry rather than a
    hard-coded list.
    """

    return list(_UL_CAPABILITIES)


__all__ = [
    "EngineCapability",
    "CapabilityAssessmentItem",
    "get_ul_capabilities",
]
