from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.projection.engine import ProjectionEngine
from actuarypoc.projection.mortality import build_term23_surface
from actuarypoc.projection.object_keys import audit_record_object_key
from actuarypoc.projection.premium import PremiumLookupService, build_premium_table, select_face_band
from actuarypoc.config.assumptions import get_current_assumption_for_product
from actuarypoc.storage.minio_client import get_bucket_name, get_minio_client
from actuarypoc.version import get_engine_version
from actuarypoc.product_registry import get_product_definition

# Default prefix for projection objects when no override is supplied.
PROJECTION_PREFIX = "projections/"
_BASE_DSL_DIR = Path(__file__).resolve().parents[1] / "dsl" / "examples"
DEFAULT_POLICY_FORMULA_PATH = _BASE_DSL_DIR / "whole_life.yaml"


def _resolve_policy_formula_path(product_code: str | None) -> Path:
    """Return the DSL file path for the given product code.

    For now this is a simple mapping:
    - TERM23* → term23_level_term.yaml (level term per ICC23 SN 174 N Term23v3)
    - everything else → whole_life.yaml (existing stub behaviour)

    This is intentionally heuristic so we can evolve product-code mappings
    without changing connector payloads.
    """

    code = (product_code or "").upper()

    # Examples this will catch (once real PAS exports exist):
    # - "TERM23"
    # - "TERM23-10", "TERM23-20", "TERM23-30"
    # - "TERM-23-10" style variants
    if code.startswith("TERM23") or code.startswith("TERM-23"):
        return _BASE_DSL_DIR / "term23_level_term.yaml"

    # For all other products, fall back to the generic whole-life DSL.
    # Product-specific behaviour should come from AssumptionSets and DSL
    # files referenced there, not from hard-coded branches in Python.
    return DEFAULT_POLICY_FORMULA_PATH


def get_latest_object_name(prefix: str) -> str:
    client = get_minio_client()
    bucket = get_bucket_name()
    latest = None
    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        if latest is None or obj.last_modified > latest.last_modified:
            latest = obj
    if latest is None:
        raise RuntimeError(f"No objects found under prefix '{prefix}'")
    return latest.object_name


def _load_latest_object(prefix: str) -> Tuple[str, Dict[str, Any]]:
    object_name = get_latest_object_name(prefix)
    client = get_minio_client()
    bucket = get_bucket_name()
    response = client.get_object(bucket, object_name)
    try:
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
        response.release_conn()
    return object_name, payload
    client = get_minio_client()
    bucket = get_bucket_name()
    latest = None
    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        if latest is None or obj.last_modified > latest.last_modified:
            latest = obj
    if latest is None:
        raise RuntimeError(f"No objects found under prefix '{prefix}'")
    response = client.get_object(bucket, latest.object_name)
    try:
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
        response.release_conn()
    return latest.object_name, payload


def _get_records(prefix: str) -> Tuple[str, List[Dict[str, Any]]]:
    object_name, payload = _load_latest_object(prefix)
    records = payload.get("records", [])
    return object_name, records


