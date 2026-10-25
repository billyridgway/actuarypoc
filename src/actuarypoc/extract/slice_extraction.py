from __future__ import annotations

"""Slice dispatch and merging for LLM extraction.

Implements the dispatch half of the slice-extraction design (see
``docs/slice-extraction-plan.md`` §4): the existing extractors' single-call
cores are invoked once per dispatch unit (a group of consecutive document
slices within a char budget), sequentially and in document order, and the
per-unit results are merged into the same output types the extractors have
always returned.

Two trust rules are enforced here:

- **Coverage is never sampled.** Every slice is in exactly one dispatch
  unit; the run report states ``slices_dispatched`` vs ``slices_total``.
- **Evidence is re-anchored, not trusted.** Model-supplied page values are
  replaced by pages derived from locating the model's own snippet inside
  the slice text; when a snippet cannot be located, the citation degrades
  to the unit's page span and the confidence is discounted.
"""

import re
import time
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from actuarypoc.config.assumptions import AssumptionSet
from actuarypoc.domain.product_mechanics import FilingSource, ProductMechanic
from actuarypoc.extract.assumptions_extractor import (
    _assumption_set_single_call,
    _extract_metadata_single_call,
)
from actuarypoc.extract.document_map import DocumentSlice, group_slices_for_dispatch
from actuarypoc.extract.mechanics_extractor import _extract_mechanics_single_call

DEFAULT_DISPATCH_CHAR_BUDGET = 6000

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm_text(value: Any) -> str:
    return _WS.sub(" ", str(value or "")).strip().lower()


def _norm_key(value: Any) -> str:
    return _NON_ALNUM.sub("_", str(value or "").lower()).strip("_")


# ---------------------------------------------------------------------------
# Dispatch units
# ---------------------------------------------------------------------------


def unit_block(unit: Sequence[DocumentSlice]) -> str:
    """Frame a dispatch unit's slices as one provenance-labelled text block."""

    parts: List[str] = []
    for sl in unit:
        if sl.page_start is not None:
            span = (
                f"pages {sl.page_start}"
                if sl.page_start == sl.page_end
                else f"pages {sl.page_start}-{sl.page_end}"
            )
        else:
            span = f"chars {sl.char_start}-{sl.char_end}"
        header = f"[SLICE {sl.slice_id} | {sl.document_hint} | {span}"
        if sl.heading:
            header += f" | heading: {sl.heading}"
        header += "]"
        parts.append(header + "\n" + sl.text)
    return "\n\n".join(parts)


def _unit_page_span(unit: Sequence[DocumentSlice]) -> Tuple[Optional[int], Optional[int]]:
    starts = [s.page_start for s in unit if s.page_start is not None]
    ends = [s.page_end for s in unit if s.page_end is not None]
    if not starts or not ends:
        return None, None
    return min(starts), max(ends)


def _span_label(unit: Sequence[DocumentSlice]) -> str:
    start, end = _unit_page_span(unit)
    if start is None or end is None:
        if unit:
            return f"chars {unit[0].char_start}-{unit[-1].char_end}"
        return "unknown location"
    return str(start) if start == end else f"pp. {start}-{end}"


# ---------------------------------------------------------------------------
# Evidence re-anchoring
# ---------------------------------------------------------------------------


def _locate_snippet_page(unit: Sequence[DocumentSlice], snippet: Any) -> Optional[int]:
    """Find the 1-based page a snippet came from within a dispatch unit.

    Searches each slice's per-page segments: first an exact
    whitespace-normalised substring match, then a >=0.75 token-overlap
    fallback (the same approach as the workspace evidence overlay).
    """

    needle = _norm_text(snippet)
    if len(needle) < 16:
        return None
    needle_tokens = set(re.findall(r"[a-z0-9]+", needle))
    best: Optional[Tuple[float, int]] = None
    for sl in unit:
        for segment, page in sl.page_segments():
            if page is None:
                continue
            haystack = _norm_text(segment)
            if needle in haystack:
                return page
            if needle_tokens:
                hay_tokens = set(re.findall(r"[a-z0-9]+", haystack))
                score = len(needle_tokens & hay_tokens) / max(len(needle_tokens), 1)
                if score >= 0.75 and (best is None or score > best[0]):
                    best = (score, page)
    return best[1] if best else None


