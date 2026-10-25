"""Phase 3 (corrections in plain English): the "This should be…" layer.

Eddy (Aug 7, 2026): when the math is wrong, the actuary should be able to
say so inside the product — "we just tell it, hey, this is what the
calculation should be" — not file a code change.  Phase 2 gave the
chassis editable slots; this module gives it *corrections*: statements
about how a calculation should work, stored as first-class product data.

A correction is an override record on the mechanics artifact
(``artifact["corrections"][mechanic]``) carrying:

* the user's own words (``text``) and provenance (who, when);
* the structured variant it maps to (surrender basis, COI timing, NAR
  definition) with its parameters;
* a confirm-back restatement in actuarial language — the exact sentence
  the user confirmed before anything applied;
* what it replaced (``replaces``): the prior in-force status, a plain
  description of the prior basis, and the prior rows themselves, so a
  filed value a correction overrides is preserved in the record, never
  silently lost.

Precedence is deliberate and loud: corrections sit above workspace edits,
accepted filed tables, synthetic tables, and placeholders.  A correction
that overrides a filed value wins — explicit user intent — but the
ledger derivation and the change history say so (basis ``corrected``,
the filed value kept in the record).

Application is deterministic.  Table-shaped corrections (surrender
basis) materialise into ``usable`` rows stamped with correction
provenance, validated by the same validators ingestion uses.
Setting-shaped corrections (COI timing, NAR definition) ride into the
projection loop through ``executable_settings`` and are applied by the
loop's own arithmetic.  No model interprets a correction at run time;
free text is only ever *suggested* a mapping at authoring time (see
``suggest_variant``), and the user confirms or rejects the suggestion.
Unmapped text is captured as a feature request by the caller — never
dropped, never guessed at.

Corrections survive analysis re-runs exactly like Phase 2 edits: the
analysis rebuilds the artifact from documents and then re-applies edits
and corrections (``reapply_corrections``) before anything is stored.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any, Dict, List, Optional
import uuid

from actuarypoc.domain import rule_bank
from actuarypoc.extract.workspace_mechanics_panel import (
    _change_record,
    _slot_status,
    _summarize_rows,
    _validate_canonical_rows,
)


CORRECTION_SOURCE_TYPE = "correction"

# The workspace feature-request capability under which unmapped
# corrections are captured (see the server's correction endpoints).
CORRECTION_REQUEST_CAPABILITY_ID = "mechanics_correction"

# Phase 4 (the rule bank): the correction variants resolve through the
# bank — the vocabularies below are the bank registry's, so a timing,
# definition, or basis the bank does not know cannot be corrected into
# existence here either.
COI_TIMINGS = tuple(rule_bank.COI_TIMING_SWITCHES)
NAR_DEFINITIONS = tuple(rule_bank.NAR_DEFINITION_SWITCHES)
_GRADED_SWITCH = rule_bank.get_switch("surrender.schedule.graded")
SURRENDER_BASES = next(
    spec.choices for spec in _GRADED_SWITCH.params if spec.name == "basis"
)

# Structured variants, keyed by the slot they attach to.  Each variant
# names the banked switches it resolves through (``bankSwitches``):
# corrections and slot defaults alike execute bank code, never a
# private copy of a formula.
VARIANTS_BY_SLOT: Dict[str, List[Dict[str, Any]]] = {
    "surrender": [
        {
            "id": "surrender_basis",
            "label": "Change the surrender charge basis",
            "params": ["basis", "percent", "amount", "gradingYears"],
            "bankSwitches": [
                "surrender.basis.percent_account_value",
                "surrender.basis.percent_face",
                "surrender.basis.fixed",
                "surrender.schedule.graded",
            ],
        },
        {
            "id": "surrender_banded",
            "label": "Set a banded (piecewise) surrender schedule",
            "params": ["bands"],
            "bankSwitches": ["surrender.schedule.banded"],
        },
    ],
    "coi": [
        {
            "id": "coi_timing",
            "label": "Change when the COI charge is deducted",
            "params": ["timing"],
            "bankSwitches": [
                "coi.timing.beginning",
                "coi.timing.middle",
                "coi.timing.end",
            ],
        },
        {
            "id": "coi_banded",
            "label": "Set banded COI rates by policy duration",
            "params": ["bands"],
            "bankSwitches": ["coi.schedule.banded"],
        },
    ],
    "nar": [
        {
            "id": "nar_definition",
            "label": "Change the net amount at risk definition",
            "params": ["definition"],
            "bankSwitches": [
                "nar.definition.factor_adjusted",
                "nar.definition.unadjusted",
            ],
        },
    ],
}

_VARIANT_SLOT: Dict[str, str] = {
    variant["id"]: slot_id
    for slot_id, variants in VARIANTS_BY_SLOT.items()
    for variant in variants
}

_TIMING_PHRASES = {
    "beginning": "deducted at the beginning of each month, before interest is credited",
    "middle": (
        "deducted in the middle of each month — half before interest is credited "
        "and half after, with the net amount at risk re-measured at each step"
    ),
    "end": (
        "deducted at the end of each month, after interest is credited, with the "
        "net amount at risk measured on the post-interest value"
    ),
}


def variants_for_slot(slot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the structured correction variants a slot supports."""

    return list(VARIANTS_BY_SLOT.get(str(slot.get("id") or ""), []))


