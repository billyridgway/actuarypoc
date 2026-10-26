from __future__ import annotations

"""Object-store workspace sources (docs/workspace-sources.md).

Covers the picker contract end to end with a bucket-aware fake store:
browsing (buckets, prefix navigation, truncation), creation with
explicit keys and with a prefix (resolved at creation), pin recording,
add-sources dedupe + stale-on-analyzed, the analyze-time pin refresh
(a changed source is recorded and the etag actually read is the one
cited), the changed-since-analyzed view, and analyze over referenced
objects producing documentMaps whose slices the harvest loader can
read — the ws-92e574c9 failure mode (no maps -> harvest reads nothing)
must be impossible for a source-built workspace.
"""

import hashlib
import io
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from actuarypoc.extract import slice_pipeline
from actuarypoc.storage import workspace_store
from actuarypoc.ui import server


class MissingObject(Exception):
    code = "NoSuchKey"


class MissingBucket(Exception):
    code = "NoSuchBucket"


class Response(io.BytesIO):
    def release_conn(self) -> None:
        pass


def _etag(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class BucketFakeMinio:
    """Multi-bucket fake; etag is the content MD5, as in real S3."""

    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, bytes]] = {}

    # -- helpers for tests -------------------------------------------------
    def put(self, bucket: str, key: str, data: bytes) -> None:
        self.buckets.setdefault(bucket, {})[key] = data

    # -- MinIO surface ------------------------------------------------------
    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.buckets

    def make_bucket(self, bucket: str) -> None:
        self.buckets.setdefault(bucket, {})

    def list_buckets(self):
        return [
            SimpleNamespace(name=name, creation_date=datetime(2026, 1, 1, tzinfo=timezone.utc))
            for name in sorted(self.buckets)
        ]

    def put_object(self, bucket, key, stream, length=None, content_type=None) -> None:
        data = stream.read(length) if length is not None else stream.read()
        self.buckets.setdefault(bucket, {})[key] = data

    def get_object(self, bucket, key) -> Response:
        if bucket not in self.buckets:
            raise MissingBucket(bucket)
        if key not in self.buckets[bucket]:
            raise MissingObject(key)
        return Response(self.buckets[bucket][key])

    def stat_object(self, bucket, key):
        if bucket not in self.buckets:
            raise MissingBucket(bucket)
        if key not in self.buckets[bucket]:
            raise MissingObject(key)
        data = self.buckets[bucket][key]
        return SimpleNamespace(
            etag=_etag(data), size=len(data),
            last_modified=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )

    def list_objects(self, bucket, prefix="", recursive=True):
        if bucket not in self.buckets:
            raise MissingBucket(bucket)
        keys = sorted(k for k in self.buckets[bucket] if k.startswith(prefix))
        out = []
        seen_prefixes = set()
        for key in keys:
            rest = key[len(prefix):]
            if not recursive and "/" in rest:
                folder = prefix + rest.split("/", 1)[0] + "/"
                if folder not in seen_prefixes:
                    seen_prefixes.add(folder)
                    out.append(SimpleNamespace(object_name=folder, is_dir=True))
                continue
            data = self.buckets[bucket][key]
            out.append(
                SimpleNamespace(
                    object_name=key, is_dir=False, size=len(data), etag=_etag(data),
                    last_modified=datetime(2026, 10, 1, tzinfo=timezone.utc),
                )
            )
        return out

    def remove_object(self, bucket, key) -> None:
        self.buckets.get(bucket, {}).pop(key, None)


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> BucketFakeMinio:
    client = BucketFakeMinio()
    client.make_bucket("app-bucket")
    client.put("filings", "promise-ul/memo.pdf", b"%PDF-memo-v1")
    client.put("filings", "promise-ul/form.pdf", b"%PDF-form-v1")
    client.put("filings", "promise-ul/sov.pdf", b"%PDF-sov-v1")
    client.put("filings", "other-product/x.pdf", b"%PDF-x")
    for module in (workspace_store, server, slice_pipeline):
        monkeypatch.setattr(module, "get_minio_client", lambda: client)
        monkeypatch.setattr(module, "ensure_bucket", lambda c: None)
    monkeypatch.setattr(workspace_store, "get_bucket_name", lambda: "app-bucket")
    monkeypatch.setattr(server, "get_bucket_name", lambda: "app-bucket")
    monkeypatch.setattr(slice_pipeline, "get_bucket_name", lambda: "app-bucket")
    return client


