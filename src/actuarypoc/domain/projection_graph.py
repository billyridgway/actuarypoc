"""Compile product projection metadata into a stable directed graph contract.

The graph is deliberately produced by the backend.  The UI must not infer
dependencies from labels because labels are presentation text, while mechanic
IDs are versioned execution contracts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from actuarypoc.domain import rule_bank as _rule_bank


GRAPH_VERSION = 1


@dataclass(frozen=True)
class MechanicDefinition:
    mechanic_id: str
    input_ids: Sequence[str] = field(default_factory=tuple)
    rule_ids: Sequence[str] = field(default_factory=tuple)
    capability_requirement_id: Optional[str] = None


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    mechanic_id: str
    dependencies: Sequence[str] = field(default_factory=tuple)


UL_MECHANICS: Sequence[MechanicDefinition] = (
    MechanicDefinition("scenario", ("issue_age", "sex", "risk_class", "tobacco_status", "face_amount")),
    MechanicDefinition("projection_controls", ("scenario_basis", "projection_horizon", "premium_timing", "charge_timing")),
    MechanicDefinition("premium", ("premium", "premium_mode"), ("premium_added",)),
    MechanicDefinition("coi", ("coi_rate",), ("coi_charge_deducted",), "coi_table"),
    MechanicDefinition("policy_fee", ("policy_fee",), ("policy_admin_fee_deducted",), "policy_admin_fees"),
    MechanicDefinition("crediting", ("guaranteed_rate",), ("interest_credited",)),
    MechanicDefinition("account_value", (), ("opening_policy_value", "closing_policy_value")),
    MechanicDefinition("surrender", ("surrender_schedule",), ("surrender_charge", "surrender_value"), "surrender_schedule"),
    MechanicDefinition("death_benefit", ("death_benefit_option",), ("death_benefit", "net_amount_at_risk")),
)


UL_RULES: Sequence[RuleDefinition] = (
    RuleDefinition("opening_policy_value", "account_value", ("input:projection_horizon",)),
    RuleDefinition("premium_added", "premium", ("input:premium", "input:premium_mode", "input:premium_timing")),
    RuleDefinition(
        "coi_charge_deducted",
        "coi",
        (
            "input:face_amount", "input:coi_rate", "input:issue_age", "input:sex",
            "input:risk_class", "input:tobacco_status", "input:charge_timing", "input:scenario_basis",
        ),
    ),
    RuleDefinition(
        "policy_admin_fee_deducted",
        "policy_fee",
        ("input:policy_fee", "input:charge_timing", "input:scenario_basis"),
    ),
    RuleDefinition(
        "interest_credited",
        "crediting",
        (
            "rule:opening_policy_value", "input:guaranteed_rate", "input:premium",
            "input:premium_timing", "input:charge_timing", "input:scenario_basis",
        ),
    ),
    RuleDefinition(
        "closing_policy_value",
        "account_value",
        (
            "rule:opening_policy_value", "rule:premium_added", "rule:coi_charge_deducted",
            "rule:policy_admin_fee_deducted", "rule:interest_credited",
        ),
    ),
    RuleDefinition(
        "surrender_charge",
        "surrender",
        ("input:face_amount", "input:surrender_schedule", "input:scenario_basis"),
    ),
    RuleDefinition("surrender_value", "surrender", ("rule:closing_policy_value", "rule:surrender_charge")),
    RuleDefinition("death_benefit", "death_benefit", ("input:face_amount", "input:death_benefit_option")),
    RuleDefinition("net_amount_at_risk", "death_benefit", ("rule:death_benefit", "rule:closing_policy_value")),
)


CONDITIONAL_SELECTOR_IDS = {"issue_age", "sex", "risk_class", "tobacco_status"}
EXECUTION_SETTING_IDS = {"projection_horizon", "premium_timing", "charge_timing"}
SCENARIO_CONTEXT_IDS = {"scenario_basis"}


def _contribution(input_id: str) -> tuple[str, str]:
    if input_id in CONDITIONAL_SELECTOR_IDS:
        return (
            "conditional_selector",
            "Selects an evidenced schedule row when the loaded table supports this dimension; may not change a placeholder-rate projection.",
        )
    if input_id in EXECUTION_SETTING_IDS:
        return "execution_setting", "Controls projection duration or the sequence in which transactions are applied."
    if input_id in SCENARIO_CONTEXT_IDS:
        return "scenario_context", "Describes the scenario basis and qualifies the result; it is not a numeric formula input."
    return "calculation_input", "Its value is consumed directly by one or more projection calculations."


def _edge_kind(dependency_id: str) -> str:
    input_id = dependency_id.removeprefix("input:")
    if input_id in CONDITIONAL_SELECTOR_IDS:
        return "conditional_lookup"
    if input_id in EXECUTION_SETTING_IDS:
        return "execution_control"
    if input_id in SCENARIO_CONTEXT_IDS:
        return "scenario_context"
    return "value_dependency"


def _fallback_disclosure(input_id: str, status: Any) -> Optional[Dict[str, str]]:
    if _status(status) != "provisional":
        return None
    if input_id == "coi_rate":
        if str(status or "").lower() == "synthetic_assumption":
            return {
                "mode": "synthetic_active",
                "missingEvidence": "Filed COI rate table",
                "fallback": "Reviewed AI-generated synthetic COI table",
                "impact": "Demographic selectors are active, but results remain scenario-only and must not be treated as filed values.",
            }
        return {
            "mode": "flat_fallback",
            "missingEvidence": "Filed COI rate table",
            "fallback": "Flat placeholder COI rate",
            "impact": "Age, sex, risk class, and tobacco selectors cannot change COI rates until an evidenced table is loaded.",
        }
    if input_id == "surrender_schedule":
        if str(status or "").lower() == "synthetic_assumption":
            return {
                "mode": "synthetic_active",
                "missingEvidence": "Filed surrender charge schedule",
                "fallback": "Reviewed AI-generated synthetic surrender schedule",
                "impact": "Duration-specific synthetic charges are active, but results remain scenario-only and are not filed values.",
            }
        return {
            "mode": "simplified_fallback",
            "missingEvidence": "Filed surrender charge schedule",
            "fallback": "Simplified declining surrender pattern",
            "impact": "Projected surrender values may differ from filed duration-specific values.",
        }
    return None


def _fmt_pct(value: Any) -> Optional[str]:
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return None


def _fmt_money(value: Any) -> Optional[str]:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return None


def _switch_description(switch_id: str) -> str:
    return _rule_bank.get_switch(switch_id).description


def _table_kind(raw: Mapping[str, Any], context: Mapping[str, Any], mechanic: str) -> Optional[str]:
    """The provenance kind of the mechanic table in force, when known.

    Sources, in order: the snapshot's rate-tables view (which classifies
    rows by provenance), the run's applied-mechanics source record, and
    the input's own status (synthetic stand-ins are marked on the node).
    """

    rate_tables = context.get("rateTables") or {}
    view = rate_tables.get(mechanic) or {}
    if view.get("status"):
        return str(view["status"])
    applied = (context.get("appliedMechanics") or {}).get(mechanic) or {}
    source = applied.get("source") or {}
    source_type = str(source.get("sourceType") or "")
    if source_type == "filed_pdf":
        return "filed"
    if source_type in {"ai_synthetic", "deterministic_fallback"}:
        return "synthetic"
    if source_type == "correction":
        return "corrected"
    if source_type:
        return "workspace_table"
    if str(raw.get("status") or "").lower() == "synthetic_assumption":
        return "synthetic"
    return None


_TABLE_KIND_PREFIX = {
    "filed": "From the filed schedule in force: ",
    "corrected": "From the corrected schedule in force: ",
    "synthetic": "From the synthetic schedule in force (a reviewed scenario stand-in, not filed values): ",
    "workspace_table": "From the workspace schedule in force: ",
}


def _coi_equation(raw: Mapping[str, Any], context: Mapping[str, Any]) -> Optional[str]:
    ledger = (context.get("ledgerFormulas") or {}).get("coi")
    if ledger:
        return str(ledger)
    applied = (context.get("appliedMechanics") or {}).get("coi") or {}
    status = str(raw.get("status") or "").lower()
    if applied.get("basis") == "table" or (not applied and status in {"evidenced", "synthetic_assumption"}):
        unit = str(applied.get("rateUnit") or "") or _table_unit(context, "coi", "rate_unit")
        if unit in _rule_bank.COI_RATE_SWITCH_BY_UNIT:
            equation = _switch_description(_rule_bank.COI_RATE_SWITCH_BY_UNIT[unit])
        else:
            equation = (
                "COI charge = COI table rate x COI net amount at risk, applied "
                "monthly from the table in force."
            )
        definition = str(applied.get("narDefinition") or "")
        if definition in _rule_bank.NAR_DEFINITION_SWITCHES:
            nar_text = _switch_description(_rule_bank.NAR_DEFINITION_SWITCHES[definition])
            equation += " " + nar_text.split(". ")[0] + "."
        timing = str(applied.get("timing") or "")
        if timing == "middle":
            equation += " The COI charge is deducted in the middle of each month: half before interest is credited and half after."
        elif timing == "end":
            equation += " The COI charge is deducted at the end of each month, after interest is credited."
        elif timing:
            equation += " The COI charge is deducted at the beginning of each month, before interest is credited."
        kind = _table_kind(raw, context, "coi")
        return (_TABLE_KIND_PREFIX.get(kind or "", "") + equation) if kind else equation
    # Placeholder / missing: the banked placeholder switch is what runs.
    rate = applied.get("flatRate")
    if rate is None:
        rate = raw.get("value")
    pct = _fmt_pct(rate)
    rate_clause = f" of {pct}" if pct else ""
    return (
        "Placeholder - no COI table is in force: COI charge each month = face amount "
        f"x flat annual placeholder rate{rate_clause} / 12. A filed COI charge is the "
        "table rate x the net amount at risk; this placeholder is not, so it stays "
        "flat and does not move with the account value."
    )


def _table_unit(context: Mapping[str, Any], mechanic: str, field: str) -> str:
    rows = ((context.get("rateTables") or {}).get(mechanic) or {}).get("rows") or []
    units = {str(row.get(field)) for row in rows if row.get(field)}
    return units.pop() if len(units) == 1 else ""


def _surrender_equation(raw: Mapping[str, Any], fallback: Optional[Dict[str, str]], context: Mapping[str, Any]) -> Optional[str]:
    ledger = (context.get("ledgerFormulas") or {}).get("surrender_charge")
    if ledger:
        return str(ledger)
    applied = (context.get("appliedMechanics") or {}).get("surrender") or {}
    status = str(raw.get("status") or "").lower()
    table_in_force = applied.get("basis") == "table" or (
        not applied and status in {"evidenced", "synthetic_assumption"}
    )
    if table_in_force:
        unit = str(applied.get("chargeUnit") or "") or _table_unit(context, "surrender", "charge_unit")
        kind = _table_kind(raw, context, "surrender")
        if unit in _rule_bank.SURRENDER_SWITCH_BY_UNIT:
            equation = _switch_description(_rule_bank.SURRENDER_SWITCH_BY_UNIT[unit])
            return (_TABLE_KIND_PREFIX.get(kind or "", "") + equation) if kind else equation
        if kind == "synthetic":
            return (
                "Surrender charge = the synthetic schedule in force's charge for "
                "the duration, applied on the basis the schedule states "
                "(scenario-only; not filed values)."
            )
        return (
            "Surrender charge = the schedule in force's charge for the duration, "
            "applied on the basis the schedule states."
        )
    if applied.get("basis") == "expired":
        return "No surrender charge applies: the surrender charge period has ended."
    if applied.get("basis") == "placeholder" and applied.get("percent") is not None:
        pct = _fmt_pct(applied.get("percent")) or "the placeholder percentage"
        return (
            f"Surrender charge = placeholder percentage x ending account value; the "
            f"year-1 placeholder percentage is {pct} and declines linearly to zero "
            "over the surrender period. Placeholder - no surrender schedule is in force."
        )
    # Definition-only fallback (legacy snapshots carry no run record): the
    # node's stated value parameterises the simplified declining pattern.
    value_text = str(raw.get("value") or "")
    match = re.search(r"(\d+(?:\.\d+)?%)\s+of\s+(face|account value)\b.*?(\d+)\s*years", value_text)
    if match:
        pct, base_word, years = match.group(1), match.group(2), match.group(3)
        base = "face amount" if base_word == "face" else "ending account value"
        return (
            f"Surrender charge = {pct} of {base} in year 1, declining linearly to "
            f"zero over {years} years: in year t, surrender charge = {base} x {pct} "
            f"x ({years} - t + 1) / {years}. Simplified fallback - no filed "
            "surrender schedule is in force."
        )
    return "No filed surrender schedule is in force. " + _switch_description(
        "surrender.placeholder.linear_account_value"
    )


def _fee_equation(raw: Mapping[str, Any], context: Mapping[str, Any]) -> Optional[str]:
    applied_fees = (context.get("appliedMechanics") or {}).get("fees") or []
    table_fees = [item for item in applied_fees if item.get("basis") == "table"]
    if table_fees:
        units: List[str] = []
        for item in table_fees:
            unit = str(item.get("feeUnit") or "")
            if unit in _rule_bank.FEE_SWITCH_BY_UNIT and unit not in units:
                units.append(unit)
        if units:
            descriptions = " ".join(
                _switch_description(_rule_bank.FEE_SWITCH_BY_UNIT[unit]) for unit in units
            )
            return "From the fee schedule in force: " + descriptions
    fallback_fees = [item for item in applied_fees if item.get("basis") == "fallback"]
    status = str(raw.get("status") or "").lower()
    if fallback_fees or status in {"missing", "not_available", "scenario_assumption"}:
        amount = fallback_fees[0].get("amount") if fallback_fees else raw.get("value")
        money = _fmt_money(amount)
        if status == "scenario_assumption" and not fallback_fees:
            return (
                f"Policy/admin fee = the user-entered annual fee of {money or 'the stated amount'}, "
                "spread evenly over the year (annual fee / 12 each month). Scenario "
                "assumption - no evidenced fee schedule is in force."
            )
        monthly = _fmt_money(float(amount) / 12.0) if isinstance(amount, (int, float)) else None
        equation = (
            "No fee schedule is in force, so no filed fee equation applies. The "
            "projection instead uses the fallback: monthly fee = configured annual "
            "policy/admin fee / 12"
        )
        if money is not None:
            equation += f", with the configured annual fee at {money}"
        if monthly is not None:
            equation += f" ({monthly} per month)"
        equation += "."
        if isinstance(amount, (int, float)) and float(amount) == 0.0:
            equation += " At that amount, no fee is deducted."
        return equation
    ledger = (context.get("ledgerFormulas") or {}).get("policy_fee")
    if ledger:
        return str(ledger)
    return (
        "Policy/admin fees are deducted monthly from the fee schedule in force, "
        "each row applied on the basis it states (a stated monthly amount, an "
        "annual amount per $1,000 of face, or a percentage of premium for a "
        "premium expense charge)."
    )


def _applied_equation(
    input_id: str,
    raw: Mapping[str, Any],
    fallback: Optional[Dict[str, str]],
    context: Mapping[str, Any],
) -> Optional[str]:
    """The equation the engine applies to one input, for the graph panel.

    Eddy's rule (Aug 7, 2026): the formula sits beside every component.
    Rule nodes already carry their step formulas; this gives each
    calculation input the equation in force for its own state — the
    ledger's own derivation when the snapshot carries the run's ledger,
    otherwise the banked switch description for the state in force, and
    for fallbacks the fallback's own equation, stated as a fallback.
    Selector and setting inputs have no applied equation (they choose
    values; they are not calculated from), so they return None.
    """

    if input_id == "coi_rate":
        return _coi_equation(raw, context)
    if input_id == "surrender_schedule":
        return _surrender_equation(raw, fallback, context)
    if input_id == "policy_fee":
        return _fee_equation(raw, context)
    if input_id == "guaranteed_rate":
        equation = _switch_description("crediting.guaranteed_annual")
        pct = _fmt_pct(raw.get("value"))
        if pct:
            equation += f" Guaranteed annual rate in force: {pct}."
        return equation
    if input_id == "premium":
        if str(raw.get("status") or "").lower() == "derived_placeholder":
            match = re.search(r"(\d+(?:\.\d+)?%)\s+of\s+face", str(raw.get("source") or ""))
            if match:
                return (
                    f"Annual premium = {match.group(1)} x face amount (the default "
                    "applied because no scenario premium was supplied)."
                )
        return "Annual premium = modal premium x payments per year under the selected premium mode."
    if input_id == "death_benefit_option":
        return (
            "Death benefit = the greater of the face amount and the corridor "
            "minimum death benefit (corridor percentage x ending account value); "
            "under the option in force the base death benefit is the face amount."
        )
    return None


def _status(value: Any) -> str:
    raw = str(value or "").lower()
    if raw in {"missing", "not_available"}:
        return "missing"
    if raw in {"placeholder", "derived_placeholder", "default", "diagnostic", "not_supplied", "scenario_assumption", "synthetic_assumption"}:
        return "provisional"
    return "ready"


def _capabilities_by_requirement(capabilities: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        str(item.get("sourceRequirementId")): dict(item)
        for item in capabilities
        if item.get("sourceRequirementId")
    }


def compile_projection_graph(
    *,
    product_code: str,
    product_type: str,
    inputs: Sequence[Mapping[str, Any]],
    steps: Sequence[Mapping[str, Any]],
    capabilities: Sequence[Mapping[str, Any]] = (),
    input_configs: Optional[Mapping[str, Mapping[str, Any]]] = None,
    context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compile projection inputs and executed steps into the graph API shape."""

    normalized_product_type = product_type.upper().replace("_", " ").replace("-", " ")
    is_ul = normalized_product_type == "UL" or "UNIVERSAL LIFE" in normalized_product_type
    mechanic_definitions = UL_MECHANICS if is_ul else ()
    rule_definitions = UL_RULES if is_ul else ()
    mechanics = {definition.mechanic_id: definition for definition in mechanic_definitions}
    input_mechanic = {
        input_id: definition.mechanic_id
        for definition in mechanic_definitions
        for input_id in definition.input_ids
    }
    rule_registry = {definition.rule_id: definition for definition in rule_definitions}
    capability_by_requirement = _capabilities_by_requirement(capabilities)
    capability_by_mechanic = {
        definition.mechanic_id: capability_by_requirement.get(definition.capability_requirement_id or "")
        for definition in mechanic_definitions
    }
    configs = input_configs or {}
    equation_context = context or {}

    nodes: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    for index, raw in enumerate(inputs):
        input_id = str(raw.get("id") or f"input-{index}")
        mechanic_id = input_mechanic.get(input_id, "unmodeled")
        contribution_type, contribution_detail = _contribution(input_id)
        fallback = _fallback_disclosure(input_id, raw.get("status"))
        equation = (
            _applied_equation(input_id, raw, fallback, equation_context)
            if mechanic_id != "unmodeled"
            else None
        )
        if mechanic_id == "unmodeled":
            diagnostics.append({
                "code": "unregistered_input",
                "nodeId": f"input:{input_id}",
                "message": f"Projection input {input_id!r} is not registered to a product mechanic.",
            })
        nodes.append({
            "id": f"input:{input_id}",
            "mechanicId": mechanic_id,
            "inputId": input_id,
            "kind": "input" if mechanic_id != "unmodeled" else "unmodeled",
            "label": raw.get("label") or input_id,
            "status": "missing" if mechanic_id == "unmodeled" else _status(raw.get("status")),
            "detail": "Unmodeled product mechanic" if mechanic_id == "unmodeled" else (
                "Missing evidenced table; fallback active" if fallback else raw.get("status")
            ),
            "value": raw.get("value"),
            "unit": raw.get("unit"),
            "source": raw.get("source"),
            "equation": equation,
            "contributionType": contribution_type,
            "contributionDetail": contribution_detail,
            "fallbackDisclosure": fallback,
            "editable": input_id in configs,
            "inputConfig": dict(configs[input_id]) if input_id in configs else None,
            "capability": capability_by_mechanic.get(mechanic_id),
        })

    known_node_ids = {node["id"] for node in nodes}
    rule_nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    for index, raw in enumerate(sorted(steps, key=lambda item: int(item.get("order") or 0))):
        rule_id = str(raw.get("id") or f"step-{index}")
        definition = rule_registry.get(rule_id)
        mechanic_id = definition.mechanic_id if definition else "unmodeled"
        node_id = f"rule:{rule_id}"
        dependencies = list(definition.dependencies) if definition else []
        if definition is None:
            diagnostics.append({
                "code": "unmodeled_mechanic",
                "nodeId": node_id,
                "message": f"Rule {rule_id!r} was discovered but has no registered execution contract.",
            })
        dependency_nodes = [node for node in nodes + rule_nodes if node["id"] in dependencies]
        has_missing = any(node["status"] == "missing" for node in dependency_nodes)
        has_provisional = any(node["status"] == "provisional" for node in dependency_nodes)
        rule_status = "missing" if definition is None else "provisional" if has_missing or has_provisional else "ready"
        rule_nodes.append({
            "id": node_id,
            "mechanicId": mechanic_id,
            "kind": "rule" if definition else "unmodeled",
            "label": raw.get("title") or (raw.get("result") or {}).get("label") or rule_id,
            "status": rule_status,
            "detail": "Unmodeled product mechanic" if definition is None else "Uses a fallback because required data is missing" if has_missing else "Uses a placeholder or default" if has_provisional else "Ready",
            "value": (raw.get("result") or {}).get("value"),
            "unit": (raw.get("result") or {}).get("unit"),
            "source": (raw.get("result") or {}).get("source"),
            "formula": raw.get("formulaText"),
            "capability": capability_by_mechanic.get(mechanic_id),
        })
        for dependency in dependencies:
            edge_kind = _edge_kind(dependency)
            inactive_lookup = (
                edge_kind == "conditional_lookup"
                and rule_id == "coi_charge_deducted"
                and any(
                    node["id"] == "input:coi_rate"
                    and (node.get("fallbackDisclosure") or {}).get("mode") == "flat_fallback"
                    for node in nodes
                )
            )
            edges.append({
                "id": f"{dependency}->{node_id}",
                "source": dependency,
                "target": node_id,
                "kind": edge_kind,
                "status": "inactive_fallback" if inactive_lookup else "active" if dependency in known_node_ids else "unresolved",
                "detail": "Inactive while the projection uses a flat COI fallback" if inactive_lookup else None,
            })
        known_node_ids.add(node_id)

    unmodeled = [node["id"] for node in nodes + rule_nodes if node["kind"] == "unmodeled"]
    return {
        "graphVersion": GRAPH_VERSION,
        "productCode": product_code,
        "productType": product_type,
        "nodes": nodes + rule_nodes,
        "edges": edges,
        "unmodeledMechanics": unmodeled,
        "diagnostics": diagnostics,
        "registry": {
            "mechanics": sorted(mechanics),
            "rules": sorted(rule_registry),
        },
    }


__all__ = ["GRAPH_VERSION", "MechanicDefinition", "RuleDefinition", "compile_projection_graph"]
