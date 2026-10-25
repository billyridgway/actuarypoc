"""Phase 5 (the validation harness): test-case packs.

Covers the pack format's round-trip through the object store and its
rejection of malformed documents with specific problems; the runner's
correctness against an independent hand computation of the filed
mechanics; tolerance semantics (absolute and relative, inside and
outside the band); the deliberate-error catch (perturb one slot value,
the pack fails the affected expectations with the expected delta, and
the run-over-run change record names them); placeholder-basis mismatch
explanations; pinned-mechanics cases; and report export completeness
(JSON identity/engine/summary + the human-readable rendering).
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from actuarypoc.extract import workspace_validation_packs as packs
from actuarypoc.storage import workspace_store
from actuarypoc.ui import server


# ---------------------------------------------------------------------------
# Fake MinIO (same pattern as test_workspace_mechanics_panel)
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


@pytest.fixture()
def pinned_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the Promise UL guaranteed rate to its documented fallback.

    The hand computation below is written against the filing-stated
    mechanics plus the product config's documented fallback credited
    rate (2%); pinning removes any dependence on whatever assumption
    discovery happens to find in this environment.
    """

    real_loader = server.load_ul_runtime_config

    def loader(product_code: str):
        config = real_loader(product_code)
        config.guaranteed_rate = 0.02
        return config

    monkeypatch.setattr(server, "load_ul_runtime_config", loader)


# ---------------------------------------------------------------------------
# Artifact builders (the repo's Promise UL filed shapes)
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


def _filed_coi_rows(rate: float = 0.11) -> list[dict]:
    return [
        {
            "duration": duration,
            "attained_age": None,
            "sex": None,
            "risk_class": None,
            "tobacco_status": None,
            "rate": rate,
            "rate_unit": "per_1000_monthly",
            "provenance": {
                "filename": "filing.pdf", "page": 4,
                "sourceType": "filed_pdf", "reviewStatus": "accepted",
            },
        }
        for duration in range(1, 31)
    ]


def _filed_surrender_rows(charge: float = 12.50) -> list[dict]:
    return [
        {
            "duration": duration,
            "issue_age": None,
            "sex": None,
            "charge": charge,
            "charge_unit": "per_1000_face",
            "provenance": {
                "filename": "filing.pdf", "page": 3,
                "sourceType": "filed_pdf", "reviewStatus": "accepted",
            },
        }
        for duration in range(1, 21)
    ]


def _filed_artifact() -> dict:
    artifact = _empty_artifact()
    artifact["usable"]["coi"] = _filed_coi_rows()
    artifact["usable"]["surrender"] = _filed_surrender_rows()
    artifact["status"]["coi"] = "filed_accepted"
    artifact["status"]["surrender"] = "filed_accepted"
    return artifact


def _seed_workspace(store: FakeMinio, artifact: dict) -> str:
    ws = workspace_store.create_workspace()
    workspace_id = ws["id"]
    workspace_store.store_workspace_executable_mechanics(workspace_id, artifact)
    return workspace_id


# ---------------------------------------------------------------------------
# Independent hand computation of the filed scenario
#
# Written from the mechanics as the filing + ledger state them, not
# from the engine's code: monthly steps; the premium ($3,600, annual
# mode) is paid in month 1; COI is deducted at the beginning of the
# month as (death benefit / NAR factor - value) / 1,000 x the filed
# monthly rate, with the filed NAR factor 1.0 and corridor 100% (no
# factor/corridor tables in force); interest is credited monthly at
# (1 + 2%)^(1/12) - 1; no fee schedule is in force and the configured
# fallback fee is $0.  The year's surrender charge is the filed
# $12.50 per $1,000 of face.
# ---------------------------------------------------------------------------

FACE = 100_000.0
ANNUAL_PREMIUM = 3_600.0
GUARANTEED_RATE = 0.02
FILED_COI_RATE = 0.11
FILED_SURRENDER_PER_1000 = 12.50


