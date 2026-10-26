from __future__ import annotations

"""Workspace-level slice extraction pipeline.

One entry point — :func:`run_workspace_slice_extraction` — used by the
workspace analyze route (see ``docs/slice-extraction-plan.md`` §6). For
each uploaded PDF in a workspace it builds and stores a document map +
slices, runs the deterministic table channel, then dispatches the
metadata / mechanics / assumptions extractors over the union of slices
and merges the results.

Everything produced is additive: new objects under
``workspaces/{id}/analysis/documents/{doc}/`` and a plain-dict result
the analyze route merges into the snapshot. This module never raises
for per-document or per-part failures — they are recorded in the run
report so the analyze route can degrade honestly.
"""

import io
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from actuarypoc.extract.document_map import (
    DocumentMap,
    build_document_map,
    coverage_gaps,
    doc_slug,
)
from actuarypoc.extract.slice_extraction import (
    extract_assumption_set_from_slices,
    extract_mechanics_from_slices,
    extract_product_metadata_from_slices,
)
from actuarypoc.extract.table_extractor import extract_tables_from_pdf_bytes
from actuarypoc.storage.minio_client import (
    document_object_location,
    ensure_bucket,
    get_bucket_name,
    get_minio_client,
)


def _dispatch_budget() -> int:
    try:
        return int(os.getenv("ACTUARYPOC_SLICE_DISPATCH_CHARS", "6000"))
    except ValueError:
        return 6000


def _put_json(key: str, value: Dict[str, Any]) -> None:
    client = get_minio_client()
    ensure_bucket(client)
    bucket = get_bucket_name()
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")
    client.put_object(
        bucket, key, io.BytesIO(payload), length=len(payload), content_type="application/json"
    )