def build_projection_summary(pas_prefix: str = "pas_export/",
                             actuarial_prefix: str = "actuarial_tables/",
                             rate_prefix: str = "rate_curves/",
                             crm_prefix: str = "crm_accounts/",
                             term23_actuarial_prefix: str = "actuarial_tables_term23/") -> Dict[str, Any]:
    # Prefer a local PAS JSON path when provided (e.g. via ConfigMap-mounted file
    # referenced by PAS_JSON_PATH). This allows clusters to avoid MinIO for PAS
    # while still using MinIO for actuarial, rates, etc.
    pas_json_path = os.getenv("PAS_JSON_PATH")
    if pas_json_path:
        with open(pas_json_path, "r", encoding="utf-8") as handle:
            pas_payload = json.load(handle)
        pas_obj = f"file://{pas_json_path}"
        pas_records = pas_payload.get("records", [])
    else:
        pas_obj, pas_records = _get_records(pas_prefix)

    actuarial_obj, actuarial_records = _get_records(actuarial_prefix)
    rate_obj, rate_records = _get_records(rate_prefix)
    crm_obj, crm_records = _get_records(crm_prefix)

    # Term23-specific actuarial slice is optional; not all products need it.
    try:
        term23_actuarial_obj, term23_actuarial_records = _get_records(term23_actuarial_prefix)
    except RuntimeError:
        term23_actuarial_obj, term23_actuarial_records = None, []

    if not pas_records:
        raise RuntimeError("PAS records empty; cannot run projection")

    # For now we project a single policy record per summary. This record
    # also serves as the canonical source of policy inputs for downstream
    # artefacts (projection summary, input snapshot, RunDetail, and the
    # Product Model Review scenarios).
    policy_record = pas_records[0]

    # Determine the product identity primarily from the orchestrator (e.g. CR / operator),
    # falling back to any legacy PAS product_code field if present.
    product_id = os.getenv("PRODUCT_ID")
    product_code: str | None = None
    assumption_set = None
    formula_path: Path

    if product_id:
        product_code = product_id.upper()
    else:
        raw_code = policy_record.get("product_code")
        if raw_code is not None:
            product_code = str(raw_code).upper()

    if product_code is not None:
        assumption_set = get_current_assumption_for_product(product_code)

    if assumption_set is not None and assumption_set.dsl_file:
        formula_path = _BASE_DSL_DIR / assumption_set.dsl_file
    else:
        formula_path = _resolve_policy_formula_path(product_code)

    formula = load_formula(str(formula_path))

    # Build a Term23 mortality surface when data is available; pass it into the engine
    # so it can surface q_x by duration in the projection output.
    mortality_surface = None
    code = (product_code or "").upper()
    if (code.startswith("TERM23") or code.startswith("TERM-23")) and term23_actuarial_records:
        mortality_surface = build_term23_surface(term23_actuarial_records)

    # Optional premium lookup via a generic premium_table meta block. This is
    # intentionally product-agnostic: Python reads meta["premium_table"] and
    # applies it without knowing which product is being projected.
    warnings: list[str] = []
    premium_table_cfg = getattr(formula, "meta", None) or {}
    premium_table_cfg = premium_table_cfg.get("premium_table") if isinstance(premium_table_cfg, dict) else None

    premium_service: PremiumLookupService | None = None
    premium_table_object: str | None = None
    if isinstance(premium_table_cfg, dict) and premium_table_cfg.get("source") == "minio" and premium_table_cfg.get("format") == "csv":
        prefix = premium_table_cfg.get("prefix")
        if prefix:
            client = get_minio_client()
            bucket = get_bucket_name()
            # Reuse the same "latest object under prefix" convention as other
            # inputs, but interpret the payload as CSV instead of JSON.
            latest = None
            for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
                if latest is None or obj.last_modified > latest.last_modified:
                    latest = obj
            if latest is not None:
                premium_table_object = latest.object_name
                resp = client.get_object(bucket, latest.object_name)
                try:
                    import csv
                    import io as _io

                    text = resp.read().decode("utf-8", errors="ignore")
                    reader = csv.DictReader(_io.StringIO(text))
                    records = list(reader)
                finally:
                    resp.close()
                    resp.release_conn()

                table = build_premium_table(records)
                if table is not None:
                    premium_service = PremiumLookupService(table)

    # If a premium table is available, compute a table-derived premium,
    # compare it to PAS modal_premium, and, when materially different,
    # emit a warning while using the table premium for projections.
    if premium_service is not None:
        try:
            face_amount = float(policy_record.get("face_amount", 0) or 0.0)
        except (TypeError, ValueError):
            face_amount = 0.0

        face_band = select_face_band(getattr(formula, "meta", {}) or {}, face_amount)

        if face_band is not None and face_amount > 0:
            try:
                issue_age = int(policy_record.get("issue_age", 0) or 0)
            except (TypeError, ValueError):
                issue_age = 0
            gender = str(policy_record.get("gender", ""))
            risk_class = str(policy_record.get("risk_class", ""))
            try:
                level_period = int(policy_record.get("level_period", 0) or 0)
            except (TypeError, ValueError):
                level_period = 0

            table_p_per_1000 = premium_service.premium_per_1000(
                issue_age=issue_age,
                gender=gender,
                risk_class=risk_class,
                face_band=face_band,
                level_period=level_period,
            )

            if table_p_per_1000 is not None:
                annual_table_premium = float(table_p_per_1000) * (face_amount / 1000.0)

                basis = str(premium_table_cfg.get("basis", "annual_per_1000"))
                modalization = premium_table_cfg.get("modalization", {}) if isinstance(premium_table_cfg, dict) else {}

                mode = str(policy_record.get("premium_mode", "")).upper()
                rule = str(modalization.get(mode, "none")).lower()

                # Currently only one basis is supported; others would be added
                # here in a data-driven way.
                annual = annual_table_premium if basis == "annual_per_1000" else annual_table_premium

                if rule == "divide_by_12":
                    expected_modal = annual / 12.0
                else:
                    expected_modal = annual

                try:
                    pas_modal = float(policy_record.get("modal_premium", 0.0) or 0.0)
                except (TypeError, ValueError):
                    pas_modal = 0.0

                diff = abs(expected_modal - pas_modal)
                material_threshold = max(0.01, 0.001 * expected_modal)
                if diff > material_threshold:
                    warnings.append(
                        "premium_mismatch: table-derived expected_modal={} vs PAS modal_premium={}".format(
                            round(expected_modal, 6), round(pas_modal, 6)
                        )
                    )

                # Precedence rule for POC/operator path: use table premium for
                # projections when available, but keep PAS modal premium as an
                # observed input in the summary.
                policy_record["premium"] = annual

    engine = ProjectionEngine(formula, mortality_surface=mortality_surface)
    projection = engine.project(policy_record)

    # Capture stable identifiers and environment hints alongside the
    # projection summary. These are used by the AuditRecord writer and
    # the RunDetail / UI layers but remain metadata-only.
    run_id = os.getenv("RUN_ID") or None
    env = os.getenv("ILLUSTRATION_ENVIRONMENT") or os.getenv("ENVIRONMENT") or None

    # Canonical policy input snapshot for downstream consumers. This is kept
    # narrow and product-agnostic: it mirrors the core policy fields that are
    # needed for RunDetail and Product Model Review, without embedding the
    # full PAS record.
    policy_inputs = {
        "issue_age": policy_record.get("issue_age"),
        "gender": policy_record.get("gender"),
        "smoker_class": policy_record.get("smoker_class"),
        "risk_class": policy_record.get("risk_class"),
        "level_period": policy_record.get("level_period"),
        "face_amount": policy_record.get("face_amount"),
        "premium_mode": policy_record.get("premium_mode"),
    }

    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "inputs": {
            "pas_object": pas_obj,
            "actuarial_object": actuarial_obj,
            "rate_object": rate_obj,
            "crm_object": crm_obj,
            "term23_actuarial_object": term23_actuarial_obj,
            "premium_table_object": premium_table_object,
            "policy_id": policy_record.get("policy_id"),
            "product_id": product_id,
            "product_code": product_code,
            "formula_path": str(formula_path),
            "assumption_set_id": getattr(assumption_set, "id", None),
            "run_id": run_id,
            # Minimal, provenance-preserving snapshot of the policy inputs
            # used for this projection. This allows RunDetail and Product
            # Model Review to surface real inputs even when the PAS export
            # schema is thin, without fabricating values.
            "policy_inputs": policy_inputs,
        },
        "metadata": {
            "actuarial_records_count": len(actuarial_records),
            "term23_actuarial_records_count": len(term23_actuarial_records),
            "rate_records_count": len(rate_records),
            "crm_records_count": len(crm_records),
            "environment": env,
        },
        "warnings": warnings,
        "projection": asdict(projection),
    }
    return summary


