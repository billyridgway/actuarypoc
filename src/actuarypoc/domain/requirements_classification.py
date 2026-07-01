"""Generic requirement classification and readiness helpers.

This module is intentionally product‑agnostic. It encodes the core
"what counts as applicable / implemented / input‑ready" rules that are
shared across Promise UL and future products.

It does **not** know about specific product codes or ICC forms; callers
are expected to provide product‑specific requirement IDs and evidence.

The key ideas mirror the design used for Promise UL readiness:

* Applicability is driven primarily by product documents or reviewer
  decisions; AI candidates and engine observations alone keep a
  requirement in "needs_review".
* Implementation state is about whether behaviour exists in the engine
  (including placeholders).
* Input state is about whether structured inputs / tables are ready for
  filed‑rate comparison (not just placeholders).
* Readiness only counts gaps where applicability is confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Optional


class EvidenceKind(str, Enum):
    """Origin for a single evidence item.

    Kept as a separate Enum instead of overloading arbitrary strings so
    rules stay explicit and testable.
    """

    PRODUCT_DOCUMENT = "product_document"  # SERFF filings, actuarial memo, specs
    PRODUCT_DEFINITION = "product_definition"  # curated ProductDefinition objects
    AI_EXTRACTION = "ai_extraction"  # LLM‑extracted candidates
    ENGINE_INTROSPECTION = "engine_introspection"  # runtime mechanics/assumptions
    REVIEWER_DECISION = "reviewer_decision"  # explicit human decisions


class Applicability(str, Enum):
    CONFIRMED_APPLICABLE = "confirmed_applicable"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED_NOT_APPLICABLE = "confirmed_not_applicable"


class ImplementationState(str, Enum):
    NOT_IMPLEMENTED = "not_implemented"
    PARTIAL = "partial"
    IMPLEMENTED = "implemented"
    UNKNOWN = "unknown"


class InputState(str, Enum):
    MISSING = "missing"
    PLACEHOLDER = "placeholder"
    READY = "ready"
    NOT_REQUIRED = "not_required"
    UNKNOWN = "unknown"


class Impact(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewerDecisionKind(str, Enum):
    CONFIRM_APPLICABLE = "confirm_applicable"
    MARK_NOT_APPLICABLE = "mark_not_applicable"


@dataclass
class Evidence:
    """Normalised evidence stub used for classification rules.

    This is deliberately small – callers can attach richer objects on
    the side and only project the fields needed for classification.
    """

    kind: EvidenceKind
    status: str = "unknown"  # e.g. "extracted", "inferred", "placeholder", "missing"
    origin: Optional[str] = None  # e.g. "ul_defaults", "pricing_workbook"


@dataclass
class ReviewerDecision:
    kind: ReviewerDecisionKind


@dataclass
class RequirementClassification:
    requirement_id: str
    impact: Impact

    applicability: Applicability
    implementation_state: ImplementationState
    input_state: InputState

    # When True, this requirement should be included in the
    # readiness "blockingConfirmedGaps" list.
    is_blocking_gap: bool = False


def _has_product_evidence(evidence: Iterable[Evidence]) -> bool:
    for ev in evidence:
        if ev.kind in {EvidenceKind.PRODUCT_DOCUMENT, EvidenceKind.PRODUCT_DEFINITION}:
            return True
    return False


def _has_engine_or_ai_evidence(evidence: Iterable[Evidence]) -> bool:
    for ev in evidence:
        if ev.kind in {EvidenceKind.AI_EXTRACTION, EvidenceKind.ENGINE_INTROSPECTION}:
            return True
    return False


def classify_applicability(
    *,
    requirement_id: str,
    applicability_evidence: Iterable[Evidence],
    reviewer_decisions: Iterable[ReviewerDecision] = (),
) -> Applicability:
    """Classify whether a requirement is applicable.

    Rules (tests are written to lock these in):

    1. Any MARK_NOT_APPLICABLE reviewer decision wins ⇒ confirmed_not_applicable.
    2. Else any CONFIRM_APPLICABLE reviewer decision wins ⇒ confirmed_applicable.
    3. Else any product_document / product_definition evidence ⇒ confirmed_applicable.
    4. Else only AI / engine evidence ⇒ needs_review.
    """

    # 1) Explicit reviewer overrides.
    for decision in reviewer_decisions:
        if decision.kind is ReviewerDecisionKind.MARK_NOT_APPLICABLE:
            return Applicability.CONFIRMED_NOT_APPLICABLE

    for decision in reviewer_decisions:
        if decision.kind is ReviewerDecisionKind.CONFIRM_APPLICABLE:
            return Applicability.CONFIRMED_APPLICABLE

    # 2) Product documents / curated definitions confirm applicability.
    if _has_product_evidence(applicability_evidence):
        return Applicability.CONFIRMED_APPLICABLE

    # 3) Engine / AI alone cannot confirm applicability.
    if _has_engine_or_ai_evidence(applicability_evidence):
        return Applicability.NEEDS_REVIEW

    # Default: nothing concrete yet.
    return Applicability.NEEDS_REVIEW


def classify_implementation_state(
    *,
    implementation_evidence: Iterable[Evidence],
) -> ImplementationState:
    """Classify whether behaviour exists in the engine.

    Any non‑missing status in AI / engine evidence implies behaviour is
    present somewhere (even as a placeholder).
    """

    saw_non_missing = False
    for ev in implementation_evidence:
        status = (ev.status or "").lower()
        if status in {"extracted", "inferred", "placeholder"}:
            return ImplementationState.PARTIAL if status == "placeholder" else ImplementationState.IMPLEMENTED
        if status and status != "missing":
            saw_non_missing = True

    if saw_non_missing:
        return ImplementationState.PARTIAL

    return ImplementationState.NOT_IMPLEMENTED


def classify_input_state(
    *,
    input_evidence: Iterable[Evidence],
) -> InputState:
    """Classify whether structured inputs / tables are ready.

    * Any placeholder‑only values ⇒ placeholder.
    * Confirmed extracted / inferred tables ⇒ ready.
    * No evidence ⇒ missing.
    """

    saw_any = False
    saw_ready = False
    saw_placeholder = False

    for ev in input_evidence:
        saw_any = True
        status = (ev.status or "").lower()
        origin = (ev.origin or "").lower()

        # Placeholder runtime defaults never count as filing evidence.
        if status == "placeholder" or origin == "placeholder":
            saw_placeholder = True
            continue
        if status in {"extracted", "inferred"}:
            saw_ready = True

    if not saw_any:
        return InputState.MISSING
    if saw_ready:
        return InputState.READY
    if saw_placeholder:
        return InputState.PLACEHOLDER
    return InputState.UNKNOWN


def classify_requirement(
    *,
    requirement_id: str,
    impact: Impact,
    applicability_evidence: Iterable[Evidence],
    implementation_evidence: Iterable[Evidence],
    input_evidence: Iterable[Evidence],
    reviewer_decisions: Iterable[ReviewerDecision] = (),
) -> RequirementClassification:
    """End‑to‑end requirement classification.

    This function deliberately *does not* know about specific Promise UL
    IDs, but it does encode the readiness semantics we rely on:

    * Only confirmed_applicable requirements are eligible to become
      blocking gaps.
    * Within confirmed_applicable, a requirement is a blocking gap when
      either implementation or inputs are not "ready".
    """

    applicability = classify_applicability(
        requirement_id=requirement_id,
        applicability_evidence=list(applicability_evidence),
        reviewer_decisions=list(reviewer_decisions),
    )

    impl_state = classify_implementation_state(
        implementation_evidence=list(implementation_evidence),
    )

    input_state = classify_input_state(input_evidence=list(input_evidence))

    is_blocking = False
    if applicability is Applicability.CONFIRMED_APPLICABLE:
        # Any high‑ or medium‑impact requirement that is not fully
        # implemented AND input‑ready is treated as a blocking gap.
        if impact in {Impact.HIGH, Impact.MEDIUM}:
            if impl_state is not ImplementationState.IMPLEMENTED or input_state is not InputState.READY:
                is_blocking = True

    return RequirementClassification(
        requirement_id=requirement_id,
        impact=impact,
        applicability=applicability,
        implementation_state=impl_state,
        input_state=input_state,
        is_blocking_gap=is_blocking,
    )
