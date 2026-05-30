from __future__ import annotations

"""Canonical object key helpers for projections and audit artefacts.

These helpers centralise the naming conventions used across the runner,
operator, and UI so that:

- Jobs and CRD status all refer to the same keys that are actually written
  to MinIO.
- Callers that do not explicitly specify object names (e.g. local CLI
  usage) still get deterministic, predictable keys.

The functions here are intentionally small and string-only so they can be
easily mirrored in other components (e.g. the Go operator) without pulling
in heavy dependencies.
"""

from typing import Final


_DEFAULT_UNKNOWN_PRODUCT: Final[str] = "unknown-product"
_DEFAULT_UNKNOWN_RUN: Final[str] = "unknown-run"


def _normalise_product_id(product_id: str | None) -> str:
    """Return a safe, normalised productId for use in object keys.

    We treat the "product id" used for object prefixes as a lower-case
    identifier (e.g. ``p12trf``) to match existing MinIO layouts.
    """

    pid = (product_id or "").strip()
    return pid.lower() or _DEFAULT_UNKNOWN_PRODUCT


def _normalise_product_code(product_code: str | None) -> str:
    """Return a safe productCode for use in audit record keys.

    Product codes in AuditRecord paths are conventionally upper-case
    (e.g. ``P12TRF``); we preserve the caller's casing when provided and
    fall back to a generic placeholder when empty.
    """

    code = (product_code or "").strip()
    return code or _DEFAULT_UNKNOWN_PRODUCT


def _normalise_run_id(run_id: str | None) -> str:
    rid = (run_id or "").strip()
    return rid or _DEFAULT_UNKNOWN_RUN


def projection_object_key(product_id: str, run_id: str) -> str:
    """Canonical projection object key.

    Layout (for MinIO):

        projections/<productId-lower>/<run_id>/projection.json
    """

    pid = _normalise_product_id(product_id)
    rid = _normalise_run_id(run_id)
    return f"projections/{pid}/{rid}/projection.json"


def audit_object_key(product_id: str, run_id: str) -> str:
    """Canonical legacy audit object key (non-AuditRecord)."""

    pid = _normalise_product_id(product_id)
    rid = _normalise_run_id(run_id)
    return f"audit/{pid}/{rid}/audit.json"


def input_snapshot_object_key(product_id: str, run_id: str) -> str:
    """Canonical input-snapshot object key."""

    pid = _normalise_product_id(product_id)
    rid = _normalise_run_id(run_id)
    return f"audit/{pid}/{rid}/inputs.json"


def audit_record_object_key(product_code: str, run_id: str) -> str:
    """Canonical AuditRecord object key.

    Layout:

        audit/<PRODUCT_CODE>/<run_id>/audit_record.json
    """

    code = _normalise_product_code(product_code)
    rid = _normalise_run_id(run_id)
    return f"audit/{code}/{rid}/audit_record.json"

