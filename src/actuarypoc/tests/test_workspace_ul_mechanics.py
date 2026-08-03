from __future__ import annotations

import pytest

from actuarypoc.extract.workspace_ul_mechanics import _extract_pdf_page, accept_filed_mechanic, extract_ul_mechanics, usable_mechanics
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


def test_extracts_filed_pdf_surrender_candidate_without_auto_accepting_specimen_values() -> None:
    page = """
    POLICY SPECIFICATIONS [SPECIMEN]
    ICC18 S18PRUL Page [3.2]
    Surrender Charge Rates
    Coverage Year  Surrender Charge Rate
    [1 [17.94130
    2 16.99702
    3 16.05274
    4 15.10846
    5 0.00000]
    Surrender Charge Calculation
    The Surrender Charge Rate divided by $1,000 is multiplied by the face reduction.
    """

    mechanics = _extract_pdf_page("ICC18 S18PRUL.pdf", 3, page)

    assert [row["duration"] for row in mechanics["surrender"]] == [1, 2, 3, 4, 5]
    assert mechanics["surrender"][0]["charge"] == 17.94130
    assert mechanics["surrender"][0]["charge_unit"] == "per_1000_face"
    assert mechanics["surrender"][0]["issue_age"] is None
    assert mechanics["surrender"][0]["sex"] is None
    assert mechanics["surrender"][0]["provenance"] == {
        "filename": "ICC18 S18PRUL.pdf",
        "page": 3,
        "tableHeading": "Surrender Charge Rates",
        "sourceType": "filed_pdf",
        "evidenceClass": "specimen_filed_table",
        "valueBasis": "guaranteed_maximum",
        "reviewStatus": "review_required",
    }
    assert "surrender" not in usable_mechanics({"mechanics": mechanics})


def test_extracts_complete_pdf_coi_candidate_and_expands_explicit_terminal_age() -> None:
    rows = "\n".join(f"{duration} {duration / 100:.5f}" for duration in range(1, 87))
    page = f"""
    POLICY SPECIFICATIONS [SPECIMEN]
    ICC18 S18PRUL Page [3.3]
    Table of Cost of Insurance (COI) Rates For Life Coverage
    Maximum Monthly Cost of Insurance Rates Per $1000.00 of Net Amount at Risk Applicable to this Coverage.
    Policy Year COI Rate
    {rows}
    87+ 0.00000
    """

    mechanics = _extract_pdf_page("ICC18 S18PRUL.pdf", 4, page)
    coi = mechanics["coi"]

    assert len(coi) == 121
    assert coi[0]["duration"] == 1
    assert coi[0]["rate"] == 0.01
    assert coi[86]["duration"] == 87
    assert coi[-1]["duration"] == 121
    assert coi[-1]["rate"] == 0.0
    assert coi[-1]["provenance"]["expandedFrom"] == "87+"
    assert coi[0]["rate_unit"] == "per_1000_monthly"
    assert "coi" not in usable_mechanics({"mechanics": mechanics})


def test_accepts_complete_filed_schedule_and_records_review_provenance() -> None:
    provenance = {
        "filename": "ICC18 S18PRUL.pdf", "page": 3, "sourceType": "filed_pdf",
        "reviewStatus": "review_required", "valueBasis": "guaranteed_maximum",
    }
    mechanics = {"coi": [], "fees": [], "surrender": [
        {"duration": duration, "charge": charge, "charge_unit": "per_1000_face", "provenance": provenance}
        for duration, charge in [(1, 17.94130), (2, 16.99702), (3, 0.0)]
    ]}
    artifact = {"mechanics": mechanics, "status": {"surrender": "filed_evidence_review_required"}}

    accepted = accept_filed_mechanic(artifact, "surrender", reviewed_by="actuary@example.com")

    assert accepted["status"]["surrender"] == "executable"
    assert len(accepted["usable"]["surrender"]) == 3
    assert accepted["reviews"]["surrender"]["reviewedBy"] == "actuary@example.com"
    assert accepted["mechanics"]["surrender"][0]["provenance"]["reviewStatus"] == "accepted"
    assert artifact["mechanics"]["surrender"][0]["provenance"]["reviewStatus"] == "review_required"


