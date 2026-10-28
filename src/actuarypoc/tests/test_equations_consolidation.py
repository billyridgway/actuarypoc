"""Equations consolidation (Oct 27, 2026).

Three changes pinned here:

* Equation proposals carry the typeset math tree (and timing note)
  of the exact body a confirmation would put in force — a suggestion
  is approved in the same form it will run in, not as prose.
* Confirm-back summaries state the empty "before" plainly
  ("nothing was in force before"), never "was nothing is in force".
* The filing-review reconciliation: the last analysis's compliance
  snapshot stays frozen, and the workspace payload names what has
  come into force since — requirements counted missing/partial at
  analysis whose table + equation are now in force, and snapshot
  gaps whose subject is now resolved.  Nothing changed → no clause.
"""

from __future__ import annotations

from actuarypoc.domain import equations as eq
from actuarypoc.extract import workspace_equations as ws_eq
from actuarypoc.extract import workspace_mechanics_proposals as proposals
from actuarypoc.extract.workspace_mechanics_panel import (
    filing_review_reconciliation,
)
from actuarypoc.storage import workspace_store
from actuarypoc.ui import server

from actuarypoc.tests.test_analysis_state_persistence import fake  # noqa: F401
from actuarypoc.tests.test_workspace_mechanics_proposals import (
    SURRENDER_TEXT,
    TIMING_TEXT,
    _candidate,
    _empty_artifact,
    _slice,
)

AT = "2026-10-27T20:30:00Z"


def _record(mechanic: str, body: dict, *, state: str = "pending", timing=None) -> dict:
    return ws_eq.new_record(
        mechanic=mechanic,
        body=body,
        state=state,
        source={"kind": "document", "statement": "stated",
                "filename": "memo.pdf", "page": 2},
        at=AT,
        timing=timing,
    )


# ---------------------------------------------------------------------------
# Proposals carry the typeset form
# ---------------------------------------------------------------------------


def test_pending_record_proposal_carries_math_tree_and_timing_note():
    artifact = _empty_artifact()
    artifact["equations"] = [
        _record("premium_load", eq.premium_load_body()),
        _record("coi_charge", eq.coi_body_for_unit("per_1000_monthly"),
                timing="end"),
    ]
    found = proposals.generate_proposals(artifact, [])
    by_mechanic = {p["equationMechanic"]: p for p in found if p["kind"] == "equation"}
    assert set(by_mechanic) == {"premium_load", "coi_charge"}
    premium = by_mechanic["premium_load"]
    assert premium["math"] is not None
    assert premium["math"]["t"] == "mul"
    coi = by_mechanic["coi_charge"]
    assert coi["math"] is not None and coi["math"]["t"] == "mul"
    assert coi["timingNote"] == eq.timing_sentence("end")


