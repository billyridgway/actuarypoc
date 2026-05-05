from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.projection.engine import ProjectionEngine
from actuarypoc.storage.minio_client import get_bucket_name, get_minio_client

PROJECTION_PREFIX = "projections/"
POLICY_FORMULA_PATH = Path(__file__).resolve().parents[1] / "dsl" / "examples" / "whole_life.yaml"


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
                             crm_prefix: str = "crm_accounts/") -> Dict[str, Any]:
    pas_obj, pas_records = _get_records(pas_prefix)
    actuarial_obj, actuarial_records = _get_records(actuarial_prefix)
    rate_obj, rate_records = _get_records(rate_prefix)
    crm_obj, crm_records = _get_records(crm_prefix)

    if not pas_records:
        raise RuntimeError("PAS records empty; cannot run projection")

    policy_record = pas_records[0]
    formula = load_formula(str(POLICY_FORMULA_PATH))
    engine = ProjectionEngine(formula)
    projection = engine.project(policy_record)

    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "inputs": {
            "pas_object": pas_obj,
            "actuarial_object": actuarial_obj,
            "rate_object": rate_obj,
            "crm_object": crm_obj,
            "policy_id": policy_record.get("policy_id"),
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
