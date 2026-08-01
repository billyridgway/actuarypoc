"""Compile product projection metadata into a stable directed graph contract.

The graph is deliberately produced by the backend.  The UI must not infer
dependencies from labels because labels are presentation text, while mechanic
IDs are versioned execution contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


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
    MechanicDefinition("premium", ("premium", "premium_mode"), ("premium_added",)),
    MechanicDefinition("coi", ("coi_rate",), ("coi_charge_deducted",), "coi_table"),
    MechanicDefinition("policy_fee", ("policy_fee",), ("policy_admin_fee_deducted",), "policy_admin_fees"),
    MechanicDefinition("crediting", ("guaranteed_rate",), ("interest_credited",)),
    MechanicDefinition("account_value", (), ("opening_policy_value", "closing_policy_value")),
    MechanicDefinition("surrender", ("surrender_schedule",), ("surrender_charge", "surrender_value"), "surrender_schedule"),
    MechanicDefinition("death_benefit", ("death_benefit_option",), ("death_benefit", "net_amount_at_risk")),
)


UL_RULES: Sequence[RuleDefinition] = (
    RuleDefinition("opening_policy_value", "account_value"),
    RuleDefinition("premium_added", "premium", ("input:premium", "input:premium_mode")),
    RuleDefinition("coi_charge_deducted", "coi", ("input:face_amount", "input:coi_rate")),
    RuleDefinition("policy_admin_fee_deducted", "policy_fee", ("input:policy_fee",)),
    RuleDefinition("interest_credited", "crediting", ("rule:opening_policy_value", "input:guaranteed_rate", "input:premium")),
    RuleDefinition(
        "closing_policy_value",
        "account_value",
        (
            "rule:opening_policy_value", "rule:premium_added", "rule:coi_charge_deducted",
            "rule:policy_admin_fee_deducted", "rule:interest_credited",
        ),
    ),
    RuleDefinition("surrender_charge", "surrender", ("input:face_amount", "input:surrender_schedule")),
    RuleDefinition("surrender_value", "surrender", ("rule:closing_policy_value", "rule:surrender_charge")),
    RuleDefinition("death_benefit", "death_benefit", ("input:face_amount", "input:death_benefit_option")),
    RuleDefinition("net_amount_at_risk", "death_benefit", ("rule:death_benefit", "rule:closing_policy_value")),
)


def _status(value: Any) -> str:
    raw = str(value or "").lower()
    if raw in {"missing", "not_available"}:
        return "missing"
    if raw in {"placeholder", "derived_placeholder", "default", "diagnostic", "not_supplied", "scenario_assumption"}:
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

    nodes: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    for index, raw in enumerate(inputs):
        input_id = str(raw.get("id") or f"input-{index}")
        mechanic_id = input_mechanic.get(input_id, "unmodeled")
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
            "detail": "Unmodeled product mechanic" if mechanic_id == "unmodeled" else raw.get("status"),
            "value": raw.get("value"),
            "unit": raw.get("unit"),
            "source": raw.get("source"),
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
            edges.append({
                "id": f"{dependency}->{node_id}",
                "source": dependency,
                "target": node_id,
                "kind": "value_dependency",
                "status": "active" if dependency in known_node_ids else "unresolved",
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
