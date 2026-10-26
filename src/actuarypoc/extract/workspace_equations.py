"""Phase 7 (the Equation Doctrine): workspace equation artifacts.

Per workspace, the mechanics artifact carries ``equations`` — a list of
equation records keyed by mechanic (see ``docs/phase-7-equations.md``).
This module owns:

* the record shape and the read views (list / in-force / citation);
* the approval machinery — approve (confirmed, validated), reject,
  actuary authoring (PUT) — with the confirm-back discipline the
  corrections and proposals flows established;
* body builders that transcribe a table unit / stated definition into
  the formula language (used by the pre-doctrine migration, by
  corrections, and by proposals — one transcription, three callers);
* the one-time pre-doctrine migration that materializes visible,
  honestly-provenanced equation artifacts from mechanics state already
  in force, so nothing that used to be a hidden code assumption stays
  hidden — and nothing changes silently;
* harvesting: deterministic prose assists plus the configured model
  reading Phase 0 slices for stated calculations.  Harvesting only
  ever *proposes* — a record is ``pending`` (or ``unmapped`` when a
  statement cannot be structured confidently) until a human approves
  it.  Nothing harvested executes unapproved.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence
import uuid

from actuarypoc.domain import equations as _eq
from actuarypoc.domain.equations import (  # noqa: F401  (re-exported builders)
    coi_body_for_unit,
    crediting_body,
    death_benefit_body,
    nar_body,
    policy_fees_body,
    premium_load_body,
    surrender_body_for_unit,
)


EQUATION_STATES = ("pending", "approved", "rejected", "superseded", "unmapped")

SOURCE_KIND_LABELS: Dict[str, str] = {
    "document": "Document-derived",
    "actuary": "Actuary-authored",
    "correction": "Workspace correction",
    "proposal": "Extraction proposal",
    "specimen": "Product specimen (pre-doctrine)",
    "pre_doctrine_migration": "Pre-doctrine workspace state",
}

#: Ledger basis per equation source kind (defined with the language).
BASIS_BY_SOURCE_KIND = _eq.BASIS_BY_SOURCE_KIND

MIGRATION_APPROVER = "pre-doctrine migration"
SPECIMEN_APPROVER = "product specimen (pre-doctrine)"


# ---------------------------------------------------------------------------
# Body builders — one transcription per stated shape.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Records: shape, views, citations
# ---------------------------------------------------------------------------


def new_record(
    *,
    mechanic: str,
    body: Optional[Dict[str, Any]],
    state: str,
    source: Dict[str, Any],
    at: str,
    timing: Optional[str] = None,
    record_id: Optional[str] = None,
    version: int = 1,
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "id": record_id or f"eq-{uuid.uuid4().hex[:12]}",
        "mechanic": mechanic,
        "version": version,
        "state": state,
        "timing": timing if mechanic == "coi_charge" else None,
        "body": deepcopy(body) if body is not None else None,
        "rendering": (
            _eq.render_with_timing(body, timing)
            if body is not None and mechanic == "coi_charge"
            else _eq.render_equation(body, mechanic) if body is not None else None
        ),
        "source": dict(source),
        "approval": None,
        "conflict": None,
        "createdAt": at,
        "updatedAt": at,
    }
    return record


def records(artifact: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [
        record for record in (artifact or {}).get("equations") or []
        if isinstance(record, dict)
    ]


def records_for(artifact: Mapping[str, Any], mechanic: str) -> List[Dict[str, Any]]:
    return [r for r in records(artifact) if r.get("mechanic") == mechanic]


def in_force(artifact: Mapping[str, Any], mechanic: str) -> Optional[Dict[str, Any]]:
    for record in records_for(artifact, mechanic):
        if record.get("state") == "approved":
            return record
    return None


def in_force_map(artifact: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """mechanic -> the approved record in force (the loop's input)."""

    result: Dict[str, Dict[str, Any]] = {}
    for mechanic in _eq.MECHANICS:
        record = in_force(artifact, mechanic)
        if record is not None and record.get("body") is not None:
            result[mechanic] = record
    return result


def citation(record: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The citation the loop/ledger attach to a mechanic's numbers."""

    if record is None:
        return None
    source = record.get("source") or {}
    view = {
        "equationId": record.get("id"),
        "mechanic": record.get("mechanic"),
        "version": record.get("version"),
        "rendering": record.get("rendering"),
        "timing": record.get("timing"),
        "sourceKind": source.get("kind"),
        "sourceKindLabel": SOURCE_KIND_LABELS.get(str(source.get("kind") or "")),
        "sourceFilename": source.get("filename"),
        "sourcePage": source.get("page"),
        "sourceStatement": source.get("statement"),
        "approvedBy": (record.get("approval") or {}).get("by"),
        "approvedAt": (record.get("approval") or {}).get("at"),
    }
    if source.get("tableSourceType"):
        view["tableSourceType"] = source["tableSourceType"]
    if isinstance(source.get("correction"), dict):
        # A correction-born equation cites its correction (who / when /
        # the actuary's words / the confirm-back) so the ledger's
        # `corrected` lines stay auditable exactly as Phase 3 made them.
        view["correction"] = dict(source["correction"])
    return view


def record_view(record: Mapping[str, Any]) -> Dict[str, Any]:
    view = deepcopy(dict(record))
    source = view.get("source") or {}
    view["sourceKindLabel"] = SOURCE_KIND_LABELS.get(str(source.get("kind") or ""))
    return view


def equations_view(artifact: Mapping[str, Any]) -> Dict[str, Any]:
    """The GET /equations payload: per-mechanic state + conflicts."""

    artifact = artifact or {}
    mechanics: Dict[str, Any] = {}
    conflicts: List[Dict[str, Any]] = []
    for mechanic in _eq.MECHANICS:
        mechanic_records = records_for(artifact, mechanic)
        current = in_force(artifact, mechanic)
        ordered = sorted(
            mechanic_records,
            key=lambda r: (r.get("state") != "approved", str(r.get("createdAt") or "")),
        )
        mechanics[mechanic] = {
            "mechanic": mechanic,
            "label": _eq.MECHANIC_LABELS[mechanic],
            "inForce": record_view(current) if current else None,
            "records": [record_view(r) for r in ordered],
            "missing": current is None,
            "resolution": (
                None if current else
                "Harvest the workspace's documents for a stated calculation, "
                "approve a harvested equation, or enter the equation directly."
            ),
        }
        for record in mechanic_records:
            if record.get("conflict"):
                conflicts.append({
                    "mechanic": mechanic,
                    "equationId": record.get("id"),
                    "state": record.get("state"),
                    "conflict": record.get("conflict"),
                    "statement": (record.get("source") or {}).get("statement"),
                    "filename": (record.get("source") or {}).get("filename"),
                    "page": (record.get("source") or {}).get("page"),
                })
            if record.get("state") == "unmapped":
                conflicts.append({
                    "mechanic": mechanic,
                    "equationId": record.get("id"),
                    "state": "unmapped",
                    "conflict": {
                        "note": (
                            "The filing states this calculation but it could "
                            "not be structured into the formula language. It "
                            "is recorded here so it is never silently dropped: "
                            "author the equation or reject the record."
                        ),
                    },
                    "statement": (record.get("source") or {}).get("statement"),
                    "filename": (record.get("source") or {}).get("filename"),
                    "page": (record.get("source") or {}).get("page"),
                })
    return {"mechanics": mechanics, "conflicts": conflicts}


# ---------------------------------------------------------------------------
# Approval machinery — preview / approve / reject / author.
#
# All functions are pure over the artifact (deep-copied in, new artifact
# out) in the corrections/proposals style; the API layer enforces the
# confirmation gate and persists.  Validation runs here too, so no
# caller can put an invalid equation in force.
# ---------------------------------------------------------------------------


def preview_equation(
    mechanic: str, body: Any, timing: Optional[str] = None
) -> Dict[str, Any]:
    """Validate + render without writing anything (the confirm-back)."""

    errors = _eq.validate_equation(mechanic, body)
    if timing is not None:
        if mechanic != "coi_charge":
            errors.append("Only the COI charge equation carries a timing attribute")
        elif timing not in _eq.COI_TIMINGS:
            errors.append(
                f"COI timing must be one of {', '.join(_eq.COI_TIMINGS)}; got {timing!r}"
            )
    rendering = None
    if not errors and isinstance(body, dict):
        rendering = (
            _eq.render_with_timing(body, timing)
            if mechanic == "coi_charge" else _eq.render_equation(body, mechanic)
        )
    return {"mechanic": mechanic, "rendering": rendering, "errors": errors}


def _find_record(artifact: Mapping[str, Any], mechanic: str, equation_id: str) -> Optional[Dict[str, Any]]:
    for record in records_for(artifact, mechanic):
        if record.get("id") == equation_id:
            return record
    return None


def _next_version(artifact: Mapping[str, Any], mechanic: str) -> int:
    versions = [
        int(record.get("version") or 0) for record in records_for(artifact, mechanic)
    ]
    return (max(versions) + 1) if versions else 1


def _refresh_conflicts(result: Dict[str, Any], mechanic: str) -> None:
    """Flag pending records whose rendering disagrees with in-force."""

    current = in_force(result, mechanic)
    for record in records_for(result, mechanic):
        if record.get("state") in {"pending", "unmapped"}:
            if (
                current is not None
                and record.get("body") is not None
                and record.get("rendering") != current.get("rendering")
            ):
                record["conflict"] = {
                    "withEquationId": current.get("id"),
                    "note": (
                        "This stated equation differs from the equation in "
                        "force. Neither wins automatically: the in-force "
                        "equation keeps executing until this one is approved."
                    ),
                }
            elif record.get("conflict"):
                record["conflict"] = None


def _put_in_force(
    result: Dict[str, Any], record: Dict[str, Any], *, who: str, at: str
) -> Dict[str, Any]:
    mechanic = str(record["mechanic"])
    for other in records_for(result, mechanic):
        if other.get("state") == "approved" and other.get("id") != record.get("id"):
            other["state"] = "superseded"
            other["updatedAt"] = at
    record["state"] = "approved"
    record["approval"] = {"by": who, "at": at}
    record["conflict"] = None
    record["updatedAt"] = at
    _refresh_conflicts(result, mechanic)
    return record


def approve_equation(
    artifact: Dict[str, Any],
    mechanic: str,
    equation_id: str,
    *,
    who: str,
    at: str,
) -> Dict[str, Any]:
    """Approve a pending record; returns {"artifact", "record"}.

    Raises ValueError for an unknown record, a record that cannot be
    approved (rejected / already superseded / unmapped — no body), or a
    body that fails validation.
    """

    result = deepcopy(artifact or {})
    record = _find_record(result, mechanic, equation_id)
    if record is None:
        raise ValueError(f"No equation {equation_id!r} for mechanic {mechanic!r}")
    if record.get("state") in {"rejected", "superseded"}:
        raise ValueError(
            f"Equation {equation_id} is {record['state']} and cannot be approved"
        )
    if record.get("body") is None:
        raise ValueError(
            "This record is a stated-but-unmapped calculation: it has no "
            "structured equation to approve. Author the equation first (PUT)."
        )
    errors = _eq.validate_equation(mechanic, record["body"])
    if record.get("timing") is not None and record["timing"] not in _eq.COI_TIMINGS:
        errors.append(f"Invalid COI timing: {record['timing']!r}")
    if errors:
        raise ValueError("The equation is not valid: " + "; ".join(errors))
    record["rendering"] = (
        _eq.render_with_timing(record["body"], record.get("timing"))
        if mechanic == "coi_charge" else _eq.render_equation(record["body"], mechanic)
    )
    _put_in_force(result, record, who=who, at=at)
    result["equations"] = records(result)
    return {"artifact": result, "record": record}


def reject_equation(
    artifact: Dict[str, Any],
    mechanic: str,
    equation_id: str,
    *,
    who: str,
    at: str,
) -> Dict[str, Any]:
    """Reject a record.  The in-force record cannot be rejected —
    supersede it by approving or authoring another equation."""

    result = deepcopy(artifact or {})
    record = _find_record(result, mechanic, equation_id)
    if record is None:
        raise ValueError(f"No equation {equation_id!r} for mechanic {mechanic!r}")
    if record.get("state") == "approved":
        raise ValueError(
            "The equation in force cannot be rejected; approve or author a "
            "replacement to supersede it"
        )
    record["state"] = "rejected"
    record["rejectedBy"] = who
    record["updatedAt"] = at
    result["equations"] = records(result)
    return {"artifact": result, "record": record}


def author_equation(
    artifact: Dict[str, Any],
    mechanic: str,
    body: Dict[str, Any],
    *,
    who: str,
    at: str,
    timing: Optional[str] = None,
    statement: Optional[str] = None,
    source_kind: str = "actuary",
    extra_source: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create an approved record from an authored/edited body.

    Used by the PUT route (actuary provenance), by corrections
    (correction provenance), and by confirmed proposals — one path into
    force, always through validation, always superseding explicitly.
    """

    preview = preview_equation(mechanic, body, timing)
    if preview["errors"]:
        raise ValueError("The equation is not valid: " + "; ".join(preview["errors"]))
    result = deepcopy(artifact or {})
    source: Dict[str, Any] = {"kind": source_kind, "statement": statement}
    if extra_source:
        source.update(extra_source)
    record = new_record(
        mechanic=mechanic,
        body=body,
        state="pending",
        source=source,
        at=at,
        timing=timing if mechanic == "coi_charge" else None,
        version=_next_version(result, mechanic),
    )
    result.setdefault("equations", []).append(record)
    _put_in_force(result, record, who=who, at=at)
    result["equations"] = records(result)
    return {"artifact": result, "record": record}


# ---------------------------------------------------------------------------
# Pre-doctrine migration — one-time, persisted, change-logged.
#
# Workspaces built before Phase 7 have mechanics state in force
# (accepted tables, workspace edits, corrections) whose governing math
# used to live in code — hidden.  The migration materializes that state
# as equation artifacts with honest provenance in an approved state, so
# the specimen (and every pre-doctrine workspace) keeps projecting
# identically while every assumption becomes visible, editable, and
# replaceable.  The runtime never derives anything: this runs once per
# artifact (at analysis and at first load under Phase 7), and after it,
# only approved artifacts execute.
# ---------------------------------------------------------------------------


def add_harvest_candidates(
    artifact: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    *,
    at: str,
    source_kind: str = "document",
) -> Dict[str, Any]:
    """Add harvest candidates as pending records (dedupe by statement)."""

    result = deepcopy(artifact or {})
    applied = _apply_candidates(
        result, candidates, at=at, source_kind=source_kind, harvester_model=None
    )
    return {"artifact": result, **applied}


def approve_harvest_candidate(
    artifact: Dict[str, Any],
    candidate: Dict[str, Any],
    *,
    who: str,
    at: str,
    proposal_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Materialise one harvest candidate and put it in force.

    Used by extraction-proposal confirmation: the proposal IS the
    candidate; confirming it creates the record (if new) and approves
    it with the confirmer as approver, the proposal's evidence stamped
    on the record's source.
    """

    mechanic = str(candidate.get("mechanic") or "")
    added = add_harvest_candidates(artifact, [candidate], at=at)
    result = added["artifact"]
    record_id = None
    for candidate_id in (added.get("created") or []) + (added.get("skipped") or []):
        record = next(
            (r for r in records_for(result, mechanic) if r.get("id") == candidate_id),
            None,
        )
        if record is not None:
            record_id = candidate_id
            break
    if record_id is None:
        raise ValueError("The proposed equation could not be materialised")
    record = next(r for r in records_for(result, mechanic) if r.get("id") == record_id)
    if record.get("state") == "unmapped" or record.get("body") is None:
        raise ValueError(
            "The stated calculation could not be structured into an equation; "
            "it is preserved as an unmapped record and cannot be approved"
        )
    approved = approve_equation(result, mechanic, record_id, who=who, at=at)
    final = approved["artifact"]
    final_record = next(
        r for r in records_for(final, mechanic) if r.get("id") == record_id
    )
    if proposal_id:
        final_record["source"]["proposalId"] = proposal_id
    return {"artifact": final, "record": final_record}


def transcribe_tables_as_approved(
    artifact: Dict[str, Any], *, who: str, at: str
) -> Dict[str, Any]:
    """Transcribe newly accepted tables into approved equations.

    Used when a filed (or synthetic) table is accepted through review:
    the accepting user is the approver and the source kind is the
    document.  Mechanics that already carry any equation record are
    left alone — an existing approved equation already reads the table
    through its lookups, and a correction/actuary equation is never
    displaced by a table acceptance.
    """

    before_ids = {str(r.get("id")) for r in records(artifact)}
    outcome = materialize_legacy_equations(artifact, at=at)
    result = outcome["artifact"]
    transcribed: List[Dict[str, Any]] = []
    for record in records(result):
        if str(record.get("id")) in before_ids:
            continue
        record["source"]["kind"] = "document"
        record["approval"] = {"by": who, "at": at}
        record["updatedAt"] = at
        transcribed.append(record)
    if transcribed:
        for mechanic in _eq.MECHANICS:
            _refresh_conflicts(result, mechanic)
    return {"artifact": result, "transcribed": transcribed}


def _first_unit(rows: Sequence[Mapping[str, Any]], field: str) -> Tuple[Optional[str], bool]:
    units = {str(row.get(field)) for row in rows if row.get(field)}
    if not units:
        return None, False
    first = next(
        (str(row.get(field)) for row in rows if row.get(field)), None
    )
    return first, len(units) > 1


def _correction_params(artifact: Mapping[str, Any], mechanic: str, variant: str) -> Dict[str, Any]:
    record = (artifact.get("corrections") or {}).get(mechanic) or {}
    if record.get("variant") == variant:
        return dict(record.get("params") or {})
    return {}


def materialize_legacy_equations(
    artifact: Dict[str, Any],
    *,
    at: str,
    specimen: bool = False,
) -> Dict[str, Any]:
    """Materialize pre-doctrine in-force state as equation artifacts.

    Returns {"artifact", "changed", "notes"}.  Never touches a mechanic
    that already has any equation record — what a human (or a harvest)
    already said stands.
    """

    result = deepcopy(artifact or {})
    notes: List[str] = []
    usable = result.get("usable") or {}
    kind = "specimen" if specimen else "pre_doctrine_migration"
    approver = SPECIMEN_APPROVER if specimen else MIGRATION_APPROVER
    origin = "the product specimen" if specimen else "the pre-doctrine workspace state"

    def dominant_source_type(rows: Sequence[Mapping[str, Any]]) -> Optional[str]:
        kinds = {
            str((row.get("provenance") or {}).get("sourceType") or "")
            for row in rows
        }
        if "" in kinds and any((row.get("provenance") or {}).get("filename") for row in rows):
            kinds.add("filed_pdf")
        for candidate in ("filed_pdf", "ai_synthetic", "deterministic_fallback", "correction", "workspace_edit"):
            if candidate in kinds:
                return candidate
        return None

    def add(
        mechanic: str,
        body: Dict[str, Any],
        note: str,
        timing: Optional[str] = None,
        table_source_type: Optional[str] = None,
    ) -> None:
        if records_for(result, mechanic):
            return
        source: Dict[str, Any] = {"kind": kind, "statement": None, "note": note}
        if table_source_type:
            source["tableSourceType"] = table_source_type
        record = new_record(
            mechanic=mechanic,
            body=body,
            state="pending",
            source=source,
            at=at,
            timing=timing,
            version=1,
        )
        record["approval"] = {"by": approver, "at": at}
        record["state"] = "approved"
        result.setdefault("equations", []).append(record)
        notes.append(f"{_eq.MECHANIC_LABELS[mechanic]}: {note}")

    def migration_note(text: str) -> str:
        return f"Materialized from {origin}: {text}"

    coi_rows = list(usable.get("coi") or [])
    surrender_rows = list(usable.get("surrender") or [])
    fee_rows = list(usable.get("fees") or [])
    nar_rows = list(usable.get("nar_factors") or [])
    corridor_rows = list(usable.get("corridor") or [])

    coi_timing = str(
        _correction_params(result, "coi", "coi_timing").get("timing") or "beginning"
    )
    if coi_timing not in _eq.COI_TIMINGS:
        coi_timing = "beginning"
    nar_definition = str(
        _correction_params(result, "nar_factors", "nar_definition").get("definition")
        or "factor_adjusted"
    )

    if coi_rows:
        unit, mixed = _first_unit(coi_rows, "rate_unit")
        if unit:
            note = migration_note(
                f"the COI table in force (rate unit {unit}); timing "
                f"{coi_timing} of month."
            )
            if mixed:
                note += (
                    " The table carries mixed rate units; this equation "
                    "follows the first row's unit — review it."
                )
            try:
                add("coi_charge", coi_body_for_unit(unit), note, timing=coi_timing, table_source_type=dominant_source_type(coi_rows))
            except ValueError:
                notes.append(
                    f"COI charge: no equation transcription for rate unit {unit!r}; "
                    "left missing for an actuary to author."
                )
        add(
            "nar_definition",
            nar_body(nar_definition if nar_definition in {"factor_adjusted", "unadjusted"} else "factor_adjusted"),
            migration_note(
                f"the net amount at risk definition in force ({nar_definition}); "
                "the filed factor applies from the NAR factor table when one is in force."
            ),
            table_source_type=dominant_source_type(nar_rows),
        )
        add(
            "death_benefit",
            death_benefit_body(),
            migration_note(
                "the death benefit in force — the greater of the face amount "
                "and the corridor percentage times the account value."
            ),
            table_source_type=dominant_source_type(corridor_rows),
        )
    else:
        if nar_rows:
            add(
                "nar_definition",
                nar_body(nar_definition if nar_definition in {"factor_adjusted", "unadjusted"} else "factor_adjusted"),
                migration_note("the NAR factor table in force."),
            )
        if corridor_rows:
            add(
                "death_benefit",
                death_benefit_body(),
                migration_note("the corridor table in force."),
            )

    if surrender_rows:
        unit, mixed = _first_unit(surrender_rows, "charge_unit")
        if unit:
            note = migration_note(f"the surrender schedule in force (charge unit {unit}).")
            if mixed:
                note += (
                    " The schedule carries mixed charge units; this equation "
                    "follows the first row's unit — review it."
                )
            try:
                add("surrender_charge", surrender_body_for_unit(unit), note, table_source_type=dominant_source_type(surrender_rows))
            except ValueError:
                notes.append(
                    f"Surrender charge: no equation transcription for charge unit {unit!r}; "
                    "left missing for an actuary to author."
                )

    if fee_rows:
        add(
            "policy_fees",
            policy_fees_body(),
            migration_note(
                "the fee schedule in force; each row converts on the basis "
                "its unit states."
            ),
            table_source_type=dominant_source_type(fee_rows),
        )
        add(
            "premium_load",
            premium_load_body(),
            migration_note(
                "premium expense rows in the fee schedule in force are taken "
                "from premiums as a percentage of the premium due."
            ),
        )

    if notes:
        add(
            "crediting",
            crediting_body(),
            migration_note(
                "interest credited monthly at the guaranteed rate, converted "
                "as (1 + guaranteed annual rate)^(1/12) − 1."
            ),
        )

    changed = bool(notes)
    if changed and not result.get("equationsMigratedAt"):
        result["equationsMigratedAt"] = at
    return {"artifact": result, "changed": changed, "notes": notes}


# ---------------------------------------------------------------------------
# Harvesting — propose, never approve.
#
# Deterministic assists first (the conservative prose patterns: a
# signal that does not fire costs a manual entry; a signal that fires
# wrongly costs trust), then the configured model reads the
# calculation-bearing slices.  Every reading is validated against the
# formula language; anything that cannot be structured confidently
# becomes a stated-but-unmapped record — never silently dropped,
# never auto-approved.
# ---------------------------------------------------------------------------

_TIMING_SIGNALS = [
    (re.compile(r"deduct\w*\s+(?:monthly\s+)?in advance|beginning of (?:the|each) (?:policy )?month|before interest is credited", re.I), "beginning"),
    (re.compile(r"in arrears|end of (?:the|each) (?:policy )?month|after interest (?:is )?credited", re.I), "end"),
    (re.compile(r"middle of (?:the|each) (?:policy )?month|mid-month", re.I), "middle"),
]

_NAR_PROSE = re.compile(
    r"net amount at risk[^.]{0,160}?(?:death benefit|benefit payable)[^.]{0,80}?"
    r"(?:less|minus|reduced by)[^.]{0,40}?account value",
    re.I | re.S,
)

_SURRENDER_PCT = re.compile(
    r"surrender charge[^.]{0,120}?(\d+(?:\.\d+)?)\s*%\s*of the account value",
    re.I | re.S,
)
_SURRENDER_GRADING = re.compile(
    r"grad\w+ to (?:zero|0)\s*(?:%|percent)?\s*over (\d{1,2}) years",
    re.I,
)

_COI_RATE_PROSE = re.compile(
    r"cost of insurance[^.]{0,200}?(?:per\s+\$?1,?000|percent\w*\s+of\s+the\s+net\s+amount\s+at\s+risk)",
    re.I | re.S,
)

_CALCULATION_KEYWORDS = (
    "cost of insurance", "surrender charge", "net amount at risk",
    "death benefit", "expense charge", "premium load", "interest is credited",
    "credited interest", "monthly deduction",
)


def _slice_page_at(slice_: Mapping[str, Any], offset: int) -> Optional[int]:
    page = slice_.get("page_start")
    for rel, pg in slice_.get("page_offsets") or []:
        if offset >= int(rel):
            page = int(pg)
        else:
            break
    return page


def _sentence_at(text: str, start: int, end: int) -> str:
    """The sentence(s) around a match — the verbatim source statement."""

    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start))
    right_candidates = [
        idx for idx in (text.find(".", end), text.find("\n", end)) if idx != -1
    ]
    right = min(right_candidates) if right_candidates else len(text)
    statement = " ".join(text[left + 1:right + 1].split())
    return statement[:600]


def _graded_surrender_body(percent: float, grading_years: int) -> Dict[str, Any]:
    """percent of account value, grading linearly to zero over the period."""

    return graded_surrender_body("percent_account_value", percent, grading_years)


def deterministic_harvest(slices: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Candidate readings from conservative prose patterns.

    Each candidate: {mechanic, body|None, timing, statement, filename,
    page, assist}.  A pattern that cannot see every number it needs
    does not fire — the model pass and the actuary remain.
    """

    candidates: List[Dict[str, Any]] = []
    for slice_ in slices or []:
        text = str(slice_.get("text") or "")
        if not text:
            continue
        lowered = text.lower()
        filename = slice_.get("document_hint")

        if "cost of insurance" in lowered or "coi" in lowered:
            for pattern, timing in _TIMING_SIGNALS:
                match = pattern.search(text)
                if match:
                    candidates.append({
                        "mechanic": "coi_charge",
                        "body": None,
                        "timing": timing,
                        "statement": _sentence_at(text, match.start(), match.end()),
                        "filename": filename,
                        "page": _slice_page_at(slice_, match.start()),
                        "assist": "coi_timing_prose",
                    })
                    break

        nar_match = _NAR_PROSE.search(text)
        if nar_match:
            candidates.append({
                "mechanic": "nar_definition",
                "body": nar_body("unadjusted"),
                "timing": None,
                "statement": _sentence_at(text, nar_match.start(), nar_match.end()),
                "filename": filename,
                "page": _slice_page_at(slice_, nar_match.start()),
                "assist": "nar_prose",
            })

        pct_match = _SURRENDER_PCT.search(text)
        grade_match = _SURRENDER_GRADING.search(text)
        if pct_match and grade_match:
            percent = float(pct_match.group(1)) / 100.0
            grading_years = int(grade_match.group(1))
            if 0 < percent <= 1 and 1 <= grading_years <= 40:
                candidates.append({
                    "mechanic": "surrender_charge",
                    "body": _graded_surrender_body(percent, grading_years),
                    "timing": None,
                    "statement": _sentence_at(
                        text, pct_match.start(), grade_match.end()
                    ),
                    "filename": filename,
                    "page": _slice_page_at(slice_, pct_match.start()),
                    "assist": "surrender_grading_prose",
                })
    return candidates


def _statement_key(mechanic: str, statement: Optional[str]) -> Optional[str]:
    if not statement:
        return None
    normalized = " ".join(str(statement).lower().split())
    return sha256(f"{mechanic}|{normalized}".encode("utf-8")).hexdigest()[:16]


def _normalized(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _apply_candidates(
    result: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    *,
    at: str,
    source_kind: str,
    harvester_model: Optional[str],
) -> Dict[str, List[str]]:
    created: List[str] = []
    skipped: List[str] = []
    touched: set = set()
    for candidate in candidates:
        mechanic = str(candidate.get("mechanic") or "")
        if mechanic not in _eq.MECHANICS:
            continue
        statement = candidate.get("statement")
        key = _statement_key(mechanic, statement) or _statement_key(
            mechanic, candidate.get("note")
        )
        existing = [
            record for record in records_for(result, mechanic)
            if key and (record.get("source") or {}).get("statementKey") == key
        ]
        if existing:
            skipped.append(str(existing[0].get("id")))
            continue
        body = candidate.get("body")
        errors: List[str] = []
        if body is not None:
            errors = _eq.validate_equation(mechanic, body)
        timing = candidate.get("timing")
        state = "pending"
        note = candidate.get("note")
        if mechanic == "coi_charge" and body is None and timing:
            # A timing-only statement attaches to the in-force body as a
            # challenger; with no body anywhere it is unmapped — the
            # statement is preserved either way.
            current = in_force(result, mechanic)
            if current is not None and current.get("body") is not None:
                body = deepcopy(current["body"])
            else:
                state = "unmapped"
                note = (
                    "The filing states the COI deduction timing, but no COI "
                    "charge equation exists yet for it to attach to."
                )
        if body is None and state != "unmapped":
            state = "unmapped"
            note = note or "The statement could not be structured into the formula language."
        if errors:
            state = "unmapped"
            body = None
            note = (
                "The proposed reading is not a valid equation: "
                + "; ".join(errors)
            )
        if state == "pending" and body is not None:
            current = in_force(result, mechanic)
            if current is not None:
                candidate_rendering = (
                    _eq.render_with_timing(body, timing)
                    if mechanic == "coi_charge" else _eq.render_equation(body, mechanic)
                )
                if candidate_rendering == current.get("rendering"):
                    skipped.append(str(current.get("id")))
                    continue
        record = new_record(
            mechanic=mechanic,
            body=body,
            state=state,
            source={
                "kind": source_kind,
                "statement": statement,
                "statementKey": key,
                "filename": candidate.get("filename"),
                "page": candidate.get("page"),
                "harvesterModel": harvester_model,
                "harvestedAt": at,
                "assist": candidate.get("assist"),
                "note": note,
            },
            at=at,
            timing=timing if mechanic == "coi_charge" else None,
            version=_next_version(result, mechanic),
        )
        result.setdefault("equations", []).append(record)
        created.append(str(record["id"]))
        touched.add(mechanic)
    for mechanic in touched:
        _refresh_conflicts(result, mechanic)
    result["equations"] = records(result)
    return {"created": created, "skipped": skipped}


_HARVEST_SYSTEM_PROMPT = (
    "You are an actuarial modeling assistant. You read excerpts of a life "
    "insurance filing and identify calculations the filing STATES in words. "
    "For each stated calculation you return the mechanic it governs, the "
    "VERBATIM sentence(s) from the excerpt (copied exactly — never "
    "paraphrased), the page, and a structured reading of the calculation in "
    "the formula language described in the prompt. If a calculation is "
    "stated but you cannot express it confidently in the formula language, "
    "return it with body null — it will be recorded as stated-but-unmapped, "
    "never dropped. Output valid JSON only."
)


def _harvest_prompt(slices: Sequence[Mapping[str, Any]]) -> str:
    quantities = {
        mechanic: sorted(_eq.quantities_for(mechanic)) for mechanic in _eq.MECHANICS
    }
    blocks = []
    for slice_ in slices:
        blocks.append(
            f"[document: {slice_.get('document_hint')}; pages "
            f"{slice_.get('page_start')}–{slice_.get('page_end')}]\n"
            f"{str(slice_.get('text') or '')[:6000]}"
        )
    return (
        "Formula language: a JSON object with exactly one operator key. "
        "Operators: const (number), qty (a quantity name), add/sub/mul/div/"
        "neg/min/max/pow (operand lists), if {cond, then, else}, cmp "
        "[op, a, b] with op in < <= > >= == !=, and/or/not, bands "
        "[{from, to, value}] by policy duration, lookup {table, field, "
        "where?, default?} over tables coi(rate), surrender(charge), "
        "fees(amount), nar_factors(factor), corridor(percentage), and "
        "rows_sum {table, where?, exclude_where?, expr} where expr may use "
        "row_amount and row_unit. Quantities per mechanic: "
        + json.dumps(quantities)
        + ". The coi_charge mechanic may also carry a timing attribute: "
        "beginning, middle, or end (when the COI is deducted within the "
        "month, if the filing states it).\n\n"
        "Return one JSON object: {\"readings\": [{\"mechanic\": one of "
        + ", ".join(_eq.MECHANICS)
        + ", \"statement\": the verbatim sentence(s), \"page\": page number, "
        "\"timing\": beginning|middle|end|null, \"body\": the formula JSON "
        "or null}]}.\n\nFiling excerpts:\n\n"
        + "\n\n".join(blocks)
    )


def calculation_slices(slices: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The slices that plausibly state calculations (keyword-filtered)."""

    selected: List[Dict[str, Any]] = []
    for slice_ in slices or []:
        text = str(slice_.get("text") or "").lower()
        if any(keyword in text for keyword in _CALCULATION_KEYWORDS):
            selected.append(slice_)
    return selected


def default_model_caller(slices: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Ask the configured model for structured readings of the slices.

    Bounded like the synthetic agents (explicit timeout, no retries) and
    fail-soft: any failure raises, and the harvest keeps the
    deterministic readings with a warning.
    """

    import os

    from openai import OpenAI

    # This VM's no_proxy can carry bracketed IPv6 entries that crash
    # httpx client construction (see AGENTS.md); sanitise in-process.
    for var in ("NO_PROXY", "no_proxy"):
        value = os.environ.get(var)
        if value and "[" in value:
            os.environ[var] = ",".join(
                part for part in value.split(",") if "[" not in part
            )

    model = (
        os.getenv("EQUATION_HARVEST_MODEL")
        or os.getenv("MECHANICS_EXTRACT_MODEL")
        or os.getenv("ASSUMPTION_EXTRACT_MODEL")
        or "gpt-4o-mini"
    )
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("no API key is configured")
    try:
        timeout = float(os.getenv("EQUATION_HARVEST_TIMEOUT_S", "45"))
    except ValueError:
        timeout = 45.0
    response = OpenAI(
        api_key=api_key, timeout=timeout, max_retries=0
    ).chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _HARVEST_SYSTEM_PROMPT},
            {"role": "user", "content": _harvest_prompt(calculation_slices(slices))},
        ],
        temperature=0.1,
    )
    content = (response.choices[0].message.content or "").strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else ""
        content = content.rsplit("```", 1)[0].strip()
    payload = json.loads(content)
    readings = payload.get("readings") if isinstance(payload, dict) else None
    if not isinstance(readings, list):
        raise RuntimeError("model harvest response carried no readings list")
    return {"readings": readings, "model": model}


def _locate_statement(
    slices: Sequence[Mapping[str, Any]], statement: str
) -> Optional[Dict[str, Any]]:
    """Find the verbatim statement in a slice; return filename + page.

    Matching is whitespace-flexible (the model's copy may collapse the
    PDF's line breaks) but word-exact: a paraphrase does not locate.
    """

    words = [re.escape(word) for word in str(statement or "").split() if word]
    if not words:
        return None
    pattern = re.compile(r"\s+".join(words), re.I)
    for slice_ in slices or []:
        match = pattern.search(str(slice_.get("text") or ""))
        if match:
            return {
                "filename": slice_.get("document_hint"),
                "page": _slice_page_at(slice_, match.start()),
            }
    # Fall back to a normalized containment check (punctuation drift).
    needle = _normalized(statement).rstrip(".")
    for slice_ in slices or []:
        if needle and needle in _normalized(str(slice_.get("text") or "")):
            return {"filename": slice_.get("document_hint"), "page": None}
    return None


def harvest_equations(
    artifact: Dict[str, Any],
    slices: Sequence[Mapping[str, Any]],
    *,
    at: str,
    model_caller: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run harvesting over the workspace's slices.

    Returns {"artifact", "created", "skipped", "warnings",
    "modelReadings"}.  Deterministic readings are always attempted;
    the model pass is attempted when slices state calculations, and
    its failure degrades to deterministic-only with a warning — the
    harvest endpoint always answers.
    """

    result = deepcopy(artifact or {})
    warnings: List[str] = []
    created: List[str] = []
    skipped: List[str] = []

    deterministic = deterministic_harvest(slices)
    applied = _apply_candidates(
        result, deterministic, at=at,
        source_kind="document", harvester_model="deterministic assists",
    )
    created += applied["created"]
    skipped += applied["skipped"]

    model_readings = 0
    bearing = calculation_slices(slices)
    if bearing:
        caller = model_caller or default_model_caller
        try:
            response = caller(slices)
            readings = response.get("readings") or []
            model_name = response.get("model")
        except Exception as exc:  # noqa: BLE001 - harvest degrades, never fails
            warnings.append(
                f"Model harvest unavailable ({type(exc).__name__}); "
                "deterministic readings only."
            )
            readings = []
            model_name = None
        candidates: List[Dict[str, Any]] = []
        for reading in readings:
            if not isinstance(reading, dict):
                continue
            model_readings += 1
            mechanic = str(reading.get("mechanic") or "")
            statement = reading.get("statement")
            located = (
                _locate_statement(slices, str(statement)) if statement else None
            )
            if statement and located is None:
                candidates.append({
                    "mechanic": mechanic,
                    "body": None,
                    "timing": None,
                    "statement": None,
                    "filename": None,
                    "page": None,
                    "note": (
                        "The model proposed a reading of a statement it "
                        f"quoted as “{str(statement)[:200]}”, which could "
                        "not be located in the document text, so nothing was "
                        "recorded as the filing's words."
                    ),
                })
                continue
            candidates.append({
                "mechanic": mechanic,
                "body": reading.get("body"),
                "timing": reading.get("timing"),
                "statement": statement,
                "filename": (located or {}).get("filename"),
                "page": (located or {}).get("page") or reading.get("page"),
                "assist": "model_reading",
            })
        applied = _apply_candidates(
            result, candidates, at=at,
            source_kind="document", harvester_model=model_name,
        )
        created += applied["created"]
        skipped += applied["skipped"]

    return {
        "artifact": result,
        "created": created,
        "skipped": skipped,
        "warnings": warnings,
        "modelReadings": model_readings,
    }


__all__ = [
    "BAND_UNITS",
    "BASIS_BY_SOURCE_KIND",
    "EQUATION_STATES",
    "MAX_SCHEDULE_DURATION",
    "MIGRATION_APPROVER",
    "SOURCE_KIND_LABELS",
    "SPECIMEN_APPROVER",
    "approve_equation",
    "author_equation",
    "banded_coi_body",
    "banded_surrender_body",
    "calculation_slices",
    "citation",
    "coi_body_for_unit",
    "crediting_body",
    "death_benefit_body",
    "deterministic_harvest",
    "equations_view",
    "graded_surrender_body",
    "harvest_equations",
    "in_force",
    "in_force_map",
    "materialize_legacy_equations",
    "nar_body",
    "new_record",
    "policy_fees_body",
    "premium_load_body",
    "preview_equation",
    "records",
    "records_for",
    "reject_equation",
    "surrender_body_for_unit",
    "validate_bands",
]


# ---------------------------------------------------------------------------
# Banded schedules (Phase 3 corrections, Phase 7 form).
#
# The band vocabulary and validation are the ones the corrections have
# always used (contiguous from year 1, only the final band open-ended,
# percentage values at most 100%).  What changed in Phase 7 is the
# output: bands compile into a formula-language ``bands`` node, not
# into materialised table rows dispatched by hidden code.
# ---------------------------------------------------------------------------

MAX_SCHEDULE_DURATION = 121  # workspace_ul_mechanics.MAX_DURATION

BAND_UNITS: Dict[str, Any] = {
    "surrender": ("percent_account_value", "percent_face", "per_1000_face", "fixed"),
    "coi": ("per_1000_monthly", "per_1000_annual", "percent_nar_annual"),
}


def _band_number(raw: Any, index: int, field: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Band {index + 1}: {field} must be a number") from exc
    if not (value == value) or value in (float("inf"), float("-inf")) or value < 0:
        raise ValueError(f"Band {index + 1}: {field} must be zero or greater")
    return value


def validate_bands(mechanic: str, bands: Any) -> List[Dict[str, Any]]:
    """Validate + normalise a banded schedule's band list.

    Bands must start at year 1, be contiguous (no gaps, no overlaps),
    and ascend.  Only the final band may be open-ended (``toYear``
    null); it is normalised to MAX_SCHEDULE_DURATION with
    ``openEnded`` set.  Band values must be non-negative; percentage
    units must be at most 100%.
    """

    if mechanic not in BAND_UNITS:
        raise ValueError(f"Banded schedules are not supported for {mechanic!r}")
    if not bands:
        raise ValueError("A banded schedule needs at least one band")
    normalised: List[Dict[str, Any]] = []
    expected_from = 1
    for index, raw in enumerate(bands):
        if not isinstance(raw, dict):
            raise ValueError(f"Band {index + 1}: expected an object describing the band")
        try:
            first = int(raw.get("fromYear"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Band {index + 1}: fromYear must be a whole number of years") from exc
        if first != expected_from:
            raise ValueError(
                f"Band {index + 1}: bands must be contiguous from year 1 with no gaps "
                f"or overlaps (expected this band to start at year {expected_from}, got {first})"
            )
        is_last = index == len(bands) - 1
        raw_to = raw.get("toYear")
        open_ended = raw_to is None
        if open_ended and not is_last:
            raise ValueError(f"Band {index + 1}: only the final band may be open-ended")
        try:
            last = MAX_SCHEDULE_DURATION if open_ended else int(raw_to)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Band {index + 1}: toYear must be a whole number of years") from exc
        if last < first or last > MAX_SCHEDULE_DURATION:
            raise ValueError(
                f"Band {index + 1}: toYear must be between {first} and {MAX_SCHEDULE_DURATION}"
            )
        unit = str(raw.get("unit") or "")
        if unit not in BAND_UNITS[mechanic]:
            raise ValueError(
                f"Band {index + 1}: unit must be one of: " + ", ".join(BAND_UNITS[mechanic])
            )
        band: Dict[str, Any] = {
            "fromYear": first,
            "toYear": last,
            "unit": unit,
            "value": _band_number(raw.get("value"), index, "value"),
        }
        if open_ended:
            band["openEnded"] = True
        if raw.get("gradeTo") is not None:
            band["gradeTo"] = _band_number(raw.get("gradeTo"), index, "gradeTo")
        for field in ("value", "gradeTo"):
            value = band.get(field)
            if value is None:
                continue
            if unit in ("percent_account_value", "percent_face", "percent_nar_annual") and value > 1:
                raise ValueError(f"Band {index + 1}: a percentage {field} must be at most 100%")
            if unit.startswith("per_1000") and value > 1000:
                raise ValueError(f"Band {index + 1}: a per-$1,000 {field} must be at most 1000")
        normalised.append(band)
        expected_from = last + 1
    return normalised


def _band_scalar(band: Mapping[str, Any]) -> Dict[str, Any]:
    """The band's value at the current duration, grading included."""

    start = float(band["value"])
    grade_to = band.get("gradeTo")
    if grade_to is None:
        return {"const": start}
    first, last = int(band["fromYear"]), int(band["toYear"])
    if last <= first:
        return {"const": float(grade_to)}
    return {"add": [
        {"const": start},
        {"mul": [
            {"const": float(grade_to) - start},
            {"div": [
                {"sub": [{"qty": "duration"}, {"const": first}]},
                {"const": last - first},
            ]},
        ]},
    ]}


def _bands_node(bands: Sequence[Mapping[str, Any]], apply_unit: Any) -> Dict[str, Any]:
    nodes = []
    for band in bands:
        nodes.append({
            "from": int(band["fromYear"]),
            "to": None if band.get("openEnded") and band.get("gradeTo") is None else int(band["toYear"]),
            "value": apply_unit(str(band["unit"]), _band_scalar(band)),
        })
    return {"bands": nodes}


def banded_surrender_body(bands: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    def apply(unit: str, scalar: Dict[str, Any]) -> Dict[str, Any]:
        if unit == "percent_account_value":
            return {"mul": [scalar, {"qty": "account_value"}]}
        if unit == "percent_face":
            return {"mul": [scalar, {"qty": "face_amount"}]}
        if unit == "per_1000_face":
            return {"mul": [scalar, {"div": [{"qty": "face_amount"}, {"const": 1000}]}]}
        return scalar  # fixed

    return _bands_node(bands, apply)


def banded_coi_body(bands: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    def apply(unit: str, scalar: Dict[str, Any]) -> Dict[str, Any]:
        per_thousand = {"mul": [{"div": [{"qty": "nar"}, {"const": 1000}]}, scalar]}
        if unit == "per_1000_monthly":
            return per_thousand
        if unit == "per_1000_annual":
            return {"div": [per_thousand, {"const": 12}]}
        return {"div": [{"mul": [{"qty": "nar"}, scalar]}, {"const": 12}]}  # percent_nar_annual

    return _bands_node(bands, apply)


def graded_surrender_body(basis: str, value: float, grading_years: int) -> Dict[str, Any]:
    """value on ``basis``, grading linearly to zero over the period."""

    factor = {"div": [
        {"sub": [{"const": grading_years + 1}, {"qty": "duration"}]},
        {"const": grading_years},
    ]}
    if basis == "percent_account_value":
        amount = {"mul": [{"qty": "account_value"}, {"const": value}]}
    elif basis == "percent_face":
        amount = {"mul": [{"qty": "face_amount"}, {"const": value}]}
    else:  # flat_amount
        amount = {"const": value}
    return {"if": {
        "cond": {"cmp": ["<=", {"qty": "duration"}, {"const": grading_years}]},
        "then": {"mul": [amount, factor]},
        "else": {"const": 0},
    }}
