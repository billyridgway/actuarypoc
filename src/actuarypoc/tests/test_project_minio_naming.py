from __future__ import annotations

import os
import types
import sys
from typing import Any, Dict, List


def _get_cli_module():
    """Import cli.main with a stubbed psycopg dependency.

    This mirrors the pattern used in the audit-record tests so we don't
    require a real Postgres driver just to exercise pure-Python helpers.
    """

    sys.modules.setdefault("psycopg", types.SimpleNamespace())
    from actuarypoc.cli import main as cli_main  # type: ignore

    return cli_main


def test_project_minio_uses_canonical_keys_when_names_not_supplied(monkeypatch) -> None:
    cli_main = _get_cli_module()

    calls: Dict[str, List[Any]] = {"projection": [], "audit": [], "snapshot": []}

    def fake_build_projection_summary(*args, **kwargs):  # type: ignore[override]
        """Return a minimal, in-memory projection summary.

        This keeps the test fully self-contained by avoiding any MinIO
        dependency while still exercising the canonical object-key logic
        inside the CLI.
        """

        run_id = os.environ.get("RUN_ID", "test-run")
        product_id = os.environ.get("PRODUCT_ID", "p12trf")

        return {
            "generated_at": "2026-01-01T00:00:00Z",
            "inputs": {
                "run_id": run_id,
                # Upper-case to match production behaviour
                "product_code": product_id.upper(),
            },
            "metadata": {},
            "warnings": [],
        }

    def fake_store_projection(summary, object_name=None):  # type: ignore[override]
        calls["projection"].append(object_name)
        return object_name

    def fake_store_json_metadata(payload, object_name):  # type: ignore[override]
        if object_name.endswith("/audit.json"):
            calls["audit"].append(object_name)
        elif object_name.endswith("/inputs.json"):
            calls["snapshot"].append(object_name)
        return object_name

    def fake_build_audit_record_from_summary(summary, *args, **kwargs):  # type: ignore[override]
        # Minimal placeholder; structure is irrelevant for this naming test.
        return {"run_id": summary.get("inputs", {}).get("run_id"), "outputs": {}}

    # Avoid touching Postgres during the test.
    def fake_record_illustration_run(*args, **kwargs):  # type: ignore[override]
        return None

    def fake_store_audit_record(record, product_code, run_id):  # type: ignore[override]
        # Avoid touching MinIO during the test; return a plausible key.
        return f"audit/{str(product_code)}/{str(run_id)}/audit_record.json"

    monkeypatch.setattr(cli_main, "build_projection_summary", fake_build_projection_summary)
    monkeypatch.setattr(cli_main, "store_projection", fake_store_projection)
    monkeypatch.setattr(cli_main, "store_json_metadata", fake_store_json_metadata)
    monkeypatch.setattr(cli_main, "build_audit_record_from_summary", fake_build_audit_record_from_summary)
    monkeypatch.setattr(cli_main, "store_audit_record", fake_store_audit_record)
    monkeypatch.setattr(cli_main, "record_illustration_run", fake_record_illustration_run)

    # Ensure RUN_ID and PRODUCT_ID are set so the helper can derive keys.
    os.environ["RUN_ID"] = "run-abc"
    os.environ["PRODUCT_ID"] = "p12trf"

    # Call the function directly with empty object-name parameters so it
    # exercises the canonical-key path instead of explicit overrides.
    cli_main.project_minio(
        pas_prefix="pas_export/",
        actuarial_prefix="actuarial_tables/",
        rate_prefix="rate_curves/",
        crm_prefix="crm_accounts/",
        term23_actuarial_prefix="actuarial_tables_term23/",
        object_name="",
        audit_object_name="",
        input_snapshot_object_name="",
    )

    assert calls["projection"] == ["projections/p12trf/run-abc/projection.json"]
    assert calls["audit"] == ["audit/p12trf/run-abc/audit.json"]
    assert calls["snapshot"] == ["audit/p12trf/run-abc/inputs.json"]
