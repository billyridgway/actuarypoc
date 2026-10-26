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


def test_missing_coi_equation_is_disclosed_and_disables_selector_lookups() -> None:
    graph = compile_projection_graph(
        product_code="UL-1",
        product_type="UL",
        inputs=[
            _input("face_amount"), _input("coi_rate", "missing"), _input("issue_age"),
            _input("sex"), _input("risk_class"), _input("tobacco_status"),
            _input("charge_timing"), _input("scenario_basis", "diagnostic"),
        ],
        steps=[_step("coi_charge_deducted", 1)],
    )

    nodes = {node["id"]: node for node in graph["nodes"]}
    disclosure = nodes["input:coi_rate"]["fallbackDisclosure"]
    assert disclosure["mode"] == "missing_equation"
    assert disclosure["missingEvidence"] == "Approved COI charge equation"
    # Phase 7: there is no fallback calculation to disclose.
    assert "fallback" not in disclosure
    assert "Not calculated" in nodes["input:coi_rate"]["equation"]
    selector_edges = [edge for edge in graph["edges"] if edge["kind"] == "conditional_lookup"]
    assert selector_edges
    assert all(edge["status"] == "inactive_missing_equation" for edge in selector_edges)


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


def _nodes(graph: dict) -> dict:
    return {node["id"]: node for node in graph["nodes"]}


def _compile(inputs, steps=(), context=None):
    return compile_projection_graph(
        product_code="UL-1", product_type="UL",
        inputs=inputs, steps=list(steps), context=context,
    )


def test_equations_without_run_context_state_the_missing_equation() -> None:
    # Legacy snapshots carry no ledger or applied-mechanics record, and
    # no tables are in force here: every mechanic input states plainly
    # that it is not calculated.  (Before Phase 7 these nodes stated the
    # placeholder formulas; those calculations no longer exist.)
    graph = _compile([
        {"id": "surrender_schedule", "label": "Surrender charge schedule", "status": "missing",
         "value": None, "source": "No approved surrender charge equation is in force"},
        {"id": "coi_rate", "label": "COI schedule", "status": "missing", "value": None, "unit": None},
        {"id": "policy_fee", "label": "Annual policy/admin fee", "status": "missing", "value": None, "unit": "USD"},
    ])
    nodes = _nodes(graph)

    coi = nodes["input:coi_rate"]["equation"]
    assert "Not calculated" in coi
    assert "no approved COI charge equation" in coi

    surrender = nodes["input:surrender_schedule"]["equation"]
    assert "Not calculated" in surrender
    assert "no approved surrender charge equation" in surrender

    fee = nodes["input:policy_fee"]["equation"]
    assert "Not calculated" in fee
    assert "no approved policy fees equation" in fee


def test_surrender_equation_names_the_ending_account_value() -> None:
    context = {
        "rateTables": {
            "surrender": {"status": "filed", "rows": [{"duration": 1, "charge": 0.1, "charge_unit": "percent_account_value"}]},
        }
    }
    graph = _compile(
        [{"id": "surrender_schedule", "label": "Surrender", "status": "evidenced", "value": "10 executable rows"}],
        context=context,
    )
    equation = _nodes(graph)["input:surrender_schedule"]["equation"]
    assert "ending account value" in equation
    assert "surrender schedule charge" in equation


def test_filed_table_equations_carry_the_table_unit_basis() -> None:
    context = {
        "rateTables": {
            "surrender": {"status": "filed", "rows": [{"duration": 1, "charge": 12.5, "charge_unit": "per_1000_face"}]},
            "coi": {"status": "filed", "rows": [{"duration": 1, "rate": 0.11, "rate_unit": "per_1000_monthly"}]},
        }
    }
    graph = _compile(
        [
            {"id": "surrender_schedule", "label": "Surrender", "status": "evidenced", "value": "20 executable rows"},
            {"id": "coi_rate", "label": "COI schedule", "status": "evidenced", "value": "968 executable rows"},
        ],
        context=context,
    )
    nodes = _nodes(graph)
    surrender = nodes["input:surrender_schedule"]["equation"]
    assert "face amount / 1000" in surrender
    assert "surrender schedule charge" in surrender
    assert "filed schedule in force" in surrender
    coi = nodes["input:coi_rate"]["equation"]
    assert "net amount at risk / 1000" in coi
    assert "COI table rate" in coi


def test_synthetic_table_equations_are_labelled_synthetic() -> None:
    from actuarypoc.domain import equations as _eq

    context = {
        "appliedMechanics": {
            "surrender": {
                "equation": {
                    "rendering": _eq.render_equation(
                        _eq.surrender_body_for_unit("percent_account_value"), "surrender_charge"
                    ),
                    "tableSourceType": "ai_synthetic",
                },
                "missing": False,
                "rowApplied": True,
            },
            "coi": {
                "equation": {
                    "rendering": _eq.render_with_timing(
                        _eq.coi_body_for_unit("per_1000_annual"), "beginning"
                    ),
                    "tableSourceType": "ai_synthetic",
                },
                "missing": False,
            },
        }
    }
    graph = _compile(
        [
            {"id": "surrender_schedule", "label": "Surrender", "status": "synthetic_assumption", "value": "10 executable rows"},
            {"id": "coi_rate", "label": "COI schedule", "status": "synthetic_assumption", "value": "968 executable rows"},
        ],
        context=context,
    )
    nodes = _nodes(graph)
    surrender = nodes["input:surrender_schedule"]["equation"]
    assert "synthetic schedule in force" in surrender
    assert "ending account value" in surrender
    coi = nodes["input:coi_rate"]["equation"]
    assert "synthetic schedule in force" in coi
    assert "net amount at risk / 1000" in coi
    assert "COI table rate" in coi


