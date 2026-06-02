from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

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
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pmr_decisions_product
    ON product_model_review_decisions(product_code);
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


def record_product_model_review_decision(
    *,
    product_code: str,
    reviewer: str | None,
    decision: str,
    exclusions: str | None = None,
    comments: str | None = None,
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
                cur.execute(
                    """
                    INSERT INTO product_model_review_decisions (
                        product_code, reviewer, decision, exclusions, comments
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, product_code, reviewer, decision, exclusions, comments, created_at
                    """,
                    (product_code, reviewer, decision, exclusions, comments),
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
                    "created_at": row[6].isoformat() if getattr(row[6], "isoformat", None) else row[6],
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None
