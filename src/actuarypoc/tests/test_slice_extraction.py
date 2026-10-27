from __future__ import annotations

"""Tests for slice-based extraction (docs/slice-extraction-plan.md).

Covers: slicing coverage/exactness over a >50,000-char document, heading
cuts, dispatch grouping, merge dedupe/conflicts, evidence re-anchoring,
late-document fact discovery through a content-aware fake OpenAI client,
the workspace pipeline end-to-end over a fake MinIO, and the analyze
route wiring.
"""

import importlib.util
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyPDF2 import PdfReader

from actuarypoc.domain.product_mechanics import FilingSource, ProductMechanic
from actuarypoc.extract import slice_pipeline
from actuarypoc.extract.document_map import (
    build_document_map,
    coverage_gaps,
    group_slices_for_dispatch,
)
from actuarypoc.extract.slice_extraction import (
    extract_assumption_set_from_slices,
    extract_mechanics_from_slices,
    extract_product_metadata_from_slices,
    merge_mechanics,
    reanchor_mechanic,
)


# ---------------------------------------------------------------------------
# Fixtures: the long synthetic filing + a content-aware fake OpenAI client
# ---------------------------------------------------------------------------


def _load_generator():
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "long_synthetic_filing", root / "examples" / "long_synthetic_filing.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = _load_generator()
GT = GEN.GROUND_TRUTH


@pytest.fixture(scope="module")
def long_pdf_bytes(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("filing") / "long-synthetic-filing.pdf"
    GEN.build(str(path))
    return path.read_bytes()


@pytest.fixture(scope="module")
def long_pages(long_pdf_bytes) -> list:
    reader = PdfReader(io.BytesIO(long_pdf_bytes))
    return [(p.extract_text() or "") for p in reader.pages]


@pytest.fixture(scope="module")
def long_map(long_pages):
    return build_document_map(
        doc_id="long-synthetic-filing.pdf",
        document_hint="long-synthetic-filing.pdf",
        pages=iter(long_pages),
        paged=True,
    )


CAPTURED: list = []


class _FakeCompletions:
    """Content-aware stub: answers from whatever text it is shown.

    This is what makes the late-fact tests discriminating — the stub can
    only report facts that actually reached it in a prompt.
    """

    def create(self, **kwargs):
        system = kwargs["messages"][0]["content"]
        user = kwargs["messages"][1]["content"]
        CAPTURED.append(user)
        if "PRODUCT MECHANICS" in system:
            content = self._mechanics(user)
        elif "AssumptionSet" in system:
            content = self._assumptions(user)
        else:
            content = self._metadata(user)
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                    finish_reason="stop")]
        )
        return resp

    @staticmethod
    def _mechanics(user: str) -> str:
        out = []
        if "Terminal Illness Accelerated Benefit Rider" in user:
            out.append({
                "id": "synlt99_terminal_illness_rider",
                "product_code": "SYN-LT99",
                "name": "Terminal Illness Accelerated Benefit Rider",
                "type": "feature",
                "description": "Accelerates up to fifty percent of the death benefit on terminal illness certification.",
                "filing_sources": [{
                    "id": "rider_src", "document_hint": "unknown", "page": "999",
                    "snippet": "Terminal Illness Accelerated Benefit Rider: upon certification",
                    "confidence": 0.9,
                }],
                "upstream_ids": [], "downstream_ids": [], "confidence": 0.9,
                "source": "ai_extracted", "status": "candidate",
            })
        if "Issue ages: 21 to 60" in user:
            out.append({
                "id": "synlt99_issue_age",
                "product_code": "SYN-LT99",
                "name": "Issue Age",
                "type": "input",
                "description": "Issue ages 21 to 60, age nearest birthday.",
                "filing_sources": [{
                    "id": "age_src", "document_hint": "unknown", "page": None,
                    "snippet": "Issue ages: 21 to 60 (age nearest birthday).",
                    "confidence": 0.85,
                }],
                "upstream_ids": [], "downstream_ids": [], "confidence": 0.85,
                "source": "ai_extracted", "status": "candidate",
            })
        if "grace period allowed by this policy" in user:
            out.append({
                "id": "grace_period",
                "product_code": "SYN-LT99",
                "name": "Grace Period",
                "type": "feature",
                "description": "Premiums may be paid within a grace period before lapse.",
                "filing_sources": [{
                    "id": "grace_src", "document_hint": "unknown", "page": None,
                    "snippet": "If a premium is not paid within the grace period allowed by this policy",
                    "confidence": 0.7,
                }],
                "upstream_ids": [], "downstream_ids": [], "confidence": 0.7,
                "source": "ai_extracted", "status": "candidate",
            })
        return json.dumps(out)

    @staticmethod
    def _assumptions(user: str) -> str:
        return json.dumps({
            "id": "ignored", "product_code": "ignored",
            "description": "Synthetic term assumption set.",
            "dsl_file": "term_life.yaml",
            "actuarial_prefix": "filings/syn-lt99/" if "SYN-2026-099" in user else None,
            "status": "draft", "is_current": False, "created_at": None,
            "created_by": "llm-extractor", "approved_at": None, "approved_by": None,
        })

    @staticmethod
    def _metadata(user: str) -> str:
        def grab(pattern):
            m = re.search(pattern, user)
            return m.group(1).strip() if m else None

        return json.dumps({
            "carrier_name": grab(r"Carrier: (.+)"),
            "product_name": grab(r"Product name: (.+)"),
            "product_code": grab(r"Product code: (\S+)"),
            "product_type": grab(r"Product type: (.+)"),
            "primary_filing_id": grab(r"Filing reference: (\S+)"),
        })


