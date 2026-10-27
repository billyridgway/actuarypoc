from __future__ import annotations

"""Background analysis jobs (docs/analyze-jobs.md).

Covers the Oct 26, 2026 failure: a 13-document analysis outlived the
browser request that started it, the request died, and the workspace
sat in silent ``ready_for_analysis`` limbo with nothing recorded. The
contract now: POST /analyze starts a job and returns promptly (202);
the job runs detached and records running / succeeded / failed (with
the error) on the workspace record; a duplicate start reports the
running job; the commit path absorbs one transient object-store blip.
"""

import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from actuarypoc.extract import slice_pipeline
from actuarypoc.storage import workspace_store
from actuarypoc.tests.test_workspace_sources import BucketFakeMinio
from actuarypoc.ui import server


MINIMAL_ARTIFACT = {
    "version": 1,
    "mechanics": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
    "warnings": [],
    "usable": {},
    "candidates": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
    "status": {},
}

CANNED_SNAPSHOT = {
    "product": {"name": "Promise UL", "code": "ICC18 P18PR UL", "type": "UL",
                "carrier": None, "filingId": None},
    "complianceMatrix": {"requirements": [], "summary": {}},
    "readinessDashboard": {},
}

CANNED_SLICE_RUN = {
    "sliceExtraction": {"status": "ok", "conflicts": []},
    "documentMaps": [{"document": "memo.pdf", "slices": []}],
    "extractedTables": [],
    "extractedMechanics": [],
    "extractedAssumptionSet": {"status": "ok"},
    "fact_fills": [],
    "appended_facts": [],
}


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> BucketFakeMinio:
    fake = BucketFakeMinio()
    fake.make_bucket("app-bucket")
    for module in (workspace_store, server, slice_pipeline):
        monkeypatch.setattr(module, "get_minio_client", lambda: fake)
        monkeypatch.setattr(module, "ensure_bucket", lambda c: None)
    monkeypatch.setattr(workspace_store, "get_bucket_name", lambda: "app-bucket")
    monkeypatch.setattr(server, "get_bucket_name", lambda: "app-bucket")
    monkeypatch.setattr(slice_pipeline, "get_bucket_name", lambda: "app-bucket")
    return fake


@pytest.fixture()
def client(fake: BucketFakeMinio) -> TestClient:
    return TestClient(server.app)


@pytest.fixture()
def fast_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real analyze core, with its slow stages replaced by fakes."""

    monkeypatch.setattr(
        server, "_extract_workspace_executable_mechanics",
        lambda docs: deepcopy(MINIMAL_ARTIFACT),
    )
    monkeypatch.setattr(
        server, "build_product_workspace_snapshot",
        lambda code: deepcopy(CANNED_SNAPSHOT),
    )
    monkeypatch.setattr(
        server, "_build_ul_projection_view",
        lambda code, req: ({"mechanicsExecution": {}}, {}, [], [], []),
    )
    monkeypatch.setattr(server, "_compile_snapshot_projection_graph", lambda snap: {})
    monkeypatch.setattr(
        slice_pipeline, "run_workspace_slice_extraction",
        lambda **kwargs: deepcopy(CANNED_SLICE_RUN),
    )


def _workspace_with_document() -> str:
    ws = workspace_store.create_workspace()
    workspace_store.create_workspace_document(
        workspace_id=ws["id"],
        description="memo.pdf",
        object_path="uploads/memo.pdf",
        kind="workspace",
    )
    return ws["id"]


def _poll_job(client: TestClient, workspace_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(f"/api/workspaces/{workspace_id}").json()
        job = (body.get("workspace") or {}).get("analysisJob") or {}
        if job.get("state") in {"succeeded", "failed"}:
            return body
        assert time.monotonic() < deadline, f"job did not finish; last state: {job}"
        time.sleep(0.05)


# ---------------------------------------------------------------------------
# Job lifecycle
# ---------------------------------------------------------------------------


def test_analyze_returns_promptly_and_commits_after_client_leaves(
    client: TestClient, fast_pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client gets its 202 while the analysis is still running —
    and the analysis commits anyway (the ws-0e4bd9b4 failure mode)."""

    workspace_id = _workspace_with_document()
    entered = threading.Event()
    release = threading.Event()

    def blocking_extract(docs):
        entered.set()
        assert release.wait(timeout=10)
        return deepcopy(MINIMAL_ARTIFACT)

    monkeypatch.setattr(server, "_extract_workspace_executable_mechanics", blocking_extract)

    resp = client.post(f"/api/workspaces/{workspace_id}/analyze")
    assert resp.status_code == 202, resp.text
    assert resp.json()["started"] is True
    assert entered.wait(timeout=5), "job thread never reached extraction"

    # The job is visibly running on the workspace record while the
    # client that started it is long gone.
    view = client.get(f"/api/workspaces/{workspace_id}").json()
    assert view["workspace"]["analysisJob"]["state"] == "running"
    assert view["workspace"]["status"] == "analyzing"

    release.set()
    body = _poll_job(client, workspace_id)
    assert body["workspace"]["status"] == "analyzed"
    job = body["workspace"]["analysisJob"]
    assert job["state"] == "succeeded"
    assert job["finishedAt"]
    assert job["error"] is None
    assert len(body["snapshot"]["documentMaps"]) == 1


