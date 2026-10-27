from __future__ import annotations

"""Phase 3 (corrections in plain English): the "This should be…" layer.

Covers the plan's Phase 3 exit flows at API level:

* (a) a filed per-$1,000-face surrender schedule is corrected to a
  percentage of account value with grading — the confirm-back restates
  it in actuarial language, nothing applies unconfirmed, and after the
  correction the Phase 1 ledger shows the new basis labelled
  ``corrected`` with the correction cited, while the filed rows are
  preserved inside the correction record and the change history;
* (b) a COI timing correction changes the ledger's COI charge and its
  derivation;
* (c) a free-text correction with no known mapping is captured as a
  product note / feature request — visible in the panel — and never
  dropped or silently applied.

Plus precedence (corrections beat workspace edits, synthetic tables and
placeholders), the NAR-definition correction, conservative free-text
suggestions, and survival of corrections across an analysis re-run.
"""

import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from actuarypoc.extract import workspace_mechanics_corrections as corrections
from actuarypoc.extract import workspace_mechanics_panel as panel
from actuarypoc.storage import workspace_store
from actuarypoc.ui import server


# ---------------------------------------------------------------------------
# Fake MinIO (same pattern as the Phase 2 panel tests)
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


# ---------------------------------------------------------------------------
# Artifact builders
# ---------------------------------------------------------------------------


def _empty_artifact() -> dict:
    return {
        "version": 1,
        "mechanics": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
        "warnings": [],
        "usable": {},
        "candidates": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
        "status": {},
    }


def _filed_surrender_rows() -> list[dict]:
    """The Promise UL shape: surrender charged per $1,000 of face."""

    return [
        {
            "duration": duration,
            "issue_age": None,
            "sex": None,
            "charge": 12.50,
            "charge_unit": "per_1000_face",
            "provenance": {
                "filename": "filing.pdf",
                "page": 3,
                "sourceType": "filed_pdf",
                "reviewStatus": "accepted",
            },
        }
        for duration in range(1, 21)
    ]


def _filed_coi_rows() -> list[dict]:
    return [
        {
            "duration": duration,
            "attained_age": None,
            "sex": None,
            "risk_class": None,
            "tobacco_status": None,
            "rate": 0.11,
            "rate_unit": "per_1000_monthly",
            "provenance": {
                "filename": "filing.pdf",
                "page": 4,
                "sourceType": "filed_pdf",
                "reviewStatus": "accepted",
            },
        }
        for duration in range(1, 31)
    ]


def _seed_workspace(store: FakeMinio, artifact: dict) -> str:
    ws = workspace_store.create_workspace()
    workspace_id = ws["id"]
    workspace_store.store_workspace_executable_mechanics(workspace_id, artifact)
    return workspace_id


def _artifact_with_filed_surrender() -> dict:
    artifact = _empty_artifact()
    artifact["usable"]["surrender"] = _filed_surrender_rows()
    artifact["status"]["surrender"] = "filed_accepted"
    return artifact


def _artifact_with_filed_coi() -> dict:
    artifact = _empty_artifact()
    artifact["usable"]["coi"] = _filed_coi_rows()
    artifact["status"]["coi"] = "filed_accepted"
    return artifact


def _projection(workspace_id: str) -> dict:
    return server.api_workspace_projection(
        workspace_id, server.WorkspaceProjectionRequest()
    )


def _ledger_component(projection: dict, component_id: str, year: int = 0) -> dict:
    row = projection["ledger"]["rows"][year]
    return next(c for c in row["components"] if c["id"] == component_id)


def _surrender_spec(**overrides) -> server.MechanicsCorrectionRequest:
    payload = {
        "variant": "surrender_basis",
        "params": {"basis": "percent_account_value", "percent": 0.08, "gradingYears": 10},
        "who": "eddy",
    }
    payload.update(overrides)
    return server.MechanicsCorrectionRequest(**payload)


# ---------------------------------------------------------------------------
# Validation + suggestions (module level)
# ---------------------------------------------------------------------------