def reanchor_mechanic(
    mech: ProductMechanic, unit: Sequence[DocumentSlice]
) -> ProductMechanic:
    """Rewrite a mechanic's filing sources with verified pages."""

    if not unit:
        return mech
    document_hint = unit[0].document_hint
    span = _span_label(unit)
    new_sources: List[FilingSource] = []
    for fs in mech.filing_sources:
        page = _locate_snippet_page(unit, fs.snippet) if fs.snippet else None
        if page is not None:
            new_sources.append(
                replace(fs, document_hint=document_hint, page=str(page))
            )
        else:
            new_sources.append(
                replace(
                    fs,
                    document_hint=document_hint,
                    page=span,
                    confidence=round(float(fs.confidence) * 0.7, 3),
                )
            )
    if not new_sources:
        first = unit[0]
        new_sources.append(
            FilingSource(
                id=f"{mech.id}_anchor",
                document_hint=document_hint,
                page=span,
                snippet=first.text[:160],
                confidence=0.5,
            )
        )
    return replace(mech, filing_sources=new_sources)


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


def _merge_two_mechanics(a: ProductMechanic, b: ProductMechanic) -> ProductMechanic:
    """Merge ``b`` into ``a`` per the plan's merge rules."""

    seen: set = set()
    sources: List[FilingSource] = []
    for fs in list(a.filing_sources) + list(b.filing_sources):
        key = (fs.document_hint, str(fs.page), _norm_text(fs.snippet))
        if key in seen:
            continue
        seen.add(key)
        sources.append(fs)

    def _union(x: List[str], y: List[str]) -> List[str]:
        out = list(x)
        for item in y:
            if item not in out:
                out.append(item)
        return out

    if b.confidence > a.confidence or (
        b.confidence == a.confidence and len(b.description) > len(a.description)
    ):
        description = b.description
    else:
        description = a.description

    return replace(
        a,
        description=description,
        filing_sources=sources,
        upstream_ids=_union(a.upstream_ids, b.upstream_ids),
        downstream_ids=_union(a.downstream_ids, b.downstream_ids),
        confidence=max(a.confidence, b.confidence),
    )


def merge_mechanics(
    per_unit: Sequence[Sequence[ProductMechanic]], *, product_code: str
) -> List[ProductMechanic]:
    """Merge per-unit mechanics into one deduped list (document order)."""

    by_id: Dict[str, ProductMechanic] = {}
    order: List[str] = []
    for unit_mechanics in per_unit:
        for mech in unit_mechanics:
            key = _norm_key(mech.id) or _norm_key(mech.name)
            if key in by_id:
                by_id[key] = _merge_two_mechanics(by_id[key], mech)
            else:
                by_id[key] = mech
                order.append(key)

    # Pass 2: fold same (name, type) mechanics the model id'd differently.
    by_name_type: Dict[Tuple[str, str], str] = {}
    final_order: List[str] = []
    for key in order:
        mech = by_id[key]
        nt = (_norm_key(mech.name), _norm_key(mech.type))
        if nt in by_name_type:
            keep_key = by_name_type[nt]
            kept = by_id[keep_key]
            merged = _merge_two_mechanics(kept, mech)
            if len(mech.filing_sources) > len(kept.filing_sources):
                merged = replace(merged, id=mech.id)
            by_id[keep_key] = merged
        else:
            by_name_type[nt] = key
            final_order.append(key)

    merged_list = [by_id[key] for key in final_order]
    code_norm = (product_code or "").strip().upper()
    return [replace(m, product_code=code_norm) for m in merged_list]


_METADATA_FIELDS = (
    "carrier_name",
    "product_name",
    "product_code",
    "product_type",
    "primary_filing_id",
)