def _hand_computed(years: int = 3) -> dict[int, dict[str, float]]:
    monthly_rate = (1.0 + GUARANTEED_RATE) ** (1.0 / 12.0) - 1.0
    value = 0.0
    out: dict[int, dict[str, float]] = {}
    for year in range(1, years + 1):
        coi_year = 0.0
        interest_year = 0.0
        for month in range(1, 13):
            if month == 1:
                value += ANNUAL_PREMIUM
            death_benefit = max(FACE, value)
            nar = max(death_benefit - value, 0.0)
            coi = nar / 1000.0 * FILED_COI_RATE
            value = max(value - coi, 0.0)
            interest = value * monthly_rate
            value += interest
            coi_year += coi
            interest_year += interest
        surrender_charge = FACE / 1000.0 * FILED_SURRENDER_PER_1000
        death_benefit = max(FACE, value)
        out[year] = {
            "accountValue": value,
            "coiCharge": coi_year,
            "interestCredited": interest_year,
            "surrenderCharge": surrender_charge,
            "surrenderValue": max(value - surrender_charge, 0.0),
            "deathBenefit": death_benefit,
            "netAmountAtRisk": max(death_benefit - value, 0.0),
        }
    return out


def _filed_pack_payload() -> dict:
    """The Promise UL validation pack (acceptance shape).

    Expectations are the hand-computed values of the filed mechanics
    above — the same arithmetic an actuary would do from the filing's
    stated tables (COI p.4, surrender p.3) — each expectation stating
    its source, as the format requires.
    """

    computed = _hand_computed(3)
    expectations = []
    for year in (1, 2, 3):
        for field in (
            "accountValue", "coiCharge", "surrenderCharge",
            "surrenderValue", "deathBenefit",
        ):
            expectations.append({
                "duration": year,
                "field": field,
                "value": round(computed[year][field], 2),
                "source": {
                    "description": (
                        "Hand-computed from the filed COI table "
                        "(0.11 per $1,000 monthly) and filed surrender "
                        "schedule ($12.50 per $1,000 of face)"
                    ),
                    "document": "filing.pdf",
                    "page": 4 if field == "coiCharge" else 3,
                },
                "tolerance": {"absolute": 0.02},
            })
    return {
        "formatVersion": 1,
        "name": "Promise UL filed-mechanics pack",
        "version": "1.0",
        "productCode": "ICC18 P18PR UL",
        "cases": [{
            "id": "filed-base-case",
            "name": "Filed base case — generic selectors, age 45, $100k",
            "inputs": {
                "issueAge": 45,
                "faceAmount": FACE,
                "premiumMode": "ANNUAL",
                "modalPremium": ANNUAL_PREMIUM,
            },
            "expectations": expectations,
        }],
    }


def _create_pack(workspace_id: str, payload: dict) -> dict:
    return server.api_create_validation_pack(workspace_id, payload)["pack"]


def _run_pack(workspace_id: str, pack_id: str, who: str = "eddy") -> dict:
    return server.api_run_validation_pack(
        workspace_id, pack_id, server.ValidationPackRunRequest(who=who)
    )["report"]


def _result(report: dict, duration: int, field: str) -> dict:
    case = report["cases"][0]
    return next(
        r for r in case["results"]
        if r["duration"] == duration and r["field"] == field
    )


# ---------------------------------------------------------------------------
# Pack format: round-trip + storage
# ---------------------------------------------------------------------------


def test_pack_round_trip_through_the_store(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _filed_artifact())
    pack = _create_pack(workspace_id, _filed_pack_payload())
    assert pack["id"].startswith("pack-")
    assert pack["createdAt"] and pack["updatedAt"]

    # The stored object is the pack document itself (plus its key).
    raw = json.loads(store.objects[f"workspaces/{workspace_id}/validation/packs/{pack['id']}.json"])
    assert raw["name"] == "Promise UL filed-mechanics pack"
    assert raw["cases"][0]["expectations"][0]["source"]["page"] in (3, 4)

    fetched = server.api_get_validation_pack(workspace_id, pack["id"])["pack"]
    assert fetched["cases"] == pack["cases"]

    listing = server.api_list_validation_packs(workspace_id)["packs"]
    assert len(listing) == 1
    assert listing[0]["caseCount"] == 1
    assert listing[0]["lastRun"] is None

    # Replace keeps identity and the creation record, takes the new body.
    replacement = _filed_pack_payload()
    replacement["id"] = pack["id"]
    replacement["version"] = "1.1"
    updated = server.api_replace_validation_pack(workspace_id, pack["id"], replacement)["pack"]
    assert updated["version"] == "1.1"
    assert updated["createdAt"] == pack["createdAt"]

    assert server.api_delete_validation_pack(workspace_id, pack["id"])["deleted"] is True
    with pytest.raises(HTTPException) as excinfo:
        server.api_get_validation_pack(workspace_id, pack["id"])
    assert excinfo.value.status_code == 404


