from __future__ import annotations

"""Phase 2 (the chassis): mechanics panel — slots, edits, change log.

Covers slot-status derivation from each mechanics state, edit validation
through the same validators ingestion uses (invalid input rejected whole,
no partial write), persistence round-trips through the object store,
staleness marking and clearing, survival of edits across an analysis
re-run, and the plan's exit flow at API level: edit the policy fee ->
re-run -> the Phase 1 ledger shows the new fee; paste a COI table ->
the ledger's rate tables show it in force.
"""

import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from actuarypoc.extract import workspace_mechanics_panel as panel
from actuarypoc.storage import workspace_store
from actuarypoc.ui import server


# ---------------------------------------------------------------------------
# Fake MinIO (same pattern as test_workspace_store)
# ---------------------------------------------------------------------------


class MissingObject(Exception):
    code = "NoSuchKey"


class Response(io.BytesIO):
    def release_conn(self) -> None:
        pass


class FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def make_bucket(self, bucket: str) -> None:
        raise AssertionError("bucket already exists")

    def put_object(self, bucket, key, stream, *, length, content_type) -> None:
        self.objects[key] = stream.read(length)

    def get_object(self, bucket, key) -> Response:
        if key not in self.objects:
            raise MissingObject(key)
        return Response(self.objects[key])

    def list_objects(self, bucket, *, prefix, recursive):
        return [
            SimpleNamespace(object_name=key)
            for key in sorted(self.objects)
            if key.startswith(prefix)
        ]

    def remove_object(self, bucket, key) -> None:
        self.objects.pop(key, None)


@pytest.fixture()
def store(monkeypatch: pytest.MonkeyPatch) -> FakeMinio:
    client = FakeMinio()
    monkeypatch.setattr(workspace_store, "get_minio_client", lambda: client)
    monkeypatch.setattr(workspace_store, "get_bucket_name", lambda: "test")
    monkeypatch.setattr(workspace_store, "ensure_bucket", lambda client: None)
    return client


def _empty_artifact() -> dict:
    return {
        "version": 1,
        "mechanics": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
        "warnings": [],
        "usable": {},
        "candidates": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
        "status": {},
    }


def _seed_workspace(store: FakeMinio, *, snapshot: dict | None = None) -> str:
    ws = workspace_store.create_workspace()
    workspace_id = ws["id"]
    workspace_store.store_workspace_executable_mechanics(workspace_id, _empty_artifact())
    if snapshot is not None:
        workspace_store.update_workspace_analysis(
            workspace_id, status="analyzed", snapshot=snapshot
        )
    return workspace_id


# ---------------------------------------------------------------------------
# Slot-status derivation
# ---------------------------------------------------------------------------


def _slot(artifact: dict, slot_id: str) -> dict:
    return panel.build_slot_view(artifact, panel.SLOT_BY_ID[slot_id], {})


def test_slot_status_missing_when_artifact_is_empty() -> None:
    view = _slot(_empty_artifact(), "coi")
    assert view["status"] == "missing"
    assert view["rowCount"] == 0
    assert view["editable"] is True


def test_slot_status_filed_pending_review() -> None:
    artifact = _empty_artifact()
    artifact["candidates"]["coi"] = [{
        "id": "cand-1", "mechanic": "coi", "reviewStatus": "review_required",
        "filename": "filing.pdf", "page": 4, "rowCount": 121, "rows": [],
    }]
    view = _slot(artifact, "coi")
    assert view["status"] == "filed_pending_review"
    assert view["pendingCandidateCount"] == 1


def test_slot_status_filed_accepted() -> None:
    artifact = _empty_artifact()
    artifact["usable"]["coi"] = [{
        "duration": 1, "attained_age": None, "sex": None, "risk_class": None,
        "tobacco_status": None, "rate": 0.11, "rate_unit": "per_1000_monthly",
        "provenance": {
            "filename": "filing.pdf", "page": 4, "sourceType": "filed_pdf",
            "reviewStatus": "accepted",
        },
    }]
    view = _slot(artifact, "coi")
    assert view["status"] == "filed_accepted"
    assert view["provenance"][0]["filename"] == "filing.pdf"
    assert view["provenance"][0]["page"] == 4


def test_slot_status_synthetic() -> None:
    artifact = _empty_artifact()
    artifact["usable"]["surrender"] = [{
        "duration": 1, "issue_age": None, "sex": None,
        "charge": 0.1, "charge_unit": "percent_account_value",
        "provenance": {"sourceType": "ai_synthetic"},
    }]
    artifact["synthetic"] = {"surrender": {"sourceType": "ai_synthetic", "rowCount": 1}}
    assert _slot(artifact, "surrender")["status"] == "synthetic"


