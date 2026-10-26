"""Phase 1 (show the math) — auditable roll-forward ledger tests.

Eddy's August-7 asks pinned here:
- the projection is a roll-forward ledger whose arithmetic identity holds
  every period;
- COI = table rate x net amount at risk, fluctuating as the account value
  and the table rate move (never a flat amount when a table is in force);
- surrender charge = the schedule's percentage of the ending account
  value — not a flat dollar amount, not a percentage of face — while a
  *filed* schedule keeps the basis it states;
- every component carries a derivation (formula + the values used), and
  placeholders are labelled as placeholders;
- the full rate tables in force travel with the projection.
"""

from __future__ import annotations

import pytest

from actuarypoc.agents.synthetic_coi_ai import build_synthetic_coi_table
from actuarypoc.agents.synthetic_surrender_ai import build_synthetic_surrender_schedule
from actuarypoc.domain.projection_ledger import build_projection_ledger, build_rate_tables_in_force
from actuarypoc.ui import server
from actuarypoc.ui.server import UlRuntimeConfig, _run_ul_projection


def _config(mechanics=None, **overrides) -> UlRuntimeConfig:
    values = {
        "guaranteed_rate": 0.02,
        "coi_rate_flat": 0.004,
        "surrender_period_years": 19,
        "max_surrender_pct": 0.10,
        "policy_fee_annual": 0.0,
        "executable_mechanics": mechanics or {},
    }
    values.update(overrides)
    return UlRuntimeConfig(**values)


def _coi_rows(unit: str = "per_1000_annual"):
    return [
        {
            "duration": year,
            "attained_age": None,
            "sex": None,
            "risk_class": None,
            "tobacco_status": None,
            "rate": 0.30 + 0.05 * year,
            "rate_unit": unit,
            "provenance": {"filename": "coi.csv", "sheet": "COI", "row": year + 1},
        }
        for year in range(1, 31)
    ]


def _fee_rows():
    return [
        {"component": "policy_fee", "duration": None, "premium_mode": None, "amount": 60.0, "fee_unit": "annual_fixed", "provenance": {"filename": "fees.csv"}},
        {"component": "monthly_expense", "duration": None, "premium_mode": None, "amount": 5.0, "fee_unit": "monthly_fixed", "provenance": {"filename": "fees.csv"}},
        {"component": "premium_expense", "duration": None, "premium_mode": None, "amount": 0.02, "fee_unit": "percent_premium", "provenance": {"filename": "fees.csv"}},
    ]


def _surrender_rows(unit: str = "percent_account_value"):
    return [
        {
            "duration": year,
            "issue_age": None,
            "sex": None,
            "charge": 0.10 - 0.01 * (year - 1),
            "charge_unit": unit,
            "provenance": {"filename": "surrender.csv"},
        }
        for year in range(1, 11)
    ]


REQUEST = {"age": 40, "faceAmount": 200_000, "premiumMode": "ANNUAL", "modalPremium": 6_000}


def _rich_projection():
    mechanics = {"coi": _coi_rows(), "fees": _fee_rows(), "surrender": _surrender_rows()}
    projection, _ = _run_ul_projection(request=dict(REQUEST), config=_config(mechanics), horizon_years=30)
    return projection


def _component(row, component_id):
    return next(item for item in row["components"] if item["id"] == component_id)


# ---------------------------------------------------------------------------
# Ledger identity and shape
# ---------------------------------------------------------------------------


def test_ledger_roll_forward_identity_holds_every_period() -> None:
    ledger = build_projection_ledger(_rich_projection())

    assert len(ledger["rows"]) == 30
    for row in ledger["rows"]:
        rolled = (
            row["beginningValue"] + row["premium"] - row["premiumLoad"]
            - row["policyFee"] - row["coiCharge"] + row["interestCredited"]
        )
        assert rolled == pytest.approx(row["endingValue"], abs=0.01), f"year {row['year']}"
        assert row["surrenderValue"] == pytest.approx(
            max(row["endingValue"] - row["surrenderCharge"], 0.0), abs=0.01
        ), f"year {row['year']}"
        if row["year"] > 1:
            previous = ledger["rows"][row["year"] - 2]
            assert row["beginningValue"] == pytest.approx(previous["endingValue"], abs=0.01)


