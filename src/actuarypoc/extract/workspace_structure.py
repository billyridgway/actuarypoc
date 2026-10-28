"""The product structure: approvals organized by the product's anatomy.

Billy (Oct 28, 2026): the suggestions and equations "feel like a random
set of things that need to be approved."  A product type has a NORMAL
structure — for a UL policy, the order money flows through the policy's
life — and the choices a person must make live inside that structure.
This module is the server-side half:

* a DECLARED structure for the UL product type (the proto-pack): the
  ordered steps, a plain-language sentence for each saying what the
  step is in the policy's life, and the member mechanics — each step
  groups its equation AND its tables, the two halves of a mechanic.
  Order and grouping come only from this declaration, never from model
  output.  Mechanics the declaration does not name render in a trailing
  "Also found in the documents" group — never forced into the anatomy.

* readings: every reading of a step's equation, unified from the
  artifact's records and the deterministic harvest, each carrying its
  evidence and a PROVENANCE CLASS (filed definition / from the filing /
  derived / carried over — no filed statement / entered in this
  workspace).  Two readings with different bodies are a CHOICE, made
  explicit — including when one of them is a carried-over incumbent
  that materialized from pre-doctrine state with no filed statement
  behind it (the ws-f107485a NAR seam: the factor-adjusted reading sat
  in force while the policy form's own definition waited as a
  "replacement"; divergence is a choice, never a silent occupation).

* step states, composed once, server-side, so the structure view and
  the decisions checklist derive from ONE composition: settled /
  choice / approval / carried / not-in-documents / stated-not-extracted
  (the last two reuse the gap-semantics coverage computation verbatim).

* the chosen option per step, for stamping projection runs: a run
  records which definition it used, by identity.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from actuarypoc.domain import equations as _eq
from actuarypoc.extract import workspace_equations as _ws_eq


# ---------------------------------------------------------------------------
# The declared UL structure (the proto-pack).
# ---------------------------------------------------------------------------

UL_STRUCTURE: List[Dict[str, Any]] = [
    {
        "id": "premium",
        "label": "Premium & loads",
        "blurb": (
            "What the policyholder pays in, and the expense load the "
            "carrier takes off each premium before it reaches the "
            "policy's account value."
        ),
        "equationMechanic": "premium_load",
        "tableMechanics": [],
        "tableSlots": [],
    },
    {
        "id": "fees",
        "label": "Policy fees",
        "blurb": (
            "The monthly policy and administration fees deducted from "
            "the account value for keeping the policy in force."
        ),
        "equationMechanic": "policy_fees",
        "tableMechanics": ["fees"],
        "tableSlots": ["fees"],
    },
    {
        "id": "crediting",
        "label": "Interest crediting",
        "blurb": (
            "The interest credited to the account value — the declared "
            "rate the policy earns between deductions."
        ),
        "equationMechanic": "crediting",
        "tableMechanics": [],
        "tableSlots": ["crediting"],
    },
    {
        "id": "death_benefit",
        "label": "Death benefit & corridor",
        "blurb": (
            "What is paid on death: the face amount, or — under the "
            "corridor — a percentage of the account value when that is "
            "greater, so the policy keeps its life-insurance character."
        ),
        "equationMechanic": "death_benefit",
        "tableMechanics": ["corridor"],
        "tableSlots": ["corridor"],
    },
    {
        "id": "nar",
        "label": "Net amount at risk",
        "blurb": (
            "The part of the death benefit the carrier is actually at "
            "risk for — the death benefit less the policy's own account "
            "value. It is the amount the cost of insurance is charged on."
        ),
        "equationMechanic": "nar_definition",
        "tableMechanics": ["nar_factors"],
        "tableSlots": ["nar"],
    },
    {
        "id": "coi",
        "label": "COI charges",
        "blurb": (
            "The monthly cost-of-insurance deduction: the net amount at "
            "risk times the filed COI rate for the insured's duration "
            "and attained age."
        ),
        "equationMechanic": "coi_charge",
        "tableMechanics": ["coi"],
        "tableSlots": ["coi"],
    },
    {
        "id": "surrender",
        "label": "Surrender & exit",
        "blurb": (
            "What it costs to leave early: the surrender charge taken "
            "from the account value when the policy is surrendered in "
            "its early years."
        ),
        "equationMechanic": "surrender_charge",
        "tableMechanics": ["surrender"],
        "tableSlots": ["surrender"],
    },
]

STRUCTURE_BY_ID: Dict[str, Dict[str, Any]] = {
    step["id"]: step for step in UL_STRUCTURE
}
DECLARED_EQUATION_MECHANICS = {step["equationMechanic"] for step in UL_STRUCTURE}
DECLARED_TABLE_MECHANICS = {
    mechanic for step in UL_STRUCTURE for mechanic in step["tableMechanics"]
}

STEP_STATE_LABELS: Dict[str, str] = {
    "settled": "Settled — in effect",
    "choice": "Your choice — more than one reading",
    "approval": "Awaiting your approval",
    "carried": "In effect — carried over, no filed statement",
    "not_in_documents": "Not stated in the documents",
    "stated_not_extracted": "Stated in the documents but not extracted",
}


# ---------------------------------------------------------------------------
# Provenance classes — what kind of authority a reading carries.
# ---------------------------------------------------------------------------

PROVENANCE_FILED_DEFINITION = "filed_definition"
PROVENANCE_FROM_FILING = "from_filing"
PROVENANCE_DERIVED = "derived"
PROVENANCE_CARRIED_OVER = "carried_over"
PROVENANCE_WORKSPACE = "workspace"

PROVENANCE_CLASS_LABELS: Dict[str, str] = {
    PROVENANCE_FILED_DEFINITION: "Filed definition",
    PROVENANCE_FROM_FILING: "From the filing",
    PROVENANCE_DERIVED: "Derived",
    PROVENANCE_CARRIED_OVER: "Carried over — no filed statement",
    PROVENANCE_WORKSPACE: "Entered in this workspace",
}

#: Classes whose readings are derived FROM the documents — a divergence
#: between one of these and any incumbent is a choice for a person.
DOCUMENT_DERIVED_CLASSES = {
    PROVENANCE_FILED_DEFINITION,
    PROVENANCE_FROM_FILING,
    PROVENANCE_DERIVED,
}

_CARRIED_SOURCE_KINDS = {"pre_doctrine_migration", "specimen"}
_CARRIED_APPROVERS = {_ws_eq.MIGRATION_APPROVER, _ws_eq.SPECIMEN_APPROVER}

#: A statement that DEFINES its mechanic (as opposed to mentioning a
#: value for it) — the policy form's "Net Amount at Risk – is the
#: difference between the Death Benefit and the Policy Value" is the
#: standing example.
_DEFINITIONAL = re.compile(
    r"(is|shall be|means)\s+(the\s+)?(difference|greater|lesser|sum|product|"
    r"amount|defined|equal|calculated|determined)",
    re.IGNORECASE,
)


def provenance_class(source: Optional[Mapping[str, Any]]) -> str:
    """The provenance class of one reading, from its source record."""

    source = dict(source or {})
    kind = str(source.get("kind") or "")
    statement = source.get("statement")
    note = str(source.get("note") or "")
    approver = str((source.get("approvalBy") or ""))
    if kind in _CARRIED_SOURCE_KINDS or approver in _CARRIED_APPROVERS:
        return PROVENANCE_CARRIED_OVER
    if kind in {"actuary", "correction"}:
        return PROVENANCE_WORKSPACE
    if statement:
        if _DEFINITIONAL.search(str(statement)):
            return PROVENANCE_FILED_DEFINITION
        return PROVENANCE_FROM_FILING
    if note.startswith("Materialized from") or source.get("tableSourceType"):
        # A body compiled by transcribing a table (or by the
        # pre-doctrine materialization of one): derived from the
        # documents' data, not stated as an equation in them.
        return PROVENANCE_DERIVED
    if kind == "document" or source.get("filename"):
        return PROVENANCE_FROM_FILING
    if kind:
        return PROVENANCE_FROM_FILING
    # No kind, no statement, no source: nothing filed stands behind it.
    return PROVENANCE_CARRIED_OVER


def _body_key(body: Optional[Mapping[str, Any]]) -> str:
    return json.dumps(body or {}, sort_keys=True, default=str)


def _reading_view(
    *,
    mechanic: str,
    body: Dict[str, Any],
    timing: Optional[str],
    state: str,
    source: Mapping[str, Any],
    record_id: Optional[str],
    origin: str,
) -> Dict[str, Any]:
    source = dict(source or {})
    pclass = provenance_class(source)
    if (
        mechanic == "nar_definition"
        and pclass == PROVENANCE_DERIVED
        and not source.get("statement")
        and body in (_eq.nar_body("factor_adjusted"), _eq.nar_body("unadjusted"))
    ):
        # The legacy NAR definition, materialized from workspace state
        # (its source kind is rewritten to "document" when a table
        # acceptance transcribes it, but no filed statement stands
        # behind the definition itself — the filing's factor table
        # states factors, not this definition).  Carried over.
        pclass = PROVENANCE_CARRIED_OVER
    return {
        "key": f"{mechanic}:{_body_key(body)[:24]}",
        "mechanic": mechanic,
        "recordId": record_id,
        "origin": origin,
        "state": state,  # "in_effect" | "pending"
        "body": body,
        "rendering": (
            _eq.render_with_timing(body, timing)
            if mechanic == "coi_charge" and timing
            else _eq.render_equation(body, mechanic)
        ),
        "math": _eq.render_math_tree(body, mechanic),
        "timingNote": _eq.timing_sentence(timing),
        "evidence": {
            "filename": source.get("filename")
            or (source.get("proposalEvidence") or {}).get("filename"),
            "page": source.get("page")
            or (source.get("proposalEvidence") or {}).get("page"),
            "snippet": source.get("statement"),
        },
        "provenanceClass": pclass,
        "provenanceLabel": PROVENANCE_CLASS_LABELS[pclass],
    }


def readings_for_mechanic(
    artifact: Mapping[str, Any],
    mechanic: str,
    slices: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Every reading of one mechanic's equation, in-effect first.

    Unified from the artifact's records (approved = in effect;
    pending = a candidate awaiting a decision) and the deterministic
    harvest over the slices (a candidate not yet saved as a record).
    Readings are deduplicated by formula body — the same reading
    found twice is one option, not two.
    """

    artifact = artifact or {}
    by_body: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    def offer(view: Dict[str, Any]) -> None:
        key = _body_key(view.get("body"))
        existing = by_body.get(key)
        if existing is None:
            by_body[key] = view
            order.append(key)
            return
        # Prefer the view that carries state: an in-effect record over
        # a pending one, a saved record over a harvest candidate.
        rank = {"in_effect": 0, "pending": 1}
        if rank.get(view["state"], 2) < rank.get(existing["state"], 2) or (
            view.get("recordId") and not existing.get("recordId")
            and view["state"] == existing["state"]
        ):
            by_body[key] = view

    for record in _ws_eq.records_for(artifact, mechanic):
        body = record.get("body")
        if body is None or record.get("state") not in {"approved", "pending"}:
            continue
        offer(_reading_view(
            mechanic=mechanic,
            body=body,
            timing=record.get("timing"),
            state="in_effect" if record.get("state") == "approved" else "pending",
            source=record.get("source") or {},
            record_id=str(record.get("id")) if record.get("id") else None,
            origin="record",
        ))
    for candidate in _ws_eq.deterministic_harvest(list(slices or [])):
        if str(candidate.get("mechanic") or "") != mechanic:
            continue
        body = candidate.get("body")
        if body is None:
            continue
        offer(_reading_view(
            mechanic=mechanic,
            body=body,
            timing=candidate.get("timing"),
            state="pending",
            source={
                "kind": "document",
                "statement": candidate.get("statement"),
                "filename": candidate.get("filename"),
                "page": candidate.get("page"),
                "assist": candidate.get("assist"),
            },
            record_id=None,
            origin="harvest",
        ))
    views = [by_body[key] for key in order]
    views.sort(key=lambda v: 0 if v["state"] == "in_effect" else 1)
    return views