def test_slot_status_workspace_table_from_document_csv() -> None:
    artifact = _empty_artifact()
    artifact["usable"]["fees"] = [{
        "component": "policy_fee", "duration": None, "premium_mode": None,
        "amount": 60, "fee_unit": "annual_fixed",
        "provenance": {"filename": "rates.csv", "sheet": "CSV", "row": 2},
    }]
    view = _slot(artifact, "fees")
    assert view["status"] == "workspace_table"
    assert view["editedInWorkspace"] is False


def test_gap_annotation_maps_to_slots() -> None:
    items = [
        {"id": "missing_coi_table", "title": "COI table missing"},
        {"id": "surrender_schedule_placeholder", "title": "Surrender schedule placeholder"},
        {"id": "policy_admin_fee_missing", "title": "Policy/admin fee missing"},
        {"id": "something_else", "title": "Unmapped"},
    ]
    annotated = panel.annotate_gap_items(items)
    assert annotated[0]["slotId"] == "coi"
    assert annotated[1]["slotId"] == "surrender"
    assert annotated[2]["slotId"] == "fees"
    assert "slotId" not in annotated[3]
    # Input items are not mutated.
    assert "slotId" not in items[0]


# ---------------------------------------------------------------------------
# Edit validation — the ingestion validators
# ---------------------------------------------------------------------------


def test_validate_table_rows_rejects_bad_unit_with_validator_message() -> None:
    with pytest.raises(ValueError, match="unsupported COI rate_unit"):
        panel.validate_table_rows("coi", [
            {"duration": 1, "rate": 0.2, "rate_unit": "per_1000_weekly"},
        ])


def test_validate_table_rows_rejects_incomplete_surrender_schedule() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        panel.validate_table_rows("surrender", [
            {"duration": 1, "charge": 0.08, "charge_unit": "percent_face"},
            {"duration": 3, "charge": 0.05, "charge_unit": "percent_face"},
        ])


def test_validate_table_rows_rejects_duplicate_selectors() -> None:
    with pytest.raises(ValueError, match="duplicate coi selector"):
        panel.validate_table_rows("coi", [
            {"duration": 1, "rate": 0.2, "rate_unit": "per_1000_monthly"},
            {"duration": 1, "rate": 0.3, "rate_unit": "per_1000_monthly"},
        ])


def test_parse_table_bytes_with_and_without_mechanic_column() -> None:
    with_mechanic = (
        b"mechanic,duration,rate,rate_unit\n"
        b"coi,1,0.20,per_1000_monthly\n"
        b"surrender,1,0.08,percent_face\n"
    )
    rows = panel.parse_table_bytes("coi", "rates.csv", with_mechanic)
    assert len(rows) == 1 and rows[0]["rate"] == 0.20

    without_mechanic = b"duration,rate,rate_unit\n1,0.20,per_1000_monthly\n2,0.21,per_1000_monthly\n"
    rows = panel.parse_table_bytes("coi", "coi.csv", without_mechanic)
    assert [row["duration"] for row in rows] == [1, 2]


def test_parse_table_bytes_rejects_invalid_rows() -> None:
    bad = b"duration,charge,charge_unit\n1,8,percent\n"
    with pytest.raises(ValueError, match="unsupported surrender charge_unit"):
        panel.parse_table_bytes("surrender", "surrender.csv", bad)


# ---------------------------------------------------------------------------
# Edit persistence, change log, staleness
# ---------------------------------------------------------------------------


def test_fee_edit_persists_change_and_marks_stale(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store)

    response = server.api_edit_mechanics_slot(
        workspace_id, "fees",
        server.MechanicsSlotEditRequest(rows=[
            {"component": "policy_fee", "amount": 240, "fee_unit": "annual_fixed"},
        ]),
    )

    assert response["projectionStale"] is True
    assert response["slot"]["status"] == "workspace_table"
    assert response["slot"]["editedInWorkspace"] is True
    assert response["change"]["slot"] == "fees"
    assert response["change"]["who"] == "workspace_user"
    assert response["change"]["prior"]["status"] == "missing"
    assert response["change"]["new"]["rowCount"] == 1

    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    assert artifact is not None
    fee_rows = artifact["usable"]["fees"]
    assert fee_rows[0]["amount"] == 240
    assert fee_rows[0]["provenance"]["sourceType"] == "workspace_edit"
    assert artifact["workspaceEdits"]["fees"]["rows"] == fee_rows

    changes = workspace_store.load_workspace_mechanics_changes(workspace_id)
    assert len(changes) == 1
    assert changes[0]["id"] == response["change"]["id"]

    ws = workspace_store.get_workspace(workspace_id)
    assert ws is not None and ws["projection_stale"] is True
    assert ws["projection_stale_slots"] == ["fees"]


