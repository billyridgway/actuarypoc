"""Auditable roll-forward ledger for UL projections (Phase 1: show the math).

Eddy, the actuary reviewing ActuaryAI (Aug 7, 2026), asked for three things
this module provides:

1. The projection presented as an account-value roll-forward ledger —
   beginning value, premium, each charge itemised, interest, ending value,
   surrender charge, surrender value — "just like a bank account".
2. The formula beside every component, with the actual values used that
   period (this rate, this net amount at risk, this base), so any line can
   be audited without reading code.
3. The full rate tables in force displayed with the projection, not only
   available as a CSV download.

Phase 7 (the Equation Doctrine): the ledger is a pure transform over the
rows produced by the UL projection loop.  Each row's ``appliedMechanics``
record cites the APPROVED EQUATION that ran for every mechanic — its
canonical rendering, its source page, its approver — and derivations here
are built from those citations, so the formula printed is the equation
that ran and the explanation can never drift from the arithmetic.  A
mechanic with no approved equation (or one that could not be evaluated)
gets a component that states the absence plainly; there are no placeholder
derivations because there is no placeholder math.

Bases are labelled honestly: ``filed`` (document-derived approved
equation), ``corrected`` (an equation born of a workspace correction),
``equation`` (an approved equation of another provenance — actuary-
authored, specimen, or pre-doctrine state), ``synthetic``/``workspace_table``
(table provenance in the rate-tables view), ``missing`` (not calculated —
no approved equation), ``scenario`` (user/diagnostic input) and
``calculated`` (the universal roll-forward identities).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from actuarypoc.domain.equations import (
    BASIS_BY_SOURCE_KIND,
    render_math_tree,
    timing_sentence,
)


LEDGER_VERSION = 2

_SOURCE_KIND_LABELS = {
    "filed": "Filed",
    "synthetic": "Synthetic table",
    "workspace_table": "Workspace table",
    "corrected": "Corrected",
    "equation": "Approved equation",
    "missing": "Not calculated — no approved equation",
    "placeholder": "Placeholder",
    "scenario": "Scenario input",
    "calculated": "Calculated",
}

_RESOLUTION = (
    "To resolve: harvest the filing's stated calculation, approve a "
    "harvested equation, or enter the equation for this mechanic."
)


def _kind_from_source(source: Optional[Dict[str, Any]]) -> str:
    source_type = str((source or {}).get("sourceType") or "")
    if source_type == "filed_pdf":
        return "filed"
    if source_type in {"ai_synthetic", "deterministic_fallback"}:
        return "synthetic"
    if source_type == "correction":
        return "corrected"
    if source:
        return "workspace_table"
    return "workspace_table"


def _input(label: str, value: Any, unit: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"label": label, "value": value}
    if unit is not None:
        out["unit"] = unit
    return out


def _component(
    component_id: str,
    label: str,
    amount: Optional[float],
    formula: str,
    inputs: Sequence[Dict[str, Any]],
    basis: str,
    equation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": component_id,
        "label": label,
        "amount": amount,
        "formula": formula,
        "inputs": list(inputs),
        "basis": basis,
        "basisLabel": _SOURCE_KIND_LABELS.get(basis, basis),
    }
    if equation is not None:
        out["equation"] = equation
        kind = str(equation.get("sourceKind") or "")
        out["source"] = {
            "sourceType": {
                "document": "filed_pdf",
                "correction": "correction",
            }.get(kind, kind or None),
            "filename": equation.get("sourceFilename"),
            "page": equation.get("sourcePage"),
            "approvedBy": equation.get("approvedBy"),
            "approvedAt": equation.get("approvedAt"),
        }
    return out


def _basis_for(citation: Optional[Dict[str, Any]]) -> str:
    if not citation:
        return "equation"
    basis = BASIS_BY_SOURCE_KIND.get(str(citation.get("sourceKind") or ""), "equation")
    if basis == "equation":
        # An equation transcribed from a table keeps the table's truth:
        # synthetic-backed numbers are labelled synthetic, filed-backed
        # numbers filed — never upgraded by the transcription.
        table_kind = str(citation.get("tableSourceType") or "")
        if table_kind in {"ai_synthetic", "deterministic_fallback"}:
            return "synthetic"
        if table_kind == "filed_pdf":
            return "filed"
        if table_kind == "correction":
            return "corrected"
        if table_kind == "workspace_edit":
            return "workspace_table"
    return basis


def _correction_inputs(citation: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ledger inputs citing the correction an equation was born from."""

    correction = (citation or {}).get("correction") or {}
    if not correction:
        return []
    inputs: List[Dict[str, Any]] = []
    if correction.get("confirmBack"):
        inputs.append(_input("Correction applied", correction.get("confirmBack")))
    elif correction.get("text"):
        inputs.append(_input("Correction applied", correction.get("text")))
    if correction.get("who"):
        inputs.append(_input("Corrected by", correction.get("who")))
    if correction.get("at"):
        inputs.append(_input("Correction recorded", correction.get("at")))
    return inputs