def test_pack_for_missing_workspace_is_404(store: FakeMinio) -> None:
    with pytest.raises(HTTPException) as excinfo:
        server.api_create_validation_pack("ws-nope", _filed_pack_payload())
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# Pack format: malformed documents rejected with specific problems
# ---------------------------------------------------------------------------


def _problems(payload) -> list[str]:
    with pytest.raises(packs.PackValidationError) as excinfo:
        packs.validate_pack(payload)
    return excinfo.value.problems


def test_malformed_pack_names_every_problem() -> None:
    problems = _problems({})
    joined = " ".join(problems)
    assert "name is required" in joined
    assert "version is required" in joined
    assert "cases must be a non-empty list" in joined


def test_unsupported_format_version_is_rejected() -> None:
    payload = _filed_pack_payload()
    payload["formatVersion"] = 99
    problems = _problems(payload)
    assert any("formatVersion 99 is not supported" in p for p in problems)


def test_unknown_field_is_rejected_with_the_registry() -> None:
    payload = _filed_pack_payload()
    payload["cases"][0]["expectations"][0]["field"] = "cashValue"
    problems = _problems(payload)
    assert any("field must be one of" in p and "cashValue" in p for p in problems)


def test_expectation_without_a_source_is_rejected() -> None:
    payload = _filed_pack_payload()
    del payload["cases"][0]["expectations"][0]["source"]
    problems = _problems(payload)
    assert any("source.description is required" in p for p in problems)


def test_negative_tolerance_is_rejected() -> None:
    payload = _filed_pack_payload()
    payload["cases"][0]["expectations"][0]["tolerance"] = {"absolute": -1}
    problems = _problems(payload)
    assert any("tolerance.absolute must be a number >= 0" in p for p in problems)


def test_duplicate_expectation_is_rejected() -> None:
    payload = _filed_pack_payload()
    payload["cases"][0]["expectations"].append(
        dict(payload["cases"][0]["expectations"][0])
    )
    problems = _problems(payload)
    assert any("duplicate expectation for duration 1" in p for p in problems)


def test_bad_inputs_are_rejected() -> None:
    payload = _filed_pack_payload()
    payload["cases"][0]["inputs"]["faceAmount"] = 0
    payload["cases"][0]["inputs"]["issueAge"] = 400
    problems = _problems(payload)
    joined = " ".join(problems)
    assert "inputs.faceAmount must be a number greater than zero" in joined
    assert "inputs.issueAge must be an integer between 0 and 120" in joined


def test_pinned_mechanics_require_the_state() -> None:
    payload = _filed_pack_payload()
    payload["cases"][0]["mechanics"] = {"mode": "pinned"}
    problems = _problems(payload)
    assert any("mechanics.executableMechanics is required" in p for p in problems)


def test_api_rejects_malformed_pack_with_problems(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _empty_artifact())
    with pytest.raises(HTTPException) as excinfo:
        server.api_create_validation_pack(workspace_id, {"name": "x"})
    assert excinfo.value.status_code == 400
    detail = excinfo.value.detail
    assert detail["code"] == "invalid_validation_pack"
    assert any("cases must be a non-empty list" in p for p in detail["problems"])
    # Nothing was stored.
    assert server.api_list_validation_packs(workspace_id)["packs"] == []


# ---------------------------------------------------------------------------
# Runner: correctness against the hand computation
# ---------------------------------------------------------------------------