def test_every_component_carries_a_derivation() -> None:
    ledger = build_projection_ledger(_rich_projection())
    expected_ids = {
        "opening_value", "premium", "premium_load", "policy_fee", "coi",
        "interest", "ending_value", "surrender_charge", "surrender_value",
        "death_benefit", "net_amount_at_risk",
    }
    for row in ledger["rows"]:
        components = {item["id"]: item for item in row["components"]}
        assert expected_ids <= set(components), f"year {row['year']}"
        for component in components.values():
            assert component["formula"], f"year {row['year']} {component['id']}"
            assert component["basis"]
        coi = components["coi"]
        rate_inputs = [item for item in coi["inputs"] if item["label"] == "COI rate applied"]
        assert rate_inputs and rate_inputs[0]["value"] == pytest.approx(0.30 + 0.05 * row["year"])


# ---------------------------------------------------------------------------
# COI = rate x net amount at risk (Eddy defect 1: flat COI)
# ---------------------------------------------------------------------------


def _expected_coi(face: float, premium: float, rate: float, unit: str, years: int):
    """Independent recursion of the documented monthly COI formula."""
    account_value = 0.0
    annual_charges = []
    for _year in range(years):
        account_value += premium
        yearly = 0.0
        for _month in range(12):
            nar = max(face - account_value, 0.0)
            if unit == "percent_nar_annual":
                monthly = nar * rate / 12.0
            else:  # per_1000_annual
                monthly = nar / 1000.0 * rate / 12.0
            yearly += monthly
            account_value -= monthly
        annual_charges.append(yearly)
    return annual_charges


@pytest.mark.parametrize("unit,rate", [("percent_nar_annual", 0.006), ("per_1000_annual", 1.2)])
def test_coi_matches_rate_times_net_amount_at_risk(unit: str, rate: float) -> None:
    mechanics = {
        "coi": [{
            "duration": None, "attained_age": None, "sex": None, "risk_class": None,
            "tobacco_status": None, "rate": rate, "rate_unit": unit,
            "provenance": {"filename": "coi.csv"},
        }],
    }
    config = _config(mechanics, guaranteed_rate=0.0)
    projection, _ = _run_ul_projection(
        request={"age": 45, "faceAmount": 100_000, "premiumMode": "ANNUAL", "modalPremium": 3_000},
        config=config,
        horizon_years=3,
    )
    expected = _expected_coi(100_000, 3_000, rate, unit, 3)
    actual = [row["coiCharge"] for row in projection["rows"]]
    for actual_charge, expected_charge in zip(actual, expected):
        assert actual_charge == pytest.approx(expected_charge, abs=1e-4)
    # The charge moves as the net amount at risk moves: never flat.
    assert len({round(charge, 2) for charge in actual}) == 3


def test_missing_coi_equation_is_stated_in_the_ledger() -> None:
    # Phase 7 (equation doctrine): with no approved COI equation the
    # mechanic does not calculate at all — the old flat fraction of face
    # is unreachable, and the ledger states the absence plainly.
    projection, _ = _run_ul_projection(request=dict(REQUEST), config=_config({}), horizon_years=5)
    ledger = build_projection_ledger(projection)
    coi = _component(ledger["rows"][0], "coi")
    assert coi["basis"] == "missing"
    assert "Not calculated" in coi["formula"]
    assert "no approved COI charge equation" in coi["formula"]
    charges = {round(row["coiCharge"], 2) for row in ledger["rows"]}
    assert charges == {0.0}
    assert projection["incomplete"] is True


# ---------------------------------------------------------------------------
# Surrender charge basis (Eddy defect 2: flat / face-based surrender)
# ---------------------------------------------------------------------------


def test_surrender_charge_is_schedule_percentage_of_account_value() -> None:
    ledger = build_projection_ledger(_rich_projection())
    for row in ledger["rows"][:10]:
        schedule_pct = 0.10 - 0.01 * (row["year"] - 1)
        assert row["surrenderCharge"] == pytest.approx(schedule_pct * row["endingValue"], rel=1e-9)
        component = _component(row, "surrender_charge")
        assert "ending account value" in component["formula"]
    # After the 10-year schedule the charge expires.
    assert ledger["rows"][10]["surrenderCharge"] == 0.0
    assert _component(ledger["rows"][10], "surrender_charge")["formula"].startswith("No surrender charge")


def test_missing_surrender_equation_charges_nothing() -> None:
    # Phase 7: the old simplified surrender pattern (a percentage of the
    # account value declining over 19 years) is deleted, not relabelled.
    # With no approved surrender equation there is no charge at all.
    projection, _ = _run_ul_projection(request=dict(REQUEST), config=_config({}), horizon_years=30)
    ledger = build_projection_ledger(projection)
    for row in ledger["rows"]:
        assert row["surrenderCharge"] == 0.0
        assert _component(row, "surrender_charge")["basis"] == "missing"