def test_spec_validation_rejects_bad_variants() -> None:
    slot = panel.SLOT_BY_ID["surrender"]
    artifact = _artifact_with_filed_surrender()
    with pytest.raises(ValueError):
        corrections.preview_correction(
            artifact, slot,
            {"variant": "surrender_basis", "params": {"basis": "percent_of_premium", "percent": 0.1, "gradingYears": 10}},
            who="eddy", at="2026-10-25T00:00:00Z",
        )
    with pytest.raises(ValueError):
        corrections.preview_correction(
            artifact, slot,
            {"variant": "surrender_basis", "params": {"basis": "percent_account_value", "percent": 1.5, "gradingYears": 10}},
            who="eddy", at="2026-10-25T00:00:00Z",
        )
    with pytest.raises(ValueError):
        corrections.preview_correction(
            artifact, slot,
            {"variant": "surrender_basis", "params": {"basis": "percent_account_value", "percent": 0.08, "gradingYears": 0}},
            who="eddy", at="2026-10-25T00:00:00Z",
        )
    # A variant on the wrong slot is rejected, not reinterpreted.
    with pytest.raises(ValueError):
        corrections.preview_correction(
            artifact, panel.SLOT_BY_ID["coi"],
            {"variant": "surrender_basis", "params": {"basis": "percent_account_value", "percent": 0.08, "gradingYears": 10}},
            who="eddy", at="2026-10-25T00:00:00Z",
        )
    with pytest.raises(ValueError):
        corrections.preview_correction(
            artifact, panel.SLOT_BY_ID["coi"],
            {"variant": "coi_timing", "params": {"timing": "quarterly"}},
            who="eddy", at="2026-10-25T00:00:00Z",
        )


def test_suggest_variant_is_conservative() -> None:
    surrender = panel.SLOT_BY_ID["surrender"]
    suggestion = corrections.suggest_variant(
        surrender, "This should be 8% of account value, grading to zero over 10 years"
    )
    assert suggestion is not None
    assert suggestion["variant"] == "surrender_basis"
    assert suggestion["params"]["basis"] == "percent_account_value"
    assert suggestion["params"]["percent"] == pytest.approx(0.08)
    assert suggestion["params"]["gradingYears"] == 10
    # No clear mapping -> None (captured as a note, never guessed at).
    assert corrections.suggest_variant(
        surrender, "the charge should feel fairer to loyal policyholders"
    ) is None
    coi = panel.SLOT_BY_ID["coi"]
    assert corrections.suggest_variant(coi, "deduct it after interest is credited") == {
        "variant": "coi_timing", "params": {"timing": "end"},
    }
    nar = panel.SLOT_BY_ID["nar"]
    assert corrections.suggest_variant(nar, "use the death benefit with no factor") == {
        "variant": "nar_definition", "params": {"definition": "unadjusted"},
    }


# ---------------------------------------------------------------------------
# Exit flow (a): filed per-$1,000-face surrender -> % of account value
# ---------------------------------------------------------------------------


EXPECTED_CONFIRM_BACK = (
    "Surrender charge: was $12.50 per $1,000 of face amount in year 1 — "
    "20 rows covering durations 1–20 in force, as filed in filing.pdf "
    "(p. 3) (accepted); now 8% of account value, grading to 0 over 10 years."
)


def test_preview_confirm_back_is_actuarial_and_writes_nothing(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _artifact_with_filed_surrender())

    preview = server.api_preview_mechanics_correction(
        workspace_id, "surrender", _surrender_spec()
    )
    assert preview["mapped"] is True
    assert preview["confirmBack"] == EXPECTED_CONFIRM_BACK
    assert preview["replaces"]["status"] == "filed_accepted"

    # A preview persists nothing.
    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    assert not (artifact.get("corrections") or {})
    assert artifact["usable"]["surrender"][0]["charge_unit"] == "per_1000_face"


