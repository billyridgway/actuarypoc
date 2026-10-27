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


def _parse_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp for ordering comparisons; None
    when the value is absent or unparseable (never raises)."""

    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _workspace_key(workspace_id: str) -> str:
    return f"workspaces/{workspace_id}/workspace.json"


def _document_key(workspace_id: str, document_id: int) -> str:
    return f"workspaces/{workspace_id}/documents/{document_id}.json"


def _feature_request_key(workspace_id: str, feature_request_id: int) -> str:
    return f"workspaces/{workspace_id}/feature-requests/{feature_request_id}.json"


def _executable_mechanics_key(workspace_id: str) -> str:
    return f"workspaces/{workspace_id}/analysis/executable-ul-mechanics.json"


def _mechanics_changes_key(workspace_id: str) -> str:
    return f"workspaces/{workspace_id}/analysis/mechanics-changes.json"


def _validation_pack_key(workspace_id: str, pack_id: str) -> str:
    return f"workspaces/{workspace_id}/validation/packs/{pack_id}.json"


def _validation_run_key(workspace_id: str, run_id: str) -> str:
    return f"workspaces/{workspace_id}/validation/runs/{run_id}.json"


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


# --- Bounded retry for transient object-store errors ---------------------
# The S3 gateway occasionally answers a read of an *existing* object with
# a transient NoSuchKey (or a throttling / 5xx code). One such blip on the
# analyze commit path discarded a completed 215-second analysis on
# Oct 26, 2026, so analyze-pipeline writes and the analysis-job state
# writes go through the retry helpers here. Scope is deliberately
# narrow: only callers that opt in get retries.

_TRANSIENT_STORE_CODES = {
    "NoSuchKey",
    "NoSuchObject",
    "NoSuchBucket",
    "SlowDown",
    "InternalError",
    "ServiceUnavailable",
    "RequestTimeout",
    "RequestTimeoutExceeded",
}


class _TransientWorkspaceMissing(Exception):
    """A workspace read came back empty; it may be a transient blip."""


def is_transient_store_error(exc: BaseException) -> bool:
    """True when `exc` looks like a transient object-store failure."""

    if isinstance(exc, _TransientWorkspaceMissing):
        return True
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code in _TRANSIENT_STORE_CODES:
        return True
    return isinstance(exc, (ConnectionError, TimeoutError))


def with_store_retry(
    operation,
    *,
    attempts: int = 4,
    base_delay_seconds: float = 0.25,
    sleep=time.sleep,
):
    """Run `operation`, retrying transient store errors with backoff.

    Non-transient errors propagate immediately; when the attempts are
    exhausted the last transient error is re-raised.
    """

    last_exc: Optional[BaseException] = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - re-raised when not transient
            if not is_transient_store_error(exc):
                raise
            last_exc = exc
            if attempt + 1 < attempts:
                sleep(base_delay_seconds * (2**attempt))
    assert last_exc is not None  # attempts >= 1 guarantees a failure was seen
    raise last_exc


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


def create_workspace(name: Optional[str] = None) -> Dict[str, Any]:
    workspace_id = f"ws-{uuid.uuid4().hex[:8]}"
    now = _now()
    workspace = {
        "id": workspace_id,
        "name": name,
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
    source: Optional[Dict[str, Any]] = None,
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
    if source is not None:
        # A source-referenced document (docs/workspace-sources.md): the
        # record carries the reference; no bytes are stored for it.
        document["source"] = source
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


def update_workspace_document(
    workspace_id: str, document: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Persist a mutated document record (e.g. a refreshed source pin)."""

    document_id = document.get("id")
    if document_id is None or get_workspace(workspace_id) is None:
        return None
    _write_json(_document_key(workspace_id, int(document_id)), document)
    return document


def store_workspace_executable_mechanics(
    workspace_id: str, value: Dict[str, Any]
) -> str:
    """Persist the validated, provenance-bearing mechanics used by projections."""

    if get_workspace(workspace_id) is None:
        raise ValueError("workspace does not exist")
    key = _executable_mechanics_key(workspace_id)
    _write_json(key, value)
    return key


def load_workspace_executable_mechanics(workspace_id: str) -> Optional[Dict[str, Any]]:
    return _read_json(_executable_mechanics_key(workspace_id))


def load_workspace_mechanics_changes(workspace_id: str) -> List[Dict[str, Any]]:
    """Return the workspace's mechanics change log, oldest first."""

    payload = _read_json(_mechanics_changes_key(workspace_id)) or {}
    changes = payload.get("changes")
    return list(changes) if isinstance(changes, list) else []