# ---------------------------------------------------------------------------
# Step composition — one composition behind the structure view and the
# decisions checklist.
# ---------------------------------------------------------------------------

_TABLE_IN_EFFECT_STATUSES = {"filed_accepted", "corrected", "workspace_table"}


def _step_state(
    *,
    readings: List[Dict[str, Any]],
    tables_in_effect: bool,
    tables_pending: bool,
    coverage_state: Optional[str],
) -> str:
    in_effect = next((r for r in readings if r["state"] == "in_effect"), None)
    distinct_bodies = {_body_key(r.get("body")) for r in readings}
    doc_derived = [
        r for r in readings if r["provenanceClass"] in DOCUMENT_DERIVED_CLASSES
    ]
    if len(distinct_bodies) > 1 and (in_effect is not None or len(doc_derived) > 1):
        # More than one evidenced reading, and they disagree: a
        # person's choice — including an incumbent (of any origin)
        # diverged from a document-derived candidate.
        return "choice"
    if in_effect is not None:
        if in_effect["provenanceClass"] == PROVENANCE_CARRIED_OVER and not doc_derived:
            return "carried"
        if tables_in_effect and not tables_pending:
            return "settled"
        return "approval" if tables_pending else "settled"
    if readings:
        return "approval"
    if coverage_state == "covered":
        # Covered by the documents, but no standalone reading stands
        # yet — the equation arrives with its table's acceptance (the
        # filed-table transcription path: COI, surrender).  Awaiting
        # that approval; never "not in the documents" (Billy's rule).
        return "approval"
    if coverage_state == "stated":
        return "stated_not_extracted"
    return "not_in_documents"


