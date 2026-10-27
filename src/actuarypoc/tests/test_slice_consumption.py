from __future__ import annotations

"""Slice consumption improvements (Oct 27, 2026).

Covers docs/analysis-slice-consumption.md: (1) parallel unit dispatch
whose merged outputs are identical to a sequential run, with per-unit
failure isolation preserved; (2) the 48,000-char default dispatch
budget; (3) unchanged-document reuse — per-document artifact reuse
and whole-run reuse keyed on source etags, including an API-level
run where a cached re-analysis preserves confirmed approvals and
makes zero new model calls; (4) paragraph-aware size cuts;
(5) sub-progress events with monotonic counters.
"""

import hashlib
import io
import json
import re
import time
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from PyPDF2 import PdfReader

from actuarypoc.domain.product_mechanics import FilingSource, ProductMechanic
from actuarypoc.extract import slice_extraction, slice_pipeline
from actuarypoc.extract.document_map import (
    DocumentSlice,
    build_document_map,
    coverage_gaps,
)
from actuarypoc.extract.slice_extraction import (
    extract_assumption_set_from_slices,
    extract_mechanics_from_slices,
    extract_product_metadata_from_slices,
)
from actuarypoc.tests.test_slice_extraction import (
    GEN,
    FakeMinio,
    _FakeCompletions,
)
from actuarypoc.tests.test_workspace_sources import BucketFakeMinio


# ---------------------------------------------------------------------------
# Fixtures: the long synthetic filing + counting/scrambled fake LLM
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def long_map(tmp_path_factory):
    path = tmp_path_factory.mktemp("filing") / "long-synthetic-filing.pdf"
    GEN.build(str(path))
    reader = PdfReader(io.BytesIO(path.read_bytes()))
    pages = [(p.extract_text() or "") for p in reader.pages]
    return build_document_map(
        doc_id="long-synthetic-filing.pdf",
        document_hint="long-synthetic-filing.pdf",
        pages=iter(pages),
        paged=True,
    )


CALLS = {"n": 0}


class _ScrambleCompletions(_FakeCompletions):
    """The content-aware fake, with a content-hashed delay so units
    complete out of order under parallel dispatch, and a call counter."""

    def create(self, **kwargs):
        CALLS["n"] += 1
        user = kwargs["messages"][1]["content"]
        digest = hashlib.md5(user.encode("utf-8")).digest()
        time.sleep((digest[0] % 25) / 1000.0)
        return super().create(**kwargs)


class _ScrambleOpenAI:
    def __init__(self, *args, **kwargs):
        self.chat = SimpleNamespace(completions=_ScrambleCompletions())


