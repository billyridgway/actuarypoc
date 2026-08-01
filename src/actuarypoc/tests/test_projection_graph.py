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
