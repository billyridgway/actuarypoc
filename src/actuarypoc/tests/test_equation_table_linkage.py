"""Phase 8 — equation <-> table linkage: structural dependencies,
resolution against the tables in force, reverse ``usedBy``, the
table-detail payload, and the evaluator row citation (stretch).

The fixtures mirror the live Promise UL workspaces' shapes: COI /
surrender / NAR / corridor equations are the canonical bodies the
harvester authors; the premium-load and policy-fees records are the
live ws-720c39d2 forms (a percent-of-premium lookup and a rows_sum
over the fee schedule).
"""

from __future__ import annotations

import copy
import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from actuarypoc.domain import equations as _equations
from actuarypoc.extract import workspace_equations as _ws_eq
from actuarypoc.extract import workspace_linkage as _linkage
from actuarypoc.storage import workspace_store
from actuarypoc.ui import server


# ---------------------------------------------------------------------------
# Server fixture (the phase 7 FakeMinio pattern)
# ---------------------------------------------------------------------------


class MissingObject(Exception):
    code = "NoSuchKey"


class Response(io.BytesIO):
    def release_conn(self) -> None:
        pass


class FakeMinio:
    """The phase 7 fake: objects keyed exactly as the store writes."""

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


@pytest.fixture(autouse=True)
def fake_minio(monkeypatch):
    store = FakeMinio()
    monkeypatch.setattr(workspace_store, "get_minio_client", lambda: store)
    monkeypatch.setattr(workspace_store, "get_bucket_name", lambda: "test")
    monkeypatch.setattr(workspace_store, "ensure_bucket", lambda client: None)
    return store


def _coi_rows(*, reviewed: bool = True) -> list:
    provenance = {
        "filename": "specimen-filing.pdf", "page": 12,
        "tableHeading": "Monthly COI rates", "valueBasis": "duration",
        "sourceType": "filed_pdf", "inputChannel": "filed_pdf",
        "reviewStatus": "accepted",
    }
    if reviewed:
        provenance["reviewedBy"] = "workspace_user"
        provenance["reviewedAt"] = "2026-10-27T01:41:00Z"
    return [
        {
            "duration": duration, "attained_age": None, "sex": None,
            "risk_class": None, "tobacco_status": None, "issue_age": None,
            "premium_mode": None, "rate": 0.19, "rate_unit": "per_1000_monthly",
            "provenance": dict(provenance),
        }
        for duration in (1, 2, 3)
    ]


def _fee_rows() -> list:
    provenance = {
        "filename": "specimen-filing.pdf", "page": 9,
        "tableHeading": "Policy charges", "valueBasis": "flat",
        "sourceType": "filed_pdf", "inputChannel": "filed_pdf",
        "reviewStatus": "accepted",
        "reviewedBy": "workspace_user", "reviewedAt": "2026-10-27T01:41:30Z",
    }
    return [
        {
            "fee_unit": "per_month", "amount": 6.0,
            "start_duration": None, "end_duration": None,
            "provenance": dict(provenance),
        },
        {
            "fee_unit": "percent_premium", "amount": 10.0,
            "start_duration": None, "end_duration": None,
            "provenance": dict(provenance),
        },
    ]


def _record(mechanic: str, body, *, state: str = "approved", version: int = 1,
            approved: bool = True, source: dict | None = None) -> dict:
    record = {
        "id": f"eq-{mechanic}-{state}-{version}",
        "mechanic": mechanic,
        "version": version,
        "state": state,
        "timing": None,
        "body": copy.deepcopy(body),
        "rendering": f"{mechanic} rendering",
        "source": source or {
            "kind": "document", "filename": "specimen-filing.pdf",
            "page": 4, "statement": "A stated calculation.",
        },
        "createdBy": "harvester", "createdAt": "2026-10-26T20:00:00Z",
        "approval": None,
        "rejection": None,
        "conflict": None,
    }
    if approved and state == "approved":
        record["approval"] = {"by": "workspace_user", "at": "2026-10-27T01:41:00Z"}
    return record