def test_apply_requires_confirmation(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _artifact_with_filed_surrender())

    with pytest.raises(HTTPException) as excinfo:
        server.api_apply_mechanics_correction(
            workspace_id, "surrender", _surrender_spec(confirmed=False)
        )
    assert excinfo.value.status_code == 400
    detail = excinfo.value.detail
    assert detail["code"] == "confirmation_required"
    assert detail["confirmBack"] == EXPECTED_CONFIRM_BACK

    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    assert not (artifact.get("corrections") or {})


def test_filed_override_persists_with_provenance_and_history(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _artifact_with_filed_surrender())

    response = server.api_apply_mechanics_correction(
        workspace_id, "surrender",
        _surrender_spec(
            confirmed=True,
            text="Surrender should be a percentage of the account value, not per thousand of face.",
        ),
    )
    assert response["mapped"] is True
    assert response["projectionStale"] is True
    assert response["correction"]["confirmBack"] == EXPECTED_CONFIRM_BACK
    assert response["slot"]["status"] == "corrected"
    assert response["slot"]["statusLabel"] == "Corrected"
    assert response["slot"]["correction"]["replacedWasFiled"] is True

    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    record = artifact["corrections"]["surrender"]
    assert record["who"] == "eddy"
    assert record["text"].startswith("Surrender should be a percentage")
    # The filed value it replaced is preserved in the record.
    assert record["replaces"]["status"] == "filed_accepted"
    assert record["replaces"]["rows"][0]["charge"] == pytest.approx(12.50)
    assert record["replaces"]["rows"][0]["provenance"]["sourceType"] == "filed_pdf"

    # Phase 7: the correction puts an approved EQUATION in force — 8%
    # of the (ending) account value grading to 0 over 10 years.  The
    # filed table rows stay as data underneath; the equation governs.
    from actuarypoc.extract import workspace_equations as ws_equations

    in_force = ws_equations.in_force(artifact, "surrender_charge")
    assert in_force is not None
    assert in_force["id"] == record["equationId"]
    assert in_force["source"]["kind"] == "correction"
    assert in_force["source"]["correction"]["confirmBack"] == EXPECTED_CONFIRM_BACK
    assert in_force["approval"]["by"] == "eddy"
    assert "ending account value" in in_force["rendering"]
    assert artifact["usable"]["surrender"][0]["charge"] == pytest.approx(12.50)
    assert artifact["status"]["surrender"] == "corrected"

    # The change history says loudly that a filed value was overridden.
    changes = workspace_store.load_workspace_mechanics_changes(workspace_id)
    correction_changes = [c for c in changes if c["kind"] == "correction"]
    assert len(correction_changes) == 1
    assert EXPECTED_CONFIRM_BACK in correction_changes[0]["summary"]
    assert "filed value it replaces is preserved" in correction_changes[0]["summary"]

    ws = workspace_store.get_workspace(workspace_id)
    assert ws is not None and ws["projection_stale"] is True


def test_ledger_reflects_the_surrender_correction(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _artifact_with_filed_surrender())

    baseline = _projection(workspace_id)["illustration"]
    baseline_row = baseline["ledger"]["rows"][0]
    # Filed basis: (100,000 / 1,000) x $12.50 = $1,250.
    assert baseline_row["surrenderCharge"] == pytest.approx(1250.0)
    baseline_component = _ledger_component(baseline, "surrender_charge")
    assert baseline_component["basis"] == "filed"

    server.api_apply_mechanics_correction(
        workspace_id, "surrender", _surrender_spec(confirmed=True)
    )

    projection = _projection(workspace_id)["illustration"]
    row = projection["ledger"]["rows"][0]
    # Corrected basis: 8% of the ending account value.
    assert row["surrenderCharge"] == pytest.approx(0.08 * row["endingValue"])
    assert row["surrenderCharge"] != pytest.approx(1250.0)

    component = _ledger_component(projection, "surrender_charge")
    assert component["basis"] == "corrected"
    assert component["basisLabel"] == "Corrected"
    assert "ending account value" in component["formula"]
    labels = {item["label"]: item["value"] for item in component["inputs"]}
    assert labels["Correction applied"] == EXPECTED_CONFIRM_BACK
    assert labels["Corrected by"] == "eddy"
    assert component["source"]["sourceType"] == "correction"

    # The rate tables in force label the corrected mechanic too: the
    # table data is unchanged, the governing equation is the correction.
    surrender_table = projection["rateTables"]["surrender"]
    assert surrender_table["status"] == "corrected"
    assert surrender_table["equation"]["sourceKind"] == "correction"