class _FakeOpenAI:
    def __init__(self, *args, **kwargs):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch):
    import actuarypoc.extract.assumptions_extractor as asmp
    import actuarypoc.extract.mechanics_extractor as mech

    CAPTURED.clear()
    monkeypatch.setattr(mech, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(asmp, "OpenAI", _FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    yield


# ---------------------------------------------------------------------------
# Document map / slicing
# ---------------------------------------------------------------------------


def test_slicing_coverage_over_long_document(long_map, long_pages):
    canonical = "\n".join(long_pages)
    assert long_map.total_chars == len(canonical) > 60_000
    assert coverage_gaps(long_map.slices, long_map.total_chars) == []
    for sl in long_map.slices:
        assert sl.char_count <= 6000
        assert canonical[sl.char_start:sl.char_end] == sl.text
    # The identity facts live entirely after char 50,000 and are covered.
    late = [s for s in long_map.slices if "SYN-LT99" in s.text]
    assert late and all(s.char_start > 50_000 for s in late)
    assert late[0].page_start == 31


def test_heading_cuts_and_page_anchoring():
    pages = [
        "Intro line one.\n" + ("filler text here. " * 30),
        "GENERAL PROVISIONS\n" + ("more provisions follow here. " * 30),
    ]
    m = build_document_map(doc_id="d", document_hint="d.pdf", pages=iter(pages))
    headings = [s.heading for s in m.slices]
    assert "GENERAL PROVISIONS" in headings
    section = next(s for s in m.slices if s.heading == "GENERAL PROVISIONS")
    assert section.page_start == 2


def test_hard_cut_overlong_line():
    line = "x" * 13_000
    m = build_document_map(doc_id="d", document_hint="d", pages=[line], paged=False)
    assert coverage_gaps(m.slices, m.total_chars) == []
    assert all(s.char_count <= 6000 for s in m.slices)
    assert "".join(s.text for s in m.slices) == line


def test_dispatch_grouping_covers_every_slice_once(long_map):
    units = group_slices_for_dispatch(long_map.slices, char_budget=6000)
    flat = [s.slice_id for unit in units for s in unit]
    assert flat == [s.slice_id for s in long_map.slices]
    for unit in units:
        if len(unit) > 1:
            assert sum(s.char_count for s in unit) <= 6000


# ---------------------------------------------------------------------------
# Merging + re-anchoring
# ---------------------------------------------------------------------------


def _mech(mid, name, mtype, conf, sources):
    return ProductMechanic(
        id=mid, product_code="X", name=name, type=mtype, description="d",
        filing_sources=sources, confidence=conf,
    )


def test_merge_mechanics_dedupes_by_id_and_name():
    src_a = FilingSource(id="a", document_hint="f.pdf", page="3", snippet="one", confidence=0.7)
    src_b = FilingSource(id="b", document_hint="f.pdf", page="5", snippet="two", confidence=0.8)
    m1 = _mech("issue_age", "Issue Age", "input", 0.7, [src_a])
    m2 = _mech("issue_age", "Issue Age", "input", 0.9, [src_b])
    m3 = _mech("different_id", "Issue Age", "input", 0.6, [src_a])
    merged = merge_mechanics([[m1], [m2, m3]], product_code="syn-lt99")
    assert len(merged) == 1
    assert merged[0].confidence == 0.9
    assert len(merged[0].filing_sources) == 2  # src_a deduped, src_b added
    assert merged[0].product_code == "SYN-LT99"


def test_reanchor_corrects_model_page(long_map):
    rider_slice = next(s for s in long_map.slices
                       if "Terminal Illness Accelerated Benefit Rider" in s.text)
    mech = _mech(
        "rider", "Rider", "feature", 0.9,
        [FilingSource(id="s", document_hint="bogus", page="999",
                      snippet="Terminal Illness Accelerated Benefit Rider: upon certification",
                      confidence=0.9)],
    )
    fixed = reanchor_mechanic(mech, [rider_slice])
    assert fixed.filing_sources[0].page == "34"
    assert fixed.filing_sources[0].document_hint == "long-synthetic-filing.pdf"
    assert fixed.filing_sources[0].confidence == 0.9  # located: no discount


def test_reanchor_unlocatable_snippet_degrades():
    m = build_document_map(doc_id="d", document_hint="d.pdf",
                             pages=["alpha beta gamma delta epsilon zeta eta theta"], paged=True)
    mech = _mech("x", "X", "feature", 1.0,
                 [FilingSource(id="s", document_hint="bogus", page="7",
                               snippet="completely unrelated text that is not present",
                               confidence=1.0)])
    fixed = reanchor_mechanic(mech, m.slices)
    assert fixed.filing_sources[0].page == "1"
    assert fixed.filing_sources[0].confidence == 0.7


# ---------------------------------------------------------------------------
# Slice dispatch against the fake model
# ---------------------------------------------------------------------------


def test_metadata_dispatch_finds_late_facts(long_map):
    result = extract_product_metadata_from_slices(slices=long_map.slices)
    assert result["status"] == "ok"
    assert result["slices_dispatched"] == result["slices_total"] == len(long_map.slices)
    meta = result["metadata"]
    assert meta["carrier_name"] == "Meridian Assurance Test Company (SYNTHETIC)"
    assert meta["product_code"] == GT["product_code"]
    assert meta["primary_filing_id"] == GT["filing_id"]
    prov = result["provenance"]["carrier_name"]
    assert prov["page_start"] == 31


def test_mechanics_dispatch_covers_tail(long_map):
    # The budget is pinned to the historical 6,000 chars: this test
    # exercises merging one mechanic out of MANY dispatch units (the
    # grace-period entry must accumulate >= 3 sources). At the current
    # 48,000-char default the document is only 2 units and the same
    # merge yields 2 sources — correct, but not what is tested here.
    result = extract_mechanics_from_slices(
        product_code="SYN-LT99", slices=long_map.slices, dispatch_char_budget=6000
    )
    assert result["status"] == "ok"
    names = {m.name for m in result["mechanics"]}
    assert "Terminal Illness Accelerated Benefit Rider" in names
    assert "Issue Age" in names
    rider = next(m for m in result["mechanics"]
                 if m.name == "Terminal Illness Accelerated Benefit Rider")
    assert rider.filing_sources[0].page == "34"
    # The grace-period mechanic is found in many filler slices and must
    # merge into one entry with multiple sources.
    grace = next(m for m in result["mechanics"] if m.name == "Grace Period")
    assert len(grace.filing_sources) >= 3


def test_assumptions_merge_takes_late_prefix(long_map):
    result = extract_assumption_set_from_slices(
        product_code="SYN-LT99", set_id="syn-lt99-workspace-v1", slices=long_map.slices
    )
    assert result["status"] == "ok"
    asn = result["assumption_set"]
    assert asn is not None
    assert asn.actuarial_prefix == "filings/syn-lt99/"  # only stated after char 50k
    assert asn.id == "syn-lt99-workspace-v1"
    assert asn.status == "draft" and asn.is_current is False


def test_from_text_dispatches_beyond_50k():
    from actuarypoc.extract.mechanics_extractor import extract_mechanics_from_text

    text = ("filler provisions text. " * 2600) + "\nTerminal Illness Accelerated Benefit Rider: upon certification\n"
    assert len(text) > 50_000
    mechanics = extract_mechanics_from_text(product_code="SYN-LT99", text=text)
    assert any("Terminal Illness" in (c) for c in CAPTURED)  # tail reached a prompt


# ---------------------------------------------------------------------------
# Workspace pipeline end-to-end (fake MinIO)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data

    def read(self, amt=None):
        return self._data

    def close(self):
        pass

    def release_conn(self):
        pass


class FakeMinio:
    def __init__(self):
        self.objects: dict = {}

    def bucket_exists(self, bucket):
        return True

    def make_bucket(self, bucket):
        pass

    def put_object(self, bucket, key, data, length=None, content_type=None):
        self.objects[key] = data.read() if hasattr(data, "read") else data

    def get_object(self, bucket, key):
        return _FakeResponse(self.objects[key])

    def list_objects(self, bucket, prefix="", recursive=True):
        return [SimpleNamespace(object_name=k) for k in sorted(self.objects)
                if k.startswith(prefix)]

    def remove_object(self, bucket, key):
        self.objects.pop(key, None)


@pytest.fixture()
def fake_store(monkeypatch, long_pdf_bytes):
    fake = FakeMinio()
    object_path = "workspaces/ws-test/20261025T000000_long-synthetic-filing.pdf"
    fake.objects[object_path] = long_pdf_bytes
    monkeypatch.setattr(slice_pipeline, "get_minio_client", lambda: fake)
    monkeypatch.setattr(slice_pipeline, "get_bucket_name", lambda: "test-bucket")
    monkeypatch.setattr(slice_pipeline, "ensure_bucket", lambda client: None)
    return fake, object_path


def _doc(object_path):
    return {
        "id": 987654321,
        "description": "long-synthetic-filing.pdf",
        "object_path": object_path,
        "kind": "workspace",
        "created_at": "2026-10-25T00:00:00Z",
    }


def test_pipeline_end_to_end(fake_store):
    fake, object_path = fake_store
    result = slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-test", documents=[_doc(object_path)],
        product_code_hint="ICC18 P18PR UL",
    )
    report = result["sliceExtraction"]
    assert report["status"] == "ok"
    assert report["documents"][0]["coverage"] == "full"
    for part in ("metadata", "mechanics", "assumptions"):
        assert report["parts"][part]["status"] == "ok", report["parts"][part]
        assert report["parts"][part]["slices_dispatched"] == report["parts"][part]["slices_total"]

    # Table channel: exact ground truth.
    assert len(result["extractedTables"]) == 1
    table = result["extractedTables"][0]
    assert table["columns"] == GT["table_columns"]
    assert table["rows"] == GT["table_rows"]
    assert table["page"] == 33

    # Fact fills carry late facts with page citations.
    fills = {f["label"]: f for f in result["fact_fills"]}
    assert fills["Carrier"]["value"] == "Meridian Assurance Test Company (SYNTHETIC)"
    assert fills["Carrier"]["source"] == "long-synthetic-filing.pdf p. 31"
    assert fills["Product code"]["value"] == "SYN-LT99"
    assert fills["Filing context"]["value"] == "SYN-2026-099"

    # Artifacts are stored as objects under the additive analysis prefix.
    keys = [k for k in fake.objects if "/analysis/documents/" in k]
    assert any(k.endswith("/map.json") for k in keys)
    assert any(k.endswith("/slices.json") for k in keys)
    assert any(k.endswith("/tables.json") for k in keys)

    # Merged mechanics include the late rider, page-cited.
    rider = next(m for m in result["extractedMechanics"]
                 if m["name"] == "Terminal Illness Accelerated Benefit Rider")
    assert rider["filing_sources"][0]["page"] == "34"


def test_pipeline_degrades_without_api_key(fake_store, monkeypatch):
    fake, object_path = fake_store
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = slice_pipeline.run_workspace_slice_extraction(
        workspace_id="ws-test", documents=[_doc(object_path)],
    )
    report = result["sliceExtraction"]
    assert report["parts"]["metadata"]["status"] == "skipped"
    assert report["parts"]["tables"]["status"] == "ok"
    assert len(result["extractedTables"]) == 1  # deterministic channel still runs
    assert result["extractedMechanics"] == []