def _artifact(*, tables: bool = True, extra_records: list | None = None) -> dict:
    """A workspace with the canonical in-force equations (and, when
    ``tables`` is on, the COI + fee tables filed)."""

    artifact: dict = {
        "usable": {}, "candidates": {}, "mechanics": {},
        "status": {}, "workspaceEdits": {}, "synthetic": {},
        "corrections": {}, "equations": [],
    }
    records = [
        _record("coi_charge", _equations.coi_body_for_unit("per_1000_monthly")),
        _record(
            "surrender_charge",
            _equations.surrender_body_for_unit("percent_account_value"),
        ),
        _record("premium_load", _equations.premium_load_body()),
        _record("policy_fees", _equations.policy_fees_body()),
        _record("nar_definition", _equations.nar_body("factor_adjusted")),
        _record("death_benefit", _equations.death_benefit_body()),
        _record(
            "crediting", _equations.crediting_body(), approved=False,
        ),
    ]
    artifact["equations"] = records + list(extra_records or [])
    if tables:
        artifact["usable"] = {
            "coi": _coi_rows(),
            "fees": _fee_rows(),
            "surrender": [
                {
                    "duration": 1, "charge": 7.0,
                    "charge_unit": "percent_account_value",
                    "provenance": {
                        "filename": "specimen-filing.pdf", "page": 14,
                        "tableHeading": "Surrender charges",
                        "valueBasis": "duration", "sourceType": "filed_pdf",
                        "inputChannel": "filed_pdf", "reviewStatus": "accepted",
                        "reviewedBy": "workspace_user",
                        "reviewedAt": "2026-10-27T01:42:00Z",
                    },
                }
            ],
            "nar_factors": [
                {
                    "duration": 1, "factor": 1.05,
                    "provenance": {
                        "filename": "specimen-filing.pdf", "page": 20,
                        "tableHeading": "NAR factors", "valueBasis": "duration",
                        "sourceType": "filed_pdf", "inputChannel": "filed_pdf",
                        "reviewStatus": "accepted",
                        "reviewedBy": "workspace_user",
                        "reviewedAt": "2026-10-27T01:43:00Z",
                    },
                }
            ],
            "corridor": [
                {
                    "attained_age": 40, "percentage": 250.0,
                    "provenance": {
                        "filename": "specimen-filing.pdf", "page": 22,
                        "tableHeading": "Minimum death benefit percentages",
                        "valueBasis": "attained_age", "sourceType": "filed_pdf",
                        "inputChannel": "filed_pdf", "reviewStatus": "accepted",
                        "reviewedBy": "workspace_user",
                        "reviewedAt": "2026-10-27T01:44:00Z",
                    },
                }
            ],
        }
    return artifact


# ---------------------------------------------------------------------------
# Dependency derivation — structural, from real bodies
# ---------------------------------------------------------------------------


def test_dependencies_derived_from_canonical_bodies() -> None:
    references = {
        body_name: _linkage.body_table_references(body)
        for body_name, body in [
            ("coi", _equations.coi_body_for_unit("per_1000_monthly")),
            ("surrender", _equations.surrender_body_for_unit("percent_account_value")),
            ("premium_load", _equations.premium_load_body()),
            ("policy_fees", _equations.policy_fees_body()),
            ("nar_adjusted", _equations.nar_body("factor_adjusted")),
            ("nar_unadjusted", _equations.nar_body("unadjusted")),
            ("death_benefit", _equations.death_benefit_body()),
            ("crediting", _equations.crediting_body()),
        ]
    }
    assert [(r["table"], r["field"], r["via"]) for r in references["coi"]] == [
        ("coi", "rate", "lookup")
    ]
    assert references["coi"][0]["hasDefault"] is False
    assert [(r["table"], r["field"], r["via"]) for r in references["surrender"]] == [
        ("surrender", "charge", "lookup")
    ]
    # premium_load reads the fee schedule's percent-of-premium row.
    assert [(r["table"], r["field"], r["via"]) for r in references["premium_load"]] == [
        ("fees", "amount", "lookup")
    ]
    assert references["premium_load"][0]["where"] == {"fee_unit": "percent_premium"}
    # policy_fees sums the fee schedule's other rows.
    assert [(r["table"], r["field"], r["via"]) for r in references["policy_fees"]] == [
        ("fees", "amount", "rows_sum")
    ]
    assert references["policy_fees"][0]["excludeWhere"] == {
        "fee_unit": "percent_premium"
    }
    assert [(r["table"], r["field"]) for r in references["nar_adjusted"]] == [
        ("nar_factors", "factor")
    ]
    # The unadjusted NAR definition reads no table.
    assert references["nar_unadjusted"] == []
    assert [(r["table"], r["field"]) for r in references["death_benefit"]] == [
        ("corridor", "percentage")
    ]
    # Crediting is a pure rate formula.
    assert references["crediting"] == []