def test_runner_matches_the_hand_computed_filed_case(
    store: FakeMinio, pinned_config: None
) -> None:
    workspace_id = _seed_workspace(store, _filed_artifact())
    pack = _create_pack(workspace_id, _filed_pack_payload())
    report = _run_pack(workspace_id, pack["id"])

    assert report["summary"]["status"] == "pass"
    assert report["summary"]["passed"] == report["summary"]["expectations"] == 15
    assert report["changeVsPreviousRun"] is None

    # The filed surrender charge is one multiplication from the filing:
    # $100,000 / 1,000 x $12.50 = $1,250.00, every year in force.
    for year in (1, 2, 3):
        result = _result(report, year, "surrenderCharge")
        assert result["actual"] == pytest.approx(1250.00)
        assert result["basis"] == "filed"
        coi = _result(report, year, "coiCharge")
        assert coi["basis"] == "filed"
        account = _result(report, year, "accountValue")
        assert account["actual"] == pytest.approx(
            _hand_computed(3)[year]["accountValue"], abs=0.02
        )

    # The engine record names the banked switches the run executed.
    switches = report["engine"]["switchesUsed"]
    assert "coi.rate.per_1000_monthly" in switches
    assert "coi.timing.beginning" in switches
    assert "surrender.basis.per_1000_face" in switches
    # Nothing in this run rests on a stand-in.
    assert report["standInLines"] == []
    assert report["engine"]["ledgerVersion"] == 1

    # The run is persisted and listed as the pack's last run.
    stored = server.api_get_validation_run(workspace_id, report["id"])["report"]
    assert stored["id"] == report["id"]
    listing = server.api_list_validation_packs(workspace_id)["packs"]
    assert listing[0]["lastRun"]["id"] == report["id"]
    assert listing[0]["lastRun"]["summary"]["status"] == "pass"


# ---------------------------------------------------------------------------
# Tolerance semantics
# ---------------------------------------------------------------------------


def test_tolerance_semantics(store: FakeMinio, pinned_config: None) -> None:
    workspace_id = _seed_workspace(store, _filed_artifact())
    actual = _hand_computed(1)[1]["accountValue"]
    payload = _filed_pack_payload()
    payload["cases"][0]["expectations"] = [
        {  # inside the absolute band
            "duration": 1, "field": "accountValue", "value": actual + 0.005,
            "source": {"description": "test"}, "tolerance": {"absolute": 0.01},
        },
        {  # outside the absolute band
            "duration": 1, "field": "surrenderValue", "value": 1.0,
            "source": {"description": "test"}, "tolerance": {"absolute": 0.01},
        },
        {  # inside only because of the relative band
            "duration": 2, "field": "accountValue",
            "value": _hand_computed(2)[2]["accountValue"] * 1.05,
            "source": {"description": "test"},
            "tolerance": {"absolute": 0.0, "relative": 0.10},
        },
        {  # outside: the relative band is narrower than the miss
            "duration": 3, "field": "accountValue",
            "value": _hand_computed(3)[3]["accountValue"] * 1.05,
            "source": {"description": "test"},
            "tolerance": {"absolute": 0.0, "relative": 0.01},
        },
    ]
    pack = _create_pack(workspace_id, payload)
    report = _run_pack(workspace_id, pack["id"])
    statuses = {
        (r["duration"], r["field"]): r["status"] for r in report["cases"][0]["results"]
    }
    assert statuses[(1, "accountValue")] == "pass"
    assert statuses[(1, "surrenderValue")] == "fail"
    assert statuses[(2, "accountValue")] == "pass"
    assert statuses[(3, "accountValue")] == "fail"
    assert report["summary"]["passed"] == 2
    assert report["summary"]["failed"] == 2
    # The failing relative case records the band it was judged against.
    failing = _result(report, 3, "accountValue")
    assert failing["tolerance"]["band"] == pytest.approx(
        0.01 * _hand_computed(3)[3]["accountValue"] * 1.05, rel=1e-6
    )
    assert failing["delta"] < 0  # engine below the inflated expectation


# ---------------------------------------------------------------------------
# The deliberate-error catch + the regression story
# ---------------------------------------------------------------------------