def _pct(value: float) -> str:
    pct = value * 100.0
    if abs(pct - round(pct)) < 1e-9:
        return f"{int(round(pct))}%"
    return f"{pct:.2f}".rstrip("0").rstrip(".") + "%"


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _source_phrase(provenance: Dict[str, Any]) -> str:
    """Short provenance phrase for a set of in-force rows."""

    source_type = str(provenance.get("sourceType") or "")
    filename = provenance.get("filename")
    page = provenance.get("page")
    where = ""
    if filename:
        where = f" in {filename}" + (f" (p. {page})" if page is not None else "")
    if source_type == "filed_pdf":
        status = provenance.get("reviewStatus")
        return f"as filed{where}" + (" (accepted)" if status == "accepted" else " (pending review)")
    if source_type == "ai_synthetic":
        return "from the synthetic schedule"
    if source_type == "workspace_edit":
        return "as set by a workspace edit"
    if source_type == CORRECTION_SOURCE_TYPE:
        return "per an earlier workspace correction"
    if filename:
        return f"from {filename}" + (f" (p. {page})" if page is not None else "")
    return "as currently in force"


def _describe_rows(mechanic: str, rows: List[Dict[str, Any]]) -> str:
    """Plain-language description of the rows currently in force."""

    if not rows:
        return ""
    first = rows[0]
    provenance = first.get("provenance") or {}
    phrase = _source_phrase(provenance)
    count = len(rows)
    span = f" over {count} year" + ("s" if count != 1 else "")
    if mechanic == "surrender":
        unit = str(first.get("charge_unit") or "")
        charge = float(first.get("charge") or 0.0)
        if unit == "per_1000_face":
            return f"{_money(charge)} per $1,000 of face amount in year 1{span}, {phrase}"
        if unit == "percent_account_value":
            return f"{_pct(charge)} of account value in year 1{span}, {phrase}"
        if unit == "percent_face":
            return f"{_pct(charge)} of face amount in year 1{span}, {phrase}"
        if unit == "fixed":
            return f"a flat {_money(charge)} in year 1{span}, {phrase}"
        return f"a schedule in force{span}, {phrase}"
    if mechanic == "nar_factors":
        return f"a NAR factor of {first.get('factor')}, {phrase}"
    return f"values in force{span}, {phrase}"


def describe_current(artifact: Dict[str, Any], slot: Dict[str, Any]) -> Dict[str, Any]:
    """Describe what is in force for a slot right now (the "was").

    Returns ``{"status", "description", "rows"}`` — the rows are the
    in-force usable rows the correction would replace (deep-copied), so
    the caller can preserve them verbatim in the correction record.
    """

    artifact = artifact or {}
    mechanic = str(slot.get("mechanic") or "")
    corrections = artifact.get("corrections") or {}
    status = _slot_status(artifact, mechanic) if mechanic else "missing"
    rows = list((artifact.get("usable") or {}).get(mechanic) or []) if mechanic else []

    if slot.get("id") == "coi":
        settings = executable_settings(artifact)
        timing = settings.get("coiTiming") or "beginning"
        return {
            "status": status,
            "description": f"COI {_TIMING_PHRASES[timing]}",
            "rows": deepcopy(rows),
        }
    if slot.get("id") == "nar":
        settings = executable_settings(artifact)
        definition = settings.get("narDefinition") or "factor_adjusted"
        factor = rows[0].get("factor") if rows else 1.0
        if definition == "unadjusted":
            description = "net amount at risk = death benefit − account value (no NAR factor applied)"
        elif rows:
            description = (
                f"net amount at risk = death benefit ÷ {factor} (the NAR factor in force) "
                "− account value"
            )
        else:
            description = (
                "net amount at risk = death benefit − account value "
                "(no NAR factor table in force; a factor of 1.0 is used)"
            )
        return {"status": status, "description": description, "rows": deepcopy(rows)}
    if not rows:
        if mechanic == "surrender":
            return {
                "status": status,
                "description": (
                    "no surrender schedule is in force; a placeholder declining "
                    "percentage of the ending account value is charged instead"
                ),
                "rows": [],
            }
        return {"status": status, "description": "nothing is in force", "rows": []}
    return {
        "status": status,
        "description": _describe_rows(mechanic, rows),
        "rows": deepcopy(rows),
    }


