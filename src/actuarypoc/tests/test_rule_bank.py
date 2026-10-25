"""Phase 4 (the rule bank) — banked switch tests.

Every banked implementation is checked against hand-computed values;
the registry is checked for completeness against the vocabularies the
rest of the system can produce (ingestion's unit sets, Phase 3's
correction variants); and the projection engine is checked for purity:
it executes banked switches only, and anything without a switch behind
it is a labeled placeholder naming its placeholder switch.
"""

from __future__ import annotations

import pytest

from actuarypoc.domain import rule_bank
from actuarypoc.domain.projection_ledger import build_projection_ledger
from actuarypoc.extract import workspace_mechanics_corrections as corrections
from actuarypoc.extract.workspace_ul_mechanics import COI_UNITS, FEE_UNITS, SURRENDER_UNITS
from actuarypoc.ui.server import UlRuntimeConfig, _run_ul_projection


# ---------------------------------------------------------------------------
# Hand-computed implementations
# ---------------------------------------------------------------------------


def test_coi_rate_units_hand_computed():
    # per_1000_monthly: NAR / 1000 × rate
    assert rule_bank.coi_charge_for_unit("per_1000_monthly", 0.5, 200_000) == pytest.approx(100.0)
    # per_1000_annual: NAR / 1000 × rate / 12
    assert rule_bank.coi_charge_for_unit("per_1000_annual", 1.2, 120_000) == pytest.approx(12.0)
    # percent_nar_annual: NAR × rate / 12
    assert rule_bank.coi_charge_for_unit("percent_nar_annual", 0.012, 100_000) == pytest.approx(100.0)


def test_nar_definitions_hand_computed():
    # factor_adjusted: max(DB / factor − value, 0)
    assert rule_bank.coi_nar_for_definition(
        "factor_adjusted", 250_000, 5_000, 1.05
    ) == pytest.approx(250_000 / 1.05 - 5_000)
    # unadjusted: max(DB − value, 0), factor ignored
    assert rule_bank.coi_nar_for_definition("unadjusted", 250_000, 5_000, 1.05) == pytest.approx(245_000)
    # floored at zero
    assert rule_bank.coi_nar_for_definition("factor_adjusted", 1_000, 5_000, 1.0) == 0.0


def _tracer_nar_log():
    return []


def _flat_coi(value):
    """A tracer COI: 0.1% of the measured value, NAR = the value."""

    return value * 0.001, value


def test_coi_timing_steps_hand_computed():
    # beginning: COI on 10,000 = 10; value 10,000 − 10 − 20 = 9,970;
    # interest 1% = 99.70; ending 10,069.70.
    value, interest, coi = rule_bank.coi_step_for_timing(
        "beginning", 10_000.0, 20.0, 0.01, _flat_coi, lambda nar: None
    )
    assert coi == pytest.approx(10.0)
    assert interest == pytest.approx(99.70)
    assert value == pytest.approx(10_069.70)

    # end: fees first (9,980), interest 99.80 → 10,079.80; COI measured
    # there = 10.0798; ending 10,069.7202.
    value, interest, coi = rule_bank.coi_step_for_timing(
        "end", 10_000.0, 20.0, 0.01, _flat_coi, lambda nar: None
    )
    assert coi == pytest.approx(10.0798)
    assert interest == pytest.approx(99.80)
    assert value == pytest.approx(10_069.7202)

    # middle: half of COI-at-10,000 (5) + fees → 9,975; interest 99.75
    # → 10,074.75; half of COI there (5.037375); ending 10,069.712625.
    value, interest, coi = rule_bank.coi_step_for_timing(
        "middle", 10_000.0, 20.0, 0.01, _flat_coi, lambda nar: None
    )
    assert coi == pytest.approx(10.037375)
    assert interest == pytest.approx(99.75)
    assert value == pytest.approx(10_069.712625)


def test_surrender_bases_hand_computed():
    assert rule_bank.surrender_charge_for_unit(
        "percent_account_value", 0.08, 6_639.20, 250_000
    ) == pytest.approx(531.136)
    assert rule_bank.surrender_charge_for_unit(
        "percent_face", 0.02, 6_639.20, 250_000
    ) == pytest.approx(5_000.0)
    assert rule_bank.surrender_charge_for_unit(
        "per_1000_face", 12.0, 6_639.20, 250_000
    ) == pytest.approx(3_000.0)
    assert rule_bank.surrender_charge_for_unit(
        "fixed", 400.0, 6_639.20, 250_000
    ) == pytest.approx(400.0)