def test_rejects_incomplete_or_non_filed_review_candidates() -> None:
    provenance = {"sourceType": "filed_pdf", "reviewStatus": "review_required"}
    incomplete = {"mechanics": {"surrender": [
        {"duration": 1, "charge": 1.0, "charge_unit": "fixed", "provenance": provenance},
        {"duration": 3, "charge": 0.0, "charge_unit": "fixed", "provenance": provenance},
    ]}}
    with pytest.raises(ValueError, match="gaps"):
        accept_filed_mechanic(incomplete, "surrender")

    synthetic = {"mechanics": {"coi": [{
        "duration": 1, "rate": 0.1, "rate_unit": "per_1000_monthly",
        "provenance": {"sourceType": "synthetic", "reviewStatus": "review_required"},
    }]}}
    with pytest.raises(ValueError, match="filed-PDF"):
        accept_filed_mechanic(synthetic, "coi")


def test_filed_mechanic_accept_endpoint_persists_reviewed_artifact(monkeypatch) -> None:
    provenance = {"sourceType": "filed_pdf", "reviewStatus": "review_required"}
    artifact = {"mechanics": {"surrender": [
        {"duration": 1, "charge": 1.0, "charge_unit": "fixed", "provenance": provenance},
        {"duration": 2, "charge": 0.0, "charge_unit": "fixed", "provenance": provenance},
    ]}, "status": {"surrender": "filed_evidence_review_required"}}
    stored = {}
    monkeypatch.setattr(server, "get_workspace", lambda workspace_id: {"id": workspace_id})
    monkeypatch.setattr(server, "load_workspace_executable_mechanics", lambda workspace_id: artifact)
    monkeypatch.setattr(
        server, "store_workspace_executable_mechanics",
        lambda workspace_id, value: stored.update(value) or "workspaces/demo/executable-mechanics.json",
    )

    response = server.api_accept_filed_mechanic(
        "demo", server.FiledMechanicReviewRequest(mechanic="surrender", reviewedBy="reviewer"),
    )

    assert response["accepted"] is True
    assert response["status"] == "executable"
    assert stored["reviews"]["surrender"]["reviewedBy"] == "reviewer"
    assert len(stored["usable"]["surrender"]) == 2


def test_reload_reapplies_accepted_filed_mechanics(monkeypatch) -> None:
    artifact = {
        "usable": {"surrender": [{"duration": 1, "charge": 0.05, "charge_unit": "percent_face"}]},
        "reviews": {"surrender": {"status": "accepted"}},
    }
    monkeypatch.setattr(server, "load_workspace_executable_mechanics", lambda workspace_id: artifact)
    monkeypatch.setattr(server, "_build_ul_projection_view", lambda product_code, request: (
        {"request": request, "rows": []}, {"steps": []}, [], [], [],
    ))
    snapshot = {"product": {"code": "ICC18 P18PR UL"}, "illustration": {"request": {"age": 45}}}

    result = server._apply_active_synthetic_mechanics(snapshot, "demo")

    assert result["illustration"]["request"]["_workspaceExecutableMechanics"] == artifact["usable"]
    assert result["executableMechanics"] == artifact


def test_pdf_extraction_does_not_promote_specimen_policyholder_inputs() -> None:
    page = """
    POLICY SPECIFICATIONS [SPECIMEN]
    ICC18 S18PRUL Page [3]
    Insured: [JOHN DOE]
    Age: [35]
    Sex: [Male]
    Risk Class: [Standard No Nicotine Use]
    Initial Face Amount [$100,000]
    Planned Annual Premium: $758.34
    """

    mechanics = _extract_pdf_page("ICC18 S18PRUL.pdf", 1, page)

    assert mechanics == {"coi": [], "surrender": [], "fees": []}