def _read_object(key: str, bucket: Optional[str] = None) -> bytes:
    client = get_minio_client()
    ensure_bucket(client)
    response = client.get_object(bucket or get_bucket_name(), key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _doc_storage_slug(document: Dict[str, Any]) -> str:
    object_path = str(document.get("object_path") or "")
    stem = Path(object_path).stem or str(document.get("id") or "document")
    return doc_slug(stem)


def _process_document(workspace_id: str, document: Dict[str, Any]) -> Dict[str, Any]:
    """Map + slice + table-extract one workspace document; store artifacts."""

    from PyPDF2 import PdfReader

    object_path = str(document.get("object_path") or "")
    filename = str(document.get("description") or Path(object_path).name)
    record: Dict[str, Any] = {
        "document": filename,
        "objectPath": object_path,
        "status": "failed",
    }
    source = document.get("source")
    if isinstance(source, dict) and source.get("bucket"):
        # Provenance for a referenced document cites the object in the
        # store (bucket + key + the etag this analyze actually read).
        record["source"] = {
            "bucket": source.get("bucket"),
            "key": source.get("key"),
            "etag": source.get("analyzedEtag") or source.get("etag"),
        }
    if Path(object_path).suffix.lower() != ".pdf" and Path(filename).suffix.lower() != ".pdf":
        record.update({"status": "skipped", "reason": "not a PDF document"})
        return record

    source_bucket, source_key = document_object_location(document, get_bucket_name())
    content = _read_object(source_key, bucket=source_bucket)
    doc_id = str(document.get("id") or object_path)
    slug = _doc_storage_slug(document)
    prefix = f"workspaces/{workspace_id}/analysis/documents/{slug}"

    reader = PdfReader(io.BytesIO(content))

    def _pages():
        for page in reader.pages:
            try:
                yield page.extract_text() or ""
            except Exception:
                yield ""

    doc_map = build_document_map(
        doc_id=doc_id,
        document_hint=filename,
        pages=_pages(),
        object_path=object_path,
        paged=True,
    )
    map_key = f"{prefix}/map.json"
    slices_key = f"{prefix}/slices.json"
    _put_json(map_key, doc_map.to_dict())
    _put_json(slices_key, doc_map.slices_payload())

    tables = extract_tables_from_pdf_bytes(content, document=filename, object_path=object_path)
    tables_key = f"{prefix}/tables.json"
    tables_payload: Dict[str, Any] = {"document": filename, "objectPath": object_path, "tables": tables}
    if record.get("source"):
        tables_payload["source"] = record["source"]
    _put_json(tables_key, tables_payload)

    gaps = coverage_gaps(doc_map.slices, doc_map.total_chars)
    record.update(
        {
            "status": "ok",
            "pageCount": doc_map.page_count,
            "totalChars": doc_map.total_chars,
            "sliceCount": len(doc_map.slices),
            "coverage": "full" if not gaps else f"partial: {len(gaps)} gap(s)",
            "mapKey": map_key,
            "slicesKey": slices_key,
            "tablesKey": tables_key,
            "tableCount": len(tables),
        }
    )
    record["_map"] = doc_map
    record["_tables"] = tables
    return record


_METADATA_FACT_LABELS = {
    "carrier_name": "Carrier",
    "product_name": "Product name",
    "product_code": "Product code",
    "product_type": "Product type",
    "primary_filing_id": "Filing context",
}


def run_workspace_slice_extraction(
    *,
    workspace_id: str,
    documents: List[Dict[str, Any]],
    product_code_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the full slice pipeline for one workspace analysis.

    Returns a dict with the run report (``sliceExtraction``), additive
    snapshot sections (``documentMaps``, ``extractedTables``,
    ``extractedMechanics``, ``extractedAssumptionSet``), candidate fact
    fills for the analyze route to apply, and facts to append verbatim.
    """

    started = time.monotonic()
    budget = _dispatch_budget()

    doc_records: List[Dict[str, Any]] = []
    maps: List[DocumentMap] = []
    all_tables: List[Dict[str, Any]] = []
    for document in documents:
        try:
            record = _process_document(workspace_id, document)
        except Exception as exc:  # noqa: BLE001 - per-document isolation
            record = {
                "document": str(document.get("description") or ""),
                "objectPath": str(document.get("object_path") or ""),
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        # (_process_document stashes internals under _map/_tables; pull
        # them back out before the record goes into the report.)
        doc_map = record.pop("_map", None)
        tables = record.pop("_tables", None)
        if doc_map is not None:
            maps.append(doc_map)
        if tables:
            all_tables.extend(tables)
        doc_records.append(record)

    all_slices = [sl for m in maps for sl in m.slices]
    has_key = bool(os.getenv("OPENAI_API_KEY"))

    parts: Dict[str, Any] = {
        "tables": {
            "status": "ok",
            "tableCount": len(all_tables),
            "documentsProcessed": sum(1 for r in doc_records if r.get("status") == "ok"),
        }
    }

    metadata: Dict[str, Any] = {}
    metadata_provenance: Dict[str, Any] = {}
    mechanics: List[Any] = []
    assumption_set = None

    def _skipped(reason: str) -> Dict[str, Any]:
        return {"status": "skipped", "reason": reason, "calls": 0}

    if not has_key:
        parts["metadata"] = _skipped("OPENAI_API_KEY is not set")
        parts["mechanics"] = _skipped("OPENAI_API_KEY is not set")
        parts["assumptions"] = _skipped("OPENAI_API_KEY is not set")
    elif not all_slices:
        parts["metadata"] = _skipped("no extractable document text")
        parts["mechanics"] = _skipped("no extractable document text")
        parts["assumptions"] = _skipped("no extractable document text")
    else:
        meta_result = extract_product_metadata_from_slices(
            slices=all_slices, dispatch_char_budget=budget
        )
        metadata = meta_result["metadata"]
        metadata_provenance = meta_result["provenance"]
        parts["metadata"] = {
            k: meta_result[k]
            for k in ("status", "calls", "succeeded_units", "failed_units",
                      "slices_dispatched", "slices_total", "duration_s", "unit_latencies_s")
        }
        parts["metadata"]["conflicts"] = meta_result["conflicts"]
        parts["metadata"]["model"] = os.getenv(
            "METADATA_EXTRACT_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini")
        )

        product_code = (
            str(metadata.get("product_code") or "").strip().upper()
            or str(product_code_hint or "").strip().upper()
            or "UNKNOWN"
        )

        mech_result = extract_mechanics_from_slices(
            product_code=product_code, slices=all_slices, dispatch_char_budget=budget
        )
        mechanics = mech_result["mechanics"]
        parts["mechanics"] = {
            k: mech_result[k]
            for k in ("status", "calls", "succeeded_units", "failed_units",
                      "slices_dispatched", "slices_total", "duration_s", "unit_latencies_s")
        }
        parts["mechanics"]["mergedCount"] = len(mechanics)
        parts["mechanics"]["model"] = os.getenv(
            "MECHANICS_EXTRACT_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini")
        )

        set_id = f"{doc_slug(product_code).lower()}-workspace-v1"
        asm_result = extract_assumption_set_from_slices(
            product_code=product_code,
            set_id=set_id,
            slices=all_slices,
            dispatch_char_budget=budget,
        )
        assumption_set = asm_result["assumption_set"]
        parts["assumptions"] = {
            k: asm_result[k]
            for k in ("status", "calls", "succeeded_units", "failed_units",
                      "slices_dispatched", "slices_total", "duration_s", "unit_latencies_s")
        }
        parts["assumptions"]["conflicts"] = asm_result["conflicts"]
        parts["assumptions"]["model"] = os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini")

    # Candidate fact fills from metadata (the analyze route applies the
    # fill-vs-conflict policy against the snapshot's existing facts).
    fact_fills: List[Dict[str, Any]] = []
    for field_name, label in _METADATA_FACT_LABELS.items():
        value = metadata.get(field_name)
        if value in (None, ""):
            continue
        prov = metadata_provenance.get(field_name) or {}
        doc_hint = prov.get("document_hint") or "filing"
        page_start, page_end = prov.get("page_start"), prov.get("page_end")
        if page_start is not None and page_end is not None and page_start != page_end:
            source = f"{doc_hint} pp. {page_start}-{page_end}"
        elif page_start is not None:
            source = f"{doc_hint} p. {page_start}"
        else:
            source = doc_hint
        fact_fills.append({"label": label, "value": value, "source": source})

    appended_facts: List[Dict[str, Any]] = []
    if mechanics:
        mech_part = parts.get("mechanics") or {}
        appended_facts.append(
            {
                "label": "Extracted mechanics",
                "value": [m.name for m in mechanics],
                "source": (
                    f"slice extraction: {mech_part.get('slices_dispatched')}/"
                    f"{mech_part.get('slices_total')} slices, {mech_part.get('calls')} calls"
                ),
                "confidence": None,
                "status": "extracted",
                "provenanceKind": "slice_extraction",
            }
        )
    if all_tables:
        appended_facts.append(
            {
                "label": "Extracted tables",
                "value": [
                    t.get("title") or f"Table on p. {t.get('page')}" for t in all_tables
                ],
                "source": "deterministic table channel (pdfplumber)",
                "confidence": None,
                "status": "extracted",
                "provenanceKind": "deterministic_table_channel",
            }
        )

    part_statuses = [p.get("status") for p in parts.values()]
    if all(s == "skipped" for s in part_statuses if s):
        overall = "skipped"
    elif any(s in {"partial", "failed", "skipped"} for s in part_statuses):
        # Anything short of a clean full run is reported as partial when
        # at least one part delivered, so "ok" always means complete.
        overall = "partial" if any(s == "ok" for s in part_statuses) else "failed"
    else:
        overall = "ok"
    if not doc_records or all(r.get("status") == "failed" for r in doc_records):
        overall = "failed"

    report = {
        "status": overall,
        "duration_s": round(time.monotonic() - started, 3),
        "dispatchCharBudget": budget,
        "documents": doc_records,
        "parts": parts,
        "conflicts": [],
        "totalSlices": len(all_slices),
        "totalCalls": sum(int(p.get("calls") or 0) for p in parts.values()),
    }

    return {
        "sliceExtraction": report,
        "documentMaps": [
            {
                "document": r.get("document"),
                "objectPath": r.get("objectPath"),
                "source": r.get("source"),
                "mapKey": r.get("mapKey"),
                "slicesKey": r.get("slicesKey"),
                "pageCount": r.get("pageCount"),
                "totalChars": r.get("totalChars"),
                "sliceCount": r.get("sliceCount"),
                "coverage": r.get("coverage"),
            }
            for r in doc_records
            if r.get("status") == "ok"
        ],
        "extractedTables": all_tables,
        "extractedMechanics": [asdict(m) for m in mechanics],
        "extractedAssumptionSet": asdict(assumption_set) if assumption_set is not None else None,
        "fact_fills": fact_fills,
        "appended_facts": appended_facts,
        "metadata": metadata,
        "metadataProvenance": metadata_provenance,
    }
