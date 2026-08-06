from __future__ import annotations

import pytest

from actuarypoc.agents.synthetic_coi_ai import build_synthetic_coi_table, synthetic_coi_preview
from actuarypoc.ui import server


PARAMETERS = {
    "base_rate_per_1000_annual": 0.4,
    "reference_age": 40,
    "annual_age_growth": 0.08,
    "male_multiplier": 1.1,
    "tobacco_multiplier": 2.0,
    "risk_class_multipliers": {"Preferred": 0.8, "Standard": 1.0},
    "minimum_rate": 0.05,
    "maximum_rate": 50.0,
    "rationale": "Unit-test proposal",
}


def test_deterministic_generator_builds_complete_bounded_selector_grid() -> None:
    rows = build_synthetic_coi_table(
        parameters=PARAMETERS,
        risk_classes=["Preferred", "Standard"],
        minimum_age=40,
        maximum_age=41,
    )

    assert len(rows) == 2 * 2 * 2 * 2
    assert {row["sex"] for row in rows} == {"F", "M"}
    assert {row["tobacco_status"] for row in rows} == {"Non-Tobacco", "Tobacco"}
    assert all(row["rate_unit"] == "per_1000_annual" for row in rows)
    assert all(row["provenance"]["sourceType"] == "ai_synthetic" for row in rows)
    female_standard = [
        row for row in rows
        if row["sex"] == "F" and row["risk_class"] == "Standard" and row["tobacco_status"] == "Non-Tobacco"
    ]
    assert female_standard[1]["rate"] > female_standard[0]["rate"]


def test_generator_rejects_unbounded_agent_parameters() -> None:
    invalid = {**PARAMETERS, "annual_age_growth": 0.9}
    with pytest.raises(ValueError, match="annual_age_growth"):
        build_synthetic_coi_table(parameters=invalid, risk_classes=["Standard"])


def test_preview_contains_reproducible_rows_and_explicit_disclaimer() -> None:
    preview = synthetic_coi_preview(parameters=PARAMETERS, risk_classes=["Preferred", "Standard"])

    assert preview["rowCount"] == 121 * 2 * 2 * 2
    assert len(preview["rows"]) == preview["rowCount"]
    assert len(preview["sampleRows"]) == 3
    assert "Not filed" in preview["disclaimer"]


def test_preview_endpoint_uses_agent_parameters_without_persisting(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_workspace", lambda workspace_id: {"id": workspace_id, "inferred_product_code": "UL-1"})
    monkeypatch.setattr(server, "_workspace_synthetic_coi_context", lambda ws: ("context", ["Preferred", "Standard"]))
    monkeypatch.setattr(server, "propose_synthetic_coi_parameters", lambda **kwargs: {**PARAMETERS, "model": "test-model"})

    response = server.api_preview_synthetic_coi("workspace-1")

    assert response["preview"]["model"] == "test-model"
    assert response["preview"]["rowCount"] == 968


def test_synthetic_context_does_not_treat_nicotine_as_risk_class() -> None:
    ws = {"latest_snapshot_json": {"productUnderstanding": {
        "riskClasses": ["Standard No Nicotine Use", "Standard Nicotine Use", "Nicotine"],
    }}}

    _, risk_classes = server._workspace_synthetic_coi_context(ws)

    assert risk_classes == ["Standard"]


def test_accept_and_remove_persist_synthetic_provenance_only_after_review(monkeypatch) -> None:
    stored = []
    artifact = {"usable": {"fees": [{"amount": 10}]}, "status": {"fees": "executable"}, "warnings": []}
    monkeypatch.setattr(server, "get_workspace", lambda workspace_id: {"id": workspace_id})
    monkeypatch.setattr(server, "_workspace_synthetic_coi_context", lambda ws: ("context", ["Preferred", "Standard"]))
    monkeypatch.setattr(server, "load_workspace_executable_mechanics", lambda workspace_id: artifact)
    monkeypatch.setattr(server, "store_workspace_executable_mechanics", lambda workspace_id, value: stored.append(value) or "object-key")

    response = server.api_accept_synthetic_coi(
        "workspace-1",
        server.SyntheticCoiAcceptRequest(parameters=PARAMETERS, model="test-model", generatedAt="2026-01-01T00:00:00Z"),
    )

    assert response["accepted"] is True
    assert artifact["status"]["coi"] == "synthetic_scenario"
    assert artifact["synthetic"]["coi"]["model"] == "test-model"
    assert len(artifact["usable"]["coi"]) == 968
    assert artifact["usable"]["fees"] == [{"amount": 10}]

    removed = server.api_remove_synthetic_coi("workspace-1")
    assert removed == {"removed": True}
    assert "coi" not in artifact["usable"]
    assert artifact["usable"]["fees"] == [{"amount": 10}]
    assert len(stored) == 2


def test_projection_uses_synthetic_demographic_rows_after_acceptance() -> None:
    rows = build_synthetic_coi_table(
        parameters=PARAMETERS,
        risk_classes=["Preferred", "Standard"],
        minimum_age=40,
        maximum_age=40,
    )
    config = server.load_ul_runtime_config("ICC18 P18PR UL")
    config.executable_mechanics = {"coi": rows}

    preferred, _ = server._run_ul_projection(
        request={
            "age": 40, "faceAmount": 100_000, "modalPremium": 3_000,
            "sex": "F", "riskClass": "Preferred", "tobaccoStatus": "Non-Tobacco",
        },
        config=config,
        horizon_years=1,
    )
    tobacco, _ = server._run_ul_projection(
        request={
            "age": 40, "faceAmount": 100_000, "modalPremium": 3_000,
            "sex": "M", "riskClass": "Standard", "tobaccoStatus": "Tobacco",
        },
        config=config,
        horizon_years=1,
    )

    assert preferred["mechanicsExecution"]["coi"]["fullyApplied"] is True
    assert tobacco["mechanicsExecution"]["coi"]["fullyApplied"] is True
    assert tobacco["rows"][0]["coiCharge"] > preferred["rows"][0]["coiCharge"]


def test_accept_refuses_to_overwrite_an_evidenced_coi_table(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_workspace", lambda workspace_id: {"id": workspace_id})
    monkeypatch.setattr(server, "_workspace_synthetic_coi_context", lambda ws: ("context", ["Standard"]))
    monkeypatch.setattr(
        server,
        "load_workspace_executable_mechanics",
        lambda workspace_id: {"usable": {"coi": [{"rate": 1.0}]}, "status": {"coi": "executable"}},
    )

    with pytest.raises(server.HTTPException) as exc_info:
        server.api_accept_synthetic_coi(
            "workspace-1",
            server.SyntheticCoiAcceptRequest(parameters=PARAMETERS, model="test-model"),
        )
    assert exc_info.value.status_code == 409
