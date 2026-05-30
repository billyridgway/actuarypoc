from __future__ import annotations

from actuarypoc.projection.object_keys import (
    projection_object_key,
    audit_object_key,
    input_snapshot_object_key,
    audit_record_object_key,
)


def test_projection_object_key_uses_lower_product_and_run_id() -> None:
    key = projection_object_key("P12TRF", "run-123")
    assert key == "projections/p12trf/run-123/projection.json"


def test_audit_and_snapshot_keys_use_lower_product_and_run_id() -> None:
    audit_key = audit_object_key("P12TRF", "run-123")
    snapshot_key = input_snapshot_object_key("P12TRF", "run-123")

    assert audit_key == "audit/p12trf/run-123/audit.json"
    assert snapshot_key == "audit/p12trf/run-123/inputs.json"


def test_audit_record_object_key_preserves_product_code_case() -> None:
    key_upper = audit_record_object_key("P12TRF", "run-123")
    key_lower = audit_record_object_key("p12trf", "run-123")

    assert key_upper == "audit/P12TRF/run-123/audit_record.json"
    # When lower-case is supplied, we currently preserve it as-is.
    assert key_lower == "audit/p12trf/run-123/audit_record.json"

