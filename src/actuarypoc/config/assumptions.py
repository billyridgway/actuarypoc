from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from actuarypoc.storage.minio_client import get_bucket_name, get_minio_client


ASSUMPTION_REGISTRY_OBJECT = "config/assumption_sets.json"


@dataclass
class AssumptionSet:
    id: str
    product_code: str
    description: str
    dsl_file: str  # relative to the DSL examples directory
    actuarial_prefix: Optional[str] = None
    status: str = "draft"  # draft | approved | deprecated
    is_current: bool = False
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssumptionSet":
        return cls(
            id=data["id"],
            product_code=data["product_code"],
            description=data.get("description", ""),
            dsl_file=data["dsl_file"],
            actuarial_prefix=data.get("actuarial_prefix"),
            status=data.get("status", "draft"),
            is_current=bool(data.get("is_current", False)),
            created_at=data.get("created_at"),
            created_by=data.get("created_by"),
            approved_at=data.get("approved_at"),
            approved_by=data.get("approved_by"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "product_code": self.product_code,
            "description": self.description,
            "dsl_file": self.dsl_file,
            "actuarial_prefix": self.actuarial_prefix,
            "status": self.status,
            "is_current": self.is_current,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
        }


def _load_registry_raw() -> Dict[str, Any]:
    """Load the raw registry JSON from MinIO, or return an empty structure.

    This is intentionally forgiving: if the object is missing or invalid, we
    fall back to an empty registry so callers can still run projections.
    """

    client = get_minio_client()
    bucket = get_bucket_name()
    try:
        response = client.get_object(bucket, ASSUMPTION_REGISTRY_OBJECT)
    except Exception:
        return {"assumption_sets": []}

    try:
        data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {"assumption_sets": []}
    finally:
        response.close()
        response.release_conn()

    if not isinstance(data, dict):
        return {"assumption_sets": []}
    data.setdefault("assumption_sets", [])
    return data


def _save_registry_raw(registry: Dict[str, Any]) -> None:
    client = get_minio_client()
    bucket = get_bucket_name()
    payload = json.dumps(registry, indent=2).encode("utf-8")
    client.put_object(
        bucket,
        ASSUMPTION_REGISTRY_OBJECT,
        data=io.BytesIO(payload),
        length=len(payload),
        content_type="application/json",
    )


def list_assumption_sets() -> List[AssumptionSet]:
    registry = _load_registry_raw()
    items = registry.get("assumption_sets", [])
    return [AssumptionSet.from_dict(item) for item in items]


def upsert_assumption_set(asn: AssumptionSet) -> AssumptionSet:
    """Insert or update an AssumptionSet in the MinIO-backed registry.

    - If an entry with the same id exists, it is replaced.
    - Otherwise, the set is appended.
    - created_at/created_by are only populated when missing so callers can
      supply their own values if desired.
    """

    registry = _load_registry_raw()
    items = registry.get("assumption_sets", [])

    now = datetime.now(timezone.utc).isoformat()

    # Ensure created_* fields are populated if absent.
    if asn.created_at is None:
        asn.created_at = now
    if asn.created_by is None:
        asn.created_by = "llm-extractor"

    payload = asn.to_dict()

    replaced = False
    for idx, item in enumerate(items):
        if item.get("id") == asn.id:
            items[idx] = payload
            replaced = True
            break

    if not replaced:
        items.append(payload)

    registry["assumption_sets"] = items
    _save_registry_raw(registry)

    return asn


def get_current_assumption_for_product(product_code: str) -> Optional[AssumptionSet]:
    code = product_code.upper()
    candidates = [
        a for a in list_assumption_sets()
        if a.product_code.upper() == code and a.status == "approved" and a.is_current
    ]
    if not candidates:
        return None
    # If multiple, just pick the first; registry should normally keep this unique.
    return candidates[0]


def approve_assumption_set(set_id: str, approved_by: str) -> Optional[AssumptionSet]:
    """Mark an assumption set as approved + current for its product.

    - status → approved
    - is_current → true
    - clears is_current on other sets for same product_code
    """

    registry = _load_registry_raw()
    items = registry.get("assumption_sets", [])
    found: Optional[Dict[str, Any]] = None
    for item in items:
        if item.get("id") == set_id:
            found = item
            break
    if found is None:
        return None

    # Clear current flag on siblings for the same product_code
    product_code = found.get("product_code")
    for item in items:
        if item.get("product_code") == product_code and item.get("id") != set_id:
            item["is_current"] = False

    now = datetime.now(timezone.utc).isoformat()
    found["status"] = "approved"
    found["is_current"] = True
    found["approved_at"] = now
    found["approved_by"] = approved_by

    registry["assumption_sets"] = items
    _save_registry_raw(registry)

    return AssumptionSet.from_dict(found)
