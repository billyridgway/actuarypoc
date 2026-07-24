from __future__ import annotations

from typing import Any, Dict, List

from actuarypoc.domain.ul_requirements import get_ul_requirement_definitions
from actuarypoc.extract.workspace_ul_analyzer import analyze_ul_workspace


def _document(document_id: str, workspace_id: str) -> Dict[str, Any]:
    return {
        "id": document_id,
        "object_path": f"workspaces/{workspace_id}/{document_id}.txt",
    }


def _ul_text(*, name: str, code: str, carrier: str, form: str) -> bytes:
    lines = [
        "Product type: Universal Life",
        f"Product name: {name}",
        f"Product code: {code}",
        f"Carrier: {carrier}",
        f"Policy form: {form}",
    ]
    for definition in get_ul_requirement_definitions():
        lines.extend(
            [
                f"Applicability {definition.requirement_id}: applicable",
                f"{definition.requirement_id}: filed value for {code}",
            ]
        )
    return "\n".join(lines).encode()


def test_analyzer_reads_only_exact_supplied_document_records() -> None:
    docs = [_document("11", "A"), _document("12", "A")]
    blobs = {
        "11": _ul_text(name="Alpha UL", code="ALPHA-UL", carrier="Alpha Life", form="UL-A"),
        "12": b"Supplement: workspace A only",
        "21": _ul_text(name="Foreign UL", code="FOREIGN-UL", carrier="Other", form="UL-X"),
    }
    loaded: List[int] = []

    def load(document: Dict[str, Any]) -> bytes:
        loaded.append(document["id"])
        return blobs[document["id"]]

    result = analyze_ul_workspace("A", docs, content_loader=load)

    assert loaded == ["11", "12"]
    assert result["analyzedWorkspaceId"] == "A"
    assert result["analyzedDocumentIds"] == ["11", "12"]
    assert result["product"]["code"] == "ALPHA-UL"
    assert "FOREIGN-UL" not in repr(result)


def test_missing_capability_declarations_block_readiness() -> None:
    doc = _document("31", "promise")
    payload = _ul_text(
        name="Promise Universal Life",
        code="PROMISE-UL",
        carrier="Promise Life",
        form="ICC18 P18PR",
    )

    payload += b"\nCapability guaranteed_credited_rate: supported"
    result = analyze_ul_workspace("promise", [doc], content_loader=lambda _: payload)

    assert result["analysisStatus"] == "analyzed"
    assert result["product"] == {
        "type": "Universal Life",
        "name": "Promise Universal Life",
        "code": "PROMISE-UL",
        "carrier": "Promise Life",
        "form": "ICC18 P18PR",
        "provenance": result["product"]["provenance"],
    }
    assert result["readinessDashboard"]["overallStatus"] == "not_ready"
    assert result["readinessDashboard"]["projectionEligible"] is False
    unresolved = result["readinessDashboard"]["unresolvedCapabilities"]
    assert unresolved
    assert all(item["capabilityStatus"] == "unresolved" for item in unresolved)
    guaranteed = next(item for item in unresolved if item["id"] == "guaranteed_credited_rate")
    assert guaranteed["capabilityProvenance"]["source"] == "no_scoped_capability_declaration"
    assert {item["documentId"] for item in result["product"]["provenance"].values()} == {"31"}


def test_explicit_scoped_engine_capability_has_non_document_provenance() -> None:
    result = analyze_ul_workspace(
        "scoped",
        [_document("32", "scoped")],
        content_loader=lambda _: _ul_text(name="Scoped UL", code="SCOPED", carrier="C", form="F"),
    )

    fee = next(item for item in result["requirements"] if item["id"] == "policy_admin_fees")
    assert fee["capabilityStatus"] == "supported"
    assert fee["capabilityProvenance"] == {
        "kind": "engine_configuration",
        "source": "actuarypoc.ui.server:_run_ul_projection.policy_fee_annual",
        "scope": "level per-policy/admin fee only",
    }
    assert fee["provenance"]["kind"] == "deterministic_rule"
    assert fee["provenance"]["legacyKind"] == "configuration_rule_derived"


