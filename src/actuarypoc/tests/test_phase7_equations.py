from __future__ import annotations

"""Phase 7 (the equation doctrine): the only equations that execute are
document-derived and human-approved, or actuary-authored — plus the
universal identities every document assumes.

Covers:
* the formula language: evaluator correctness per construct
  (hand-computed) and rejection of invalid equations with specific
  messages at validation time;
* harvesting over an authored filing-style specimen that STATES its
  calculations in prose (the repo's Promise UL materials gate their
  specimen tables on a specimen marker and state no prose rules, so
  the prose fixture below is authored for this test and says so);
* approval gating over real HTTP: unapproved equations never execute,
  an unconfirmed approve is a 400 carrying the rendering to confirm;
* conflict surfacing: a stated equation that disagrees with the one in
  force is flagged — neither silently wins;
* the NO-NET PROOF: a workspace with no approved COI equation projects
  with NO COI charge and an explicit incompleteness flag — the retired
  flat placeholder figure is unreachable;
* the end-to-end acceptance: prose-stated COI timing + NAR definition
  + surrender equation -> harvest -> approve -> projection whose
  year-1 COI and surrender match a hand recursion of the STATED
  equations, cited in the ledger; then an actuary-authored edit
  changes the output by exactly the stated amount.
"""

import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from actuarypoc.domain import equations as eq
from actuarypoc.extract import workspace_equations as weq
from actuarypoc.storage import workspace_store
from actuarypoc.ui import server


# ---------------------------------------------------------------------------
# Fake MinIO (same pattern as the Phase 2/3 tests)
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


def _seed_workspace(store: FakeMinio, artifact: dict) -> str:
    ws = workspace_store.create_workspace()
    workspace_id = ws["id"]
    workspace_store.store_workspace_executable_mechanics(workspace_id, artifact)
    return workspace_id


def _projection(workspace_id: str) -> dict:
    return server.api_workspace_projection(
        workspace_id, server.WorkspaceProjectionRequest()
    )["illustration"]


def _ledger_component(projection: dict, component_id: str, year: int = 0) -> dict:
    row = projection["ledger"]["rows"][year]
    return next(c for c in row["components"] if c["id"] == component_id)


# ---------------------------------------------------------------------------
# The formula language: hand-computed evaluation per construct
# ---------------------------------------------------------------------------


def _values(**overrides) -> dict:
    base = {
        "duration": 3,
        "month_in_year": 6,
        "attained_age": 45,
        "issue_age": 42,
        "face_amount": 100_000.0,
        "account_value": 12_000.0,
        "death_benefit": 100_000.0,
        "nar": 88_000.0,
        "premium_due": 300.0,
        "payment_due": 300.0,
        "guaranteed_rate": 0.03,
    }
    base.update(overrides)
    return base


def test_evaluator_arithmetic_and_functions() -> None:
    body = {"mul": [{"qty": "nar"}, {"div": [{"const": 0.24}, {"const": 12}]}]}
    assert eq.evaluate(body, _values(), {}) == pytest.approx(88_000 * 0.02)
    capped = {"min": [{"qty": "account_value"}, {"max": [{"const": 500}, {"const": 250}]}]}
    assert eq.evaluate(capped, _values(), {}) == 500
    powered = {"pow": [{"add": [{"const": 1}, {"qty": "guaranteed_rate"}]}, {"div": [{"const": 1}, {"const": 12}]}]}
    assert eq.evaluate(powered, _values(), {}) == pytest.approx(1.03 ** (1 / 12))


def test_evaluator_conditionals_and_bands() -> None:
    body = {
        "if": {
            "cond": {"cmp": ["<=", {"qty": "duration"}, {"const": 10}]},
            "then": {"mul": [{"qty": "account_value"}, {"const": 0.09}]},
            "else": {"const": 0},
        }
    }
    assert eq.evaluate(body, _values(), {}) == pytest.approx(1_080.0)
    assert eq.evaluate(body, _values(duration=11), {}) == 0.0
    banded = {
        "bands": [
            {"from": 1, "to": 5, "value": {"const": 10}},
            {"from": 6, "to": None, "value": {"const": 4}},
        ]
    }
    assert eq.evaluate(banded, _values(duration=3), {}) == 10
    assert eq.evaluate(banded, _values(duration=9), {}) == 4
    with pytest.raises(eq.Unevaluable):
        eq.evaluate(banded, _values(duration=0), {})


