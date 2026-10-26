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
import unicodedata
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
                        # The record's own reason first (Phase 8):
                        # the generic paragraph is the fallback, not
                        # the answer, when a precise reason was kept.
                        "note": (
                            (record.get("source") or {}).get("note")
                            or "The filing states this calculation but it could "
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
#
# The structuring bridge (Phase 8, docs/structuring-bridge.md): all
# matching — statement location and the deterministic patterns alike —
# runs over a CANONICAL form of the slice text, because the PDF text
# layer splits words mid-word ("surrende r", "policy va lue") and
# carries Unicode math glyphs (𝑞𝑥).  The canonical form is
# NFKC-folded, punctuation-folded, lowercased, and whitespace-free,
# with an index map back to the original text, so a match found in
# canonical space yields the filing's own sentence from the original
# text as the recorded statement — never the model's cleaned-up copy.
# ---------------------------------------------------------------------------

_FOLD_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-", "‐": "-", "­": "",
    " ": " ",
}


def _canon_with_map(text: Any) -> "tuple[str, List[int]]":
    """(canonical text, index map) for matching over extracted text.

    Canonical: NFKC-normalized (𝑞𝑥 -> qx, ligatures expanded),
    punctuation-folded, lowercased, all whitespace removed.  The index
    map gives, for each canonical character, its offset in the
    original text, so a canonical match span maps back to the
    original sentence.
    """

    canon_chars: List[str] = []
    index_map: List[int] = []
    for offset, ch in enumerate(str(text or "")):
        for fch in unicodedata.normalize("NFKC", ch):
            fch = _FOLD_MAP.get(fch, fch)
            if fch.isspace():
                continue
            canon_chars.append(fch.lower())
            index_map.append(offset)
    return "".join(canon_chars), index_map


def canon_text(text: Any) -> str:
    """The canonical form of a text or quote (see _canon_with_map)."""

    return _canon_with_map(text)[0]


def _canon_loose(text: Any) -> str:
    """Alphanumerics-only canonical form, for containment comparisons.

    Used only when deciding whether an unlocated model claim and a
    located statement are the same words: punctuation drift (an
    en-dash the claim dropped, a comma the extraction kept) must not
    defeat the comparison.  Never used for matching or validation.
    """

    return "".join(ch for ch in canon_text(text) if ch.isalnum())


def _canon_regex(pattern: str) -> "re.Pattern[str]":
    """Compile an authored regex for canonical text.

    The authored pattern is written against ordinary spaced text;
    canonical text has no whitespace and is already lowercase, so
    literal spaces and ``\\s`` atoms are dropped and the pattern is
    lowered.  Character classes and spans (``[^.]{0,120}?``) carry
    over unchanged — periods survive canonicalization.
    """

    out: List[str] = []
    i = 0
    src = pattern.lower()
    while i < len(src):
        ch = src[i]
        if ch == "\\" and i + 1 < len(src):
            nxt = src[i + 1]
            if nxt == "s":
                i += 2
                if i < len(src) and src[i] in "+*?":
                    i += 1
                continue
            out.append(src[i:i + 2])
            i += 2
            continue
        if ch == " ":
            i += 1
            continue
        out.append(ch)
        i += 1
    return re.compile("".join(out), re.S)


def _canon_match_span(
    match: "re.Match[str]", index_map: List[int]
) -> "tuple[int, int]":
    """Map a canonical match span back to original-text offsets."""

    start = index_map[match.start()]
    end = index_map[match.end() - 1] + 1 if match.end() > match.start() else start
    return start, end

_TIMING_SIGNALS = [
    (_canon_regex(r"deduct\w*\s+(?:monthly\s+)?in advance|beginning of (?:the|each) (?:policy )?month|before interest is credited"), "beginning"),
    (_canon_regex(r"in arrears|end of (?:the|each) (?:policy )?month|after interest (?:is )?credited"), "end"),
    (_canon_regex(r"middle of (?:the|each) (?:policy )?month|mid-month"), "middle"),
]

_NAR_PROSE = _canon_regex(
    r"net amount at risk[^.]{0,160}?(?:death benefit|benefit payable)[^.]{0,80}?"
    r"(?:less|minus|reduced by)[^.]{0,40}?account value"
)

# The same definition stated the other common way: "the difference
# between the death benefit and the policy value" (Promise UL form).
_NAR_DIFFERENCE = _canon_regex(
    r"net amount at risk[^.]{0,100}?difference between[^.]{0,80}?"
    r"death benefit[^.]{0,60}?(?:policy|account) value"
)

_SURRENDER_PCT = _canon_regex(
    r"surrender charge[^.]{0,120}?(\d+(?:\.\d+)?)\s*%\s*of the account value"
)
_SURRENDER_GRADING = _canon_regex(
    r"grad\w+ to (?:zero|0)\s*(?:%|percent)?\s*over (\d{1,2}) years"
)

_COI_RATE_PROSE = _canon_regex(
    r"cost of insurance[^.]{0,200}?(?:per\s+\$?1,?000|percent\w*\s+of\s+the\s+net\s+amount\s+at\s+risk)"
)

# --- Second-generation assists (Phase 8).  Each was written against a
# real filing sentence (see docs/structuring-bridge.md) and is kept
# narrow on purpose: the phrase must name the mechanic AND carry the
# parameter the body needs, in one breath.

# "The Premium Expense Charge is currently set at 10% for new issues"
# (with "applied to each premium" in the same passage) -> premium due
# x the stated percentage, as a const body: the rate is in the words.
_PREMIUM_PCT = _canon_regex(
    r"premium expense charge[^%]{0,240}?(?:set at|of)\s*(\d+(?:\.\d+)?)\s*%"
)
_PREMIUM_PCT_OF = _canon_regex(
    r"(\d+(?:\.\d+)?)\s*%\s*of\s+(?:each\s+)?premium"
)

