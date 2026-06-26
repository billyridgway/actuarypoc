from __future__ import annotations

import os
import time
import json
import uuid
from datetime import date, datetime
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Sequence

import psycopg


# Simple in-process counter for write failures. In the POC we don't yet
# expose this via Prometheus, but logs will include failures and this can
# be wired into metrics later.
_POSTGRES_WRITE_FAILURES = 0


_DDL = """
CREATE TABLE IF NOT EXISTS products (
    product_id text PRIMARY KEY,
    carrier text,
    version integer,
    metadata jsonb,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS assumption_sets (
    id text PRIMARY KEY,
    product_id text NOT NULL,
    version integer,
    status text,
    approved_by text,
    approved_at timestamptz,
    object_path text,
    object_hash text,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
    id bigserial PRIMARY KEY,
    assumption_set_id text NOT NULL,
    approved_by text NOT NULL,
    approved_at timestamptz NOT NULL DEFAULT now(),
    comment text
);

CREATE TABLE IF NOT EXISTS illustration_runs (
    run_id text PRIMARY KEY,
    product_id text NOT NULL,
    project_name text,
    status text,
    created_at timestamptz DEFAULT now(),
    completed_at timestamptz,
    projection_object_path text,
    audit_object_path text,
    input_snapshot_path text,
    error text
);

-- Indexes for common query patterns.
CREATE INDEX IF NOT EXISTS idx_illustration_runs_product
    ON illustration_runs(product_id);
CREATE INDEX IF NOT EXISTS idx_illustration_runs_created
    ON illustration_runs(created_at);

CREATE INDEX IF NOT EXISTS idx_assumption_sets_product
    ON assumption_sets(product_id);

CREATE TABLE IF NOT EXISTS documents (
    id bigserial PRIMARY KEY,
    product_id text,
    kind text,
    serff_id text,
    description text,
    object_path text,
    object_hash text,
    extraction_status text,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_product
    ON documents(product_id);

CREATE TABLE IF NOT EXISTS golden_tests (
    id bigserial PRIMARY KEY,
    product_id text,
    name text,
    policy_object_path text,
    expected_object_path text,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS golden_test_results (
    id bigserial PRIMARY KEY,
    golden_test_id bigint REFERENCES golden_tests(id),
    run_id text,
    passed boolean,
    details text,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS product_model_review_decisions (
    id bigserial PRIMARY KEY,
    product_code text NOT NULL,
    reviewer text,
    decision text NOT NULL,
    exclusions text,
    comments text,
    filing_id text,
    generation_id text,
    pd_generated_at timestamptz,
    pd_generator_version text,
    pd_warning_count integer,
    coverage_covered_count integer,
    coverage_partial_count integer,
    coverage_gap_count integer,
    coverage_not_applicable_count integer,
    validation_status text,
    validation_pass_count integer,
    validation_warning_count integer,
    validation_fail_count integer,
    scenario_validation_status text,
    scenario_validation_pass_count integer,
    scenario_validation_warning_count integer,
    scenario_validation_fail_count integer,
    product_definition_path text,
    product_definition_hash text,
    build_report_path text,
    build_report_hash text,
    coverage_matrix_hash text,
    validation_snapshot_hash text,
    coverage_matrix_path text,
    validation_report_path text,
    bundle_path text,
    bundle_hash text,
    bundle_created_at timestamptz,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pmr_decisions_product
    ON product_model_review_decisions(product_code);

CREATE TABLE IF NOT EXISTS filing_rule_evidence (
    id bigserial PRIMARY KEY,
    product_code text NOT NULL,
    filing_id text,
    document_path text,
    rule_id text NOT NULL,
    page_reference text,
    source_snippet text,
    ai_interpretation text,
    confidence text,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_filing_rule_evidence_product_filing
    ON filing_rule_evidence(product_code, filing_id);

CREATE TABLE IF NOT EXISTS mechanic_patch_approvals (
    id bigserial PRIMARY KEY,
    product_code text NOT NULL,
    dsl_path text NOT NULL,
    source_mechanic_id text,
    source_mechanic_name text,
    patch_status text NOT NULL,
    reviewer text,
    comments text,
    current_value jsonb,
    proposed_value jsonb,
    reviewed_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mechanic_patch_approvals_product_dsl
    ON mechanic_patch_approvals(product_code, dsl_path);

-- Backfill columns for extended Product Model Review decision context
ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS filing_id text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS generation_id text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS pd_generated_at timestamptz;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS pd_generator_version text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS pd_warning_count integer;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS coverage_covered_count integer;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS coverage_partial_count integer;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS coverage_gap_count integer;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS coverage_not_applicable_count integer;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS validation_status text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS validation_pass_count integer;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS validation_warning_count integer;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS validation_fail_count integer;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS scenario_validation_status text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS scenario_validation_pass_count integer;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS scenario_validation_warning_count integer;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS scenario_validation_fail_count integer;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS product_definition_path text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS product_definition_hash text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS build_report_path text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS build_report_hash text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS coverage_matrix_hash text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS validation_snapshot_hash text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS coverage_matrix_path text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS validation_report_path text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS bundle_path text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS bundle_hash text;

ALTER TABLE product_model_review_decisions
    ADD COLUMN IF NOT EXISTS bundle_created_at timestamptz;

CREATE TABLE IF NOT EXISTS workspaces (
    id text PRIMARY KEY,
    status text NOT NULL,
    document_count integer NOT NULL DEFAULT 0,
    latest_snapshot_json jsonb,
    inferred_product_name text,
    inferred_product_code text,
    inferred_product_type text,
    inferred_carrier text,
    inferred_filing_context text,
    inferred_primary_product_code text,
    understanding_status text,
    compliance_overall_status text,
    compliance_implemented_count integer,
    compliance_partial_count integer,
    compliance_missing_count integer,
    projection_trust_level text,
    last_analysis_run_id text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workspace_documents (
    workspace_id text NOT NULL,
    document_id bigint NOT NULL REFERENCES documents(id),
    added_at timestamptz DEFAULT now(),
    PRIMARY KEY (workspace_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_documents_workspace
    ON workspace_documents(workspace_id);

CREATE TABLE IF NOT EXISTS feature_requests (
    id bigserial PRIMARY KEY,
    workspace_id text NOT NULL,
    product_code text,
    capability_id text NOT NULL,
    title text NOT NULL,
    description text,
    impact text,
    priority text,
    status text NOT NULL,
    source_requirement_id text,
    source_requirement_text text,
    source_document text,
    source_reference text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feature_requests_workspace
    ON feature_requests(workspace_id);

CREATE INDEX IF NOT EXISTS idx_feature_requests_workspace_capability
    ON feature_requests(workspace_id, capability_id);
"""


