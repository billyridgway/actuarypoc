"""Phase 2 (the chassis): the workspace mechanics panel.

Eddy (Aug 7, 2026) asked for a pre-built UL chassis whose inputs live in
editable slots — "What is your surrender charge schedule? What are your
policy fees? What does your net amount at risk calculation look like?" —
instead of a document-first flow where every retune means re-uploading a
filing.  This module is the server-side half of that panel:

* slot derivation — each mechanic the chassis needs (COI schedule,
  surrender schedule, policy/admin fees, NAR factor, corridor / minimum
  death benefit, interest crediting) presented with its status, current
  values, and provenance, derived from the existing mechanics artifact
  (``usable`` / ``candidates`` / ``synthetic`` / ``workspaceEdits``);
* slot edits — validated by exactly the row validators ingestion uses
  (``_parse_row``) plus the same completeness rules (``usable_mechanics``),
  so an edit can never write a table the projection could not execute;
* change records — every edit summarised (who, when, slot, prior -> new)
  for the persisted audit log;
* gap mapping — the snapshot's gap items annotated with the slot that
  resolves them, so the gaps list and the panel are one source of truth.

Workspace edits live in the artifact under ``workspaceEdits`` and are
re-applied onto the fresh artifact each analysis builds from documents,
so an edit survives re-runs (see ``reapply_workspace_edits``).  Edited
rows carry ``sourceType: "workspace_edit"`` provenance, which the Phase 1
ledger labels honestly as a workspace table.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
from typing import Any, Dict, List, Optional, Sequence
import uuid

from actuarypoc.extract import workspace_equations as _ws_equations
from actuarypoc.extract.workspace_ul_mechanics import (
    _name,
    _parse_row,
    _read_tables,
    candidate_diff,
    candidate_group_key,
    candidate_provenance,
    candidate_selector_summary,
    rows_coverage_text,
    usable_mechanics,
)


MECHANIC_SLOTS: List[Dict[str, Any]] = [
    {"id": "coi", "mechanic": "coi", "label": "COI schedule", "kind": "table"},
    {"id": "surrender", "mechanic": "surrender", "label": "Surrender schedule", "kind": "table"},
    {"id": "fees", "mechanic": "fees", "label": "Policy and admin fees", "kind": "table"},
    {"id": "nar", "mechanic": "nar_factors", "label": "Net amount at risk (NAR) factor", "kind": "scalar"},
    {"id": "corridor", "mechanic": "corridor", "label": "Corridor / minimum death benefit", "kind": "table"},
    {"id": "crediting", "mechanic": None, "label": "Interest crediting (guaranteed rate)", "kind": "display"},
]

SLOT_BY_ID: Dict[str, Dict[str, Any]] = {slot["id"]: slot for slot in MECHANIC_SLOTS}

# The projection-gap ids the workspace view emits (see
# ``_build_ul_projection_view``) and the slot that resolves each one.
GAP_SLOT_MAP: Dict[str, str] = {
    # Phase 7 gap ids (missing-equation states) plus the legacy ids,
    # which can still appear in snapshots stored before Phase 7.
    "missing_coi_equation": "coi",
    "missing_surrender_equation": "surrender",
    "missing_policy_fees_equation": "fees",
    "missing_nar_equation": "nar",
    "missing_crediting_equation": "crediting",
    "missing_coi_table": "coi",
    "surrender_schedule_placeholder": "surrender",
    "policy_admin_fee_missing": "fees",
}

STATUS_LABELS: Dict[str, str] = {
    "filed_accepted": "Filed (accepted)",
    "filed_pending_review": "Filed (pending review)",
    "synthetic": "Synthetic",
    "workspace_table": "Workspace table",
    "corrected": "Corrected",
    "configured": "Configured",
    "missing": "Missing",
}

_EDIT_SOURCE_TYPE = "workspace_edit"


def annotate_gap_items(gap_items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return gap items with the resolving ``slotId`` added where one exists."""

    annotated: List[Dict[str, Any]] = []
    for item in gap_items or []:
        row = dict(item)
        slot_id = GAP_SLOT_MAP.get(str(item.get("id") or ""))
        if slot_id:
            row["slotId"] = slot_id
        annotated.append(row)
    return annotated


# ---------------------------------------------------------------------------
# Filing-review reconciliation (Oct 27, 2026)
#
# The workbench header shows the last analysis's compliance snapshot —
# implemented / partial / missing counts and open gaps, frozen at
# analysis time by design.  Frozen reads as current, though: a
# requirement the analysis counted missing can come into force minutes
# later through approvals, and the header never said so.  This
# reconciliation is computed LIVE against the current artifact on
# every read: the snapshot counts do not change, but the payload
# names what has since come into force, and the header appends it.
# ---------------------------------------------------------------------------