def test_harvest_proposal_carries_math_tree():
    artifact = _empty_artifact()
    artifact["usable"]["coi"] = [
        {"duration": 1, "sex": None, "risk_class": None, "tobacco_status": None,
         "rate": 0.19, "rate_unit": "per_1000_monthly",
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf"}}
    ]
    found = proposals.generate_proposals(artifact, [_slice(TIMING_TEXT, page=7)])
    assert len(found) == 1
    assert found[0]["math"] is not None and found[0]["math"]["t"] == "mul"
    assert found[0]["timingNote"] == eq.timing_sentence("end")

    surrender = proposals.generate_proposals(
        _empty_artifact(), [_slice(SURRENDER_TEXT, page=6)]
    )
    assert len(surrender) == 1
    assert surrender[0]["math"] is not None


# ---------------------------------------------------------------------------
# Plain "before" wording
# ---------------------------------------------------------------------------


def test_table_proposal_confirm_back_states_empty_before_plainly():
    artifact = _empty_artifact()
    artifact["candidates"]["fees"].append(_candidate("fees", "cand-fees-1", [
        {"duration": 1, "component": "monthly_expense", "amount": 7.5,
         "amount_unit": "modal_fixed",
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
    ], page=5, heading="Policy and Administrative Charges"))
    found = proposals.generate_proposals(artifact, [])
    assert len(found) == 1
    option = found[0]["options"][0]
    assert "nothing was in force before" in option["confirmBack"]
    assert "was nothing is in force" not in option["confirmBack"]


def test_equation_proposal_confirm_back_states_empty_before_plainly():
    artifact = _empty_artifact()
    artifact["equations"] = [_record("premium_load", eq.premium_load_body())]
    found = proposals.generate_proposals(artifact, [])
    assert len(found) == 1
    assert "nothing was in force before" in found[0]["confirmBack"]
    assert "was no approved equation in force" not in found[0]["confirmBack"]


# ---------------------------------------------------------------------------
# Filing-review reconciliation
# ---------------------------------------------------------------------------


def _snapshot() -> dict:
    return {
        "complianceMatrix": {
            "summary": {"implemented": 3, "partial": 0, "missing": 3,
                        "overallStatus": "red"},
            "requirements": [
                {"id": "guaranteed_credited_rate",
                 "name": "Guaranteed credited rate",
                 "classification": {"implementationState": "implemented"},
                 "evidence": [{"id": "guaranteed_credited_rate"}]},
                {"id": "coi_table", "name": "COI rate table",
                 "classification": {"implementationState": "not_implemented"},
                 "evidence": [{"id": "coi_rates"}]},
                {"id": "surrender_schedule", "name": "Surrender charge schedule",
                 "classification": {"implementationState": "not_implemented"},
                 "evidence": [{"id": "surrender_schedule"}]},
                {"id": "policy_admin_fees", "name": "Policy / admin fees",
                 "classification": {"implementationState": "not_implemented"},
                 "evidence": [{"id": "policy_admin_fee"}]},
            ],
        },
        "gaps": {"items": [
            {"id": "missing_coi_equation", "title": "COI charge equation missing",
             "status": "missing"},
        ]},
    }


def _in_force_artifact() -> dict:
    return {
        "usable": {
            "coi": [{"duration": 1, "rate": 0.19}],
            "surrender": [{"duration": 1, "charge": 0.09}],
            "fees": [{"duration": 1, "amount": 7.5}],
        },
        "equations": [
            _record("coi_charge", eq.coi_body_for_unit("per_1000_monthly"),
                    state="approved"),
            _record("surrender_charge", eq.surrender_body_for_unit("per_1000_face"),
                    state="approved"),
            _record("policy_fees", eq.policy_fees_body(), state="approved"),
        ],
    }


def test_reconciliation_names_what_came_into_force_after_analysis():
    result = filing_review_reconciliation(_snapshot(), _in_force_artifact())
    assert result["missingAtAnalysis"] == 3
    assert result["openGapsAtAnalysis"] == 1
    assert [r["name"] for r in result["resolvedRequirements"]] == [
        "COI rate table", "Surrender charge schedule", "Policy / admin fees",
    ]
    assert [g["id"] for g in result["resolvedGaps"]] == ["missing_coi_equation"]
    assert result["text"] == (
        "3 missing at analysis — now in force: COI rate table, "
        "Surrender charge schedule, Policy / admin fees; "
        "1 open gap at analysis — now resolved: COI charge equation missing"
    )


def test_reconciliation_is_empty_when_nothing_changed():
    result = filing_review_reconciliation(_snapshot(), {})
    assert result["resolvedRequirements"] == []
    assert result["resolvedGaps"] == []
    assert result["text"] is None
    # The frozen counts still report what the analysis found.
    assert result["missingAtAnalysis"] == 3
    assert result["openGapsAtAnalysis"] == 1


def test_reconciliation_names_only_what_actually_resolved():
    artifact = _in_force_artifact()
    artifact["usable"]["fees"] = []
    artifact["equations"] = [
        r for r in artifact["equations"] if r["mechanic"] != "policy_fees"
    ]
    result = filing_review_reconciliation(_snapshot(), artifact)
    assert [r["name"] for r in result["resolvedRequirements"]] == [
        "COI rate table", "Surrender charge schedule",
    ]
    assert "Policy / admin fees" not in (result["text"] or "")


def test_table_without_equation_does_not_reconcile():
    # The filed table alone does not calculate: with the COI table in
    # force but no approved COI equation, the requirement (and the
    # missing-equation gap) stays unreconciled.
    artifact = _in_force_artifact()
    artifact["equations"] = [
        r for r in artifact["equations"] if r["mechanic"] != "coi_charge"
    ]
    result = filing_review_reconciliation(_snapshot(), artifact)
    assert [r["name"] for r in result["resolvedRequirements"]] == [
        "Surrender charge schedule", "Policy / admin fees",
    ]
    assert result["resolvedGaps"] == []


def test_workspace_payload_carries_reconciliation(fake):
    ws = workspace_store.create_workspace()
    workspace_store.update_workspace_analysis(
        ws["id"], status="analyzed", snapshot=_snapshot(),
    )
    workspace_store.store_workspace_executable_mechanics(
        ws["id"], _in_force_artifact(),
    )
    payload = server.api_get_workspace(ws["id"])
    reconciliation = payload["workspace"]["filingReviewReconciliation"]
    assert reconciliation["text"] is not None
    assert "now in force: COI rate table" in reconciliation["text"]


def test_workspace_payload_reconciliation_none_when_nothing_changed(fake):
    ws = workspace_store.create_workspace()
    workspace_store.update_workspace_analysis(
        ws["id"], status="analyzed", snapshot=_snapshot(),
    )
    payload = server.api_get_workspace(ws["id"])
    reconciliation = payload["workspace"]["filingReviewReconciliation"]
    assert reconciliation["text"] is None
    assert reconciliation["resolvedRequirements"] == []
