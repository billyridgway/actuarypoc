"""The product structure (Billy, Oct 28, 2026).

Suggestions and equations as a flat feed "feel like a random set of
things that need to be approved."  Approvals are now organized by the
NORMAL STRUCTURE of the product type — the UL anatomy in money-flow
order — with the choices located inside it:

* the declared steps, in declared order, grouping each step's equation
  AND its tables; undealt mechanics land in "Also found", never forced
  into the anatomy;
* a step's state composed once, server-side (settled / choice /
  approval / carried / not-in-documents / stated-not-extracted);
* multiple readings of a mechanic as explicit options with provenance
  classes — above all the ws-f107485a seam: a factor-adjusted NAR
  reading carried over from pre-doctrine state (NO filed statement)
  must never silently occupy the slot while the policy form's own
  definition waits — divergence is a CHOICE, excluded from bulk
  approval with both readings named;
* choosing an option is the approval act, recorded in history, and a
  projection run stamps the chosen option per step.
"""

from __future__ import annotations

from actuarypoc.domain import equations as eq
from actuarypoc.extract import workspace_equations as ws_eq
from actuarypoc.extract import workspace_structure as structure
from actuarypoc.extract.workspace_mechanics_corrections import (
    executable_mechanics_view,
)
from actuarypoc.extract.workspace_mechanics_panel import build_mechanics_panel
from actuarypoc.extract.workspace_mechanics_proposals import (
    apply_proposal,
    bulk_summary,
    generate_proposals,
    plan_bulk_approval,
)
from actuarypoc.ui import server


AT = "2026-10-28T08:30:00Z"
FORM_NAR_STATEMENT = (
    "Net Amount at Risk – is the difference between the Death Benefit "
    "and the Policy Value."
)


def _record(mechanic, body, *, state="pending", source=None, at=AT):
    return ws_eq.new_record(
        mechanic=mechanic,
        body=body,
        state=state,
        source=source or {
            "kind": "document",
            "statement": f"The filing states the {mechanic} calculation.",
            "filename": "filing.pdf",
            "page": 2,
        },
        at=at,
    )


def _carried_nar_record():
    record = ws_eq.new_record(
        mechanic="nar_definition",
        body=eq.nar_body("factor_adjusted"),
        state="approved",
        source={
            "kind": "pre_doctrine_migration",
            "statement": None,
            "note": (
                "Materialized from the pre-doctrine workspace state: the "
                "net amount at risk definition in force (factor_adjusted); "
                "the filed factor applies from the NAR factor table when "
                "one is in force."
            ),
        },
        at=AT,
    )
    record["approval"] = {"by": ws_eq.MIGRATION_APPROVER, "at": AT}
    return record


def _filed_nar_record():
    return _record(
        "nar_definition",
        eq.nar_body("unadjusted"),
        source={
            "kind": "document",
            "statement": FORM_NAR_STATEMENT,
            "filename": "ICC18 P18PRUL.pdf",
            "page": 4,
        },
    )


def _slot(slot_id, status="filed_accepted", pending=0):
    return {
        "id": slot_id, "mechanic": slot_id, "status": status,
        "kind": "table", "pendingCandidateCount": pending,
    }


def _step(view, step_id):
    return next(s for s in view["steps"] if s["id"] == step_id)


# ---------------------------------------------------------------------------
# The declaration: order, grouping, also-found
# ---------------------------------------------------------------------------


def test_structure_steps_follow_the_declared_anatomy() -> None:
    view = structure.build_structure({"equations": [], "candidates": {}, "usable": {}})
    assert [s["id"] for s in view["steps"]] == [
        "premium", "fees", "crediting", "death_benefit", "nar", "coi", "surrender",
    ]
    assert _step(view, "nar")["tableMechanics"] == ["nar_factors"]
    assert _step(view, "coi")["tableMechanics"] == ["coi"]
    assert _step(view, "fees")["equationMechanic"] == "policy_fees"
    assert view["progress"]["total"] == 7
    assert view["progress"]["headerText"].startswith("Product structure: 0 of 7")


def test_undeclared_mechanics_land_in_also_found() -> None:
    artifact = {
        "equations": [_record("rider_waiver", {"const": 0})],
        "candidates": {"mortality": [{"id": "m1", "rows": []}]},
        "usable": {},
    }
    view = structure.build_structure(artifact)
    found = {item["mechanic"]: item["kind"] for item in view["alsoFound"]}
    assert found == {"mortality": "table", "rider_waiver": "equation"}
    assert all(
        step["equationMechanic"] != "rider_waiver" for step in view["steps"]
    )


def test_panel_payload_carries_the_structure() -> None:
    panel = build_mechanics_panel({"equations": [], "candidates": {}, "usable": {}})
    assert [s["id"] for s in panel["structure"]["steps"]] == [
        "premium", "fees", "crediting", "death_benefit", "nar", "coi", "surrender",
    ]