@pytest.fixture()
def fake_llm(monkeypatch):
    import actuarypoc.extract.assumptions_extractor as asmp
    import actuarypoc.extract.mechanics_extractor as mech

    CALLS["n"] = 0
    monkeypatch.setattr(mech, "OpenAI", _ScrambleOpenAI)
    monkeypatch.setattr(asmp, "OpenAI", _ScrambleOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return CALLS


def _report_core(report: dict) -> dict:
    return {
        k: report[k]
        for k in (
            "status",
            "calls",
            "succeeded_units",
            "failed_units",
            "slices_dispatched",
            "slices_total",
        )
    }


def _jsonable(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# (1) Parallel dispatch: identical merges, isolated failures
# ---------------------------------------------------------------------------


def test_parallel_mechanics_merge_matches_sequential(long_map, fake_llm):
    seq = extract_mechanics_from_slices(
        product_code="SYN-LT99", slices=long_map.slices,
        dispatch_char_budget=6000, concurrency=1,
    )
    par = extract_mechanics_from_slices(
        product_code="SYN-LT99", slices=long_map.slices,
        dispatch_char_budget=6000, concurrency=8,
    )
    assert _report_core(par) == _report_core(seq)
    assert _jsonable([asdict(m) for m in par["mechanics"]]) == _jsonable(
        [asdict(m) for m in seq["mechanics"]]
    )


def test_parallel_metadata_merge_matches_sequential(long_map, fake_llm):
    seq = extract_product_metadata_from_slices(
        slices=long_map.slices, dispatch_char_budget=6000, concurrency=1
    )
    par = extract_product_metadata_from_slices(
        slices=long_map.slices, dispatch_char_budget=6000, concurrency=8
    )
    assert _report_core(par) == _report_core(seq)
    for key in ("metadata", "provenance", "conflicts"):
        assert _jsonable(par[key]) == _jsonable(seq[key])


def test_parallel_assumptions_merge_matches_sequential(long_map, fake_llm):
    kwargs = dict(
        product_code="SYN-LT99", set_id="syn-lt99-workspace-v1",
        slices=long_map.slices, dispatch_char_budget=6000,
    )
    seq = extract_assumption_set_from_slices(concurrency=1, **kwargs)
    par = extract_assumption_set_from_slices(concurrency=8, **kwargs)
    assert _report_core(par) == _report_core(seq)
    assert _jsonable(asdict(par["assumption_set"])) == _jsonable(
        asdict(seq["assumption_set"])
    )
    assert _jsonable(par["conflicts"]) == _jsonable(seq["conflicts"])


def _hand_slice(idx: int, text: str) -> DocumentSlice:
    return DocumentSlice(
        slice_id=f"d-s{idx:04d}",
        doc_id="d",
        document_hint="d.pdf",
        page_start=1,
        page_end=1,
        heading=None,
        char_start=idx * 1000,
        char_end=idx * 1000 + len(text),
        text=text,
    )


def test_concurrent_failure_isolation_matches_sequential(monkeypatch):
    slices = [
        _hand_slice(0, "alpha provisions text"),
        _hand_slice(1, "BOOM unit one"),
        _hand_slice(2, "beta provisions text"),
        _hand_slice(3, "BOOM unit two"),
        _hand_slice(4, "gamma provisions text"),
    ]

    def _call(*, product_code, text, model=None):
        if "BOOM" in text:
            raise RuntimeError("unit exploded")
        return [
            ProductMechanic(
                id="ok_mech", product_code=product_code, name="OK Mechanic",
                type="feature", description="fine",
                filing_sources=[
                    FilingSource(
                        id="s", document_hint="x", page=None,
                        snippet="provisions text", confidence=0.9,
                    )
                ],
                confidence=0.9,
            )
        ]

    monkeypatch.setattr(slice_extraction, "_extract_mechanics_single_call", _call)
    results = {}
    for mode, conc in (("seq", 1), ("par", 4)):
        results[mode] = extract_mechanics_from_slices(
            product_code="X", slices=slices, dispatch_char_budget=10,
            concurrency=conc,
        )
    for result in results.values():
        assert result["status"] == "partial"
        assert result["succeeded_units"] == 3
        assert result["failed_units"] == [
            {"slice_ids": ["d-s0001"], "error": "RuntimeError: unit exploded"},
            {"slice_ids": ["d-s0003"], "error": "RuntimeError: unit exploded"},
        ]
        assert [m.name for m in result["mechanics"]] == ["OK Mechanic"]
    assert _jsonable([asdict(m) for m in results["par"]["mechanics"]]) == _jsonable(
        [asdict(m) for m in results["seq"]["mechanics"]]
    )


def test_default_dispatch_budget_is_48000():
    assert slice_extraction.DEFAULT_DISPATCH_CHAR_BUDGET == 48000
    assert slice_pipeline._dispatch_budget() == 48000


# ---------------------------------------------------------------------------
# (4) Paragraph-aware size cuts
# ---------------------------------------------------------------------------


def _numbered_lines(count: int, *, blank_after: int | None = None) -> str:
    lines = []
    for i in range(count):
        lines.append(f"L{i:02d} " + "x" * 195)  # 199 chars per line
        if blank_after is not None and i == blank_after:
            lines.append("")
    return "\n".join(lines)


def _assert_map_invariants(m, canonical: str) -> None:
    assert coverage_gaps(m.slices, m.total_chars) == []
    for sl in m.slices:
        assert sl.char_count <= 6000
        assert canonical[sl.char_start:sl.char_end] == sl.text


def test_size_cut_prefers_paragraph_boundary_in_window():
    # 18 content lines (~3,600 chars incl. newlines) then a paragraph
    # break: the break lands inside the ±800 window around the 4,000
    # target, so the first slice must end AT the break, whole.
    page = _numbered_lines(36, blank_after=17)
    m = build_document_map(doc_id="d", document_hint="d.pdf", pages=[page])
    _assert_map_invariants(m, page)
    first = m.slices[0]
    assert first.text.endswith("\n\n")  # closed by the blank line
    # The next slice opens with the standard ~300-char overlap seed
    # (the straddling tail), then the new paragraph, whole.
    assert "\n\nL18 " in m.slices[1].text


def test_size_cut_falls_back_without_paragraph_break_in_window():
    # The only blank line sits far below the window (after line 4,
    # ~1,000 chars); cuts behave as they always did: first line
    # boundary at or past the target, never a paragraph landing.
    page = _numbered_lines(36, blank_after=4)
    m = build_document_map(doc_id="d", document_hint="d.pdf", pages=[page])
    _assert_map_invariants(m, page)
    first = m.slices[0]
    assert first.char_count >= 4000
    assert not first.text.endswith("\n\n")


# ---------------------------------------------------------------------------
# (3) Unchanged-document reuse (pipeline level)
# ---------------------------------------------------------------------------


def _tiny_pdf(lines: list[str]) -> bytes:
    page = GEN._Page()
    y = 780.0
    for line in lines:
        page.text(50, y, line)
        y -= 16
    return GEN.build_pdf_bytes([page])


MEMO_LINES = [
    "Carrier: Meridian Test Company",
    "Product name: Tiny Universal Life",
    "Product code: TNY-1",
    "Product type: Universal Life",
    "Filing reference: TNY-2026-001",
    "Terminal Illness Accelerated Benefit Rider: upon certification",
    "Issue ages: 21 to 60 (age nearest birthday).",
]


def _etag(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


@pytest.fixture()
def bucket_store(monkeypatch):
    fake = BucketFakeMinio()
    fake.make_bucket("app-bucket")
    fake.make_bucket("filings")
    monkeypatch.setattr(slice_pipeline, "get_minio_client", lambda: fake)
    monkeypatch.setattr(slice_pipeline, "get_bucket_name", lambda: "app-bucket")
    monkeypatch.setattr(slice_pipeline, "ensure_bucket", lambda client: None)
    return fake


def _ref_doc(key: str, etag: str, description: str) -> dict:
    return {
        "id": key,
        "description": description,
        "object_path": key,
        "kind": "source",
        "source": {"bucket": "filings", "key": key, "etag": etag},
    }


def test_whole_run_reused_when_nothing_changed(bucket_store, fake_llm):
    pdf = _tiny_pdf(MEMO_LINES)
    bucket_store.put("filings", "memo.pdf", pdf)
    doc = _ref_doc("memo.pdf", _etag(pdf), "memo.pdf")

    first = slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-cache", documents=[doc], product_code_hint="TNY-1"
    )
    assert first["sliceExtraction"]["status"] == "ok"
    calls_after_first = CALLS["n"]
    assert calls_after_first > 0

    second = slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-cache", documents=[doc], product_code_hint="TNY-1"
    )
    assert second["sliceExtraction"].get("reused") is True
    assert CALLS["n"] == calls_after_first  # zero new model calls
    assert second["extractedMechanics"] == first["extractedMechanics"]
    assert second["metadata"] == first["metadata"]


def test_changed_document_reprocesses_and_recaches(bucket_store, fake_llm):
    pdf_v1 = _tiny_pdf(MEMO_LINES)
    bucket_store.put("filings", "memo.pdf", pdf_v1)
    doc = _ref_doc("memo.pdf", _etag(pdf_v1), "memo.pdf")
    slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-cache", documents=[doc], product_code_hint="TNY-1"
    )
    calls_v1 = CALLS["n"]

    pdf_v2 = _tiny_pdf(["Carrier: Other Company"] + MEMO_LINES[1:])
    bucket_store.put("filings", "memo.pdf", pdf_v2)
    doc_v2 = _ref_doc("memo.pdf", _etag(pdf_v2), "memo.pdf")
    changed = slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-cache", documents=[doc_v2], product_code_hint="TNY-1"
    )
    assert changed["sliceExtraction"].get("reused") is not True
    assert changed["sliceExtraction"]["documentsReused"] == 0
    assert CALLS["n"] > calls_v1
    fills = {f["label"]: f["value"] for f in changed["fact_fills"]}
    assert fills["Carrier"] == "Other Company"

    again = slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-cache", documents=[doc_v2], product_code_hint="TNY-1"
    )
    assert again["sliceExtraction"].get("reused") is True


