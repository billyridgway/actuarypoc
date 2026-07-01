from dataclasses import asdict

from actuarypoc.domain.life_product_models import (
    BaseLifeProductModel,
    EvidenceRef,
    FieldEvidence,
    RateTable,
    TermLifeModel,
    TableWithStatus,
    UniversalLifeModel,
    WholeLifeModel,
)


def test_base_life_product_model_round_trips_to_dict() -> None:
    model = BaseLifeProductModel(
        product_code="TEST-TERM",
        product_name="Test Term Product",
        carrier="Example Life",
        jurisdiction="US",
        product_type="term",
        issue_age_min=18,
        issue_age_max=75,
        risk_classes=["Preferred", "Standard"],
        premium_pattern="level",
        premium_guarantee_description="Level premiums guaranteed for 20 years.",
        riders=["Waiver of Premium"],
        metadata_sources=[EvidenceRef(document="spec.pdf", page="3", snippet="Product overview")],
    )

    data = asdict(model)
    assert data["product_code"] == "TEST-TERM"
    assert data["product_type"] == "term"
    assert "metadata_sources" in data


def test_term_life_model_embeds_rate_tables_and_field_evidence() -> None:
    ev = FieldEvidence(
        id="term_level_prem_20",
        status="extracted",
        value_summary="20-year level premium table",
        sources=[EvidenceRef(document="term-rates.pdf", page="5")],
        impact="high",
    )
    table = RateTable(id="TERM20", description="20-year level term rates", evidence=ev)

    model = TermLifeModel(
        product_code="TERM20",
        product_type="term",
        term_period_years=20,
        renewable=True,
        convertible=True,
        premium_rate_tables=[table],
        field_evidence={ev.id: ev},
    )

    assert model.term_period_years == 20
    assert model.premium_rate_tables[0].evidence is ev
    assert model.field_evidence["term_level_prem_20"].status == "extracted"


def test_universal_life_model_supports_core_ul_fields() -> None:
    coi_ev = FieldEvidence(
        id="ul_coi_table_main",
        status="placeholder",
        value_summary="Flat 40 bps COI placeholder",
        sources=[EvidenceRef(document="ul-memo.pdf", page="2")],
        impact="high",
    )
    surr_ev = FieldEvidence(
        id="ul_surr_sched_main",
        status="placeholder",
        value_summary="Declining surrender charge over 19 years",
        sources=[EvidenceRef(document="ul-memo.pdf", page="4")],
        impact="high",
    )

    model = UniversalLifeModel(
        product_code="UL-TEST",
        product_name="Test UL",
        product_type="ul",
        death_benefit_options=["Option A"],
        guaranteed_rate=0.02,
        current_rate=0.045,
        crediting_rules="Current rate is non-guaranteed and may change.",
        coi_basis="NAR",
        coi_tables=[TableWithStatus(id="COI-MAIN", description="Main COI table", evidence=coi_ev)],
        surrender_schedule=TableWithStatus(id="SURRENDER-MAIN", description="Main surrender schedule", evidence=surr_ev),
        field_evidence={
            coi_ev.id: coi_ev,
            surr_ev.id: surr_ev,
        },
    )

    assert model.product_code == "UL-TEST"
    assert model.product_type == "ul"
    assert model.death_benefit_options == ["Option A"]
    assert model.coi_basis == "NAR"
    assert model.surrender_schedule is not None
    assert "ul_coi_table_main" in model.field_evidence


def test_whole_life_model_captures_guaranteed_values_and_dividends() -> None:
    gv_ev = FieldEvidence(
        id="wl_guaranteed_csv",
        status="extracted",
        value_summary="Guaranteed cash value table",
        sources=[EvidenceRef(document="wl-memo.pdf", page="6")],
        impact="high",
    )
    model = WholeLifeModel(
        product_code="WL-TEST",
        product_name="Test Whole Life",
        product_type="whole",
        participating=True,
        guarantee_basis="Net level reserve",
        guaranteed_cash_value_table=TableWithStatus(id="GV", description="Guaranteed values", evidence=gv_ev),
        dividend_rules="Dividends are declared annually at the Board's discretion.",
        field_evidence={gv_ev.id: gv_ev},
    )

    assert model.participating is True
    assert model.guaranteed_cash_value_table is not None
    assert model.field_evidence["wl_guaranteed_csv"].impact == "high"