#: Snapshot requirement ids (the UL catalogue ids in
#: domain/ul_requirements.py, plus their field-evidence ids) and the
#: slot whose in-force state satisfies the requirement.
REQUIREMENT_SLOT_MAP: Dict[str, str] = {
    "coi_table": "coi",
    "coi_rates": "coi",
    "surrender_schedule": "surrender",
    "policy_admin_fees": "fees",
    "policy_admin_fee": "fees",
}

#: The equation that must be approved for a slot to count as in force
#: in the reconciliation — a filed table alone does not calculate
#: without its equation.  (The fees slot's equation is policy_fees;
#: premium_load is a separate mechanic that reads the same table.)
SLOT_EQUATION_MECHANIC: Dict[str, str] = {
    "coi": "coi_charge",
    "surrender": "surrender_charge",
    "fees": "policy_fees",
    "nar": "nar_definition",
    "corridor": "death_benefit",
    "crediting": "crediting",
}


def _slot_now_in_force(artifact: Dict[str, Any], slot_id: str) -> bool:
    """Whether a slot can calculate NOW: its filed table is in force
    (usable rows present) and its equation is approved."""

    slot = SLOT_BY_ID.get(slot_id) or {}
    mechanic = slot.get("mechanic")
    if mechanic:
        rows = list((artifact.get("usable") or {}).get(str(mechanic)) or [])
        if not rows:
            return False
    equation_mechanic = SLOT_EQUATION_MECHANIC.get(slot_id)
    if equation_mechanic is not None:
        return _ws_equations.in_force(artifact, equation_mechanic) is not None
    return True


def _requirement_slot(requirement: Dict[str, Any]) -> Optional[str]:
    slot_id = REQUIREMENT_SLOT_MAP.get(str(requirement.get("id") or ""))
    if slot_id:
        return slot_id
    for evidence in requirement.get("evidence") or []:
        slot_id = REQUIREMENT_SLOT_MAP.get(str((evidence or {}).get("id") or ""))
        if slot_id:
            return slot_id
    return None


#: The table mechanics whose filed candidates / in-force rows evidence
#: document coverage for a slot (the artifact's table keys).
TABLE_MECHANICS: Sequence[str] = ("coi", "surrender", "fees", "nar_factors", "corridor")