def _get_dsn() -> Optional[str]:
    """Return the Postgres DSN, or None when not configured.

    For the Pi k3s cluster we expect something like:
    postgresql://illustrator:illustrator@postgres.illustrations-poc.svc.cluster.local:5432/illustrations
    """

    return os.getenv("POSTGRES_DSN")


@contextmanager
def _conn() -> Any:
    dsn = _get_dsn()
    if not dsn:
        yield None
        return

    with psycopg.connect(dsn, autocommit=True) as conn:  # type: ignore[arg-type]
        yield conn


def _note_failure(exc: Exception) -> None:
    global _POSTGRES_WRITE_FAILURES
    _POSTGRES_WRITE_FAILURES += 1
    # For now we just log to stderr; a future iteration can expose this via
    # a proper /metrics endpoint.
    print(f"[postgres_client] write failure (count={_POSTGRES_WRITE_FAILURES}): {exc}", flush=True)


def _json_default(obj: object) -> str:
    """Best-effort JSON serializer for non-primitive types.

    We currently only expect datetime/date objects inside workspace
    analysis snapshots; represent them as ISO-8601 strings so the
    snapshot can be stored in Postgres JSONB without failing.
    """

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def ensure_schema() -> None:
    dsn = _get_dsn()
    if not dsn:
        return
    # Best-effort, idempotent DDL.
    try:
        with _conn() as conn:
            if conn is None:
                return
            with conn.cursor() as cur:
                cur.execute(_DDL)
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)


def _workspace_row_to_dict(row: Any, include_snapshot: bool = True) -> Dict[str, Any]:
    """Map a workspaces row to a dict.

    The column order must match the SELECT clauses in the helpers below.
    """

    # When include_snapshot=True we expect latest_snapshot_json in the
    # result set; when False we skip it to reduce payload size.
    if include_snapshot:
        (
            wid,
            status,
            document_count,
            latest_snapshot_json,
            inferred_product_name,
            inferred_product_code,
            inferred_product_type,
            inferred_carrier,
            inferred_filing_context,
            inferred_primary_product_code,
            understanding_status,
            compliance_overall_status,
            compliance_implemented_count,
            compliance_partial_count,
            compliance_missing_count,
            projection_trust_level,
            last_analysis_run_id,
            created_at,
            updated_at,
        ) = row
    else:
        (
            wid,
            status,
            document_count,
            inferred_product_name,
            inferred_product_code,
            inferred_product_type,
            inferred_carrier,
            inferred_filing_context,
            inferred_primary_product_code,
            understanding_status,
            compliance_overall_status,
            compliance_implemented_count,
            compliance_partial_count,
            compliance_missing_count,
            projection_trust_level,
            last_analysis_run_id,
            created_at,
            updated_at,
        ) = row
        latest_snapshot_json = None

    return {
        "id": wid,
        "status": status,
        "document_count": document_count,
        "latest_snapshot_json": latest_snapshot_json,
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
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _feature_request_row_to_dict(row: Any) -> Dict[str, Any]:
    """Map a feature_requests row to a dict.

    The column order must match the SELECT clauses in helpers below.
    """

    (
        fr_id,
        workspace_id,
        product_code,
        capability_id,
        title,
        description,
        impact,
        priority,
        status,
        source_requirement_id,
        source_requirement_text,
        source_document,
        source_reference,
        created_at,
        updated_at,
    ) = row

    return {
        "id": fr_id,
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
        "created_at": created_at,
        "updated_at": updated_at,
    }


def record_assumption_set(
    *,
    set_id: str,
    product_id: str,
    status: str,
    object_path: str,
    object_hash: str,
) -> None:
    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO assumption_sets (id, product_id, status, object_path, object_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                      SET product_id = EXCLUDED.product_id,
                          status = EXCLUDED.status,
                          object_path = EXCLUDED.object_path,
                          object_hash = EXCLUDED.object_hash
                    """,
                    (set_id, product_id, status, object_path, object_hash),
                )
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)


def record_approval(*, set_id: str, approved_by: str, comment: str | None = None) -> None:
    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO approvals (assumption_set_id, approved_by, comment)
                    VALUES (%s, %s, %s)
                    """,
                    (set_id, approved_by, comment),
                )
                cur.execute(
                    """
                    UPDATE assumption_sets
                       SET status = 'approved',
                           approved_by = %s,
                           approved_at = now()
                     WHERE id = %s
                    """,
                    (approved_by, set_id),
                )
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)