def test_per_document_reuse_when_only_one_document_changes(bucket_store, fake_llm):
    pdf_a = _tiny_pdf(MEMO_LINES)
    pdf_b = _tiny_pdf(["Product code: TNY-1", "Grace notes for form B."])
    bucket_store.put("filings", "a.pdf", pdf_a)
    bucket_store.put("filings", "b.pdf", pdf_b)
    doc_a = _ref_doc("a.pdf", _etag(pdf_a), "a.pdf")
    doc_b = _ref_doc("b.pdf", _etag(pdf_b), "b.pdf")

    first = slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-partial", documents=[doc_a, doc_b],
        product_code_hint="TNY-1",
    )
    assert first["sliceExtraction"]["documentsReused"] == 0

    pdf_b2 = _tiny_pdf(["Product code: TNY-1", "Grace notes for form B, revised."])
    bucket_store.put("filings", "b.pdf", pdf_b2)
    doc_b2 = _ref_doc("b.pdf", _etag(pdf_b2), "b.pdf")
    second = slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-partial", documents=[doc_a, doc_b2],
        product_code_hint="TNY-1",
    )
    report = second["sliceExtraction"]
    assert report.get("reused") is not True  # not a whole-run hit
    assert report["documentsReused"] == 1
    records = {r["document"]: r for r in report["documents"]}
    assert records["a.pdf"].get("reused") is True
    assert records["b.pdf"].get("reused") is not True
    # The passes still ran over the union of both documents' slices.
    assert report["totalCalls"] > 0