def _equation_inputs(citation: Dict[str, Any]) -> List[Dict[str, Any]]:
    inputs: List[Dict[str, Any]] = []
    if citation.get("sourceFilename"):
        where = f"Source: {citation['sourceFilename']}"
        if citation.get("sourcePage"):
            where += f", p. {citation['sourcePage']}"
        inputs.append(_input("Equation source", where))
    if citation.get("approvedBy"):
        inputs.append(_input("Approved by", citation.get("approvedBy")))
    if citation.get("approvedAt"):
        inputs.append(_input("Approved at", citation.get("approvedAt")))
    return inputs


#: The equation-mechanic label used in "no approved … equation" absence
#: statements, keyed by ledger component id.
_EQUATION_LABELS = {
    "coi": "COI charge",
    "premium_load": "premium load",
    "policy_fee": "policy fees",
    "interest": "crediting",
    "surrender_charge": "surrender charge",
    "death_benefit": "death benefit",
    "net_amount_at_risk": "net amount at risk",
}


def _mechanic_component(
    component_id: str,
    label: str,
    amount: Optional[float],
    status: Optional[Dict[str, Any]],
    inputs: Sequence[Dict[str, Any]] = (),
    *,
    applied_note: Optional[str] = None,
) -> Dict[str, Any]:
    """One mechanic's ledger component, from its equation citation.

    In force -> the formula IS the approved equation's rendering.
    Missing -> the component states the absence and the resolution.
    Failed -> the equation is cited and the failure is stated; the
    mechanic contributed nothing.
    """

    status = status or {}
    citation = status.get("equation")
    if status.get("missing") or citation is None:
        equation_label = _EQUATION_LABELS.get(component_id, label)
        return _component(
            component_id, label, amount,
            f"Not calculated — no approved {equation_label} equation is in "
            f"force for this workspace, so no {equation_label} is included "
            f"in this projection. " + _RESOLUTION,
            list(inputs),
            "missing",
        )
    formula = str(citation.get("rendering") or "")
    if applied_note:
        formula = f"{formula} {applied_note}" if formula else applied_note
    all_inputs = list(inputs) + _equation_inputs(citation) + _correction_inputs(citation)
    if status.get("failed"):
        formula += (
            f" This equation could not be evaluated this year "
            f"({status.get('failureReason')}), so the mechanic contributed "
            "nothing this year."
        )
    return _component(
        component_id, label, amount, formula, all_inputs,
        _basis_for(citation), citation,
    )


# ---------------------------------------------------------------------------
# Per-mechanic components
# ---------------------------------------------------------------------------