def test_dependencies_finds_a_lookup_nested_in_a_default() -> None:
    body = {
        "lookup": {
            "table": "coi", "where": None,
            "default": {"lookup": {"table": "nar_factors", "where": None, "default": None}},
        }
    }
    tables = [r["table"] for r in _linkage.body_table_references(body)]
    assert tables == ["coi", "nar_factors"]


# ---------------------------------------------------------------------------
# Resolution — filed vs missing, never dropped
# ---------------------------------------------------------------------------


def _dependencies_by_mechanic(artifact: dict) -> dict:
    view = _ws_eq.equations_view(artifact)
    _linkage.enrich_equations_view(view, artifact)
    return {
        mechanic: (view["mechanics"][mechanic]["inForce"] or {}).get(
            "tableDependencies"
        )
        for mechanic in _equations.MECHANICS
    }, view


def test_resolution_when_tables_are_filed() -> None:
    dependencies, view = _dependencies_by_mechanic(_artifact(tables=True))
    coi = dependencies["coi_charge"]
    assert coi[0]["status"] == "filed"
    assert coi[0]["rowCount"] == 3
    assert coi[0]["sourceFilename"] == "specimen-filing.pdf"
    assert coi[0]["sourcePage"] == 12
    assert coi[0]["acceptedBy"] == "workspace_user"
    assert coi[0]["acceptedAt"] == "2026-10-27T01:41:00Z"
    assert dependencies["death_benefit"][0]["table"] == "corridor"
    assert dependencies["nar_definition"][0]["table"] == "nar_factors"
    assert dependencies["crediting"] == []
    # The reverse linkage: every table here is used by someone.
    tables = {entry["table"]: entry for entry in view["tables"]}
    assert tables["coi"]["usedBy"] == ["coi_charge"]
    assert tables["surrender"]["usedBy"] == ["surrender_charge"]
    assert sorted(tables["fees"]["usedBy"]) == ["policy_fees", "premium_load"]
    assert tables["nar_factors"]["usedBy"] == ["nar_definition"]
    assert tables["corridor"]["usedBy"] == ["death_benefit"]
    assert all(not entry["unused"] for entry in tables.values())


def test_resolution_when_tables_are_missing() -> None:
    dependencies, view = _dependencies_by_mechanic(_artifact(tables=False))
    coi = dependencies["coi_charge"]
    assert coi, "a missing table must never drop the dependency"
    assert coi[0]["status"] == "missing"
    assert coi[0]["rowCount"] == 0
    assert coi[0]["missingReason"] == "table_not_extracted"
    # A default-less lookup says the equation cannot be evaluated.
    assert "cannot be evaluated" in coi[0]["note"]
    # A defaulted lookup (corridor) says the fallback is used.
    corridor = dependencies["death_benefit"][0]
    assert corridor["status"] == "missing"
    assert "fallback" in corridor["note"]
    tables = {entry["table"]: entry for entry in view["tables"]}
    assert tables["coi"]["status"] == "missing"
    # usedBy still names the in-force equations that read it.
    assert tables["coi"]["usedBy"] == ["coi_charge"]


def test_unused_table_says_so_plainly() -> None:
    # No corridor equation in force -> the corridor table is unused.
    artifact = _artifact(tables=True)
    artifact["equations"] = [
        record for record in artifact["equations"]
        if record["mechanic"] != "death_benefit"
    ]
    tables = {
        entry["table"]: entry for entry in _linkage.tables_linkage(artifact)
    }
    assert tables["corridor"]["usedBy"] == []
    assert tables["corridor"]["unused"] is True
    assert tables["coi"]["unused"] is False