def test_evaluator_lookups_and_rows_sum() -> None:
    tables = {
        "coi": [
            {"duration": 3, "attained_age": 45, "rate": 0.19, "rate_unit": "per_1000_monthly"},
            {"duration": 3, "attained_age": 46, "rate": 0.21, "rate_unit": "per_1000_monthly"},
        ],
        "fees": [
            {"duration": 3, "amount": 5.0, "fee_unit": "monthly_fixed"},
            {"duration": 3, "amount": 0.5, "fee_unit": "per_1000_face_annual"},
        ],
    }
    lookup = {"lookup": {"table": "coi", "field": "rate"}}
    assert eq.evaluate(lookup, _values(), tables) == pytest.approx(0.19)
    with_default = {"lookup": {"table": "coi", "field": "rate", "default": {"const": 1}}}
    assert eq.evaluate(with_default, _values(duration=99), tables) == 1
    with pytest.raises(eq.Unevaluable):
        eq.evaluate(lookup, _values(duration=99), tables)
    fees = {
        "rows_sum": {
            "table": "fees",
            "expr": {
                "if": {
                    "cond": {"cmp": ["==", {"qty": "row_unit"}, {"str": "per_1000_face_annual"}]},
                    "then": {"div": [{"mul": [{"qty": "row_amount"}, {"qty": "face_amount"}]}, {"const": 12000}]},
                    "else": {"qty": "row_amount"},
                }
            },
        }
    }
    # 5.00 fixed + 0.50 x 100,000 / 12,000 = 5.00 + 4.1667
    assert eq.evaluate(fees, _values(), tables) == pytest.approx(5.0 + 0.5 * 100_000 / 12_000)


def test_validation_rejects_invalid_equations_with_specific_messages() -> None:
    unknown_qty = eq.validate_equation("coi_charge", {"qty": "mortality_table"})
    assert unknown_qty and "Unknown quantity" in unknown_qty[0] and "mortality_table" in unknown_qty[0]
    unknown_table = eq.validate_equation(
        "coi_charge", {"lookup": {"table": "mortality", "field": "rate"}}
    )
    assert unknown_table and "Unknown table" in unknown_table[0]
    wrong_field = eq.validate_equation(
        "coi_charge", {"lookup": {"table": "coi", "field": "charge"}}
    )
    assert wrong_field and "value field is 'rate'" in wrong_field[0]
    bad_op = eq.validate_equation("coi_charge", {"eval": [{"const": 1}]})
    assert bad_op and "Unknown formula node" in bad_op[0]
    type_error = eq.validate_equation(
        "coi_charge", {"add": [{"qty": "nar"}, {"str": "x"}]}
    )
    assert type_error
    bad_mechanic = eq.validate_equation("not_a_mechanic", {"const": 1})
    assert bad_mechanic and "mechanic" in bad_mechanic[0].lower()


def test_rendering_is_canonical_actuarial_language() -> None:
    body = {"div": [{"mul": [{"qty": "nar"}, {"lookup": {"table": "coi", "field": "rate"}}]}, {"const": 1000}]}
    text = eq.render_equation(body, "coi_charge")
    assert "net amount at risk" in text and "COI table rate" in text
    timed = eq.render_with_timing(body, "end")
    assert "deducted at the end of each month" in timed


# ---------------------------------------------------------------------------
# Harvesting: authored prose fixture + model-reading discipline
# ---------------------------------------------------------------------------

# Authored filing-style specimen. The repo's Promise UL materials gate
# their specimen tables on a specimen marker and state no prose rules;
# these statements are written for this test in filing language.
NAR_TEXT = (
    "Section 4.2 — Net Amount at Risk. The net amount at risk is the "
    "death benefit payable less the account value on the monthly "
    "processing date."
)
COI_TIMING_TEXT = (
    "Section 5.1 — Cost of Insurance Deduction. The cost of insurance "
    "charge is deducted in arrears, at the end of each policy month, "
    "after interest has been credited for that month."
)
SURRENDER_TEXT = (
    "Section 6.3 — Surrender Charge. The surrender charge is 9% of the "
    "account value at the time of surrender, grading to zero over "
    "12 years."
)