# "An Administrative Charge is deducted at the beginning of each
# policy month..." -> the canonical fee-schedule rows_sum; the
# schedule carries the amounts, the statement states the deduction.
_ADMIN_CHARGE = _canon_regex(
    r"administrative charge[^.]{0,140}?deducted[^.]{0,140}?"
    r"(?:each policy month|monthly|policy month)"
)
# The memorandum's twin statement of the same charge: "The Expense
# Charge is calculated as a monthly amount per $1,000 of face
# amount..." — same body, different words.
_EXPENSE_MONTHLY = _canon_regex(
    r"expense charge[^.]{0,80}?monthly amount per\s+\$?1,?000"
)

# "The annual credited rate will not be less than the Guaranteed
# Minimum Annual Interest Rate shown in the Policy Specification
# which is currently set at 2% for new issues." -> the crediting
# body; the guaranteed rate is a chassis quantity, the percentage is
# captured for the record's note.
_CREDITING_GUARANTEED = _canon_regex(
    r"guaranteed minimum annual interest rate[^%]{0,200}?"
    r"set at\s*(\d+(?:\.\d+)?)\s*%"
)

# "Option A: Death Benefit = Face amount. In no case will the death
# benefit be less than the amount required to qualify under Internal
# Revenue Code Section 7702..." — both halves must be present in the
# slice: the level amount AND the qualification floor.
_DB_FACE_AMOUNT = _canon_regex(r"death benefit\s*=\s*face amount")
_DB_FLOOR = _canon_regex(
    r"in no case will the death benefit be less than|"
    r"less than the amount required to qualify|section 7702|"
    r"cash value accumulation test"
)