def test_fee_units_hand_computed():
    assert rule_bank.monthly_fee_for_unit("monthly_fixed", 15.0, face_amount=100_000, payment_due=False) == 15.0
    assert rule_bank.monthly_fee_for_unit("modal_fixed", 50.0, face_amount=100_000, payment_due=True) == 50.0
    assert rule_bank.monthly_fee_for_unit("modal_fixed", 50.0, face_amount=100_000, payment_due=False) == 0.0
    assert rule_bank.monthly_fee_for_unit("per_1000_face_annual", 6.0, face_amount=250_000, payment_due=False) == pytest.approx(125.0)
    assert rule_bank.monthly_fee_for_unit("annual_fixed", 240.0, face_amount=100_000, payment_due=False) == pytest.approx(20.0)
    # percent_premium is a premium load, never a monthly policy fee
    assert rule_bank.monthly_fee_for_unit("percent_premium", 0.02, face_amount=100_000, payment_due=True) == 0.0
    assert rule_bank.premium_load_for_row(0.02, 5_000.0) == pytest.approx(100.0)
    assert rule_bank.fee_fallback_monthly(120.0) == pytest.approx(10.0)


def test_crediting_and_placeholders_hand_computed():
    assert rule_bank.monthly_crediting_rate(0.03) == pytest.approx(1.03 ** (1 / 12) - 1)
    assert rule_bank.coi_placeholder_monthly_charge(250_000, 0.002) == pytest.approx(250_000 * 0.002 / 12)
    charge, pct = rule_bank.surrender_placeholder_charge(3, 10_000.0, period_years=10, max_pct=0.10)
    assert pct == pytest.approx(0.08)  # 0.10 × (10 − 3 + 1) / 10
    assert charge == pytest.approx(800.0)
    charge, pct = rule_bank.surrender_placeholder_charge(11, 10_000.0, period_years=10, max_pct=0.10)
    assert charge == 0.0 and pct is None


def test_unbanked_values_raise_instead_of_improvising():
    with pytest.raises(ValueError):
        rule_bank.coi_charge_for_unit("per_1000_weekly", 0.5, 100_000)
    with pytest.raises(ValueError):
        rule_bank.surrender_charge_for_unit("percent_of_something", 0.1, 1_000, 1_000)
    with pytest.raises(ValueError):
        rule_bank.monthly_fee_for_unit("per_smile", 1.0, face_amount=1_000, payment_due=True)
    with pytest.raises(ValueError):
        rule_bank.coi_step_for_timing("quarterly", 1_000.0, 0.0, 0.0, _flat_coi, lambda nar: None)
    with pytest.raises(ValueError):
        rule_bank.coi_nar_for_definition("corridor_adjusted", 1_000, 0, 1.0)
    with pytest.raises(ValueError):
        rule_bank.get_switch("coi.rate.per_1000_weekly")


# ---------------------------------------------------------------------------
# Schedule materializers
# ---------------------------------------------------------------------------


def test_graded_materializer_matches_the_phase3_shape():
    rows = rule_bank.materialize_graded_surrender(
        {"basis": "percent_account_value", "percent": 0.08, "gradingYears": 10}
    )
    assert len(rows) == 10
    assert rows[0]["charge"] == pytest.approx(0.08)            # (10 − 1 + 1) / 10
    assert rows[9]["charge"] == pytest.approx(0.008)           # (10 − 10 + 1) / 10
    assert rows[0]["charge_unit"] == "percent_account_value"
    flat = rule_bank.materialize_graded_surrender(
        {"basis": "flat_amount", "amount": 500.0, "gradingYears": 5}
    )
    assert flat[0]["charge_unit"] == "fixed"
    assert flat[0]["charge"] == pytest.approx(500.0)
    assert flat[4]["charge"] == pytest.approx(100.0)


def test_banded_materializer_surrender_with_grading_and_open_end():
    bands = rule_bank.validate_bands("surrender", [
        {"fromYear": 1, "toYear": 10, "unit": "percent_account_value", "value": 0.08, "gradeTo": 0.04},
        {"fromYear": 11, "toYear": None, "unit": "percent_account_value", "value": 0.0},
    ])
    rows = rule_bank.materialize_banded_rows("surrender", bands)
    assert len(rows) == 121  # open-ended band runs to the max duration
    assert rows[0]["charge"] == pytest.approx(0.08)
    assert rows[9]["charge"] == pytest.approx(0.04)            # graded to the band's end value
    assert rows[4]["charge"] == pytest.approx(0.08 + (0.04 - 0.08) * (4 / 9))
    assert rows[10]["charge"] == 0.0
    assert rows[0]["_band"]["label"] == "years 1–10"
    assert rows[10]["_band"]["label"] == "years 11+"
    assert rows[10]["_band"]["index"] == 2