def _row_citation_text(entry: Dict[str, Any]) -> str:
    """One evaluator row citation as a plain-language ledger line."""

    table_label = {
        "coi": "COI table",
        "surrender": "surrender schedule",
        "fees": "fee schedule",
        "nar_factors": "NAR factor table",
        "corridor": "corridor table",
    }.get(str(entry.get("table") or ""), str(entry.get("table") or "table"))
    if entry.get("defaulted"):
        return (
            f"No {table_label} row applied — the equation's stated "
            "fallback was used."
        )
    parts = [table_label]
    key_bits: List[str] = []
    if entry.get("duration") is not None:
        key_bits.append(f"duration {entry['duration']}")
    if entry.get("attainedAge") is not None:
        key_bits.append(f"attained age {entry['attainedAge']}")
    for label, field in (
        ("sex", "sex"), ("risk class", "riskClass"), ("tobacco", "tobaccoStatus"),
    ):
        if entry.get(field):
            key_bits.append(f"{label} {entry[field]}")
    if key_bits:
        parts.append("row at " + ", ".join(key_bits))
    if entry.get("value") is not None:
        value = f"{entry['field']} {entry['value']}"
        if entry.get("unit"):
            value += f" {entry['unit']}"
        parts.append(value)
    text = " — ".join(parts)
    if entry.get("sourceFilename"):
        origin = str(entry["sourceFilename"])
        if entry.get("sourcePage") is not None:
            origin += f", p. {entry['sourcePage']}"
        text += f" ({origin})"
    return text


def _coi_component(row: Dict[str, Any], applied: Dict[str, Any]) -> Dict[str, Any]:
    coi = applied.get("coi") or {}
    nar = applied.get("nar") or {}
    inputs: List[Dict[str, Any]] = []
    if coi.get("rate") is not None:
        inputs.append(_input("COI rate applied", coi.get("rate"), coi.get("rateUnit") or None))
    # The filed row the year's charges read, cited by the evaluator
    # at lookup time (``appliedMechanics.coi.tableRows``): the rate
    # above is auditable to a row of a named table in a named filing.
    table_rows = coi.get("tableRows") or []
    for entry in table_rows[:3]:
        inputs.append(_input("COI table row applied", _row_citation_text(entry)))
    if len(table_rows) > 3:
        inputs.append(_input(
            "COI table rows applied",
            f"{len(table_rows)} distinct rows across the year",
        ))
    if row.get("narFactor") is not None:
        inputs.append(_input("NAR factor", row.get("narFactor")))
    if nar.get("definition") == "unadjusted" and row.get("filedNarFactor") is not None:
        inputs.append(_input("Filed NAR factor (not applied)", row.get("filedNarFactor")))
    inputs.extend([
        _input("Monthly COI net amount at risk (lowest month)", coi.get("monthlyNarMin"), "USD"),
        _input("Monthly COI net amount at risk (highest month)", coi.get("monthlyNarMax"), "USD"),
        _input("Face amount", row.get("faceAmount"), "USD"),
    ])
    notes: List[str] = []
    if coi.get("equation"):
        notes.append("The year's charge is the sum of the 12 monthly charges.")
    if nar.get("definition") == "unadjusted":
        notes.append(
            "Per the approved net amount at risk equation, the filed NAR "
            "factor is not applied."
        )
    component = _mechanic_component(
        "coi", "Cost of insurance (COI)", float(row.get("coiCharge") or 0.0),
        coi, inputs,
        applied_note=" ".join(notes) if notes else None,
    )
    # The COI charge is computed from the net amount at risk: when the
    # NAR equation in force is a correction, the charge's derivation is
    # corrected too, and the ledger says so on the COI component.
    nar_citation = nar.get("equation") or {}
    if (
        nar_citation.get("sourceKind") == "correction"
        and component.get("basis") in {"filed", "equation"}
    ):
        component["basis"] = "corrected"
        component["basisLabel"] = _SOURCE_KIND_LABELS["corrected"]
        component["inputs"] = list(component.get("inputs") or []) + _correction_inputs(nar_citation)
    return component


