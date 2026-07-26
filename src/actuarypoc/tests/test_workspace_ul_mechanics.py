from __future__ import annotations

from actuarypoc.extract.workspace_ul_mechanics import extract_ul_mechanics, usable_mechanics
from actuarypoc.ui import server


def test_extracts_validated_csv_mechanics_with_row_provenance() -> None:
    content = b"""mechanic,duration,rate,rate_unit,charge,charge_unit,amount,fee_unit
coi,1,0.20,per_1000_monthly,,,,
surrender,1,,,0.08,percent_face,,
fees,,,,,,60,annual_fixed
"""
    result = extract_ul_mechanics("rates.csv", content)

    assert result["warnings"] == []
    assert result["mechanics"]["coi"][0]["rate"] == 0.20
    assert result["mechanics"]["coi"][0]["provenance"] == {
        "filename": "rates.csv",
        "sheet": "CSV",
        "row": 2,
    }
    assert set(usable_mechanics(result)) == {"coi", "surrender", "fees"}


def test_rejects_ambiguous_units_and_incomplete_duration_schedule() -> None:
    content = b"""mechanic,duration,charge,charge_unit
surrender,1,8,percent
surrender,3,0.05,percent_face
"""
    result = extract_ul_mechanics("rates.csv", content)

    assert len(result["warnings"]) == 1
    assert "unsupported surrender charge_unit" in result["warnings"][0]
    assert "surrender" not in usable_mechanics(result)


def test_projection_executes_rates_surrender_and_fee_schedules() -> None:
    config = server.load_ul_runtime_config("ICC18 P18PR UL")
    config.executable_mechanics = {
        "coi": [
            {
                "duration": 1,
                "attained_age": None,
                "sex": "F",
                "risk_class": "Standard",
                "tobacco_status": "Non-Tobacco",
                "rate": 1.0,
                "rate_unit": "per_1000_annual",
            }
        ],
        "surrender": [
            {
                "duration": 1,
                "issue_age": None,
                "sex": None,
                "charge": 0.05,
                "charge_unit": "percent_face",
            }
        ],
        "fees": [
            {
                "duration": None,
                "premium_mode": None,
                "amount": 120.0,
                "fee_unit": "annual_fixed",
            }
        ],
    }
    projection, _ = server._run_ul_projection(
        request={
            "age": 45,
            "faceAmount": 100_000,
            "modalPremium": 3_000,
            "premiumMode": "ANNUAL",
            "sex": "F",
            "riskClass": "Standard",
            "tobaccoStatus": "Non-Tobacco",
        },
        config=config,
        horizon_years=1,
    )

    row = projection["rows"][0]
    assert row["coiCharge"] == 96.94
    assert row["policyFee"] == 120.0
    assert row["surrenderCharge"] == 5_000.0
    assert projection["mechanicsExecution"]["coi"]["fullyApplied"] is True


def test_projection_retains_placeholder_for_unmatched_coi_selector() -> None:
    config = server.load_ul_runtime_config("ICC18 P18PR UL")
    config.executable_mechanics = {
        "coi": [
            {
                "duration": 1,
                "attained_age": None,
                "sex": "M",
                "risk_class": None,
                "tobacco_status": None,
                "rate": 1.0,
                "rate_unit": "per_1000_annual",
            }
        ]
    }
    projection, _ = server._run_ul_projection(
        request={"age": 45, "faceAmount": 100_000, "sex": "F"},
        config=config,
        horizon_years=1,
    )

    assert projection["rows"][0]["coiCharge"] == 400.0
    assert projection["mechanicsExecution"]["coi"]["fallbackYears"] == [1]


def test_capability_reconciliation_requires_executable_status() -> None:
    snapshot = server.build_product_workspace_snapshot("ICC18 P18PR UL")
    snapshot["executableMechanics"] = {
        "status": {"coi": "partial_fallback", "surrender": "executable", "fees": "executable"}
    }

    result = server._build_capability_assessment(snapshot)
    statuses = {item["capabilityId"]: item["status"] for item in result["items"]}

    assert statuses["UL_CAP_COI_TABLE_AGE_GENDER_CLASS"] != "supported"
    assert statuses["UL_CAP_SURRENDER_FIXED_SCHEDULE"] == "supported"
    assert statuses["UL_CAP_LEVEL_POLICY_FEE"] == "supported"