def build_structure(
    artifact: Mapping[str, Any],
    slices: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    slot_views: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compose the product structure for one workspace.

    ``slot_views`` are the mechanics panel's table-slot views (keyed by
    slot id), reused so a step's tables are the panel's own state, not
    a second derivation.  Returns {"steps", "alsoFound", "decisions",
    "progress"}.
    """

    artifact = artifact or {}
    slices = list(slices or [])
    slots_by_id = {
        str(view.get("id")): view for view in (slot_views or []) if isinstance(view, Mapping)
    }
    coverage = _ws_eq.equation_document_coverage(artifact, slices)
    steps: List[Dict[str, Any]] = []
    decisions: List[Dict[str, Any]] = []
    for step in UL_STRUCTURE:
        mechanic = step["equationMechanic"]
        readings = readings_for_mechanic(artifact, mechanic, slices)
        member_slots = [
            slots_by_id[slot_id] for slot_id in step["tableSlots"]
            if slot_id in slots_by_id
        ]
        tables_in_effect = all(
            view.get("status") in _TABLE_IN_EFFECT_STATUSES or view.get("kind") == "display"
            for view in member_slots
        ) if member_slots else True
        tables_pending = any(
            int(view.get("pendingCandidateCount") or 0) > 0 for view in member_slots
        )
        cov = coverage.get(mechanic) or {}
        state = _step_state(
            readings=readings,
            tables_in_effect=tables_in_effect,
            tables_pending=tables_pending,
            coverage_state=cov.get("state"),
        )
        in_effect = next((r for r in readings if r["state"] == "in_effect"), None)
        view = {
            "id": step["id"],
            "label": step["label"],
            "blurb": step["blurb"],
            "equationMechanic": mechanic,
            "equationLabel": _eq.MECHANIC_LABELS.get(mechanic, mechanic),
            "tableMechanics": list(step["tableMechanics"]),
            "slots": member_slots,
            "state": state,
            "stateLabel": STEP_STATE_LABELS[state],
            "options": readings,
            "inEffect": in_effect,
            "coverage": {
                "state": cov.get("state"),
                "filename": cov.get("filename"),
                "page": cov.get("page"),
            },
        }
        steps.append(view)
        label = step["label"]
        if state == "choice":
            decisions.append({
                "stepId": step["id"], "stepLabel": label, "kind": "choice",
                "mechanic": mechanic,
                "text": (
                    f"{label}: {len({_body_key(r.get('body')) for r in readings})} "
                    "readings — choose which one governs"
                ),
            })
        elif state == "approval":
            decisions.append({
                "stepId": step["id"], "stepLabel": label, "kind": "approval",
                "mechanic": mechanic,
                "text": f"{label}: awaiting your approval",
            })
        elif state == "carried":
            decisions.append({
                "stepId": step["id"], "stepLabel": label, "kind": "carried",
                "mechanic": mechanic,
                "text": (
                    f"{label}: in effect from a carried-over reading with no "
                    "filed statement — review it when you can"
                ),
            })
        elif state in {"not_in_documents", "stated_not_extracted"}:
            decisions.append({
                "stepId": step["id"], "stepLabel": label, "kind": state,
                "mechanic": mechanic,
                "text": f"{label}: {STEP_STATE_LABELS[state].lower()}",
            })
    # Also found: mechanics with records, candidates, or usable rows
    # that the declared anatomy does not name.  Never forced in.
    found: Dict[str, Dict[str, Any]] = {}
    for record in _ws_eq.records(artifact):
        mechanic = str(record.get("mechanic") or "")
        if mechanic and mechanic not in DECLARED_EQUATION_MECHANICS:
            found.setdefault(mechanic, {"mechanic": mechanic, "kind": "equation"})
    for mechanic in list((artifact.get("candidates") or {}).keys()) + list(
        (artifact.get("usable") or {}).keys()
    ):
        if mechanic not in DECLARED_TABLE_MECHANICS:
            found.setdefault(mechanic, {"mechanic": mechanic, "kind": "table"})
    settled = sum(1 for step in steps if step["state"] == "settled")
    choices = sum(1 for step in steps if step["state"] == "choice")
    progress = {
        "settled": settled,
        "total": len(steps),
        "choicesAwaiting": choices,
        "decisionsAwaiting": len(decisions),
        "headerText": (
            f"Product structure: {settled} of {len(steps)} steps settled"
            + (f" · {choices} choice(s) awaiting you" if choices else "")
        ),
    }
    return {
        "steps": steps,
        "alsoFound": [found[key] for key in sorted(found)],
        "decisions": decisions,
        "progress": progress,
    }


def chosen_options(artifact: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The chosen option per step: the in-effect reading's identity.

    Stamped onto projection runs so a run always names the definitions
    it used — which NAR definition, which crediting equation — by
    record id, rendering, and provenance class.
    """

    in_force = {
        step["equationMechanic"]: _ws_eq.in_force(artifact or {}, step["equationMechanic"])
        for step in UL_STRUCTURE
    }
    return chosen_options_from_in_force(in_force)