def _fee_components(row: Dict[str, Any], applied: Dict[str, Any]) -> List[Dict[str, Any]]:
    load_inputs = [_input("Annual premium", row.get("annualPremium"), "USD")]
    fee_inputs = [_input("Ending account value", row.get("endingPolicyValue"), "USD")]
    return [
        _mechanic_component(
            "premium_load", "Premium expense charge",
            float(row.get("premiumLoad") or 0.0),
            applied.get("premiumLoad") or {}, load_inputs,
        ),
        _mechanic_component(
            "policy_fee", "Policy and admin fees",
            float(row.get("policyFee") or 0.0),
            applied.get("fees") or {}, fee_inputs,
            applied_note=(
                "The year's total is the sum of the 12 monthly deductions."
                if (applied.get("fees") or {}).get("equation") else None
            ),
        ),
    ]


def _surrender_component(row: Dict[str, Any], applied: Dict[str, Any]) -> Dict[str, Any]:
    surrender = applied.get("surrender") or {}
    amount = float(row.get("surrenderCharge") or 0.0)
    ending = float(row.get("endingPolicyValue") or row.get("policyValue") or 0.0)
    inputs = [
        _input("Ending account value", ending, "USD"),
        _input("Face amount", row.get("faceAmount"), "USD"),
    ]
    component = _mechanic_component(
        "surrender_charge", "Surrender charge", amount, surrender, inputs,
    )
    if (
        surrender.get("equation")
        and not surrender.get("failed")
        and not surrender.get("rowApplied", True)
        and amount == 0.0
    ):
        # The equation evaluated and no schedule row applies this year:
        # the charge period has ended, and the derivation says so
        # before it cites the equation that produced zero.
        component["formula"] = (
            "No surrender charge applies this year: the surrender charge "
            "period has ended. " + str(component.get("formula") or "")
        )
    return component


def _interest_component(row: Dict[str, Any], applied: Dict[str, Any]) -> Dict[str, Any]:
    crediting = applied.get("crediting") or {}
    return _mechanic_component(
        "interest", "Interest credited",
        float(row.get("guaranteedInterest") or 0.0),
        crediting,
        [_input("Guaranteed annual credited rate", crediting.get("guaranteedRate"), "rate")],
        applied_note=(
            "Credited monthly on the account value at each month's crediting "
            "point; the year's interest is the sum of the 12 monthly credits."
            if crediting.get("equation") else None
        ),
    )


def _death_benefit_component(row: Dict[str, Any], applied: Dict[str, Any]) -> Dict[str, Any]:
    nar = applied.get("nar") or {}
    status = {
        "equation": nar.get("deathBenefitEquation"),
        "missing": nar.get("deathBenefitEquation") is None,
        "failed": bool(nar.get("failed")),
        "failureReason": nar.get("failureReason"),
    }
    amount = row.get("deathBenefit")
    return _mechanic_component(
        "death_benefit", "Death benefit",
        float(amount) if isinstance(amount, (int, float)) else None,
        status,
        [
            _input("Face amount", row.get("faceAmount"), "USD"),
            _input("Ending account value", row.get("endingPolicyValue"), "USD"),
        ],
    )


def _nar_component(row: Dict[str, Any], applied: Dict[str, Any]) -> Dict[str, Any]:
    nar = applied.get("nar") or {}
    status = {
        "equation": nar.get("equation"),
        "missing": bool(nar.get("missing")),
        "failed": bool(nar.get("failed")),
        "failureReason": nar.get("failureReason"),
    }
    # The ledger's NAR is the approved equation's output — the
    # COI-measurement NAR — not the row's plain DB-minus-AV reporting
    # field.
    amount = row.get("coiNetAmountAtRisk")
    return _mechanic_component(
        "net_amount_at_risk", "Net amount at risk",
        float(amount) if isinstance(amount, (int, float)) else None,
        status,
        [
            _input("Death benefit", row.get("deathBenefit"), "USD"),
            _input("Ending account value", row.get("endingPolicyValue"), "USD"),
        ],
    )