def _slices() -> list[dict]:
    return [
        {"filename": "specimen-filing.pdf", "page_start": 5, "page_offsets": [], "text": NAR_TEXT},
        {"filename": "specimen-filing.pdf", "page_start": 7, "page_offsets": [], "text": COI_TIMING_TEXT},
        {"filename": "specimen-filing.pdf", "page_start": 9, "page_offsets": [], "text": SURRENDER_TEXT},
    ]


def _filed_coi_artifact() -> dict:
    artifact = _empty_artifact()
    artifact["usable"]["coi"] = [
        {
            "duration": duration,
            "issue_age": None,
            "attained_age": None,
            "sex": None,
            "risk_class": None,
            "tobacco_status": None,
            "rate": 0.19,
            "rate_unit": "per_1000_monthly",
            "provenance": {
                "filename": "specimen-filing.pdf",
                "page": 12,
                "sourceType": "filed_pdf",
                "reviewStatus": "accepted",
            },
        }
        for duration in range(1, 31)
    ]
    artifact["status"]["coi"] = "filed_accepted"
    return artifact


def test_deterministic_harvest_structures_the_stated_calculations() -> None:
    candidates = weq.deterministic_harvest(_slices())
    by_mechanic = {c["mechanic"]: c for c in candidates}
    assert set(by_mechanic) == {"nar_definition", "coi_charge", "surrender_charge"}
    assert by_mechanic["nar_definition"]["statement"] in NAR_TEXT
    assert by_mechanic["nar_definition"]["page"] == 5
    assert by_mechanic["coi_charge"]["timing"] == "end"
    assert by_mechanic["coi_charge"]["page"] == 7
    surrender = by_mechanic["surrender_charge"]
    assert surrender["page"] == 9 and "9%" in surrender["statement"]
    rendering = eq.render_equation(surrender["body"], "surrender_charge")
    assert "account value" in rendering and "0.09" in rendering


def test_model_reading_with_unverifiable_quote_becomes_unmapped_not_dropped() -> None:
    def fake_caller(slices):
        return {
            "readings": [
                {
                    "mechanic": "crediting",
                    "statement": "Interest is credited at the moon rate.",  # not in the text
                    "body": {"const": 0},
                },
                {
                    "mechanic": "premium_load",
                    "statement": "Loads are deducted from each premium as received.",  # not in the text
                    "body": {"qty": "definitely_not_a_quantity"},
                },
            ]
        }

    artifact = _empty_artifact()
    result = weq.harvest_equations(artifact, _slices(), at="2026-10-26T00:00:00Z", model_caller=fake_caller)
    created_records = [
        r for r in weq.records(result["artifact"]) if r["id"] in result["created"]
    ]
    unmapped = [r for r in created_records if r["body"] is None]
    # The two model readings, plus the deterministic COI timing
    # statement, which has no COI body anywhere to attach to.
    assert len(unmapped) == 3
    assert all(r["state"] == "unmapped" for r in unmapped)
    model_unmapped = [r for r in unmapped if r["mechanic"] in ("crediting", "premium_load")]
    assert len(model_unmapped) == 2
    assert all(r["source"]["statement"] is None for r in model_unmapped)
    # The model's claim survives inside the note — never presented as
    # the filing's own words, never silently dropped.
    assert any("moon rate" in (r["source"]["note"] or "") for r in unmapped)


def test_harvest_never_auto_approves() -> None:
    artifact = _empty_artifact()
    result = weq.harvest_equations(artifact, _slices(), at="2026-10-26T00:00:00Z")
    assert result["created"]
    created_records = [
        r for r in weq.records(result["artifact"]) if r["id"] in result["created"]
    ]
    assert created_records and all(
        r["state"] in ("pending", "unmapped") for r in created_records
    )
    assert weq.in_force_map(result["artifact"]) == {}


# ---------------------------------------------------------------------------
# The NO-NET PROOF
# ---------------------------------------------------------------------------


