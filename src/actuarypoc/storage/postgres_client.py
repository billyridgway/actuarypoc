from __future__ import annotations

import os
import time
import json
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

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
    product_definition_path text,
    product_definition_hash text,
    build_report_path text,
    build_report_hash text,
    coverage_matrix_hash text,
    validation_snapshot_hash text,
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
                           product_definition_path,
                           product_definition_hash,
                           build_report_path,
                           build_report_hash,
                           coverage_matrix_hash,
                           validation_snapshot_hash,
                           created_at
                      FROM product_model_review_decisions
                     WHERE product_code = %s
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
                    "product_definition_path": row[19],
                    "product_definition_hash": row[20],
                    "build_report_path": row[21],
                    "build_report_hash": row[22],
                    "coverage_matrix_hash": row[23],
                    "validation_snapshot_hash": row[24],
                    "created_at": row[25].isoformat() if getattr(row[25], "isoformat", None) else row[25],
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
    product_definition_path: str | None = None,
    product_definition_hash: str | None = None,
    build_report_path: str | None = None,
    build_report_hash: str | None = None,
    coverage_matrix_hash: str | None = None,
    validation_snapshot_hash: str | None = None,
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
                        product_definition_path,
                        product_definition_hash,
                        build_report_path,
                        build_report_hash,
                        coverage_matrix_hash,
                        validation_snapshot_hash
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s
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
                              product_definition_path,
                              product_definition_hash,
                              build_report_path,
                              build_report_hash,
                              coverage_matrix_hash,
                              validation_snapshot_hash,
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
                        product_definition_path,
                        product_definition_hash,
                        build_report_path,
                        build_report_hash,
                        coverage_matrix_hash,
                        validation_snapshot_hash,
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
                    "product_definition_path": row[19],
                    "product_definition_hash": row[20],
                    "build_report_path": row[21],
                    "build_report_hash": row[22],
                    "coverage_matrix_hash": row[23],
                    "validation_snapshot_hash": row[24],
                    "created_at": row[25].isoformat() if getattr(row[25], "isoformat", None) else row[25],
                }
    except Exception as exc:  # noqa: BLE001
        _note_failure(exc)
        return None