def build_projection_ledger(projection: Dict[str, Any]) -> Dict[str, Any]:
    """Transform projection rows into the auditable roll-forward ledger.

    Each ledger row carries the roll-forward amounts plus a ``components``
    list: one derivation record per component.  Mechanic components cite
    the approved equation that ran (its rendering, source, approver);
    the skeleton components state the universal identities.
    """

    rows: List[Dict[str, Any]] = []
    for row in (projection or {}).get("rows") or []:
        applied = row.get("appliedMechanics") or {}
        beginning = float(row.get("openingPolicyValue") or 0.0)
        premium = float(row.get("annualPremium") or row.get("premium") or 0.0)
        ending = float(row.get("endingPolicyValue") or row.get("policyValue") or 0.0)

        components: List[Dict[str, Any]] = [
            _component(
                "opening_value", "Beginning account value", beginning,
                "Beginning account value is the prior year's ending account value (zero in policy year 1).",
                [], "calculated",
            ),
            _component(
                "premium", "Premium paid", premium,
                "Annual premium = modal premium x payments per year under the selected premium mode.",
                [
                    _input("Modal premium", row.get("modalPremium"), "USD"),
                    _input("Premium mode", row.get("premiumMode")),
                ],
                "scenario",
            ),
        ]
        components.extend(_fee_components(row, applied))
        components.append(_coi_component(row, applied))
        components.append(_interest_component(row, applied))
        components.append(_component(
            "ending_value", "Ending account value", ending,
            "Ending account value = beginning value + premium - premium expense charge "
            "- policy/admin fees - COI charge + interest credited.",
            [
                _input("Beginning account value", beginning, "USD"),
                _input("Premium paid", premium, "USD"),
                _input("Premium expense charge", float(row.get("premiumLoad") or 0.0), "USD"),
                _input("Policy and admin fees", float(row.get("policyFee") or 0.0), "USD"),
                _input("COI charge", float(row.get("coiCharge") or 0.0), "USD"),
                _input("Interest credited", float(row.get("guaranteedInterest") or 0.0), "USD"),
            ],
            "calculated",
        ))
        components.append(_surrender_component(row, applied))
        components.append(_component(
            "surrender_value", "Surrender value", float(row.get("surrenderValue") or 0.0),
            "Surrender value = ending account value - surrender charge, floored at zero.",
            [
                _input("Ending account value", ending, "USD"),
                _input("Surrender charge", float(row.get("surrenderCharge") or 0.0), "USD"),
            ],
            "calculated",
        ))
        components.append(_death_benefit_component(row, applied))
        components.append(_nar_component(row, applied))

        rows.append({
            "year": row.get("year"),
            "attainedAge": row.get("attainedAge"),
            "beginningValue": beginning,
            "premium": premium,
            "premiumLoad": float(row.get("premiumLoad") or 0.0),
            "policyFee": float(row.get("policyFee") or 0.0),
            "coiCharge": float(row.get("coiCharge") or 0.0),
            "interestCredited": float(row.get("guaranteedInterest") or 0.0),
            "endingValue": ending,
            "surrenderCharge": float(row.get("surrenderCharge") or 0.0),
            "surrenderValue": float(row.get("surrenderValue") or 0.0),
            "deathBenefit": (
                float(row["deathBenefit"])
                if isinstance(row.get("deathBenefit"), (int, float)) else None
            ),
            "netAmountAtRisk": (
                float(row["netAmountAtRisk"])
                if isinstance(row.get("netAmountAtRisk"), (int, float)) else None
            ),
            "cumulativePremium": float(row.get("cumulativePremium") or 0.0),
            "components": components,
        })

    return {
        "ledgerVersion": LEDGER_VERSION,
        "granularity": "annual",
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Rate tables in force
# ---------------------------------------------------------------------------


def _table_sources(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: List[Dict[str, Any]] = []
    for row in rows:
        provenance = row.get("provenance") or {}
        view = {
            "filename": provenance.get("filename"),
            "page": provenance.get("page"),
            "tableHeading": provenance.get("tableHeading"),
            "valueBasis": provenance.get("valueBasis"),
            "sourceType": provenance.get("sourceType"),
        }
        if any(view.values()) and view not in seen:
            seen.append(view)
    return seen


def _table_status(rows: Sequence[Dict[str, Any]]) -> str:
    if not rows:
        return "missing"
    kinds = {_kind_from_source(row.get("provenance")) for row in rows}
    for kind in ("corrected", "filed", "synthetic", "workspace_table"):
        if kind in kinds:
            return kind
    return "workspace_table"


def _citation_view(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not record:
        return None
    source = record.get("source") or {}
    body = record.get("body")
    return {
        "equationId": record.get("id"),
        "mechanic": record.get("mechanic"),
        "version": record.get("version"),
        "rendering": record.get("rendering"),
        # Typeset form of the same body (None -> prose alone) and the
        # timing statement as its own line, as in the record views.
        "math": (
            render_math_tree(body, str(record.get("mechanic") or "") or None)
            if body is not None else None
        ),
        "timingNote": timing_sentence(record.get("timing")),
        "timing": record.get("timing"),
        "sourceKind": source.get("kind"),
        "sourceFilename": source.get("filename"),
        "sourcePage": source.get("page"),
        "approvedBy": (record.get("approval") or {}).get("by"),
        "approvedAt": (record.get("approval") or {}).get("at"),
    }


def build_rate_tables_in_force(
    executable_mechanics: Optional[Dict[str, Any]],
    *,
    equations: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the full rate tables the projection charges from.

    Eddy asked for "the full rates that they're using" beside the
    projection: the complete COI table and surrender schedule in
    force, each beside the approved equation that applies it.  When no
    table is in force the view says so plainly — tables are data, and
    a missing table is a data absence (an equation that looks the
    table up will state the consequence), never a placeholder.
    """

    executable = executable_mechanics or {}
    equations = equations or {}
    coi_rows = list(executable.get("coi") or [])
    surrender_rows = list(executable.get("surrender") or [])

    coi_view: Dict[str, Any] = {
        "status": _table_status(coi_rows),
        "rowCount": len(coi_rows),
        "rows": [
            {
                "duration": row.get("duration"),
                "attained_age": row.get("attained_age"),
                "sex": row.get("sex"),
                "risk_class": row.get("risk_class"),
                "tobacco_status": row.get("tobacco_status"),
                "rate": row.get("rate"),
                "rate_unit": row.get("rate_unit"),
                "band": (row.get("provenance") or {}).get("band"),
            }
            for row in coi_rows
        ],
        "sources": _table_sources(coi_rows),
        "equation": _citation_view(equations.get("coi_charge")),
        "missingTable": None,
    }
    if not coi_rows:
        coi_view["missingTable"] = {
            "description": (
                "No COI rate table is in force for this workspace. COI charges "
                "are calculated only by an approved COI charge equation; an "
                "equation that reads a COI table cannot be evaluated until "
                "a table is in force."
            ),
        }
    coi_record = equations.get("coi_charge") or {}
    if (coi_record.get("source") or {}).get("kind") == "correction":
        coi_view["status"] = "corrected"

    surrender_view: Dict[str, Any] = {
        "status": _table_status(surrender_rows),
        "rowCount": len(surrender_rows),
        "rows": [
            {
                "duration": row.get("duration"),
                "charge": row.get("charge"),
                "charge_unit": row.get("charge_unit"),
                "band": (row.get("provenance") or {}).get("band"),
            }
            for row in surrender_rows
        ],
        "sources": _table_sources(surrender_rows),
        "equation": _citation_view(equations.get("surrender_charge")),
        "missingTable": None,
    }
    if not surrender_rows:
        surrender_view["missingTable"] = {
            "description": (
                "No surrender charge schedule is in force for this workspace. "
                "Surrender charges are calculated only by an approved "
                "surrender charge equation."
            ),
        }
    surrender_record = equations.get("surrender_charge") or {}
    if (surrender_record.get("source") or {}).get("kind") == "correction":
        surrender_view["status"] = "corrected"

    return {"coi": coi_view, "surrender": surrender_view}


__all__ = ["LEDGER_VERSION", "build_projection_ledger", "build_rate_tables_in_force"]