def test_invalid_edit_writes_nothing(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store)
    before = workspace_store.load_workspace_executable_mechanics(workspace_id)

    with pytest.raises(HTTPException) as excinfo:
        server.api_edit_mechanics_slot(
            workspace_id, "coi",
            server.MechanicsSlotEditRequest(rows=[
                {"duration": 1, "rate": 0.2, "rate_unit": "per_1000_weekly"},
            ]),
        )
    assert excinfo.value.status_code == 400
    assert "unsupported COI rate_unit" in str(excinfo.value.detail)

    after = workspace_store.load_workspace_executable_mechanics(workspace_id)
    assert after == before
    assert workspace_store.load_workspace_mechanics_changes(workspace_id) == []
    ws = workspace_store.get_workspace(workspace_id)
    assert not (ws or {}).get("projection_stale")


def test_history_is_newest_first_and_panel_carries_it(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store)
    server.api_edit_mechanics_slot(
        workspace_id, "fees",
        server.MechanicsSlotEditRequest(rows=[
            {"component": "policy_fee", "amount": 100, "fee_unit": "annual_fixed"},
        ]),
    )
    server.api_edit_mechanics_slot(
        workspace_id, "nar",
        server.MechanicsSlotEditRequest(factor=1.05),
    )

    history = server.api_get_mechanics_panel_history(workspace_id)
    # Phase 7: loading the pre-doctrine artifact also records the
    # one-time equation migration in the same audit history.
    user_changes = [c for c in history["changes"] if c["kind"] != "equations_migrated"]
    assert [c["slot"] for c in user_changes] == ["nar", "fees"]
    assert any(c["kind"] == "equations_migrated" for c in history["changes"])
    assert user_changes[0]["new"] == {"factor": 1.05}
    assert user_changes[1]["prior"]["status"] == "missing"

    panel_payload = server.api_get_mechanics_panel(workspace_id)
    panel_user_changes = [c for c in panel_payload["changeLog"] if c["kind"] != "equations_migrated"]
    assert [c["slot"] for c in panel_user_changes] == ["nar", "fees"]
    assert panel_payload["projectionStale"] is True
    assert panel_payload["projectionStaleSlots"] == ["fees", "nar"]


def test_nar_factor_edit_validation(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store)
    with pytest.raises(HTTPException) as excinfo:
        server.api_edit_mechanics_slot(
            workspace_id, "nar", server.MechanicsSlotEditRequest(factor=7.5)
        )
    assert excinfo.value.status_code == 400
    assert "at most 2.0" in str(excinfo.value.detail)

    response = server.api_edit_mechanics_slot(
        workspace_id, "nar", server.MechanicsSlotEditRequest(factor=1.02)
    )
    assert response["slot"]["value"] == 1.02
    assert response["slot"]["status"] == "workspace_table"


def test_unknown_and_display_only_slots_are_rejected(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store)
    with pytest.raises(HTTPException) as excinfo:
        server.api_edit_mechanics_slot(
            workspace_id, "bogus", server.MechanicsSlotEditRequest(rows=[])
        )
    assert excinfo.value.status_code == 404

    with pytest.raises(HTTPException) as excinfo:
        server.api_edit_mechanics_slot(
            workspace_id, "crediting", server.MechanicsSlotEditRequest(factor=0.03)
        )
    assert excinfo.value.status_code == 400

    with pytest.raises(HTTPException) as excinfo:
        server.api_get_mechanics_panel("ws-missing")
    assert excinfo.value.status_code == 404


def test_panel_shape_and_gap_mapping(store: FakeMinio) -> None:
    snapshot = {
        "product": {"code": "ICC18 P18PR UL", "type": "UL"},
        "gaps": {"items": [
            {"id": "policy_admin_fee_missing", "title": "Policy/admin fee missing"},
            {"id": "missing_coi_table", "title": "COI table missing"},
        ], "warnings": [], "notes": []},
    }
    workspace_id = _seed_workspace(store, snapshot=snapshot)

    payload = server.api_get_mechanics_panel(workspace_id)
    assert [slot["id"] for slot in payload["slots"]] == [
        "coi", "surrender", "fees", "nar", "corridor", "crediting",
    ]
    gaps = {gap["id"]: gap for gap in payload["gaps"]}
    assert gaps["policy_admin_fee_missing"]["slotId"] == "fees"
    assert gaps["missing_coi_table"]["slotId"] == "coi"
    crediting = next(slot for slot in payload["slots"] if slot["id"] == "crediting")
    assert crediting["editable"] is False
    assert payload["projectionStale"] is False


def test_analysis_update_clears_staleness(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store)
    server.api_edit_mechanics_slot(
        workspace_id, "fees",
        server.MechanicsSlotEditRequest(rows=[
            {"component": "policy_fee", "amount": 100, "fee_unit": "annual_fixed"},
        ]),
    )
    ws = workspace_store.get_workspace(workspace_id)
    assert ws is not None and ws["projection_stale"] is True

    workspace_store.update_workspace_analysis(
        workspace_id, status="analyzed", snapshot={"product": {"code": "X"}}
    )
    ws = workspace_store.get_workspace(workspace_id)
    assert ws is not None and ws["projection_stale"] is False
    assert ws["projection_stale_slots"] == []


