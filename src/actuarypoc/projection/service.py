from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.projection.engine import ProjectionEngine
from actuarypoc.projection.mortality import build_term23_surface
from actuarypoc.config.assumptions import get_current_assumption_for_product
from actuarypoc.storage.minio_client import get_bucket_name, get_minio_client

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

    # Choose the appropriate DSL based on PAS product_code, preferring an
    # approved/current assumption set when available.
    product_code = policy_record.get("product_code")
    assumption_set = None
    formula_path: Path

    if product_code is not None:
        assumption_set = get_current_assumption_for_product(str(product_code))

    if assumption_set is not None and assumption_set.dsl_file:
        formula_path = _BASE_DSL_DIR / assumption_set.dsl_file
    else:
        formula_path = _resolve_policy_formula_path(str(product_code) if product_code is not None else None)

    formula = load_formula(str(formula_path))

    # Build a Term23 mortality surface when data is available; pass it into the engine
    # so it can surface q_x by duration in the projection output.
    mortality_surface = None
    if product_code is not None:
        code = str(product_code).upper()
        if (code.startswith("TERM23") or code.startswith("TERM-23")) and term23_actuarial_records:
            mortality_surface = build_term23_surface(term23_actuarial_records)

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
            "policy_id": policy_record.get("policy_id"),
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
        "projection": asdict(projection),
    }
    return summary


def store_projection(summary: Dict[str, Any]) -> str:
    import io

    client = get_minio_client()
    bucket = get_bucket_name()
    object_name = f"{PROJECTION_PREFIX}projection-{int(datetime.utcnow().timestamp())}.json"
    encoded = json.dumps(summary, indent=2).encode("utf-8")

    client.put_object(
        bucket,
        object_name,
        data=io.BytesIO(encoded),
        length=len(encoded),
        content_type="application/json",
    )
    return object_name
