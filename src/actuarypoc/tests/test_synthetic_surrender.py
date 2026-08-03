from __future__ import annotations

import pytest

from actuarypoc.agents.synthetic_surrender_ai import (
    build_synthetic_surrender_schedule,
    synthetic_surrender_preview,
)
from actuarypoc.ui import server


PARAMETERS = {
    "initial_charge_percent_face": 0.12,
    "terminal_charge_percent_face": 0.0,
    "period_years": 10,
    "curve_shape": "linear",
    "rationale": "Unit-test schedule",
}


def test_builds_complete_declining_duration_schedule() -> None:
    rows = build_synthetic_surrender_schedule(parameters=PARAMETERS)

    assert len(rows) == 10
    assert [row["duration"] for row in rows] == list(range(1, 11))
    assert rows[0]["charge"] == 0.12
    assert rows[-1]["charge"] == 0.0
    assert all(rows[index]["charge"] >= rows[index + 1]["charge"] for index in range(len(rows) - 1))
    assert all(row["provenance"]["sourceType"] == "ai_synthetic" for row in rows)


def test_rejects_invalid_agent_schedule_parameters() -> None:
    with pytest.raises(ValueError, match="percentages"):
        build_synthetic_surrender_schedule(
            parameters={**PARAMETERS, "terminal_charge_percent_face": 0.2},
        )
    with pytest.raises(ValueError, match="curve_shape"):
        build_synthetic_surrender_schedule(parameters={**PARAMETERS, "curve_shape": "random"})


def test_preview_is_explicitly_synthetic_and_download_ready() -> None:
    preview = synthetic_surrender_preview(parameters=PARAMETERS)

    assert preview["mechanic"] == "surrender"
    assert preview["rowCount"] == 10
    assert preview["rows"][-1]["duration"] == 10
    assert "Not a filed" in preview["disclaimer"]


def test_accept_remove_and_projection_execution(monkeypatch) -> None:
    artifact = {"usable": {"fees": [{"amount": 10}]}, "status": {}, "warnings": []}
    stored = []
    monkeypatch.setattr(server, "get_workspace", lambda workspace_id: {"id": workspace_id})
    monkeypatch.setattr(server, "load_workspace_executable_mechanics", lambda workspace_id: artifact)
    monkeypatch.setattr(server, "store_workspace_executable_mechanics", lambda workspace_id, value: stored.append(value) or "key")

    accepted = server.api_accept_synthetic_surrender(
        "workspace-1",
        server.SyntheticCoiAcceptRequest(parameters=PARAMETERS, model="test-model"),
    )
    assert accepted["accepted"] is True
    assert artifact["status"]["surrender"] == "synthetic_scenario"
    assert len(artifact["usable"]["surrender"]) == 10

    config = server.load_ul_runtime_config("ICC18 P18PR UL")
    config.executable_mechanics = {"surrender": artifact["usable"]["surrender"]}
    projection, _ = server._run_ul_projection(
        request={"age": 45, "faceAmount": 100_000, "modalPremium": 3_000},
        config=config,
        horizon_years=1,
    )
    assert projection["mechanicsExecution"]["surrender"]["fullyApplied"] is True
    assert projection["rows"][0]["surrenderCharge"] == 12_000

    assert server.api_remove_synthetic_surrender("workspace-1") == {"removed": True}
    assert "surrender" not in artifact["usable"]
    assert artifact["usable"]["fees"] == [{"amount": 10}]


def test_accept_refuses_to_replace_evidenced_surrender_schedule(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_workspace", lambda workspace_id: {"id": workspace_id})
    monkeypatch.setattr(
        server,
        "load_workspace_executable_mechanics",
        lambda workspace_id: {"usable": {"surrender": [{"duration": 1, "charge": 0.1}]}, "status": {}},
    )
    with pytest.raises(server.HTTPException) as exc_info:
        server.api_accept_synthetic_surrender(
            "workspace-1",
            server.SyntheticCoiAcceptRequest(parameters=PARAMETERS),
        )
    assert exc_info.value.status_code == 409