# ---------------------------------------------------------------------------
# API-level exit flow: edits flow into the Phase 1 ledger
# ---------------------------------------------------------------------------


def _projection(workspace_id: str) -> dict:
    return server.api_workspace_projection(
        workspace_id, server.WorkspaceProjectionRequest()
    )


def _ledger_component(projection: dict, component_id: str) -> dict:
    row = projection["ledger"]["rows"][0]
    return next(c for c in row["components"] if c["id"] == component_id)


def test_fee_edit_flows_into_the_ledger(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store)

    baseline = _projection(workspace_id)["illustration"]
    baseline_fee = baseline["ledger"]["rows"][0]["policyFee"]

    server.api_edit_mechanics_slot(
        workspace_id, "fees",
        server.MechanicsSlotEditRequest(rows=[
            {"component": "policy_fee", "amount": 240, "fee_unit": "annual_fixed"},
        ]),
    )

    projection = _projection(workspace_id)["illustration"]
    ledger_row = projection["ledger"]["rows"][0]
    assert ledger_row["policyFee"] == pytest.approx(240.0)
    assert ledger_row["policyFee"] != pytest.approx(baseline_fee)
    fee_component = _ledger_component(projection, "policy_fee")
    assert fee_component["basis"] == "workspace_table"
    assert fee_component["amount"] == pytest.approx(240.0)


def test_pasted_coi_table_is_in_force_in_the_ledger(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store)
    csv_text = "duration,rate,rate_unit\n" + "\n".join(
        f"{duration},{0.10 + duration * 0.001:.3f},per_1000_monthly"
        for duration in range(1, 31)
    )

    response = server.api_edit_mechanics_slot(
        workspace_id, "coi",
        server.MechanicsSlotEditRequest(csvText=csv_text),
    )
    assert response["slot"]["status"] == "workspace_table"
    assert response["slot"]["rowCount"] == 30

    projection = _projection(workspace_id)["illustration"]
    coi_table = projection["rateTables"]["coi"]
    assert coi_table["status"] == "workspace_table"
    assert coi_table["rowCount"] == 30
    assert coi_table["rows"][0]["rate"] == pytest.approx(0.101)
    assert coi_table["rows"][29]["rate"] == pytest.approx(0.130)

    coi_component = _ledger_component(projection, "coi")
    assert coi_component["basis"] == "workspace_table"
    # Rate x net amount at risk, not the flat placeholder.
    assert "net amount at risk" in coi_component["formula"].lower()


def test_edits_survive_an_analysis_rerun(store: FakeMinio, monkeypatch) -> None:
    workspace_id = _seed_workspace(store)
    workspace_store.create_workspace_document(
        workspace_id=workspace_id,
        description="filing.pdf",
        object_path=f"workspaces/{workspace_id}/filing.pdf",
    )
    server.api_edit_mechanics_slot(
        workspace_id, "fees",
        server.MechanicsSlotEditRequest(rows=[
            {"component": "policy_fee", "amount": 240, "fee_unit": "annual_fixed"},
        ]),
    )

    # Simulate the re-run: analysis rebuilds the artifact from documents
    # (fresh, edit-free) — the stored workspace edits must be re-applied.
    monkeypatch.setattr(
        server, "_extract_workspace_executable_mechanics",
        lambda docs: _empty_artifact(),
    )
    monkeypatch.setattr(
        server, "build_product_workspace_snapshot",
        lambda code: {
            "product": {"name": "Promise UL", "code": "ICC18 P18PR UL", "type": "UL"},
            "complianceMatrix": {"requirements": [], "summary": {}},
            "readinessDashboard": {},
        },
    )
    monkeypatch.setattr(server, "_apply_workspace_document_evidence", lambda snap, docs: snap)
    monkeypatch.setattr(
        server, "_build_ul_projection_view",
        lambda code, req: ({"mechanicsExecution": {}}, {}, [], [], []),
    )
    import actuarypoc.extract.slice_pipeline as slice_pipeline

    def _slice_boom(**kwargs):
        raise RuntimeError("slice stage disabled in this test")

    monkeypatch.setattr(slice_pipeline, "run_workspace_slice_extraction", _slice_boom)

    result = server.api_workspace_analyze(workspace_id)
    assert result["workspace"]["status"] == "analyzed"

    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    assert artifact is not None
    assert artifact["usable"]["fees"][0]["amount"] == 240
    assert artifact["workspaceEdits"]["fees"]["rows"][0]["amount"] == 240

    ws = workspace_store.get_workspace(workspace_id)
    assert ws is not None and ws["projection_stale"] is False