def test_correction_over_missing_and_over_edit(store: FakeMinio) -> None:
    # Over nothing in force: the confirm-back names the absence.
    workspace_id = _seed_workspace(store, _empty_artifact())
    preview = server.api_preview_mechanics_correction(
        workspace_id, "surrender", _surrender_spec()
    )
    assert "no surrender schedule is in force" in preview["confirmBack"]
    assert "no surrender charge is calculated" in preview["confirmBack"]
    server.api_apply_mechanics_correction(
        workspace_id, "surrender", _surrender_spec(confirmed=True)
    )
    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    assert artifact["corrections"]["surrender"]["replaces"]["status"] == "missing"

    # Over a Phase 2 workspace edit: the correction's equation wins,
    # immediately and after the edit/correction re-application order a
    # re-run performs.  The edit's rows remain as data underneath.
    workspace_id = _seed_workspace(store, _empty_artifact())
    server.api_edit_mechanics_slot(
        workspace_id, "surrender",
        server.MechanicsSlotEditRequest(rows=[
            {"duration": 1, "charge": 0.2, "charge_unit": "percent_face"},
            {"duration": 2, "charge": 0.2, "charge_unit": "percent_face"},
        ]),
    )
    server.api_apply_mechanics_correction(
        workspace_id, "surrender", _surrender_spec(confirmed=True)
    )
    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    assert artifact["corrections"]["surrender"]["replaces"]["status"] == "workspace_table"

    from actuarypoc.extract import workspace_equations as ws_equations

    in_force = ws_equations.in_force(artifact, "surrender_charge")
    assert in_force is not None
    assert in_force["source"]["kind"] == "correction"

    fresh = _empty_artifact()
    fresh = panel.reapply_workspace_edits(fresh, artifact.get("workspaceEdits"))
    fresh = corrections.reapply_corrections(fresh, artifact.get("corrections"))
    fresh_in_force = ws_equations.in_force(fresh, "surrender_charge")
    assert fresh_in_force is not None
    assert fresh_in_force["source"]["kind"] == "correction"
    assert "ending account value" in fresh_in_force["rendering"]
    assert fresh["usable"]["surrender"][0]["charge_unit"] == "percent_face"


# ---------------------------------------------------------------------------
# Exit flow (b): COI timing correction changes the ledger's COI
# ---------------------------------------------------------------------------


def test_coi_timing_correction_changes_ledger_coi(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _artifact_with_filed_coi())

    baseline = _projection(workspace_id)["illustration"]
    baseline_coi = baseline["ledger"]["rows"][0]["coiCharge"]
    assert baseline_coi > 0
    baseline_component = _ledger_component(baseline, "coi")
    assert baseline_component["basis"] == "filed"
    assert "beginning of each month" in baseline_component["formula"]

    preview = server.api_preview_mechanics_correction(
        workspace_id, "coi",
        server.MechanicsCorrectionRequest(
            variant="coi_timing", params={"timing": "end"}, who="eddy"
        ),
    )
    assert preview["confirmBack"] == (
        "COI charge timing: was deducted at the beginning of each month, "
        "before interest is credited; now deducted at the end of each "
        "month, after interest is credited, with the net amount at risk "
        "measured on the post-interest value."
    )

    server.api_apply_mechanics_correction(
        workspace_id, "coi",
        server.MechanicsCorrectionRequest(
            variant="coi_timing", params={"timing": "end"}, who="eddy", confirmed=True
        ),
    )

    projection = _projection(workspace_id)["illustration"]
    corrected_coi = projection["ledger"]["rows"][0]["coiCharge"]
    # End-of-month deduction moves the charge. In this scenario the
    # death benefit is the face amount (the corridor does not bind), so
    # measuring the NAR after interest — on a higher account value —
    # shrinks the net amount at risk and the charge dips slightly.
    assert corrected_coi != pytest.approx(baseline_coi)
    assert corrected_coi < baseline_coi

    component = _ledger_component(projection, "coi")
    assert component["basis"] == "corrected"
    assert component["basisLabel"] == "Corrected"
    assert "end of each month" in component["formula"]
    labels = {item["label"]: item["value"] for item in component["inputs"]}
    assert "Correction applied" in labels
    assert labels["Corrected by"] == "eddy"