_CALCULATION_KEYWORDS = (
    "cost of insurance", "surrender charge", "net amount at risk",
    "death benefit", "expense charge", "premium load", "interest is credited",
    "credited interest", "monthly deduction",
    # Phase 8: the crediting and fee statements the first gate missed.
    "interest will be credited", "annual credited rate",
    "guaranteed minimum annual interest rate", "administrative charge",
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

    All matching runs over the canonical text (Phase 8 — the PDF text
    layer splits words mid-word); statements and pages are taken from
    the original text via the canonical index map.
    """

    candidates: List[Dict[str, Any]] = []
    for slice_ in slices or []:
        text = str(slice_.get("text") or "")
        if not text:
            continue
        canon, cmap = _canon_with_map(text)
        filename = slice_.get("document_hint")

        def _span(match: "re.Match[str]") -> "tuple[int, int]":
            return _canon_match_span(match, cmap)

        if "costofinsurance" in canon or "coi" in canon:
            for pattern, timing in _TIMING_SIGNALS:
                match = pattern.search(canon)
                if match:
                    start, end = _span(match)
                    candidates.append({
                        "mechanic": "coi_charge",
                        "body": None,
                        "timing": timing,
                        "statement": _sentence_at(text, start, end),
                        "filename": filename,
                        "page": _slice_page_at(slice_, start),
                        "assist": "coi_timing_prose",
                    })
                    break

        nar_match = _NAR_PROSE.search(canon) or _NAR_DIFFERENCE.search(canon)
        if nar_match:
            start, end = _span(nar_match)
            candidates.append({
                "mechanic": "nar_definition",
                "body": nar_body("unadjusted"),
                "timing": None,
                "statement": _sentence_at(text, start, end),
                "filename": filename,
                "page": _slice_page_at(slice_, start),
                "assist": "nar_prose",
            })

        pct_match = _SURRENDER_PCT.search(canon)
        grade_match = _SURRENDER_GRADING.search(canon)
        if pct_match and grade_match:
            percent = float(pct_match.group(1)) / 100.0
            grading_years = int(grade_match.group(1))
            if 0 < percent <= 1 and 1 <= grading_years <= 40:
                p_start, _ = _span(pct_match)
                _, g_end = _span(grade_match)
                candidates.append({
                    "mechanic": "surrender_charge",
                    "body": _graded_surrender_body(percent, grading_years),
                    "timing": None,
                    "statement": _sentence_at(text, p_start, g_end),
                    "filename": filename,
                    "page": _slice_page_at(slice_, p_start),
                    "assist": "surrender_grading_prose",
                })

        # --- Second-generation assists (Phase 8) -------------------
        premium_match = _PREMIUM_PCT.search(canon) or \
            _PREMIUM_PCT_OF.search(canon)
        if premium_match:
            pct = float(premium_match.group(1)) / 100.0
            if 0 < pct <= 1:
                start, end = _span(premium_match)
                candidates.append({
                    "mechanic": "premium_load",
                    # The rate is in the words, so the body carries
                    # it as a const — premium_load_body() would route
                    # through the fee table and default to 0 in a
                    # workspace whose table was never extracted.
                    "body": {"mul": [
                        {"qty": "premium_due"}, {"const": pct},
                    ]},
                    "timing": None,
                    "statement": _sentence_at(text, start, end),
                    "filename": filename,
                    "page": _slice_page_at(slice_, start),
                    "assist": "premium_percent_prose",
                    "note": "The filing states the premium expense "
                            f"charge as {premium_match.group(1)}% of "
                            "each premium; structured directly from "
                            "the stated percentage.",
                })
        admin_match = _ADMIN_CHARGE.search(canon) or \
            _EXPENSE_MONTHLY.search(canon)
        if admin_match:
            start, end = _span(admin_match)
            candidates.append({
                "mechanic": "policy_fees",
                "body": policy_fees_body(),
                "timing": None,
                "statement": _sentence_at(text, start, end),
                "filename": filename,
                "page": _slice_page_at(slice_, start),
                "assist": "admin_charge_prose",
                "note": "The filing states this charge is deducted "
                        "monthly; the amounts live in the fee "
                        "schedule, so the equation is the canonical "
                        "sum of the schedule's applicable rows.",
            })
        crediting_match = _CREDITING_GUARANTEED.search(canon)
        if crediting_match:
            start, end = _span(crediting_match)
            candidates.append({
                "mechanic": "crediting",
                "body": crediting_body(),
                "timing": None,
                "statement": _sentence_at(text, start, end),
                "filename": filename,
                "page": _slice_page_at(slice_, start),
                "assist": "crediting_guaranteed_prose",
                "note": "The filing guarantees the credited rate "
                        "will not be less than the guaranteed minimum "
                        "annual interest rate, stated as currently "
                        f"{crediting_match.group(1)}% for new issues.",
            })
        face_match = _DB_FACE_AMOUNT.search(canon)
        if face_match and _DB_FLOOR.search(canon):
            start, end = _span(face_match)
            candidates.append({
                "mechanic": "death_benefit",
                "body": death_benefit_body(),
                "timing": None,
                "statement": _sentence_at(text, start, end),
                "filename": filename,
                "page": _slice_page_at(slice_, start),
                "assist": "death_benefit_prose",
                "note": "The filing states the death benefit as the "
                        "face amount, never less than the amount "
                        "required to qualify as life insurance (the "
                        "corridor); structured as the greater of the "
                        "face amount and the corridor amount.",
            })
    return candidates


def _unextracted_table_block(
    body: Any, artifact: Mapping[str, Any]
) -> Optional[str]:
    """The first bare (default-less) coi/surrender lookup in a body
    whose table the workspace does not hold, if any.

    A default-less lookup cannot degrade gracefully when its table
    is absent — the number would be invented or the run would fail —
    so the bridge refuses to propose such a body until the table
    has been extracted (the no-silent-zero rule, applied to every
    candidate source, not just the deterministic pointers).
    Defaulted lookups (surrender's 0, the corridor's 1) state their
    own absence and are always allowed.
    """

    usable = (artifact or {}).get("usable") or {}
    blocked: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if set(node.keys()) == {"lookup"} and isinstance(
                node.get("lookup"), dict
            ):
                spec = node["lookup"]
                table = str(spec.get("table") or "")
                if table in ("coi", "surrender") and "default" not in spec:
                    if not list(usable.get(table) or []):
                        blocked.append(table)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(body)
    return blocked[0] if blocked else None


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
        body = candidate.get("body")
        errors: List[str] = []
        if body is not None:
            errors = _eq.validate_equation(mechanic, body)
        # A candidate statement spanning a passage can contain the
        # sentence an earlier record was filed under (the deterministic
        # assists and the located model reading choose different spans
        # of the same words).  For the upgrade paths below, an
        # unmapped record whose statement is contained in — or
        # contains — the candidate's counts as the same statement.
        contained_unmapped: List[Dict[str, Any]] = []
        if statement:
            candidate_loose = _canon_loose(statement)
            if candidate_loose:
                existing_ids = {r.get("id") for r in existing}
                for record in records_for(result, mechanic):
                    if record.get("state") != "unmapped":
                        continue
                    if record.get("id") in existing_ids:
                        continue
                    other_statement = (record.get("source") or {}).get("statement")
                    if not other_statement:
                        continue
                    other_loose = _canon_loose(other_statement)
                    if other_loose and (
                        other_loose in candidate_loose
                        or candidate_loose in other_loose
                    ):
                        contained_unmapped.append(record)
        if existing or contained_unmapped:
            unmapped_existing = [
                r for r in existing if r.get("state") == "unmapped"
            ] + contained_unmapped
            if unmapped_existing and body is not None and not errors:
                # Phase 8 upgrade: a statement first recorded as
                # stated-but-unmapped is superseded by a structured
                # reading of the same statement — the unmapped record
                # is preserved as superseded history, never deleted.
                # One guard: a MODEL reading may not supersede the
                # bridge's own table-pointer / statement-capture
                # record for the SAME statement (an exact statementKey
                # match).  Those records carry a deliberate caution
                # (e.g. the charge lives in a table this workspace
                # does not hold); the model's confidence does not
                # erase it, and the model's proposal for that exact
                # statement is skipped in its favor.  Passage-level
                # (contained) matches are not the same statement and
                # supersede freely, as do deterministic candidates —
                # including a later pointer whose table HAS been
                # extracted.
                if candidate.get("assist") == "model_reading":
                    existing_ids = {r.get("id") for r in existing}
                    targets = [
                        old for old in unmapped_existing
                        if old.get("id") not in existing_ids
                        or (old.get("source") or {}).get("assist")
                        not in ("table_pointer", "statement_capture")
                    ]
                    if not targets:
                        skipped.append(str(existing[0].get("id")))
                        continue
                    unmapped_existing = targets
                for old in unmapped_existing:
                    old["state"] = "superseded"
                    old["updatedAt"] = at
                    old_source = old.setdefault("source", {})
                    old_source["note"] = (
                        (old_source.get("note") or "")
                        + " Superseded by a structured reading of the "
                        "same statement in a later harvest."
                    ).strip()
                touched.add(mechanic)
            elif (
                unmapped_existing
                and candidate.get("note_authoritative")
                and candidate.get("note")
            ):
                # A deterministic capture with a precise reason may
                # sharpen an existing unmapped record's generic note.
                old = unmapped_existing[0]
                old_source = old.setdefault("source", {})
                old_note = str(old_source.get("note") or "")
                if not old_note or old_note.startswith(
                    "The statement could not be structured"
                ) or old_note.startswith("The model proposed a reading"):
                    old_source["note"] = candidate["note"]
                    old["updatedAt"] = at
                skipped.append(str(old.get("id")))
                continue
            elif existing:
                skipped.append(str(existing[0].get("id")))
                continue
            else:
                skipped.append(str(contained_unmapped[0].get("id")))
                continue
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
        blocked_table = None
        proposed_body = None
        # Only bodies the candidate ARRIVED with are blocked — a
        # timing statement's body, copied from the human-approved
        # in-force equation, is not a new proposal.
        if state == "pending" and body is not None \
                and candidate.get("body") is not None:
            blocked_table = _unextracted_table_block(body, result)
            if blocked_table:
                proposed_body = body
                body = None
                state = "unmapped"
                table_label = (
                    "COI rate" if blocked_table == "coi"
                    else "surrender schedule"
                )
                note = (
                    f"The proposed equation reads the {table_label} "
                    "table, which has not been extracted into this "
                    "workspace yet, so it cannot be transcribed yet. "
                    "Extract or accept the table, then re-run harvest."
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
        if errors:
            # The pane's "why" must be answerable: keep the rejected
            # body and the validator's exact words on the record.
            record["source"]["validationErrors"] = errors
            record["source"]["rejectedBody"] = candidate.get("body")
        if blocked_table:
            record["source"]["rejectedBody"] = proposed_body
            record["source"]["blockedReason"] = "table_not_extracted"
        if candidate.get("claimedStatement"):
            record["source"]["claimedStatement"] = candidate["claimedStatement"]
        result.setdefault("equations", []).append(record)
        created.append(str(record["id"]))
        touched.add(mechanic)
        if statement:
            # Phase 8: a located statement supersedes an earlier
            # unlocatable model claim of the same words — the filing's
            # own sentence replaces the model's paraphrase as the
            # record of what was stated.
            new_canon = _canon_loose(statement)
            for other in records_for(result, mechanic):
                if other is record or other.get("state") != "unmapped":
                    continue
                other_source = other.get("source") or {}
                if other_source.get("statement"):
                    continue
                claim = other_source.get("claimedStatement")
                if not claim:
                    note_match = re.search(
                        r"“([^”]+)”", str(other_source.get("note") or "")
                    )
                    claim = note_match.group(1) if note_match else None
                if not claim:
                    continue
                claim_canon = _canon_loose(claim)
                if claim_canon and (
                    claim_canon in new_canon or new_canon in claim_canon
                ):
                    other["state"] = "superseded"
                    other["updatedAt"] = at
                    other_source["note"] = (
                        (other_source.get("note") or "")
                        + " Superseded: the statement was located in "
                        "the document text in a later harvest and "
                        "recorded from the filing's own words."
                    ).strip()
    for mechanic in touched:
        _refresh_conflicts(result, mechanic)
    result["equations"] = records(result)
    return {"created": created, "skipped": skipped}


# --- Table pointers and statement captures (Phase 8) ----------------
#
# Some filing statements do not state a calculation — they point at
# one (rates "shown in Appendix 2", a charge "in accordance with the
# schedule shown in" an exhibit), derive one (monthly COI rates
# converted from annual mortality), grade one (equal annual
# decrements), or state a purpose (nonforfeiture limits).  These are
# captured deterministically with the precise reason they cannot be
# structured, because model coverage of them is a lottery.  A pointer
# becomes a real pending equation ONLY when the table it names is in
# the artifact's usable set — the bridge never proposes a lookup
# against a table the workspace does not hold (no silent zero).

_COI_TABLE_POINTER = _canon_regex(
    r"cost of insurance rates are shown in|coi rates are shown in"
)
_SURRENDER_SCHEDULE_POINTER = _canon_regex(
    r"surrender charge[^.]{0,300}?in accordance with the schedule shown in"
)
_COI_CONVERSION_CAPTURE = _canon_regex(
    r"converted from an annual to monthly coi rate|"
    r"monthly coi rate[^.]{0,140}?lesser of"
)
_SURRENDER_DECREMENT_CAPTURE = _canon_regex(
    r"surrender charge[^.]{0,160}?equal annual decrements"
)
_NONFORFEITURE_CAPTURE = _canon_regex(
    r"surrender charges are set to meet nonforfeiture limits"
)
_DB_QUALIFICATION_CAPTURE = _canon_regex(r"death benefit qualification test")


def _table_pointer_candidates(
    artifact: Mapping[str, Any],
    slices: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Pointer/capture candidates (deterministic, artifact-aware)."""

    usable = (artifact or {}).get("usable") or {}
    candidates: List[Dict[str, Any]] = []
    for slice_ in slices or []:
        text = str(slice_.get("text") or "")
        if not text:
            continue
        canon, cmap = _canon_with_map(text)
        filename = slice_.get("document_hint")

        def add(mechanic: str, match: "re.Match[str]",
                body: Optional[Dict[str, Any]], note: str,
                assist: str) -> None:
            start, end = _canon_match_span(match, cmap)
            candidates.append({
                "mechanic": mechanic,
                "body": body,
                "timing": None,
                "statement": _sentence_at(text, start, end),
                "filename": filename,
                "page": _slice_page_at(slice_, start),
                "assist": assist,
                "note": note,
                "note_authoritative": True,
            })

        coi_pointer = _COI_TABLE_POINTER.search(canon)
        if coi_pointer:
            unit, _mixed = _first_unit(list(usable.get("coi") or []), "rate_unit")
            body = coi_body_for_unit(unit) if unit else None
            add(
                "coi_charge", coi_pointer, body,
                "The filing states the charge through the filed COI "
                "rate table this statement points to; structured as "
                "the table's rate applied to the net amount at risk."
                if body else
                "The filing points to the maximum cost of insurance "
                "rates in an appendix table. The rates themselves are "
                "a table, and no usable COI table has been extracted "
                "into this workspace yet, so the charge equation "
                "(table rate applied to the net amount at risk) "
                "cannot be transcribed. Extract or accept the COI "
                "table, then re-run harvest.",
                "table_pointer",
            )
        surrender_pointer = _SURRENDER_SCHEDULE_POINTER.search(canon)
        if surrender_pointer:
            unit, _mixed = _first_unit(
                list(usable.get("surrender") or []), "charge_unit"
            )
            body = surrender_body_for_unit(unit) if unit else None
            add(
                "surrender_charge", surrender_pointer, body,
                "The filing states the charge through the filed "
                "surrender schedule this statement points to; "
                "structured from that schedule."
                if body else
                "The filing states the surrender charge as a schedule "
                "amount per $1,000 of initial face amount (by issue "
                "age and gender), in accordance with the schedule. "
                "The amounts are a table, and no usable surrender "
                "schedule has been extracted into this workspace yet, "
                "so the equation cannot be transcribed. Extract or "
                "accept the surrender schedule, then re-run harvest.",
                "table_pointer",
            )
        conversion = _COI_CONVERSION_CAPTURE.search(canon)
        if conversion:
            add(
                "coi_charge", conversion, None,
                "The filing states how the COI table's monthly rates "
                "are derived from annual mortality (qx): the monthly "
                "rate is the lesser of the mortality-derived monthly "
                "rate and 1/12. That derivation produces the rate "
                "table — it is not the charge equation, and the "
                "formula language has no mortality quantity distinct "
                "from the table's rate — so the statement is "
                "recorded, not structured. The charge equation "
                "awaits the COI table.",
                "statement_capture",
            )
        decrement = _SURRENDER_DECREMENT_CAPTURE.search(canon)
        if decrement:
            add(
                "surrender_charge", decrement, None,
                "The filing states the surrender charge grades down "
                "by equal annual decrements to zero after the "
                "surrender charge period. The per-year amounts live "
                "in the surrender schedule, which has not been "
                "extracted into this workspace yet.",
                "statement_capture",
            )
        nonforfeiture = _NONFORFEITURE_CAPTURE.search(canon)
        if nonforfeiture:
            add(
                "surrender_charge", nonforfeiture, None,
                "The filing states the purpose the surrender charges "
                "are set to meet (nonforfeiture limits), not a "
                "calculation; the charge itself is stated as the "
                "schedule.",
                "statement_capture",
            )
        qualification = _DB_QUALIFICATION_CAPTURE.search(canon)
        if qualification:
            add(
                "death_benefit", qualification, None,
                "The filing points to the death benefit qualification "
                "test (the §7702 cash value accumulation test) the "
                "policy must satisfy; the test's percentages are "
                "shown in the policy specifications. The corridor "
                "equation is proposed from the Option A statement; "
                "this pointer is recorded for completeness.",
                "statement_capture",
            )
    return candidates


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


def _template_bodies() -> Dict[str, Any]:
    """The canonical body per mechanic shape, for prompts and repair.

    The model's job is to pick the template that matches the
    statement's shape and fill only the parameters the statement
    itself states — never to invent formula syntax.
    """

    return {
        "coi_charge — rate table per $1,000 of NAR, monthly":
            coi_body_for_unit("per_1000_monthly"),
        "coi_charge — rate table per $1,000 of NAR, annual":
            coi_body_for_unit("per_1000_annual"),
        "nar_definition — death benefit less account value":
            nar_body("unadjusted"),
        "nar_definition — factor-adjusted":
            nar_body("factor_adjusted"),
        "death_benefit — face amount with corridor floor":
            death_benefit_body(),
        "surrender_charge — schedule per $1,000 of face":
            surrender_body_for_unit("per_1000_face"),
        "surrender_charge — schedule % of account value":
            surrender_body_for_unit("percent_account_value"),
        "premium_load — stated percentage of each premium "
        "(replace the const with the stated percentage, as a decimal)":
            {"mul": [{"qty": "premium_due"}, {"const": 0.1}]},
        "policy_fees — monthly fee schedule sum":
            policy_fees_body(),
        "crediting — guaranteed-rate crediting":
            crediting_body(),
    }


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
        "row_amount and row_unit. Each node is {\"<operator>\": ...} — "
        "for example {\"mul\": [{\"qty\": \"premium_due\"}, {\"const\": 0.1}]} "
        "is premium due times 10%. There is no \"operator\"/\"operands\" "
        "form. Quantities per mechanic: "
        + json.dumps(quantities)
        + ". The coi_charge mechanic may also carry a timing attribute: "
        "beginning, middle, or end (when the COI is deducted within the "
        "month, if the filing states it).\n\n"
        "Canonical bodies — when a statement matches one of these "
        "shapes, return that body, filling only the parameters the "
        "statement itself states (a stated percentage becomes the "
        "const): "
        + json.dumps(_template_bodies())
        + "\n\nRules: copy each statement EXACTLY as printed, odd "
        "spacing included — never paraphrase, summarize, or clean it "
        "up, and never write a sentence of your own as a statement. A "
        "percentage of premium stated in words becomes a const "
        "multiplier on premium_due, never a table lookup. A charge "
        "the filing states as a table (rates or amounts 'shown in' an "
        "appendix or schedule) uses the matching canonical lookup "
        "body. Report EVERY stated calculation for the seven "
        "mechanics, including interest crediting and the net amount "
        "at risk, even when you must return body null for it.\n\n"
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


_BATCH_CHAR_BUDGET = 40000


def _reading_batches(
    slices: Sequence[Mapping[str, Any]],
) -> List[List[Mapping[str, Any]]]:
    """Group slices into per-document batches under a character budget.

    One mega-call over every bearing slice measured ~48k prompt
    tokens on a real filing package and its failure lost the whole
    pass; batches keep each call small enough to parse, retry, and
    attribute.
    """

    by_document: Dict[str, List[Mapping[str, Any]]] = {}
    order: List[str] = []
    for slice_ in slices:
        key = str(slice_.get("document_hint") or "")
        if key not in by_document:
            by_document[key] = []
            order.append(key)
        by_document[key].append(slice_)
    batches: List[List[Mapping[str, Any]]] = []
    for key in order:
        batch: List[Mapping[str, Any]] = []
        size = 0
        for slice_ in by_document[key]:
            chars = min(len(str(slice_.get("text") or "")), 6000)
            if batch and size + chars > _BATCH_CHAR_BUDGET:
                batches.append(batch)
                batch, size = [], 0
            batch.append(slice_)
            size += chars
        if batch:
            batches.append(batch)
    return batches


def _parse_model_payload(content: Any) -> Any:
    """Parse a model response into JSON, tolerantly but loudly.

    Fallback order: strip a code fence, then parse; else extract the
    first balanced {...} object and parse that.  Anything else raises
    ValueError naming the failure — a parse failure must never again
    surface as a bare, unexplained degradation.
    """

    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if "```" in text:
            text = text.rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        pass
    start = text.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            ch = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:index + 1])
    raise ValueError(
        "model output carried no parseable JSON object "
        f"(begins: {text[:120]!r})"
    )