def document_coverage(
    artifact: Dict[str, Any], slices: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """Document coverage for the workspace's mechanics and tables.

    Gap semantics (Billy, Oct 27, 2026): "missing" means missing FROM
    THE DOCUMENTS.  ``equations`` is the per-mechanic three-state
    coverage from :func:`workspace_equations.equation_document_coverage`;
    ``tables`` marks each table mechanic covered when the analysis
    extracted a filed candidate for it or rows are already in force —
    either way the documents state the table and we hold the evidence.
    """

    artifact = artifact or {}
    tables = {
        mechanic: bool(
            (artifact.get("candidates") or {}).get(mechanic)
            or (artifact.get("usable") or {}).get(mechanic)
        )
        for mechanic in TABLE_MECHANICS
    }
    return {
        "equations": _ws_equations.equation_document_coverage(artifact, slices),
        "tables": tables,
    }


def apply_document_coverage_to_requirements(
    snapshot: Dict[str, Any], coverage: Dict[str, Any]
) -> None:
    """Relabel analysis-time requirement statuses with document semantics.

    Runs at analysis finalization (after the holistic review, so a
    review-found candidate counts), before readiness counts are
    reconciled.  A requirement the bare projection snapshot counted
    "missing" purely because nothing was approved yet is rewritten to
    the distinct ``covered`` state when the documents cover it — a
    filed table candidate or an evidenced equation candidate for its
    slot.  Genuinely uncovered requirements keep "missing": that word
    now means not covered by the documents.
    """

    matrix = (snapshot or {}).get("complianceMatrix") or {}
    requirements = list(matrix.get("requirements") or [])
    if not requirements:
        return
    equations = (coverage or {}).get("equations") or {}
    tables = (coverage or {}).get("tables") or {}
    classified = {
        str(entry.get("id") or ""): entry
        for entry in ((snapshot.get("requirementsClassification") or {}).get("all") or [])
        if isinstance(entry, dict)
    }
    for requirement in requirements:
        if str(requirement.get("status") or "").lower() != "missing":
            continue
        slot_id = _requirement_slot(requirement)
        if slot_id is None:
            continue
        slot = SLOT_BY_ID.get(slot_id) or {}
        table_mechanic = slot.get("mechanic")
        table_covered = bool(table_mechanic and tables.get(str(table_mechanic)))
        equation_mechanic = SLOT_EQUATION_MECHANIC.get(slot_id)
        equation_covered = bool(
            equation_mechanic
            and (equations.get(str(equation_mechanic)) or {}).get("state") == "covered"
        )
        if not (table_covered or equation_covered):
            continue
        requirement["status"] = "covered"
        classification = requirement.setdefault("classification", {})
        if isinstance(classification, dict):
            classification["implementationState"] = "covered"
        requirement["documentCoverage"] = {
            "covered": True,
            "basis": (
                "filed table extracted from the documents"
                if table_covered
                else "equation candidate extracted from the documents"
            ),
        }
        entry = classified.get(str(requirement.get("id") or ""))
        if entry is not None:
            entry["implementationState"] = "covered"


def filing_review_reconciliation(
    snapshot: Dict[str, Any], artifact: Dict[str, Any]
) -> Dict[str, Any]:
    """What has come into force since the snapshot's analysis ran.

    Returns the analysis-time counts (from the snapshot's own
    summary, so they always match the header's frozen counts), the
    requirements the analysis counted missing/partial that are NOW
    in force, the snapshot gaps whose subject is NOW resolved, and
    a ready-to-render ``text`` clause — None when nothing has
    changed since the analysis, in which case the header shows the
    frozen line alone.
    """

    snapshot = snapshot or {}
    artifact = artifact or {}
    matrix = snapshot.get("complianceMatrix") or {}
    requirements = list(matrix.get("requirements") or [])
    summary = matrix.get("summary") or {}
    missing = int(summary.get("missing") or 0)
    partial = int(summary.get("partial") or 0)
    covered = int(summary.get("covered") or 0)
    if not summary:
        missing = sum(
            1 for r in requirements
            if (r.get("classification") or {}).get("implementationState") == "not_implemented"
        )
        partial = sum(
            1 for r in requirements
            if (r.get("classification") or {}).get("implementationState") == "partial"
        )
        covered = sum(
            1 for r in requirements
            if (r.get("classification") or {}).get("implementationState") == "covered"
        )
    gap_items = list(((snapshot.get("gaps") or {}).get("items")) or [])

    resolved_requirements: List[Dict[str, Any]] = []
    for requirement in requirements:
        state = (requirement.get("classification") or {}).get("implementationState")
        if state not in {"not_implemented", "partial", "covered"}:
            continue
        slot_id = _requirement_slot(requirement)
        if slot_id is None or not _slot_now_in_force(artifact, slot_id):
            continue
        resolved_requirements.append({
            "id": str(requirement.get("id") or ""),
            "name": str(requirement.get("name") or requirement.get("id") or ""),
            "stateAtAnalysis": state,
        })

    resolved_gaps: List[Dict[str, Any]] = []
    for gap in gap_items:
        slot_id = GAP_SLOT_MAP.get(str(gap.get("id") or ""))
        if slot_id is None or not _slot_now_in_force(artifact, slot_id):
            continue
        resolved_gaps.append({
            "id": str(gap.get("id") or ""),
            "title": str(gap.get("title") or gap.get("id") or ""),
        })

    # Review-sourced reconciliation (Billy, Oct 27, 2026, "also
    # reconciling the compliance header"): the holistic review runs
    # inside the analysis job, and when its self-checks / re-reads /
    # reconciliation cases change what the analysis concluded — a
    # requirement snapshotted as missing whose equation the review
    # actually FOUND — that is named here too, computed from the
    # review record, with the same provenance discipline (what was
    # found, by which check, with rationale).  The snapshot stays
    # frozen; approval-driven reconciliation above is untouched; a
    # requirement the review found nothing for stays missing.
    review: Dict[str, Any] = {}
    if isinstance(artifact.get("holisticReview"), dict):
        review = artifact["holisticReview"] or {}
    elif isinstance(snapshot.get("holisticReview"), dict):
        review = snapshot["holisticReview"] or {}
    _review_equation_slot = {
        "coi_charge": "coi", "surrender_charge": "surrender",
        "premium_load": "fees", "policy_fees": "fees",
        "nar_definition": "nar", "death_benefit": "corridor",
        "crediting": "crediting",
    }
    _review_table_slot = {
        str(slot.get("mechanic")): str(slot.get("id"))
        for slot in MECHANIC_SLOTS if slot.get("mechanic")
    }
    found_by_slot: Dict[str, Dict[str, Any]] = {}
    for entry in review.get("found") or []:
        if not isinstance(entry, dict):
            continue
        slot_id = entry.get("slot") or _review_equation_slot.get(
            str(entry.get("mechanic") or "")
        ) or _review_table_slot.get(str(entry.get("mechanic") or ""))
        if slot_id and str(slot_id) not in found_by_slot:
            found_by_slot[str(slot_id)] = entry

    resolved_ids = {item["id"] for item in resolved_requirements}
    review_resolved_requirements: List[Dict[str, Any]] = []
    for requirement in requirements:
        state = (requirement.get("classification") or {}).get("implementationState")
        if state not in {"not_implemented", "partial", "covered"}:
            continue
        if str(requirement.get("id") or "") in resolved_ids:
            continue
        slot_id = _requirement_slot(requirement)
        if slot_id is None or slot_id not in found_by_slot:
            continue
        entry = found_by_slot[slot_id]
        review_resolved_requirements.append({
            "id": str(requirement.get("id") or ""),
            "name": str(requirement.get("name") or requirement.get("id") or ""),
            "foundByReview": True,
            "check": entry.get("check"),
            "rationale": entry.get("rationale"),
            "filename": entry.get("filename"),
            "page": entry.get("page"),
        })

    resolved_gap_ids = {item["id"] for item in resolved_gaps}
    review_resolved_gaps: List[Dict[str, Any]] = []
    for gap in gap_items:
        if str(gap.get("id") or "") in resolved_gap_ids:
            continue
        slot_id = GAP_SLOT_MAP.get(str(gap.get("id") or ""))
        if slot_id is None or slot_id not in found_by_slot:
            continue
        entry = found_by_slot[slot_id]
        review_resolved_gaps.append({
            "id": str(gap.get("id") or ""),
            "title": str(gap.get("title") or gap.get("id") or ""),
            "foundByReview": True,
            "check": entry.get("check"),
            "rationale": entry.get("rationale"),
        })

    parts: List[str] = []
    if resolved_requirements:
        counts = []
        if missing:
            counts.append(f"{missing} missing")
        if partial:
            counts.append(f"{partial} partial")
        # With the gap semantics (Oct 27, 2026) a requirement can have
        # been "covered" at analysis — stated in the documents, not yet
        # approved.  Name that count too when a covered requirement is
        # among the resolved ones, so the clause never claims a
        # covered requirement was counted missing.
        if covered and any(
            item.get("stateAtAnalysis") == "covered" for item in resolved_requirements
        ):
            counts.append(f"{covered} covered")
        names = ", ".join(item["name"] for item in resolved_requirements)
        parts.append(f"{' · '.join(counts)} at analysis — now in force: {names}")
    if resolved_gaps:
        titles = ", ".join(item["title"] for item in resolved_gaps)
        parts.append(
            f"{len(gap_items)} open gap"
            + ("s" if len(gap_items) != 1 else "")
            + f" at analysis — now resolved: {titles}"
        )
    if review_resolved_requirements:
        names = ", ".join(item["name"] for item in review_resolved_requirements)
        first = review_resolved_requirements[0]
        parts.append(
            f"found by the holistic review ({first.get('check') or 'self-check'}): "
            f"{names}"
            + (f" — {first['rationale']}" if first.get("rationale") else "")
        )
    if review_resolved_gaps:
        titles = ", ".join(item["title"] for item in review_resolved_gaps)
        parts.append(
            f"open gap at analysis — found by the holistic review: {titles}"
        )
    return {
        "missingAtAnalysis": missing,
        "partialAtAnalysis": partial,
        "coveredAtAnalysis": covered,
        "openGapsAtAnalysis": len(gap_items),
        "resolvedRequirements": resolved_requirements,
        "resolvedGaps": resolved_gaps,
        "reviewResolvedRequirements": review_resolved_requirements,
        "reviewResolvedGaps": review_resolved_gaps,
        "text": "; ".join(parts) if parts else None,
    }


def _rows_digest(rows: Sequence[Dict[str, Any]]) -> str:
    payload = json.dumps(list(rows), sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def _summarize_rows(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {"rowCount": len(rows), "digest": _rows_digest(rows)}


def _provenance_views(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: List[Dict[str, Any]] = []
    for row in rows:
        provenance = row.get("provenance") or {}
        view = {
            "filename": provenance.get("filename"),
            "page": provenance.get("page"),
            "tableHeading": provenance.get("tableHeading"),
            "sourceType": provenance.get("sourceType"),
            "reviewStatus": provenance.get("reviewStatus"),
        }
        if any(value is not None for value in view.values()) and view not in seen:
            seen.append(view)
    return seen


def _slot_status(artifact: Dict[str, Any], mechanic: str) -> str:
    """Derive a slot's status from the mechanics artifact's own state."""

    # Phase 3: an active correction outranks every other state — it is
    # the actuary's explicit statement of how the calculation should work.
    if mechanic in (artifact.get("corrections") or {}):
        return "corrected"
    edits = artifact.get("workspaceEdits") or {}
    if mechanic in edits:
        return "workspace_table"
    if (artifact.get("synthetic") or {}).get(mechanic):
        return "synthetic"
    usable_rows = list((artifact.get("usable") or {}).get(mechanic) or [])
    if usable_rows:
        if any(
            (row.get("provenance") or {}).get("sourceType") == "filed_pdf"
            and (row.get("provenance") or {}).get("reviewStatus") == "accepted"
            for row in usable_rows
        ):
            return "filed_accepted"
        return "workspace_table"
    candidates = list((artifact.get("candidates") or {}).get(mechanic) or [])
    if any(c.get("reviewStatus") == "review_required" for c in candidates):
        return "filed_pending_review"
    raw_rows = list((artifact.get("mechanics") or {}).get(mechanic) or [])
    if any(
        (row.get("provenance") or {}).get("reviewStatus") == "review_required"
        for row in raw_rows
    ):
        return "filed_pending_review"
    return "missing"


def _pending_candidate_count(artifact: Dict[str, Any], mechanic: str) -> int:
    candidates = list((artifact.get("candidates") or {}).get(mechanic) or [])
    return sum(1 for c in candidates if c.get("reviewStatus") == "review_required")


def _pending_candidate_views(artifact: Dict[str, Any], mechanic: str) -> List[Dict[str, Any]]:
    views: List[Dict[str, Any]] = []
    for candidate in (artifact.get("candidates") or {}).get(mechanic) or []:
        if candidate.get("reviewStatus") != "review_required":
            continue
        provenance = candidate_provenance(candidate)
        views.append({
            "id": candidate.get("id"),
            "filename": provenance["filename"],
            "page": provenance["page"],
            "tableHeading": provenance["tableHeading"],
            "sources": provenance["sources"],
            "rowCount": candidate.get("rowCount"),
            "valueBasis": candidate.get("valueBasis"),
        })
    return views


def _candidate_views(artifact: Dict[str, Any], mechanic: str) -> List[Dict[str, Any]]:
    """Every filed candidate for a slot, with its own state.

    Candidates are selector slices of one table (Oct 27 model):
    each is in force or not on its own — several can be in force
    together, their rows unioned — so the view reports per-candidate
    state (in force, awaiting review, superseded, and how many of
    its rows an override decision took out of force), plus how its
    rows compare with the first candidate in force (identical rows
    dedupe; rows only it carries are added coverage; rows priced
    differently are the conflict region).
    """

    candidates = [
        candidate
        for candidate in (artifact.get("candidates") or {}).get(mechanic) or []
        if isinstance(candidate, dict)
    ]
    if not candidates:
        return []
    reference = next(
        (c for c in candidates if c.get("reviewStatus") == "accepted"),
        candidates[0],
    )
    views: List[Dict[str, Any]] = []
    for candidate in candidates:
        rows = list(candidate.get("rows") or [])
        group = candidate_group_key(mechanic, candidate)
        overridden = {
            tuple(item)
            for item in candidate.get("overriddenSelectors") or []
            if isinstance(item, (list, tuple))
        }
        provenance = candidate_provenance(candidate)
        view: Dict[str, Any] = {
            "id": candidate.get("id"),
            "filename": provenance["filename"],
            "page": provenance["page"],
            "tableHeading": provenance["tableHeading"],
            "sources": provenance["sources"],
            "rowCount": candidate.get("rowCount") or len(rows),
            "valueBasis": candidate.get("valueBasis"),
            "reviewStatus": candidate.get("reviewStatus"),
            "inForce": candidate.get("reviewStatus") == "accepted",
            "group": sorted(group[1]),
            "coverageText": rows_coverage_text(rows),
            "selectors": candidate_selector_summary(rows),
            "overriddenRowCount": len(overridden),
            "overriddenBy": candidate.get("overriddenBy"),
            "diffVsReference": None,
        }
        if candidate is not reference:
            view["diffVsReference"] = candidate_diff(
                list(reference.get("rows") or []), rows, mechanic
            )
            view["referenceCandidateId"] = reference.get("id")
            view["referenceInForce"] = reference.get("reviewStatus") == "accepted"
        views.append(view)
    return views


def _crediting_view(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Display-only crediting slot, derived from the latest snapshot."""

    snapshot = snapshot or {}
    rate: Any = None
    source: Optional[str] = None
    ledger_rows = (((snapshot.get("illustration") or {}).get("ledger") or {}).get("rows") or [])
    if ledger_rows:
        for component in ledger_rows[0].get("components") or []:
            if component.get("id") == "interest":
                for item in component.get("inputs") or []:
                    if item.get("label") == "Guaranteed annual credited rate":
                        rate = item.get("value")
                break
    if rate is None:
        for item in (snapshot.get("assumptions") or {}).get("provenance") or []:
            if str(item.get("name") or "").strip().lower() == "guaranteed credited rate":
                rate = item.get("value")
                source = item.get("source")
                break
    status = "configured" if rate is not None else "missing"
    return {
        "id": "crediting",
        "mechanic": None,
        "label": "Interest crediting (guaranteed rate)",
        "kind": "display",
        "status": status,
        "statusLabel": STATUS_LABELS[status],
        "editable": False,
        # Provenance honesty (revamp): this value is an assumption
        # from the product's runtime configuration, NOT a value read
        # from the filing — the payload says so in terms, and the UI
        # styles it distinctly from filing-derived values.
        "sourceKind": "assumption",
        "sourceLabel": (
            "Assumption — set in the product's runtime configuration; "
            "not read from the filing"
        ),
        "value": rate,
        "provenance": (
            [{"filename": None, "page": None, "tableHeading": None,
              "sourceType": "runtime_config", "reviewStatus": None, "source": source}]
            if rate is not None else []
        ),
        "pendingCandidateCount": 0,
        "pendingCandidates": [],
        "editedInWorkspace": False,
        "lastEdit": None,
    }


def correction_view(record: Dict[str, Any]) -> Dict[str, Any]:
    """The panel view of one active correction (Phase 3)."""

    replaces = (record or {}).get("replaces") or {}
    return {
        "id": record.get("id"),
        "slot": record.get("slot"),
        "mechanic": record.get("mechanic"),
        "variant": record.get("variant"),
        "params": record.get("params"),
        "text": record.get("text"),
        "who": record.get("who"),
        "at": record.get("at"),
        "confirmBack": record.get("confirmBack"),
        "replaces": {
            "status": replaces.get("status"),
            "description": replaces.get("description"),
        },
        # Flattened for the panel UI: a filed override must be loud.
        "replacedStatus": replaces.get("status"),
        "replacedDescription": replaces.get("description"),
        "replacedWasFiled": replaces.get("status")
        in {"filed_accepted", "filed_pending_review"},
    }


def build_slot_view(
    artifact: Dict[str, Any], slot: Dict[str, Any], snapshot: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Build the API view of one slot from the mechanics artifact."""

    if slot["kind"] == "display":
        return _crediting_view(snapshot)
    mechanic = str(slot["mechanic"])
    usable_rows = list((artifact.get("usable") or {}).get(mechanic) or [])
    edits = artifact.get("workspaceEdits") or {}
    edit = edits.get(mechanic) or {}
    status = _slot_status(artifact, mechanic)
    correction = (artifact.get("corrections") or {}).get(mechanic)
    view: Dict[str, Any] = {
        "id": slot["id"],
        "mechanic": mechanic,
        "label": slot["label"],
        "kind": slot["kind"],
        "status": status,
        "statusLabel": STATUS_LABELS[status],
        "editable": True,
        "rowCount": len(usable_rows),
        "coverageText": rows_coverage_text(usable_rows),
        "rows": usable_rows,
        "provenance": _provenance_views(usable_rows),
        "pendingCandidateCount": _pending_candidate_count(artifact, mechanic),
        "pendingCandidates": _pending_candidate_views(artifact, mechanic),
        "candidates": _candidate_views(artifact, mechanic),
        "editedInWorkspace": mechanic in edits,
        "lastEdit": (
            {"at": edit.get("updatedAt"), "who": edit.get("updatedBy")}
            if mechanic in edits else None
        ),
        "correction": correction_view(correction) if correction else None,
    }
    if slot["kind"] == "scalar":
        view["value"] = (usable_rows[0].get("factor") if usable_rows else None)
    return view


def build_mechanics_panel(
    artifact: Dict[str, Any],
    *,
    snapshot: Optional[Dict[str, Any]] = None,
    gaps: Optional[List[Dict[str, Any]]] = None,
    changes: Optional[List[Dict[str, Any]]] = None,
    workspace: Optional[Dict[str, Any]] = None,
    correction_requests: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble the full panel payload for one workspace."""

    artifact = artifact or {}
    workspace = workspace or {}
    corrections = [
        correction_view(record)
        for record in (artifact.get("corrections") or {}).values()
        if isinstance(record, dict)
    ]
    corrections.sort(key=lambda record: str(record.get("at") or ""), reverse=True)
    return {
        "workspaceId": workspace.get("id"),
        "slots": [
            build_slot_view(artifact, slot, snapshot) for slot in MECHANIC_SLOTS
        ],
        "gaps": annotate_gap_items(list(gaps or [])),
        "changeLog": list(reversed(list(changes or [])))[:50],
        "corrections": corrections,
        "correctionRequests": list(correction_requests or []),
        "projectionStale": bool(workspace.get("projection_stale")),
        "projectionStaleSince": workspace.get("projection_stale_since"),
        "projectionStaleSlots": list(workspace.get("projection_stale_slots") or []),
    }


# ---------------------------------------------------------------------------
# Edit validation — the same validators ingestion uses
# ---------------------------------------------------------------------------


def _validate_canonical_rows(mechanic: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate canonical rows for one mechanic; raise ValueError on any defect.

    ``rows`` are dicts in the stored row shape (``duration``, ``rate``,
    ``rate_unit`` ...).  Each row is re-parsed through the ingestion
    validator (``_parse_row``) and the resulting set must satisfy the
    same completeness rules that make a table executable at ingestion
    (``usable_mechanics``).  Nothing is written anywhere by this helper:
    an edit either validates completely or is rejected whole.
    """

    if not rows:
        raise ValueError(f"No {mechanic} rows were supplied")
    canonical: List[Dict[str, Any]] = []
    errors: List[str] = []
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            errors.append(f"row {index}: expected an object of table fields")
            continue
        candidate = {key: value for key, value in raw.items() if key != "provenance"}
        try:
            canonical.append(_parse_row(mechanic, candidate))
        except ValueError as exc:
            errors.append(f"row {index}: {exc}")
    if errors:
        raise ValueError("; ".join(errors))

    selector_fields = (
        "duration", "attained_age", "sex", "risk_class", "tobacco_status", "premium_mode",
    )
    seen: set = set()
    for row in canonical:
        selector = tuple(row.get(field) for field in selector_fields)
        if selector in seen:
            raise ValueError(f"duplicate {mechanic} selector {selector}")
        seen.add(selector)

    probe = {"mechanics": {mechanic: canonical}}
    if mechanic not in usable_mechanics(probe):
        raise ValueError(
            f"The supplied {mechanic} table is incomplete and cannot be executed: "
            "schedules must cover consecutive durations starting at 1 with no gaps, "
            "and every row must carry the fields its unit requires."
        )
    return canonical


def parse_table_bytes(mechanic: str, filename: str, content: bytes) -> List[Dict[str, Any]]:
    """Parse an uploaded/pasted CSV or TSV table for one slot.

    Uses the ingestion table reader (``_read_tables``) and row validator
    (``_parse_row``): a file whose ``mechanic`` column names several
    mechanics contributes only this slot's rows; a file without one is
    read as this slot's table.
    """

    frames = _read_tables(filename, content)
    if not frames:
        raise ValueError("Only CSV or TSV tables can be used to replace a slot table")
    collected: List[Dict[str, Any]] = []
    errors: List[str] = []
    for sheet, frame in frames:
        frame = frame.rename(columns={column: _name(column) for column in frame.columns})
        if "mechanic" in set(frame.columns):
            groups = frame.groupby(frame["mechanic"].map(_name), dropna=False)
        else:
            groups = [(mechanic, frame)]
        for raw_kind, group in groups:
            kind = {"policy_fee": "fees", "admin_fee": "fees", "fee": "fees"}.get(
                _name(raw_kind), _name(raw_kind)
            )
            if kind != mechanic:
                continue
            for index, raw in group.iterrows():
                row_number = int(index) + 2
                try:
                    collected.append(_parse_row(mechanic, raw.to_dict()))
                except ValueError as exc:
                    errors.append(f"{filename} sheet {sheet} row {row_number}: {exc}")
    if errors:
        raise ValueError("; ".join(errors))
    if not collected:
        raise ValueError(f"No {mechanic} rows were found in {filename}")
    # Re-run the shared validation so pasted/uploaded tables meet the same
    # duplicate + completeness bar as JSON row edits.
    return _validate_canonical_rows(mechanic, collected)


def validate_table_rows(mechanic: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate JSON-supplied rows for a table slot (see _validate_canonical_rows)."""

    return _validate_canonical_rows(mechanic, rows)


# ---------------------------------------------------------------------------
# Edit application + change records
# ---------------------------------------------------------------------------


def _stamp_edit_provenance(rows: List[Dict[str, Any]], *, who: str, at: str) -> List[Dict[str, Any]]:
    stamped: List[Dict[str, Any]] = []
    for row in rows:
        stamped.append({
            **row,
            "provenance": {
                "sourceType": _EDIT_SOURCE_TYPE,
                "filename": "Workspace edit",
                "editedBy": who,
                "editedAt": at,
            },
        })
    return stamped


def _change_record(
    *,
    workspace_id: Optional[str],
    slot: Dict[str, Any],
    kind: str,
    who: str,
    at: str,
    summary: str,
    prior: Dict[str, Any],
    new: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "id": f"chg-{uuid.uuid4().hex[:12]}",
        "workspaceId": workspace_id,
        "slot": slot["id"],
        "mechanic": slot.get("mechanic"),
        "kind": kind,
        "who": who,
        "at": at,
        "summary": summary,
        "prior": prior,
        "new": new,
    }


def apply_table_edit(
    artifact: Dict[str, Any],
    slot: Dict[str, Any],
    canonical_rows: List[Dict[str, Any]],
    *,
    workspace_id: Optional[str],
    who: str,
    at: str,
) -> Dict[str, Any]:
    """Apply a validated table replacement to a copy of the artifact.

    Returns ``{"artifact": ..., "change": ...}``.  The edit supersedes
    any synthetic table for the mechanic (recorded in the summary); the
    document-derived ``mechanics``/``candidates``/``reviews`` state is
    left untouched, so a filed table can always be re-accepted.
    """

    mechanic = str(slot["mechanic"])
    result = deepcopy(artifact or {})
    prior_rows = list((result.get("usable") or {}).get(mechanic) or [])
    prior_status = _slot_status(result, mechanic)
    prior_summary = {**_summarize_rows(prior_rows), "status": prior_status}

    stamped = _stamp_edit_provenance(canonical_rows, who=who, at=at)
    result.setdefault("usable", {})[mechanic] = stamped
    result.setdefault("workspaceEdits", {})[mechanic] = {
        "rows": stamped,
        "updatedAt": at,
        "updatedBy": who,
    }
    result.setdefault("status", {})[mechanic] = "workspace_table"

    notes = []
    synthetic = result.get("synthetic") or {}
    if mechanic in synthetic:
        synthetic.pop(mechanic, None)
        notes.append("replaced the synthetic table")
    def _row_word(count: int) -> str:
        return "row" if count == 1 else "rows"

    summary = (
        f"{slot['label']} replaced in the workspace — {len(stamped)} {_row_word(len(stamped))} "
        f"(was {prior_status.replace('_', ' ')}"
        + (f", {len(prior_rows)} {_row_word(len(prior_rows))}" if prior_rows else "")
        + ")"
        + (f"; {'; '.join(notes)}" if notes else "")
        + "."
    )
    change = _change_record(
        workspace_id=workspace_id,
        slot=slot,
        kind="table_replace",
        who=who,
        at=at,
        summary=summary,
        prior=prior_summary,
        new={**_summarize_rows(stamped), "status": "workspace_table"},
    )
    return {"artifact": result, "change": change}


def apply_nar_factor_edit(
    artifact: Dict[str, Any],
    slot: Dict[str, Any],
    factor: Any,
    *,
    workspace_id: Optional[str],
    who: str,
    at: str,
) -> Dict[str, Any]:
    """Apply a validated NAR-factor edit (the scalar slot)."""

    mechanic = "nar_factors"
    try:
        value = float(factor)
    except (TypeError, ValueError) as exc:
        raise ValueError("NAR factor must be a number") from exc
    if not math.isfinite(value):
        raise ValueError("NAR factor must be a finite number")
    # Range validation lives in the shared row validator (_parse_row),
    # the same one ingestion applies to nar_factors rows.
    value = _parse_row(mechanic, {"factor": value})["factor"]

    result = deepcopy(artifact or {})
    prior_rows = list((result.get("usable") or {}).get(mechanic) or [])
    prior_factor = prior_rows[0].get("factor") if prior_rows else None

    stamped = _stamp_edit_provenance([{"factor": value}], who=who, at=at)
    result.setdefault("usable", {})[mechanic] = stamped
    result.setdefault("workspaceEdits", {})[mechanic] = {
        "rows": stamped,
        "updatedAt": at,
        "updatedBy": who,
    }
    result.setdefault("status", {})[mechanic] = "workspace_table"

    change = _change_record(
        workspace_id=workspace_id,
        slot=slot,
        kind="nar_factor",
        who=who,
        at=at,
        summary=(
            f"NAR factor set in the workspace — {value} "
            f"(was {prior_factor if prior_factor is not None else 'not set'})."
        ),
        prior={"factor": prior_factor},
        new={"factor": value},
    )
    return {"artifact": result, "change": change}


def reapply_workspace_edits(
    fresh_artifact: Dict[str, Any], prior_edits: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Re-apply persisted workspace edits onto a freshly extracted artifact.

    Analysis rebuilds the mechanics artifact from the workspace's
    documents; without this step a re-run would silently discard every
    slot edit.  Edits win over document-derived ``usable`` rows for
    their mechanic, exactly as they did when first applied.
    """

    if not prior_edits:
        return fresh_artifact
    fresh_artifact["workspaceEdits"] = deepcopy(prior_edits)
    usable = fresh_artifact.setdefault("usable", {})
    status = fresh_artifact.setdefault("status", {})
    for mechanic, edit in prior_edits.items():
        rows = list((edit or {}).get("rows") or [])
        if not rows:
            continue
        usable[mechanic] = deepcopy(rows)
        status[mechanic] = "workspace_table"
    return fresh_artifact


__all__ = [
    "MECHANIC_SLOTS",
    "SLOT_BY_ID",
    "GAP_SLOT_MAP",
    "STATUS_LABELS",
    "annotate_gap_items",
    "filing_review_reconciliation",
    "build_mechanics_panel",
    "build_slot_view",
    "correction_view",
    "parse_table_bytes",
    "validate_table_rows",
    "apply_table_edit",
    "apply_nar_factor_edit",
    "reapply_workspace_edits",
]