def test_banded_materializer_coi_rows():
    bands = rule_bank.validate_bands("coi", [
        {"fromYear": 1, "toYear": 20, "unit": "per_1000_monthly", "value": 0.42},
        {"fromYear": 21, "toYear": 30, "unit": "per_1000_monthly", "value": 0.85},
    ])
    rows = rule_bank.materialize_banded_rows("coi", bands)
    assert len(rows) == 30
    assert rows[0]["rate"] == pytest.approx(0.42)
    assert rows[20]["rate"] == pytest.approx(0.85)
    assert rows[0]["rate_unit"] == "per_1000_monthly"


def test_banded_validation_rejects_bad_shapes():
    with pytest.raises(ValueError, match="start at year 1"):
        rule_bank.validate_bands("surrender", [
            {"fromYear": 2, "toYear": 5, "unit": "fixed", "value": 100.0},
        ])
    with pytest.raises(ValueError, match="gap"):
        rule_bank.validate_bands("surrender", [
            {"fromYear": 1, "toYear": 5, "unit": "fixed", "value": 100.0},
            {"fromYear": 7, "toYear": 9, "unit": "fixed", "value": 50.0},
        ])
    with pytest.raises(ValueError, match="overlap"):
        rule_bank.validate_bands("surrender", [
            {"fromYear": 1, "toYear": 5, "unit": "fixed", "value": 100.0},
            {"fromYear": 5, "toYear": 9, "unit": "fixed", "value": 50.0},
        ])
    with pytest.raises(ValueError, match="open-ended"):
        rule_bank.validate_bands("surrender", [
            {"fromYear": 1, "toYear": None, "unit": "fixed", "value": 100.0},
            {"fromYear": 2, "toYear": 9, "unit": "fixed", "value": 50.0},
        ])
    with pytest.raises(ValueError, match="unit must be one of"):
        rule_bank.validate_bands("surrender", [
            {"fromYear": 1, "toYear": 5, "unit": "percent_smiles", "value": 0.1},
        ])
    with pytest.raises(ValueError, match="at most 100%"):
        rule_bank.validate_bands("surrender", [
            {"fromYear": 1, "toYear": 5, "unit": "percent_account_value", "value": 1.5},
        ])
    with pytest.raises(ValueError, match="zero or greater"):
        rule_bank.validate_bands("coi", [
            {"fromYear": 1, "toYear": 5, "unit": "per_1000_monthly", "value": -0.1},
        ])


def test_param_validation():
    switch = rule_bank.get_switch("surrender.schedule.graded")
    params = rule_bank.validate_params(switch, {
        "basis": "percent_face", "percent": 0.05, "gradingYears": 8,
    })
    assert params["gradingYears"] == 8
    with pytest.raises(ValueError):
        rule_bank.validate_params(switch, {"basis": "percent_face", "gradingYears": 8})
    with pytest.raises(ValueError):
        rule_bank.validate_params(switch, {
            "basis": "sideways", "percent": 0.05, "gradingYears": 8,
        })
    with pytest.raises(ValueError):
        rule_bank.validate_params(switch, {
            "basis": "percent_face", "percent": 0.05, "gradingYears": 400,
        })


# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------


def test_every_ingestion_unit_maps_to_a_banked_switch():
    for unit in COI_UNITS:
        assert rule_bank.coi_rate_switch_id(unit) in rule_bank.SWITCHES
    for unit in SURRENDER_UNITS:
        assert rule_bank.surrender_switch_id(unit) in rule_bank.SWITCHES
    for unit in FEE_UNITS:
        assert rule_bank.fee_switch_id(unit) in rule_bank.SWITCHES
    for timing in corrections.COI_TIMINGS:
        assert rule_bank.coi_timing_switch_id(timing) in rule_bank.SWITCHES
    for definition in corrections.NAR_DEFINITIONS:
        assert rule_bank.nar_switch_id(definition) in rule_bank.SWITCHES


def test_every_correction_variant_names_banked_switches():
    for variants in corrections.VARIANTS_BY_SLOT.values():
        for variant in variants:
            assert variant.get("bankSwitches"), variant["id"]
            for switch_id in variant["bankSwitches"]:
                assert switch_id in rule_bank.SWITCHES, (variant["id"], switch_id)


def test_bank_catalog_is_presentable():
    import json

    catalog = rule_bank.bank_catalog()
    json.dumps(catalog)  # must be JSON-serializable for the panel payload
    assert len(catalog) == len(rule_bank.SWITCHES)
    for entry in catalog:
        assert entry["description"]
        assert entry["mechanic"]
        assert isinstance(entry["params"], list)


# ---------------------------------------------------------------------------
# Engine purity
# ---------------------------------------------------------------------------


def _config(mechanics=None, **overrides) -> UlRuntimeConfig:
    values = {
        "guaranteed_rate": 0.02,
        "coi_rate_flat": 0.004,
        "surrender_period_years": 19,
        "max_surrender_pct": 0.10,
        "policy_fee_annual": 120.0,
        "executable_mechanics": mechanics or {},
    }
    values.update(overrides)
    return UlRuntimeConfig(**values)


