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
_UNSAFE_KINDS = {"fallback", "placeholder", "default"}

# This is deliberately a narrow statement about the existing UL projection
# implementation, not a document claim and not a generic capability registry.
# The existing engine applies a level per-policy fee.  Its COI implementation
# is a flat placeholder and its surrender pattern is only an approximation, so
# neither is verified support for a filed requirement.
_VERIFIED_UL_ENGINE_CAPABILITIES = {
    "policy_admin_fees": {
        "source": "actuarypoc.ui.server:_run_ul_projection.policy_fee_annual",
        "scope": "level per-policy/admin fee only",
    }
}


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

    def provenance(item: Dict[str, Any], *, kind: str = "document_extracted") -> Dict[str, Any]:
        return {
            "kind": kind,
            "documentId": item.get("documentId"),
            "snippet": item.get("snippet"),
            "method": "deterministic_key_value_parser",
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

        base = {
            "id": rid,
            "name": definition.name,
            "impact": definition.impact,
            "reason": "",
            "provenance": {
                "kind": "configuration_rule_derived",
                "method": "applicability_partition_rule",
                "source": "ul_requirement_catalogue_and_partition_rules",
            },
        }
        if applicability_value in {"not applicable", "not_applicable", "no"}:
            base.update(applicability="not_applicable", reason="Document explicitly marks requirement not applicable.")
            bucket = "notApplicable"
        elif not applicability_item and not value_item:
            base.update(applicability="unresolved", reason="Supplied documents do not resolve applicability.")
            bucket = "unresolvedApplicability"
        else:
            base["applicability"] = "applicable"
            capability = _VERIFIED_UL_ENGINE_CAPABILITIES.get(rid)
            if capability is None:
                base.update(reason="Existing UL engine support is not explicitly verified for this requirement.")
                base["capabilityStatus"] = "unresolved"
                base["capabilityProvenance"] = {
                    "kind": "engine_configuration",
                    "source": "no_scoped_capability_declaration",
                    "scope": rid,
                }
                bucket = "unresolvedCapabilities"
            elif value_item is None:
                base.update(reason="Applicable requirement has no supplied document value.")
                bucket = "missingInformation"
            else:
                base.update(
                    reason="Applicable requirement has document evidence and supported behavior.",
                    value=value_item["value"],
                    valueProvenance=provenance(value_item),
                    capabilityStatus="supported",
                    capabilityProvenance={"kind": "engine_configuration", **capability},
                )
                bucket = "satisfied"
        base["category"] = bucket
        partitions[bucket].append(base)
        all_requirements.append(base)

    material_inputs = [item for item in all_requirements if "valueProvenance" in item]
    unsafe_inputs = [
        item for item in material_inputs if item["valueProvenance"].get("kind") in _UNSAFE_KINDS
    ]
    blockers = (
        partitions["missingInformation"]
        + partitions["unsupportedCapabilities"]
        + partitions["unresolvedCapabilities"]
        + partitions["unresolvedApplicability"]
        + unsafe_inputs
    )
    eligible = not blockers
    readiness = {
        **partitions,
        "projectionEligible": eligible,
        "projectionBlockers": [
            {"requirementId": item["id"], "category": item["category"], "reason": item["reason"]}
            for item in blockers
        ],
        "materialInputProvenance": [
            {"requirementId": item["id"], **item["valueProvenance"]} for item in material_inputs
        ],
        "overallStatus": "ready" if eligible else "not_ready",
        "projectionTrustLevel": "document_bound" if eligible else "insufficient",
    }
    return {
        "analysisStatus": "analyzed",
        "analyzedWorkspaceId": workspace_id,
        "analyzedDocumentIds": document_ids,
        "product": product,
        "readiness": readiness,
        "readinessDashboard": readiness,
        "requirements": all_requirements,
        "requirementsClassification": {"all": all_requirements},
    }


__all__ = ["analyze_ul_workspace"]