def test_no_approved_coi_equation_means_no_coi_charge(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _empty_artifact())
    projection = _projection(workspace_id)
    rows = projection["rows"]
    assert rows, "the roll-forward skeleton still runs"
    assert all(row["coiCharge"] == 0.0 for row in rows)
    assert all(row["policyFee"] == 0.0 for row in rows)
    assert all(row["guaranteedInterest"] == 0.0 for row in rows)
    assert all(row["deathBenefit"] is None for row in rows)
    assert projection["incomplete"] is True
    missing = {m["mechanic"] for m in projection["missingMechanics"]}
    assert missing == set(eq.MECHANICS)
    # The retired flat placeholder ($1,000/yr at the canned 1% of face)
    # must be unreachable: no row carries it, and no source module
    # still names the retired calculation.
    assert all(row["coiCharge"] != 1000.0 for row in rows)
    component = _ledger_component(projection, "coi")
    assert component["basis"] == "missing"
    assert component["amount"] == 0.0
    assert "no approved COI charge equation" in component["formula"]


def test_no_net_at_source_level() -> None:
    import pathlib

    package = pathlib.Path(__file__).resolve().parents[1]
    assert not (package / "domain" / "rule_bank.py").exists()
    server_text = (package / "ui" / "server.py").read_text()
    assert "coi_placeholder_annual" not in server_text
    assert "SWITCHES" not in server_text


