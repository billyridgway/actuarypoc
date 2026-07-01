from __future__ import annotations

"""Core life product domain models.

These dataclasses provide a product-line-aware representation of life
products that other layers (extraction, requirements classification,
capability assessment, and projection engines) can share.

The intent is that **every** supported product – term, whole life,
UL, indexed UL, etc. – is mapped into one of these models, rather than
having per-product ad hoc shapes.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Shared evidence types
# ---------------------------------------------------------------------------


@dataclass
class EvidenceRef:
    """Reference back to a filing/spec document.

    Designed to be JSON-serialisable and stable over time.
    """

    document: Optional[str] = None
    page: Optional[str] = None
    snippet: Optional[str] = None
    confidence: Optional[float] = None


@dataclass
class FieldEvidence:
    """Status + provenance for a single logical field or table.

    This is intentionally small and generic so it can be shared across
    product lines and plugged directly into the generic requirements
    classifier via a thin adapter.
    """

    id: str
    status: str  # e.g. "extracted" | "inferred" | "placeholder" | "missing"
    value_summary: Optional[str] = None
    sources: List[EvidenceRef] = field(default_factory=list)
    impact: str = "low"  # "high" | "medium" | "low"


# ---------------------------------------------------------------------------
# Base model for all life products
# ---------------------------------------------------------------------------


@dataclass
class BaseLifeProductModel:
    """Common core for all life products.

    Line-specific models *must* extend this via normal Python class
    inheritance so type checks and routing stay simple.
    """

    product_code: str
    product_name: Optional[str] = None
    carrier: Optional[str] = None
    jurisdiction: Optional[str] = None

    # Coarse product type label used for routing, e.g. "term",
    # "whole", "ul", "indexed_ul".
    product_type: str = "unknown"

    # Coverage scope.
    issue_age_min: Optional[int] = None
    issue_age_max: Optional[int] = None
    risk_classes: List[str] = field(default_factory=list)

    # High-level premium pattern and guarantees.
    premium_pattern: Optional[str] = None  # "level", "single", "flexible", ...
    premium_guarantee_description: Optional[str] = None

    # Riders / options present (term riders, chronic illness, etc.).
    riders: List[str] = field(default_factory=list)

    # Optional metadata / traceability hints.
    metadata_sources: List[EvidenceRef] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Term life
# ---------------------------------------------------------------------------


@dataclass
class RateTable:
    """Placeholder for a term or COI rate table.

    For now we only track a simple identifier and an evidence block;
    concrete dimensionality (age, sex, class, duration, etc.) lives in
    the underlying store (CSV, DSL, MinIO object, ...).
    """

    id: str
    description: Optional[str] = None
    evidence: Optional[FieldEvidence] = None


@dataclass
class TermLifeModel(BaseLifeProductModel):
    """Term life coverage and mechanics."""

    term_period_years: Optional[int] = None
    renewable: Optional[bool] = None
    convertible: Optional[bool] = None
    conversion_rules: Optional[str] = None

    premium_rate_tables: List[RateTable] = field(default_factory=list)
    reentry_rules: Optional[str] = None

    # Field-level evidence keyed by logical requirement/field id.
    field_evidence: Dict[str, FieldEvidence] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Whole life
# ---------------------------------------------------------------------------


@dataclass
class TableWithStatus:
    """Generic table wrapper with evidence and a human summary.

    Used for guaranteed value tables, surrender schedules, etc.
    """

    id: str
    description: Optional[str] = None
    evidence: Optional[FieldEvidence] = None


@dataclass
class WholeLifeModel(BaseLifeProductModel):
    """Whole life product mechanics."""

    participating: Optional[bool] = None
    guarantee_basis: Optional[str] = None  # e.g. "2001 CSO", "net level reserve"

    guaranteed_cash_value_table: Optional[TableWithStatus] = None
    dividend_rules: Optional[str] = None
    paid_up_options: Optional[str] = None

    field_evidence: Dict[str, FieldEvidence] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Universal life
# ---------------------------------------------------------------------------


@dataclass
class FeeSchedule:
    """Simplified fee schedule wrapper for UL and related lines."""

    id: str
    description: Optional[str] = None
    evidence: Optional[FieldEvidence] = None


@dataclass
class UniversalLifeModel(BaseLifeProductModel):
    """Universal life (and close relatives) mechanics.

    This is the primary target for the current Promise UL work, but it is
    explicitly product-agnostic so other UL products can plug in.
    """

    # Death benefit / face mechanics.
    death_benefit_options: List[str] = field(default_factory=list)

    # Crediting mechanics.
    guaranteed_rate: Optional[float] = None
    current_rate: Optional[float] = None
    crediting_rules: Optional[str] = None

    # Charges.
    coi_basis: Optional[str] = None  # e.g. "NAR", "face".
    coi_tables: List[TableWithStatus] = field(default_factory=list)
    policy_fees: List[FeeSchedule] = field(default_factory=list)
    premium_loads: List[FeeSchedule] = field(default_factory=list)

    # Surrender mechanics.
    surrender_schedule: Optional[TableWithStatus] = None
    mva_rules: Optional[str] = None

    # Loans / withdrawals.
    loan_rules: Optional[str] = None
    withdrawal_rules: Optional[str] = None

    field_evidence: Dict[str, FieldEvidence] = field(default_factory=dict)


__all__ = [
    "EvidenceRef",
    "FieldEvidence",
    "BaseLifeProductModel",
    "RateTable",
    "TermLifeModel",
    "TableWithStatus",
    "WholeLifeModel",
    "FeeSchedule",
    "UniversalLifeModel",
]