def append_workspace_mechanics_change(
    workspace_id: str, change: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Append one change record to the workspace's mechanics change log.

    The log is the audit trail Eddy asked for: every slot edit records
    who changed what, when, and the prior -> new summary.  It is stored
    as its own object under the workspace prefix so workspace deletion
    removes it with everything else.
    """

    if get_workspace(workspace_id) is None:
        raise ValueError("workspace does not exist")
    changes = load_workspace_mechanics_changes(workspace_id)
    changes.append(change)
    _write_json(_mechanics_changes_key(workspace_id), {"changes": changes})
    return changes


def store_workspace_validation_pack(
    workspace_id: str, pack: Dict[str, Any]
) -> str:
    """Persist a validation pack (Phase 5) under the workspace prefix."""

    if get_workspace(workspace_id) is None:
        raise ValueError("workspace does not exist")
    pack_id = str((pack or {}).get("id") or "")
    if not pack_id:
        raise ValueError("validation pack has no id")
    key = _validation_pack_key(workspace_id, pack_id)
    _write_json(key, pack)
    return key


def load_workspace_validation_pack(
    workspace_id: str, pack_id: str
) -> Optional[Dict[str, Any]]:
    return _read_json(_validation_pack_key(workspace_id, pack_id))


def list_workspace_validation_packs(workspace_id: str) -> List[Dict[str, Any]]:
    packs = _list_json(f"workspaces/{workspace_id}/validation/packs/")
    return sorted(
        packs, key=lambda row: (str(row.get("createdAt") or ""), str(row.get("name") or ""))
    )


def delete_workspace_validation_pack(workspace_id: str, pack_id: str) -> bool:
    if load_workspace_validation_pack(workspace_id, pack_id) is None:
        return False
    client, bucket = _client_and_bucket()
    client.remove_object(bucket, _validation_pack_key(workspace_id, pack_id))
    return True


def store_workspace_validation_run(
    workspace_id: str, run: Dict[str, Any]
) -> str:
    """Persist one validation run report (Phase 5) for the run history."""

    if get_workspace(workspace_id) is None:
        raise ValueError("workspace does not exist")
    run_id = str((run or {}).get("id") or "")
    if not run_id:
        raise ValueError("validation run has no id")
    key = _validation_run_key(workspace_id, run_id)
    _write_json(key, run)
    return key


def load_workspace_validation_run(
    workspace_id: str, run_id: str
) -> Optional[Dict[str, Any]]:
    return _read_json(_validation_run_key(workspace_id, run_id))


def list_workspace_validation_runs(
    workspace_id: str, pack_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return stored validation runs, newest first (optionally per pack)."""

    runs = _list_json(f"workspaces/{workspace_id}/validation/runs/")
    if pack_id is not None:
        runs = [run for run in runs if run.get("packId") == pack_id]
    return sorted(
        runs,
        key=lambda row: (str(row.get("ranAt") or ""), str(row.get("id") or "")),
        reverse=True,
    )


def set_workspace_projection_stale(
    workspace_id: str,
    *,
    stale: bool,
    slots: Optional[Sequence[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Mark (or clear) the workspace's saved projection as stale.

    A slot edit makes the persisted analysis snapshot older than the
    mechanics it was computed from; the flag tells the UI to offer the
    re-run flow.  Analysis itself clears the flag via
    ``update_workspace_analysis``.
    """

    workspace = get_workspace(workspace_id)
    if workspace is None:
        return None
    if stale:
        existing = list(workspace.get("projection_stale_slots") or [])
        for slot in slots or []:
            if slot not in existing:
                existing.append(slot)
        workspace["projection_stale"] = True
        workspace["projection_stale_since"] = _now()
        workspace["projection_stale_slots"] = existing
    else:
        workspace["projection_stale"] = False
        workspace["projection_stale_since"] = None
        workspace["projection_stale_slots"] = []
    workspace["updated_at"] = _now()
    _write_json(_workspace_key(workspace_id), workspace)
    return workspace


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
    clear_projection_stale_through: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    workspace = get_workspace(workspace_id)
    if workspace is None:
        return None
    # Staleness has one precise meaning: the saved projection predates
    # the latest input change (marked by projection_stale_since).  A
    # completed analysis recomputes the saved projection from the
    # inputs as of the moment the analysis STARTED, so it clears only
    # staleness marked at or before that moment — an input change
    # made while the analysis ran postdates the recomputation and
    # must stay marked.  Callers pass the stale-since they observed
    # at start as ``clear_projection_stale_through``; without it, an
    # existing mark is preserved (e.g. the analysis-failure path,
    # whose snapshot was never refreshed).
    current_since = workspace.get("projection_stale_since")
    if current_since is None or (
        clear_projection_stale_through is not None
        and _parse_iso(current_since) is not None
        and _parse_iso(clear_projection_stale_through) is not None
        and _parse_iso(current_since) <= _parse_iso(clear_projection_stale_through)
    ):
        stale_fields = {
            "projection_stale": False,
            "projection_stale_since": None,
            "projection_stale_slots": [],
        }
    else:
        stale_fields = {
            "projection_stale": bool(workspace.get("projection_stale")),
            "projection_stale_since": current_since,
            "projection_stale_slots": list(workspace.get("projection_stale_slots") or []),
        }
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
            **stale_fields,
            "updated_at": _now(),
        }
    )
    _write_json(_workspace_key(workspace_id), workspace)
    return workspace


def update_workspace_analysis_job(
    workspace_id: str,
    patch: Dict[str, Any],
    *,
    status: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Merge `patch` into the workspace record's ``analysis_job`` state.

    The job record is the durable home of background-analysis state
    (docs/analyze-jobs.md): it lives on workspace.json in the object
    store, so any reader — a polling browser, a later page load, an API
    client — sees the same truth, and a job's failure is recorded here
    instead of vanishing with a dead HTTP request. `status`, when given,
    also moves the workspace's own status in the same write. Writes are
    retried on transient store errors; returns the updated workspace,
    or None when the workspace cannot be read after retries.
    """

    def _op() -> Dict[str, Any]:
        workspace = get_workspace(workspace_id)
        if workspace is None:
            raise _TransientWorkspaceMissing(workspace_id)
        job = dict(workspace.get("analysis_job") or {})
        job.update(patch)
        workspace["analysis_job"] = job
        if status is not None:
            workspace["status"] = status
        workspace["updated_at"] = _now()
        _write_json(_workspace_key(workspace_id), workspace)
        return workspace

    try:
        return with_store_retry(_op)
    except _TransientWorkspaceMissing:
        return None


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