def test_filed_schedule_keeps_the_basis_it_states() -> None:
    # A filed schedule expressed per $1,000 of face is evidence: it is
    # applied exactly as filed, and the derivation says so.
    mechanics = {"surrender": _surrender_rows(unit="per_1000_face")}
    for row in mechanics["surrender"]:
        row["charge"] = 8.0
    projection, _ = _run_ul_projection(request=dict(REQUEST), config=_config(mechanics), horizon_years=3)
    ledger = build_projection_ledger(projection)
    first = ledger["rows"][0]
    assert first["surrenderCharge"] == pytest.approx(200_000 / 1000.0 * 8.0)
    component = _component(first, "surrender_charge")
    # The derivation printed is the approved equation that ran, cited.
    assert "surrender schedule charge" in component["formula"]
    assert component["basis"] == "filed"
    assert component["equation"]["mechanic"] == "surrender_charge"


# ---------------------------------------------------------------------------
# Rate tables in force
# ---------------------------------------------------------------------------


def _equations_for(mechanics):
    from actuarypoc.extract.workspace_equations import (
        in_force_map,
        materialize_legacy_equations,
    )

    artifact = {"usable": mechanics}
    artifact = materialize_legacy_equations(artifact, at="2026-01-01T00:00:00Z")["artifact"]
    return in_force_map(artifact)


def test_rate_tables_in_force_carry_the_full_tables() -> None:
    mechanics = {"coi": _coi_rows(), "surrender": _surrender_rows()}
    tables = build_rate_tables_in_force(mechanics, equations=_equations_for(mechanics))
    assert tables["coi"]["rowCount"] == 30
    assert len(tables["coi"]["rows"]) == 30
    assert tables["coi"]["rows"][0]["rate"] == pytest.approx(0.35)
    assert tables["coi"]["status"] == "workspace_table"
    assert tables["coi"]["equation"]["mechanic"] == "coi_charge"
    assert tables["surrender"]["rowCount"] == 10
    assert tables["surrender"]["rows"][0]["charge_unit"] == "percent_account_value"


def test_rate_tables_in_force_state_the_absence_plainly() -> None:
    tables = build_rate_tables_in_force({})
    assert tables["coi"]["status"] == "missing"
    assert "No COI rate table is in force" in tables["coi"]["missingTable"]["description"]
    assert "placeholder" not in tables["coi"]
    assert tables["surrender"]["status"] == "missing"
    assert "No surrender charge schedule is in force" in tables["surrender"]["missingTable"]["description"]


# ---------------------------------------------------------------------------
# Regression: the Promise UL synthetic path Eddy reviewed
# ---------------------------------------------------------------------------


def _synthetic_mechanics():
    coi_rows = build_synthetic_coi_table(
        parameters={
            "base_rate_per_1000_annual": 0.4,
            "reference_age": 40,
            "annual_age_growth": 0.08,
            "male_multiplier": 1.1,
            "tobacco_multiplier": 2.0,
            "risk_class_multipliers": {"Standard": 1.0},
            "minimum_rate": 0.05,
            "maximum_rate": 50.0,
            "rationale": "Regression-test proposal",
        },
        risk_classes=["Standard"],
        minimum_age=40,
        maximum_age=75,
    )
    surrender_rows = build_synthetic_surrender_schedule(parameters={
        "initial_charge_percent_account_value": 0.12,
        "terminal_charge_percent_account_value": 0.0,
        "period_years": 10,
        "curve_shape": "linear",
        "rationale": "Regression-test schedule",
    })
    return {"coi": coi_rows, "surrender": surrender_rows}, surrender_rows