def test_middle_timing_and_correction_supersession(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _artifact_with_filed_coi())

    def year_one_coi() -> float:
        return _projection(workspace_id)["illustration"]["ledger"]["rows"][0]["coiCharge"]

    def apply_timing(timing: str) -> dict:
        return server.api_apply_mechanics_correction(
            workspace_id, "coi",
            server.MechanicsCorrectionRequest(
                variant="coi_timing", params={"timing": timing},
                who="eddy", confirmed=True,
            ),
        )

    beginning_coi = year_one_coi()
    end_response = apply_timing("end")
    end_coi = year_one_coi()
    assert end_coi != pytest.approx(beginning_coi)

    middle_response = apply_timing("middle")
    middle_coi = year_one_coi()
    # Middle produces its own distinct charge. (Its ordering against
    # "beginning" is a second-order effect — the half left invested
    # earns interest inside the measurement month while the re-measured
    # NAR shrinks — so no universal ordering is asserted; what the
    # correction must do is change the charge deterministically and say
    # so in the derivation, which is asserted below.)
    assert middle_coi != pytest.approx(beginning_coi)
    assert middle_coi != pytest.approx(end_coi)

    # The second correction supersedes the first, and says so.
    assert middle_response["correction"]["id"] != end_response["correction"]["id"]
    changes = workspace_store.load_workspace_mechanics_changes(workspace_id)
    summaries = [c["summary"] for c in changes if c["kind"] == "correction"]
    assert len(summaries) == 2
    assert "supersedes the earlier correction" in summaries[-1]

    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    settings = corrections.executable_settings(artifact)
    assert settings["coiTiming"] == "middle"

    component = _ledger_component(_projection(workspace_id)["illustration"], "coi")
    assert component["basis"] == "corrected"
    assert "middle of each month" in component["formula"]


def test_nar_definition_correction_changes_coi_and_keeps_filed_factor(store: FakeMinio) -> None:
    artifact = _artifact_with_filed_coi()
    artifact["usable"]["nar_factors"] = [{
        "factor": 1.05,
        "provenance": {
            "filename": "filing.pdf", "page": 6,
            "sourceType": "filed_pdf", "reviewStatus": "accepted",
        },
    }]
    artifact["status"]["nar_factors"] = "filed_accepted"
    workspace_id = _seed_workspace(store, artifact)

    baseline = _projection(workspace_id)["illustration"]
    baseline_coi = baseline["ledger"]["rows"][0]["coiCharge"]

    server.api_apply_mechanics_correction(
        workspace_id, "nar",
        server.MechanicsCorrectionRequest(
            variant="nar_definition", params={"definition": "unadjusted"},
            who="eddy", confirmed=True,
        ),
    )

    projection = _projection(workspace_id)["illustration"]
    corrected_coi = projection["ledger"]["rows"][0]["coiCharge"]
    # Without the 1.05 divisor the net amount at risk — and so the COI —
    # is larger.
    assert corrected_coi > baseline_coi

    component = _ledger_component(projection, "coi")
    assert component["basis"] == "corrected"
    inputs = {item["label"]: item["value"] for item in component["inputs"]}
    assert inputs["NAR factor"] == pytest.approx(1.0)
    assert inputs["Filed NAR factor (not applied)"] == pytest.approx(1.05)
    assert "not applied" in component["formula"]


