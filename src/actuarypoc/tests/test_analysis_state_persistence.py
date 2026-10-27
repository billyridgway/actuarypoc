"""Confirmed state must survive re-analysis (Oct 27, 2026 defect).

Billy's sequence on ws-b5ea66f5: confirm table choices + approve
equations, then re-run analysis (the stale banner's own advice) —
afterwards every candidate was back to ``review_required``, every
choice was proposed again, and the projection's rate tables read
"missing", while the equation approvals survived.  The analysis
rebuild must carry the workspace's confirmed decision state over,
merged by candidate identity, exactly as it already carries
workspace edits, corrections, and equation records.

These tests run the full API sequence against a fake object store:
analyze -> confirm -> assert in force -> RE-ANALYZE -> assert still
in force.  Only the document-extraction stage is faked (it returns
the canonical extracted artifact a real extraction of the same
documents would produce — candidate ids are content hashes, so a
re-extraction of unchanged documents reproduces them verbatim).
"""

from __future__ import annotations

import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from actuarypoc.extract import slice_pipeline
from actuarypoc.storage import workspace_store
from actuarypoc.ui import server


CANNED_SNAPSHOT = {
    "product": {"name": "Promise UL", "code": "ICC18 P18PR UL", "type": "UL",
                "carrier": None, "filingId": None},
    "complianceMatrix": {"requirements": [], "summary": {}},
    "readinessDashboard": {},
}

CANNED_SLICE_RUN = {
    "sliceExtraction": {"status": "ok", "conflicts": []},
    "documentMaps": [],
    "extractedTables": [],
    "extractedMechanics": [],
    "extractedAssumptionSet": {"status": "ok"},
    "fact_fills": [],
    "appended_facts": [],
}


def _filed_row(mechanic: str, filename: str, page: int, **fields) -> dict:
    row = dict(fields)
    row["provenance"] = {
        "sourceType": "filed_pdf",
        "reviewStatus": "review_required",
        "filename": filename,
        "page": page,
        "tableHeading": "Filed schedule",
    }
    return row


def _coi_rows(tobacco: str, filename: str, *, rate_base: float = 0.19) -> list:
    return [
        _filed_row(
            "coi", filename, 4,
            duration=d, attained_age=None, sex="M",
            risk_class="Standard", tobacco_status=tobacco,
            rate=rate_base + 0.01 * (d - 1), rate_unit="per_1000_monthly",
        )
        for d in (1, 2, 3)
    ]


def _candidate(mechanic: str, candidate_id: str, rows: list, *, filename: str, page: int) -> dict:
    return {
        "id": candidate_id,
        "mechanic": mechanic,
        "filename": filename,
        "page": page,
        "tableHeading": "Filed schedule",
        "rowCount": len(rows),
        "valueBasis": "guaranteed_maximum",
        "reviewStatus": "review_required",
        "rows": rows,
    }