def test_deliberate_slot_error_is_caught(
    store: FakeMinio, pinned_config: None
) -> None:
    workspace_id = _seed_workspace(store, _filed_artifact())
    pack = _create_pack(workspace_id, _filed_pack_payload())
    first = _run_pack(workspace_id, pack["id"])
    assert first["summary"]["status"] == "pass"

    # Perturb one slot value through the product's own edit path: the
    # filed surrender charge $12.50 -> $15.00 per $1,000 of face.
    server.api_edit_mechanics_slot(
        workspace_id, "surrender",
        server.MechanicsSlotEditRequest(rows=[
            {"duration": d, "charge": 15.00, "charge_unit": "per_1000_face"}
            for d in range(1, 21)
        ]),
    )

    second = _run_pack(workspace_id, pack["id"])
    assert second["summary"]["status"] == "fail"
    # The surrender expectations fail with exactly the perturbed delta:
    # (15.00 - 12.50) x 100 = +$250.00.  Everything else still passes,
    # because the surrender charge does not feed the account value.
    for year in (1, 2, 3):
        result = _result(second, year, "surrenderCharge")
        assert result["status"] == "fail"
        assert result["actual"] == pytest.approx(1500.00)
        assert result["delta"] == pytest.approx(250.00)
        assert _result(second, year, "accountValue")["status"] == "pass"
        # Surrender value moves by the same amount, the other way (to
        # within the pack's own cent-rounding of the expected value).
        sv = _result(second, year, "surrenderValue")
        assert sv["status"] == "fail"
        assert sv["delta"] == pytest.approx(-250.00, abs=0.01)

    change = second["changeVsPreviousRun"]
    assert change["previousRunId"] == first["id"]
    assert set(change["mechanicsChangedCases"]) == {"filed-base-case"}
    assert any("surrenderCharge" in key for key in change["newlyFailing"])
    assert not any("accountValue" in key for key in change["newlyFailing"])
    assert change["newlyPassing"] == []

    # Run history: both runs, newest first.
    history = server.api_list_validation_pack_runs(workspace_id, pack["id"])["runs"]
    assert [run["id"] for run in history] == [second["id"], first["id"]]
    assert history[0]["summary"]["status"] == "fail"


# ---------------------------------------------------------------------------
# Placeholder basis: the mismatch explains itself
# ---------------------------------------------------------------------------


def test_placeholder_mismatch_explains_itself(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _empty_artifact())
    payload = {
        "name": "Expectations against an empty product",
        "version": "0.1",
        "cases": [{
            "name": "No mechanics in force",
            "inputs": {"issueAge": 45, "faceAmount": 100_000.0, "modalPremium": 3_600.0},
            "expectations": [
                {
                    "duration": 1, "field": "coiCharge", "value": 999.99,
                    "source": {"description": "carrier illustration, year 1 COI"},
                },
                {
                    "duration": 1, "field": "surrenderCharge", "value": 0.0,
                    "source": {"description": "carrier illustration, year 1"},
                },
            ],
        }],
    }
    pack = _create_pack(workspace_id, payload)
    report = _run_pack(workspace_id, pack["id"])
    assert report["summary"]["status"] == "fail"

    coi = _result(report, 1, "coiCharge")
    assert coi["basis"] == "placeholder"
    assert coi["status"] == "fail"
    assert "PLACEHOLDER" in coi["explanation"]
    # The flat placeholder is the config's 0.4% of face: $400.00/year.
    assert coi["actual"] == pytest.approx(400.00)

    surrender = _result(report, 1, "surrenderCharge")
    assert surrender["basis"] == "placeholder"
    # Both stand-in lines are named in the report's stand-in list.
    standin_fields = {line["field"] for line in report["standInLines"]}
    assert {"coiCharge", "surrenderCharge"} <= standin_fields
    assert "coi.placeholder.flat_face" in report["engine"]["switchesUsed"]


# ---------------------------------------------------------------------------
# Pinned mechanics: a case carries the state it assumes
# ---------------------------------------------------------------------------