def record_illustration_run(
    *,
    run_id: str,
    product_id: str,
    project_name: str | None,
    status: str,
    projection_object_path: str | None = None,
    audit_object_path: str | None = None,
    input_snapshot_path: str | None = None,
    error: str | None = None,
) -> None:
    """Record or update an illustration run.

    For the POC we treat each call as a completed run (success or failure),
    and set created_at/completed_at to "now" on first insert.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return
            with conn.cursor() as cur:
                now = time.time()
                cur.execute(
                    """
                    INSERT INTO illustration_runs (
                        run_id, product_id, project_name, status,
                        created_at, completed_at,
                        projection_object_path, audit_object_path, input_snapshot_path,
                        error
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        to_timestamp(%s), to_timestamp(%s),
                        %s, %s, %s,
                        %s
                    )
                    ON CONFLICT (run_id) DO UPDATE
                      SET status = EXCLUDED.status,
                          completed_at = EXCLUDED.completed_at,
                          projection_object_path = EXCLUDED.projection_object_path,
                          audit_object_path = EXCLUDED.audit_object_path,
                          input_snapshot_path = EXCLUDED.input_snapshot_path,
                          error = EXCLUDED.error
                    """,
                    (
                        run_id,
                        product_id,
                        project_name,
                        status,
                        now,
                        now,
                        projection_object_path,
                        audit_object_path,
                        input_snapshot_path,
                        error,
                    ),
                )
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)


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
    """Create a single local feature request for a workspace.

    This helper performs a straightforward INSERT and returns the stored
    row as a dict. Callers are responsible for enforcing idempotency
    (e.g. avoiding duplicates per workspace+capability) at a higher
    level.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO feature_requests (
                        workspace_id,
                        product_code,
                        capability_id,
                        title,
                        description,
                        impact,
                        priority,
                        status,
                        source_requirement_id,
                        source_requirement_text,
                        source_document,
                        source_reference
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING
                        id,
                        workspace_id,
                        product_code,
                        capability_id,
                        title,
                        description,
                        impact,
                        priority,
                        status,
                        source_requirement_id,
                        source_requirement_text,
                        source_document,
                        source_reference,
                        created_at,
                        updated_at
                    """,
                    (
                        workspace_id,
                        product_code,
                        capability_id,
                        title,
                        description,
                        impact,
                        priority,
                        status,
                        source_requirement_id,
                        source_requirement_text,
                        source_document,
                        source_reference,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return _feature_request_row_to_dict(row)
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def list_feature_requests(workspace_id: str) -> List[Dict[str, Any]]:
    """Return all feature requests for a workspace.

    Results are ordered by created_at ascending to provide a stable
    review order in the UI.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return []
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        workspace_id,
                        product_code,
                        capability_id,
                        title,
                        description,
                        impact,
                        priority,
                        status,
                        source_requirement_id,
                        source_requirement_text,
                        source_document,
                        source_reference,
                        created_at,
                        updated_at
                      FROM feature_requests
                     WHERE workspace_id = %s
                  ORDER BY created_at ASC, id ASC
                    """,
                    (workspace_id,),
                )
                rows = cur.fetchall() or []
                return [_feature_request_row_to_dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return []


def get_feature_request(feature_request_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single feature request by id.

    When Postgres is unavailable or the id does not exist, returns
    ``None`` instead of raising.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        workspace_id,
                        product_code,
                        capability_id,
                        title,
                        description,
                        impact,
                        priority,
                        status,
                        source_requirement_id,
                        source_requirement_text,
                        source_document,
                        source_reference,
                        created_at,
                        updated_at
                      FROM feature_requests
                     WHERE id = %s
                    """,
                    (feature_request_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return _feature_request_row_to_dict(row)
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def update_feature_request_status(
    *, feature_request_id: int, workspace_id: Optional[str], status: str
) -> Optional[Dict[str, Any]]:
    """Update the status of a feature request.

    When ``workspace_id`` is provided the update is scoped to that
    workspace to avoid cross-workspace edits.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                if workspace_id:
                    cur.execute(
                        """
                        UPDATE feature_requests
                           SET status = %s,
                               updated_at = now()
                         WHERE id = %s
                           AND workspace_id = %s
                     RETURNING
                        id,
                        workspace_id,
                        product_code,
                        capability_id,
                        title,
                        description,
                        impact,
                        priority,
                        status,
                        source_requirement_id,
                        source_requirement_text,
                        source_document,
                        source_reference,
                        created_at,
                        updated_at
                        """,
                        (status, feature_request_id, workspace_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE feature_requests
                           SET status = %s,
                               updated_at = now()
                         WHERE id = %s
                     RETURNING
                        id,
                        workspace_id,
                        product_code,
                        capability_id,
                        title,
                        description,
                        impact,
                        priority,
                        status,
                        source_requirement_id,
                        source_requirement_text,
                        source_document,
                        source_reference,
                        created_at,
                        updated_at
                        """,
                        (status, feature_request_id),
                    )

                row = cur.fetchone()
                if not row:
                    return None
                return _feature_request_row_to_dict(row)
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def create_workspace() -> Optional[Dict[str, Any]]:
    """Create a new document-first workspace.

    Workspaces start in the ``waiting_for_documents`` status with zero
    documents and no analysis snapshot.
    """

    ensure_schema()
    wid = f"ws-{uuid.uuid4().hex[:8]}"
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workspaces (id, status, document_count)
                    VALUES (%s, %s, 0)
                    RETURNING
                        id,
                        status,
                        document_count,
                        latest_snapshot_json,
                        inferred_product_name,
                        inferred_product_code,
                        inferred_product_type,
                        inferred_carrier,
                        inferred_filing_context,
                        inferred_primary_product_code,
                        understanding_status,
                        compliance_overall_status,
                        compliance_implemented_count,
                        compliance_partial_count,
                        compliance_missing_count,
                        projection_trust_level,
                        last_analysis_run_id,
                        created_at,
                        updated_at
                    """,
                    (wid, "waiting_for_documents"),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return _workspace_row_to_dict(row, include_snapshot=True)
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def list_workspaces() -> List[Dict[str, Any]]:
    """Return a summary list of workspaces for the catalog view."""

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return []
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        w.id,
                        w.status,
                        COALESCE(dc.doc_count, 0) AS document_count,
                        w.inferred_product_name,
                        w.inferred_product_code,
                        w.inferred_product_type,
                        w.inferred_carrier,
                        w.inferred_filing_context,
                        w.inferred_primary_product_code,
                        w.understanding_status,
                        w.compliance_overall_status,
                        w.compliance_implemented_count,
                        w.compliance_partial_count,
                        w.compliance_missing_count,
                        w.projection_trust_level,
                        w.last_analysis_run_id,
                        w.created_at,
                        w.updated_at
                      FROM workspaces w
                 LEFT JOIN (
                        SELECT workspace_id, COUNT(document_id) AS doc_count
                          FROM workspace_documents
                      GROUP BY workspace_id
                      ) dc
                        ON dc.workspace_id = w.id
                  ORDER BY w.created_at DESC
                    """,
                )
                rows = cur.fetchall() or []
                return [_workspace_row_to_dict(r, include_snapshot=False) for r in rows]
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return []


def get_workspace(workspace_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single workspace with its latest snapshot (when present)."""

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        w.id,
                        w.status,
                        COALESCE(dc.doc_count, 0) AS document_count,
                        w.latest_snapshot_json,
                        w.inferred_product_name,
                        w.inferred_product_code,
                        w.inferred_product_type,
                        w.inferred_carrier,
                        w.inferred_filing_context,
                        w.inferred_primary_product_code,
                        w.understanding_status,
                        w.compliance_overall_status,
                        w.compliance_implemented_count,
                        w.compliance_partial_count,
                        w.compliance_missing_count,
                        w.projection_trust_level,
                        w.last_analysis_run_id,
                        w.created_at,
                        w.updated_at
                      FROM workspaces w
                 LEFT JOIN (
                        SELECT workspace_id, COUNT(document_id) AS doc_count
                          FROM workspace_documents
                      GROUP BY workspace_id
                      ) dc
                        ON dc.workspace_id = w.id
                     WHERE w.id = %s
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return _workspace_row_to_dict(row, include_snapshot=True)
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def record_workspace_document(workspace_id: str, document_id: int) -> None:
    """Associate an existing document with a workspace and bump counts.

    This also updates ``document_count`` and status when the workspace
    was previously waiting for documents.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return
            with conn.cursor() as cur:
                # Link the document to the workspace. ON CONFLICT ensures
                # we do not create duplicate links for the same
                # (workspace_id, document_id) pair.
                cur.execute(
                    """
                    INSERT INTO workspace_documents (workspace_id, document_id)
                    VALUES (%s, %s)
                    ON CONFLICT (workspace_id, document_id) DO NOTHING
                    """,
                    (workspace_id, document_id),
                )
                inserted = cur.rowcount or 0
                # Bump document_count and move from waiting_for_documents
                # to ready_for_analysis when appropriate.
                cur.execute(
                    """
                    UPDATE workspaces
                       SET document_count = document_count + CASE WHEN %s > 0 THEN 1 ELSE 0 END,
                           status = CASE
                                      WHEN status IN ('waiting_for_documents', 'analysis_failed')
                                      THEN 'ready_for_analysis'
                                      ELSE status
                                    END,
                           updated_at = now()
                     WHERE id = %s
                    """,
                    (inserted, workspace_id),
                )
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)