# ---------------------------------------------------------------------------
# Spec validation + materialisation
# ---------------------------------------------------------------------------


def _validate_spec(slot: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a correction spec; return its normalised params.

    ``spec`` is ``{"variant": <id>, "params": {...}}``.  Raises
    ValueError with an actuary-readable message on any defect; nothing
    is applied anywhere by this helper.
    """

    variant = str(spec.get("variant") or "")
    params = dict(spec.get("params") or {})
    slot_id = str(slot.get("id") or "")
    if _VARIANT_SLOT.get(variant) != slot_id:
        raise ValueError(
            f"Correction variant {variant!r} does not apply to the {slot.get('label')} slot"
        )
    if variant == "surrender_basis":
        basis = str(params.get("basis") or "")
        if basis not in SURRENDER_BASES:
            raise ValueError(
                "Surrender basis must be one of: percentage of account value, "
                "percentage of face amount, or a flat amount"
            )
        grading = params.get("gradingYears")
        try:
            grading_years = int(grading)
        except (TypeError, ValueError) as exc:
            raise ValueError("Grading years must be a whole number of years") from exc
        if grading_years < 1 or grading_years > 40:
            raise ValueError("Grading years must be between 1 and 40")
        normalised: Dict[str, Any] = {"basis": basis, "gradingYears": grading_years}
        if basis in ("percent_account_value", "percent_face"):
            try:
                percent = float(params.get("percent"))
            except (TypeError, ValueError) as exc:
                raise ValueError("A percentage is required for a percentage surrender basis") from exc
            if not math.isfinite(percent) or percent <= 0 or percent > 1:
                raise ValueError("The surrender percentage must be greater than 0 and at most 100%")
            normalised["percent"] = percent
        else:
            try:
                amount = float(params.get("amount"))
            except (TypeError, ValueError) as exc:
                raise ValueError("A dollar amount is required for a flat surrender basis") from exc
            if not math.isfinite(amount) or amount <= 0:
                raise ValueError("The flat surrender amount must be greater than 0")
            normalised["amount"] = amount
        return normalised
    if variant == "coi_timing":
        timing = str(params.get("timing") or "")
        if timing not in COI_TIMINGS:
            raise ValueError("COI timing must be beginning, middle, or end of the period")
        return {"timing": timing}
    if variant == "nar_definition":
        definition = str(params.get("definition") or "")
        if definition not in NAR_DEFINITIONS:
            raise ValueError(
                "NAR definition must be factor_adjusted (death benefit / NAR factor "
                "- account value) or unadjusted (death benefit - account value)"
            )
        return {"definition": definition}
    if variant in ("surrender_banded", "coi_banded"):
        # Band shapes are validated by the rule bank (contiguous from
        # year 1, no gaps or overlaps, banked units, sane ranges).
        mechanic = "surrender" if variant == "surrender_banded" else "coi"
        bands = rule_bank.validate_bands(mechanic, params.get("bands"))
        return {"bands": bands}
    raise ValueError(f"Unknown correction variant: {variant!r}")


def _graded_surrender_rows(
    params: Dict[str, Any],
    *,
    who: str,
    at: str,
    correction_id: str,
    text: Optional[str],
    confirm_back: str,
) -> List[Dict[str, Any]]:
    """Materialise a surrender-basis correction into validated rows.

    The schedule starts at the corrected value in year 1 and grades
    linearly to zero at the end of the grading period — the shape Eddy
    described ("8% of account value, grading to 0 over 10 years").
    Phase 4: the row construction is the rule bank's graded-schedule
    materializer (surrender.schedule.graded); this function validates
    the rows with the same validators ingestion uses and stamps the
    correction provenance so the ledger can label them.
    """

    canonical = _validate_canonical_rows(
        "surrender", rule_bank.materialize_graded_surrender(params)
    )
    provenance = {
        "sourceType": CORRECTION_SOURCE_TYPE,
        "filename": "Workspace correction",
        "correctionId": correction_id,
        "correctedBy": who,
        "correctedAt": at,
        "correctionText": text,
        "confirmBack": confirm_back,
    }
    return [{**row, "provenance": dict(provenance)} for row in canonical]


def _banded_rows(
    mechanic: str,
    params: Dict[str, Any],
    *,
    who: str,
    at: str,
    correction_id: str,
    text: Optional[str],
    confirm_back: str,
) -> List[Dict[str, Any]]:
    """Materialise a banded-schedule correction into validated rows.

    The bank's banded materializer (surrender.schedule.banded /
    coi.schedule.banded) builds one row per duration, each tagged
    with its band; the tag moves into the row provenance — the
    projection loop's source summary carries it from there, so the
    ledger derivation can name the band applied for a period.
    """

    materialised = rule_bank.materialize_banded_rows(mechanic, params["bands"])
    bands = [row.pop("_band", None) for row in materialised]
    canonical = _validate_canonical_rows(mechanic, materialised)
    provenance = {
        "sourceType": CORRECTION_SOURCE_TYPE,
        "filename": "Workspace correction",
        "correctionId": correction_id,
        "correctedBy": who,
        "correctedAt": at,
        "correctionText": text,
        "confirmBack": confirm_back,
    }
    return [
        {**row, "provenance": {**provenance, "band": band}}
        for row, band in zip(canonical, bands)
    ]


def _confirm_back(
    slot: Dict[str, Any],
    variant: str,
    params: Dict[str, Any],
    was: Dict[str, Any],
    artifact: Dict[str, Any],
) -> str:
    """Restate a correction in actuarial language for confirmation."""

    was_text = was["description"]
    if variant == "surrender_basis":
        grading = int(params["gradingYears"])
        grade = f"grading to 0 over {grading} year" + ("s" if grading != 1 else "")
        if params["basis"] == "percent_account_value":
            now = f"{_pct(float(params['percent']))} of account value, {grade}"
        elif params["basis"] == "percent_face":
            now = f"{_pct(float(params['percent']))} of face amount, {grade}"
        else:
            now = f"a flat {_money(float(params['amount']))} in year 1, {grade}"
        return f"Surrender charge: was {was_text}; now {now}."
    if variant == "coi_timing":
        return (
            f"COI charge timing: was {_TIMING_PHRASES[_current_timing(artifact)]}; "
            f"now {_TIMING_PHRASES[params['timing']]}."
        )
    if variant == "nar_definition":
        if params["definition"] == "unadjusted":
            now = "death benefit − account value (the NAR factor is not applied)"
        else:
            rows = list((artifact.get("usable") or {}).get("nar_factors") or [])
            factor = rows[0].get("factor") if rows else 1.0
            now = f"death benefit ÷ {factor} (the NAR factor in force) − account value"
        return f"Net amount at risk for COI: was {was_text}; now {now}."
    if variant in ("surrender_banded", "coi_banded"):
        bands_text = "; ".join(
            _band_phrase(index, band) for index, band in enumerate(params["bands"], start=1)
        )
        if variant == "surrender_banded":
            return f"Surrender charge: was {was_text}; now a banded schedule — {bands_text}."
        return f"COI rates: was {was_text}; now banded by policy duration — {bands_text}."
    raise ValueError(f"Unknown correction variant: {variant!r}")


def _short_band_value(unit: str, value: float) -> str:
    if unit in ("percent_account_value", "percent_face", "percent_nar_annual"):
        return _pct(value)
    if unit in ("per_1000_face", "fixed"):
        return _money(value)
    return f"{value:g}"


def _band_phrase(index: int, band: Dict[str, Any]) -> str:
    """One band restated in actuarial language for the confirm-back."""

    unit = str(band.get("unit") or "")
    value = float(band.get("value") or 0.0)
    span = band.get("label") or f"years {band.get('fromYear')}–{band.get('toYear') or '+'}"
    if value == 0:
        amount = "no charge"
    elif unit == "percent_account_value":
        amount = f"{_pct(value)} of account value"
    elif unit == "percent_face":
        amount = f"{_pct(value)} of face amount"
    elif unit == "per_1000_face":
        amount = f"{_money(value)} per $1,000 of face amount"
    elif unit == "fixed":
        amount = f"a flat {_money(value)}"
    elif unit == "per_1000_monthly":
        amount = f"{value:g} per $1,000 of net amount at risk, monthly"
    elif unit == "per_1000_annual":
        amount = f"{value:g} per $1,000 of net amount at risk, annually"
    elif unit == "percent_nar_annual":
        amount = f"{_pct(value)} of net amount at risk, annually"
    else:
        amount = f"{value:g} ({unit})"
    grade_to = band.get("gradeTo")
    if grade_to is not None and float(grade_to) != value:
        amount += f", grading linearly to {_short_band_value(unit, float(grade_to))}"
    return f"band {index} ({span}): {amount}"


def _current_timing(artifact: Dict[str, Any]) -> str:
    return str(executable_settings(artifact or {}).get("coiTiming") or "beginning")


# ---------------------------------------------------------------------------
# Preview + apply
# ---------------------------------------------------------------------------


def _build_correction(
    artifact: Dict[str, Any],
    slot: Dict[str, Any],
    spec: Dict[str, Any],
    *,
    who: str,
    at: str,
    correction_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the full correction record for a spec (pure; no writes)."""

    params = _validate_spec(slot, spec)
    variant = str(spec.get("variant"))
    text = str(spec.get("text") or "").strip() or None
    was = describe_current(artifact, slot)
    confirm_back = _confirm_back(slot, variant, params, was, artifact)
    record: Dict[str, Any] = {
        "id": correction_id or f"cor-{uuid.uuid4().hex[:12]}",
        "slot": slot["id"],
        "mechanic": slot.get("mechanic"),
        "variant": variant,
        "params": params,
        "text": text,
        "who": who,
        "at": at,
        "confirmBack": confirm_back,
        "replaces": {
            "status": was["status"],
            "description": was["description"],
            "rows": was["rows"],
            "wasCorrection": (artifact.get("corrections") or {}).get(
                str(slot.get("mechanic") or "")
            ),
        },
    }
    if variant == "surrender_basis":
        record["rows"] = _graded_surrender_rows(
            params,
            who=who,
            at=at,
            correction_id=record["id"],
            text=text,
            confirm_back=confirm_back,
        )
    if variant in ("surrender_banded", "coi_banded"):
        record["rows"] = _banded_rows(
            str(slot.get("mechanic") or ""),
            params,
            who=who,
            at=at,
            correction_id=record["id"],
            text=text,
            confirm_back=confirm_back,
        )
    return record


