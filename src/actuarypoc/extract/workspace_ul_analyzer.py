"""Document-bound adapter for the existing UL requirement analyzer.

The adapter deliberately accepts document records, rather than a product code.  It
uses the existing UL catalogue and produces a small canonical readiness contract.
No registry, runtime assumption, filename, or product default participates in the
result.
"""

from __future__ import annotations

import io
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyPDF2 import PdfReader

from actuarypoc.domain.requirements_classification import (
    Applicability,
    Evidence,
    EvidenceKind,
    Impact,
    InputState,
    ReviewerDecision,
    ReviewerDecisionKind,
    classify_requirement,
)
from actuarypoc.domain.ul_requirements import get_ul_requirement_definitions
from actuarypoc.storage.minio_client import get_bucket_name, get_minio_client


ContentLoader = Callable[[Dict[str, Any]], bytes]

_IDENTITY_KEYS = {
    "product_type": "type",
    "product_name": "name",
    "product_code": "code",
    "carrier": "carrier",
    "policy_form": "form",
}
# This is deliberately a narrow statement about the existing UL projection
# implementation, not a document claim and not a generic capability registry.
# The existing engine applies a level per-policy fee.  Its COI implementation
# is a flat placeholder and its surrender pattern is only an approximation, so
# neither is verified support for a filed requirement.
_VERIFIED_UL_ENGINE_CAPABILITIES = {
    "policy_admin_fees": {
        "status": "supported",
        "source": "actuarypoc.ui.server:_run_ul_projection.policy_fee_annual",
        "scope": "level per-policy/admin fee only",
    },
    "coi_table": {
        "status": "unsupported",
        "source": "actuarypoc.ui.server:_run_ul_projection.config.coi_rate_flat",
        "scope": "flat placeholder is not support for a filed COI rate table",
    },
    "surrender_schedule": {
        "status": "unsupported",
        "source": "actuarypoc.ui.server:_run_ul_projection.config.surrender_period_years/max_surrender_pct",
        "scope": "runtime approximation is not support for a filed surrender schedule",
    },
}


def _input_status(value: str) -> str:
    """Label explicit unsafe values without presenting them as source truth."""

    lowered = value.strip().lower()
    for kind in ("placeholder", "fallback", "default"):
        if re.search(rf"\b{kind}\b", lowered):
            return kind
    return "extracted"


def _analysis_failure(workspace_id: str, errors: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a stable non-fabricating failure contract for invalid membership."""

    return {
        "analysisStatus": "analysis_failed",
        "analysisFailureReason": "Workspace document membership is invalid.",
        "analysisErrors": errors,
        "analyzedWorkspaceId": workspace_id,
        "analyzedDocumentIds": [],
        "readinessDashboard": {
            "overallStatus": "analysis_failed",
            "projectionTrustLevel": "unavailable",
            "projectionEligible": False,
        },
        "extractedFacts": [],
        "requirementsCandidates": [],
    }


def _validate_documents(workspace_id: str, documents: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Validate the complete membership set before any object is loaded."""

    errors: List[Dict[str, Any]] = []
    seen: Dict[str, Tuple[int, Any]] = {}
    for index, document in enumerate(documents):
        document_id = document.get("id") if isinstance(document, dict) else None
        path = None
        if isinstance(document, dict):
            path = document.get("object_path")
            if path is None:
                path = document.get("objectPath")
        if not isinstance(document_id, str) or not document_id.strip():
            errors.append({"code": "invalid_document_id", "index": index})
        else:
            document_id = document_id.strip()
            if document_id in seen:
                first_index, first_path = seen[document_id]
                errors.append(
                    {
                        "code": "duplicate_document_id",
                        "documentId": document_id,
                        "firstIndex": first_index,
                        "index": index,
                        "conflictingObjectPath": path != first_path,
                    }
                )
            else:
                seen[document_id] = (index, path)
        malformed_path = (
            not isinstance(path, str)
            or not path.strip()
            or path != path.strip()
            or path.startswith("/")
            or any(part in {".", ".."} for part in path.split("/"))
        )
        if malformed_path:
            error: Dict[str, Any] = {"code": "invalid_object_path", "index": index}
            if isinstance(document_id, str) and document_id.strip():
                error["documentId"] = document_id.strip()
            errors.append(error)
    return _analysis_failure(workspace_id, errors) if errors else None


def _load_object(document: Dict[str, Any]) -> bytes:
    """Read only the object named by the supplied document record."""

    object_path = document.get("object_path") or document.get("objectPath")
    if not isinstance(object_path, str) or not object_path:
        raise ValueError("workspace document has no object path")
    response = get_minio_client().get_object(get_bucket_name(), object_path)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _text(payload: bytes, object_path: str) -> str:
    if payload.startswith(b"%PDF") or object_path.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(payload))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    return payload.decode("utf-8", errors="replace")


