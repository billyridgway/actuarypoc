from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from actuarypoc.storage import workspace_store


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

    def put_object(
        self,
        bucket: str,
        key: str,
        stream: io.BytesIO,
        *,
        length: int,
        content_type: str,
    ) -> None:
        self.objects[key] = stream.read(length)

    def get_object(self, bucket: str, key: str) -> Response:
        if key not in self.objects:
            raise MissingObject(key)
        return Response(self.objects[key])

    def list_objects(self, bucket: str, *, prefix: str, recursive: bool):
        return [
            SimpleNamespace(object_name=key)
            for key in sorted(self.objects)
            if key.startswith(prefix)
        ]

    def remove_object(self, bucket: str, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture()
def store(monkeypatch: pytest.MonkeyPatch) -> FakeMinio:
    client = FakeMinio()
    monkeypatch.setattr(workspace_store, "get_minio_client", lambda: client)
    monkeypatch.setattr(workspace_store, "get_bucket_name", lambda: "test")
    return client


def test_workspace_lifecycle_is_persisted_in_minio(store: FakeMinio) -> None:
    workspace = workspace_store.create_workspace()
    workspace_id = workspace["id"]

    assert workspace_store.get_workspace(workspace_id) == workspace
    assert workspace_store.list_workspaces() == [workspace]

    document = workspace_store.create_workspace_document(
        workspace_id=workspace_id,
        description="filing.pdf",
        object_path=f"workspaces/{workspace_id}/filing.pdf",
    )
    assert document is not None
    assert workspace_store.list_workspace_documents(workspace_id) == [document]

    ready = workspace_store.get_workspace(workspace_id)
    assert ready is not None
    assert ready["status"] == "ready_for_analysis"
    assert ready["document_count"] == 1

    analyzed = workspace_store.update_workspace_analysis(
        workspace_id,
        status="analyzed",
        snapshot={"product": {"code": "TEST"}},
        inferred_product_code="TEST",
    )
    assert analyzed is not None
    assert analyzed["latest_snapshot_json"]["product"]["code"] == "TEST"

    result = workspace_store.delete_workspace_and_documents(
        workspace_id,
        owned_document_ids=[document["id"]],
    )
    assert result == {"deleted_documents": 1, "deleted_objects": 2}
    assert workspace_store.get_workspace(workspace_id) is None
    assert not any(key.startswith(f"workspaces/{workspace_id}/") for key in store.objects)


def test_feature_requests_are_workspace_scoped(store: FakeMinio) -> None:
    first = workspace_store.create_workspace()
    second = workspace_store.create_workspace()

    request = workspace_store.create_feature_request(
        workspace_id=first["id"],
        product_code="TEST",
        capability_id="cap-1",
        title="Implement capability",
    )
    assert request is not None
    assert workspace_store.list_feature_requests(first["id"]) == [request]
    assert workspace_store.list_feature_requests(second["id"]) == []

    updated = workspace_store.update_feature_request_status(
        feature_request_id=request["id"],
        workspace_id=first["id"],
        status="approved",
    )
    assert updated is not None
    assert updated["status"] == "approved"
    assert workspace_store.update_feature_request_status(
        feature_request_id=request["id"],
        workspace_id=second["id"],
        status="rejected",
    ) is None


def test_executable_mechanics_are_persisted_under_workspace_prefix(store: FakeMinio) -> None:
    workspace = workspace_store.create_workspace()
    value = {"version": 1, "usable": {"fees": [{"amount": 60.0}]}}

    key = workspace_store.store_workspace_executable_mechanics(workspace["id"], value)

    assert key == f"workspaces/{workspace['id']}/analysis/executable-ul-mechanics.json"
    assert workspace_store.load_workspace_executable_mechanics(workspace["id"]) == value