@pytest.fixture()
def client(fake: BucketFakeMinio) -> TestClient:
    return TestClient(server.app)


# ---------------------------------------------------------------------------
# Browsing
# ---------------------------------------------------------------------------


def test_browsing_buckets_and_prefix_navigation(client: TestClient) -> None:
    buckets = client.get("/api/object-store/buckets").json()["buckets"]
    assert [b["name"] for b in buckets] == ["app-bucket", "filings"]

    root = client.get("/api/object-store/objects", params={"bucket": "filings"}).json()
    assert root["truncated"] is False
    assert [(e["key"], e["isPrefix"]) for e in root["entries"]] == [
        ("other-product/", True),
        ("promise-ul/", True),
    ]

    level = client.get(
        "/api/object-store/objects",
        params={"bucket": "filings", "prefix": "promise-ul/"},
    ).json()
    files = [e for e in level["entries"] if not e["isPrefix"]]
    assert [e["key"] for e in files] == [
        "promise-ul/form.pdf", "promise-ul/memo.pdf", "promise-ul/sov.pdf",
    ]
    memo = next(e for e in files if e["key"].endswith("memo.pdf"))
    assert memo["etag"] == _etag(b"%PDF-memo-v1")
    assert memo["size"] == len(b"%PDF-memo-v1")

    missing = client.get("/api/object-store/objects", params={"bucket": "nope"})
    assert missing.status_code == 404


def test_browsing_truncation_flag(client: TestClient, fake: BucketFakeMinio) -> None:
    for i in range(505):
        fake.put("big", f"f{i:04d}.pdf", b"x")
    page = client.get("/api/object-store/objects", params={"bucket": "big"}).json()
    assert page["truncated"] is True
    assert len(page["entries"]) == 500


# ---------------------------------------------------------------------------
# Creation + sources
# ---------------------------------------------------------------------------


