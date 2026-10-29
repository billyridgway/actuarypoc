"""Bulk approval ("approve all uncontested") + typeset equations.

Billy (Oct 27, 2026) approved both features in one breath.  The bulk
action exists because approving a fresh workspace's suggestions one
by one is a ten-click slog — but it is built UNDER the doctrine, not
around it: a summary first (what will be approved; what is excluded,
named, and why), nothing applied without the confirmed call, every
item applied through the single-item paths and recorded individually
in the change history under one batch id.  The eligibility matrix is
the point: competing readings for one mechanic, a replacement of a
different in-force equation, and a table candidate in genuine
conflict with rows in force all stay pending — bulk approval never
swallows a rival.

The typeset form is the same formula body walked into a structured
math tree (fraction / lookup / cases), rendered beside — never
instead of — the prose rendering, with a hard fallback: an unknown
node shape yields no tree at all, and the prose stands alone.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from actuarypoc.domain import equations as eq
from actuarypoc.domain.projection_ledger import build_rate_tables_in_force
from actuarypoc.extract import workspace_equations as ws_eq
from actuarypoc.extract.workspace_mechanics_proposals import (
    apply_bulk_approval,
    bulk_summary,
    plan_bulk_approval,
)
from actuarypoc.extract.workspace_ul_mechanics import accept_filed_mechanic
from actuarypoc.ui import server

from actuarypoc.tests.test_analysis_state_persistence import (
    _analyze,
    _candidate,
    _coi_rows,
    _confirm,
    _extracted_artifact,
    _filed_row,
    _panel,
    _projection,
    _workspace_with_document,
    fake,
)

AT = "2026-10-27T12:00:00Z"


@pytest.fixture()
def client(fake) -> TestClient:
    return TestClient(server.app)


def _pending_record(mechanic: str, body: dict, *, statement: str = "stated") -> dict:
    return ws_eq.new_record(
        mechanic=mechanic,
        body=body,
        state="pending",
        source={"kind": "document", "statement": statement,
                "filename": "memo.pdf", "page": 2},
        at=AT,
    )


# ---------------------------------------------------------------------------
# Typeset rendering — structure, coverage, fallback
# ---------------------------------------------------------------------------


def _kinds(tree) -> set:
    found = set()

    def walk(node):
        if isinstance(node, dict):
            if "t" in node:
                found.add(node["t"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(tree)
    return found


CANONICAL_BODIES = {
    "coi_charge": eq.coi_body_for_unit("per_1000_monthly"),
    "surrender_charge": eq.surrender_body_for_unit("per_1000_face"),
    "premium_load": eq.premium_load_body(),
    "policy_fees": eq.policy_fees_body(),
    "crediting": eq.crediting_body(),
    "nar_definition": eq.nar_body("factor_adjusted"),
    "death_benefit": eq.death_benefit_body(),
}


def test_all_seven_promise_ul_bodies_render_typeset() -> None:
    for mechanic, body in CANONICAL_BODIES.items():
        tree = eq.render_math_tree(body, mechanic)
        assert tree is not None, mechanic


def test_coi_tree_is_a_fraction_times_a_lookup() -> None:
    tree = eq.render_math_tree(CANONICAL_BODIES["coi_charge"], "coi_charge")
    assert tree["t"] == "mul"
    fraction, lookup = tree["items"]
    assert fraction["t"] == "div"
    assert fraction["num"] == {"t": "qty", "v": "nar", "label": "net amount at risk"}
    assert fraction["den"] == {"t": "num", "v": "1000"}
    assert lookup["t"] == "lookup"
    assert lookup["name"] == "COI rate"
    assert lookup["args"] == ["duration", "attained age"]


def test_fee_chain_renders_as_a_summation_of_cases() -> None:
    tree = eq.render_math_tree(CANONICAL_BODIES["policy_fees"], "policy_fees")
    assert tree["t"] == "rows_sum"
    assert tree["tableLabel"] == "fee schedule"
    assert any("percent_premium" in note for note in tree["notes"])
    cases = tree["expr"]
    assert cases["t"] == "cases"
    assert len(cases["rows"]) == 2  # then-branch + otherwise
    # The unit chain nests down the "otherwise" branches: three
    # cases deep before the plain row amount falls out.
    depth = 0
    node = cases
    while node["t"] == "cases":
        depth += 1
        node = node["rows"][1]["value"]
    assert depth == 3
    assert node == {"t": "qty", "v": "row_amount", "label": "row amount"}
    assert {"cmp", "div", "mul", "str"} <= _kinds(tree)


def test_crediting_tree_has_power_with_fraction_exponent() -> None:
    tree = eq.render_math_tree(CANONICAL_BODIES["crediting"], "crediting")
    kinds = _kinds(tree)
    assert {"pow", "div", "paren", "sub"} <= kinds


def test_nar_and_death_benefit_trees_use_max_and_lookups() -> None:
    nar = eq.render_math_tree(CANONICAL_BODIES["nar_definition"], "nar_definition")
    assert nar["t"] == "max"
    assert "lookup" in _kinds(nar)
    db = eq.render_math_tree(CANONICAL_BODIES["death_benefit"], "death_benefit")
    assert db["t"] == "max"
    assert db["items"][0]["v"] == "face_amount"


def test_premium_load_lookup_carries_its_where() -> None:
    tree = eq.render_math_tree(CANONICAL_BODIES["premium_load"], "premium_load")
    lookup = next(item for item in tree["items"] if item["t"] == "lookup")
    assert {"field": "fee unit", "value": "percent_premium"} in lookup["where"]
    assert lookup["default"] == {"t": "num", "v": "0"}


def test_unknown_shapes_fall_back_to_no_tree() -> None:
    assert eq.render_math_tree({"frobnicate": {"qty": "nar"}}) is None
    assert eq.render_math_tree({"mul": [{"qty": "nar"}, {"wat": 1}]}) is None
    assert eq.render_math_tree(None) is None
    assert eq.render_math_tree({}) is None


def test_record_view_and_citation_carry_math_and_timing() -> None:
    record = ws_eq.new_record(
        mechanic="coi_charge",
        body=CANONICAL_BODIES["coi_charge"],
        state="approved",
        source={"kind": "document", "filename": "spec.pdf", "page": 4},
        at=AT,
        timing="beginning",
    )
    view = ws_eq.record_view(record)
    assert view["math"]["t"] == "mul"
    assert view["timingNote"] == eq.TIMING_SENTENCES["beginning"]
    tables = build_rate_tables_in_force(
        {"coi": [], "surrender": []}, equations={"coi_charge": record}
    )
    citation = tables["coi"]["equation"]
    assert citation["math"]["t"] == "mul"
    assert citation["timingNote"] == eq.TIMING_SENTENCES["beginning"]


def test_record_view_with_unstructurable_body_has_no_math() -> None:
    record = _pending_record("crediting", {"frobnicate": 1})
    view = ws_eq.record_view(record)
    assert view["math"] is None
    assert view["rendering"]  # the prose (such as it is) still stands


# ---------------------------------------------------------------------------
# Bulk planning — the eligibility matrix
# ---------------------------------------------------------------------------


def test_plan_makes_every_clean_slice_eligible() -> None:
    plan = plan_bulk_approval(_extracted_artifact(), [])
    eligible_ids = {
        item["candidateId"] for item in plan["eligible"] if item.get("candidateId")
    }
    assert eligible_ids == {
        "cand-coi-tob", "cand-coi-nt", "cand-sur", "cand-cor", "cand-nar",
    }
    # The two text-stated readings ride the same batch as their own
    # equation items (Oct 28, 2026): approved as equations in the
    # batch, never transcribed from the tables they read.
    assert {
        item["mechanic"] for item in plan["eligible"] if item["kind"] == "equation"
    } == {"death_benefit", "nar_definition"}
    assert plan["excluded"] == []
    summary = bulk_summary(plan)
    assert summary["eligibleCount"] == 7
    assert summary["tableCount"] == 5
    assert summary["equationCount"] == 2


def test_plan_excludes_competing_readings_by_name() -> None:
    artifact = _extracted_artifact()
    artifact["equations"] = [
        _pending_record("policy_fees", eq.policy_fees_body(), statement="reading A"),
        _pending_record(
            "policy_fees",
            {"rows_sum": {"table": "fees", "expr": {"qty": "row_amount"}}},
            statement="reading B",
        ),
        _pending_record("crediting", eq.crediting_body(), statement="clean"),
    ]
    plan = plan_bulk_approval(artifact, [])
    excluded = [i for i in plan["excluded"] if i["kind"] == "equation"]
    assert len(excluded) == 2
    assert all("competing readings" in i["reason"] for i in excluded)
    eligible_eq = [i for i in plan["eligible"] if i["kind"] == "equation"]
    assert [i["mechanic"] for i in eligible_eq] == ["crediting"]


def test_plan_excludes_a_replacement_of_an_in_force_equation() -> None:
    artifact = _extracted_artifact()
    approved = _pending_record("crediting", eq.crediting_body())
    approved["state"] = "approved"
    approved["approval"] = {"by": "workspace_user", "at": AT}
    challenger = _pending_record(
        "crediting",
        {"mul": [{"qty": "account_value"}, {"const": 0.02}]},
        statement="a different crediting reading",
    )
    artifact["equations"] = [approved, challenger]
    plan = plan_bulk_approval(artifact, [])
    excluded = [i for i in plan["excluded"] if i["kind"] == "equation"]
    assert len(excluded) == 1
    assert "replace" in excluded[0]["reason"]


def test_plan_excludes_a_candidate_in_conflict_with_rows_in_force() -> None:
    artifact = accept_filed_mechanic(
        _extracted_artifact(), "coi", candidate_id="cand-coi-nt",
        reviewed_by="workspace_user",
    )
    challenger_rows = _coi_rows("Non-Tobacco", "rival.pdf", rate_base=0.55)
    artifact["candidates"]["coi"].append(
        _candidate("coi", "cand-coi-rival", challenger_rows,
                   filename="rival.pdf", page=9)
    )
    plan = plan_bulk_approval(artifact, [])
    excluded = [i for i in plan["excluded"] if i.get("candidateId") == "cand-coi-rival"]
    assert len(excluded) == 1
    assert "disagree" in excluded[0]["reason"]


# ---------------------------------------------------------------------------
# Bulk application — through the single-item paths, batch-tagged
# ---------------------------------------------------------------------------


def test_apply_approves_the_clean_set_and_tags_the_batch() -> None:
    artifact = _extracted_artifact()
    outcome = apply_bulk_approval(
        artifact, [], workspace_id="ws-test", who="workspace_user", at=AT
    )
    assert len(outcome["applied"]) == 7
    assert len(outcome["changes"]) == 7
    assert all(c["batchId"] == outcome["batchId"] for c in outcome["changes"])
    assert all(c["bulkApproval"] is True for c in outcome["changes"])
    updated = outcome["artifact"]
    assert len(updated["usable"]["coi"]) == 6  # both slices, unioned
    assert plan_bulk_approval(updated, [])["eligible"] == []


def test_apply_never_swallows_a_mid_batch_conflict() -> None:
    artifact = _extracted_artifact()
    rival_rows = _coi_rows("Non-Tobacco", "rival.pdf", rate_base=0.55)
    artifact["candidates"]["coi"].append(
        _candidate("coi", "cand-coi-rival", rival_rows,
                   filename="rival.pdf", page=9)
    )
    plan = plan_bulk_approval(artifact, [])
    # Neither candidate conflicts with anything IN FORCE at plan time.
    assert {i["candidateId"] for i in plan["eligible"]} >= {
        "cand-coi-nt", "cand-coi-rival",
    }
    outcome = apply_bulk_approval(
        artifact, [], workspace_id="ws-test", who="workspace_user", at=AT
    )
    applied_ids = {i["candidateId"] for i in outcome["applied"]}
    skipped = {i["candidateId"]: i for i in outcome["skipped"]}
    assert "cand-coi-nt" in applied_ids
    assert "cand-coi-rival" in skipped
    assert "disagree" in skipped["cand-coi-rival"]["reason"]
    rival = next(
        c for c in outcome["artifact"]["candidates"]["coi"]
        if c["id"] == "cand-coi-rival"
    )
    assert rival["reviewStatus"] == "review_required"


# ---------------------------------------------------------------------------
# The endpoint — summary before apply, batch history, contested stays
# ---------------------------------------------------------------------------


def _approve_all(client: TestClient, workspace_id: str, **payload) -> "object":
    return client.post(
        f"/api/workspaces/{workspace_id}/mechanics-panel/approve-all",
        json=payload,
    )


def _history(client: TestClient, workspace_id: str) -> list:
    resp = client.get(f"/api/workspaces/{workspace_id}/mechanics-panel/history")
    assert resp.status_code == 200, resp.text
    return resp.json()["changes"]


def test_unconfirmed_bulk_call_summarises_and_changes_nothing(
    client: TestClient,
) -> None:
    workspace_id = _workspace_with_document()
    _analyze(client, workspace_id)
    before = _panel(client, workspace_id)
    assert len(before["proposals"]) == 7

    resp = _approve_all(client, workspace_id)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "confirmation_required"
    assert detail["summary"]["eligibleCount"] == 7
    assert detail["summary"]["tableCount"] == 5
    assert "Approve all uncontested" in detail["confirmBack"]

    after = _panel(client, workspace_id)
    assert len(after["proposals"]) == 7
    assert _history(client, workspace_id) == []


def test_confirmed_bulk_call_applies_and_records_the_batch(
    client: TestClient,
) -> None:
    workspace_id = _workspace_with_document()
    _analyze(client, workspace_id)

    resp = _approve_all(client, workspace_id, confirmed=True)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert body["summary"]["appliedCount"] == 7

    changes = _history(client, workspace_id)
    assert len(changes) == 7
    assert all(c.get("batchId") == body["batchId"] for c in changes)
    assert all(c.get("bulkApproval") is True for c in changes)

    panel = _panel(client, workspace_id)
    assert panel["proposals"] == []
    coi = next(s for s in panel["slots"] if s["id"] == "coi")
    assert coi["rowCount"] == 6  # both filed slices in force as a union

    illustration = _projection(client, workspace_id, "Tobacco")
    # The approved set prices the scenario: the COI table the batch
    # put in force is the one the run charges from, and year 1 (inside
    # the fixture's 3-duration schedule) carries a real COI charge.
    assert illustration["rateTables"]["coi"]["status"] == "filed"
    assert illustration["rows"][0]["coiCharge"] > 0


def test_confirmed_bulk_call_leaves_contested_items_pending(
    client: TestClient,
) -> None:
    workspace_id = _workspace_with_document()
    _analyze(client, workspace_id)

    # Plant two rival readings of policy_fees and one clean crediting
    # reading on the analyzed artifact, as harvesting would leave them.
    artifact = server.load_workspace_executable_mechanics(workspace_id)
    artifact["equations"] = [
        _pending_record("policy_fees", eq.policy_fees_body(), statement="reading A"),
        _pending_record(
            "policy_fees",
            {"rows_sum": {"table": "fees", "expr": {"qty": "row_amount"}}},
            statement="reading B",
        ),
        _pending_record("crediting", eq.crediting_body(), statement="clean"),
    ]
    server.store_workspace_executable_mechanics(workspace_id, artifact)

    resp = _approve_all(client, workspace_id)
    assert resp.status_code == 400, resp.text
    summary = resp.json()["detail"]["summary"]
    assert summary["eligibleCount"] == 6  # 5 tables + the clean equation
    assert summary["equationCount"] == 1
    assert len(summary["excluded"]) == 2
    assert all("competing readings" in e["reason"] for e in summary["excluded"])

    resp = _approve_all(client, workspace_id, confirmed=True)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["appliedCount"] == 6

    equations = body["panel"]["equations"]["mechanics"]
    assert equations["crediting"]["inForce"] is not None
    assert equations["crediting"]["inForce"]["math"]["t"] == "mul"
    assert equations["policy_fees"]["inForce"] is None
    pending_fees = [
        r for r in equations["policy_fees"]["records"] if r["state"] == "pending"
    ]
    assert len(pending_fees) == 2

    changes = _history(client, workspace_id)
    assert len(changes) == 6
    assert all(c.get("batchId") == body["batchId"] for c in changes)


def test_apply_delivers_the_promised_reading_not_the_transcribed_one() -> None:
    """Live-gate regression (Oct 27, 2026): the memo's prose harvests
    an ephemeral premium-load reading (10% of premium, a const body)
    while accepting the fees table transcribes a DIFFERENT premium
    load (the fee-table lookup) for any mechanic with no record yet.
    A tables-first batch displaced the promised reading before its
    turn; the batch must land the confirmed equations first so
    transcription defers to them."""
    artifact = _extracted_artifact()
    fees_rows = [
        _filed_row(
            "fees", "specimen-base.pdf", 5, component="premium_expense",
            duration=None, premium_mode=None, amount=10.0,
            fee_unit="percent_premium",
        ),
        _filed_row(
            "fees", "specimen-base.pdf", 5, component="policy_fee",
            duration=None, premium_mode=None, amount=60.0,
            fee_unit="annual_fixed",
        ),
    ]
    artifact["mechanics"]["fees"] = fees_rows
    artifact["candidates"]["fees"] = [
        _candidate("fees", "cand-fees", fees_rows,
                   filename="specimen-base.pdf", page=5)
    ]
    slices = [{
        "text": (
            "The Premium Expense Charge is currently set at 10% for "
            "new issues, applied to each premium."
        ),
        "document_hint": "memo.pdf",
        "page": 2,
    }]
    plan = plan_bulk_approval(artifact, slices)
    eligible_eq = [i for i in plan["eligible"] if i["kind"] == "equation"]
    assert {i["mechanic"] for i in eligible_eq} == {
        "premium_load", "death_benefit", "nar_definition",
    }

    outcome = apply_bulk_approval(
        artifact, slices, workspace_id="ws-test", who="workspace_user", at=AT
    )
    assert outcome["skipped"] == []
    assert len(outcome["applied"]) == len(plan["eligible"])
    in_force = ws_eq.in_force(outcome["artifact"], "premium_load")
    assert in_force is not None
    assert in_force["body"] == {"mul": [{"qty": "premium_due"}, {"const": 0.1}]}