def build_p12trf_projection_summary(policies_prefix: str = "p12trf/") -> Dict[str, Any]:
    """Build a projection summary for the P12TRF term sample policies.

    This is a POC-specific helper that:
    - reads the latest object under the ``p12trf/`` prefix (produced by
      ``p12trf_policies_job``),
    - uses the P12TRF term DSL (p12trf_term.yaml), and
    - runs the generic ProjectionEngine on the first policy record.

    It deliberately does not depend on PAS exports so the P12TRF slice can
    be showcased independently while PAS integration is still evolving.
    """

    policies_obj, policies_records = _get_records(policies_prefix)
    if not policies_records:
        raise RuntimeError("P12TRF policies empty; cannot run projection")

    policy_record = policies_records[0]

    formula_path = _BASE_DSL_DIR / "p12trf_term.yaml"
    formula = load_formula(str(formula_path))

    # Reuse the Term23 actuarial slice (when present) to drive a thin 2017 CSO
    # mortality surface for the P12TRF sample as well. This keeps the P12TRF
    # projection consistent with the CLI helper and avoids a flat
    # survival=1 approximation.
    try:
        term23_actuarial_obj, term23_actuarial_records = _get_records("actuarial_tables_term23/")
    except RuntimeError:
        term23_actuarial_obj, term23_actuarial_records = None, []

    mortality_surface = None
    if term23_actuarial_records:
        mortality_surface = build_term23_surface(term23_actuarial_records)

    engine = ProjectionEngine(formula, mortality_surface=mortality_surface)
    projection = engine.project(policy_record)

    # Canonical policy inputs for the P12TRF sample path. These mirror the
    # generic policy_inputs block used in build_projection_summary so that
    # RunDetail and Product Model Review can treat both paths uniformly.
    policy_inputs = {
        "issue_age": policy_record.get("issue_age"),
        "gender": policy_record.get("gender"),
        "smoker_class": policy_record.get("smoker_class"),
        "risk_class": policy_record.get("risk_class"),
        "level_period": policy_record.get("level_period"),
        "face_amount": policy_record.get("face_amount"),
        "premium_mode": policy_record.get("premium_mode"),
    }

    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "inputs": {
            "p12trf_policies_object": policies_obj,
            "term23_actuarial_object": term23_actuarial_obj,
            "policy_number": policy_record.get("policy_number"),
            "product_type": policy_record.get("product_type"),
            "formula_path": str(formula_path),
            "policy_inputs": policy_inputs,
        },
        "metadata": {
            "p12trf_records_count": len(policies_records),
        },
        "projection": asdict(projection),
    }
    return summary