def test_create_with_explicit_keys_pins_references(client: TestClient) -> None:
    resp = client.post(
        "/api/workspaces",
        json={"sources": [{"bucket": "filings", "keys": ["promise-ul/memo.pdf", "promise-ul/form.pdf"]}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workspace"]["status"] == "ready_for_analysis"
    assert body["workspace"]["documentCount"] == 2
    by_key = {s["key"]: s for s in body["sources"]}
    assert by_key["promise-ul/memo.pdf"]["pinnedEtag"] == _etag(b"%PDF-memo-v1")
    assert by_key["promise-ul/memo.pdf"]["analyzedEtag"] is None

    workspace_id = body["workspace"]["id"]
    docs = workspace_store.list_workspace_documents(workspace_id)
    assert {d["kind"] for d in docs} == {"object_store"}
    # Reference, don't copy: nothing was written into the app bucket
    # besides the workspace's own records, and the source bytes are
    # untouched in their bucket.
    stored = workspace_store.get_workspace(workspace_id)
    assert stored["document_count"] == 2

    view = client.get(f"/api/workspaces/{workspace_id}").json()
    assert len(view["sources"]) == 2
    memo = next(s for s in view["sources"] if s["key"].endswith("memo.pdf"))
    assert memo["changedSinceAnalyzed"] is False
    assert memo["changedAtAnalyze"] is False
    assert memo["missing"] is False


def test_create_with_prefix_resolves_at_creation(
    client: TestClient, fake: BucketFakeMinio
) -> None:
    resp = client.post(
        "/api/workspaces", json={"sources": [{"bucket": "filings", "prefix": "promise-ul/"}]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workspace"]["documentCount"] == 3
    assert {s["key"] for s in body["sources"]} == {
        "promise-ul/memo.pdf", "promise-ul/form.pdf", "promise-ul/sov.pdf",
    }
    # A file arriving under the prefix AFTER creation does not join:
    # the recorded references are the creation-time resolution.
    fake.put("filings", "promise-ul/late.pdf", b"%PDF-late")
    docs = workspace_store.list_workspace_documents(body["workspace"]["id"])
    assert len(docs) == 3


def test_create_with_missing_key_fails_without_creating(client: TestClient) -> None:
    resp = client.post(
        "/api/workspaces",
        json={"sources": [{"bucket": "filings", "keys": ["promise-ul/nope.pdf"]}]},
    )
    assert resp.status_code == 400
    assert workspace_store.list_workspaces() == []


def test_create_without_sources_is_the_upload_path(client: TestClient) -> None:
    resp = client.post("/api/workspaces")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workspace"]["status"] == "waiting_for_documents"
    assert body["sources"] == []
    view = client.get(f"/api/workspaces/{body['workspace']['id']}").json()
    assert view["sources"] == []


def test_add_sources_dedupes_and_marks_analyzed_stale(
    client: TestClient, fake: BucketFakeMinio
) -> None:
    created = client.post(
        "/api/workspaces",
        json={"sources": [{"bucket": "filings", "keys": ["promise-ul/memo.pdf"]}]},
    ).json()
    workspace_id = created["workspace"]["id"]
    # Simulate an analyzed workspace.
    workspace_store.update_workspace_analysis(workspace_id, status="analyzed", snapshot={})

    resp = client.post(
        f"/api/workspaces/{workspace_id}/sources",
        json={"sources": [{"bucket": "filings", "keys": ["promise-ul/memo.pdf", "promise-ul/form.pdf"]}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["added"] == 1
    assert body["skippedDuplicates"] == 1

    ws = workspace_store.get_workspace(workspace_id)
    assert ws["projection_stale"] is True
    changes = workspace_store.load_workspace_mechanics_changes(workspace_id)
    assert [c["kind"] for c in changes] == ["sources_added"]
    assert "form.pdf" in changes[0]["summary"]


# ---------------------------------------------------------------------------
# Pin discipline at analyze time
# ---------------------------------------------------------------------------


def _create_memo_workspace(client: TestClient) -> str:
    body = client.post(
        "/api/workspaces",
        json={"sources": [{"bucket": "filings", "keys": ["promise-ul/memo.pdf"]}]},
    ).json()
    return body["workspace"]["id"]


def test_refresh_records_a_changed_source_and_advances_the_pin(
    client: TestClient, fake: BucketFakeMinio
) -> None:
    workspace_id = _create_memo_workspace(client)
    fake.put("filings", "promise-ul/memo.pdf", b"%PDF-memo-v2-CHANGED")

    docs = workspace_store.list_workspace_documents(workspace_id)
    refreshed = server._refresh_source_documents(workspace_id, docs)
    source = refreshed[0]["source"]
    assert source["changedAtAnalyze"] is True
    assert source["previousEtag"] == _etag(b"%PDF-memo-v1")
    assert source["analyzedEtag"] == _etag(b"%PDF-memo-v2-CHANGED")
    # The pin advanced to what was actually read: the cited etag can
    # never be an etag whose bytes were not the ones analyzed.
    assert source["etag"] == _etag(b"%PDF-memo-v2-CHANGED")

    persisted = workspace_store.list_workspace_documents(workspace_id)[0]
    assert persisted["source"]["analyzedEtag"] == _etag(b"%PDF-memo-v2-CHANGED")
    changes = workspace_store.load_workspace_mechanics_changes(workspace_id)
    assert [c["kind"] for c in changes] == ["source_changed"]
    assert "promise-ul/memo.pdf" in changes[0]["summary"]

    # Unchanged on the next pass.
    refreshed = server._refresh_source_documents(
        workspace_id, workspace_store.list_workspace_documents(workspace_id)
    )
    assert refreshed[0]["source"]["changedAtAnalyze"] is False


def test_changed_since_analyzed_view(
    client: TestClient, fake: BucketFakeMinio
) -> None:
    workspace_id = _create_memo_workspace(client)
    docs = workspace_store.list_workspace_documents(workspace_id)
    server._refresh_source_documents(workspace_id, docs)

    view = client.get(f"/api/workspaces/{workspace_id}").json()
    assert view["sources"][0]["changedSinceAnalyzed"] is False

    fake.put("filings", "promise-ul/memo.pdf", b"%PDF-memo-v3")
    view = client.get(f"/api/workspaces/{workspace_id}").json()
    assert view["sources"][0]["changedSinceAnalyzed"] is True
    assert view["sources"][0]["analyzedEtag"] == _etag(b"%PDF-memo-v1")

    fake.remove_object("filings", "promise-ul/memo.pdf")
    view = client.get(f"/api/workspaces/{workspace_id}").json()
    assert view["sources"][0]["missing"] is True


# ---------------------------------------------------------------------------
# Analyze over referenced objects -> documentMaps -> harvest can read
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def long_pdf_bytes(tmp_path_factory) -> bytes:
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "long_synthetic_filing", root / "examples" / "long_synthetic_filing.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    path = tmp_path_factory.mktemp("filing") / "long-synthetic-filing.pdf"
    mod.build(str(path))
    return path.read_bytes()


@pytest.fixture()
def analyze_client(
    client: TestClient, fake: BucketFakeMinio, monkeypatch: pytest.MonkeyPatch,
    long_pdf_bytes: bytes,
) -> TestClient:
    import actuarypoc.extract.assumptions_extractor as asmp
    import actuarypoc.extract.mechanics_extractor as mech
    from actuarypoc.tests.test_slice_extraction import _FakeOpenAI

    monkeypatch.setattr(mech, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(asmp, "OpenAI", _FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        server, "build_product_workspace_snapshot",
        lambda code: {
            "product": {"name": "Promise UL", "code": "ICC18 P18PR UL",
                        "type": "UL", "carrier": None, "filingId": None},
            "complianceMatrix": {"requirements": [], "summary": {}},
            "readinessDashboard": {},
        },
    )
    monkeypatch.setattr(
        server, "_build_ul_projection_view",
        lambda code, req: ({"mechanicsExecution": {}}, {}, [], [], []),
    )
    monkeypatch.setattr(server, "_compile_snapshot_projection_graph", lambda snap: {})
    monkeypatch.setattr(
        server, "_extract_workspace_executable_mechanics",
        lambda docs: {
            "version": 1,
            "mechanics": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
            "warnings": [], "usable": {},
            "candidates": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
            "status": {},
        },
    )
    fake.put("filings", "promise-ul/long-filing.pdf", long_pdf_bytes)
    return client


def test_analyze_over_source_documents_produces_document_maps(
    analyze_client: TestClient, fake: BucketFakeMinio, long_pdf_bytes: bytes
) -> None:
    created = analyze_client.post(
        "/api/workspaces",
        json={"sources": [{"bucket": "filings", "keys": ["promise-ul/long-filing.pdf"]}]},
    ).json()
    workspace_id = created["workspace"]["id"]

    resp = analyze_client.post(f"/api/workspaces/{workspace_id}/analyze")
    assert resp.status_code == 200, resp.text
    snapshot = resp.json()["snapshot"]

    maps = snapshot.get("documentMaps") or []
    assert len(maps) == 1
    record = maps[0]
    assert snapshot["sliceExtraction"]["documents"][0]["status"] == "ok"
    # The map cites the object in the store, with the etag actually read.
    assert record["source"] == {
        "bucket": "filings",
        "key": "promise-ul/long-filing.pdf",
        "etag": _etag(long_pdf_bytes),
    }
    assert record["slicesKey"] in fake.buckets["app-bucket"]

    # The harvest slice loader finds this workspace's slices — the
    # ws-92e574c9 failure mode cannot occur for a source-built workspace.
    slices = server._load_workspace_slices(workspace_id)
    assert slices, "harvest would read zero document text"
    assert all(s.get("document_hint") == "long-filing.pdf" for s in slices)

    doc = workspace_store.list_workspace_documents(workspace_id)[0]
    assert doc["source"]["analyzedEtag"] == _etag(long_pdf_bytes)
    assert doc["source"]["changedAtAnalyze"] is False