def _openai_client_and_model() -> "tuple[Any, str]":
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
        timeout = float(os.getenv("EQUATION_HARVEST_TIMEOUT_S", "120"))
    except ValueError:
        timeout = 120.0
    return OpenAI(api_key=api_key, timeout=timeout, max_retries=0), model


def _chat_json(client: Any, model: str, messages: List[Dict[str, str]]) -> Any:
    """One JSON-mode chat call; returns the parsed payload.

    Requests structured output (response_format json_object); if the
    provider rejects that parameter, retries once without it — the
    tolerant parser is the backstop either way.  Raises with the
    cause named (finish reason / parse detail) on failure.
    """

    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001 - retry only the known case
        if "response_format" not in str(exc):
            raise
        kwargs.pop("response_format")
        response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    content = choice.message.content or ""
    try:
        payload = _parse_model_payload(content)
    except ValueError as exc:
        raise RuntimeError(
            f"model output unparseable ({exc}); "
            f"finish_reason={getattr(choice, 'finish_reason', None)}, "
            f"content_chars={len(content)}"
        ) from exc
    return payload, getattr(choice, "finish_reason", None)


def _read_batch(
    client: Any, model: str, batch: List[Mapping[str, Any]], depth: int = 0
) -> List[Any]:
    """Read one batch; a truncated or unparseable batch splits once."""

    try:
        payload, finish_reason = _chat_json(client, model, [
            {"role": "system", "content": _HARVEST_SYSTEM_PROMPT},
            {"role": "user", "content": _harvest_prompt(batch)},
        ])
    except RuntimeError:
        if len(batch) > 1 and depth < 2:
            mid = len(batch) // 2
            return (
                _read_batch(client, model, batch[:mid], depth + 1)
                + _read_batch(client, model, batch[mid:], depth + 1)
            )
        raise
    if finish_reason == "length" and len(batch) > 1 and depth < 2:
        mid = len(batch) // 2
        return (
            _read_batch(client, model, batch[:mid], depth + 1)
            + _read_batch(client, model, batch[mid:], depth + 1)
        )
    readings = payload.get("readings") if isinstance(payload, dict) else None
    if not isinstance(readings, list):
        raise RuntimeError("model harvest response carried no readings list")
    return readings