# ---------------------------------------------------------------------------
# Provenance classes
# ---------------------------------------------------------------------------


def test_provenance_classes() -> None:
    assert structure.provenance_class({
        "kind": "document", "statement": FORM_NAR_STATEMENT,
        "filename": "ICC18 P18PRUL.pdf", "page": 4,
    }) == "filed_definition"
    assert structure.provenance_class({
        "kind": "document",
        "statement": "The Premium Expense Charge is currently set at 10%.",
        "filename": "memo.pdf", "page": 2,
    }) == "from_filing"
    assert structure.provenance_class({
        "kind": "document", "statement": None,
        "note": "Materialized from the pre-doctrine workspace state: the COI table in force.",
        "tableSourceType": "filed_pdf",
    }) == "derived"
    assert structure.provenance_class({
        "kind": "pre_doctrine_migration", "statement": None,
        "note": "Materialized from the pre-doctrine workspace state: ...",
    }) == "carried_over"
    assert structure.provenance_class({"kind": "specimen", "statement": None}) == "carried_over"
    assert structure.provenance_class({"kind": "actuary", "statement": "Entered by hand"}) == "workspace"


def test_transcribed_legacy_nar_definition_reads_as_carried_over() -> None:
    """When a table acceptance transcribes the materialized NAR
    definition, its source kind is rewritten to "document" — but the
    definition itself has no filed statement (the form states the
    other one), so the reading is carried over, not derived."""

    record = ws_eq.new_record(
        mechanic="nar_definition",
        body=eq.nar_body("factor_adjusted"),
        state="approved",
        source={
            "kind": "document",
            "statement": None,
            "note": (
                "Materialized from the pre-doctrine workspace state: the "
                "net amount at risk definition in force (factor_adjusted); "
                "the filed factor applies from the NAR factor table when "
                "one is in force."
            ),
            "tableSourceType": "filed_pdf",
        },
        at=AT,
    )
    record["approval"] = {"by": "workspace_user", "at": AT}
    readings = structure.readings_for_mechanic(
        {"equations": [record]}, "nar_definition", []
    )
    assert len(readings) == 1
    assert readings[0]["provenanceClass"] == "carried_over"


# ---------------------------------------------------------------------------
# Step states
# ---------------------------------------------------------------------------


def test_step_settled_when_equation_and_tables_in_effect() -> None:
    artifact = {
        "equations": [_record("coi_charge", eq.coi_body_for_unit("per_1000_monthly"),
                                state="approved")],
        "candidates": {}, "usable": {},
    }
    view = structure.build_structure(artifact, slot_views=[_slot("coi")])
    assert _step(view, "coi")["state"] == "settled"
    assert view["progress"]["settled"] == 1


def test_step_approval_for_a_single_pending_reading() -> None:
    artifact = {
        "equations": [_record("premium_load", eq.premium_load_body())],
        "candidates": {}, "usable": {},
    }
    view = structure.build_structure(artifact)
    assert _step(view, "premium")["state"] == "approval"


def test_step_choice_for_two_pending_readings() -> None:
    artifact = {
        "equations": [
            _record("policy_fees", eq.policy_fees_body()),
            _record("policy_fees", {"rows_sum": {"table": "fees", "expr": {"qty": "row_amount"}}}),
        ],
        "candidates": {}, "usable": {},
    }
    view = structure.build_structure(artifact)
    step = _step(view, "fees")
    assert step["state"] == "choice"
    assert len(step["options"]) == 2
    assert view["progress"]["choicesAwaiting"] == 1
    assert any(d["stepId"] == "fees" and d["kind"] == "choice" for d in view["decisions"])


def test_step_choice_when_a_carried_incumbent_diverges_from_the_form() -> None:
    """The ws-f107485a shape: the factor-adjusted reading is IN EFFECT
    (carried over, no filed statement) and the policy form's own
    definition is pending.  That is a choice — never a settled slot."""

    artifact = {
        "equations": [_carried_nar_record(), _filed_nar_record()],
        "candidates": {}, "usable": {},
    }
    view = structure.build_structure(artifact, slot_views=[_slot("nar")])
    step = _step(view, "nar")
    assert step["state"] == "choice"
    classes = {o["provenanceClass"] for o in step["options"]}
    assert classes == {"carried_over", "filed_definition"}
    assert step["inEffect"]["provenanceClass"] == "carried_over"