# ---------------------------------------------------------------------------
# Exit flow (c): unmapped free text is captured, never dropped
# ---------------------------------------------------------------------------


UNMAPPED_TEXT = "the surrender charge should reward policyholders who keep the policy a long time"


def test_unmapped_correction_lands_as_a_feature_request(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _artifact_with_filed_surrender())
    baseline = _projection(workspace_id)["illustration"]
    baseline_charge = baseline["ledger"]["rows"][0]["surrenderCharge"]

    preview = server.api_preview_mechanics_correction(
        workspace_id, "surrender",
        server.MechanicsCorrectionRequest(text=UNMAPPED_TEXT, who="eddy"),
    )
    assert preview["mapped"] is False
    assert preview["suggested"] is False
    assert UNMAPPED_TEXT in preview["confirmBack"]

    response = server.api_apply_mechanics_correction(
        workspace_id, "surrender",
        server.MechanicsCorrectionRequest(text=UNMAPPED_TEXT, who="eddy"),
    )
    assert response["mapped"] is False
    assert response["projectionStale"] is False
    request = response["featureRequest"]
    assert request["capabilityId"] == "mechanics_correction"
    assert UNMAPPED_TEXT in request["description"]

    # Visible in the panel as a correction request, and in the history.
    payload = server.api_get_mechanics_panel(workspace_id)
    assert [r["id"] for r in payload["correctionRequests"]] == [request["id"]]
    note_changes = [c for c in payload["changeLog"] if c["kind"] == "correction_note"]
    assert len(note_changes) == 1
    assert UNMAPPED_TEXT in note_changes[0]["summary"]

    # Nothing was applied: no correction record, projection unchanged.
    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    assert not (artifact.get("corrections") or {})
    after = _projection(workspace_id)["illustration"]
    assert after["ledger"]["rows"][0]["surrenderCharge"] == pytest.approx(baseline_charge)


def test_text_suggestion_is_offered_then_applied_on_confirm(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _artifact_with_filed_coi())
    text = "the COI should be deducted after interest is credited"

    preview = server.api_preview_mechanics_correction(
        workspace_id, "coi", server.MechanicsCorrectionRequest(text=text, who="eddy")
    )
    assert preview["mapped"] is False
    assert preview["suggested"] is True
    assert preview["suggestion"]["params"]["timing"] == "end"
    assert "end of each month" in preview["confirmBack"]

    # The suggestion alone applies nothing.
    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    assert not (artifact.get("corrections") or {})

    response = server.api_apply_mechanics_correction(
        workspace_id, "coi",
        server.MechanicsCorrectionRequest(
            variant="coi_timing", params={"timing": "end"},
            text=text, who="eddy", confirmed=True,
        ),
    )
    assert response["correction"]["variant"] == "coi_timing"
    assert response["correction"]["text"] == text
    assert response["slot"]["status"] == "corrected"


def test_correction_routes_reject_empty_and_unknown(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _artifact_with_filed_surrender())
    with pytest.raises(HTTPException) as excinfo:
        server.api_preview_mechanics_correction(
            workspace_id, "surrender", server.MechanicsCorrectionRequest()
        )
    assert excinfo.value.status_code == 400
    with pytest.raises(HTTPException) as excinfo:
        server.api_apply_mechanics_correction(
            "ws-missing", "surrender", _surrender_spec(confirmed=True)
        )
    assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException) as excinfo:
        server.api_apply_mechanics_correction(
            workspace_id, "bogus", _surrender_spec(confirmed=True)
        )
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# The same exit flows over real HTTP (TestClient through the ASGI app)
# ---------------------------------------------------------------------------