def store_projection(summary: Dict[str, Any], object_name: str | None = None) -> str:
    """Persist a projection summary to MinIO and return its object key.

    Priority for the target object name:

    1. If ``object_name`` is provided (e.g. via the CLI ``--object-name``
       option or the ``PROJECTION_OBJECT_NAME`` environment variable), it is
       used *verbatim*. This is the path that the Kubernetes operator Job
       should reference in status.
    2. Otherwise, look for ``PROJECTIONS_PREFIX`` in the environment and use
       that as the base prefix.
    3. If neither is set, fall back to :data:`PROJECTION_PREFIX`.

    In the non-explicit case we append a timestamped filename of the form
    ``projection-<ts>.json`` under the chosen prefix.
    """

    import io
    import os

    client = get_minio_client()
    bucket = get_bucket_name()

    if not object_name:
        # Allow callers (e.g. Jobs) to steer the prefix without having to
        # construct a full object key themselves.
        prefix = os.getenv("PROJECTIONS_PREFIX", PROJECTION_PREFIX)
        if not prefix.endswith("/"):
            prefix = prefix + "/"
        object_name = f"{prefix}projection-{int(datetime.utcnow().timestamp())}.json"

    encoded = json.dumps(summary, indent=2).encode("utf-8")

    client.put_object(
        bucket,
        object_name,
        data=io.BytesIO(encoded),
        length=len(encoded),
        content_type="application/json",
    )
    return object_name


def store_json_metadata(payload: Dict[str, Any], object_name: str) -> str:
    """Persist a small, sanitized JSON document to MinIO.

    This helper is intended for audit / snapshot artefacts. Callers are
    expected to pass only metadata (object keys, counts, timestamps, ids),
    not raw PAS records or policyholder-level values.
    """

    import io

    client = get_minio_client()
    bucket = get_bucket_name()

    encoded = json.dumps(payload, indent=2).encode("utf-8")
    client.put_object(
        bucket,
        object_name,
        data=io.BytesIO(encoded),
        length=len(encoded),
        content_type="application/json",
    )
    return object_name


def build_audit_from_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Derive a lightweight audit document from a projection summary.

    The audit intentionally mirrors only high-level metadata and input
    wiring; the full projection payload is omitted to keep this artefact
    small and free of policyholder-level values.
    """

    inputs = summary.get("inputs", {})
    metadata = summary.get("metadata", {})
    warnings = summary.get("warnings", [])
    engine_version = get_engine_version()

    return {
        "generated_at": summary.get("generated_at"),
        "engine_version": engine_version,
        "inputs": inputs,
        "metadata": metadata,
        "warnings": warnings,
    }


def build_input_snapshot_from_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Return a minimal snapshot of which inputs were used for a run."""

    return {
        "generated_at": summary.get("generated_at"),
        "inputs": summary.get("inputs", {}),
    }