def test_duplicate_start_reports_running_job_and_starts_nothing(
    client: TestClient, fast_pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = _workspace_with_document()
    entered = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def blocking_extract(docs):
        calls["n"] += 1
        entered.set()
        assert release.wait(timeout=10)
        return deepcopy(MINIMAL_ARTIFACT)

    monkeypatch.setattr(server, "_extract_workspace_executable_mechanics", blocking_extract)

    first = client.post(f"/api/workspaces/{workspace_id}/analyze")
    assert first.status_code == 202 and first.json()["started"] is True
    run_id = first.json()["analysisJob"]["runId"]
    assert entered.wait(timeout=5)

    second = client.post(f"/api/workspaces/{workspace_id}/analyze")
    assert second.status_code == 202, second.text
    assert second.json()["started"] is False
    assert second.json()["analysisJob"]["runId"] == run_id

    release.set()
    _poll_job(client, workspace_id)
    assert calls["n"] == 1


def test_failed_analysis_is_recorded_on_the_workspace(
    client: TestClient, fast_pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = _workspace_with_document()

    def exploding_extract(docs):
        raise RuntimeError("kaboom-extract")

    monkeypatch.setattr(server, "_extract_workspace_executable_mechanics", exploding_extract)

    resp = client.post(f"/api/workspaces/{workspace_id}/analyze")
    assert resp.status_code == 202, resp.text

    body = _poll_job(client, workspace_id)
    job = body["workspace"]["analysisJob"]
    assert job["state"] == "failed"
    assert "kaboom-extract" in job["error"]
    assert job["finishedAt"]
    # Never again silent ready_for_analysis limbo.
    assert body["workspace"]["status"] == "analysis_failed"


def test_failed_reanalysis_keeps_the_analyzed_state(
    client: TestClient, fast_pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = _workspace_with_document()
    assert client.post(f"/api/workspaces/{workspace_id}/analyze").status_code == 202
    body = _poll_job(client, workspace_id)
    assert body["workspace"]["status"] == "analyzed"

    def exploding_extract(docs):
        raise RuntimeError("second-run-boom")

    monkeypatch.setattr(server, "_extract_workspace_executable_mechanics", exploding_extract)
    resp = client.post(f"/api/workspaces/{workspace_id}/analyze")
    assert resp.status_code == 202 and resp.json()["started"] is True

    body = _poll_job(client, workspace_id)
    assert body["workspace"]["analysisJob"]["state"] == "failed"
    assert "second-run-boom" in body["workspace"]["analysisJob"]["error"]
    # The good analysis survives the failed re-run.
    assert body["workspace"]["status"] == "analyzed"
    assert body["snapshot"]


def test_orphaned_running_record_is_closed_out_and_restarted(
    client: TestClient, fast_pipeline
) -> None:
    """A 'running' record whose process died (pod restart) must not
    block new analyses forever: past the staleness bound it is closed
    out as interrupted and a fresh job starts."""

    workspace_id = _workspace_with_document()
    started_long_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    workspace_store.update_workspace_analysis_job(
        workspace_id,
        {
            "state": "running",
            "phase": "extracting_mechanics",
            "startedAt": started_long_ago.replace("+00:00", "Z"),
            "finishedAt": None,
            "error": None,
            "runId": "orphan-run",
        },
    )

    resp = client.post(f"/api/workspaces/{workspace_id}/analyze")
    assert resp.status_code == 202, resp.text
    assert resp.json()["started"] is True
    assert resp.json()["analysisJob"]["runId"] != "orphan-run"

    body = _poll_job(client, workspace_id)
    assert body["workspace"]["analysisJob"]["state"] == "succeeded"


def test_fresh_running_record_from_another_process_dedupes(
    client: TestClient, fast_pipeline
) -> None:
    workspace_id = _workspace_with_document()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    workspace_store.update_workspace_analysis_job(
        workspace_id,
        {
            "state": "running",
            "phase": "extracting_slices",
            "startedAt": now,
            "finishedAt": None,
            "error": None,
            "runId": "elsewhere-run",
        },
    )

    resp = client.post(f"/api/workspaces/{workspace_id}/analyze")
    assert resp.status_code == 202, resp.text
    assert resp.json()["started"] is False
    assert resp.json()["analysisJob"]["runId"] == "elsewhere-run"


def test_analyze_start_validates_like_the_old_route(client: TestClient) -> None:
    missing = client.post("/api/workspaces/ws-nope/analyze")
    assert missing.status_code == 404

    empty = workspace_store.create_workspace()
    no_docs = client.post(f"/api/workspaces/{empty['id']}/analyze")
    assert no_docs.status_code == 400


# ---------------------------------------------------------------------------
# Commit resilience
# ---------------------------------------------------------------------------


class _FakeS3Error(Exception):
    code = "NoSuchKey"


def test_commit_mechanics_absorbs_one_transient_nosuchkey(
    fake: BucketFakeMinio, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = workspace_store.create_workspace()
    real_store = workspace_store.store_workspace_executable_mechanics
    calls = {"n": 0}

    def flaky(workspace_id, value):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _FakeS3Error("simulated transient NoSuchKey")
        return real_store(workspace_id, value)

    monkeypatch.setattr(server, "store_workspace_executable_mechanics", flaky)
    monkeypatch.setattr(server, "_ANALYSIS_COMMIT_BASE_DELAY_SECONDS", 0)

    key = server._commit_mechanics_artifact(ws["id"], {"version": 1})
    assert calls["n"] == 2
    assert key.endswith("executable-ul-mechanics.json")
    assert workspace_store.load_workspace_executable_mechanics(ws["id"])["version"] == 1


def test_commit_mechanics_absorbs_transient_existence_check_failure(
    fake: BucketFakeMinio, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact Oct 26 wart: the store's existence read of an existing
    workspace.json transiently 404s, surfacing as
    ValueError('workspace does not exist') at commit time."""

    ws = workspace_store.create_workspace()
    real_store = workspace_store.store_workspace_executable_mechanics
    calls = {"n": 0}

    def flaky(workspace_id, value):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("workspace does not exist")
        return real_store(workspace_id, value)

    monkeypatch.setattr(server, "store_workspace_executable_mechanics", flaky)
    monkeypatch.setattr(server, "_ANALYSIS_COMMIT_BASE_DELAY_SECONDS", 0)

    server._commit_mechanics_artifact(ws["id"], {"version": 2})
    assert calls["n"] == 2
    assert workspace_store.load_workspace_executable_mechanics(ws["id"])["version"] == 2


def test_commit_mechanics_does_not_retry_real_errors(
    fake: BucketFakeMinio, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = workspace_store.create_workspace()
    calls = {"n": 0}

    def broken(workspace_id, value):
        calls["n"] += 1
        raise RuntimeError("genuinely broken")

    monkeypatch.setattr(server, "store_workspace_executable_mechanics", broken)
    monkeypatch.setattr(server, "_ANALYSIS_COMMIT_BASE_DELAY_SECONDS", 0)

    with pytest.raises(RuntimeError, match="genuinely broken"):
        server._commit_mechanics_artifact(ws["id"], {"version": 1})
    assert calls["n"] == 1


def test_commit_analysis_retries_a_transient_missing_read(
    fake: BucketFakeMinio, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = workspace_store.create_workspace()
    real_update = workspace_store.update_workspace_analysis
    calls = {"n": 0}

    def flaky(workspace_id, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # workspace read transiently missed
        return real_update(workspace_id, **kwargs)

    monkeypatch.setattr(server, "update_workspace_analysis", flaky)
    monkeypatch.setattr(server, "_ANALYSIS_COMMIT_BASE_DELAY_SECONDS", 0)

    updated = server._commit_workspace_analysis(
        ws["id"], status="analyzed", snapshot={"a": 1}
    )
    assert updated is not None
    assert updated["status"] == "analyzed"
    assert calls["n"] == 2

    # Exhaustion preserves the old semantics: None -> the caller 503s.
    monkeypatch.setattr(server, "update_workspace_analysis", lambda wid, **kw: None)
    assert (
        server._commit_workspace_analysis(ws["id"], status="analyzed", snapshot={})
        is None
    )


# ---------------------------------------------------------------------------
# Store-level job state
# ---------------------------------------------------------------------------


def test_analysis_job_state_roundtrip(fake: BucketFakeMinio) -> None:
    ws = workspace_store.create_workspace()
    updated = workspace_store.update_workspace_analysis_job(
        ws["id"],
        {"state": "running", "phase": "starting", "runId": "r1"},
        status="analyzing",
    )
    assert updated is not None
    assert updated["status"] == "analyzing"

    workspace_store.update_workspace_analysis_job(ws["id"], {"phase": "extracting_slices"})
    job = workspace_store.get_workspace(ws["id"])["analysis_job"]
    assert job == {
        "state": "running",
        "phase": "extracting_slices",
        "runId": "r1",
    }

    assert (
        workspace_store.update_workspace_analysis_job("ws-missing", {"state": "running"})
        is None
    )
