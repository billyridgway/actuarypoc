from actuarypoc.domain.projection_graph import compile_projection_graph


def _input(input_id: str, status: str = "configured") -> dict:
    return {"id": input_id, "label": input_id.replace("_", " ").title(), "status": status, "value": 1}


def _step(rule_id: str, order: int) -> dict:
    return {"id": rule_id, "order": order, "title": rule_id.replace("_", " ").title(), "result": {"value": 1}}


def test_compiler_uses_stable_dependencies_and_propagates_missing_data() -> None:
    graph = compile_projection_graph(
        product_code="UL-1",
        product_type="UL",
        inputs=[
            _input("premium"), _input("premium_mode"), _input("face_amount"),
            _input("coi_rate", "missing"), _input("policy_fee"), _input("guaranteed_rate"),
        ],
        steps=[
            _step("opening_policy_value", 1), _step("premium_added", 2),
            _step("coi_charge_deducted", 3), _step("policy_admin_fee_deducted", 4),
            _step("interest_credited", 5), _step("closing_policy_value", 6),
        ],
        input_configs={"premium": {"kind": "number", "min": 1}},
    )

    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("input:coi_rate", "rule:coi_charge_deducted") in edges
    assert ("rule:coi_charge_deducted", "rule:closing_policy_value") in edges
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["input:premium"]["editable"] is True
    assert nodes["rule:coi_charge_deducted"]["status"] == "provisional"
    assert nodes["rule:closing_policy_value"]["status"] == "provisional"


def test_discovered_unknown_mechanics_are_visible_instead_of_dropped() -> None:
    graph = compile_projection_graph(
        product_code="NEW-1",
        product_type="UL",
        inputs=[_input("persistency_assumption")],
        steps=[_step("dynamic_lapse_adjustment", 1)],
    )

    assert graph["unmodeledMechanics"] == [
        "input:persistency_assumption",
        "rule:dynamic_lapse_adjustment",
    ]
    assert all(node["kind"] == "unmodeled" and node["status"] == "missing" for node in graph["nodes"])
    assert {item["code"] for item in graph["diagnostics"]} == {"unregistered_input", "unmodeled_mechanic"}


def test_product_evidence_changes_the_compiled_topology() -> None:
    base = compile_projection_graph(
        product_code="UL-A", product_type="UL",
        inputs=[_input("premium"), _input("premium_mode")],
        steps=[_step("premium_added", 1)],
    )
    surrender = compile_projection_graph(
        product_code="UL-B", product_type="UL",
        inputs=[_input("premium"), _input("premium_mode"), _input("face_amount"), _input("surrender_schedule")],
        steps=[_step("premium_added", 1), _step("surrender_charge", 2)],
    )

    assert {node["id"] for node in base["nodes"]} != {node["id"] for node in surrender["nodes"]}
    assert "rule:surrender_charge" not in {node["id"] for node in base["nodes"]}
    assert "rule:surrender_charge" in {node["id"] for node in surrender["nodes"]}


def test_ul_registry_is_not_misapplied_to_an_unimplemented_product_family() -> None:
    graph = compile_projection_graph(
        product_code="TERM-1", product_type="Term Life",
        inputs=[_input("premium")], steps=[_step("premium_added", 1)],
    )

    assert graph["registry"] == {"mechanics": [], "rules": []}
    assert graph["unmodeledMechanics"] == ["input:premium", "rule:premium_added"]


def test_projection_timing_controls_are_registered_and_connected() -> None:
    graph = compile_projection_graph(
        product_code="UL-1",
        product_type="UL",
        inputs=[
            _input("projection_horizon"), _input("premium_timing"), _input("charge_timing"),
            _input("premium"), _input("premium_mode"), _input("face_amount"),
            _input("coi_rate"), _input("policy_fee"), _input("guaranteed_rate"),
        ],
        steps=[
            _step("opening_policy_value", 1), _step("premium_added", 2),
            _step("coi_charge_deducted", 3), _step("policy_admin_fee_deducted", 4),
            _step("interest_credited", 5),
        ],
    )

    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["input:projection_horizon"]["mechanicId"] == "projection_controls"
    assert nodes["input:premium_timing"]["status"] == "ready"
    assert nodes["input:charge_timing"]["status"] == "ready"
    assert not graph["unmodeledMechanics"]
    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("input:projection_horizon", "rule:opening_policy_value") in edges
    assert ("input:premium_timing", "rule:premium_added") in edges
    assert ("input:charge_timing", "rule:coi_charge_deducted") in edges
    assert ("input:charge_timing", "rule:policy_admin_fee_deducted") in edges
    assert ("input:premium_timing", "rule:interest_credited") in edges


