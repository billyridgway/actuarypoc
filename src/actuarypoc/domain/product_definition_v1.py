from __future__ import annotations

"""Minimal v1 ProductDefinition model.

This module defines a small, JSON-serialisable ProductDefinition shape that
is scoped by (product_code, filing_id) and stored in MinIO under::

    product-definitions/{product_code}/{filing_id}/product-definition.json

The goal for v1 is to establish a durable artefact format that captures the
core product dimensions and their documentary backing, without yet building
full ingestion or extraction from SERFF filings.
"""

from typing import Any, Dict, List, Optional

try:  # FastAPI can be configured with either Pydantic v1 or v2
    from pydantic import BaseModel
except Exception:  # pragma: no cover - extremely unlikely in this env
    BaseModel = object  # type: ignore[assignment]


class ProductDefinitionSourceDocument(BaseModel):  # type: ignore[misc]
    """Reference to a source document that informs the ProductDefinition.

    For v1 this is intentionally lightweight and uses the same object paths
    and filing identifiers that the rest of the P12TRF POC uses.
    """

    document_path: str
    description: Optional[str] = None
    filing_id: Optional[str] = None


class ProductDefinitionEvidenceRef(BaseModel):  # type: ignore[misc]
    """Reference from a modeled feature back to a filing rule / evidence row.

    The combination of (rule_id, document_path, page_reference) is enough to
    join back to ``filing_rule_evidence`` rows for richer detail when needed.
    """

    feature_id: str
    rule_id: Optional[str] = None
    document_path: Optional[str] = None
    page_reference: Optional[str] = None


class ProductCoverage(BaseModel):  # type: ignore[misc]
    """Represents a base coverage or rider in the product.

    This is intentionally simple for v1; later slices can add richer
    attributes as needed.
    """

    id: str
    name: str
    kind: str  # e.g. "base" or "rider"
    term_periods: List[int] = []
    notes: Optional[str] = None


class ProductDefinitionV1(BaseModel):  # type: ignore[misc]
    """Top-level ProductDefinition artefact stored in MinIO.

    This model is versioned at the payload level (``schema_version``) so that
    future iterations can evolve without breaking existing artefacts.
    """

    schema_version: str = "product-definition-v1"
    product_code: str
    filing_id: str

    coverages: List[ProductCoverage] = []

    # Core dimensionality for simple term products like P12TRF.
    issue_age_min: Optional[int] = None
    issue_age_max: Optional[int] = None
    term_periods: List[int] = []
    underwriting_classes: List[str] = []
    risk_classes: List[str] = []
    smoker_classes: List[str] = []
    premium_modes: List[str] = []

    # Simple face amount bounds inferred from scenarios when available.
    face_amount_min: Optional[float] = None
    face_amount_max: Optional[float] = None

    # Documentary traceability.
    source_documents: List[ProductDefinitionSourceDocument] = []
    evidence_refs: List[ProductDefinitionEvidenceRef] = []

    extra: Dict[str, Any] = {}

    def summary(self) -> Dict[str, Any]:
        """Return a small summary dict suitable for the Trust Surface UI."""

        return {
            "productCode": self.product_code,
            "filingId": self.filing_id,
            "coverages": [c.dict() for c in self.coverages],  # type: ignore[call-arg]
            "issueAges": {
                "min": self.issue_age_min,
                "max": self.issue_age_max,
            },
            "termPeriods": self.term_periods,
            "underwritingClasses": self.underwriting_classes,
            "riskClasses": self.risk_classes,
            "smokerClasses": self.smoker_classes,
            "premiumModes": self.premium_modes,
            "faceAmounts": {
                "min": self.face_amount_min,
                "max": self.face_amount_max,
            },
            "sourceDocumentCount": len(self.source_documents),
            "evidenceRefCount": len(self.evidence_refs),
        }