# ---------------------------------------------------------------------------
# Over real HTTP: harvest -> approve -> execute -> cite -> edit
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(store: FakeMinio, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(server, "_load_workspace_slices", lambda workspace_id: _slices())
    return TestClient(server.app)


def _approve(client: TestClient, workspace_id: str, mechanic: str, record_id: str, **kw):
    payload = {"equationId": record_id, "confirmed": True, "who": "eddy"}
    payload.update(kw)
    return client.post(
        f"/api/workspaces/{workspace_id}/equations/{mechanic}/approve", json=payload
    )


def _harvest_and_get(client: TestClient, workspace_id: str) -> dict:
    response = client.post(f"/api/workspaces/{workspace_id}/equations/harvest", json={})
    assert response.status_code == 200, response.text
    return response.json()


def _pending(view: dict, mechanic: str) -> dict:
    records = view["mechanics"][mechanic]["records"]
    pending = [r for r in records if r["state"] == "pending"]
    assert pending, f"no pending record for {mechanic}: {records}"
    return pending[0]


def test_end_to_end_stated_equations_drive_the_projection(
    client: TestClient, store: FakeMinio
) -> None:
    workspace_id = _seed_workspace(store, _filed_coi_artifact())

    # Before harvest: the migration materialized the filed table's
    # equations (beginning timing, factor-adjusted NAR) — the specimen
    # still projects, with honest provenance.
    before = client.get(f"/api/workspaces/{workspace_id}/equations").json()
    coi_before = before["mechanics"]["coi_charge"]["inForce"]
    assert coi_before is not None
    assert coi_before["approval"]["by"] == "pre-doctrine migration"

    view = _harvest_and_get(client, workspace_id)
    # Proposals carry the filing's verbatim words and pages.
    nar_pending = _pending(view, "nar_definition")
    assert nar_pending["source"]["page"] == 5
    assert "less the account value" in nar_pending["source"]["statement"]
    surrender_pending = _pending(view, "surrender_charge")
    assert surrender_pending["source"]["page"] == 9
    coi_pending = _pending(view, "coi_charge")
    assert coi_pending["source"]["page"] == 7 and coi_pending["timing"] == "end"

    # CONFLICT: the stated NAR definition disagrees with the in-force
    # (migrated, factor-adjusted) one — flagged, and the in-force
    # equation is unchanged until a human approves.
    assert nar_pending["conflict"]
    assert nar_pending["conflict"]["withEquationId"] == (
        view["mechanics"]["nar_definition"]["inForce"]["id"]
    )
    conflicts = {(c["mechanic"]) for c in view["conflicts"]}
    assert "nar_definition" in conflicts
    assert view["mechanics"]["nar_definition"]["inForce"]["id"] != nar_pending["id"]

    # Unconfirmed approval is rejected and carries the rendering.
    refused = _approve(client, workspace_id, "nar_definition", nar_pending["id"], confirmed=False)
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "confirmation_required"
    assert "account value" in refused.json()["detail"]["rendering"]
    still = client.get(f"/api/workspaces/{workspace_id}/equations/nar_definition").json()
    assert still["inForce"]["id"] != nar_pending["id"]

    # Approve all three stated equations.
    for mechanic, record in (
        ("nar_definition", nar_pending),
        ("surrender_charge", surrender_pending),
        ("coi_charge", coi_pending),
    ):
        response = _approve(client, workspace_id, mechanic, record["id"])
        assert response.status_code == 200, response.text
        in_force = response.json()["equations"]["mechanics"][mechanic]["inForce"]
        assert in_force["id"] == record["id"]
        assert in_force["approval"]["by"] == "eddy"

    # Hand recursion of the STATED equations for policy year 1:
    # monthly, COI deducted at month end after interest; NAR = death
    # benefit - account value (unadjusted, as stated); surrender =
    # 9% of account value grading to zero over 12 years.  The scenario
    # givens (annual premium, guaranteed rate) are read from the
    # projection's own disclosed inputs.
    projection_peek = _projection(workspace_id)
    inputs = {i["id"]: i["value"] for i in projection_peek["inputs"]}
    annual_premium = float(inputs["premium"])
    guaranteed = float(inputs["guaranteed_rate"])
    monthly_rate = (1 + guaranteed) ** (1 / 12) - 1
    balance = 0.0
    coi_year = 0.0
    for month in range(12):
        if month == 0:
            balance += annual_premium  # annual mode: the year's premium lands first
        interest = balance * monthly_rate
        balance += interest
        nar = max(100_000.0 - balance, 0.0)
        coi = nar / 1000.0 * 0.19
        balance -= coi
        coi_year += coi
    # Grading convention (the ported Phase 3 shape): the factor is
    # (G + 1 - duration) / G, so year 1 carries the full 9% and the
    # charge reaches zero after year 12.
    expected_surrender = balance * 0.09 * (12 + 1 - 1) / 12

    projection = _projection(workspace_id)
    row = projection["rows"][0]
    assert row["coiCharge"] == pytest.approx(coi_year, rel=1e-9)
    assert row["surrenderCharge"] == pytest.approx(expected_surrender, rel=1e-9)
    assert projection["incomplete"] is False or {
        m["mechanic"] for m in projection["missingMechanics"]
    } <= {"premium_load", "policy_fees"}

    # The ledger cites the approved equations that ran.
    coi_component = _ledger_component(projection, "coi")
    assert coi_component["amount"] == pytest.approx(coi_year, rel=1e-9)
    assert coi_component["equation"]["mechanic"] == "coi_charge"
    assert coi_component["equation"]["sourcePage"] == 7
    assert coi_component["equation"]["approvedBy"] == "eddy"
    nar_component = _ledger_component(projection, "net_amount_at_risk")
    assert "account value" in nar_component["formula"]
    surrender_component = _ledger_component(projection, "surrender_charge")
    assert surrender_component["equation"]["sourcePage"] == 9
    assert surrender_component["amount"] == pytest.approx(expected_surrender, rel=1e-9)

    # The applied-equations record (what validation packs persist).
    applied = {c["mechanic"] for c in projection["appliedEquations"]}
    assert {"coi_charge", "nar_definition", "surrender_charge", "crediting"} <= applied


def test_actuary_authored_edit_changes_output_by_the_stated_amount(
    client: TestClient, store: FakeMinio
) -> None:
    workspace_id = _seed_workspace(store, _filed_coi_artifact())
    view = _harvest_and_get(client, workspace_id)
    surrender_pending = _pending(view, "surrender_charge")
    assert _approve(client, workspace_id, "surrender_charge", surrender_pending["id"]).status_code == 200
    baseline = _projection(workspace_id)["rows"][0]
    assert baseline["surrenderCharge"] > 0

    new_body = {
        "if": {
            "cond": {"cmp": ["<=", {"qty": "duration"}, {"const": 12}]},
            "then": {"mul": [{"qty": "account_value"}, {"const": 0.05}]},
            "else": {"const": 0},
        }
    }
    # Unconfirmed PUT is a preview only — nothing is written.
    preview = client.put(
        f"/api/workspaces/{workspace_id}/equations/surrender_charge",
        json={"body": new_body, "confirmed": False, "who": "eddy"},
    )
    assert preview.status_code == 200 and preview.json()["preview"] is True
    assert "0.05" in preview.json()["rendering"]
    unchanged = _projection(workspace_id)["rows"][0]
    assert unchanged["surrenderCharge"] == pytest.approx(baseline["surrenderCharge"])

    saved = client.put(
        f"/api/workspaces/{workspace_id}/equations/surrender_charge",
        json={"body": new_body, "confirmed": True, "who": "eddy"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["record"]["source"]["kind"] == "actuary"
    row = _projection(workspace_id)["rows"][0]
    assert row["surrenderCharge"] == pytest.approx(row["endingPolicyValue"] * 0.05, rel=1e-9)


def test_actuary_put_rejects_invalid_equation(client: TestClient, store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _empty_artifact())
    response = client.put(
        f"/api/workspaces/{workspace_id}/equations/coi_charge",
        json={
            "body": {"qty": "not_a_quantity"},
            "confirmed": True,
            "who": "eddy",
        },
    )
    assert response.status_code == 400
    assert "not_a_quantity" in response.json()["detail"]["errors"][0]


def test_approve_unknown_record_and_reject_flow(client: TestClient, store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _filed_coi_artifact())
    missing = _approve(client, workspace_id, "coi_charge", "eq-doesnotexist")
    assert missing.status_code == 404
    view = _harvest_and_get(client, workspace_id)
    pending = _pending(view, "surrender_charge")
    rejected = client.post(
        f"/api/workspaces/{workspace_id}/equations/surrender_charge/reject",
        json={"equationId": pending["id"], "who": "eddy"},
    )
    assert rejected.status_code == 200
    after = client.get(f"/api/workspaces/{workspace_id}/equations/surrender_charge").json()
    record = next(r for r in after["records"] if r["id"] == pending["id"])
    assert record["state"] == "rejected"
    assert after["inForce"] is None
    # A rejected equation can never be approved afterwards.
    assert _approve(client, workspace_id, "surrender_charge", pending["id"]).status_code == 400


def test_unapproved_harvested_equation_never_executes(
    client: TestClient, store: FakeMinio
) -> None:
    workspace_id = _seed_workspace(store, _empty_artifact())
    view = _harvest_and_get(client, workspace_id)
    assert _pending(view, "surrender_charge") is not None
    projection = _projection(workspace_id)
    rows = projection["rows"]
    assert all(row["surrenderCharge"] == 0.0 for row in rows)
    assert projection["incomplete"] is True


def test_banded_correction_becomes_the_surrender_equation(
    client: TestClient, store: FakeMinio
) -> None:
    workspace_id = _seed_workspace(store, _filed_coi_artifact())
    base = f"/api/workspaces/{workspace_id}/mechanics-panel"
    bands = {
        "bands": [
            {"fromYear": 1, "toYear": 5, "unit": "percent_account_value", "value": 0.10},
            {"fromYear": 6, "toYear": None, "unit": "percent_account_value", "value": 0.02},
        ]
    }
    preview = client.post(
        f"{base}/surrender/corrections/preview",
        json={"variant": "surrender_banded", "params": bands, "who": "eddy"},
    )
    assert preview.status_code == 200, preview.text
    applied = client.post(
        f"{base}/surrender/corrections",
        json={
            "variant": "surrender_banded",
            "params": bands,
            "who": "eddy",
            "confirmed": True,
        },
    )
    assert applied.status_code == 200, applied.text
    view = client.get(f"/api/workspaces/{workspace_id}/equations/surrender_charge").json()
    assert view["inForce"]["source"]["kind"] == "correction"
    assert "by policy duration" in view["inForce"]["rendering"]
    projection = _projection(workspace_id)
    component = _ledger_component(projection, "surrender_charge")
    assert component["basis"] == "corrected"
    row = projection["rows"][0]
    assert row["surrenderCharge"] == pytest.approx(row["endingPolicyValue"] * 0.10, rel=1e-9)