def test_reuse_unavailable_without_a_trustworthy_etag(monkeypatch, fake_llm):
    fake = FakeMinio()
    pdf = _tiny_pdf(MEMO_LINES)
    fake.objects["uploads/memo.pdf"] = pdf
    monkeypatch.setattr(slice_pipeline, "get_minio_client", lambda: fake)
    monkeypatch.setattr(slice_pipeline, "get_bucket_name", lambda: "test-bucket")
    monkeypatch.setattr(slice_pipeline, "ensure_bucket", lambda client: None)
    doc = {
        "id": 7,
        "description": "memo.pdf",
        "object_path": "uploads/memo.pdf",
        "kind": "workspace",
    }
    first = slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-noetag", documents=[doc]
    )
    calls_first = CALLS["n"]
    assert calls_first > 0
    second = slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-noetag", documents=[doc]
    )
    # The fake store's listings carry no etags: nothing may be reused
    # on a guess, so the second run pays full price again.
    assert second["sliceExtraction"]["documentsReused"] == 0
    assert second["sliceExtraction"].get("reused") is not True
    assert CALLS["n"] == 2 * calls_first
    assert first["sliceExtraction"]["status"] == "ok"


# ---------------------------------------------------------------------------
# (5) Sub-progress events
# ---------------------------------------------------------------------------


def _assert_monotonic_units(events: list[dict], pass_name: str) -> None:
    seq = [e for e in events if e.get("pass") == pass_name]
    assert seq, f"no progress events for pass {pass_name!r}"
    done = [e["unitsDone"] for e in seq]
    assert done == sorted(done)
    assert done[-1] == seq[-1]["unitsTotal"] >= 1
    assert all(e["detail"] for e in seq)


def test_progress_events_fire_with_monotonic_counters(bucket_store, fake_llm):
    pdf_a = _tiny_pdf(MEMO_LINES)
    pdf_b = _tiny_pdf(["Product code: TNY-1", "Grace notes for form B."])
    bucket_store.put("filings", "a.pdf", pdf_a)
    bucket_store.put("filings", "b.pdf", pdf_b)
    events: list[dict] = []
    slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-progress",
        documents=[
            _ref_doc("a.pdf", _etag(pdf_a), "a.pdf"),
            _ref_doc("b.pdf", _etag(pdf_b), "b.pdf"),
        ],
        product_code_hint="TNY-1",
        progress_callback=events.append,
    )
    read_events = [e for e in events if e["stage"] == "documents"]
    assert [e["documentsDone"] for e in read_events] == [1, 2]
    assert all(e["documentsTotal"] == 2 for e in events)
    for pass_name in ("metadata", "mechanics", "assumptions"):
        _assert_monotonic_units(events, pass_name)