def default_model_caller(slices: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Ask the configured model for structured readings of the slices.

    Batched per document under a character budget, JSON-mode
    requested, tolerantly parsed.  Fail-soft at the harvest level:
    any failure raises with its cause named, and the harvest keeps
    the deterministic readings with that cause in the warning.
    """

    client, model = _openai_client_and_model()
    readings: List[Any] = []
    batches = _reading_batches(calculation_slices(slices))
    for batch in batches:
        readings.extend(_read_batch(client, model, batch))
    return {"readings": readings, "model": model, "batches": len(batches)}


_REPAIR_SYSTEM_PROMPT = (
    "You are an actuarial modeling assistant. You repair a structured "
    "reading of a life insurance filing statement so it validates in "
    "the formula language, or you decline. Output valid JSON only."
)


def default_repair_caller(
    mechanic: str,
    statement: str,
    body: Optional[Dict[str, Any]],
    errors: Sequence[str],
) -> Optional[Dict[str, Any]]:
    """One repair attempt: statement + body + the validator's errors.

    Returns the corrected body, or None when the statement cannot be
    expressed in the formula language.  The caller validates whatever
    comes back — a repair is a proposal, never a bypass.
    """

    client, model = _openai_client_and_model()
    templates = {
        key: value for key, value in _template_bodies().items()
        if key.startswith(mechanic)
    }
    prompt = (
        f"Mechanic: {mechanic}\n"
        f"Statement (verbatim from the filing): {statement}\n"
        "Quantities allowed for this mechanic: "
        + json.dumps(sorted(_eq.quantities_for(mechanic)))
        + "\nCanonical bodies for this mechanic: "
        + json.dumps(templates)
        + "\nFormula language: a JSON object with exactly one operator "
        "key — {\"<operator>\": ...}; operators const, qty, add, sub, "
        "mul, div, neg, min, max, pow, if {cond, then, else}, cmp "
        "[op, a, b], and/or/not, bands, lookup {table, field, where?, "
        "default?}, rows_sum {table, where?, exclude_where?, expr}. "
        "Tables: coi(rate), surrender(charge), fees(amount), "
        "nar_factors(factor), corridor(percentage). There is no "
        "\"operator\"/\"operands\" form.\n"
        f"Current body: {json.dumps(body)}\n"
        f"Validator errors: {json.dumps(list(errors))}\n"
        "Translate the current body's SYNTAX into the formula "
        "language only: never add, remove, or change a quantity, "
        "constant, or table — the arithmetic content must stay "
        "exactly what the current body already says (renaming a "
        "quantity to its canonical name above is allowed). Return "
        "one JSON object {\"body\": <the corrected formula JSON>}, "
        "or {\"body\": null} if the current body's arithmetic cannot "
        "be expressed in the formula language."
    )
    payload, _finish = _chat_json(client, model, [
        {"role": "system", "content": _REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ])
    if isinstance(payload, dict) and "body" in payload:
        return payload.get("body")
    return None


def _locate_statement(
    slices: Sequence[Mapping[str, Any]], statement: str
) -> Optional[Dict[str, Any]]:
    """Find the verbatim statement in a slice; return its provenance.

    Matching runs over the canonical text (Phase 8): the PDF layer
    splits words mid-word ("surrende r") and carries Unicode math
    glyphs, so word-exact matching against the raw text refused
    quotes that ARE the filing's words.  Canonical matching is still
    word-exact — a paraphrase does not locate — but the recorded
    statement is the slice's own sentence around the match, never
    the model's cleaned-up copy.  Returns {filename, page, statement}.
    """

    needle = canon_text(statement)
    if not needle:
        return None
    for slice_ in slices or []:
        text = str(slice_.get("text") or "")
        if not text:
            continue
        canon, cmap = _canon_with_map(text)
        index = canon.find(needle)
        span = len(needle)
        if index < 0 and len(needle) > 60:
            # The quote may run past the sentence it names (or pick up
            # the next sentence's start); its first sentence locating
            # is enough to anchor the record.
            cut = needle.find(".", 40)
            if cut > 0:
                index = canon.find(needle[:cut + 1])
                span = cut + 1
        if index < 0:
            continue
        start = cmap[index]
        end = cmap[index + span - 1] + 1
        return {
            "filename": slice_.get("document_hint"),
            "page": _slice_page_at(slice_, start),
            "statement": _sentence_at(text, start, end),
        }
    return None


def _body_leaves(body: Any) -> List["tuple[str, str]"]:
    """The content leaves of a formula body, as a sorted multiset.

    Quantities, constants, strings, and table references — the
    arithmetic content of the body, independent of its syntax shape.
    The walk is generic (it descends through any dict/list), so a
    body written in the wrong node dialect yields the same leaves
    as its canonical translation.
    """

    leaves: List["tuple[str, str]"] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            keys = set(node.keys())
            if keys == {"qty"}:
                leaves.append(("qty", str(node["qty"])))
                return
            if keys == {"const"}:
                value = node["const"]
                leaves.append((
                    "const",
                    repr(float(value)) if isinstance(value, (int, float))
                    else repr(value),
                ))
                return
            if keys == {"str"}:
                leaves.append(("str", str(node["str"])))
                return
            if keys == {"lookup"} and isinstance(node.get("lookup"), dict):
                leaves.append(("lookup", str(node["lookup"].get("table"))))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(body)
    return sorted(leaves)


def _leaves_compatible(
    original: List["tuple[str, str]"],
    repaired: List["tuple[str, str]"],
    mechanic: str,
) -> bool:
    """May a repaired body replace the proposed one?

    Identical content always may.  Otherwise the only permitted
    change is renaming quantities that are invalid for the mechanic
    into valid ones, one-for-one, with all other content untouched.
    """

    if original == repaired:
        return True
    from collections import Counter

    original_counts = Counter(original)
    repaired_counts = Counter(repaired)
    for kind in ("const", "str", "lookup"):
        if Counter({k: v for k, v in original_counts.items() if k[0] == kind}) != \
                Counter({k: v for k, v in repaired_counts.items() if k[0] == kind}):
            return False
    removed = original_counts - repaired_counts
    added = repaired_counts - original_counts
    if any(kind != "qty" for kind, _value in removed) or \
            any(kind != "qty" for kind, _value in added):
        return False
    if sum(removed.values()) != sum(added.values()):
        return False
    valid = _eq.quantities_for(mechanic)
    return all(value not in valid for _k, value in removed) and \
        all(value in valid for _k, value in added)


# A located model reading is filed under the mechanic it names; the
# statement itself must mention that mechanic's subject.  A reading
# whose statement never mentions it is a misfiling (the rehearsal
# filed a Net Cash Surrender Value sentence under nar_definition
# with an invented body) — recorded, never structured.
_MECHANIC_ANCHORS: Dict[str, "tuple[str, ...]"] = {
    "coi_charge": ("costofinsurance", "coi"),
    "surrender_charge": ("surrender",),
    "premium_load": ("premium",),
    "policy_fees": ("charge", "fee"),
    "crediting": ("credit", "interest"),
    "nar_definition": ("netamountatrisk",),
    "death_benefit": ("deathbenefit",),
}


def harvest_equations(
    artifact: Dict[str, Any],
    slices: Sequence[Mapping[str, Any]],
    *,
    at: str,
    model_caller: Optional[Any] = None,
    repair_caller: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run harvesting over the workspace's slices.

    Returns {"artifact", "created", "skipped", "warnings",
    "modelReadings", "repairLog", "coverage"}.  Deterministic
    readings (prose assists, then table pointers/captures) are always
    attempted; the model pass is attempted when slices state
    calculations, and its failure degrades to deterministic-only with
    a warning naming the cause — the harvest endpoint always answers.

    Repair (Phase 8): a located model reading whose body fails
    validation gets up to two repair attempts fed the validator's
    exact errors, but only when a repair caller is available: the
    real default, or one injected alongside the model caller.  An
    injected fake model caller never triggers repair calls, so
    tests stay deterministic.  Repair may translate syntax but
    never change the arithmetic content (leaf-checked); a reading
    that still fails is recorded unmapped with its validation
    errors and rejected body.  A located reading whose statement
    never mentions the mechanic it was filed under is recorded as
    a misfiling, never structured.

    Coverage: any mechanic with no record at all after the run is
    named in coverage as "no_statement_found" — a silent blank is
    not an acceptable harvest outcome.
    """

    result = deepcopy(artifact or {})
    warnings: List[str] = []
    created: List[str] = []
    skipped: List[str] = []
    repair_log: List[Dict[str, Any]] = []

    deterministic = deterministic_harvest(slices)
    applied = _apply_candidates(
        result, deterministic, at=at,
        source_kind="document", harvester_model="deterministic assists",
    )
    created += applied["created"]
    skipped += applied["skipped"]

    pointers = _table_pointer_candidates(result, slices)
    applied = _apply_candidates(
        result, pointers, at=at,
        source_kind="document", harvester_model="deterministic assists",
    )
    created += applied["created"]
    skipped += applied["skipped"]

    if repair_caller is not None:
        repair = repair_caller
    elif model_caller is None:
        repair = default_repair_caller
    else:
        repair = None

    def attempt_repairs(
        mechanic: str,
        statement: str,
        body: Dict[str, Any],
        errors: List[str],
    ) -> "tuple[Dict[str, Any], List[str], bool]":
        """Bounded repair loop over an INVALID body.

        Repair may translate syntax — the wrong node dialect, a
        misspelled quantity name — but it may not change the
        arithmetic: a repaired body is adopted only when its leaf
        content (quantities, constants, strings, table references)
        matches the proposed body's, allowing only renames of
        quantities that are invalid for the mechanic into valid
        ones.  A repair that invents content is rejected and the
        reading stays unmapped with its original evidence.  (The
        first live rehearsal showed why: unconstrained repairs
        "fixed" bodies into different calculations.)  Null bodies
        are never repaired — with the canonical templates in the
        prompt, a model that proposes no body has declined, and
        second-guessing a decline is invention.
        """

        original_leaves = _body_leaves(body)
        current_body = body
        current_errors = list(errors)
        attempted = False
        for _attempt in range(2):
            if repair is None:
                break
            attempted = True
            entry: Dict[str, Any] = {
                "mechanic": mechanic,
                "statement": str(statement)[:160],
                "errors": list(current_errors),
            }
            try:
                proposed = repair(
                    mechanic, statement, current_body, current_errors
                )
            except Exception as exc:  # noqa: BLE001 - repair is best-effort
                entry["outcome"] = f"repair call failed ({type(exc).__name__})"
                repair_log.append(entry)
                break
            if proposed is None:
                entry["outcome"] = "declined — not expressible"
                repair_log.append(entry)
                break
            if not _leaves_compatible(original_leaves, _body_leaves(proposed), mechanic):
                entry["outcome"] = (
                    "rejected — the repair changed the arithmetic "
                    "content (quantities/constants), which repair "
                    "may not do"
                )
                repair_log.append(entry)
                break
            new_errors = _eq.validate_equation(mechanic, proposed)
            entry["outcome"] = "fixed" if not new_errors else "still invalid"
            if new_errors:
                entry["remainingErrors"] = new_errors
            repair_log.append(entry)
            current_body, current_errors = proposed, new_errors
            if not new_errors:
                break
        return current_body, current_errors, attempted

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
                f"Model harvest unavailable ({type(exc).__name__}: {exc}); "
                "deterministic readings only."
            )
            readings = []
            model_name = None
        candidates: List[Dict[str, Any]] = []
        unreadable = 0
        for reading in readings:
            if not isinstance(reading, dict):
                continue
            model_readings += 1
            mechanic = str(reading.get("mechanic") or "")
            statement = reading.get("statement")
            if not statement:
                # A reading with no statement carries nothing the
                # doctrine protects — there is no statement to
                # preserve — so it records nothing at all.
                unreadable += 1
                continue
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
                    "claimedStatement": str(statement)[:600],
                    "note": (
                        "The model proposed a reading of a statement it "
                        f"quoted as “{str(statement)[:200]}”, which could "
                        "not be located in the document text, so nothing was "
                        "recorded as the filing's words."
                    ),
                })
                continue
            located_statement = (located or {}).get("statement") or statement
            body = reading.get("body")
            errors: List[str] = []
            if body is not None:
                errors = _eq.validate_equation(mechanic, body) \
                    if mechanic in _eq.MECHANICS else []
            note = None
            anchors = _MECHANIC_ANCHORS.get(mechanic) or ()
            if anchors and located_statement and not any(
                anchor in canon_text(located_statement) for anchor in anchors
            ):
                # Misfiling: the statement does not mention the
                # mechanic it was filed under.  Record it under the
                # filed mechanic (nothing is dropped) with the reason,
                # but never structure it and never repair it.
                body = None
                errors = []
                note = (
                    "The model filed this statement under "
                    f"{_eq.MECHANIC_LABELS.get(mechanic, mechanic)}, but "
                    "the statement does not mention that mechanic — it "
                    "appears misfiled, so it is recorded, not structured."
                )
            elif body is None:
                note = (
                    "The model located this statement in the filing but "
                    "proposed no equation for it; recorded as stated, "
                    "not structured."
                )
            else:
                key = _statement_key(mechanic, located_statement)
                # Repair is skipped only when a record already stands
                # that _apply_candidates would keep unconditionally;
                # an existing UNMAPPED record is the upgrade case,
                # where a repaired body is exactly what supersedes it.
                already_recorded = True
                if mechanic in _eq.MECHANICS and key:
                    already_recorded = any(
                        (record.get("source") or {}).get("statementKey") == key
                        and record.get("state") != "unmapped"
                        for record in records_for(result, mechanic)
                    )
                if not already_recorded and errors:
                    body, errors, _attempted = attempt_repairs(
                        mechanic, str(located_statement or ""), body, errors
                    )
            candidates.append({
                "mechanic": mechanic,
                "body": body,
                "timing": reading.get("timing"),
                "statement": located_statement,
                "filename": (located or {}).get("filename"),
                "page": (located or {}).get("page") or reading.get("page"),
                "assist": "model_reading",
                "note": note,
            })
        if unreadable:
            warnings.append(
                f"Model returned {unreadable} reading(s) with no "
                "statement; nothing was recorded for them."
            )
        applied = _apply_candidates(
            result, candidates, at=at,
            source_kind="document", harvester_model=model_name,
        )
        created += applied["created"]
        skipped += applied["skipped"]

    coverage = [
        {
            "mechanic": mechanic,
            "status": "no_statement_found",
            "note": "No statement for this mechanic was found in the "
                    "workspace's documents.",
        }
        for mechanic in _eq.MECHANICS
        if not records_for(result, mechanic)
    ]

    return {
        "artifact": result,
        "created": created,
        "skipped": skipped,
        "warnings": warnings,
        "modelReadings": model_readings,
        "repairLog": repair_log,
        "coverage": coverage,
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