def test_diagnostic_projection_basis_is_registered_as_provisional_context() -> None:
    graph = compile_projection_graph(
        product_code="UL-1",
        product_type="UL",
        inputs=[
            _input("scenario_basis", "diagnostic"), _input("face_amount"),
            _input("coi_rate"), _input("charge_timing"),
        ],
        steps=[_step("coi_charge_deducted", 1)],
    )

    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["input:scenario_basis"]["kind"] == "input"
    assert nodes["input:scenario_basis"]["mechanicId"] == "projection_controls"
    assert nodes["input:scenario_basis"]["status"] == "provisional"
    assert nodes["input:scenario_basis"]["contributionType"] == "scenario_context"
    assert "input:scenario_basis" not in graph["unmodeledMechanics"]
    assert ("input:scenario_basis", "rule:coi_charge_deducted") in {
        (edge["source"], edge["target"]) for edge in graph["edges"]
    }


def test_graph_distinguishes_values_selectors_settings_and_context_edges() -> None:
    graph = compile_projection_graph(
        product_code="UL-1",
        product_type="UL",
        inputs=[
            _input("face_amount"), _input("coi_rate"), _input("issue_age"),
            _input("sex"), _input("risk_class"), _input("tobacco_status"),
            _input("charge_timing"), _input("scenario_basis", "diagnostic"),
        ],
        steps=[_step("coi_charge_deducted", 1)],
    )

    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["input:face_amount"]["contributionType"] == "calculation_input"
    assert nodes["input:sex"]["contributionType"] == "conditional_selector"
    assert nodes["input:charge_timing"]["contributionType"] == "execution_setting"
    kinds = {(edge["source"], edge["kind"]) for edge in graph["edges"]}
    assert ("input:face_amount", "value_dependency") in kinds
    assert ("input:sex", "conditional_lookup") in kinds
    assert ("input:charge_timing", "execution_control") in kinds
    assert ("input:scenario_basis", "scenario_context") in kinds


def test_missing_coi_table_discloses_fallback_and_disables_selector_lookups() -> None:
    graph = compile_projection_graph(
        product_code="UL-1",
        product_type="UL",
        inputs=[
            _input("face_amount"), _input("coi_rate", "placeholder"), _input("issue_age"),
            _input("sex"), _input("risk_class"), _input("tobacco_status"),
            _input("charge_timing"), _input("scenario_basis", "diagnostic"),
        ],
        steps=[_step("coi_charge_deducted", 1)],
    )

    nodes = {node["id"]: node for node in graph["nodes"]}
    disclosure = nodes["input:coi_rate"]["fallbackDisclosure"]
    assert disclosure["missingEvidence"] == "Filed COI rate table"
    assert disclosure["fallback"] == "Flat placeholder COI rate"
    selector_edges = [edge for edge in graph["edges"] if edge["kind"] == "conditional_lookup"]
    assert selector_edges
    assert all(edge["status"] == "inactive_fallback" for edge in selector_edges)


def test_synthetic_coi_table_remains_provisional_but_activates_selector_lookups() -> None:
    graph = compile_projection_graph(
        product_code="UL-1",
        product_type="UL",
        inputs=[
            _input("face_amount"), _input("coi_rate", "synthetic_assumption"), _input("issue_age"),
            _input("sex"), _input("risk_class"), _input("tobacco_status"),
            _input("charge_timing"), _input("scenario_basis", "diagnostic"),
        ],
        steps=[_step("coi_charge_deducted", 1)],
    )

    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["input:coi_rate"]["status"] == "provisional"
    assert nodes["input:coi_rate"]["fallbackDisclosure"]["mode"] == "synthetic_active"
    selector_edges = [edge for edge in graph["edges"] if edge["kind"] == "conditional_lookup"]
    assert selector_edges
    assert all(edge["status"] == "active" for edge in selector_edges)


def test_synthetic_surrender_schedule_is_provisional_and_disclosed() -> None:
    graph = compile_projection_graph(
        product_code="UL-1",
        product_type="UL",
        inputs=[_input("face_amount"), _input("surrender_schedule", "synthetic_assumption"), _input("scenario_basis", "diagnostic")],
        steps=[_step("surrender_charge", 1)],
    )
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["input:surrender_schedule"]["status"] == "provisional"
    assert nodes["input:surrender_schedule"]["fallbackDisclosure"]["mode"] == "synthetic_active"