def test_canonical_classification_shape_and_legacy_aliases() -> None:
    result = analyze_ul_workspace(
        "canonical",
        [_document("33", "canonical")],
        content_loader=lambda _: _ul_text(name="Canonical UL", code="CAN-UL", carrier="C", form="F"),
    )

    assert result["readinessContractVersion"] == "1.0"
    assert result["readiness"] is result["readinessDashboard"]
    assert result["requirements"] is result["requirementsClassification"]["all"]
    for item in result["requirementsClassification"]["all"]:
        assert item["requirementId"] == item["id"]
        assert item["materiality"] == item["impact"]
        assert item["applicability"] == "confirmed_applicable"
        assert item["legacyApplicability"] == "applicable"
        assert item["implementationState"] in {
            "implemented", "partial", "not_implemented", "unknown"
        }
        assert item["inputState"] == "ready"
        assert isinstance(item["isBlockingGap"], bool)
        assert item["provenance"]["kind"] == "deterministic_rule"
        assert item["valueProvenance"]["kind"] == "product_document"
        assert item["valueProvenance"]["legacyKind"] == "document_extracted"


def test_missing_input_and_capability_gaps_are_independent() -> None:
    payload = b"\n".join(
        [
            b"Product type: Universal Life",
            b"Product name: Gap UL",
            b"Product code: GAP-UL",
            b"Carrier: Gap Life",
            b"Policy form: GAP-F",
            b"Applicability guaranteed_credited_rate: applicable",
            b"Applicability coi_table: applicable",
        ]
    )
    result = analyze_ul_workspace(
        "gaps", [_document("34", "gaps")], content_loader=lambda _: payload
    )

    missing_ids = {item["requirementId"] for item in result["readiness"]["missingInformation"]}
    unsupported_ids = {
        item["requirementId"] for item in result["readiness"]["unsupportedCapabilities"]
    }
    unresolved_ids = {
        item["requirementId"] for item in result["readiness"]["unresolvedCapabilities"]
    }
    assert {"guaranteed_credited_rate", "coi_table"} <= missing_ids
    assert "coi_table" in unsupported_ids
    assert "guaranteed_credited_rate" in unresolved_ids
    unknown = next(
        item for item in result["requirements"] if item["requirementId"] == "guaranteed_credited_rate"
    )
    assert unknown["capabilityStatus"] == "unresolved"
    assert unknown["implementationState"] == "not_implemented"
    assert unknown["inputState"] == "missing"
    assert unknown["isBlockingGap"] is True


def test_applicability_precedes_missingness_and_document_requests() -> None:
    payload = b"\n".join(
        [
            b"Product type: Universal Life",
            b"Product name: Applicability UL",
            b"Product code: APP-UL",
            b"Carrier: App Life",
            b"Policy form: APP-F",
            b"Applicability policy_admin_fees: not applicable",
        ]
    )
    result = analyze_ul_workspace(
        "applicability", [_document("35", "applicability")], content_loader=lambda _: payload
    )

    fee = next(item for item in result["requirements"] if item["requirementId"] == "policy_admin_fees")
    assert fee["applicability"] == "confirmed_not_applicable"
    assert fee["inputState"] == "not_required"
    assert fee["isBlockingGap"] is False
    assert fee in result["readiness"]["notApplicable"]
    assert fee not in result["readiness"]["missingInformation"]
    assert all(
        blocker["requirementId"] != "policy_admin_fees"
        for blocker in result["readiness"]["projectionBlockers"]
    )

    unresolved = next(
        item for item in result["requirements"] if item["requirementId"] == "death_benefit_option"
    )
    assert unresolved["applicability"] == "needs_review"
    assert unresolved["inputState"] == "missing"
    assert unresolved["isBlockingGap"] is False
    assert unresolved in result["readiness"]["unresolvedApplicability"]
    assert unresolved not in result["readiness"]["missingInformation"]


def test_placeholder_default_or_fallback_input_is_not_ready_or_document_extracted() -> None:
    for marker in ("placeholder", "default", "fallback"):
        payload = b"\n".join(
            [
                b"Product type: Universal Life",
                b"Product name: Unsafe Input UL",
                b"Product code: UNSAFE-UL",
                b"Carrier: Unsafe Life",
                b"Policy form: UNSAFE-F",
                b"Applicability policy_admin_fees: applicable",
                f"policy_admin_fees: {marker} annual fee".encode(),
            ]
        )
        result = analyze_ul_workspace(
            marker, [_document(f"unsafe-{marker}", marker)], content_loader=lambda _: payload
        )
        fee = next(item for item in result["requirements"] if item["requirementId"] == "policy_admin_fees")
        assert fee["inputState"] == "placeholder"
        assert fee["isBlockingGap"] is True
        assert fee["valueProvenance"]["kind"] == marker
        assert fee["valueProvenance"]["kind"] not in {"product_document", "ai_extraction"}
        assert fee in result["readiness"]["missingInformation"]