def chosen_options_from_in_force(
    in_force: Mapping[str, Optional[Mapping[str, Any]]]
) -> List[Dict[str, Any]]:
    """The chosen options from a mechanic -> in-effect record map
    (the shape a projection request already carries)."""

    chosen: List[Dict[str, Any]] = []
    for step in UL_STRUCTURE:
        mechanic = step["equationMechanic"]
        record = in_force.get(mechanic)
        if record is None or record.get("body") is None:
            continue
        view = _reading_view(
            mechanic=mechanic,
            body=record["body"],
            timing=record.get("timing"),
            state="in_effect",
            source=record.get("source") or {},
            record_id=str(record.get("id")) if record.get("id") else None,
            origin="record",
        )
        chosen.append({
            "stepId": step["id"],
            "stepLabel": step["label"],
            "mechanic": mechanic,
            "equationId": view["recordId"],
            "rendering": view["rendering"],
            "provenanceClass": view["provenanceClass"],
            "provenanceLabel": view["provenanceLabel"],
        })
    return chosen


def definitions_line(chosen: Sequence[Mapping[str, Any]]) -> str:
    """One human line naming the definitions a run used."""

    if not chosen:
        return ""
    parts = [
        f"{item['stepLabel']}: {item['rendering']} ({item['provenanceLabel'].lower()})"
        for item in chosen
    ]
    return "Definitions in effect — " + "; ".join(parts)


__all__ = [
    "UL_STRUCTURE",
    "STRUCTURE_BY_ID",
    "STEP_STATE_LABELS",
    "PROVENANCE_CLASS_LABELS",
    "DOCUMENT_DERIVED_CLASSES",
    "provenance_class",
    "readings_for_mechanic",
    "build_structure",
    "chosen_options",
    "chosen_options_from_in_force",
    "definitions_line",
]
