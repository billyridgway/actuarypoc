from __future__ import annotations

from datetime import datetime
import types
import sys
from typing import Any, Dict


def _get_projection_service():
    """Import projection.service with a stubbed psycopg dependency.

    This avoids requiring psycopg to be installed just for unit tests that
    exercise pure-Python helpers.
    """

    sys.modules.setdefault("psycopg", types.SimpleNamespace())
    from actuarypoc.projection import service as projection_service  # type: ignore

    return projection_service


def test_build_audit_record_from_summary_minimal_fields() -> None:
    service = _get_projection_service()
    summary = {
      "generated_at": "2026-05-29T12:00:00Z",
      "inputs": {
        "product_code": "P12TRF",
        "pas_object": "pas_export/pas-123.json",
        "actuarial_object": "actuarial_tables/act-123.json",
        "term23_actuarial_object": "actuarial_tables_term23/term23-123.json",
        "rate_object": "rate_curves/rates-123.json",
        "crm_object": "crm_accounts/crm-123.json",
        "premium_table_object": "premium_tables/P12TRF/table-123.csv",
        "assumption_set_id": "term-risk-class-mapping-v1",
        "formula_path": "src/actuarypoc/dsl/examples/p12trf_term.yaml",
      },
    }

    record = service.build_audit_record_from_summary(
        summary,
        projection_object="projections/P12TRF/run-123.json",
        audit_object="audit/P12TRF/run-123/audit.json",
        input_snapshot_object="audit/P12TRF/run-123/inputs.json",
    )

    assert record["audit_version"] == "1.0"
    assert record["product"]["product_code"] == "P12TRF"
    assert record["outputs"]["projection_object"] == "projections/P12TRF/run-123.json"
    assert record["outputs"]["audit_object"] == "audit/P12TRF/run-123/audit.json"
    assert record["outputs"]["input_snapshot_object"] == "audit/P12TRF/run-123/inputs.json"

    # No secrets or raw projection data should appear
    assert "projection" not in record


def test_build_audit_record_assumptions_and_dsl() -> None:
    service = _get_projection_service()
    summary = {
      "generated_at": datetime.utcnow().isoformat(),
      "inputs": {
        "product_code": "P12TRF",
        "assumption_set_id": "term-risk-class-mapping-v1",
        "formula_path": "src/actuarypoc/dsl/examples/p12trf_term.yaml",
      },
    }

    record = service.build_audit_record_from_summary(summary, projection_object="projections/P12TRF/run-abc.json")

    # AssumptionSet should be reflected when present
    assert isinstance(record.get("assumptions"), list)
    assert any(a.get("assumption_set_id") == "term-risk-class-mapping-v1" for a in record["assumptions"])

    # DSL file reference should be preserved
    assert record.get("dsl", {}).get("file") == "src/actuarypoc/dsl/examples/p12trf_term.yaml"


def test_store_audit_record_builds_expected_key(monkeypatch) -> None:
    projection_service = _get_projection_service()
    calls: dict = {}

    def fake_store_json_metadata(payload, object_name):  # type: ignore[override]
        calls["payload"] = payload
        calls["object_name"] = object_name
        return object_name

    monkeypatch.setattr(projection_service, "store_json_metadata", fake_store_json_metadata)

    result = projection_service.store_audit_record({"foo": "bar"}, product_code="P12TRF", run_id="run-xyz")

    expected_key = "audit/P12TRF/run-xyz/audit_record.json"
    assert result == expected_key
    assert calls["object_name"] == expected_key


def test_build_audit_record_adds_product_definition_and_filings() -> None:
    service = _get_projection_service()
    summary = {
      "generated_at": "2026-05-29T12:00:00Z",
      "inputs": {
        "product_code": "P12TRF",
        "assumption_set_id": "term-risk-class-mapping-v1",
        "formula_path": "src/actuarypoc/dsl/examples/p12trf_term.yaml",
      },
    }

    record = service.build_audit_record_from_summary(
        summary,
        projection_object="projections/P12TRF/run-123.json",
    )

    # P12TRF ProductDefinition should be wired into the AuditRecord.
    assert record["product"]["product_definition_id"] == "P12TRF-def-v1-poc"

    # Filing references from the ProductDefinition should appear as
    # metadata-only entries (ids only, no docs).
    filings = record.get("filings")
    assert isinstance(filings, list)
    assert any(
        f.get("filing_id", "").startswith("P12TRF-2020-01") and f.get("serff_tracking_id") == "SERFF-PLACEHOLDER"
        for f in filings or []
    )


def test_build_audit_record_handles_missing_product_definition(monkeypatch) -> None:
    service = _get_projection_service()

    # Force the registry lookup to return None so we exercise the
    # "no ProductDefinition available" path.
    monkeypatch.setattr(service, "get_product_definition", lambda code: None)

    summary = {
      "generated_at": "2026-05-29T12:00:00Z",
      "inputs": {
        "product_code": "UNKNOWN-PRODUCT",
        "assumption_set_id": "asn-x",
        "formula_path": "src/actuarypoc/dsl/examples/unknown.yaml",
      },
    }

    record = service.build_audit_record_from_summary(
        summary,
        projection_object="projections/UNKNOWN/run-123.json",
    )

    # Should not raise; product_definition_id remains None and filings empty.
    assert record["product"].get("product_definition_id") is None
    filings = record.get("filings") or []
    assert isinstance(filings, list)
    assert filings == []


def test_build_audit_record_includes_engine_and_runner(monkeypatch) -> None:
    service = _get_projection_service()

    # Clear any pre-existing version env so we exercise the helper + fallback.
    for name in ("ENGINE_VERSION", "ILLUSTRATION_ENGINE_VERSION"):
        monkeypatch.delenv(name, raising=False)

    summary: Dict[str, Any] = {
        "generated_at": "2026-05-29T12:00:00Z",
        "inputs": {
            "product_code": "P12TRF",
        },
    }

    # Runner image should be taken from RUNNER_IMAGE env.
    monkeypatch.setenv("RUNNER_IMAGE", "ghcr.io/billyridgway/actuarypoc:main")

    record = service.build_audit_record_from_summary(
        summary,
        projection_object="projections/P12TRF/run-123.json",
    )

    engine = record.get("engine") or {}
    assert engine.get("runner_image") == "ghcr.io/billyridgway/actuarypoc:main"

    # Engine version should always be a non-empty string, even when env
    # overrides are not set. The exact value is owned by the version helper.
    engine_version = engine.get("engine_version")
    assert isinstance(engine_version, str)
    assert engine_version != ""
