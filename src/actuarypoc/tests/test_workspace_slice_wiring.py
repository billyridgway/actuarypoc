from __future__ import annotations

"""End-to-end analyze-route wiring for the slice-extraction stage.

Runs ``api_workspace_analyze`` over the long synthetic filing with a
fake MinIO, a canned Promise-UL snapshot baseline, and the content-aware
fake OpenAI from ``test_slice_extraction``. Asserts the snapshot gains
the late-document facts (which exist only after char 50,000), that the
canned identity is NOT silently overwritten (the conflict is recorded),
and that the deterministic table matches ground truth cell-for-cell.
"""

import pytest

from actuarypoc.extract import slice_pipeline
from actuarypoc.tests.test_slice_extraction import GT, FakeMinio

OBJECT_PATH = "workspaces/ws-e2e/20261025T000000_long-synthetic-filing.pdf"
DOC = {
    "id": 424242,
    "description": "long-synthetic-filing.pdf",
    "object_path": OBJECT_PATH,
    "kind": "workspace",
    "created_at": "2026-10-25T00:00:00Z",
}


@pytest.fixture()
def analyze_env(monkeypatch, tmp_path):
    import actuarypoc.extract.assumptions_extractor as asmp
    import actuarypoc.extract.mechanics_extractor as mech
    from actuarypoc.tests.test_slice_extraction import _FakeOpenAI
    from actuarypoc.ui import server

    monkeypatch.setattr(mech, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(asmp, "OpenAI", _FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    pdf_path = tmp_path / "long-synthetic-filing.pdf"
    from actuarypoc.tests.test_slice_extraction import GEN

    GEN.build(str(pdf_path))

    fake = FakeMinio()
    fake.objects[OBJECT_PATH] = pdf_path.read_bytes()

    monkeypatch.setattr(server, "get_minio_client", lambda: fake)
    monkeypatch.setattr(server, "get_bucket_name", lambda: "test-bucket")
    monkeypatch.setattr(server, "ensure_bucket", lambda client: None)
    monkeypatch.setattr(slice_pipeline, "get_minio_client", lambda: fake)
    monkeypatch.setattr(slice_pipeline, "get_bucket_name", lambda: "test-bucket")
    monkeypatch.setattr(slice_pipeline, "ensure_bucket", lambda client: None)

    monkeypatch.setattr(
        server, "get_workspace",
        lambda ws_id: {"id": ws_id, "document_count": 1,
                       "latest_snapshot_json": {}, "status": "ready_for_analysis",
                       "created_at": "2026-10-25T00:00:00Z",
                       "updated_at": "2026-10-25T00:00:00Z"},
    )
    monkeypatch.setattr(server, "list_workspace_documents", lambda ws_id: [DOC])
    monkeypatch.setattr(
        server, "_extract_workspace_executable_mechanics",
        lambda docs: {
            "version": 1,
            "mechanics": {"coi": [], "surrender": [], "fees": [],
                          "nar_factors": [], "corridor": []},
            "warnings": [], "usable": {},
            "candidates": {"coi": [], "surrender": [], "fees": [],
                           "nar_factors": [], "corridor": []},
            "status": {},
        },
    )
    monkeypatch.setattr(
        server, "store_workspace_executable_mechanics",
        lambda ws_id, artifact: "workspaces/ws-e2e/analysis/executable-ul-mechanics.json",
    )
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

    captured = {}

    def _update(ws_id, **kwargs):
        captured.update(kwargs)
        return {"id": ws_id, "document_count": 1,
                "status": kwargs.get("status"), "created_at": "2026-10-25T00:00:00Z",
                "updated_at": "2026-10-25T00:00:00Z"}

    monkeypatch.setattr(server, "update_workspace_analysis", _update)
    return server, captured


def test_analyze_merges_slice_extraction(analyze_env):
    server, captured = analyze_env
    resp = server.api_workspace_analyze("ws-e2e")
    snapshot = resp["snapshot"]

    # The stage ran clean over the full document.
    assert snapshot["sliceExtraction"]["status"] == "ok"
    assert snapshot["documentMaps"][0]["coverage"] == "full"

    facts = {f["label"]: f for f in snapshot["extractedFacts"]}
    # Late carrier fact filled the empty slot, page-cited, honestly sourced.
    carrier = facts["Carrier"]
    assert carrier["value"] == "Meridian Assurance Test Company (SYNTHETIC)"
    assert carrier["source"] == "long-synthetic-filing.pdf p. 31"
    assert carrier["provenanceKind"] == "slice_extraction"
    assert carrier["status"] == "extracted"
    # Filing id likewise (only stated after char 50,000).
    assert facts["Filing context"]["value"] == GT["filing_id"]
    # Appended extraction facts exist.
    assert "Extracted mechanics" in facts
    assert "Terminal Illness Accelerated Benefit Rider" in facts["Extracted mechanics"]["value"]
    assert "Extracted tables" in facts

    # The canned Promise-UL identity was NOT silently overwritten; the
    # conflict is recorded instead.
    conflicts = snapshot["sliceExtraction"]["conflicts"]
    by_label = {c["label"]: c for c in conflicts}
    assert by_label["Product code"]["documentValue"] == "SYN-LT99"
    assert by_label["Product code"]["snapshotValue"] == "ICC18 P18PR UL"
    assert facts["Product code"]["value"] == "ICC18 P18PR UL"

    # Deterministic table: cell-for-cell ground truth.
    assert len(snapshot["extractedTables"]) == 1
    assert snapshot["extractedTables"][0]["rows"] == GT["table_rows"]
    assert snapshot["extractedTables"][0]["columns"] == GT["table_columns"]

    # Merged mechanics carry the re-anchored rider page.
    rider = next(m for m in snapshot["extractedMechanics"]
                 if m["name"] == "Terminal Illness Accelerated Benefit Rider")
    assert rider["filing_sources"][0]["page"] == "34"

    # productUnderstanding gained additive document-derived entries.
    understanding = snapshot["productUnderstanding"]
    assert understanding["carrier"] == "Meridian Assurance Test Company (SYNTHETIC)"
    assert understanding["filingContext"] == GT["filing_id"]
    assert understanding["sliceExtractionStatus"] == "ok"

    # The route still completes its normal persistence path.
    assert captured["status"] == "analyzed"
    assert captured["snapshot"] is snapshot
