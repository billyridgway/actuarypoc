"""Unification revamp — one approval reality.

Covers the revamp's contracts (docs/unification-revamp.md):

* the coverage check names, up front, an in-force table that cannot
  serve the scenario's underwriting class — and stays silent for a
  duration-only (wildcard) table;
* a run's per-year failures collapse into one named failure with
  its year range, and the run summary names a coverage failure
  once (reason ``table_coverage``);
* filed-table proposals are ONE choice per alternative group, with
  options + a computed diff; confirming requires the choice;
* accepting an alternative supersedes the previously accepted one;
  identical rows dedupe with both provenances kept;
* counts say what they count (rows + duration coverage);
* the panel payload and the equations payload agree — both read
  the same artifact store.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from actuarypoc.domain import equations as _eq
from actuarypoc.extract import workspace_mechanics_proposals as proposals
from actuarypoc.extract.workspace_mechanics_corrections import describe_current
from actuarypoc.extract.workspace_mechanics_panel import (
    SLOT_BY_ID,
    build_slot_view,
)
from actuarypoc.extract.workspace_ul_mechanics import (
    accept_filed_mechanic,
    candidate_diff,
    dedupe_rows,
    rows_coverage_text,
)
from actuarypoc.storage import workspace_store
from actuarypoc.ui import server


def _filed_row(mechanic: str, **fields) -> dict:
    row = dict(fields)
    row["provenance"] = {
        "sourceType": "filed_pdf", "reviewStatus": "review_required",
        "filename": "specimen.pdf", "page": 4,
    }
    return row


def _candidate(mechanic: str, candidate_id: str, rows: list, *, filename="specimen.pdf", page=4) -> dict:
    return {
        "id": candidate_id, "mechanic": mechanic, "filename": filename,
        "page": page, "tableHeading": "Table", "rowCount": len(rows),
        "valueBasis": "guaranteed_maximum", "reviewStatus": "review_required",
        "rows": rows,
    }


def _coi_rows(tobacco: str, *, durations=range(1, 4), rate=0.19) -> list:
    return [
        _filed_row(
            "coi", duration=d, attained_age=None, sex="M",
            risk_class="Standard", tobacco_status=tobacco,
            rate=rate, rate_unit="per_1000_monthly",
        )
        for d in durations
    ]


# ---------------------------------------------------------------------------
# Coverage: the matcher verdict + the pre-run naming
# ---------------------------------------------------------------------------


def test_coverage_silent_for_duration_only_table_and_selectorless_scenario():
    # Hand-computed: every row's selectors are null (wildcards), so
    # the table serves any scenario — no issue may be named.
    executable = {"coi": [
        {"duration": d, "attained_age": None, "sex": None,
         "risk_class": None, "tobacco_status": None,
         "rate": 0.19, "rate_unit": "per_1000_monthly"}
        for d in range(1, 4)
    ]}
    assert server._selector_match_issues(executable, {"age": 45}) == []


def test_coverage_names_missing_selectors_for_class_specific_table():
    # The saved-scenario shape: the in-force table carries only
    # Tobacco rows; the scenario specifies no class at all.
    executable = {"coi": _coi_rows("Tobacco")}
    issues = server._selector_match_issues(executable, {"age": 45})
    assert len(issues) == 1
    issue = issues[0]
    assert issue["mechanic"] == "coi"
    assert set(issue["missingSelectors"]) == {"sex", "risk_class", "tobacco_status"}
    assert issue["tableSelectors"]["tobacco_status"] == ["Tobacco"]
    assert issue["years"] == list(range(1, 31))
    assert "Tobacco" in issue["message"]


def test_coverage_names_value_mismatch_when_scenario_specifies_another_class():
    executable = {"coi": _coi_rows("Tobacco")}
    issues = server._selector_match_issues(executable, {
        "age": 45, "sex": "M", "riskClass": "Standard",
        "tobaccoStatus": "Non-Tobacco",
    })
    assert len(issues) == 1
    assert issues[0]["missingSelectors"] == []
    assert "Non-Tobacco" in issues[0]["message"]


def test_run_names_coverage_failure_once_with_collapsed_years():
    config = server.load_ul_runtime_config("ICC18 P18PR UL")
    config.executable_mechanics = {"coi": [
        {key: value for key, value in row.items() if key != "provenance"}
        for row in _coi_rows("Tobacco")
    ]}
    projection, _ = server._run_ul_projection(
        request={"age": 45, "faceAmount": 100_000},
        config=config, horizon_years=3,
    )
    execution = projection["mechanicsExecution"]["coi_charge"]
    assert execution["failedYears"] == [1, 2, 3]
    # 3 per-year failures, ONE collapsed entry spanning years 1–3.
    assert len(execution["failureSummary"]) == 1
    assert execution["failureSummary"][0]["yearRange"] == "1–3"
    assert execution["failureSummary"][0]["years"] == [1, 2, 3]
    missing = {m["mechanic"]: m for m in projection["missingMechanics"]}
    assert missing["coi_charge"]["reason"] == "table_coverage"
    assert "Tobacco" in missing["coi_charge"]["detail"]
    assert projection["coverageIssues"][0]["mechanic"] == "coi"


# ---------------------------------------------------------------------------
# Candidates as choices
# ---------------------------------------------------------------------------


def _two_specimen_artifact() -> dict:
    return {
        "version": 1,
        "mechanics": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
        "warnings": [], "usable": {}, "status": {},
        "candidates": {
            "coi": [
                _candidate("coi", "cand-base", _coi_rows("Non-Tobacco"), filename="base.pdf"),
                _candidate("coi", "cand-nic", _coi_rows("Tobacco"), filename="nicotine.pdf"),
            ],
            "surrender": [], "fees": [], "nar_factors": [], "corridor": [],
        },
    }


def test_two_specimens_become_two_independent_approvals():
    """Selector-slice model (Oct 27, 2026): the revamp's one-choice-
    per-group model forced the user to amputate half the table's
    coverage — the base specimen and the Nicotine specimen are
    complementary slices (Non-Tobacco vs Tobacco rows), not rival
    versions.  Each pending candidate is its own approval proposal,
    labeled with the coverage it adds."""

    found = proposals.generate_proposals(_two_specimen_artifact(), [])
    assert len(found) == 2
    assert all(p["kind"] == "filed_table_choice" for p in found)
    by_candidate = {p["candidateId"]: p for p in found}
    assert set(by_candidate) == {"cand-base", "cand-nic"}
    for candidate_id, tobacco in (("cand-base", "Non-Tobacco"), ("cand-nic", "Tobacco")):
        proposal = by_candidate[candidate_id]
        assert [o["candidateId"] for o in proposal["options"]] == [candidate_id]
        assert proposal["options"][0]["selectors"]["tobacco_status"] == [tobacco]
        assert "conflict" not in proposal


def test_each_slice_confirms_independently_and_coverage_unions():
    artifact = _two_specimen_artifact()
    nic = next(
        p for p in proposals.generate_proposals(artifact, [])
        if p["candidateId"] == "cand-nic"
    )
    outcome = proposals.apply_proposal(
        artifact, nic, workspace_id="ws-t", who="eddy", at="2026-10-27T00:00:00Z",
    )
    usable = outcome["artifact"]["usable"]["coi"]
    assert len(usable) == 3
    assert {row["tobacco_status"] for row in usable} == {"Tobacco"}
    # The other slice is still its own pending approval — accepting
    # one slice never decides the other.
    remaining = proposals.generate_proposals(outcome["artifact"], [])
    assert [p["candidateId"] for p in remaining] == ["cand-base"]
    outcome = proposals.apply_proposal(
        outcome["artifact"], remaining[0], workspace_id="ws-t", who="eddy",
        at="2026-10-27T00:01:00Z",
    )
    assert len(outcome["artifact"]["usable"]["coi"]) == 6
    assert proposals.generate_proposals(outcome["artifact"], []) == []


def test_fee_component_slices_are_independent_and_conflicts_surface_on_accept():
    fees_a = [_filed_row("fees", component="monthly_expense", duration=1,
                         premium_mode=None, amount=18.95, fee_unit="monthly_fixed")]
    fees_b = [_filed_row("fees", component="monthly_expense", duration=1,
                         premium_mode=None, amount=27.40, fee_unit="monthly_fixed")]
    fees_admin = [_filed_row("fees", component="administrative", duration=None,
                             premium_mode=None, amount=8.0, fee_unit="monthly_fixed")]
    artifact = _two_specimen_artifact()
    artifact["candidates"]["coi"] = []
    artifact["candidates"]["fees"] = [
        _candidate("fees", "cand-exp-a", fees_a, filename="base.pdf", page=5),
        _candidate("fees", "cand-exp-b", fees_b, filename="nicotine.pdf", page=5),
        _candidate("fees", "cand-admin", fees_admin, filename="base.pdf", page=2),
    ]
    # Nothing accepted yet: three independent approvals.
    found = proposals.generate_proposals(artifact, [])
    assert len(found) == 3
    assert all(len(p["options"]) == 1 for p in found)
    # Accept the first expense slice; the second prices the SAME
    # selector differently (18.95 vs 27.40) — a genuine conflict,
    # surfaced as a named two-option choice, never a silent merge.
    accepted = accept_filed_mechanic(artifact, "fees", candidate_id="cand-exp-a")
    found = proposals.generate_proposals(accepted, [])
    conflict = next(p for p in found if p.get("conflict"))
    assert conflict["conflict"]["differingRows"] == 1
    assert [o["candidateId"] for o in conflict["options"]] == ["cand-exp-a", "cand-exp-b"]
    assert conflict["options"][0]["inForce"] is True


def test_accepting_both_specimens_unions_their_coverage():
    artifact = _two_specimen_artifact()
    accepted = accept_filed_mechanic(artifact, "coi", candidate_id="cand-base")
    assert {r["tobacco_status"] for r in accepted["usable"]["coi"]} == {"Non-Tobacco"}
    both = accept_filed_mechanic(accepted, "coi", candidate_id="cand-nic")
    assert len(both["usable"]["coi"]) == 6
    assert {r["tobacco_status"] for r in both["usable"]["coi"]} == {
        "Non-Tobacco", "Tobacco",
    }
    states = {c["id"]: c["reviewStatus"] for c in both["candidates"]["coi"]}
    assert states == {"cand-base": "accepted", "cand-nic": "accepted"}


def test_identical_rows_dedupe_keeping_both_provenances():
    rows_a = [_filed_row("fees", component="policy_fee", duration=None,
                         premium_mode=None, amount=100.0, fee_unit="annual_fixed")]
    rows_b = [_filed_row("fees", component="policy_fee", duration=None,
                         premium_mode=None, amount=100.0, fee_unit="annual_fixed")]
    rows_b[0]["provenance"] = {**rows_b[0]["provenance"], "filename": "other.pdf", "page": 9}
    merged = dedupe_rows(rows_a + rows_b, "fees")
    assert len(merged) == 1
    also = merged[0]["provenance"]["alsoFiledAs"]
    assert len(also) == 1 and also[0]["filename"] == "other.pdf"

    diff = candidate_diff(rows_a, rows_b, "fees")
    assert diff["identicalRows"] == 1 and diff["differingRows"] == 0


# ---------------------------------------------------------------------------
# Counts + provenance honesty + panel candidates
# ---------------------------------------------------------------------------


def test_counts_say_rows_and_duration_coverage():
    rows = [{"duration": d} for d in range(1, 122)]
    assert rows_coverage_text(rows) == "121 rows covering durations 1–121"
    assert rows_coverage_text(rows + rows) == "242 rows across durations 1–121"
    assert rows_coverage_text([{"duration": 1}]) == "1 row at duration 1"
    assert rows_coverage_text([{"factor": 1.05}]) == "1 row"


def test_describe_current_never_sums_rows_as_years():
    artifact = _two_specimen_artifact()
    artifact["candidates"]["fees"] = [_candidate("fees", "cand-fees", [
        _filed_row("fees", component="monthly_expense", duration=d,
                   premium_mode=None, amount=18.95, fee_unit="monthly_fixed")
        for d in range(1, 4)
    ], page=5)]
    accepted = accept_filed_mechanic(artifact, "fees", candidate_id="cand-fees")
    description = describe_current(accepted, SLOT_BY_ID["fees"])["description"]
    assert "over 3 years" not in description
    assert "3 rows covering durations 1–3" in description


def test_slot_view_lists_candidates_as_one_choice():
    artifact = accept_filed_mechanic(_two_specimen_artifact(), "coi", candidate_id="cand-base")
    view = build_slot_view(artifact, SLOT_BY_ID["coi"])
    assert view["coverageText"] == "3 rows covering durations 1–3"
    by_id = {c["id"]: c for c in view["candidates"]}
    assert by_id["cand-base"]["inForce"] is True
    assert by_id["cand-nic"]["inForce"] is False
    assert by_id["cand-nic"]["diffVsReference"]["onlyInA"] == 3


def test_crediting_slot_is_labeled_an_assumption():
    snapshot = {"assumptions": {"provenance": [
        {"name": "Guaranteed credited rate", "value": 0.02, "source": "runtime_config"},
    ]}}
    view = build_slot_view({}, SLOT_BY_ID["crediting"], snapshot)
    assert view["value"] == 0.02
    assert view["sourceKind"] == "assumption"
    assert "not read from the filing" in view["sourceLabel"]


# ---------------------------------------------------------------------------
# One approval reality at the API surface
# ---------------------------------------------------------------------------


class _MissingObject(Exception):
    code = "NoSuchKey"


class _FakeMinio:
    def __init__(self) -> None:
        self.objects: dict = {}

    def put_object(self, bucket, key, data, length, content_type=None):
        self.objects[key] = data.read() if hasattr(data, "read") else data
        return SimpleNamespace(etag="test")

    def get_object(self, bucket, key):
        if key not in self.objects:
            raise _MissingObject(key)
        payload = self.objects[key]
        return SimpleNamespace(read=lambda: payload, close=lambda: None, release_conn=lambda: None)

    def list_objects(self, bucket, *, prefix, recursive):
        return [
            SimpleNamespace(object_name=key)
            for key in sorted(self.objects) if key.startswith(prefix)
        ]

    def remove_object(self, bucket, key) -> None:
        self.objects.pop(key, None)


@pytest.fixture()
def store(monkeypatch: pytest.MonkeyPatch) -> _FakeMinio:
    client = _FakeMinio()
    monkeypatch.setattr(workspace_store, "get_minio_client", lambda: client)
    monkeypatch.setattr(workspace_store, "get_bucket_name", lambda: "test")
    monkeypatch.setattr(workspace_store, "ensure_bucket", lambda client: None)
    monkeypatch.setattr(server, "_load_workspace_slices", lambda workspace_id: [])
    return client


def test_panel_and_equations_payloads_agree_and_slots_carry_used_by(store):
    from fastapi.testclient import TestClient

    artifact = {
        "version": 1,
        "mechanics": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
        "warnings": [],
        "usable": {
            "coi": [
                {key: value for key, value in row.items() if key != "provenance"}
                | {"provenance": {"sourceType": "filed_pdf", "reviewStatus": "accepted",
                                  "filename": "specimen.pdf", "page": 4}}
                for row in _coi_rows("Tobacco")
            ],
            "nar_factors": [{"factor": 1.05, "provenance": {
                "sourceType": "filed_pdf", "reviewStatus": "accepted",
                "filename": "specimen.pdf", "page": 6}}],
        },
        "candidates": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
        "status": {"coi": "executable", "nar_factors": "executable"},
        "equations": [{
            "id": "eq-coi-1", "mechanic": "coi_charge", "version": 1,
            "state": "approved", "timing": "beginning",
            "body": _eq.coi_body_for_unit("per_1000_monthly"),
            "rendering": "COI charge = net amount at risk / 1000 × COI table rate",
            "source": {"kind": "filed_table"},
            "approval": {"by": "eddy", "at": "2026-10-27T00:00:00Z"},
            "conflict": None, "createdAt": "2026-10-27T00:00:00Z",
            "updatedAt": "2026-10-27T00:00:00Z",
        }, {
            # The NAR definition in force is the plain one — it does
            # NOT read the nar_factors table, orphaning it.
            "id": "eq-nar-1", "mechanic": "nar_definition", "version": 1,
            "state": "approved", "timing": None,
            "body": _eq.nar_body("unadjusted"),
            "rendering": "Net amount at risk = death benefit − account value",
            "source": {"kind": "document"},
            "approval": {"by": "eddy", "at": "2026-10-27T00:00:00Z"},
            "conflict": None, "createdAt": "2026-10-27T00:00:00Z",
            "updatedAt": "2026-10-27T00:00:00Z",
        }],
    }
    ws = workspace_store.create_workspace()
    workspace_store.store_workspace_executable_mechanics(ws["id"], artifact)
    client = TestClient(server.app)

    panel = client.get(f"/api/workspaces/{ws['id']}/mechanics-panel").json()
    equations = client.get(f"/api/workspaces/{ws['id']}/equations").json()

    # The panel's embedded equation state and the equations endpoint
    # are two reads of the same store: they cannot disagree.
    for mechanic, view in equations["mechanics"].items():
        panel_view = panel["equations"]["mechanics"][mechanic]
        assert bool(panel_view["inForce"]) == bool(view["inForce"]), mechanic
        if view["inForce"]:
            assert panel_view["inForce"]["id"] == view["inForce"]["id"]

    slots = {slot["id"]: slot for slot in panel["slots"]}
    assert slots["coi"]["usedByEquations"] == ["coi_charge"]
    assert slots["coi"]["unusedByEquations"] is False
    # The orphan: a table in force that no approved equation reads
    # says so on its own card.
    assert slots["nar"]["unusedByEquations"] is True
    assert slots["nar"]["usedByEquations"] == []
