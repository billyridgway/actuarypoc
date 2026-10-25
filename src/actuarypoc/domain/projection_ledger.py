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

The ledger is a pure transform over the rows produced by the UL projection
loop.  The loop records an ``appliedMechanics`` block on each row describing
exactly which table row / placeholder it applied; derivations here are built
from that record so the explanation can never drift from the arithmetic.

Bases are labelled honestly: ``filed`` (reviewed filed table), ``synthetic``
(reviewed AI-generated stand-in table), ``workspace_table`` (validated
workspace table without filed/synthetic provenance), ``placeholder`` (no
table in force — the fallback formula is stated, never hidden),
``scenario`` (user/diagnostic input) and ``calculated`` (arithmetic on the
other components).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


LEDGER_VERSION = 1

_SOURCE_KIND_LABELS = {
    "filed": "Filed table",
    "synthetic": "Synthetic table",
    "workspace_table": "Workspace table",
    "corrected": "Corrected",
    "placeholder": "Placeholder",
    "scenario": "Scenario input",
    "calculated": "Calculated",
}


def _kind_from_source(source: Optional[Dict[str, Any]]) -> str:
    source_type = str((source or {}).get("sourceType") or "")
    if source_type == "filed_pdf":
        return "filed"
    if source_type == "ai_synthetic":
        return "synthetic"
    if source_type == "correction":
        return "corrected"
    if source:
        return "workspace_table"
    return "workspace_table"