def preview_correction(
    artifact: Dict[str, Any],
    slot: Dict[str, Any],
    spec: Dict[str, Any],
    *,
    who: str,
    at: str,
) -> Dict[str, Any]:
    """Build the confirm-back preview for a correction (nothing persists)."""

    record = _build_correction(artifact or {}, slot, spec, who=who, at=at)
    return {
        "mapped": True,
        "confirmBack": record["confirmBack"],
        "replaces": {
            "status": record["replaces"]["status"],
            "description": record["replaces"]["description"],
        },
        "correction": record,
    }


def correction_citation(record: Dict[str, Any]) -> Dict[str, Any]:
    """The compact citation the ledger carries for a correction."""

    return {
        "id": record.get("id"),
        "who": record.get("who"),
        "at": record.get("at"),
        "text": record.get("text"),
        "confirmBack": record.get("confirmBack"),
    }


def apply_correction(
    artifact: Dict[str, Any],
    slot: Dict[str, Any],
    spec: Dict[str, Any],
    *,
    workspace_id: Optional[str],
    who: str,
    at: str,
) -> Dict[str, Any]:
    """Apply a validated, user-confirmed correction to a copy of the artifact.

    Returns ``{"artifact": ..., "correction": ..., "change": ...}``.
    Table-shaped corrections replace the mechanic's ``usable`` rows;
    setting-shaped corrections are recorded and reach the projection
    through :func:`executable_settings`.  The document-derived state
    (``mechanics`` / ``candidates`` / ``reviews``) is left untouched, and
    the replaced in-force rows are preserved inside the record.
    """

    result = deepcopy(artifact or {})
    record = _build_correction(result, slot, spec, who=who, at=at)
    mechanic = str(slot["mechanic"])

    prior_correction = (result.get("corrections") or {}).get(mechanic)
    result.setdefault("corrections", {})[mechanic] = record
    if record.get("rows") is not None:
        # Table-shaped corrections (surrender_basis, the banded
        # schedules) replace the mechanic's usable rows outright.
        result.setdefault("usable", {})[mechanic] = deepcopy(record["rows"])
    result.setdefault("status", {})[mechanic] = "corrected"

    summary = record["confirmBack"]
    if prior_correction:
        summary += f" This supersedes the earlier correction by {prior_correction.get('who')} at {prior_correction.get('at')}."
    if record["replaces"]["status"] in {"filed_accepted", "filed_pending_review"}:
        summary += " The filed value it replaces is preserved in this record."
    change = _change_record(
        workspace_id=workspace_id,
        slot=slot,
        kind="correction",
        who=who,
        at=at,
        summary=summary,
        prior={
            **_summarize_rows(record["replaces"]["rows"]),
            "status": record["replaces"]["status"],
            "description": record["replaces"]["description"],
        },
        new={
            "status": "corrected",
            "variant": record["variant"],
            "params": record["params"],
            "correctionId": record["id"],
        },
    )
    change["correctionId"] = record["id"]
    change["correctionText"] = record["text"]
    return {"artifact": result, "correction": record, "change": change}


