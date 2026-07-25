"""MinIO-backed persistence for document-first workspaces.

Workspace state is deliberately stored alongside its durable artifacts instead
of in the cluster-local Postgres instance. Each entity is a small JSON object,
which keeps updates atomic at the object level and makes the complete
workspace portable with its ``workspaces/{id}/`` prefix.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import time
from typing import Any, Dict, List, Optional, Sequence
import uuid

from actuarypoc.storage.minio_client import ensure_bucket, get_bucket_name, get_minio_client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _workspace_key(workspace_id: str) -> str:
    return f"workspaces/{workspace_id}/workspace.json"


def _document_key(workspace_id: str, document_id: int) -> str:
    return f"workspaces/{workspace_id}/documents/{document_id}.json"


def _feature_request_key(workspace_id: str, feature_request_id: int) -> str:
    return f"workspaces/{workspace_id}/feature-requests/{feature_request_id}.json"


def _client_and_bucket() -> tuple[Any, str]:
    client = get_minio_client()
    ensure_bucket(client)
    return client, get_bucket_name()


def _read_json(key: str) -> Optional[Dict[str, Any]]:
    client, bucket = _client_and_bucket()
    response = None
    try:
        response = client.get_object(bucket, key)
        value = json.loads(response.read().decode("utf-8"))
        return value if isinstance(value, dict) else None
    except Exception as exc:  # MinIO uses S3Error for missing keys.
        if getattr(exc, "code", None) in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            return None
        raise
    finally:
        if response is not None:
            response.close()
            response.release_conn()


def _write_json(key: str, value: Dict[str, Any]) -> None:
    client, bucket = _client_and_bucket()
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")
    client.put_object(
        bucket,
        key,
        io.BytesIO(payload),
        length=len(payload),
        content_type="application/json",
    )


def _list_json(prefix: str) -> List[Dict[str, Any]]:
    client, bucket = _client_and_bucket()
    values: List[Dict[str, Any]] = []
    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        if not obj.object_name.endswith(".json"):
            continue
        value = _read_json(obj.object_name)
        if value is not None:
            values.append(value)
    return values


def create_workspace() -> Dict[str, Any]:
    workspace_id = f"ws-{uuid.uuid4().hex[:8]}"
    now = _now()
    workspace = {
        "id": workspace_id,
        "status": "waiting_for_documents",
        "document_count": 0,
        "latest_snapshot_json": {},
        "created_at": now,
        "updated_at": now,
    }
    _write_json(_workspace_key(workspace_id), workspace)
    return workspace


def list_workspaces() -> List[Dict[str, Any]]:
    client, bucket = _client_and_bucket()
    workspaces: List[Dict[str, Any]] = []
    for obj in client.list_objects(bucket, prefix="workspaces/", recursive=True):
        if not obj.object_name.endswith("/workspace.json"):
            continue
        workspace = _read_json(obj.object_name)
        if workspace is not None:
            workspaces.append(workspace)
    return sorted(workspaces, key=lambda row: str(row.get("created_at") or ""), reverse=True)


def get_workspace(workspace_id: str) -> Optional[Dict[str, Any]]:
    return _read_json(_workspace_key(workspace_id))


def create_workspace_document(
    *,
    workspace_id: str,
    description: str,
    object_path: str,
    kind: str = "workspace",
    object_hash: Optional[str] = None,
    filing_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    workspace = get_workspace(workspace_id)
    if workspace is None:
        return None

    document_id = time.time_ns()
    now = _now()
    document = {
        "id": document_id,
        "product_id": workspace_id,
        "kind": kind,
        "serff_id": filing_id,
        "description": description,
        "object_path": object_path,
        "object_hash": object_hash,
        "created_at": now,
    }
    _write_json(_document_key(workspace_id, document_id), document)

    workspace["document_count"] = len(list_workspace_documents(workspace_id))
    if workspace.get("status") in {"waiting_for_documents", "analysis_failed"}:
        workspace["status"] = "ready_for_analysis"
    workspace["updated_at"] = now
    _write_json(_workspace_key(workspace_id), workspace)
    return document


def list_workspace_documents(workspace_id: str) -> List[Dict[str, Any]]:
    documents = _list_json(f"workspaces/{workspace_id}/documents/")
    return sorted(documents, key=lambda row: (str(row.get("created_at") or ""), int(row.get("id") or 0)))


def update_workspace_analysis(
    workspace_id: str,
    *,
    status: str,
    snapshot: Dict[str, Any],
    inferred_product_name: Optional[str] = None,
    inferred_product_code: Optional[str] = None,
    inferred_product_type: Optional[str] = None,
    inferred_carrier: Optional[str] = None,
    inferred_filing_context: Optional[str] = None,
    inferred_primary_product_code: Optional[str] = None,
    understanding_status: Optional[str] = None,
    compliance_overall_status: Optional[str] = None,
    compliance_implemented_count: Optional[int] = None,
    compliance_partial_count: Optional[int] = None,
    compliance_missing_count: Optional[int] = None,
    projection_trust_level: Optional[str] = None,
    last_analysis_run_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    workspace = get_workspace(workspace_id)
    if workspace is None:
        return None
    workspace.update(
        {
            "status": status,
            "latest_snapshot_json": snapshot,
            "inferred_product_name": inferred_product_name,
            "inferred_product_code": inferred_product_code,
            "inferred_product_type": inferred_product_type,
            "inferred_carrier": inferred_carrier,
            "inferred_filing_context": inferred_filing_context,
            "inferred_primary_product_code": inferred_primary_product_code,
            "understanding_status": understanding_status,
            "compliance_overall_status": compliance_overall_status,
            "compliance_implemented_count": compliance_implemented_count,
            "compliance_partial_count": compliance_partial_count,
            "compliance_missing_count": compliance_missing_count,
            "projection_trust_level": projection_trust_level,
            "last_analysis_run_id": last_analysis_run_id,
            "updated_at": _now(),
        }
    )
    _write_json(_workspace_key(workspace_id), workspace)
    return workspace


def delete_workspace_and_documents(
    workspace_id: str,
    owned_document_ids: Optional[Sequence[int]] = None,
) -> Optional[Dict[str, Any]]:
    if get_workspace(workspace_id) is None:
        return None
    client, bucket = _client_and_bucket()
    objects = list(client.list_objects(bucket, prefix=f"workspaces/{workspace_id}/", recursive=True))
    for obj in objects:
        client.remove_object(bucket, obj.object_name)
    return {
        "deleted_documents": len(set(owned_document_ids or [])),
        "deleted_objects": len(objects),
    }


def create_feature_request(
    *,
    workspace_id: str,
    product_code: Optional[str],
    capability_id: str,
    title: str,
    description: Optional[str] = None,
    impact: Optional[str] = None,
    priority: Optional[str] = None,
    status: str = "proposed",
    source_requirement_id: Optional[str] = None,
    source_requirement_text: Optional[str] = None,
    source_document: Optional[str] = None,
    source_reference: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if get_workspace(workspace_id) is None:
        return None
    request_id = time.time_ns()
    now = _now()
    request = {
        "id": request_id,
        "workspace_id": workspace_id,
        "product_code": product_code,
        "capability_id": capability_id,
        "title": title,
        "description": description,
        "impact": impact,
        "priority": priority,
        "status": status,
        "source_requirement_id": source_requirement_id,
        "source_requirement_text": source_requirement_text,
        "source_document": source_document,
        "source_reference": source_reference,
        "created_at": now,
        "updated_at": now,
    }
    _write_json(_feature_request_key(workspace_id, request_id), request)
    return request


def list_feature_requests(workspace_id: str) -> List[Dict[str, Any]]:
    requests = _list_json(f"workspaces/{workspace_id}/feature-requests/")
    return sorted(requests, key=lambda row: (str(row.get("created_at") or ""), int(row.get("id") or 0)))


def update_feature_request_status(
    *, feature_request_id: int, workspace_id: Optional[str], status: str
) -> Optional[Dict[str, Any]]:
    if not workspace_id:
        return None
    key = _feature_request_key(workspace_id, feature_request_id)
    request = _read_json(key)
    if request is None:
        return None
    request["status"] = status
    request["updated_at"] = _now()
    _write_json(key, request)
    return request
