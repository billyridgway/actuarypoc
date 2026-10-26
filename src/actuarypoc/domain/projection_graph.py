"""Compile product projection metadata into a stable directed graph contract.

The graph is deliberately produced by the backend.  The UI must not infer
dependencies from labels because labels are presentation text, while mechanic
IDs are versioned execution contracts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from actuarypoc.domain import equations as _eq


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
    """What the node discloses about its evidence state.

    Phase 7: there are no math fallbacks to disclose.  A synthetic table
    in force is disclosed as synthetic (its equation is a transcription
    of that table); a mechanic with no approved equation is disclosed
    as a missing equation — the mechanic does not calculate.
    """

    raw_status = str(status or "").lower()
    if input_id == "coi_rate":
        if raw_status == "synthetic_assumption":
            return {
                "mode": "synthetic_active",
                "missingEvidence": "Filed COI rate table",
                "fallback": "Reviewed AI-generated synthetic COI table",
                "impact": "Demographic selectors are active, but results remain scenario-only and must not be treated as filed values.",
            }
        if _status(status) in {"missing", "provisional"}:
            return {
                "mode": "missing_equation",
                "missingEvidence": "Approved COI charge equation",
                "impact": "No COI charge is calculated until an equation is harvested and approved, or entered. Age, sex, risk class, and tobacco selectors cannot change COI charges until then.",
            }
    if input_id == "surrender_schedule":
        if raw_status == "synthetic_assumption":
            return {
                "mode": "synthetic_active",
                "missingEvidence": "Filed surrender charge schedule",
                "fallback": "Reviewed AI-generated synthetic surrender schedule",
                "impact": "Duration-specific synthetic charges are active, but results remain scenario-only and are not filed values.",
            }
        if _status(status) in {"missing", "provisional"}:
            return {
                "mode": "missing_equation",
                "missingEvidence": "Approved surrender charge equation",
                "impact": "No surrender charge is calculated until an equation is harvested and approved, or entered.",
            }
    if input_id == "policy_fee" and _status(status) == "missing":
        return {
            "mode": "missing_equation",
            "missingEvidence": "Approved policy fees equation",
            "impact": "No policy or admin fees are calculated until an equation is harvested and approved, or entered.",
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


def _table_kind(raw: Mapping[str, Any], context: Mapping[str, Any], mechanic: str) -> Optional[str]:
    """The provenance kind of the mechanic table in force, when known.

    Sources, in order: the snapshot's rate-tables view (which classifies
    rows by provenance), the applied equation citation's table source
    type, and the input's own status (synthetic stand-ins are marked on
    the node).
    """

    rate_tables = context.get("rateTables") or {}
    view = rate_tables.get(mechanic) or {}
    if view.get("status"):
        return str(view["status"])
    applied_key = {"coi": "coi", "surrender": "surrender", "fees": "fees"}.get(mechanic, mechanic)
    applied = (context.get("appliedMechanics") or {}).get(applied_key) or {}
    citation = applied.get("equation") or {}
    source_type = str(citation.get("tableSourceType") or "")
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


def _applied_entry(context: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return (context.get("appliedMechanics") or {}).get(key) or {}


def _missing_equation_text(label: str) -> str:
    return (
        f"Not calculated — no approved {label} equation is in force, so no "
        f"{label} is calculated. Harvest the filing's stated calculation and "
        "approve it, or enter the equation, to calculate it."
    )


def _entry_equation(entry: Mapping[str, Any], label: str) -> Optional[str]:
    """The equation text for one applied-mechanics entry (new shape)."""

    if not entry:
        return None
    citation = entry.get("equation")
    if entry.get("missing"):
        return _missing_equation_text(label)
    if citation:
        rendering = str(citation.get("rendering") or "")
        if entry.get("failed"):
            return (
                f"{rendering} This equation could not be evaluated this year "
                f"({entry.get('failureReason') or 'evaluation failed'}), so the "
                "mechanic contributed nothing."
            )
        return rendering or None
    return None


def _table_unit(context: Mapping[str, Any], mechanic: str, field: str) -> str:
    rows = ((context.get("rateTables") or {}).get(mechanic) or {}).get("rows") or []
    units = {str(row.get(field)) for row in rows if row.get(field)}
    return units.pop() if len(units) == 1 else ""


def _coi_equation(raw: Mapping[str, Any], context: Mapping[str, Any]) -> Optional[str]:
    ledger = (context.get("ledgerFormulas") or {}).get("coi")
    if ledger:
        return str(ledger)
    from_entry = _entry_equation(_applied_entry(context, "coi"), "COI charge")
    if from_entry:
        kind = _table_kind(raw, context, "coi")
        prefix = _TABLE_KIND_PREFIX.get(kind or "", "")
        return prefix + from_entry if not from_entry.startswith("Not calculated") else from_entry
    # No run record (legacy snapshot): derive from the table in force —
    # the transcription of that table is the equation that would run.
    status = str(raw.get("status") or "").lower()
    if status in {"evidenced", "synthetic_assumption"}:
        unit = _table_unit(context, "coi", "rate_unit")
        if unit:
            equation = _eq.render_equation(_eq.coi_body_for_unit(unit), "coi_charge")
            kind = _table_kind(raw, context, "coi")
            return (_TABLE_KIND_PREFIX.get(kind or "", "") + equation) if kind else equation
    return _missing_equation_text("COI charge")


def _surrender_equation(raw: Mapping[str, Any], fallback: Optional[Dict[str, str]], context: Mapping[str, Any]) -> Optional[str]:
    ledger = (context.get("ledgerFormulas") or {}).get("surrender_charge")
    if ledger:
        return str(ledger)
    entry = _applied_entry(context, "surrender")
    from_entry = _entry_equation(entry, "surrender charge")
    if from_entry:
        if (
            entry.get("equation")
            and not entry.get("rowApplied")
            and not entry.get("failed")
        ):
            return (
                "No surrender charge applies this year: the surrender charge "
                f"period has ended. The approved equation is: {from_entry}"
            )
        kind = _table_kind(raw, context, "surrender")
        prefix = _TABLE_KIND_PREFIX.get(kind or "", "")
        return prefix + from_entry if not from_entry.startswith("Not calculated") else from_entry
    status = str(raw.get("status") or "").lower()
    if status in {"evidenced", "synthetic_assumption"}:
        unit = _table_unit(context, "surrender", "charge_unit")
        if unit:
            equation = _eq.render_equation(_eq.surrender_body_for_unit(unit), "surrender_charge")
            kind = _table_kind(raw, context, "surrender")
            return (_TABLE_KIND_PREFIX.get(kind or "", "") + equation) if kind else equation
    return _missing_equation_text("surrender charge")


def _fee_equation(raw: Mapping[str, Any], context: Mapping[str, Any]) -> Optional[str]:
    ledger = (context.get("ledgerFormulas") or {}).get("policy_fee")
    if ledger:
        return str(ledger)
    from_entry = _entry_equation(_applied_entry(context, "fees"), "policy fees")
    if from_entry:
        return from_entry
    status = str(raw.get("status") or "").lower()
    if status == "scenario_assumption":
        money = _fmt_money(raw.get("value"))
        return (
            f"The user-entered annual fee of {money or 'the stated amount'} is a "
            "scenario assumption and is not applied: fees are calculated only by "
            "an approved policy fees equation, and none is in force."
        )
    rows = ((context.get("rateTables") or {}).get("fees") or {}).get("rows") or []
    if rows:
        return _eq.render_equation(_eq.policy_fees_body(), "policy_fees")
    return _missing_equation_text("policy fees")


def _applied_equation(
    input_id: str,
    raw: Mapping[str, Any],
    fallback: Optional[Dict[str, str]],
    context: Mapping[str, Any],
) -> Optional[str]:
    """The equation the engine applies to one input, for the graph panel.

    Eddy's rule (Aug 7, 2026): the formula sits beside every component.
    Phase 7: the formula shown is the approved equation that ran — the
    ledger's own derivation when the snapshot carries the run's ledger,
    otherwise the applied equation's canonical rendering, otherwise the
    transcription of the table in force — and for a mechanic with no
    approved equation, a plain statement that it is not calculated.
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
        from_entry = _entry_equation(_applied_entry(context, "crediting"), "crediting")
        if from_entry:
            return from_entry
        equation = _eq.render_equation(_eq.crediting_body(), "crediting")
        pct = _fmt_pct(raw.get("value"))
        if pct:
            equation += f" Guaranteed annual rate in force: {pct}."
        return "Interest credited each month = " + equation
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
        from_entry = _entry_equation(_applied_entry(context, "deathBenefit"), "death benefit")
        if from_entry:
            return from_entry
        return "Death benefit = " + _eq.render_equation(_eq.death_benefit_body(), "death_benefit")
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
                "Not calculated — no approved equation in force" if fallback and fallback.get("mode") == "missing_equation" else "Synthetic schedule in force (scenario-only)" if fallback else raw.get("status")
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
            "detail": "Unmodeled product mechanic" if definition is None else "Not calculated — an approved equation or required input is missing" if has_missing else "Uses a provisional input (synthetic schedule or scenario value)" if has_provisional else "Ready",
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
                    and (node.get("fallbackDisclosure") or {}).get("mode") == "missing_equation"
                    for node in nodes
                )
            )
            edges.append({
                "id": f"{dependency}->{node_id}",
                "source": dependency,
                "target": node_id,
                "kind": edge_kind,
                "status": "inactive_missing_equation" if inactive_lookup else "active" if dependency in known_node_ids else "unresolved",
                "detail": "Inactive while no approved COI equation is in force" if inactive_lookup else None,
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