def test_pinned_case_runs_its_own_mechanics(store: FakeMinio) -> None:
    workspace_id = _seed_workspace(store, _empty_artifact())
    filed_view = {
        "coi": _filed_coi_rows(),
        "surrender": _filed_surrender_rows(),
        "fees": [],
        "nar_factors": [],
        "corridor": [],
    }
    expectations = [{
        "duration": 1, "field": "surrenderCharge", "value": 1250.00,
        "source": {"description": "filed surrender schedule, $12.50 per $1,000"},
    }]
    payload = {
        "name": "Workspace vs pinned",
        "version": "1",
        "cases": [
            {
                "id": "workspace-case", "name": "Runs the workspace state",
                "inputs": {"issueAge": 45, "faceAmount": 100_000.0, "modalPremium": 3_600.0},
                "expectations": expectations,
            },
            {
                "id": "pinned-case", "name": "Runs its pinned filed state",
                "inputs": {"issueAge": 45, "faceAmount": 100_000.0, "modalPremium": 3_600.0},
                "mechanics": {"mode": "pinned", "executableMechanics": filed_view},
                "expectations": expectations,
            },
        ],
    }
    pack = _create_pack(workspace_id, payload)
    report = _run_pack(workspace_id, pack["id"])
    by_id = {case["caseId"]: case for case in report["cases"]}

    workspace_result = by_id["workspace-case"]["results"][0]
    assert workspace_result["basis"] == "placeholder"
    assert workspace_result["status"] == "fail"

    pinned_result = by_id["pinned-case"]["results"][0]
    assert pinned_result["basis"] == "filed"
    assert pinned_result["status"] == "pass"
    assert pinned_result["actual"] == pytest.approx(1250.00)

    assert (
        by_id["workspace-case"]["mechanicsFingerprint"]
        != by_id["pinned-case"]["mechanicsFingerprint"]
    )


# ---------------------------------------------------------------------------
# Missing durations + export completeness
# ---------------------------------------------------------------------------


def test_duration_beyond_the_horizon_is_missing_not_invented(
    store: FakeMinio,
) -> None:
    workspace_id = _seed_workspace(store, _filed_artifact())
    payload = _filed_pack_payload()
    payload["cases"][0]["expectations"] = [{
        "duration": 45, "field": "accountValue", "value": 1.0,
        "source": {"description": "illustration year 45"},
    }]
    pack = _create_pack(workspace_id, payload)
    report = _run_pack(workspace_id, pack["id"])
    result = _result(report, 45, "accountValue")
    assert result["status"] == "missing"
    assert result["actual"] is None
    assert "no year-45 row" in result["explanation"]
    assert report["summary"]["missing"] == 1


def test_exported_report_is_complete(store: FakeMinio, pinned_config: None) -> None:
    workspace_id = _seed_workspace(store, _filed_artifact())
    pack = _create_pack(workspace_id, _filed_pack_payload())
    report = _run_pack(workspace_id, pack["id"], who="eddy")

    fetched = server.api_get_validation_run(workspace_id, report["id"])["report"]
    assert fetched["packId"] == pack["id"]
    assert fetched["packName"] == "Promise UL filed-mechanics pack"
    assert fetched["packVersion"] == "1.0"
    assert fetched["workspaceId"] == workspace_id
    assert fetched["ranBy"] == "eddy"
    assert fetched["ranAt"]
    assert fetched["engine"]["switchesUsed"]
    assert fetched["summary"]["expectations"] == 15

    response = server.api_get_validation_run_report_text(workspace_id, report["id"])
    text = response.body.decode("utf-8")
    assert "VALIDATION REPORT" in text
    assert "Promise UL filed-mechanics pack" in text
    assert "coi.rate.per_1000_monthly" in text
    assert "Filed base case" in text
    assert "PASS" in text

    # A failing run's text rendering carries the mismatch explanations.
    # (Expectations are ordered year-then-field; index 1 is the year-1
    # COI charge, whose actual rests on the filed table.)
    bad = _filed_pack_payload()
    bad["name"] = "Deliberately wrong pack"
    bad["cases"][0]["expectations"][1]["value"] = 42.00
    bad_pack = _create_pack(workspace_id, bad)
    bad_report = _run_pack(workspace_id, bad_pack["id"])
    assert bad_report["summary"]["status"] == "fail"
    bad_text = server.api_get_validation_run_report_text(
        workspace_id, bad_report["id"]
    ).body.decode("utf-8")
    assert "Mismatches:" in bad_text
    assert "genuine mismatch" in bad_text  # the filed-basis explanation