def _extracted_artifact() -> dict:
    """The fresh artifact an analysis rebuild produces from the documents.

    Two COI candidates that are selector-disjoint slices of one table
    (Non-Tobacco base specimen, Tobacco Nicotine specimen, identical
    rates per duration — the Promise UL shape), one surrender
    candidate, one corridor candidate.
    """

    # Distinct rate bases per slice (0.29 Tobacco vs 0.19 Non-Tobacco)
    # so a scenario's charge proves WHICH slice priced it.
    coi_tob = _coi_rows("Tobacco", "specimen-nicotine.pdf", rate_base=0.29)
    coi_nt = _coi_rows("Non-Tobacco", "specimen-base.pdf")
    surrender = [
        _filed_row(
            "surrender", "specimen-base.pdf", 3,
            duration=d, attained_age=None, sex=None, risk_class=None,
            tobacco_status=None, charge=11 - d, charge_unit="percent_face",
        )
        for d in (1, 2, 3)
    ]
    corridor = [
        _filed_row(
            "corridor", "specimen-base.pdf", 6,
            duration=d, attained_age=None, sex=None, risk_class=None,
            tobacco_status=None, percentage=2.5,
        )
        for d in (1, 2, 3)
    ]
    nar = [
        _filed_row("nar_factors", "specimen-base.pdf", 8, factor=1.0)
    ]
    mechanics = {
        "coi": coi_tob + coi_nt,
        "surrender": surrender,
        "fees": [],
        "nar_factors": nar,
        "corridor": corridor,
    }
    return {
        "version": 1,
        "mechanics": mechanics,
        "warnings": [],
        "usable": {},
        "candidates": {
            "coi": [
                _candidate("coi", "cand-coi-tob", coi_tob, filename="specimen-nicotine.pdf", page=4),
                _candidate("coi", "cand-coi-nt", coi_nt, filename="specimen-base.pdf", page=4),
            ],
            "surrender": [
                _candidate("surrender", "cand-sur", surrender, filename="specimen-base.pdf", page=3),
            ],
            "fees": [],
            "nar_factors": [
                _candidate("nar_factors", "cand-nar", nar, filename="specimen-base.pdf", page=8),
            ],
            "corridor": [
                _candidate("corridor", "cand-cor", corridor, filename="specimen-base.pdf", page=6),
            ],
        },
        "status": {
            mechanic: "filed_evidence_review_required"
            for mechanic in ("coi", "surrender", "fees", "nar_factors", "corridor")
        },
    }


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch):
    from actuarypoc.tests.test_workspace_sources import BucketFakeMinio

    fake = BucketFakeMinio()
    fake.make_bucket("app-bucket")
    for module in (workspace_store, server, slice_pipeline):
        monkeypatch.setattr(module, "get_minio_client", lambda: fake)
        monkeypatch.setattr(module, "ensure_bucket", lambda c: None)
    monkeypatch.setattr(workspace_store, "get_bucket_name", lambda: "app-bucket")
    monkeypatch.setattr(server, "get_bucket_name", lambda: "app-bucket")
    monkeypatch.setattr(slice_pipeline, "get_bucket_name", lambda: "app-bucket")
    monkeypatch.setattr(
        server, "_extract_workspace_executable_mechanics",
        lambda docs: _extracted_artifact(),
    )
    monkeypatch.setattr(
        server, "build_product_workspace_snapshot",
        lambda code: deepcopy(CANNED_SNAPSHOT),
    )
    monkeypatch.setattr(server, "_compile_snapshot_projection_graph", lambda snap: {})
    monkeypatch.setattr(
        slice_pipeline, "run_workspace_slice_extraction",
        lambda **kwargs: deepcopy(CANNED_SLICE_RUN),
    )
    return fake


@pytest.fixture()
def client(fake) -> TestClient:
    return TestClient(server.app)


def _workspace_with_document() -> str:
    ws = workspace_store.create_workspace()
    workspace_store.create_workspace_document(
        workspace_id=ws["id"],
        description="specimen.pdf",
        object_path="uploads/specimen.pdf",
        kind="workspace",
    )
    return ws["id"]


def _analyze(client: TestClient, workspace_id: str) -> dict:
    resp = client.post(f"/api/workspaces/{workspace_id}/analyze")
    assert resp.status_code == 202, resp.text
    deadline = time.monotonic() + 30
    while True:
        body = client.get(f"/api/workspaces/{workspace_id}").json()
        job = (body.get("workspace") or {}).get("analysisJob") or {}
        if job.get("state") in {"succeeded", "failed"}:
            assert job.get("state") == "succeeded", f"analysis failed: {job}"
            return body
        assert time.monotonic() < deadline, f"job did not finish; last state: {job}"
        time.sleep(0.05)


def _panel(client: TestClient, workspace_id: str) -> dict:
    resp = client.get(f"/api/workspaces/{workspace_id}/mechanics-panel")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _slot(panel: dict, slot_id: str) -> dict:
    return next(s for s in panel["slots"] if s["id"] == slot_id)