def test_correction_flows_over_http(store: FakeMinio) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(server.app)
    workspace_id = _seed_workspace(store, _artifact_with_filed_surrender())
    base = f"/api/workspaces/{workspace_id}/mechanics-panel"

    preview = client.post(
        f"{base}/surrender/corrections/preview",
        json={
            "variant": "surrender_basis",
            "params": {"basis": "percent_account_value", "percent": 0.08, "gradingYears": 10},
            "who": "eddy",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["confirmBack"] == EXPECTED_CONFIRM_BACK

    unconfirmed = client.post(
        f"{base}/surrender/corrections",
        json={
            "variant": "surrender_basis",
            "params": {"basis": "percent_account_value", "percent": 0.08, "gradingYears": 10},
            "who": "eddy",
        },
    )
    assert unconfirmed.status_code == 400
    assert unconfirmed.json()["detail"]["code"] == "confirmation_required"

    applied = client.post(
        f"{base}/surrender/corrections",
        json={
            "variant": "surrender_basis",
            "params": {"basis": "percent_account_value", "percent": 0.08, "gradingYears": 10},
            "who": "eddy",
            "confirmed": True,
        },
    )
    assert applied.status_code == 200
    assert applied.json()["slot"]["status"] == "corrected"

    panel_payload = client.get(base)
    assert panel_payload.status_code == 200
    surrender_slot = next(
        s for s in panel_payload.json()["slots"] if s["id"] == "surrender"
    )
    assert surrender_slot["status"] == "corrected"
    assert surrender_slot["correction"]["confirmBack"] == EXPECTED_CONFIRM_BACK
    assert surrender_slot["correction"]["replacedWasFiled"] is True
    assert surrender_slot["correctionVariants"][0]["id"] == "surrender_basis"

    projection = client.post(
        f"/api/workspaces/{workspace_id}/projection", json={}
    )
    assert projection.status_code == 200
    component = _ledger_component(projection.json()["illustration"], "surrender_charge")
    assert component["basis"] == "corrected"

    note = client.post(
        f"{base}/surrender/corrections",
        json={"text": UNMAPPED_TEXT, "who": "eddy"},
    )
    assert note.status_code == 200
    assert note.json()["mapped"] is False

    panel_after = client.get(base).json()
    assert len(panel_after["correctionRequests"]) == 1
    assert panel_after["correctionRequests"][0]["capabilityId"] == "mechanics_correction"


# ---------------------------------------------------------------------------
# Corrections survive an analysis re-run
# ---------------------------------------------------------------------------


def test_corrections_survive_an_analysis_rerun(store: FakeMinio, monkeypatch) -> None:
    workspace_id = _seed_workspace(store, _artifact_with_filed_surrender())
    workspace_store.create_workspace_document(
        workspace_id=workspace_id,
        description="filing.pdf",
        object_path=f"workspaces/{workspace_id}/filing.pdf",
    )
    server.api_apply_mechanics_correction(
        workspace_id, "surrender", _surrender_spec(confirmed=True)
    )

    # The re-run rebuilds the artifact from the documents (the filed
    # schedule comes back); the stored correction must be re-applied.
    monkeypatch.setattr(
        server, "_extract_workspace_executable_mechanics",
        lambda docs: _artifact_with_filed_surrender(),
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
    record = artifact["corrections"]["surrender"]
    assert record["confirmBack"] == EXPECTED_CONFIRM_BACK
    # The re-run rebuilt the filed table; the correction survives as
    # the approved equation in force, not as rewritten rows.
    assert artifact["usable"]["surrender"][0]["charge_unit"] == "per_1000_face"
    from actuarypoc.extract import workspace_equations as ws_equations

    in_force = ws_equations.in_force(artifact, "surrender_charge")
    assert in_force is not None
    assert in_force["source"]["kind"] == "correction"
    # The executable view carries the correction into the next run.
    view = corrections.executable_mechanics_view(artifact)
    assert view["_equations"]["surrender_charge"]["id"] == in_force["id"]