def test_step_carried_when_only_a_carried_reading_is_in_effect() -> None:
    artifact = {
        "equations": [
            _record("death_benefit", eq.death_benefit_body(), state="approved",
                    source={"kind": "specimen", "statement": None,
                            "note": "Materialized from the product specimen: the death benefit in force."}),
        ],
        "candidates": {}, "usable": {},
    }
    artifact["equations"][0]["approval"] = {"by": ws_eq.SPECIMEN_APPROVER, "at": AT}
    view = structure.build_structure(artifact, slot_views=[_slot("corridor")])
    assert _step(view, "death_benefit")["state"] == "carried"


def test_step_not_in_documents_and_stated_not_extracted() -> None:
    view = structure.build_structure({"equations": [], "candidates": {}, "usable": {}})
    assert _step(view, "premium")["state"] == "not_in_documents"

    unmapped = _record("surrender_charge", None, state="unmapped")
    view = structure.build_structure(
        {"equations": [unmapped], "candidates": {}, "usable": {}}
    )
    assert _step(view, "surrender")["state"] == "stated_not_extracted"


# ---------------------------------------------------------------------------
# The bulk seam: divergence is contested, both readings named
# ---------------------------------------------------------------------------


def test_bulk_excludes_the_form_definition_against_a_carried_incumbent() -> None:
    artifact = {
        "equations": [_carried_nar_record(), _filed_nar_record()],
        "candidates": {}, "usable": {},
    }
    plan = plan_bulk_approval(artifact, [])
    excluded = [i for i in plan["excluded"] if i.get("mechanic") == "nar_definition"]
    assert len(excluded) == 1
    item = excluded[0]
    assert item["provenanceClass"] == "filed_definition"
    assert item["divergentReading"]["provenanceClass"] == "carried_over"
    # Both readings are named in the reason.
    assert "competing readings" in item["reason"]
    assert "replace" in item["reason"]
    assert "NAR factor table factor" in item["reason"]  # the carried reading
    assert "death benefit − the account value" in item["reason"]  # the form's
    assert not [i for i in plan["eligible"] if i.get("mechanic") == "nar_definition"]
    summary = bulk_summary(plan)
    assert "Net amount at risk definition" in summary["confirmBack"]


def test_bulk_keeps_a_single_clean_reading_eligible_with_its_class() -> None:
    artifact = {
        "equations": [_record("crediting", eq.crediting_body())],
        "candidates": {}, "usable": {},
    }
    plan = plan_bulk_approval(artifact, [])
    eligible = [i for i in plan["eligible"] if i.get("mechanic") == "crediting"]
    assert len(eligible) == 1
    assert eligible[0]["provenanceClass"] == "from_filing"


# ---------------------------------------------------------------------------
# Choosing an option: the approval act, history, and the run stamp
# ---------------------------------------------------------------------------


def test_choosing_the_form_definition_records_history_and_stamps_runs() -> None:
    carried, filed = _carried_nar_record(), _filed_nar_record()
    artifact = {"equations": [carried, filed], "candidates": {}, "usable": {}}
    proposals = generate_proposals(artifact, [])
    proposal = next(
        p for p in proposals
        if p.get("kind") == "equation" and p.get("equationMechanic") == "nar_definition"
    )
    outcome = apply_proposal(
        artifact, proposal, workspace_id="ws-test", who="workspace_user", at=AT
    )
    change = outcome["change"]
    assert change["kind"] == "proposal_equation"
    assert change["equationId"] == filed["id"]

    updated = outcome["artifact"]
    chosen = structure.chosen_options(updated)
    nar = next(c for c in chosen if c["mechanic"] == "nar_definition")
    assert nar["equationId"] == filed["id"]
    assert nar["provenanceClass"] == "filed_definition"
    assert nar["stepId"] == "nar"
    assert "Net amount at risk" in structure.definitions_line(chosen)

    # The projection view stamps the same choice onto the run record.
    view = executable_mechanics_view(updated)
    captured = {}

    def fake_provider(code, request):
        captured["request"] = request
        return {
            "projection": {
                "rows": [], "metrics": {}, "mechanicsExecution": {},
                "coverageIssues": [], "appliedEquations": [],
                "incomplete": False, "missingMechanics": [],
                "ledger": None, "rateTables": None, "reconciliation": None,
            },
            "request": {}, "projectionInputs": [],
            "mechanicsExplanation": {}, "warnings": [], "notes": [],
        }

    original = server._get_illustration_provider
    server._get_illustration_provider = lambda code: fake_provider
    try:
        snapshot, *_ = server._build_ul_projection_view(
            "ICC18 P18PR UL", {"_workspaceExecutableMechanics": view}
        )
    finally:
        server._get_illustration_provider = original
    stamped = {c["mechanic"]: c for c in snapshot["definitionsUsed"]}
    assert stamped["nar_definition"]["equationId"] == filed["id"]
    assert stamped["nar_definition"]["provenanceClass"] == "filed_definition"
    assert "Net amount at risk" in snapshot["definitionsLine"]