def _confirm(client: TestClient, workspace_id: str, proposal_id: str, candidate_id=None) -> dict:
    payload = {"confirmed": True}
    if candidate_id:
        payload["candidateId"] = candidate_id
    resp = client.post(
        f"/api/workspaces/{workspace_id}/mechanics-panel/proposals/{proposal_id}/confirm",
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _accept(client: TestClient, workspace_id: str, mechanic: str, candidate_id: str, **extra) -> dict:
    resp = client.post(
        f"/api/workspaces/{workspace_id}/filed-mechanics/accept",
        json={"mechanic": mechanic, "candidateId": candidate_id, **extra},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _projection(client: TestClient, workspace_id: str, tobacco: str, **overrides) -> dict:
    payload = {
        "issueAge": 45,
        "faceAmount": 100000,
        "premiumMode": "ANNUAL",
        "modalPremium": 12000,
        "sex": "M",
        "riskClass": "Standard",
        "tobaccoStatus": tobacco,
    }
    payload.update(overrides)
    resp = client.post(f"/api/workspaces/{workspace_id}/projection", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["illustration"]


# ---------------------------------------------------------------------------
# The arbiter: Billy's sequence under the contract as it stands.
# Confirm a choice, re-run analysis, and the confirmed state must
# still be in force.  (Written against the pre-existing single-choice
# proposal shape so it isolates the re-analysis behavior alone.)
# ---------------------------------------------------------------------------


def test_confirmed_choice_survives_reanalysis(client: TestClient) -> None:
    workspace_id = _workspace_with_document()
    _analyze(client, workspace_id)

    panel = _panel(client, workspace_id)
    coi_proposals = [
        p for p in panel["proposals"]
        if p.get("mechanic") == "coi" and p.get("kind", "").startswith("filed_table")
    ]
    assert coi_proposals, "expected a filed COI proposal after analysis"
    proposal = coi_proposals[0]
    option_ids = [
        o["candidateId"] for o in proposal.get("options") or []
    ] or [proposal.get("candidateId")]
    assert "cand-coi-tob" in option_ids
    _confirm(client, workspace_id, proposal["id"], "cand-coi-tob")
    # The remaining tables the transcribed equations read, accepted
    # through the slot-card path (Billy's flow accepted them all).
    _accept(client, workspace_id, "surrender", "cand-sur")
    _accept(client, workspace_id, "corridor", "cand-cor")
    _accept(client, workspace_id, "nar_factors", "cand-nar")

    # In force everywhere before the re-run.
    panel = _panel(client, workspace_id)
    coi_slot = _slot(panel, "coi")
    in_force = [c for c in coi_slot["candidates"] if c.get("inForce")]
    assert [c["id"] for c in in_force] == ["cand-coi-tob"], coi_slot["candidates"]
    illustration = _projection(client, workspace_id, "Tobacco")
    assert illustration["rows"][0]["coiCharge"] > 0, illustration["rows"][0]

    # The stale banner's own advice: re-run the analysis.
    body = _analyze(client, workspace_id)
    assert body["workspace"]["projectionStale"] is False

    # The confirmed choice must still be in force — panel, equations
    # view, and the projection's own rate tables must agree.
    panel = _panel(client, workspace_id)
    coi_slot = _slot(panel, "coi")
    in_force = [c for c in coi_slot["candidates"] if c.get("inForce")]
    assert [c["id"] for c in in_force] == ["cand-coi-tob"], (
        "re-analysis discarded the confirmed COI acceptance: "
        f"{coi_slot['candidates']}"
    )
    assert coi_slot["rowCount"] == 3
    illustration = _projection(client, workspace_id, "Tobacco")
    assert illustration["rows"][0]["coiCharge"] > 0, illustration["rows"][0]
    coi_table = (illustration.get("rateTables") or {}).get("coi") or {}
    assert coi_table.get("status") != "missing", coi_table


# ---------------------------------------------------------------------------
# Selector slices: both specimens approved, each scenario priced by
# its own slice, and both acceptances survive re-analysis.
# ---------------------------------------------------------------------------


def _confirm_candidate(client: TestClient, workspace_id: str, candidate_id: str) -> None:
    panel = _panel(client, workspace_id)
    proposal = next(
        p for p in panel["proposals"] if p.get("candidateId") == candidate_id
    )
    _confirm(client, workspace_id, proposal["id"], candidate_id)


def _accept_all_tables(client: TestClient, workspace_id: str) -> None:
    _confirm_candidate(client, workspace_id, "cand-coi-tob")
    _confirm_candidate(client, workspace_id, "cand-coi-nt")
    _accept(client, workspace_id, "surrender", "cand-sur")
    _accept(client, workspace_id, "corridor", "cand-cor")
    _accept(client, workspace_id, "nar_factors", "cand-nar")


def test_both_coi_slices_union_and_each_scenario_computes(client: TestClient) -> None:
    workspace_id = _workspace_with_document()
    _analyze(client, workspace_id)
    _accept_all_tables(client, workspace_id)

    panel = _panel(client, workspace_id)
    coi_slot = _slot(panel, "coi")
    assert coi_slot["rowCount"] == 6
    assert {c["id"] for c in coi_slot["candidates"] if c.get("inForce")} == {
        "cand-coi-tob", "cand-coi-nt",
    }

    tobacco = _projection(client, workspace_id, "Tobacco")
    non_tobacco = _projection(client, workspace_id, "Non-Tobacco")
    assert tobacco["rows"][0]["coiCharge"] > 0
    assert non_tobacco["rows"][0]["coiCharge"] > 0
    # The Tobacco slice prices at 0.29, the Non-Tobacco at 0.19: each
    # scenario was priced by its OWN slice's rows.
    assert tobacco["rows"][0]["coiCharge"] > non_tobacco["rows"][0]["coiCharge"]
    assert (tobacco.get("rateTables") or {})["coi"]["rowCount"] == 6

    # Re-analysis keeps both slices in force and both scenarios live.
    _analyze(client, workspace_id)
    panel = _panel(client, workspace_id)
    coi_slot = _slot(panel, "coi")
    assert {c["id"] for c in coi_slot["candidates"] if c.get("inForce")} == {
        "cand-coi-tob", "cand-coi-nt",
    }
    assert _projection(client, workspace_id, "Tobacco")["rows"][0]["coiCharge"] > 0
    assert _projection(client, workspace_id, "Non-Tobacco")["rows"][0]["coiCharge"] > 0


# ---------------------------------------------------------------------------
# Genuine conflicts: same selectors, different values.  Never a
# silent merge — the direct accept refuses, the proposal asks, and
# only the user's explicit choice overrides (a fully overridden
# slice is the one genuine "superseded").
# ---------------------------------------------------------------------------


def _conflicting_artifact() -> dict:
    artifact = _extracted_artifact()
    challenger = _coi_rows("Tobacco", "specimen-nicotine-corrected.pdf", rate_base=0.39)
    artifact["candidates"]["coi"].append(
        _candidate(
            "coi", "cand-coi-tob2", challenger,
            filename="specimen-nicotine-corrected.pdf", page=4,
        )
    )
    artifact["mechanics"]["coi"] = artifact["mechanics"]["coi"] + challenger
    return artifact


def test_conflicting_slice_refuses_then_the_users_choice_governs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        server, "_extract_workspace_executable_mechanics",
        lambda docs: _conflicting_artifact(),
    )
    workspace_id = _workspace_with_document()
    _analyze(client, workspace_id)
    _confirm_candidate(client, workspace_id, "cand-coi-tob")
    _accept(client, workspace_id, "surrender", "cand-sur")
    _accept(client, workspace_id, "corridor", "cand-cor")
    _accept(client, workspace_id, "nar_factors", "cand-nar")
    before = _projection(client, workspace_id, "Tobacco")["rows"][0]["coiCharge"]
    assert before > 0

    # Direct accept of the challenger refuses without the explicit
    # conflict decision.
    resp = client.post(
        f"/api/workspaces/{workspace_id}/filed-mechanics/accept",
        json={"mechanic": "coi", "candidateId": "cand-coi-tob2"},
    )
    assert resp.status_code == 409, resp.text
    assert "conflicts with the accepted table" in resp.json()["detail"]

    # The proposal names the conflict and requires the choice.
    panel = _panel(client, workspace_id)
    conflict = next(
        p for p in panel["proposals"] if p.get("conflict")
    )
    assert conflict["conflict"]["candidateId"] == "cand-coi-tob2"
    assert conflict["conflict"]["differingRows"] == 3
    resp = client.post(
        f"/api/workspaces/{workspace_id}/mechanics-panel/proposals/{conflict['id']}/confirm",
        json={"confirmed": True},
    )
    assert resp.status_code in {400, 409}, resp.text

    # Choosing the challenger: its rows govern the contested region;
    # the incumbent, overridden on every row, is superseded.
    _confirm(client, workspace_id, conflict["id"], "cand-coi-tob2")
    panel = _panel(client, workspace_id)
    coi_slot = _slot(panel, "coi")
    states = {c["id"]: c for c in coi_slot["candidates"]}
    assert states["cand-coi-tob2"]["inForce"] is True
    assert states["cand-coi-tob"]["reviewStatus"] == "superseded"
    assert states["cand-coi-tob"]["overriddenRowCount"] == 3
    # The Tobacco scenario now prices from the challenger's 0.39 rows
    # (vs the incumbent's 0.29): the charge rises by roughly the rate
    # ratio, proving the challenger's rows govern.
    after = _projection(client, workspace_id, "Tobacco")["rows"][0]["coiCharge"]
    assert after > before * 1.2


def test_conflict_kept_branch_leaves_the_incumbent_governing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        server, "_extract_workspace_executable_mechanics",
        lambda docs: _conflicting_artifact(),
    )
    workspace_id = _workspace_with_document()
    _analyze(client, workspace_id)
    _confirm_candidate(client, workspace_id, "cand-coi-tob")

    panel = _panel(client, workspace_id)
    conflict = next(p for p in panel["proposals"] if p.get("conflict"))
    outcome = _confirm(client, workspace_id, conflict["id"], "cand-coi-tob")

    panel = _panel(client, workspace_id)
    coi_slot = _slot(panel, "coi")
    states = {c["id"]: c for c in coi_slot["candidates"]}
    assert states["cand-coi-tob"]["inForce"] is True
    assert states["cand-coi-tob2"]["inForce"] is False
    assert coi_slot["rowCount"] == 3
    # The decision is recorded and the conflict does not re-ask.
    assert not any(p.get("conflict") for p in panel["proposals"])
    assert outcome["change"]["kind"] == "proposal_conflict_kept"


# ---------------------------------------------------------------------------
# Dismissals survive re-analysis; the stale flag's full lifecycle.
# ---------------------------------------------------------------------------


def test_proposal_dismissal_survives_reanalysis(client: TestClient) -> None:
    workspace_id = _workspace_with_document()
    _analyze(client, workspace_id)
    panel = _panel(client, workspace_id)
    corridor = next(
        p for p in panel["proposals"] if p.get("candidateId") == "cand-cor"
    )
    resp = client.post(
        f"/api/workspaces/{workspace_id}/mechanics-panel/proposals/{corridor['id']}/dismiss",
        json={},
    )
    assert resp.status_code == 200, resp.text

    _analyze(client, workspace_id)
    panel = _panel(client, workspace_id)
    assert not any(
        p.get("candidateId") == "cand-cor" for p in panel["proposals"]
    )
    corridor_slot = _slot(panel, "corridor")
    assert corridor_slot["candidates"][0]["reviewStatus"] == "review_required"


def _stale(client: TestClient, workspace_id: str) -> bool:
    body = client.get(f"/api/workspaces/{workspace_id}").json()
    return bool((body.get("workspace") or {}).get("projectionStale"))


def test_stale_flag_lifecycle(client: TestClient) -> None:
    workspace_id = _workspace_with_document()
    _analyze(client, workspace_id)
    assert _stale(client, workspace_id) is False

    # An input change (a confirmed table choice) marks it.
    _confirm_candidate(client, workspace_id, "cand-coi-tob")
    assert _stale(client, workspace_id) is True

    # A completed projection run recomputes from current inputs: clear.
    _projection(client, workspace_id, "Tobacco")
    assert _stale(client, workspace_id) is False

    # A direct filed-table acceptance marks it too.
    _accept(client, workspace_id, "surrender", "cand-sur")
    assert _stale(client, workspace_id) is True

    # A re-analysis discharges it (its saved projection was recomputed
    # from the inputs as of the analysis start).
    _analyze(client, workspace_id)
    assert _stale(client, workspace_id) is False


# ---------------------------------------------------------------------------
# A missing table is NAMED — coverageIssues carries it before the
# run's numbers are read, and the mechanic's absence entry names the
# table instead of an unexplained evaluation failure.
# ---------------------------------------------------------------------------


def test_missing_table_is_named_not_an_evaluation_failure(client: TestClient) -> None:
    workspace_id = _workspace_with_document()
    _analyze(client, workspace_id)

    # An approved COI equation in force with NO table accepted (the
    # Oct 27 live state after the wipe).
    artifact = server.load_workspace_executable_mechanics(workspace_id)
    record = server._workspace_equations.new_record(
        mechanic="coi_charge",
        body=server._workspace_equations.coi_body_for_unit("per_1000_monthly"),
        state="approved",
        source={"kind": "document", "statement": None, "note": "test seed"},
        at="2026-10-27T00:00:00Z",
        timing="beginning",
    )
    record["approval"] = {"by": "eddy", "at": "2026-10-27T00:00:00Z"}
    artifact.setdefault("equations", []).append(record)
    server.store_workspace_executable_mechanics(workspace_id, artifact)

    resp = client.post(
        f"/api/workspaces/{workspace_id}/projection",
        json={
            "issueAge": 45, "faceAmount": 100000, "premiumMode": "ANNUAL",
            "modalPremium": 12000, "sex": "M", "riskClass": "Standard",
            "tobaccoStatus": "Tobacco",
        },
    )
    assert resp.status_code == 200, resp.text
    illustration = resp.json()["illustration"]
    named = [
        issue for issue in illustration["coverageIssues"]
        if issue.get("kind") == "table_not_in_force" and issue.get("table") == "coi"
    ]
    assert named and "no COI table is in force" in named[0]["message"]
    missing = {m["mechanic"]: m for m in illustration["missingMechanics"]}
    assert missing["coi_charge"]["reason"] == "table_not_in_force"
    assert "COI table" in missing["coi_charge"]["detail"]
    # Exactly one absence entry for the mechanic, and its per-year
    # failures collapse into one summary group (never 30 rows).
    assert sum(
        1 for m in illustration["missingMechanics"] if m["mechanic"] == "coi_charge"
    ) == 1
    execution = illustration["mechanicsExecution"]["coi_charge"]
    assert len(execution["failureSummary"]) == 1


# ---------------------------------------------------------------------------
# carry_over_decision_state, unit level: synthetic state transplants,
# and a decided candidate the new extraction no longer produces is
# reported, never silently dropped.
# ---------------------------------------------------------------------------


def test_carry_over_transplants_synthetic_and_reports_vanished() -> None:
    from actuarypoc.extract.workspace_ul_mechanics import (
        accept_filed_mechanic,
        carry_over_decision_state,
    )

    prior = accept_filed_mechanic(
        _extracted_artifact(), "coi", candidate_id="cand-coi-nt",
        reviewed_by="billy",
    )
    prior["synthetic"] = {
        "surrender": {"status": "accepted", "sourceType": "ai_synthetic"}
    }
    prior["usable"]["surrender"] = [{
        "duration": 1, "charge": 0.1, "charge_unit": "percent_face",
        "provenance": {"sourceType": "ai_synthetic", "reviewStatus": "accepted"},
    }]
    prior["status"]["surrender"] = "synthetic_scenario"

    fresh = _extracted_artifact()
    # The new extraction no longer produces the accepted NT slice.
    fresh["candidates"]["coi"] = [
        c for c in fresh["candidates"]["coi"] if c["id"] != "cand-coi-nt"
    ]
    fresh["mechanics"]["coi"] = [
        row for row in fresh["mechanics"]["coi"]
        if (row.get("provenance") or {}).get("filename") != "specimen-base.pdf"
    ]

    outcome = carry_over_decision_state(fresh, prior)
    artifact = outcome["artifact"]
    assert artifact["synthetic"]["surrender"]["status"] == "accepted"
    assert len(artifact["usable"]["surrender"]) == 1
    assert artifact["status"]["surrender"] == "synthetic_scenario"
    assert any("cand-coi-nt" in note for note in outcome["notes"])