def test_synthetic_path_fixes_the_august_7_defects() -> None:
    mechanics, surrender_rows = _synthetic_mechanics()
    illustration = server.build_promise_ul_illustration("ICC18 P18PR UL", {
        "age": 45,
        "faceAmount": 250_000,
        "premiumMode": "ANNUAL",
        "sex": "M",
        "riskClass": "Standard",
        "tobaccoStatus": "Non-Tobacco",
        # The illustration builder takes the usable mechanics mapping
        # directly (the workspace view unwraps the stored artifact first).
        "_workspaceExecutableMechanics": mechanics,
    })
    projection = illustration["projection"]
    rows = projection["rows"]

    # Defect 1: COI was a flat $400-style amount. With the synthetic table
    # in force it is rate x net amount at risk and fluctuates by year.
    coi_charges = [round(row["coiCharge"], 2) for row in rows[:8]]
    assert len(set(coi_charges)) > 1
    assert all(charge != pytest.approx(250_000 * 0.004) for charge in coi_charges)
    ledger_rows = projection["ledger"]["rows"]
    coi_component = _component(ledger_rows[0], "coi")
    assert coi_component["basis"] == "synthetic"
    assert "placeholder" not in coi_component["formula"].lower()

    # Defect 2: surrender was a flat / face-based amount. It is now the
    # schedule percentage of the ending account value, every year.
    for row, schedule_row in zip(rows[:10], surrender_rows):
        assert row["surrenderCharge"] == pytest.approx(
            schedule_row["charge"] * row["endingPolicyValue"], rel=1e-9,
        )

    # The full synthetic COI table travels with the projection.
    assert projection["rateTables"]["coi"]["status"] == "synthetic"
    assert projection["rateTables"]["coi"]["rowCount"] == len(mechanics["coi"])


def test_workspace_view_carries_ledger_tables_and_reconciliation() -> None:
    mechanics, _ = _synthetic_mechanics()
    view, _mechanics, _warnings, _notes, gaps = server._build_ul_projection_view("ICC18 P18PR UL", {
        "age": 45,
        "faceAmount": 250_000,
        "premiumMode": "ANNUAL",
        "sex": "M",
        "riskClass": "Standard",
        "tobaccoStatus": "Non-Tobacco",
        # Callers pass the usable mechanics mapping (the snapshot builder
        # unwraps the stored artifact before calling the view).
        "_workspaceExecutableMechanics": mechanics,
    })
    assert view is not None
    assert len(view["ledger"]["rows"]) == 30
    assert view["rateTables"]["coi"]["rowCount"] == len(mechanics["coi"])
    assert view["reconciliation"]["passed"] is True
    assert "surrender_schedule_placeholder" not in {item["id"] for item in gaps}


def test_workspace_view_missing_equation_gap_still_detected() -> None:
    view, _mechanics, _warnings, _notes, gaps = server._build_ul_projection_view("ICC18 P18PR UL", {})
    assert view is not None
    gap_ids = {item["id"] for item in gaps}
    assert "missing_coi_equation" in gap_ids
    assert "missing_surrender_equation" in gap_ids
    assert _component(view["ledger"]["rows"][0], "coi")["basis"] == "missing"


# ---------------------------------------------------------------------------
# Mechanics explanation states the basis actually applied
# ---------------------------------------------------------------------------


def test_explanation_formula_text_matches_the_applied_basis() -> None:
    mechanics, _ = _synthetic_mechanics()
    config = server.load_ul_runtime_config("ICC18 P18PR UL")
    config.executable_mechanics = mechanics
    request = {
        "age": 45, "faceAmount": 250_000, "premiumMode": "ANNUAL",
        "sex": "M", "riskClass": "Standard", "tobaccoStatus": "Non-Tobacco",
    }
    projection, normalised = server._run_ul_projection(request=request, config=config, horizon_years=30)
    explanation = server.build_ul_projection_explanation(
        product_code="ICC18 P18PR UL",
        request=normalised,
        config=config,
        projection=projection,
        year=1,
    )
    steps = {step["id"]: step for step in explanation["steps"]}
    assert "flat fraction of face" not in steps["coi_charge_deducted"]["formulaText"]
    assert "net amount at risk" in steps["coi_charge_deducted"]["formulaText"]
    assert "ending account value" in steps["surrender_charge"]["formulaText"]


def test_explanation_states_the_missing_equation() -> None:
    config = server.load_ul_runtime_config("ICC18 P18PR UL")
    projection, normalised = server._run_ul_projection(
        request={"age": 45, "faceAmount": 250_000, "premiumMode": "ANNUAL"},
        config=config,
        horizon_years=30,
    )
    explanation = server.build_ul_projection_explanation(
        product_code="ICC18 P18PR UL",
        request=normalised,
        config=config,
        projection=projection,
        year=1,
    )
    steps = {step["id"]: step for step in explanation["steps"]}
    assert steps["coi_charge_deducted"]["formulaText"].startswith("Not calculated")
    assert "no approved COI charge equation" in steps["coi_charge_deducted"]["formulaText"]
    assert steps["surrender_charge"]["formulaText"].startswith("Not calculated")
    assert "no approved surrender charge equation" in steps["surrender_charge"]["formulaText"]