def executable_settings(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Projection-loop settings implied by the active corrections.

    Rides inside the executable-mechanics dict under ``_settings`` so
    every projection consumer (analysis, GET-time rebuild, diagnostic)
    applies the same corrected arithmetic.
    """

    corrections = (artifact or {}).get("corrections") or {}
    settings: Dict[str, Any] = {}
    coi = corrections.get("coi") or {}
    if coi.get("variant") == "coi_timing":
        settings["coiTiming"] = (coi.get("params") or {}).get("timing")
        settings["coiTimingCorrection"] = correction_citation(coi)
    nar = corrections.get("nar_factors") or {}
    if nar.get("variant") == "nar_definition":
        settings["narDefinition"] = (nar.get("params") or {}).get("definition")
        settings["narDefinitionCorrection"] = correction_citation(nar)
    return settings


def executable_mechanics_view(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """The executable-mechanics dict for a projection request.

    The artifact's ``usable`` tables plus the correction settings, so
    the projection loop charges exactly what the panel shows in force.
    """

    usable = deepcopy((artifact or {}).get("usable") or {})
    settings = executable_settings(artifact or {})
    if settings:
        usable["_settings"] = settings
    return usable


def reapply_corrections(
    fresh_artifact: Dict[str, Any], prior_corrections: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Re-apply persisted corrections onto a freshly extracted artifact.

    Corrections are durable statements of how the calculation should
    work; a re-run rebuilds the artifact from documents, so without
    this step a re-run would silently discard them.  They are applied
    after workspace edits (corrections outrank edits), and their
    materialised rows are regenerated deterministically from the stored
    parameters with the original correction's provenance.
    """

    if not prior_corrections:
        return fresh_artifact
    fresh_artifact["corrections"] = deepcopy(prior_corrections)
    usable = fresh_artifact.setdefault("usable", {})
    status = fresh_artifact.setdefault("status", {})
    for mechanic, record in prior_corrections.items():
        if not isinstance(record, dict):
            continue
        if record.get("variant") == "surrender_basis":
            rows = _graded_surrender_rows(
                dict(record.get("params") or {}),
                who=str(record.get("who") or "workspace_user"),
                at=str(record.get("at") or ""),
                correction_id=str(record.get("id") or ""),
                text=record.get("text"),
                confirm_back=str(record.get("confirmBack") or ""),
            )
            usable[mechanic] = rows
            record["rows"] = deepcopy(rows)
        elif record.get("variant") in ("surrender_banded", "coi_banded"):
            rows = _banded_rows(
                mechanic,
                dict(record.get("params") or {}),
                who=str(record.get("who") or "workspace_user"),
                at=str(record.get("at") or ""),
                correction_id=str(record.get("id") or ""),
                text=record.get("text"),
                confirm_back=str(record.get("confirmBack") or ""),
            )
            usable[mechanic] = rows
            record["rows"] = deepcopy(rows)
        status[mechanic] = "corrected"
    return fresh_artifact


# ---------------------------------------------------------------------------
# Free-text mapping suggestions (authoring time only)
# ---------------------------------------------------------------------------


def suggest_variant(slot: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
    """Suggest a structured variant for free text, or return None.

    Deliberately conservative keyword matching, used only at authoring
    time: the suggestion is shown to the user, who confirms or rejects
    it.  Nothing is ever applied from a suggestion alone, and text with
    no clear mapping returns None so the caller can capture it as a
    product note instead of guessing.
    """

    lowered = f" {(text or '').lower()} "
    slot_id = str(slot.get("id") or "")
    if slot_id == "surrender":
        percent_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", lowered)
        percent = float(percent_match.group(1)) / 100.0 if percent_match else None
        grading_match = re.search(r"(\d+)\s*(?:years|yrs)", lowered)
        grading = int(grading_match.group(1)) if grading_match else None
        if "account value" in lowered and percent is not None:
            return {
                "variant": "surrender_basis",
                "params": {
                    "basis": "percent_account_value",
                    "percent": percent,
                    "gradingYears": grading or 10,
                },
            }
        if ("of face" in lowered or "face amount" in lowered) and percent is not None:
            return {
                "variant": "surrender_basis",
                "params": {
                    "basis": "percent_face",
                    "percent": percent,
                    "gradingYears": grading or 10,
                },
            }
        amount_match = re.search(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)", lowered)
        if "flat" in lowered and amount_match:
            return {
                "variant": "surrender_basis",
                "params": {
                    "basis": "flat_amount",
                    "amount": float(amount_match.group(1).replace(",", "")),
                    "gradingYears": grading or 10,
                },
            }
        return None
    if slot_id == "coi":
        if "end of" in lowered or "after interest" in lowered:
            return {"variant": "coi_timing", "params": {"timing": "end"}}
        if "beginning of" in lowered or "before interest" in lowered or "start of" in lowered:
            return {"variant": "coi_timing", "params": {"timing": "beginning"}}
        if "middle of" in lowered or "mid-month" in lowered or "mid month" in lowered:
            return {"variant": "coi_timing", "params": {"timing": "middle"}}
        return None
    if slot_id == "nar":
        if "no factor" in lowered or "without the factor" in lowered or "ignore the factor" in lowered:
            return {"variant": "nar_definition", "params": {"definition": "unadjusted"}}
        if "with the factor" in lowered or "divide by the factor" in lowered or "÷" in lowered:
            return {"variant": "nar_definition", "params": {"definition": "factor_adjusted"}}
        return None
    return None


def build_note_change(
    *,
    workspace_id: Optional[str],
    slot: Dict[str, Any],
    who: str,
    at: str,
    text: str,
    feature_request_id: Any,
) -> Dict[str, Any]:
    """Change-log record for an unmapped correction captured as a note.

    The projection is deliberately unchanged by a note; the record makes
    the capture itself auditable in the same history as applied edits
    and corrections.
    """

    change = _change_record(
        workspace_id=workspace_id,
        slot=slot,
        kind="correction_note",
        who=who,
        at=at,
        summary=(
            f"Correction note recorded for {slot['label']}: “{text}” — it does not "
            "match a known correction type, so it was captured as a product "
            "feature request and the projection is unchanged."
        ),
        prior={},
        new={"featureRequestId": feature_request_id},
    )
    change["correctionText"] = text
    return change


def correction_view(record: Dict[str, Any]) -> Dict[str, Any]:
    """The API/panel view of one active correction."""

    replaces = record.get("replaces") or {}
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
    }


__all__ = [
    "CORRECTION_REQUEST_CAPABILITY_ID",
    "CORRECTION_SOURCE_TYPE",
    "COI_TIMINGS",
    "NAR_DEFINITIONS",
    "SURRENDER_BASES",
    "VARIANTS_BY_SLOT",
    "variants_for_slot",
    "describe_current",
    "preview_correction",
    "apply_correction",
    "build_note_change",
    "correction_citation",
    "correction_view",
    "executable_settings",
    "executable_mechanics_view",
    "reapply_corrections",
    "suggest_variant",
]