def enrich_audit_record_with_product_definition(
    record: Dict[str, Any], product_definition: Optional[Dict[str, Any]]
) -> None:
    """Best-effort enrichment of an AuditRecord using ProductDefinition data.

    Mutates ``record`` in-place. Safe to call with ``product_definition`` set
    to ``None``.
    """

    if not product_definition:
        return

    # Ensure the product container exists.
    record.setdefault("product", {})

    pd_id = product_definition.get("product_definition_id")
    if pd_id:
        record["product"]["product_definition_id"] = pd_id

    filings: List[Dict[str, Any]] = []
    for ref in product_definition.get("filing_refs", []) or []:
        if not isinstance(ref, dict):
            continue
        filings.append(
            {
                "filing_id": ref.get("filing_id"),
                "serff_tracking_id": ref.get("serff_tracking_id"),
            }
        )

    if filings:
        record["filings"] = filings


def build_audit_record_from_summary(
    summary: Dict[str, Any],
    projection_object: str,
    audit_object: Optional[str] = None,
    input_snapshot_object: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a canonical-ish AuditRecord from a projection summary.

    This implementation focuses on the subset of fields that are safely
    available today, as described in docs/audit-model.md:

    - audit_version
    - run_id (from RUN_ID env, when set)
    - product_code (from summary inputs)
    - environment (from ILLUSTRATION_ENVIRONMENT/ENVIRONMENT env, optional)
    - engine_version (from ENGINE_VERSION/ILLUSTRATION_ENGINE_VERSION env)
    - runner_image (from RUNNER_IMAGE env, optional)
    - assumption_set_id (from summary inputs)
    - dsl_file (from summary inputs.formula_path)
    - input object keys (PAS, actuarial, rates, CRM, premium table)
    - projection_object, audit_object, input_snapshot_object
    - created_at / generated_at

    It deliberately does **not** embed raw PAS data, projection arrays, or
    any policyholder-level details.
    """

    inputs = summary.get("inputs", {}) or {}

    run_id = os.getenv("RUN_ID") or None
    product_code = inputs.get("product_code") or None
    environment = os.getenv("ILLUSTRATION_ENVIRONMENT") or os.getenv("ENVIRONMENT") or None
    engine_version = get_engine_version()
    runner_image = os.getenv("RUNNER_IMAGE") or None
    assumption_set_id = inputs.get("assumption_set_id") or None
    formula_path = inputs.get("formula_path") or None

    created_at = summary.get("generated_at") or datetime.utcnow().isoformat()

    record: Dict[str, Any] = {
        "audit_version": "1.0",
        "run_id": run_id,
        "product": {
            "product_code": product_code,
            "product_definition_id": None,
        },
        "filings": [],
        "assumptions": [],
        "engine": {
            "engine_version": engine_version,
            "runner_image": runner_image,
        },
        "inputs": {
            "pas_export": inputs.get("pas_object"),
            "actuarial_tables": inputs.get("actuarial_object"),
            "term23_actuarial": inputs.get("term23_actuarial_object"),
            "rate_curves": inputs.get("rate_object"),
            "crm_accounts": inputs.get("crm_object"),
            "premium_table": inputs.get("premium_table_object"),
        },
        "outputs": {
            "projection_object": projection_object,
            "audit_object": audit_object,
            "input_snapshot_object": input_snapshot_object,
        },
        "environment": environment,
        "created_at": created_at,
    }

    if assumption_set_id:
        record["assumptions"].append(
            {
                "assumption_set_id": assumption_set_id,
                "role": None,
                "status": None,
            }
        )

    if formula_path:
        record.setdefault("dsl", {})["file"] = formula_path

    # Best-effort wiring to ProductDefinition + FilingRecord based on the
    # local product registry abstraction.
    try:
        product_definition = get_product_definition(product_code or "")
        enrich_audit_record_with_product_definition(record, product_definition)
    except Exception:
        # Do not let ProductDefinition/FilingRecord wiring break audit
        # record generation; this is a best-effort enrichment.
        pass

    return record


def store_audit_record(record: Dict[str, Any], product_code: str, run_id: str) -> str:
    """Persist an AuditRecord JSON to MinIO under the canonical key.

    The object key is:

        audit/<product_code>/<run_id>/audit_record.json

    Callers are expected to ensure that product_code and run_id are
    meaningful and non-empty when this is invoked.
    """

    object_name = audit_record_object_key(product_code, run_id)
    return store_json_metadata(record, object_name)