def list_workspace_documents(workspace_id: str) -> List[Dict[str, Any]]:
    """Return documents associated with a workspace.

    Shape mirrors list_product_documents.where possible.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return []
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.id,
                           d.kind,
                           d.description,
                           d.object_path,
                           d.created_at,
                           d.serff_id
                      FROM workspace_documents wd
                      JOIN documents d ON d.id = wd.document_id
                     WHERE wd.workspace_id = %s
                  ORDER BY wd.added_at, d.created_at
                    """,
                    (workspace_id,),
                )
                rows = cur.fetchall() or []
                out: List[Dict[str, Any]] = []
                for r in rows:
                    out.append(
                        {
                            "id": r[0],
                            "kind": r[1],
                            "description": r[2],
                            "object_path": r[3],
                            "created_at": r[4],
                            "serff_id": r[5],
                        }
                    )
                return out
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return []


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
    """Update a workspace with the result of an analysis run."""

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE workspaces
                       SET status = %s,
                           latest_snapshot_json = %s::jsonb,
                           inferred_product_name = %s,
                           inferred_product_code = %s,
                           inferred_product_type = %s,
                           inferred_carrier = %s,
                           inferred_filing_context = %s,
                           inferred_primary_product_code = %s,
                           understanding_status = %s,
                           compliance_overall_status = %s,
                           compliance_implemented_count = %s,
                           compliance_partial_count = %s,
                           compliance_missing_count = %s,
                           projection_trust_level = %s,
                           last_analysis_run_id = %s,
                           updated_at = now()
                     WHERE id = %s
                 RETURNING
                        id,
                        status,
                        document_count,
                        latest_snapshot_json,
                        inferred_product_name,
                        inferred_product_code,
                        inferred_product_type,
                        inferred_carrier,
                        inferred_filing_context,
                        inferred_primary_product_code,
                        understanding_status,
                        compliance_overall_status,
                        compliance_implemented_count,
                        compliance_partial_count,
                        compliance_missing_count,
                        projection_trust_level,
                        last_analysis_run_id,
                        created_at,
                        updated_at
                    """,
                    (
                        status,
                        json.dumps(snapshot, default=_json_default),
                        inferred_product_name,
                        inferred_product_code,
                        inferred_product_type,
                        inferred_carrier,
                        inferred_filing_context,
                        inferred_primary_product_code,
                        understanding_status,
                        compliance_overall_status,
                        compliance_implemented_count,
                        compliance_partial_count,
                        compliance_missing_count,
                        projection_trust_level,
                        last_analysis_run_id,
                        workspace_id,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return _workspace_row_to_dict(row, include_snapshot=True)
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def delete_workspace_and_documents(
    workspace_id: str,
    owned_document_ids: Optional[Sequence[int]] = None,
) -> Optional[Dict[str, Any]]:
    """Delete a workspace and its workspace-owned documents.

    This helper performs conservative cleanup for the document-first
    workspace flow:

    - All ``workspace_documents`` links for the workspace are removed.
    - ``documents`` rows are deleted *only* for document IDs that are
      explicitly marked as workspace-owned by the caller *and* are not
      referenced by any other workspace.
    - The ``workspaces`` row itself is deleted.

    The caller is responsible for performing any corresponding MinIO
    object deletions. When Postgres is unavailable this returns
    ``None`` instead of raising.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                # Normalise and de-duplicate the candidate document IDs.
                owned_ids: List[int] = []
                if owned_document_ids:
                    seen: set[int] = set()
                    for raw in owned_document_ids:
                        try:
                            val = int(raw)
                        except (TypeError, ValueError):
                            continue
                        if val in seen:
                            continue
                        seen.add(val)
                        owned_ids.append(val)

                safe_delete_ids: List[int] = []
                if owned_ids:
                    # Only delete documents that are *exclusively*
                    # referenced by this workspace. Documents linked to
                    # multiple workspaces are treated as shared and kept.
                    cur.execute(
                        """
                        SELECT document_id, COUNT(*) AS ref_count
                          FROM workspace_documents
                         WHERE document_id = ANY(%s)
                        GROUP BY document_id
                        """,
                        (owned_ids,),
                    )
                    rows = cur.fetchall() or []
                    for doc_id, ref_count in rows:
                        if int(ref_count or 0) == 1:
                            safe_delete_ids.append(int(doc_id))

                # Delete workspace_document links first to avoid FK
                # violations when removing document rows.
                cur.execute(
                    """
                    DELETE FROM workspace_documents
                     WHERE workspace_id = %s
                    """,
                    (workspace_id,),
                )
                deleted_links = cur.rowcount or 0

                deleted_docs = 0
                if safe_delete_ids:
                    cur.execute(
                        """
                        DELETE FROM documents
                         WHERE id = ANY(%s)
                        """,
                        (safe_delete_ids,),
                    )
                    deleted_docs = cur.rowcount or 0

                cur.execute(
                    """
                    DELETE FROM workspaces
                     WHERE id = %s
                    """,
                    (workspace_id,),
                )
                deleted_ws = cur.rowcount or 0

                return {
                    "deleted_workspace": deleted_ws,
                    "deleted_documents": deleted_docs,
                    "deleted_workspace_documents": deleted_links,
                    "safe_document_ids": safe_delete_ids,
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def upsert_product_review_draft(
    *,
    product_id: str,
    carrier: str,
    product_name: str,
    product_type: str,
    review_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Create or update a lightweight Product Review draft.

    This reuses the existing ``products`` table and stores review-specific
    fields inside the ``metadata`` JSONB column. It is intentionally MVP-only
    and does not attempt to model full product lifecycle or versions.
    """

    ensure_schema()
    meta: Dict[str, Any] = {
        "name": product_name,
        "type": product_type,
    }
    if review_metadata:
        meta["review"] = review_metadata

    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO products (product_id, carrier, version, metadata)
                    VALUES (%s, %s, 1, %s::jsonb)
                    ON CONFLICT (product_id) DO UPDATE
                      SET carrier = EXCLUDED.carrier,
                          metadata = EXCLUDED.metadata,
                          version = COALESCE(products.version, 0) + 1
                    RETURNING product_id, carrier, version, metadata, created_at
                    """,
                    (product_id, carrier, json.dumps(meta)),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "product_id": row[0],
                    "carrier": row[1],
                    "version": row[2],
                    "metadata": row[3],
                    "created_at": row[4],
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def get_product_review(product_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a stored Product Review draft from the products table.

    Returns ``None`` when Postgres is unavailable or no such product exists.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT product_id, carrier, version, metadata, created_at
                      FROM products
                     WHERE product_id = %s
                    """,
                    (product_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "product_id": row[0],
                    "carrier": row[1],
                    "version": row[2],
                    "metadata": row[3],
                    "created_at": row[4],
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def register_product_catalog(product_id: str, catalog: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Attach or update catalog metadata for a product.

    This marks a product as "known" to the system so that it can appear in
    the product catalog / Known Products dropdown without implying that the
    executable model is production‑ready.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                # Load existing metadata so we can safely merge the
                # catalog block without clobbering review state.
                cur.execute(
                    """
                    SELECT carrier, metadata
                      FROM products
                     WHERE product_id = %s
                    """,
                    (product_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                carrier, meta = row[0], row[1]
                if not isinstance(meta, dict):
                    meta = {}
                meta = dict(meta)
                meta["catalog"] = catalog

                cur.execute(
                    """
                    UPDATE products
                       SET metadata = %s::jsonb,
                           version = COALESCE(version, 0) + 1
                     WHERE product_id = %s
                 RETURNING product_id, carrier, version, metadata, created_at
                    """,
                    (json.dumps(meta), product_id),
                )
                row2 = cur.fetchone()
                if not row2:
                    return None
                return {
                    "product_id": row2[0],
                    "carrier": row2[1],
                    "version": row2[2],
                    "metadata": row2[3],
                    "created_at": row2[4],
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def list_registered_products() -> List[Dict[str, Any]]:
    """Return products whose catalog.status is 'registered'.

    This is used to populate the Known Products dropdown with products
    that have saved review state and filings, regardless of model
    implementation completeness.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return []
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT product_id, carrier, version, metadata, created_at
                      FROM products
                     WHERE metadata -> 'catalog' ->> 'status' = 'registered'
                    ORDER BY product_id
                    """,
                )
                rows = cur.fetchall() or []
                results: List[Dict[str, Any]] = []
                for row in rows:
                    results.append(
                        {
                            "product_id": row[0],
                            "carrier": row[1],
                            "version": row[2],
                            "metadata": row[3],
                            "created_at": row[4],
                        }
                    )
                return results
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return []


def record_document_upload(
    *,
    product_id: str,
    kind: str,
    description: str,
    object_path: str,
    object_hash: Optional[str] = None,
    filing_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Record a single uploaded document for a product.

    This wires into the existing ``documents`` table and keeps the schema
    intentionally loose: callers are responsible for choosing a sensible
    ``kind`` and ``description`` label.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (product_id, kind, serff_id, description, object_path, object_hash)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, product_id, kind, serff_id, description, object_path, object_hash, created_at
                    """,
                    (product_id, kind, filing_id, description, object_path, object_hash),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "product_id": row[1],
                    "kind": row[2],
                    "serff_id": row[3],
                    "description": row[4],
                    "object_path": row[5],
                    "object_hash": row[6],
                    "created_at": row[7],
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def record_mechanic_patch_approval(
    *,
    product_code: str,
    dsl_path: str,
    source_mechanic_id: Optional[str],
    source_mechanic_name: Optional[str],
    patch_status: str,
    reviewer: Optional[str],
    comments: Optional[str],
    current_value: Any,
    proposed_value: Any,
) -> Optional[Dict[str, Any]]:
    """Persist a single mechanics-derived DSL patch approval decision.

    This is intentionally MVP-only and does not attempt to enforce
    uniqueness per (product_code, dsl_path); callers are expected to use
    the latest record when summarising approval state.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mechanic_patch_approvals (
                        product_code,
                        dsl_path,
                        source_mechanic_id,
                        source_mechanic_name,
                        patch_status,
                        reviewer,
                        comments,
                        current_value,
                        proposed_value
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    RETURNING id, product_code, dsl_path, source_mechanic_id,
                              source_mechanic_name, patch_status, reviewer,
                              comments, current_value, proposed_value,
                              reviewed_at
                    """,
                    (
                        product_code,
                        dsl_path,
                        source_mechanic_id,
                        source_mechanic_name,
                        patch_status,
                        reviewer,
                        comments,
                        json.dumps(current_value) if current_value is not None else "null",
                        json.dumps(proposed_value) if proposed_value is not None else "null",
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "product_code": row[1],
                    "dsl_path": row[2],
                    "source_mechanic_id": row[3],
                    "source_mechanic_name": row[4],
                    "patch_status": row[5],
                    "reviewer": row[6],
                    "comments": row[7],
                    "current_value": row[8],
                    "proposed_value": row[9],
                    "reviewed_at": row[10],
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def list_mechanic_patch_approvals(product_code: str) -> List[Dict[str, Any]]:
    """Return all mechanic patch approvals for a product.

    Results are ordered by reviewed_at descending so the first row per
    (product_code, dsl_path) is the latest decision.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return []
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, product_code, dsl_path, source_mechanic_id,
                           source_mechanic_name, patch_status, reviewer,
                           comments, current_value, proposed_value,
                           reviewed_at
                      FROM mechanic_patch_approvals
                     WHERE product_code = %s
                     ORDER BY reviewed_at DESC
                    """,
                    (product_code,),
                )
                rows = cur.fetchall() or []
                out: List[Dict[str, Any]] = []
                for row in rows:
                    out.append(
                        {
                            "id": row[0],
                            "product_code": row[1],
                            "dsl_path": row[2],
                            "source_mechanic_id": row[3],
                            "source_mechanic_name": row[4],
                            "patch_status": row[5],
                            "reviewer": row[6],
                            "comments": row[7],
                            "current_value": row[8],
                            "proposed_value": row[9],
                            "reviewed_at": row[10],
                        }
                    )
                return out
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return []


def relabel_documents_product(old_product_id: str, new_product_id: str) -> int:
    """Update documents rows from one product_id to another.

    Returns the number of rows updated. When Postgres is unavailable this
    returns 0 instead of raising.
    """

    if not old_product_id or not new_product_id or old_product_id == new_product_id:
        return 0

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return 0
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE documents
                       SET product_id = %s
                     WHERE product_id = %s
                    """,
                    (new_product_id, old_product_id),
                )
                return cur.rowcount or 0
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return 0


def list_product_documents(product_id: str, filing_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return documents for a product + optional filing, newest first.

    When Postgres is unavailable, this returns an empty list instead of
    failing the caller.

    - When ``filing_id`` is provided, only documents with matching
      ``serff_id`` are returned.
    - When ``filing_id`` is None, only documents with ``serff_id IS NULL``
      are returned (unassigned filing context).
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return []
            with conn.cursor() as cur:
                if filing_id is not None and filing_id != "":
                    cur.execute(
                        """
                        SELECT id, product_id, kind, serff_id, description, object_path, object_hash, created_at
                          FROM documents
                         WHERE product_id = %s
                           AND serff_id = %s
                         ORDER BY created_at DESC, id DESC
                        """,
                        (product_id, filing_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, product_id, kind, serff_id, description, object_path, object_hash, created_at
                          FROM documents
                         WHERE product_id = %s
                           AND serff_id IS NULL
                         ORDER BY created_at DESC, id DESC
                        """,
                        (product_id,),
                    )
                rows = cur.fetchall() or []
                return [
                    {
                        "id": r[0],
                        "product_id": r[1],
                        "kind": r[2],
                        "serff_id": r[3],
                        "description": r[4],
                        "object_path": r[5],
                        "object_hash": r[6],
                        "created_at": r[7],
                    }
                    for r in rows
                ]
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return []


def record_filing_rule_evidence(
    *,
    product_code: str,
    filing_id: Optional[str],
    document_path: str,
    rule_id: str,
    page_reference: Optional[str],
    source_snippet: str,
    ai_interpretation: str,
    confidence: str,
) -> Optional[Dict[str, Any]]:
    """Insert one filing rule evidence row for a product/filing/rule.

    This is intentionally MVP-simple: the caller provides all fields, and we
    return the stored row so the UI/API can confirm what was written.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO filing_rule_evidence (
                        product_code, filing_id, document_path, rule_id,
                        page_reference, source_snippet, ai_interpretation, confidence
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, product_code, filing_id, document_path, rule_id,
                              page_reference, source_snippet, ai_interpretation, confidence, created_at
                    """,
                    (
                        product_code,
                        filing_id,
                        document_path,
                        rule_id,
                        page_reference,
                        source_snippet,
                        ai_interpretation,
                        confidence,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "product_code": row[1],
                    "filing_id": row[2],
                    "document_path": row[3],
                    "rule_id": row[4],
                    "page_reference": row[5],
                    "source_snippet": row[6],
                    "ai_interpretation": row[7],
                    "confidence": row[8],
                    "created_at": row[9],
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def list_filing_rule_evidence(product_code: str, filing_id: Optional[str]) -> List[Dict[str, Any]]:
    """List filing rule evidence rows for a product + optional filing.

    When Postgres is unavailable, returns an empty list instead of failing
    callers.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return []
            with conn.cursor() as cur:
                if filing_id is not None and filing_id != "":
                    cur.execute(
                        """
                        SELECT id, product_code, filing_id, document_path, rule_id,
                               page_reference, source_snippet, ai_interpretation, confidence, created_at
                          FROM filing_rule_evidence
                         WHERE product_code = %s
                           AND filing_id = %s
                         ORDER BY rule_id, id
                        """,
                        (product_code, filing_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, product_code, filing_id, document_path, rule_id,
                               page_reference, source_snippet, ai_interpretation, confidence, created_at
                          FROM filing_rule_evidence
                         WHERE product_code = %s
                           AND filing_id IS NULL
                         ORDER BY rule_id, id
                        """,
                        (product_code,),
                    )
                rows = cur.fetchall() or []
                return [
                    {
                        "id": r[0],
                        "product_code": r[1],
                        "filing_id": r[2],
                        "document_path": r[3],
                        "rule_id": r[4],
                        "page_reference": r[5],
                        "source_snippet": r[6],
                        "ai_interpretation": r[7],
                        "confidence": r[8],
                        "created_at": r[9],
                    }
                    for r in rows
                ]
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return []


def get_last_product_model_review_decision(product_code: str) -> Optional[Dict[str, Any]]:
    """Return the most recent Product Model Review decision for a product.

    When Postgres is unavailable or no decisions exist, returns None.

    The lookup is deliberately case-insensitive on ``product_code`` so that
    older rows written with inconsistent casing (e.g. "P12TRF" vs "p12trf")
    still participate in the ordering. The *most recent* row is selected by
    ``created_at DESC, id DESC``.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id,
                           product_code,
                           reviewer,
                           decision,
                           exclusions,
                           comments,
                           filing_id,
                           generation_id,
                           pd_generated_at,
                           pd_generator_version,
                           pd_warning_count,
                           coverage_covered_count,
                           coverage_partial_count,
                           coverage_gap_count,
                           coverage_not_applicable_count,
                           validation_status,
                           validation_pass_count,
                           validation_warning_count,
                           validation_fail_count,
                           scenario_validation_status,
                           scenario_validation_pass_count,
                           scenario_validation_warning_count,
                           scenario_validation_fail_count,
                           product_definition_path,
                           product_definition_hash,
                           build_report_path,
                           build_report_hash,
                           coverage_matrix_hash,
                           validation_snapshot_hash,
                           bundle_path,
                           bundle_hash,
                           bundle_created_at,
                           created_at,
                           coverage_matrix_path,
                           validation_report_path
                      FROM product_model_review_decisions
                     WHERE UPPER(product_code) = UPPER(%s)
                     ORDER BY created_at DESC, id DESC
                     LIMIT 1
                    """,
                    (product_code,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "product_code": row[1],
                    "reviewer": row[2],
                    "decision": row[3],
                    "exclusions": row[4],
                    "comments": row[5],
                    "filing_id": row[6],
                    "generation_id": row[7],
                    "pd_generated_at": row[8].isoformat() if getattr(row[8], "isoformat", None) else row[8],
                    "pd_generator_version": row[9],
                    "pd_warning_count": row[10],
                    "coverage_covered_count": row[11],
                    "coverage_partial_count": row[12],
                    "coverage_gap_count": row[13],
                    "coverage_not_applicable_count": row[14],
                    "validation_status": row[15],
                    "validation_pass_count": row[16],
                    "validation_warning_count": row[17],
                    "validation_fail_count": row[18],
                    "scenario_validation_status": row[19],
                    "scenario_validation_pass_count": row[20],
                    "scenario_validation_warning_count": row[21],
                    "scenario_validation_fail_count": row[22],
                    "product_definition_path": row[23],
                    "product_definition_hash": row[24],
                    "build_report_path": row[25],
                    "build_report_hash": row[26],
                    "coverage_matrix_hash": row[27],
                    "validation_snapshot_hash": row[28],
                    "bundle_path": row[29],
                    "bundle_hash": row[30],
                    "bundle_created_at": row[31].isoformat() if getattr(row[31], "isoformat", None) else row[31],
                    "created_at": row[32].isoformat() if getattr(row[32], "isoformat", None) else row[32],
                    "coverage_matrix_path": row[33],
                    "validation_report_path": row[34],
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def list_product_model_review_decisions(product_code: str) -> List[Dict[str, Any]]:
    """Return all Product Model Review decisions for a product, newest first.

    The lookup is case-insensitive on ``product_code`` and orders rows by
    ``created_at DESC, id DESC`` so that the most recent decision appears
    first. When Postgres is unavailable this returns an empty list.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return []
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id,
                           product_code,
                           reviewer,
                           decision,
                           exclusions,
                           comments,
                           filing_id,
                           generation_id,
                           pd_generated_at,
                           pd_generator_version,
                           pd_warning_count,
                           coverage_covered_count,
                           coverage_partial_count,
                           coverage_gap_count,
                           coverage_not_applicable_count,
                           validation_status,
                           validation_pass_count,
                           validation_warning_count,
                           validation_fail_count,
                           scenario_validation_status,
                           scenario_validation_pass_count,
                           scenario_validation_warning_count,
                           scenario_validation_fail_count,
                           product_definition_path,
                           product_definition_hash,
                           build_report_path,
                           build_report_hash,
                           coverage_matrix_hash,
                           validation_snapshot_hash,
                           bundle_path,
                           bundle_hash,
                           bundle_created_at,
                           created_at,
                           coverage_matrix_path,
                           validation_report_path
                      FROM product_model_review_decisions
                     WHERE UPPER(product_code) = UPPER(%s)
                     ORDER BY created_at DESC, id DESC
                    """,
                    (product_code,),
                )
                rows = cur.fetchall() or []
                decisions: List[Dict[str, Any]] = []
                for row in rows:
                    decisions.append(
                        {
                            "id": row[0],
                            "product_code": row[1],
                            "reviewer": row[2],
                            "decision": row[3],
                            "exclusions": row[4],
                            "comments": row[5],
                            "filing_id": row[6],
                            "generation_id": row[7],
                            "pd_generated_at": row[8].isoformat() if getattr(row[8], "isoformat", None) else row[8],
                            "pd_generator_version": row[9],
                            "pd_warning_count": row[10],
                            "coverage_covered_count": row[11],
                            "coverage_partial_count": row[12],
                            "coverage_gap_count": row[13],
                            "coverage_not_applicable_count": row[14],
                            "validation_status": row[15],
                            "validation_pass_count": row[16],
                            "validation_warning_count": row[17],
                            "validation_fail_count": row[18],
                            "scenario_validation_status": row[19],
                            "scenario_validation_pass_count": row[20],
                            "scenario_validation_warning_count": row[21],
                            "scenario_validation_fail_count": row[22],
                            "product_definition_path": row[23],
                            "product_definition_hash": row[24],
                            "build_report_path": row[25],
                            "build_report_hash": row[26],
                            "coverage_matrix_hash": row[27],
                            "validation_snapshot_hash": row[28],
                            "bundle_path": row[29],
                            "bundle_hash": row[30],
                            "bundle_created_at": row[31].isoformat() if getattr(row[31], "isoformat", None) else row[31],
                            "created_at": row[32].isoformat() if getattr(row[32], "isoformat", None) else row[32],
                            "coverage_matrix_path": row[33],
                            "validation_report_path": row[34],
                        }
                    )
                return decisions
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return []


def get_product_model_review_decision(product_code: str, decision_id: int) -> Optional[Dict[str, Any]]:
    """Return a single Product Model Review decision by ID for a product.

    The lookup is case-insensitive on ``product_code`` and constrains on the
    numeric ``decision_id``. When Postgres is unavailable or no matching row
    exists, returns None.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id,
                           product_code,
                           reviewer,
                           decision,
                           exclusions,
                           comments,
                           filing_id,
                           generation_id,
                           pd_generated_at,
                           pd_generator_version,
                           pd_warning_count,
                           coverage_covered_count,
                           coverage_partial_count,
                           coverage_gap_count,
                           coverage_not_applicable_count,
                           validation_status,
                           validation_pass_count,
                           validation_warning_count,
                           validation_fail_count,
                           scenario_validation_status,
                           scenario_validation_pass_count,
                           scenario_validation_warning_count,
                           scenario_validation_fail_count,
                           product_definition_path,
                           product_definition_hash,
                           build_report_path,
                           build_report_hash,
                           coverage_matrix_hash,
                           validation_snapshot_hash,
                           bundle_path,
                           bundle_hash,
                           bundle_created_at,
                           created_at,
                           coverage_matrix_path,
                           validation_report_path
                      FROM product_model_review_decisions
                     WHERE id = %s
                       AND UPPER(product_code) = UPPER(%s)
                     LIMIT 1
                    """,
                    (decision_id, product_code),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "product_code": row[1],
                    "reviewer": row[2],
                    "decision": row[3],
                    "exclusions": row[4],
                    "comments": row[5],
                    "filing_id": row[6],
                    "generation_id": row[7],
                    "pd_generated_at": row[8].isoformat() if getattr(row[8], "isoformat", None) else row[8],
                    "pd_generator_version": row[9],
                    "pd_warning_count": row[10],
                    "coverage_covered_count": row[11],
                    "coverage_partial_count": row[12],
                    "coverage_gap_count": row[13],
                    "coverage_not_applicable_count": row[14],
                    "validation_status": row[15],
                    "validation_pass_count": row[16],
                    "validation_warning_count": row[17],
                    "validation_fail_count": row[18],
                    "scenario_validation_status": row[19],
                    "scenario_validation_pass_count": row[20],
                    "scenario_validation_warning_count": row[21],
                    "scenario_validation_fail_count": row[22],
                    "product_definition_path": row[23],
                    "product_definition_hash": row[24],
                    "build_report_path": row[25],
                    "build_report_hash": row[26],
                    "coverage_matrix_hash": row[27],
                    "validation_snapshot_hash": row[28],
                    "bundle_path": row[29],
                    "bundle_hash": row[30],
                    "bundle_created_at": row[31].isoformat() if getattr(row[31], "isoformat", None) else row[31],
                    "created_at": row[32].isoformat() if getattr(row[32], "isoformat", None) else row[32],
                    "coverage_matrix_path": row[33],
                    "validation_report_path": row[34],
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def record_product_model_review_decision(
    *,
    product_code: str,
    reviewer: str | None,
    decision: str,
    exclusions: str | None = None,
    comments: str | None = None,
    filing_id: str | None = None,
    generation_id: str | None = None,
    pd_generated_at: str | None = None,
    pd_generator_version: str | None = None,
    pd_warning_count: int | None = None,
    coverage_covered_count: int | None = None,
    coverage_partial_count: int | None = None,
    coverage_gap_count: int | None = None,
    coverage_not_applicable_count: int | None = None,
    validation_status: str | None = None,
    validation_pass_count: int | None = None,
    validation_warning_count: int | None = None,
    validation_fail_count: int | None = None,
    scenario_validation_status: str | None = None,
    scenario_validation_pass_count: int | None = None,
    scenario_validation_warning_count: int | None = None,
    scenario_validation_fail_count: int | None = None,
    product_definition_path: str | None = None,
    product_definition_hash: str | None = None,
    build_report_path: str | None = None,
    build_report_hash: str | None = None,
    coverage_matrix_path: str | None = None,
    coverage_matrix_hash: str | None = None,
    validation_report_path: str | None = None,
    validation_snapshot_hash: str | None = None,
    bundle_path: str | None = None,
    bundle_hash: str | None = None,
    bundle_created_at: str | None = None,
) -> Optional[Dict[str, Any]]:
    """Persist a Product Model Review decision, returning the stored row.

    This is intentionally MVP-simple: a single table capturing who made a
    decision for a given product, what they decided, and any exclusions /
    comments. Callers are expected to enforce allowed decision values.
    """

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                print(
                    "[pmr_decision_db_debug] "
                    f"product_code={product_code} "
                    f"coverage_matrix_path={coverage_matrix_path} "
                    f"coverage_matrix_hash={coverage_matrix_hash} "
                    f"validation_report_path={validation_report_path} "
                    f"validation_snapshot_hash={validation_snapshot_hash}",
                    flush=True,
                )
                cur.execute(
                    """
                    INSERT INTO product_model_review_decisions (
                        product_code,
                        reviewer,
                        decision,
                        exclusions,
                        comments,
                        filing_id,
                        generation_id,
                        pd_generated_at,
                        pd_generator_version,
                        pd_warning_count,
                        coverage_covered_count,
                        coverage_partial_count,
                        coverage_gap_count,
                        coverage_not_applicable_count,
                        validation_status,
                        validation_pass_count,
                        validation_warning_count,
                        validation_fail_count,
                        scenario_validation_status,
                        scenario_validation_pass_count,
                        scenario_validation_warning_count,
                        scenario_validation_fail_count,
                        product_definition_path,
                        product_definition_hash,
                        build_report_path,
                        build_report_hash,
                        coverage_matrix_path,
                        coverage_matrix_hash,
                        validation_report_path,
                        validation_snapshot_hash,
                        bundle_path,
                        bundle_hash,
                        bundle_created_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    RETURNING id,
                              product_code,
                              reviewer,
                              decision,
                              exclusions,
                              comments,
                              filing_id,
                              generation_id,
                              pd_generated_at,
                              pd_generator_version,
                              pd_warning_count,
                              coverage_covered_count,
                              coverage_partial_count,
                              coverage_gap_count,
                              coverage_not_applicable_count,
                              validation_status,
                              validation_pass_count,
                              validation_warning_count,
                              validation_fail_count,
                              scenario_validation_status,
                              scenario_validation_pass_count,
                              scenario_validation_warning_count,
                              scenario_validation_fail_count,
                              product_definition_path,
                              product_definition_hash,
                              build_report_path,
                              build_report_hash,
                              coverage_matrix_path,
                              coverage_matrix_hash,
                              validation_report_path,
                              validation_snapshot_hash,
                              bundle_path,
                              bundle_hash,
                              bundle_created_at,
                              created_at
                    """,
                    (
                        product_code,
                        reviewer,
                        decision,
                        exclusions,
                        comments,
                        filing_id,
                        generation_id,
                        pd_generated_at,
                        pd_generator_version,
                        pd_warning_count,
                        coverage_covered_count,
                        coverage_partial_count,
                        coverage_gap_count,
                        coverage_not_applicable_count,
                        validation_status,
                        validation_pass_count,
                        validation_warning_count,
                        validation_fail_count,
                        scenario_validation_status,
                        scenario_validation_pass_count,
                        scenario_validation_warning_count,
                        scenario_validation_fail_count,
                        product_definition_path,
                        product_definition_hash,
                        build_report_path,
                        build_report_hash,
                        coverage_matrix_path,
                        coverage_matrix_hash,
                        validation_report_path,
                        validation_snapshot_hash,
                        bundle_path,
                        bundle_hash,
                        bundle_created_at,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "product_code": row[1],
                    "reviewer": row[2],
                    "decision": row[3],
                    "exclusions": row[4],
                    "comments": row[5],
                    "filing_id": row[6],
                    "generation_id": row[7],
                    "pd_generated_at": row[8].isoformat() if getattr(row[8], "isoformat", None) else row[8],
                    "pd_generator_version": row[9],
                    "pd_warning_count": row[10],
                    "coverage_covered_count": row[11],
                    "coverage_partial_count": row[12],
                    "coverage_gap_count": row[13],
                    "coverage_not_applicable_count": row[14],
                    "validation_status": row[15],
                    "validation_pass_count": row[16],
                    "validation_warning_count": row[17],
                    "validation_fail_count": row[18],
                    "scenario_validation_status": row[19],
                    "scenario_validation_pass_count": row[20],
                    "scenario_validation_warning_count": row[21],
                    "scenario_validation_fail_count": row[22],
                    "product_definition_path": row[23],
                    "product_definition_hash": row[24],
                    "build_report_path": row[25],
                    "build_report_hash": row[26],
                    "coverage_matrix_path": row[27],
                    "coverage_matrix_hash": row[28],
                    "validation_report_path": row[29],
                    "validation_snapshot_hash": row[30],
                    "bundle_path": row[31],
                    "bundle_hash": row[32],
                    "bundle_created_at": row[33].isoformat() if getattr(row[33], "isoformat", None) else row[33],
                    "created_at": row[34].isoformat() if getattr(row[34], "isoformat", None) else row[34],
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None


def update_product_model_review_bundle(
    decision_id: int,
    *,
    bundle_path: str,
    bundle_hash: str,
    bundle_created_at: str,
) -> None:
    """Update bundle metadata for an existing PMR decision row."""

    ensure_schema()
    try:
        with _conn() as conn:
            if conn is None:
                return
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE product_model_review_decisions
                       SET bundle_path = %s,
                           bundle_hash = %s,
                           bundle_created_at = %s
                     WHERE id = %s
                    """,
                    (bundle_path, bundle_hash, bundle_created_at, decision_id),
                )
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