def test_workspace_analysis_reads_pdf_candidates_and_marks_them_for_review(monkeypatch) -> None:
    class Response:
        def read(self) -> bytes:
            return b"filed PDF bytes"

        def close(self) -> None:
            pass

        def release_conn(self) -> None:
            pass

    class Client:
        def get_object(self, bucket: str, object_path: str) -> Response:
            assert bucket == "workspace-bucket"
            assert object_path == "documents/spec.pdf"
            return Response()

    candidate = {
        "duration": 1,
        "attained_age": None,
        "sex": None,
        "risk_class": None,
        "tobacco_status": None,
        "rate": 0.1142,
        "rate_unit": "per_1000_monthly",
        "provenance": {"reviewStatus": "review_required", "sourceType": "filed_pdf"},
    }
    monkeypatch.setattr(server, "get_minio_client", lambda: Client())
    monkeypatch.setattr(server, "ensure_bucket", lambda client: None)
    monkeypatch.setattr(server, "get_bucket_name", lambda: "workspace-bucket")
    monkeypatch.setattr(
        server,
        "extract_ul_mechanics",
        lambda filename, content: {
            "version": 2,
            "mechanics": {"coi": [candidate], "surrender": [], "fees": []},
            "warnings": [],
        },
    )

    artifact = server._extract_workspace_executable_mechanics([
        {"description": "ICC18 S18PRUL.pdf", "object_path": "documents/spec.pdf"},
    ])

    assert artifact["mechanics"]["coi"] == [candidate]
    assert artifact["usable"] == {}
    assert artifact["status"] == {
        "coi": "filed_evidence_review_required",
        "surrender": "missing_or_incomplete",
        "fees": "missing_or_incomplete",
    }


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


def test_engine_capabilities_do_not_depend_on_workspace_schedule_availability() -> None:
    snapshot = {
        "product": {"code": "ICC18 P18PR UL"},
        "productModel": {
            "type": "ul",
            "universalLife": {
                "product_code": "ICC18 P18PR UL",
                "product_type": "ul",
                "field_evidence": {},
            },
        },
        "complianceMatrix": {"requirements": []},
    }
    snapshot["executableMechanics"] = {
        "status": {"coi": "partial_fallback", "surrender": "executable", "fees": "executable"}
    }

    result = server._build_capability_assessment(snapshot)
    statuses = {item["capabilityId"]: item["status"] for item in result["items"]}

    assert statuses["UL_CAP_COI_TABLE_AGE_GENDER_CLASS"] == "supported"
    assert statuses["UL_CAP_SURRENDER_FIXED_SCHEDULE"] == "supported"
    assert statuses["UL_CAP_LEVEL_POLICY_FEE"] == "supported"


def test_projection_selects_attained_age_sex_and_class_coi_row() -> None:
    config = server.load_ul_runtime_config("ICC18 P18PR UL")
    config.executable_mechanics = {
        "coi": [
            {"duration": None, "attained_age": 45, "sex": "M", "risk_class": "Standard", "tobacco_status": "Non-Tobacco", "rate": 1.0, "rate_unit": "per_1000_annual"},
            {"duration": None, "attained_age": 45, "sex": "F", "risk_class": "Preferred", "tobacco_status": "Non-Tobacco", "rate": 2.0, "rate_unit": "per_1000_annual"},
        ]
    }

    projection, _ = server._run_ul_projection(
        request={"age": 45, "faceAmount": 100_000, "modalPremium": 3_000, "sex": "F", "riskClass": "Preferred", "tobaccoStatus": "Non-Tobacco"},
        config=config,
        horizon_years=1,
    )

    assert projection["rows"][0]["coiCharge"] == 193.88
    assert projection["mechanicsExecution"]["coi"]["fullyApplied"] is True


def test_projection_executes_fixed_surrender_schedule_and_modal_fee() -> None:
    config = server.load_ul_runtime_config("ICC18 P18PR UL")
    config.executable_mechanics = {
        "surrender": [
            {"duration": 1, "issue_age": None, "sex": None, "charge": 750.0, "charge_unit": "fixed"},
        ],
        "fees": [
            {"duration": None, "premium_mode": "MONTHLY", "amount": 10.0, "fee_unit": "modal_fixed"},
        ],
    }

    projection, _ = server._run_ul_projection(
        request={"age": 45, "faceAmount": 100_000, "modalPremium": 250, "premiumMode": "MONTHLY"},
        config=config,
        horizon_years=2,
    )

    assert projection["rows"][0]["surrenderCharge"] == 750.0
    assert projection["rows"][1]["surrenderCharge"] == 0.0
    assert projection["rows"][0]["policyFee"] == 120.0
    assert projection["rows"][1]["policyFee"] == 120.0
    assert projection["mechanicsExecution"]["surrender"]["fullyApplied"] is True
    assert projection["mechanicsExecution"]["fees"]["fullyApplied"] is True