def test_second_ul_identity_does_not_share_promise_or_term_fallback() -> None:
    doc = _document("41", "distinct")
    payload = _ul_text(
        name="Harbor Flexible UL",
        code="HARBOR-FUL-7",
        carrier="Harbor Mutual",
        form="HM-UL-2026",
    )

    result = analyze_ul_workspace("distinct", [doc], content_loader=lambda _: payload)

    assert result["analysisStatus"] == "analyzed"
    assert result["product"]["name"] == "Harbor Flexible UL"
    assert result["product"]["code"] == "HARBOR-FUL-7"
    assert result["product"]["carrier"] == "Harbor Mutual"
    assert "Promise" not in repr(result)
    assert "P12TRF" not in repr(result)
    assert "ICC18 P18PR" not in repr(result)
    assert all("Promise" not in item.get("reason", "") for item in result["requirements"])


def test_unsupported_or_unresolved_product_type_is_analysis_unavailable() -> None:
    unsupported = _document("51", "term")
    unresolved = _document("52", "unknown")

    term_result = analyze_ul_workspace(
        "term",
        [unsupported],
        content_loader=lambda _: b"Product type: Term Life\nProduct code: P12TRF",
    )
    unknown_result = analyze_ul_workspace(
        "unknown",
        [unresolved],
        content_loader=lambda _: b"Product name: Unclassified filing",
    )

    for result, workspace_id, document_id in (
        (term_result, "term", "51"),
        (unknown_result, "unknown", "52"),
    ):
        assert result["analysisStatus"] == "analysis_unavailable"
        assert result["analyzedWorkspaceId"] == workspace_id
        assert result["analyzedDocumentIds"] == [document_id]
        assert result["readinessDashboard"]["overallStatus"] == "analysis_unavailable"
        assert result["readinessDashboard"]["projectionTrustLevel"] == "unavailable"
        assert result["readinessDashboard"]["projectionEligible"] is False
        assert "product" not in result


def test_invalid_membership_sets_fail_before_loading_any_blob() -> None:
    cases = [
        ([{"id": None, "object_path": "workspaces/w/a.txt"}], "invalid_document_id"),
        ([{"id": " ", "object_path": "workspaces/w/a.txt"}], "invalid_document_id"),
        ([{"id": 7, "object_path": "workspaces/w/a.txt"}], "invalid_document_id"),
        (
            [
                {"id": "same", "object_path": "workspaces/w/a.txt"},
                {"id": "same", "object_path": "workspaces/w/a.txt"},
            ],
            "duplicate_document_id",
        ),
        (
            [
                {"id": "same", "object_path": "workspaces/w/a.txt"},
                {"id": "same", "object_path": "workspaces/w/b.txt"},
            ],
            "duplicate_document_id",
        ),
        ([{"id": "missing"}], "invalid_object_path"),
        ([{"id": "blank", "object_path": "  "}], "invalid_object_path"),
        ([{"id": "malformed", "object_path": "workspaces/../other.txt"}], "invalid_object_path"),
    ]

    for documents, expected_code in cases:
        loaded: List[str] = []
        result = analyze_ul_workspace(
            "w", documents, content_loader=lambda document: loaded.append(document["id"]) or b"ignored"
        )
        assert loaded == []
        assert result["analysisStatus"] == "analysis_failed"
        assert result["analyzedDocumentIds"] == []
        assert result["extractedFacts"] == []
        assert expected_code in {error["code"] for error in result["analysisErrors"]}

    conflicting = analyze_ul_workspace("w", cases[4][0], content_loader=lambda _: b"ignored")
    duplicate = next(error for error in conflicting["analysisErrors"] if error["code"] == "duplicate_document_id")
    assert duplicate["conflictingObjectPath"] is True