def test_pending_equations_carry_would_be_dependencies() -> None:
    pending = _record(
        "coi_charge", _equations.coi_body_for_unit("per_1000_monthly"),
        state="pending", version=2, approved=False,
    )
    artifact = _artifact(tables=False, extra_records=[pending])
    view = _ws_eq.equations_view(artifact)
    _linkage.enrich_equations_view(view, artifact)
    records = view["mechanics"]["coi_charge"]["records"]
    pending_record = next(r for r in records if r["state"] == "pending")
    assert pending_record["tableDependencies"][0]["table"] == "coi"
    assert pending_record["tableDependencies"][0]["status"] == "missing"
    # Pending usage is reported separately, never as a live dependency.
    tables = {entry["table"]: entry for entry in view["tables"]}
    assert tables["coi"]["usedByPending"] == ["coi_charge"]


def test_unmapped_records_carry_no_dependencies() -> None:
    unmapped = _record(
        "surrender_charge", None, state="unmapped", approved=False,
        source={"kind": "stated", "statement": "Charges per the schedule."},
    )
    unmapped["body"] = None
    unmapped["unmappedReason"] = "table_not_extracted"
    artifact = _artifact(tables=True, extra_records=[unmapped])
    view = _ws_eq.equations_view(artifact)
    _linkage.enrich_equations_view(view, artifact)
    record = next(
        r for r in view["mechanics"]["surrender_charge"]["records"]
        if r["state"] == "unmapped"
    )
    assert record["tableDependencies"] == []


# ---------------------------------------------------------------------------
# Table detail — rows, provenance, recorded history
# ---------------------------------------------------------------------------


def _seed_workspace(fake_minio, artifact: dict) -> str:
    workspace = workspace_store.create_workspace()
    workspace_id = workspace["id"]
    workspace_store.store_workspace_executable_mechanics(workspace_id, artifact)
    return workspace_id


def _changes_key(workspace_id: str) -> str:
    return f"workspaces/{workspace_id}/analysis/mechanics-changes.json"


def test_table_detail_rows_provenance_and_acceptance(fake_minio) -> None:
    workspace_id = _seed_workspace(fake_minio, _artifact(tables=True))
    client = TestClient(server.app)
    response = client.get(f"/api/workspaces/{workspace_id}/tables/coi")
    assert response.status_code == 200
    detail = response.json()
    assert detail["status"] == "filed"
    assert detail["rowCount"] == 3
    assert len(detail["rows"]) == 3
    assert detail["rows"][0]["rate"] == 0.19
    assert detail["rows"][0]["provenance"]["filename"] == "specimen-filing.pdf"
    assert detail["rows"][0]["provenance"]["page"] == 12
    assert detail["usedBy"] == ["coi_charge"]
    # The filed acceptance is recorded from the rows' own provenance.
    acceptance = [
        entry for entry in detail["history"] if entry["kind"] == "filed_acceptance"
    ]
    assert len(acceptance) == 1
    assert acceptance[0]["who"] == "workspace_user"
    assert acceptance[0]["at"] == "2026-10-27T01:41:00Z"
    assert acceptance[0]["recordedAs"] == "row_provenance"


def test_table_detail_merges_change_log_and_provenance(fake_minio) -> None:
    import json

    workspace_id = _seed_workspace(fake_minio, _artifact(tables=True))
    changes = [
        {
            "id": "chg-1", "workspaceId": workspace_id, "slot": "fees",
            "mechanic": "fees", "kind": "proposal_accept",
            "who": "workspace_user", "at": "2026-10-27T01:41:30Z",
            "summary": "Accepted the proposed fee schedule.",
            "prior": {"rowCount": 1}, "new": {"rowCount": 2},
        },
        {
            # An equation event for the same slot family: not a
            # table event, must not appear.
            "id": "chg-2", "workspaceId": workspace_id, "slot": "fees",
            "mechanic": "policy_fees", "kind": "equation_approved",
            "who": "workspace_user", "at": "2026-10-27T02:00:00Z",
            "summary": "Approved the policy fees equation.",
            "prior": None, "new": None,
        },
    ]
    fake_minio.objects[_changes_key(workspace_id)] = json.dumps(
        {"changes": changes}
    ).encode()
    client = TestClient(server.app)
    detail = client.get(f"/api/workspaces/{workspace_id}/tables/fees").json()
    kinds = [entry["kind"] for entry in detail["history"]]
    assert kinds == ["proposal_accept"]
    assert detail["history"][0]["summary"] == "Accepted the proposed fee schedule."