_REQUEST = {"age": 45, "faceAmount": 250_000, "premiumMode": "ANNUAL", "modalPremium": 5_000}


def test_engine_purity_no_tables_means_labeled_placeholders():
    """With nothing in force, every covered mechanic runs a banked
    PLACEHOLDER switch — named in the applied mechanics — and the
    ledger labels the lines placeholder."""

    projection, _ = _run_ul_projection(request=dict(_REQUEST), config=_config({}), horizon_years=30)
    first = projection["rows"][0]["appliedMechanics"]
    assert first["coi"]["rateSwitch"] == "coi.placeholder.flat_face"
    assert first["coi"]["timingSwitch"] == "coi.timing.beginning"
    assert first["coi"]["narSwitch"] == "nar.definition.factor_adjusted"
    assert first["surrender"]["basisSwitch"] == "surrender.placeholder.linear_account_value"
    assert first["fees"][0]["unitSwitch"] == "fees.fallback.configured_annual"
    assert first["crediting"]["switch"] == "crediting.guaranteed_annual"

    ledger = build_projection_ledger(projection)
    components = {c["id"]: c for c in ledger["rows"][0]["components"]}
    assert components["coi"]["basis"] == "placeholder"
    assert components["surrender_charge"]["basis"] == "placeholder"


def test_engine_annotations_name_the_switches_in_force():
    mechanics = {
        "coi": [
            {
                "duration": year, "attained_age": None, "sex": None,
                "risk_class": None, "tobacco_status": None,
                "rate": 0.42, "rate_unit": "per_1000_monthly",
                "provenance": {"filename": "coi.csv"},
            }
            for year in range(1, 31)
        ],
        "surrender": [
            {
                "duration": year, "issue_age": None, "sex": None,
                "charge": 0.05, "charge_unit": "percent_face",
                "provenance": {"filename": "surrender.csv"},
            }
            for year in range(1, 11)
        ],
        "fees": [
            {
                "component": "policy_fee", "duration": None, "premium_mode": None,
                "amount": 240.0, "fee_unit": "annual_fixed",
                "provenance": {"filename": "fees.csv"},
            }
        ],
        "_settings": {"coiTiming": "end", "narDefinition": "unadjusted"},
    }
    projection, _ = _run_ul_projection(request=dict(_REQUEST), config=_config(mechanics), horizon_years=30)
    first = projection["rows"][0]["appliedMechanics"]
    assert first["coi"]["rateSwitch"] == "coi.rate.per_1000_monthly"
    assert first["coi"]["timingSwitch"] == "coi.timing.end"
    assert first["coi"]["narSwitch"] == "nar.definition.unadjusted"
    assert first["surrender"]["basisSwitch"] == "surrender.basis.percent_face"
    assert first["fees"][0]["unitSwitch"] == "fees.unit.annual_fixed"


def test_banded_correction_names_its_band_in_the_ledger():
    """Eddy's hard case end-to-end: a banded surrender correction runs
    through the loop, and the year's derivation names the band."""

    from actuarypoc.extract.workspace_mechanics_panel import SLOT_BY_ID

    artifact = {"usable": {}, "candidates": {}, "status": {}, "mechanics": {}, "reviews": {}}
    slot = SLOT_BY_ID["surrender"]
    outcome = corrections.apply_correction(
        artifact,
        slot,
        {
            "variant": "surrender_banded",
            "params": {"bands": [
                {"fromYear": 1, "toYear": 10, "unit": "percent_account_value", "value": 0.08},
                {"fromYear": 11, "toYear": None, "unit": "percent_account_value", "value": 0.0},
            ]},
            "text": "surrender is 8% of account value for ten years, then nothing",
        },
        workspace_id="ws-test",
        who="eddy",
        at="2026-10-25T00:00:00Z",
    )
    mechanics = corrections.executable_mechanics_view(outcome["artifact"])
    projection, _ = _run_ul_projection(request=dict(_REQUEST), config=_config(mechanics), horizon_years=30)
    year1 = projection["rows"][0]["appliedMechanics"]["surrender"]
    assert year1["band"]["index"] == 1
    assert year1["basisSwitch"] == "surrender.basis.percent_account_value"
    ledger = build_projection_ledger(projection)
    surrender = next(
        c for c in ledger["rows"][0]["components"] if c["id"] == "surrender_charge"
    )
    assert "band 1" in surrender["formula"]
    assert any(i["label"] == "Schedule band" for i in surrender["inputs"])
    # Year 12 is in band 2 (no charge).
    assert ledger["rows"][11]["surrenderCharge"] == pytest.approx(0.0)
