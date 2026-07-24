from __future__ import annotations

from typing import Any, Dict, List

from actuarypoc.domain.ul_requirements import get_ul_requirement_definitions
from actuarypoc.extract.workspace_ul_analyzer import analyze_ul_workspace


def _document(document_id: int, workspace_id: str) -> Dict[str, Any]:
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
    docs = [_document(11, "A"), _document(12, "A")]
    blobs = {
        11: _ul_text(name="Alpha UL", code="ALPHA-UL", carrier="Alpha Life", form="UL-A"),
        12: b"Supplement: workspace A only",
        21: _ul_text(name="Foreign UL", code="FOREIGN-UL", carrier="Other", form="UL-X"),
    }
    loaded: List[int] = []

    def load(document: Dict[str, Any]) -> bytes:
        loaded.append(document["id"])
        return blobs[document["id"]]

    result = analyze_ul_workspace("A", docs, content_loader=load)

    assert loaded == [11, 12]
    assert result["analyzedWorkspaceId"] == "A"
    assert result["analyzedDocumentIds"] == [11, 12]
    assert result["product"]["code"] == "ALPHA-UL"
    assert "FOREIGN-UL" not in repr(result)


def test_supported_ul_is_document_bound_and_ready() -> None:
    doc = _document(31, "promise")
    payload = _ul_text(
        name="Promise Universal Life",
        code="PROMISE-UL",
        carrier="Promise Life",
        form="ICC18 P18PR",
    )

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
    assert result["readinessDashboard"]["overallStatus"] == "ready"
    assert result["readinessDashboard"]["projectionEligible"] is True
    assert {item["documentId"] for item in result["product"]["provenance"].values()} == {31}


def test_second_ul_identity_does_not_share_promise_or_term_fallback() -> None:
    doc = _document(41, "distinct")
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


def test_unsupported_or_unresolved_product_type_is_analysis_unavailable() -> None:
    unsupported = _document(51, "term")
    unresolved = _document(52, "unknown")

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
        (term_result, "term", 51),
        (unknown_result, "unknown", 52),
    ):
        assert result["analysisStatus"] == "analysis_unavailable"
        assert result["analyzedWorkspaceId"] == workspace_id
        assert result["analyzedDocumentIds"] == [document_id]
        assert result["readinessDashboard"]["overallStatus"] == "analysis_unavailable"
        assert result["readinessDashboard"]["projectionTrustLevel"] == "unavailable"
        assert result["readinessDashboard"]["projectionEligible"] is False
        assert "product" not in result