def _source_view(source: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not source:
        return None
    view = {
        "filename": source.get("filename"),
        "page": source.get("page"),
        "tableHeading": source.get("tableHeading"),
        "valueBasis": source.get("valueBasis"),
        "sourceType": source.get("sourceType"),
    }
    # Phase 3: a corrected line cites its correction (who / when / the
    # user's own words) so the override is auditable from the ledger.
    for key in ("correctedBy", "correctedAt", "correctionText", "confirmBack"):
        if source.get(key) is not None:
            view[key] = source.get(key)
    # Phase 4: a row from a banded schedule names its band.
    if source.get("band") is not None:
        view["band"] = source.get("band")
    return view


def _band_sentence(band: Optional[Dict[str, Any]]) -> str:
    """The derivation sentence naming a banded schedule's band."""

    if not band:
        return ""
    label = band.get("label") or f"years {band.get('fromYear')}–{band.get('toYear')}"
    return (
        f" This year's row comes from band {band.get('index')} of the banded "
        f"schedule in force ({label})."
    )


def _band_input(band: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not band:
        return None
    label = band.get("label") or f"years {band.get('fromYear')}–{band.get('toYear')}"
    return _input("Schedule band", f"band {band.get('index')} ({label})")


def _correction_inputs(citation: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ledger inputs citing a correction record (who / when / words)."""

    if not citation:
        return []
    inputs: List[Dict[str, Any]] = []
    if citation.get("confirmBack"):
        inputs.append(_input("Correction applied", citation.get("confirmBack")))
    elif citation.get("text"):
        inputs.append(_input("Correction applied", citation.get("text")))
    if citation.get("who"):
        inputs.append(_input("Corrected by", citation.get("who")))
    if citation.get("at"):
        inputs.append(_input("Correction recorded", citation.get("at")))
    return inputs


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
    source: Optional[Dict[str, Any]] = None,
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
    source_view = _source_view(source)
    if source_view is not None:
        out["source"] = source_view
    return out


_COI_FORMULAS = {
    "per_1000_monthly": (
        "Each month: COI charge = (COI net amount at risk / 1,000) x monthly rate per $1,000. "
        "COI net amount at risk = death benefit / NAR factor - account value at the start of the month. "
        "The year's charge is the sum of the 12 monthly charges."
    ),
    "per_1000_annual": (
        "Each month: COI charge = (COI net amount at risk / 1,000) x (annual rate per $1,000 / 12). "
        "COI net amount at risk = death benefit / NAR factor - account value at the start of the month. "
        "The year's charge is the sum of the 12 monthly charges."
    ),
    "percent_nar_annual": (
        "Each month: COI charge = COI net amount at risk x (annual rate / 12). "
        "COI net amount at risk = death benefit / NAR factor - account value at the start of the month. "
        "The year's charge is the sum of the 12 monthly charges."
    ),
}


_COI_TIMING_SENTENCES = {
    "beginning": (
        " The COI charge is deducted at the beginning of each month, before "
        "interest is credited."
    ),
    "middle": (
        " The COI charge is deducted in the middle of each month: half before "
        "interest is credited and half after, with the net amount at risk "
        "re-measured at each step."
    ),
    "end": (
        " The COI charge is deducted at the end of each month, after interest "
        "is credited, with the net amount at risk measured on the "
        "post-interest value."
    ),
}


def _coi_component(row: Dict[str, Any], applied: Dict[str, Any]) -> Dict[str, Any]:
    coi = applied.get("coi") or {}
    amount = float(row.get("coiCharge") or 0.0)
    timing = str(coi.get("timing") or "beginning")
    timing_sentence = _COI_TIMING_SENTENCES.get(timing, "")
    timing_correction = coi.get("timingCorrection") or None
    nar_correction = coi.get("narDefinitionCorrection") or None
    if coi.get("basis") == "table":
        unit = str(coi.get("rateUnit") or "")
        formula = _COI_FORMULAS.get(
            unit,
            "Each month: COI charge = table rate applied to the COI net amount at risk "
            "(death benefit / NAR factor - account value). The year's charge is the sum of "
            "the 12 monthly charges.",
        )
        formula += timing_sentence
        formula += _band_sentence(coi.get("band"))
        inputs = [
            _input("COI rate applied", coi.get("rate"), unit or None),
            _input("NAR factor", coi.get("narFactor")),
            _input("Monthly COI net amount at risk (lowest month)", coi.get("monthlyNarMin"), "USD"),
            _input("Monthly COI net amount at risk (highest month)", coi.get("monthlyNarMax"), "USD"),
            _input("Face amount", row.get("faceAmount"), "USD"),
        ]
        band_input = _band_input(coi.get("band"))
        if band_input is not None:
            inputs.append(band_input)
        if coi.get("narDefinition") == "unadjusted":
            formula += (
                " Per the NAR definition in force, the filed NAR factor"
                + (f" of {coi.get('narFactorFiled')}" if coi.get("narFactorFiled") is not None else "")
                + " is not applied: the COI net amount at risk is the death benefit "
                "minus the account value."
            )
            inputs.append(_input("Filed NAR factor (not applied)", coi.get("narFactorFiled")))
        inputs.extend(_correction_inputs(timing_correction))
        inputs.extend(_correction_inputs(nar_correction))
        basis = (
            "corrected"
            if (timing_correction or nar_correction)
            else _kind_from_source(coi.get("source"))
        )
        return _component(
            "coi", "Cost of insurance (COI)", amount, formula, inputs,
            basis, coi.get("source"),
        )
    formula = (
        "Placeholder - no COI table is in force for this scenario: each month, "
        "COI charge = face amount x flat annual placeholder rate / 12. A filed COI charge "
        "is the table rate multiplied by the net amount at risk; this placeholder is not, "
        "so it stays flat and does not move with the account value."
    )
    formula += timing_sentence
    inputs = [
        _input("Flat placeholder rate (annual, of face amount)", coi.get("flatRate"), "rate"),
        _input("Face amount", row.get("faceAmount"), "USD"),
    ]
    # A timing correction on a placeholder COI is cited, but the basis
    # stays "placeholder": the rate is still not a filed rate, and that
    # remains the line's dominant honesty signal.
    inputs.extend(_correction_inputs(timing_correction))
    return _component("coi", "Cost of insurance (COI)", amount, formula, inputs, "placeholder")


def _fee_components(row: Dict[str, Any], applied: Dict[str, Any]) -> List[Dict[str, Any]]:
    fees = [item for item in (applied.get("fees") or []) if isinstance(item, dict)]
    loads = [item for item in fees if item.get("flowsTo") == "premium_load"]
    charges = [item for item in fees if item.get("flowsTo") != "premium_load"]

    components: List[Dict[str, Any]] = []
    load_amount = float(row.get("premiumLoad") or 0.0)
    if loads:
        inputs = [
            _input(
                f"{item.get('component') or 'Premium expense'} rate",
                item.get("rate"),
                "rate",
            )
            for item in loads
        ]
        inputs.append(_input("Annual premium", row.get("annualPremium"), "USD"))
        first = loads[0]
        components.append(_component(
            "premium_load",
            "Premium expense charge",
            load_amount,
            "Premium expense charge = premium paid x the premium expense rate, deducted from "
            "each premium payment before it is added to the account value.",
            inputs,
            _kind_from_source(first.get("source")) if first.get("basis") == "table" else "placeholder",
            first.get("source"),
        ))
    else:
        components.append(_component(
            "premium_load",
            "Premium expense charge",
            load_amount,
            "No premium expense charge was deducted this year (no premium expense rate is in force).",
            [_input("Annual premium", row.get("annualPremium"), "USD")],
            "calculated",
        ))

    fee_amount = float(row.get("policyFee") or 0.0)
    table_charges = [item for item in charges if item.get("basis") == "table"]
    if table_charges:
        inputs = [
            _input(
                str(item.get("component") or "Policy fee").replace("_", " "),
                item.get("amount"),
                "USD",
            )
            for item in table_charges
        ]
        first = table_charges[0]
        components.append(_component(
            "policy_fee",
            "Policy and admin fees",
            fee_amount,
            "Policy and admin fees are deducted monthly from the fee schedules in force; "
            "the year's total is the sum of the 12 monthly deductions itemised below.",
            inputs,
            _kind_from_source(first.get("source")),
            first.get("source"),
        ))
    elif charges:
        components.append(_component(
            "policy_fee",
            "Policy and admin fees",
            fee_amount,
            "No evidenced fee schedule is loaded; the configured annual policy/admin fee is "
            "spread evenly across the months of the year.",
            [_input("Configured annual policy/admin fee", charges[0].get("amount"), "USD")],
            "placeholder",
        ))
    else:
        components.append(_component(
            "policy_fee",
            "Policy and admin fees",
            fee_amount,
            "No policy or admin fees were deducted this year (no fee schedule is in force).",
            [],
            "placeholder",
        ))
    return components


def _surrender_component(row: Dict[str, Any], applied: Dict[str, Any]) -> Dict[str, Any]:
    component = _surrender_component_inner(row, applied)
    # Phase 4: when the year's row came from a banded schedule, the
    # derivation names the band that produced it.
    band = (applied.get("surrender") or {}).get("band")
    band_input = _band_input(band)
    if band_input is not None:
        component["formula"] = str(component.get("formula") or "") + _band_sentence(band)
        component["inputs"] = list(component.get("inputs") or []) + [band_input]
    return component


def _surrender_component_inner(row: Dict[str, Any], applied: Dict[str, Any]) -> Dict[str, Any]:
    surrender = applied.get("surrender") or {}
    amount = float(row.get("surrenderCharge") or 0.0)
    ending = float(row.get("endingPolicyValue") or row.get("policyValue") or 0.0)
    basis = str(surrender.get("basis") or "")
    unit = str(surrender.get("chargeUnit") or "")
    percent = surrender.get("percent")
    source = surrender.get("source") or {}
    if basis == "table" and _kind_from_source(source) == "corrected":
        # Phase 3: a corrected schedule states its own basis in its
        # derivation and cites the correction; what it replaced is
        # preserved in the correction record and the change history.
        citation = {
            "who": source.get("correctedBy"),
            "at": source.get("correctedAt"),
            "text": source.get("correctionText"),
            "confirmBack": source.get("confirmBack"),
        }
        override_note = (
            " This schedule is a workspace correction and overrides the schedule "
            "previously in force; the value it replaced is preserved in the "
            "correction record and the change history."
        )
        inputs = _correction_inputs(citation)
        if unit == "percent_account_value":
            return _component(
                "surrender_charge", "Surrender charge", amount,
                "Surrender charge = corrected schedule percentage x ending account value."
                + override_note,
                [
                    _input("Schedule percentage", percent, "rate"),
                    _input("Ending account value", ending, "USD"),
                ] + inputs,
                "corrected", source,
            )
        if unit == "percent_face":
            return _component(
                "surrender_charge", "Surrender charge", amount,
                "Surrender charge = corrected schedule percentage x face amount."
                + override_note,
                [
                    _input("Schedule percentage", percent, "rate"),
                    _input("Face amount", row.get("faceAmount"), "USD"),
                ] + inputs,
                "corrected", source,
            )
        if unit == "per_1000_face":
            return _component(
                "surrender_charge", "Surrender charge", amount,
                "Surrender charge = (face amount / 1,000) x corrected schedule charge "
                "per $1,000 of face amount." + override_note,
                [
                    _input("Schedule charge per $1,000 of face", surrender.get("perThousand"), "USD"),
                    _input("Face amount", row.get("faceAmount"), "USD"),
                ] + inputs,
                "corrected", source,
            )
        return _component(
            "surrender_charge", "Surrender charge", amount,
            "Surrender charge = the corrected fixed amount for this duration."
            + override_note,
            [_input("Corrected fixed charge", amount, "USD")] + inputs,
            "corrected", source,
        )
    if basis == "table" and unit == "percent_account_value":
        return _component(
            "surrender_charge", "Surrender charge", amount,
            "Surrender charge = schedule percentage x ending account value.",
            [
                _input("Schedule percentage", percent, "rate"),
                _input("Ending account value", ending, "USD"),
            ],
            _kind_from_source(surrender.get("source")), surrender.get("source"),
        )
    if basis == "table" and unit == "percent_face":
        return _component(
            "surrender_charge", "Surrender charge", amount,
            "Surrender charge = schedule percentage x face amount. The schedule in force "
            "states its charges on a face-amount basis; it is applied exactly as filed.",
            [
                _input("Schedule percentage", percent, "rate"),
                _input("Face amount", row.get("faceAmount"), "USD"),
            ],
            _kind_from_source(surrender.get("source")), surrender.get("source"),
        )
    if basis == "table" and unit == "per_1000_face":
        return _component(
            "surrender_charge", "Surrender charge", amount,
            "Surrender charge = (face amount / 1,000) x schedule charge per $1,000 of face "
            "amount, exactly as stated in the schedule in force.",
            [
                _input("Schedule charge per $1,000 of face", surrender.get("perThousand"), "USD"),
                _input("Face amount", row.get("faceAmount"), "USD"),
            ],
            _kind_from_source(surrender.get("source")), surrender.get("source"),
        )
    if basis == "table":
        return _component(
            "surrender_charge", "Surrender charge", amount,
            "Surrender charge = the fixed amount stated in the schedule in force for this duration.",
            [_input("Schedule fixed charge", amount, "USD")],
            _kind_from_source(surrender.get("source")), surrender.get("source"),
        )
    if basis == "expired":
        return _component(
            "surrender_charge", "Surrender charge", amount,
            "No surrender charge applies this year: the surrender charge period has ended.",
            [_input("Ending account value", ending, "USD")],
            _kind_from_source(surrender.get("source")) if surrender.get("tableLoaded") else "placeholder",
            surrender.get("source"),
        )
    # Placeholder fallback: a declining percentage of the ending account value.
    return _component(
        "surrender_charge", "Surrender charge", amount,
        "Placeholder - no surrender schedule is in force: surrender charge = placeholder "
        "percentage x ending account value. The placeholder percentage declines linearly "
        "over the surrender period and is not a filed schedule.",
        [
            _input("Placeholder percentage this year", percent, "rate"),
            _input("Ending account value", ending, "USD"),
        ],
        "placeholder",
    )


def build_projection_ledger(projection: Dict[str, Any]) -> Dict[str, Any]:
    """Transform projection rows into the auditable roll-forward ledger.

    Each ledger row carries the roll-forward amounts plus a ``components``
    list: one derivation record per component, each with a plain-language
    formula and the actual values the engine used that period (taken from
    the row's ``appliedMechanics`` record).
    """

    rows: List[Dict[str, Any]] = []
    for row in (projection or {}).get("rows") or []:
        applied = row.get("appliedMechanics") or {}
        crediting = applied.get("crediting") or {}
        nar = applied.get("nar") or {}
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
        components.append(_component(
            "interest", "Interest credited", float(row.get("guaranteedInterest") or 0.0),
            "Interest is credited monthly at the guaranteed rate (monthly rate = "
            "(1 + guaranteed annual rate)^(1/12) - 1) on the account value after premiums, "
            "premium loads, COI and fees. The year's interest is the sum of the 12 monthly credits.",
            [_input("Guaranteed annual credited rate", crediting.get("guaranteedRate"), "rate")],
            "calculated",
        ))
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
        components.append(_component(
            "death_benefit", "Death benefit", float(row.get("deathBenefit") or 0.0),
            "Death benefit = the greater of the face amount and the minimum death benefit "
            "(corridor) percentage x ending account value.",
            [
                _input("Face amount", row.get("faceAmount"), "USD"),
                _input("Minimum death benefit percentage", nar.get("corridorPercentage"), "rate"),
                _input("Ending account value", ending, "USD"),
            ],
            _kind_from_source(None) if nar.get("corridorBasis") == "table" else "calculated",
        ))
        components.append(_component(
            "net_amount_at_risk", "Net amount at risk", float(row.get("netAmountAtRisk") or 0.0),
            "Net amount at risk = death benefit - ending account value, floored at zero.",
            [
                _input("Death benefit", float(row.get("deathBenefit") or 0.0), "USD"),
                _input("Ending account value", ending, "USD"),
            ],
            "calculated",
        ))

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
            "deathBenefit": float(row.get("deathBenefit") or 0.0),
            "netAmountAtRisk": float(row.get("netAmountAtRisk") or 0.0),
            "cumulativePremium": float(row.get("cumulativePremium") or 0.0),
            "components": components,
        })

    return {
        "ledgerVersion": LEDGER_VERSION,
        "granularity": "annual",
        "rows": rows,
    }


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
        return "placeholder"
    kinds = {_kind_from_source(row.get("provenance")) for row in rows}
    for kind in ("corrected", "filed", "synthetic", "workspace_table"):
        if kind in kinds:
            return kind
    return "workspace_table"


def build_rate_tables_in_force(
    executable_mechanics: Optional[Dict[str, Any]],
    *,
    coi_rate_flat: float,
    max_surrender_pct: float,
    surrender_period_years: int,
) -> Dict[str, Any]:
    """Return the full rate tables the projection charges from.

    Eddy asked for "the full rates that they're using" beside the
    projection: the complete COI table and surrender schedule in force —
    or, when no table is in force, a plain statement of the placeholder
    that is being used instead.
    """

    executable = executable_mechanics or {}
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
        "placeholder": None,
    }
    if not coi_rows:
        coi_view["placeholder"] = {
            "flatRate": coi_rate_flat,
            "description": (
                f"No COI table is in force. A flat placeholder rate of {coi_rate_flat:.2%} of the "
                "face amount per year is charged instead; it is not a rate x net amount at risk."
            ),
        }

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
        "placeholder": None,
    }
    if not surrender_rows:
        surrender_view["placeholder"] = {
            "description": (
                f"No surrender schedule is in force. A placeholder percentage of the ending "
                f"account value is charged instead: {max_surrender_pct:.0%} in policy year 1, "
                f"declining linearly to 0% after year {surrender_period_years}."
            ),
        }

    return {"coi": coi_view, "surrender": surrender_view}


__all__ = ["LEDGER_VERSION", "build_projection_ledger", "build_rate_tables_in_force"]