# ---------------------------------------------------------------------------
# (3) Cached re-analysis preserves approvals — API level
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from actuarypoc.storage import workspace_store  # noqa: E402
from actuarypoc.tests.test_analysis_state_persistence import (  # noqa: E402
    CANNED_SNAPSHOT,
    _accept,
    _confirm,
    _extracted_artifact,
    _panel,
    _slot,
)
from actuarypoc.ui import server  # noqa: E402

SPECIMEN_PDF = _tiny_pdf(MEMO_LINES)


@pytest.fixture()
def client(monkeypatch, bucket_store, fake_llm):
    # Same store wiring as the persistence harness's `fake` fixture —
    # one BucketFakeMinio behind every namespace — except the slice
    # pipeline itself stays REAL (that is what this test exercises).
    fake = bucket_store
    for module in (workspace_store, server):
        monkeypatch.setattr(module, "get_minio_client", lambda: fake)
        monkeypatch.setattr(module, "ensure_bucket", lambda c: None)
        monkeypatch.setattr(module, "get_bucket_name", lambda: "app-bucket")
    monkeypatch.setattr(
        server,
        "_extract_workspace_executable_mechanics",
        lambda *args, **kwargs: deepcopy(_extracted_artifact()),
    )
    monkeypatch.setattr(
        server,
        "build_product_workspace_snapshot",
        lambda *args, **kwargs: deepcopy(CANNED_SNAPSHOT),
    )
    monkeypatch.setattr(
        server, "_compile_snapshot_projection_graph", lambda *args, **kwargs: {}
    )
    return TestClient(server.app)


def _analyze(client: TestClient, workspace_id: str) -> None:
    resp = client.post(f"/api/workspaces/{workspace_id}/analyze")
    assert resp.status_code == 202, resp.text
    deadline = time.monotonic() + 60
    while True:
        body = client.get(f"/api/workspaces/{workspace_id}").json()
        job = (body.get("workspace") or {}).get("analysisJob") or {}
        if job.get("state") in {"succeeded", "failed"}:
            assert job.get("state") == "succeeded", f"analysis failed: {job}"
            return
        assert time.monotonic() < deadline, f"job did not finish: {job}"
        time.sleep(0.05)


def _accept_all_tables(client: TestClient, workspace_id: str) -> None:
    panel = _panel(client, workspace_id)
    for cand in ("cand-coi-tob", "cand-coi-nt"):
        proposal = next(
            p for p in panel["proposals"] if p.get("candidateId") == cand
        )
        _confirm(client, workspace_id, proposal["id"], cand)
    _accept(client, workspace_id, "surrender", "cand-sur")
    _accept(client, workspace_id, "corridor", "cand-cor")
    _accept(client, workspace_id, "nar_factors", "cand-nar")


def test_cached_reanalysis_preserves_approvals_and_skips_model_calls(
    client: TestClient, bucket_store
):
    ws = workspace_store.create_workspace()
    workspace_id = ws["id"]
    workspace_store.create_workspace_document(
        workspace_id=workspace_id,
        description="specimen.pdf",
        object_path="uploads/specimen.pdf",
        kind="workspace",
    )
    bucket_store.put("app-bucket", "uploads/specimen.pdf", SPECIMEN_PDF)

    _analyze(client, workspace_id)
    calls_after_first = CALLS["n"]
    assert calls_after_first > 0
    _accept_all_tables(client, workspace_id)

    # The document never changed, so the re-analysis is served by the
    # whole-run cache: zero new model calls. The mechanics rebuild
    # and decision-state carry-over still run on those inputs, so
    # every confirmed acceptance survives.
    _analyze(client, workspace_id)
    assert CALLS["n"] == calls_after_first

    panel = _panel(client, workspace_id)
    coi_slot = _slot(panel, "coi")
    assert {c["id"] for c in coi_slot["candidates"] if c.get("inForce")} == {
        "cand-coi-tob", "cand-coi-nt",
    }
    in_force = {
        c["id"]
        for slot in panel["slots"]
        for c in slot.get("candidates") or []
        if c.get("inForce")
    }
    assert in_force == {
        "cand-coi-tob", "cand-coi-nt", "cand-sur", "cand-cor", "cand-nar",
    }