def _fields(text: str) -> Dict[str, List[Tuple[str, str]]]:
    """Parse conservative ``label: value`` evidence from extracted text."""

    result: Dict[str, List[Tuple[str, str]]] = {}
    for raw_line in text.splitlines():
        match = re.match(r"^\s*([A-Za-z][A-Za-z0-9 _.-]{1,80})\s*:\s*(\S.*)\s*$", raw_line)
        if not match:
            continue
        key = re.sub(r"[^a-z0-9]+", "_", match.group(1).strip().lower()).strip("_")
        result.setdefault(key, []).append((match.group(2).strip(), raw_line.strip()))
    return result


def analyze_ul_workspace(
    workspace_id: str,
    documents: List[Dict[str, Any]],
    *,
    content_loader: Optional[ContentLoader] = None,
) -> Dict[str, Any]:
    """Analyze exactly ``documents`` and return canonical UL readiness."""

    validation_failure = _validate_documents(workspace_id, documents)
    if validation_failure is not None:
        return validation_failure

    loader = content_loader or _load_object
    combined: Dict[str, List[Dict[str, Any]]] = {}
    for document in documents:
        path = document.get("object_path") or document.get("objectPath") or ""
        parsed = _fields(_text(loader(document), str(path)))
        for key, values in parsed.items():
            for value, snippet in values:
                combined.setdefault(key, []).append(
                    {"value": value, "snippet": snippet, "documentId": document.get("id")}
                )

    def unique(key: str) -> Optional[Dict[str, Any]]:
        candidates = combined.get(key, [])
        normalized = {str(item["value"]).strip().casefold() for item in candidates}
        return candidates[0] if len(normalized) == 1 else None

    type_item = unique("product_type")
    is_ul = bool(type_item and re.search(r"\buniversal life\b|^ul$", str(type_item["value"]), re.I))
    identity_items = {out: unique(source) for source, out in _IDENTITY_KEYS.items()}
    identity_complete = all(identity_items.values())
    document_ids = [document.get("id") for document in documents]

    if not is_ul or not identity_complete:
        return {
            "analysisStatus": "analysis_unavailable",
            "analysisUnavailableReason": "Supplied document evidence does not resolve one supported UL identity.",
            "analyzedWorkspaceId": workspace_id,
            "analyzedDocumentIds": document_ids,
            "readinessDashboard": {
                "overallStatus": "analysis_unavailable",
                "projectionTrustLevel": "unavailable",
                "projectionEligible": False,
            },
            "extractedFacts": [],
            "requirementsCandidates": [],
        }

    def provenance(item: Dict[str, Any], *, kind: str = "product_document") -> Dict[str, Any]:
        return {
            "kind": kind,
            "documentId": item.get("documentId"),
            "snippet": item.get("snippet"),
            "method": "deterministic_key_value_parser",
            "legacyKind": "document_extracted" if kind == "product_document" else None,
        }

    product: Dict[str, Any] = {}
    product_provenance: Dict[str, Any] = {}
    for field, item in identity_items.items():
        assert item is not None
        product[field] = item["value"]
        product_provenance[field] = provenance(item)
    product["provenance"] = product_provenance

    partitions: Dict[str, List[Dict[str, Any]]] = {
        "satisfied": [],
        "missingInformation": [],
        "unsupportedCapabilities": [],
        "unresolvedCapabilities": [],
        "unresolvedApplicability": [],
        "notApplicable": [],
    }
    all_requirements: List[Dict[str, Any]] = []
    for definition in get_ul_requirement_definitions():
        rid = definition.requirement_id
        value_item = unique(rid)
        applicability_item = unique(f"applicability_{rid}")
        applicability_value = str(applicability_item["value"]).lower() if applicability_item else ""

        capability = _VERIFIED_UL_ENGINE_CAPABILITIES.get(rid)
        capability_status = capability.get("status") if capability else "unknown"
        implementation_evidence: List[Evidence] = []
        if capability_status == "supported":
            implementation_evidence.append(
                Evidence(EvidenceKind.ENGINE_INTROSPECTION, status="extracted", origin="engine_configuration")
            )
        elif capability_status == "unsupported" and rid == "surrender_schedule":
            implementation_evidence.append(
                Evidence(EvidenceKind.ENGINE_INTROSPECTION, status="placeholder", origin="placeholder")
            )

        reviewer_decisions: List[ReviewerDecision] = []
        applicability_evidence: List[Evidence] = []
        if applicability_value in {"not applicable", "not_applicable", "no"}:
            reviewer_decisions.append(ReviewerDecision(ReviewerDecisionKind.MARK_NOT_APPLICABLE))
        elif applicability_item or value_item:
            applicability_evidence.append(Evidence(EvidenceKind.PRODUCT_DOCUMENT, status="extracted"))

        input_status = _input_status(str(value_item["value"])) if value_item else "missing"
        input_evidence: List[Evidence] = []
        if value_item is not None:
            if input_status == "extracted":
                input_evidence.append(Evidence(EvidenceKind.PRODUCT_DOCUMENT, status="extracted"))
            else:
                input_evidence.append(
                    Evidence(EvidenceKind.ENGINE_INTROSPECTION, status="placeholder", origin=input_status)
                )

        classification = classify_requirement(
            requirement_id=rid,
            impact=Impact(definition.impact),
            applicability_evidence=applicability_evidence,
            implementation_evidence=implementation_evidence,
            input_evidence=input_evidence,
            reviewer_decisions=reviewer_decisions,
        )
        base = {
            "id": rid,
            "requirementId": rid,
            "name": definition.name,
            "impact": definition.impact,
            "materiality": definition.impact,
            "applicability": classification.applicability.value,
            "legacyApplicability": {
                Applicability.CONFIRMED_APPLICABLE: "applicable",
                Applicability.NEEDS_REVIEW: "unresolved",
                Applicability.CONFIRMED_NOT_APPLICABLE: "not_applicable",
            }[classification.applicability],
            "implementationState": classification.implementation_state.value,
            "inputState": classification.input_state.value,
            "isBlockingGap": classification.is_blocking_gap,
            "reason": "",
            "provenance": {
                "kind": "deterministic_rule",
                "method": "applicability_partition_rule",
                "source": "ul_requirement_catalogue_and_partition_rules",
                "legacyKind": "configuration_rule_derived",
            },
        }
        if capability is None:
            base["capabilityStatus"] = "unresolved"
            base["capabilityProvenance"] = {
                "kind": "engine_configuration",
                "source": "no_scoped_capability_declaration",
                "scope": rid,
            }
        else:
            base["capabilityStatus"] = capability_status
            base["capabilityProvenance"] = {
                "kind": "engine_configuration",
                **{key: value for key, value in capability.items() if key != "status"},
            }

        if value_item is not None:
            value_kind = "product_document" if input_status == "extracted" else input_status
            base.update(value=value_item["value"], valueProvenance=provenance(value_item, kind=value_kind))

        if classification.applicability is Applicability.CONFIRMED_NOT_APPLICABLE:
            base["reason"] = "Document explicitly marks requirement not applicable."
            primary_bucket = "notApplicable"
            partitions["notApplicable"].append(base)
        elif classification.applicability is Applicability.NEEDS_REVIEW:
            base["reason"] = "Supplied documents do not resolve applicability."
            primary_bucket = "unresolvedApplicability"
            partitions["unresolvedApplicability"].append(base)
        else:
            if classification.input_state is not InputState.READY:
                partitions["missingInformation"].append(base)
            if capability_status == "unsupported":
                partitions["unsupportedCapabilities"].append(base)
            elif capability_status == "unknown":
                partitions["unresolvedCapabilities"].append(base)

            if classification.input_state is not InputState.READY:
                base["reason"] = "Applicable requirement input is absent or not ready."
                primary_bucket = "missingInformation"
            elif capability_status == "unsupported":
                base["reason"] = "Existing UL engine explicitly does not support this filed requirement."
                primary_bucket = "unsupportedCapabilities"
            elif capability_status == "unknown":
                base["reason"] = "Existing UL engine support is not explicitly declared for this requirement."
                primary_bucket = "unresolvedCapabilities"
            else:
                base["reason"] = "Applicable requirement has ready document input and supported behavior."
                primary_bucket = "satisfied"
                partitions["satisfied"].append(base)

        # Compatibility alias: legacy consumers use one presentation category
        # even though canonical gap partitions are intentionally non-exclusive.
        base["category"] = primary_bucket
        all_requirements.append(base)

    material_inputs = [item for item in all_requirements if "valueProvenance" in item]
    blockers = [item for item in all_requirements if item["isBlockingGap"]]
    eligible = not blockers
    readiness = {
        **partitions,
        "projectionEligible": eligible,
        "projectionBlockers": [
            {"requirementId": item["requirementId"], "category": item["category"], "reason": item["reason"]}
            for item in blockers
        ],
        "materialInputProvenance": [
            {"requirementId": item["requirementId"], **item["valueProvenance"]} for item in material_inputs
        ],
        "overallStatus": "ready" if eligible else "not_ready",
        "projectionTrustLevel": "document_bound" if eligible else "insufficient",
    }
    return {
        "analysisStatus": "analyzed",
        "readinessContractVersion": "1.0",
        "analyzedWorkspaceId": workspace_id,
        "analyzedDocumentIds": document_ids,
        "product": product,
        "readiness": readiness,
        "readinessDashboard": readiness,
        "requirements": all_requirements,
        "requirementsClassification": {"all": all_requirements},
    }


__all__ = ["analyze_ul_workspace"]
