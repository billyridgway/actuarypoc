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
