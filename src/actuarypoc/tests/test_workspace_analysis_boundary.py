from __future__ import annotations

import sys
import types
from typing import Any, Dict, List

sys.modules.setdefault("psycopg", types.SimpleNamespace())
from actuarypoc.ui import server


def _workspace(workspace_id: str) -> Dict[str, Any]:
    return {"id": workspace_id, "status": "ready_for_analysis", "document_count": 99}


def _doc(document_id: str, workspace_id: str) -> Dict[str, Any]:
    return {
        "id": document_id,
        "kind": "workspace",
        "description": f"{workspace_id}-{document_id}.pdf",
        "object_path": f"workspaces/{workspace_id}/{document_id}.pdf",
        "created_at": None,
        "serff_id": None,
    }


def _install_storage_fakes(
    monkeypatch: Any,
    documents_by_workspace: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    persisted: List[Dict[str, Any]] = []
    monkeypatch.setattr(server, "get_workspace", lambda workspace_id: _workspace(workspace_id))
    monkeypatch.setattr(
        server,
        "list_workspace_documents",
        lambda workspace_id: list(documents_by_workspace.get(workspace_id, [])),
    )

    def update(workspace_id: str, **kwargs: Any) -> Dict[str, Any]:
        persisted.append({"workspace_id": workspace_id, **kwargs})
        return {**_workspace(workspace_id), "status": kwargs["status"], "latest_snapshot_json": kwargs["snapshot"]}

    monkeypatch.setattr(server, "update_workspace_analysis", update)
    return persisted


def test_workspace_analysis_passes_only_exact_workspace_documents(monkeypatch: Any) -> None:
    docs_a = [_doc("11", "A"), _doc("12", "A")]
    docs_b = [_doc("21", "B")]
    persisted = _install_storage_fakes(monkeypatch, {"A": docs_a, "B": docs_b})
    calls: List[Dict[str, Any]] = []

    def analyzer(workspace_id: str, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        calls.append({"workspace_id": workspace_id, "documents": documents})
        return {"analysisStatus": "analyzed", "product": {"name": "Test product"}}

    monkeypatch.setattr(server, "analyze_workspace_documents", analyzer)

    response = server.api_workspace_analyze("A")

    assert calls == [{"workspace_id": "A", "documents": docs_a}]
    assert response["snapshot"]["analyzedWorkspaceId"] == "A"
    assert response["snapshot"]["analyzedDocumentIds"] == ["11", "12"]
    assert [item["id"] for item in response["snapshot"]["documentInventory"]] == ["11", "12"]
    assert persisted[0]["snapshot"]["analyzedDocumentIds"] == ["11", "12"]
    assert "21" not in response["snapshot"]["analyzedDocumentIds"]


def test_workspace_analysis_uses_current_membership_on_each_run(monkeypatch: Any) -> None:
    documents = {"A": [_doc("11", "A")]}
    _install_storage_fakes(monkeypatch, documents)
    seen_ids: List[List[int]] = []

    def analyzer(_workspace_id: str, current_docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        seen_ids.append([doc["id"] for doc in current_docs])
        return {"analysisStatus": "analyzed"}

    monkeypatch.setattr(server, "analyze_workspace_documents", analyzer)
    server.api_workspace_analyze("A")
    documents["A"] = [_doc("12", "A"), _doc("13", "A")]
    response = server.api_workspace_analyze("A")

    assert seen_ids == [["11"], ["12", "13"]]
    assert response["snapshot"]["analyzedDocumentIds"] == ["12", "13"]


def test_unsupported_documents_persist_honest_analysis_unavailable(monkeypatch: Any) -> None:
    docs = [_doc("31", "unsupported")]
    persisted = _install_storage_fakes(monkeypatch, {"unsupported": docs})
    monkeypatch.setattr(
        server,
        "analyze_workspace_documents",
        lambda _workspace_id, _documents: {
            "analysisStatus": "analysis_unavailable",
            "analysisUnavailableReason": "unsupported input",
            # Unavailable adapter output is untrusted and must be discarded.
            "product": {"code": "FIXED-FALLBACK"},
            "extractedFacts": [{"label": "Product code", "value": "FIXED-FALLBACK"}],
        },
    )

    response = server.api_workspace_analyze("unsupported")
    snapshot = response["snapshot"]

    assert response["workspace"]["status"] == "analysis_unavailable"
    assert persisted[0]["status"] == "analysis_unavailable"
    assert snapshot["analysisStatus"] == "analysis_unavailable"
    assert snapshot["analyzedWorkspaceId"] == "unsupported"
    assert snapshot["analyzedDocumentIds"] == ["31"]
    assert snapshot["extractedFacts"] == []
    assert snapshot.get("product") is None
    assert persisted[0]["inferred_product_code"] is None
    assert snapshot["readinessDashboard"]["projectionTrustLevel"] == "unavailable"


def test_endpoint_rejects_invalid_membership_before_loading_blobs(monkeypatch: Any) -> None:
    from actuarypoc.extract.workspace_ul_analyzer import analyze_ul_workspace

    invalid_sets = [
        [{"id": None, "object_path": "workspaces/w/a.txt"}],
        [{"id": "", "object_path": "workspaces/w/a.txt"}],
        [{"id": 9, "object_path": "workspaces/w/a.txt"}],
        [
            {"id": "same", "object_path": "workspaces/w/a.txt"},
            {"id": "same", "object_path": "workspaces/w/a.txt"},
        ],
        [
            {"id": "same", "object_path": "workspaces/w/a.txt"},
            {"id": "same", "object_path": "workspaces/w/b.txt"},
        ],
        [{"id": "missing"}],
        [{"id": "malformed", "object_path": "/absolute/object.txt"}],
    ]

    for index, documents in enumerate(invalid_sets):
        workspace_id = f"invalid-{index}"
        persisted = _install_storage_fakes(monkeypatch, {workspace_id: documents})
        loaded: List[Any] = []
        monkeypatch.setattr(
            server,
            "analyze_workspace_documents",
            lambda wid, docs: analyze_ul_workspace(
                wid, docs, content_loader=lambda document: loaded.append(document.get("id")) or b"ignored"
            ),
        )

        response = server.api_workspace_analyze(workspace_id)

        assert loaded == []
        assert response["workspace"]["status"] == "analysis_failed"
        assert response["snapshot"]["analysisStatus"] == "analysis_failed"
        assert response["snapshot"]["analyzedDocumentIds"] == []
        assert response["snapshot"]["extractedFacts"] == []
        assert persisted[0]["status"] == "analysis_failed"