def test_applied_missing_and_fee_equation() -> None:
    from actuarypoc.domain import equations as _eq

    context = {
        "appliedMechanics": {
            "surrender": {"equation": None, "missing": True},
            "coi": {"equation": None, "missing": True},
            "fees": {
                "equation": {
                    "rendering": _eq.render_equation(_eq.policy_fees_body(), "policy_fees"),
                    "tableSourceType": "filed_pdf",
                },
                "missing": False,
            },
        }
    }
    graph = _compile(
        [
            {"id": "surrender_schedule", "label": "Surrender", "status": "missing", "value": None},
            {"id": "coi_rate", "label": "COI schedule", "status": "missing", "value": None},
            {"id": "policy_fee", "label": "Fee", "status": "evidenced", "value": "3 executable rows"},
        ],
        context=context,
    )
    nodes = _nodes(graph)
    assert "Not calculated" in nodes["input:surrender_schedule"]["equation"]
    assert "Not calculated" in nodes["input:coi_rate"]["equation"]
    fee = nodes["input:policy_fee"]["equation"]
    assert "sum over the fee schedule rows in force" in fee


def test_ledger_formulas_are_reused_verbatim_when_the_run_carries_them() -> None:
    context = {
        "ledgerFormulas": {
            "coi": "LEDGER-COI-FORMULA",
            "surrender_charge": "LEDGER-SURRENDER-FORMULA",
            "policy_fee": "LEDGER-FEE-FORMULA",
        }
    }
    graph = _compile(
        [
            {"id": "coi_rate", "label": "COI", "status": "evidenced", "value": "rows"},
            {"id": "surrender_schedule", "label": "Surrender", "status": "evidenced", "value": "rows"},
            {"id": "policy_fee", "label": "Fee", "status": "evidenced", "value": "rows"},
        ],
        context=context,
    )
    nodes = _nodes(graph)
    assert nodes["input:coi_rate"]["equation"] == "LEDGER-COI-FORMULA"
    assert nodes["input:surrender_schedule"]["equation"] == "LEDGER-SURRENDER-FORMULA"
    assert nodes["input:policy_fee"]["equation"] == "LEDGER-FEE-FORMULA"


def test_scenario_fee_and_remaining_calculation_inputs_have_equations() -> None:
    graph = _compile([
        {"id": "policy_fee", "label": "Fee", "status": "scenario_assumption", "value": 240.0, "unit": "USD"},
        {"id": "guaranteed_rate", "label": "Guaranteed rate", "status": "evidenced", "value": 0.02, "unit": "rate"},
        {"id": "premium", "label": "Annual premium", "status": "user_entered", "value": 3000.0, "unit": "USD"},
        {"id": "death_benefit_option", "label": "DB option", "status": "configured", "value": "level"},
        {"id": "sex", "label": "Sex", "status": "not_supplied", "value": None},
        {"id": "face_amount", "label": "Face amount", "status": "default", "value": 100000.0},
    ])
    nodes = _nodes(graph)
    fee = nodes["input:policy_fee"]["equation"]
    assert "$240.00" in fee and "user-entered" in fee
    assert "not applied" in fee
    crediting = nodes["input:guaranteed_rate"]["equation"]
    assert "(1 + the guaranteed annual rate)" in crediting
    assert "Guaranteed annual rate in force: 2.00%" in crediting
    assert "modal premium x payments per year" in nodes["input:premium"]["equation"]
    death_benefit = nodes["input:death_benefit_option"]["equation"]
    assert "the greater of (the face amount" in death_benefit
    assert "corridor" in death_benefit
    # Selectors and plain scenario values carry no applied equation.
    assert nodes["input:sex"]["equation"] is None
    assert nodes["input:face_amount"]["equation"] is None


def test_every_mechanic_input_has_an_equation_in_every_state() -> None:
    states = {
        "coi_rate": ["evidenced", "synthetic_assumption", "placeholder", "missing"],
        "surrender_schedule": ["evidenced", "synthetic_assumption", "placeholder", "missing"],
        "policy_fee": ["evidenced", "synthetic_assumption", "missing", "scenario_assumption"],
    }
    values = {
        "coi_rate": 0.004,
        "surrender_schedule": "10.00% of account value declining over 19 years",
        "policy_fee": 0.0,
    }
    for input_id, statuses in states.items():
        for status in statuses:
            graph = _compile([{"id": input_id, "label": input_id, "status": status, "value": values[input_id]}])
            equation = _nodes(graph)[f"input:{input_id}"]["equation"]
            assert equation and equation.strip(), f"{input_id} in state {status} has no equation"
