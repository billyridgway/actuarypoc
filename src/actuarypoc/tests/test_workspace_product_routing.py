from actuarypoc.ui import server


def test_promise_ul_type_does_not_require_product_review_storage(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_product_review", lambda product_code: None)

    assert server._get_product_type("ICC18 P18PR UL") == "UL"
    assert server._get_product_type("ICC18P18PRUL") == "UL"


def test_product_review_type_takes_precedence(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "get_product_review",
        lambda product_code: {"metadata": {"productType": "Universal Life"}},
    )

    assert server._get_product_type("CUSTOM-UL") == "Universal Life"


def test_unknown_product_without_review_is_not_assumed_to_be_ul(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_product_review", lambda product_code: None)

    assert server._get_product_type("UNKNOWN") == ""
    assert not server._is_ul_product_type(server._get_product_type("UNKNOWN"))


def test_promise_ul_workspace_snapshot_builds_without_review_storage(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_product_review", lambda product_code: None)
    monkeypatch.setattr(server, "list_product_documents", lambda product_code, filing_id=None: [])

    snapshot = server.build_product_workspace_snapshot("ICC18 P18PR UL")

    assert snapshot["product"]["code"] == "ICC18 P18PR UL"
    assert snapshot["productModel"]["type"] == "ul"
    assert snapshot["illustration"] is not None


def test_workspace_evidence_replaces_generic_citation(monkeypatch) -> None:
    snapshot = server.build_product_workspace_snapshot("ICC18 P18PR UL")
    documents = [
        {"description": "Promise UL Actuarial Memo.pdf", "object_path": "workspace/memo.pdf"},
        {"description": "ICC18 P18PRUL.pdf", "object_path": "workspace/policy.pdf"},
    ]
    corpus = [
        {
            "filename": "Promise UL Actuarial Memo.pdf",
            "objectPath": "workspace/memo.pdf",
            "pages": [
                "The annual credited rate will not be less than the Guaranteed Minimum "
                "Annual Interest Rate shown in the Policy Specification which is currently "
                "set at 2%. Policy credits interest at least at the guaranteed minimum rate."
            ],
        },
        {
            "filename": "ICC18 P18PRUL.pdf",
            "objectPath": "workspace/policy.pdf",
            "pages": [
                "ICC18 P18PRULAPPLICANT. Issue ages 18 through 80. "
                "Underwriting classes: Preferred Plus, Standard, Tobacco."
            ],
        },
    ]
    monkeypatch.setattr(server, "_extract_workspace_documents", lambda docs: (documents, corpus))

    result = server._apply_workspace_document_evidence(snapshot, documents)

    facts = {fact["label"]: fact for fact in result["extractedFacts"]}
    assert facts["Product name"]["provenanceKind"] == "workspace_document"
    assert facts["Form numbers"]["value"] == ["ICC18 P18PRUL"]
    assert facts["Issue age range"]["value"] == "18-80"
    assert facts["Risk classes"]["value"] == ["Preferred Plus", "Standard", "Tobacco"]
    assert result["formClassifications"]["primary"] == ["ICC18 P18PRUL"]
    assert "ICC18 P18PRULAPPLICANT" not in result["formClassifications"]["referenced"]
    credited = result["complianceMatrix"]["requirements"][0]
    source = credited["evidence"][0]["sources"][0]
    assert source["document"] == "Promise UL Actuarial Memo.pdf"
    assert source["page"] == "1"

    server._reconcile_workspace_readiness(result)
    capabilities = server._build_capability_assessment(result)
    statuses = {item["sourceRequirementId"]: item["status"] for item in capabilities["items"]}
    assert statuses["coi_table"] == "unsupported"
    assert statuses["surrender_schedule"] == "partial"
    assert statuses["policy_admin_fees"] == "partial"


def test_workspace_readiness_counts_missing_requirements() -> None:
    snapshot = {
        "complianceMatrix": {
            "requirements": [
                {"status": "implemented", "impact": "high"},
                {"status": "partial", "impact": "high"},
                {"status": "missing", "impact": "medium"},
            ]
        },
        "readinessDashboard": {},
        "pmrReadiness": {
            "messages": [
                "No review exists.",
                "Compliance summary: implemented=2, partial=2, missing=0, overall status=yellow.",
            ]
        },
    }

    server._reconcile_workspace_readiness(snapshot)

    assert snapshot["complianceMatrix"]["summary"] == {
        "implemented": 1,
        "partial": 1,
        "missing": 1,
        "overallStatus": "yellow",
    }
    assert snapshot["readinessDashboard"]["projectionTrustLevel"] == "exploration_only"
    assert snapshot["pmrReadiness"]["complianceSummary"]["missing"] == 1
    assert snapshot["pmrReadiness"]["messages"][-1] == (
        "Compliance summary: implemented=1, partial=1, missing=1, overall status=yellow."
    )
