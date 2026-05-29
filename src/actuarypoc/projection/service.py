from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.projection.engine import ProjectionEngine
from actuarypoc.projection.mortality import build_term23_surface
from actuarypoc.projection.premium import PremiumLookupService, build_premium_table, select_face_band
from actuarypoc.config.assumptions import get_current_assumption_for_product
from actuarypoc.storage.minio_client import get_bucket_name, get_minio_client

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
        },
        "metadata": {
            "actuarial_records_count": len(actuarial_records),
            "term23_actuarial_records_count": len(term23_actuarial_records),
            "rate_records_count": len(rate_records),
            "crm_records_count": len(crm_records),
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

    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "inputs": {
            "p12trf_policies_object": policies_obj,
            "term23_actuarial_object": term23_actuarial_obj,
            "policy_number": policy_record.get("policy_number"),
            "product_type": policy_record.get("product_type"),
            "formula_path": str(formula_path),
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
    engine_version = os.getenv("ENGINE_VERSION") or os.getenv("ILLUSTRATION_ENGINE_VERSION")

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