def merge_metadata(
    per_unit: Sequence[Tuple[Dict[str, Any], Sequence[DocumentSlice]]]
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Field-wise first-non-null merge with provenance and conflicts."""

    merged: Dict[str, Any] = {f: None for f in _METADATA_FIELDS}
    provenance: Dict[str, Any] = {}
    conflicts: List[Dict[str, Any]] = []
    for unit_index, (meta, unit) in enumerate(per_unit):
        start, end = _unit_page_span(unit)
        for field_name in _METADATA_FIELDS:
            value = meta.get(field_name)
            if value in (None, ""):
                continue
            if merged[field_name] in (None, ""):
                merged[field_name] = value
                provenance[field_name] = {
                    "slice_ids": [s.slice_id for s in unit],
                    "document_hint": unit[0].document_hint if unit else None,
                    "page_start": start,
                    "page_end": end,
                    "unit_index": unit_index,
                }
            elif str(merged[field_name]).strip().lower() != str(value).strip().lower():
                conflicts.append(
                    {
                        "field": field_name,
                        "kept": merged[field_name],
                        "rejected": value,
                        "slice_ids": [s.slice_id for s in unit],
                        "page_start": start,
                        "page_end": end,
                    }
                )
    return merged, provenance, conflicts


_ASSUMPTION_SCALAR_FIELDS = (
    "dsl_file",
    "actuarial_prefix",
    "created_by",
)


def _assumption_completeness(asn: AssumptionSet) -> int:
    values = [asn.description, asn.dsl_file, asn.actuarial_prefix, asn.created_by]
    return sum(1 for v in values if v not in (None, ""))


def merge_assumption_sets(
    per_unit: Sequence[Tuple[AssumptionSet, Sequence[DocumentSlice]]],
    *,
    product_code: str,
    set_id: str,
) -> Tuple[AssumptionSet, List[Dict[str, Any]]]:
    """Merge per-unit AssumptionSets (first-non-empty wins; conflicts noted)."""

    if not per_unit:
        raise ValueError("no per-unit assumption sets to merge")

    conflicts: List[Dict[str, Any]] = []
    merged_values: Dict[str, Any] = {f: None for f in _ASSUMPTION_SCALAR_FIELDS}
    for asn, unit in per_unit:
        start, end = _unit_page_span(unit)
        for field_name in _ASSUMPTION_SCALAR_FIELDS:
            value = getattr(asn, field_name)
            if value in (None, ""):
                continue
            if merged_values[field_name] in (None, ""):
                merged_values[field_name] = value
            elif merged_values[field_name] != value:
                conflicts.append(
                    {
                        "field": field_name,
                        "kept": merged_values[field_name],
                        "rejected": value,
                        "slice_ids": [s.slice_id for s in unit],
                        "page_start": start,
                        "page_end": end,
                    }
                )

    best = max((asn for asn, _ in per_unit), key=_assumption_completeness)
    merged = AssumptionSet(
        id=set_id,
        product_code=(product_code or "").strip().upper(),
        description=best.description or "",
        dsl_file=merged_values["dsl_file"] or best.dsl_file or "",
        actuarial_prefix=merged_values["actuarial_prefix"],
        status="draft",
        is_current=False,
        created_at=None,
        created_by=merged_values["created_by"],
        approved_at=None,
        approved_by=None,
    )
    return merged, conflicts


# ---------------------------------------------------------------------------
# Dispatch drivers
# ---------------------------------------------------------------------------


def _base_report(slices: Sequence[DocumentSlice]) -> Dict[str, Any]:
    return {
        "status": "skipped" if not slices else "failed",
        "calls": 0,
        "succeeded_units": 0,
        "failed_units": [],
        "slices_dispatched": 0,
        "slices_total": len(slices),
        "duration_s": 0.0,
        "unit_latencies_s": [],
    }


def _finish_report(report: Dict[str, Any], t0: float) -> Dict[str, Any]:
    report["duration_s"] = round(time.monotonic() - t0, 3)
    if report["succeeded_units"] and report["failed_units"]:
        report["status"] = "partial"
    elif report["succeeded_units"]:
        report["status"] = "ok"
    elif report["failed_units"]:
        report["status"] = "failed"
    return report


def extract_mechanics_from_slices(
    *,
    product_code: str,
    slices: Sequence[DocumentSlice],
    model: Optional[str] = None,
    dispatch_char_budget: int = DEFAULT_DISPATCH_CHAR_BUDGET,
) -> Dict[str, Any]:
    """Dispatch mechanics extraction over slices and merge the results."""

    t0 = time.monotonic()
    report = _base_report(slices)
    per_unit: List[List[ProductMechanic]] = []
    for unit in group_slices_for_dispatch(list(slices), char_budget=dispatch_char_budget):
        report["calls"] += 1
        report["slices_dispatched"] += len(unit)
        unit_t0 = time.monotonic()
        try:
            raw = _extract_mechanics_single_call(
                product_code=product_code, text=unit_block(unit), model=model
            )
            per_unit.append([reanchor_mechanic(m, unit) for m in raw])
            report["succeeded_units"] += 1
        except Exception as exc:  # noqa: BLE001 - per-unit isolation by design
            report["failed_units"].append(
                {
                    "slice_ids": [s.slice_id for s in unit],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        report["unit_latencies_s"].append(round(time.monotonic() - unit_t0, 3))
    report["mechanics"] = merge_mechanics(per_unit, product_code=product_code)
    return _finish_report(report, t0)


def extract_product_metadata_from_slices(
    *,
    slices: Sequence[DocumentSlice],
    model: Optional[str] = None,
    dispatch_char_budget: int = DEFAULT_DISPATCH_CHAR_BUDGET,
) -> Dict[str, Any]:
    """Dispatch metadata extraction over slices; merge field-wise."""

    t0 = time.monotonic()
    report = _base_report(slices)
    per_unit: List[Tuple[Dict[str, Any], Sequence[DocumentSlice]]] = []
    for unit in group_slices_for_dispatch(list(slices), char_budget=dispatch_char_budget):
        report["calls"] += 1
        report["slices_dispatched"] += len(unit)
        unit_t0 = time.monotonic()
        try:
            meta = _extract_metadata_single_call(text=unit_block(unit), model=model)
            per_unit.append((meta, unit))
            report["succeeded_units"] += 1
        except Exception as exc:  # noqa: BLE001
            report["failed_units"].append(
                {
                    "slice_ids": [s.slice_id for s in unit],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        report["unit_latencies_s"].append(round(time.monotonic() - unit_t0, 3))
    merged, provenance, conflicts = merge_metadata(per_unit)
    # Refine provenance to the individual slice that contains the
    # winning value, when it can be located verbatim (or whitespace-
    # normalised) — unit-level spans are the fallback.
    for field_name, prov in provenance.items():
        value = merged.get(field_name)
        unit = per_unit[prov["unit_index"]][1]
        located = None
        for sl in unit:
            if value and (str(value) in sl.text or _norm_text(value) in _norm_text(sl.text)):
                located = sl
                break
        if located is not None:
            prov["slice_ids"] = [located.slice_id]
            prov["page_start"] = located.page_start
            prov["page_end"] = located.page_end
        prov.pop("unit_index", None)
    report["metadata"] = merged
    report["provenance"] = provenance
    report["conflicts"] = conflicts
    return _finish_report(report, t0)


def extract_assumption_set_from_slices(
    *,
    product_code: str,
    set_id: str,
    slices: Sequence[DocumentSlice],
    description_hint: Optional[str] = None,
    model: Optional[str] = None,
    dispatch_char_budget: int = DEFAULT_DISPATCH_CHAR_BUDGET,
) -> Dict[str, Any]:
    """Dispatch AssumptionSet extraction over slices and merge."""

    t0 = time.monotonic()
    report = _base_report(slices)
    per_unit: List[Tuple[AssumptionSet, Sequence[DocumentSlice]]] = []
    for unit in group_slices_for_dispatch(list(slices), char_budget=dispatch_char_budget):
        report["calls"] += 1
        report["slices_dispatched"] += len(unit)
        unit_t0 = time.monotonic()
        try:
            asn = _assumption_set_single_call(
                product_code=product_code,
                text=unit_block(unit),
                set_id=set_id,
                description_hint=description_hint,
                model=model,
            )
            per_unit.append((asn, unit))
            report["succeeded_units"] += 1
        except Exception as exc:  # noqa: BLE001
            report["failed_units"].append(
                {
                    "slice_ids": [s.slice_id for s in unit],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        report["unit_latencies_s"].append(round(time.monotonic() - unit_t0, 3))
    if per_unit:
        merged, conflicts = merge_assumption_sets(
            per_unit, product_code=product_code, set_id=set_id
        )
        report["assumption_set"] = merged
        report["conflicts"] = conflicts
    else:
        report["assumption_set"] = None
        report["conflicts"] = []
    return _finish_report(report, t0)