def test_table_detail_paging_and_unknown_table(fake_minio) -> None:
    workspace_id = _seed_workspace(fake_minio, _artifact(tables=True))
    client = TestClient(server.app)
    page = client.get(
        f"/api/workspaces/{workspace_id}/tables/coi",
        params={"offset": 2, "limit": 1},
    ).json()
    assert page["rowsReturned"] == 1 and page["truncated"] is True
    assert client.get(f"/api/workspaces/{workspace_id}/tables/nope").status_code == 404


def test_equations_endpoint_carries_linkage(fake_minio) -> None:
    workspace_id = _seed_workspace(fake_minio, _artifact(tables=True))
    client = TestClient(server.app)
    payload = client.get(f"/api/workspaces/{workspace_id}/equations").json()
    in_force = payload["mechanics"]["coi_charge"]["inForce"]
    assert in_force["tableDependencies"][0]["table"] == "coi"
    assert in_force["tableDependencies"][0]["status"] == "filed"
    assert payload["tables"]
    single = client.get(f"/api/workspaces/{workspace_id}/equations/coi_charge").json()
    assert single["inForce"]["tableDependencies"][0]["rowCount"] == 3


# ---------------------------------------------------------------------------
# Stretch — the evaluator's row citation and the ledger line
# ---------------------------------------------------------------------------


def test_evaluator_trace_cites_the_row_used() -> None:
    tables = {"coi": _coi_rows()}
    values = {"duration": 2, "attained_age": 45, "nar": 90_000.0}
    body = _equations.coi_body_for_unit("per_1000_monthly")
    plain = _equations.evaluate(body, values, tables)
    trace: list = []
    traced = _equations.evaluate(body, values, tables, trace=trace)
    assert traced == plain  # the trace never changes the value
    assert len(trace) == 1
    citation = trace[0]
    assert citation["table"] == "coi"
    assert citation["defaulted"] is False
    assert citation["value"] == 0.19
    assert citation["unit"] == "per_1000_monthly"
    assert citation["duration"] == 2
    assert citation["sourceFilename"] == "specimen-filing.pdf"
    assert citation["sourcePage"] == 12


def test_evaluator_trace_marks_a_defaulted_lookup() -> None:
    trace: list = []
    _equations.evaluate(
        _equations.nar_body("factor_adjusted"),
        {"duration": 1, "death_benefit": 100.0, "account_value": 10.0},
        {},
        trace=trace,
    )
    assert trace and trace[0]["defaulted"] is True
    assert trace[0]["value"] is None


def _projection(workspace_id: str) -> dict:
    return server.api_workspace_projection(
        workspace_id, server.WorkspaceProjectionRequest()
    )["illustration"]


def test_projection_year_names_the_coi_table_row(fake_minio) -> None:
    artifact = _artifact(tables=True)
    # The crediting record in the fixture is approved without an
    # approval stamp; stamp it so the projection runs end to end.
    for record in artifact["equations"]:
        if record["mechanic"] == "crediting":
            record["approval"] = {
                "by": "workspace_user", "at": "2026-10-27T01:41:00Z",
            }
    workspace_id = _seed_workspace(fake_minio, artifact)
    illustration = _projection(workspace_id)
    years = illustration["rows"]
    assert years, "the projection must produce years"
    first = years[0]
    table_rows = (first.get("appliedMechanics") or {}).get("coi", {}).get(
        "tableRows"
    )
    assert table_rows, "the year must cite the COI row its charges read"
    assert table_rows[0]["table"] == "coi"
    assert table_rows[0]["value"] == 0.19
    assert table_rows[0]["sourceFilename"] == "specimen-filing.pdf"
    # The ledger names the row beside the charge.
    ledger_row = illustration["ledger"]["rows"][0]
    coi = next(c for c in ledger_row["components"] if c["id"] == "coi")
    labels = [entry["label"] for entry in coi["inputs"]]
    assert "COI table row applied" in labels
    row_line = next(
        entry["value"] for entry in coi["inputs"]
        if entry["label"] == "COI table row applied"
    )
    assert "COI table" in row_line and "specimen-filing.pdf" in row_line
