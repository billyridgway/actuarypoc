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

from actuarypoc.extract.workspace_ul_mechanics import (
    _name,
    _parse_row,
    _read_tables,
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
        views.append({
            "id": candidate.get("id"),
            "filename": candidate.get("filename"),
            "page": candidate.get("page"),
            "tableHeading": candidate.get("tableHeading"),
            "rowCount": candidate.get("rowCount"),
            "valueBasis": candidate.get("valueBasis"),
        })
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
        "rows": usable_rows,
        "provenance": _provenance_views(usable_rows),
        "pendingCandidateCount": _pending_candidate_count(artifact, mechanic),
        "pendingCandidates": _pending_candidate_views(artifact, mechanic),
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
    "build_mechanics_panel",
    "build_slot_view",
    "correction_view",
    "parse_table_bytes",
    "validate_table_rows",
    "apply_table_edit",
    "apply_nar_factor_edit",
    "reapply_workspace_edits",
]
