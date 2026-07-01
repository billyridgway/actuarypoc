from actuarypoc.domain.requirements_classification import (
    Applicability,
    Evidence,
    EvidenceKind,
    Impact,
    ImplementationState,
    InputState,
    ReviewerDecision,
    ReviewerDecisionKind,
    classify_applicability,
    classify_requirement,
)


def _ev(kind: EvidenceKind, status: str = "extracted", origin: str | None = None) -> Evidence:
    return Evidence(kind=kind, status=status, origin=origin)


# 1. Requirement with product evidence and no implementation lowers readiness

def test_product_evidence_no_implementation_is_blocking_gap() -> None:
    applicability_evidence = [_ev(EvidenceKind.PRODUCT_DOCUMENT, status="extracted")]
    implementation_evidence: list[Evidence] = []  # no behaviour detected
    input_evidence: list[Evidence] = []

    cls = classify_requirement(
        requirement_id="coi_table",
        impact=Impact.HIGH,
        applicability_evidence=applicability_evidence,
        implementation_evidence=implementation_evidence,
        input_evidence=input_evidence,
    )

    assert cls.applicability is Applicability.CONFIRMED_APPLICABLE
    assert cls.implementation_state is ImplementationState.NOT_IMPLEMENTED
    assert cls.is_blocking_gap is True


# 2. Candidate requirement with only AI / engine evidence does not lower readiness

def test_ai_only_candidate_needs_review_not_blocking() -> None:
    applicability_evidence = [_ev(EvidenceKind.AI_EXTRACTION, status="extracted")]
    implementation_evidence = [_ev(EvidenceKind.ENGINE_INTROSPECTION, status="extracted")]
    input_evidence: list[Evidence] = []

    cls = classify_requirement(
        requirement_id="policy_admin_fees",
        impact=Impact.MEDIUM,
        applicability_evidence=applicability_evidence,
        implementation_evidence=implementation_evidence,
        input_evidence=input_evidence,
    )

    assert cls.applicability is Applicability.NEEDS_REVIEW
    # While applicability is unresolved, we *compute* implementation and
    # input states but they must not create a blocking gap.
    assert cls.is_blocking_gap is False


# 3. Reviewer confirmation promotes needs_review to confirmed_applicable

def test_reviewer_confirm_applicable_overrides_ai_only() -> None:
    applicability_evidence = [_ev(EvidenceKind.AI_EXTRACTION, status="extracted")]
    implementation_evidence = [_ev(EvidenceKind.ENGINE_INTROSPECTION, status="placeholder")]
    input_evidence = [_ev(EvidenceKind.ENGINE_INTROSPECTION, status="placeholder")]
    reviewer_decisions = [ReviewerDecision(kind=ReviewerDecisionKind.CONFIRM_APPLICABLE)]

    cls = classify_requirement(
        requirement_id="policy_admin_fees",
        impact=Impact.MEDIUM,
        applicability_evidence=applicability_evidence,
        implementation_evidence=implementation_evidence,
        input_evidence=input_evidence,
        reviewer_decisions=reviewer_decisions,
    )

    assert cls.applicability is Applicability.CONFIRMED_APPLICABLE
    # With only placeholder implementation/inputs this becomes a
    # confirmed blocking gap for a medium‑impact requirement.
    assert cls.implementation_state is ImplementationState.PARTIAL
    assert cls.input_state is InputState.PLACEHOLDER
    assert cls.is_blocking_gap is True


# 4. Reviewer rejection marks confirmed_not_applicable

def test_reviewer_mark_not_applicable_wins() -> None:
    applicability_evidence = [_ev(EvidenceKind.PRODUCT_DOCUMENT, status="extracted")]

    cls = classify_requirement(
        requirement_id="some_rider",
        impact=Impact.LOW,
        applicability_evidence=applicability_evidence,
        implementation_evidence=[],
        input_evidence=[],
        reviewer_decisions=[ReviewerDecision(kind=ReviewerDecisionKind.MARK_NOT_APPLICABLE)],
    )

    assert cls.applicability is Applicability.CONFIRMED_NOT_APPLICABLE
    # Not eligible as a gap regardless of implementation / inputs.
    assert cls.is_blocking_gap is False


# 5. Engine capability alone cannot create confirmed requirement

def test_engine_capability_only_needs_review() -> None:
    applicability_evidence = [_ev(EvidenceKind.ENGINE_INTROSPECTION, status="extracted")]

    app = classify_applicability(
        requirement_id="engine_only",
        applicability_evidence=applicability_evidence,
        reviewer_decisions=[],
    )

    assert app is Applicability.NEEDS_REVIEW


# 6. Placeholder runtime values cannot serve as filing evidence

def test_placeholder_values_do_not_make_inputs_ready() -> None:
    input_evidence = [
        _ev(EvidenceKind.ENGINE_INTROSPECTION, status="placeholder", origin="placeholder"),
    ]

    cls = classify_requirement(
        requirement_id="surrender_schedule",
        impact=Impact.HIGH,
        applicability_evidence=[_ev(EvidenceKind.PRODUCT_DOCUMENT, status="extracted")],
        implementation_evidence=input_evidence,
        input_evidence=input_evidence,
    )

    assert cls.applicability is Applicability.CONFIRMED_APPLICABLE
    assert cls.input_state is InputState.PLACEHOLDER
    assert cls.is_blocking_gap is True


# 7. No product‑specific codes in classifier logic

def test_classifier_is_product_agnostic() -> None:
    """Sanity‑check that the classifier does not special‑case Promise UL IDs.

    This is a structural test: we only assert that the module text does
    not contain specific product codes that would make the classifier
    Promise‑UL‑only.
    """

    import inspect

    from actuarypoc.domain import requirements_classification as mod

    src = inspect.getsource(mod)
    assert "P12TRF" not in src
    assert "Promise UL" not in src
