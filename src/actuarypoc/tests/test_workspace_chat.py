"""Grounded workbench chat (Nov 5, 2026).

The chat answers questions about the product and the presented
projection under the product doctrine, and these tests pin the
doctrine, not just the plumbing:

* the router classifies into exactly one intent, deterministically
  (filing / model / ledger / scenario change / out of scope), and
  flags explicit arithmetic requests;
* the chat NEVER computes numbers — with a stubbed model that
  states a fabricated figure, the grounding pass drops the
  offending sentence and the answer keeps only tool-provided
  figures;
* a scenario change returns a structured proposal for the scenario
  form and no computed figures;
* absence is a first-class answer in three-state language ("not in
  the documents"), never an improvisation;
* citations that survive validation name material the tools
  actually provided (document + page, equation in force, ledger
  years).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from actuarypoc.domain import equations as eq
from actuarypoc.extract import workspace_chat as chat
from actuarypoc.extract import workspace_equations as ws_eq
from actuarypoc.ui import server

from actuarypoc.tests.test_workspace_mechanics_proposals import _slice


AT = "2026-11-05T12:00:00Z"
NAR_STATEMENT = (
    "Net Amount at Risk is the Death Benefit less the Account Value."
)


def _nar_record() -> dict:
    return ws_eq.new_record(
        mechanic="nar_definition",
        body=eq.nar_body("unadjusted"),
        state="approved",
        source={
            "kind": "document",
            "statement": NAR_STATEMENT,
            "filename": "specimen-base.pdf",
            "page": 5,
        },
        at=AT,
        record_id="eq-chat-nar",
    )


def _coi_rows() -> list:
    return [
        {
            "duration": d, "attained_age": None, "sex": "M",
            "risk_class": "Standard", "tobacco_status": "Non-Tobacco",
            "rate": 0.19 + 0.01 * (d - 1), "rate_unit": "per_1000_monthly",
            "provenance": {
                "sourceType": "filed_pdf", "filename": "specimen-base.pdf",
                "page": 4, "tableHeading": "COI schedule",
            },
        }
        for d in (1, 2, 3)
    ]


def _ledger_rows() -> list:
    return [
        {"year": 9, "cashValue": 47000.0, "deathBenefit": 100000.0},
        {"year": 10, "cashValue": 50000.0, "deathBenefit": 100000.0},
        {"year": 11, "cashValue": 53500.0, "deathBenefit": 100000.0},
    ]


def _artifact() -> dict:
    return {
        "version": 1,
        "equations": [_nar_record()],
        "candidates": {},
        "usable": {"coi": _coi_rows()},
    }


def _coverage() -> dict:
    return {
        "equations": {
            "nar_definition": {
                "state": "covered", "filename": "specimen-base.pdf",
                "page": 5, "statement": NAR_STATEMENT,
            },
            "surrender_charge": {
                "state": "absent", "filename": None, "page": None,
                "statement": None,
            },
        },
        "tables": {"coi": True},
    }


def _context(**overrides) -> chat.ChatContext:
    snapshot = {
        "illustration": {
            "request": {
                "age": 45, "faceAmount": 100000, "modalPremium": 3000,
                "premiumMode": "ANNUAL", "sex": "M",
                "riskClass": "Standard", "tobaccoStatus": "Non-Tobacco",
            },
            "rows": _ledger_rows(),
            "metrics": {},
        }
    }
    kwargs = dict(
        workspace_id="ws-chat",
        snapshot=snapshot,
        artifact=_artifact(),
        slices=[_slice(NAR_STATEMENT, page=5, filename="specimen-base.pdf")],
        coverage=_coverage(),
    )
    kwargs.update(overrides)
    return chat.ChatContext(**kwargs)


# ---------------------------------------------------------------------------
# Stage 1: the router
# ---------------------------------------------------------------------------


def test_router_filing_fact() -> None:
    route = chat.classify_intent("What does the filing say about the grace period?")
    assert route.intent == chat.INTENT_FILING_FACT


def test_router_model_fact_names_the_mechanic() -> None:
    route = chat.classify_intent("How is the net amount at risk defined?")
    assert route.intent == chat.INTENT_MODEL_FACT
    assert route.slots["mechanics"] == ["nar_definition"]


def test_router_ledger_explanation_extracts_the_year() -> None:
    route = chat.classify_intent("Why does the cash value dip in year 9?")
    assert route.intent == chat.INTENT_LEDGER
    assert route.slots["years"] == [9]


def test_router_table_question_is_model_fact_not_ledger() -> None:
    route = chat.classify_intent("What is the COI rate at duration 5?")
    assert route.intent == chat.INTENT_MODEL_FACT
    assert route.slots["tables"] == ["coi"]


def test_router_scenario_change_parses_the_field() -> None:
    route = chat.classify_intent("What if the premium were $5,000 a year?")
    assert route.intent == chat.INTENT_SCENARIO_CHANGE
    changes = route.slots["scenario_changes"]
    assert changes[0]["field"] == "premium"
    assert changes[0]["newValue"] == 5000.0


def test_router_flags_the_arithmetic_trap() -> None:
    route = chat.classify_intent("What's 12% of the year-10 cash value?")
    assert route.intent == chat.INTENT_LEDGER
    assert route.slots["arithmetic_request"] is True
    assert route.slots["years"] == [10]


def test_router_out_of_scope() -> None:
    route = chat.classify_intent("What's the weather in Chicago?")
    assert route.intent == chat.INTENT_OUT_OF_SCOPE


def test_router_product_overview_story() -> None:
    """Billy's verbatim live question (Nov 5, 2026): a product-level
    ask with no mechanic, table, or ledger anchor is an overview,
    not out of scope."""

    route = chat.classify_intent("Tell me the story about this insurance product.")
    assert route.intent == chat.INTENT_PRODUCT_OVERVIEW


def test_router_product_overview_summarize() -> None:
    route = chat.classify_intent("Summarize this insurance product.")
    assert route.intent == chat.INTENT_PRODUCT_OVERVIEW


def test_router_product_overview_what_is_this_product() -> None:
    route = chat.classify_intent("What is this product?")
    assert route.intent == chat.INTENT_PRODUCT_OVERVIEW


def test_router_explain_mechanic_is_not_overview() -> None:
    """A summary verb aimed at a named mechanic stays with the
    mechanic's specific intent."""

    route = chat.classify_intent("Explain the COI charge.")
    assert route.intent == chat.INTENT_MODEL_FACT


def test_router_summarize_table_is_not_overview() -> None:
    route = chat.classify_intent("Summarize the surrender table.")
    assert route.intent == chat.INTENT_MODEL_FACT
    assert route.slots["tables"] == ["surrender"]


# ---------------------------------------------------------------------------
# The tool layer
# ---------------------------------------------------------------------------


def test_tool_table_slice_filters_by_duration() -> None:
    ctx = _context()
    view = ctx.get_table_slice("coi", {"duration": 2})
    assert view["inForce"] is True
    assert view["rowCount"] == 1
    assert view["rows"][0]["duration"] == 2
    assert view["provenance"]["filename"] == "specimen-base.pdf"


def test_tool_search_filing_text_returns_document_and_page() -> None:
    ctx = _context()
    hits = ctx.search_filing_text(["net amount at risk"])
    assert hits
    assert hits[0]["document"] == "specimen-base.pdf"
    assert hits[0]["page"] == 5
    assert "Net Amount at Risk" in hits[0]["snippet"]


def test_tool_equation_in_force_quotes_the_filed_statement() -> None:
    ctx = _context()
    record = ctx.get_equation_in_force("nar_definition")
    assert record is not None
    assert record["statement"] == NAR_STATEMENT
    assert record["page"] == 5


# ---------------------------------------------------------------------------
# The doctrine, end to end (stubbed model)
# ---------------------------------------------------------------------------


def _stub_caller(payload):
    def call(system: str, user: str):
        return payload

    return call


def test_grounding_drops_a_fabricated_figure() -> None:
    """The stubbed model states one tool-provided figure and one it
    invented.  The invented figure's sentence is dropped; the quoted
    figure survives, with the drop disclosed."""

    ctx = _context()
    caller = _stub_caller({
        "answer": (
            "The year 10 cash value is $50,000. "
            "The surrender value is $999,999."
        ),
        "citations": [{"kind": "ledger", "years": [10]}],
    })
    result = chat.answer_question(
        ctx, "What is the cash value in year 10?", answer_caller=caller
    )
    assert result["intent"] == chat.INTENT_LEDGER
    assert "$50,000" in result["answer"]
    assert "999" not in result["answer"]
    assert result.get("groundingNote")
    assert result["citations"]
    assert result["citations"][0]["kind"] == "ledger"
    assert result["citations"][0]["years"] == [10]


def test_filing_answer_carries_document_and_page_citation() -> None:
    ctx = _context()
    caller = _stub_caller({
        "answer": (
            "The filing states: Net Amount at Risk is the Death "
            "Benefit less the Account Value."
        ),
        "citations": [
            {"kind": "filing", "document": "specimen-base.pdf", "page": 5}
        ],
    })
    result = chat.answer_question(
        ctx,
        "What does the filing say about the net amount at risk?",
        answer_caller=caller,
    )
    assert result["intent"] == chat.INTENT_FILING_FACT
    assert result["citations"] == [{
        "kind": "filing",
        "document": "specimen-base.pdf",
        "page": 5,
        "label": "specimen-base.pdf · p. 5",
    }]


def test_invalid_citations_are_dropped() -> None:
    ctx = _context()
    caller = _stub_caller({
        "answer": "The year 10 cash value is $50,000.",
        "citations": [
            {"kind": "filing", "document": "invented.pdf", "page": 99},
            {"kind": "ledger", "years": [10]},
        ],
    })
    result = chat.answer_question(
        ctx, "What is the cash value in year 10?", answer_caller=caller
    )
    kinds = [(c["kind"], c.get("document")) for c in result["citations"]]
    assert ("filing", "invented.pdf") not in kinds
    assert ("ledger", None) in kinds


def test_arithmetic_trap_is_never_computed() -> None:
    """12% of the year-10 cash value ($50,000) is $6,000 — the chat
    must quote the base figure and decline the arithmetic, and the
    product must appear nowhere in the answer."""

    ctx = _context()
    result = chat.answer_question(
        ctx, "What's 12% of the year-10 cash value?",
        answer_caller=_stub_caller({"answer": "unused"}),
    )
    assert result["intent"] == chat.INTENT_LEDGER
    assert "don't do arithmetic" in result["answer"]
    assert "$50,000" in result["answer"]
    assert "6,000" not in result["answer"]
    assert "6000" not in result["answer"]


def test_scenario_change_returns_a_proposal_not_numbers() -> None:
    ctx = _context()
    result = chat.answer_question(
        ctx, "What if the premium were $5,000 a year?",
        answer_caller=_stub_caller({"answer": "unused"}),
    )
    assert result["intent"] == chat.INTENT_SCENARIO_CHANGE
    proposal = result["scenario_proposal"]
    assert proposal["changes"] == [{
        "field": "premium",
        "label": "Premium",
        "currentValue": 3000,
        "newValue": 5000.0,
    }]
    assert "projection engine" in result["answer"]


def test_absence_filing_question_not_in_the_documents() -> None:
    ctx = _context()
    result = chat.answer_question(
        ctx, "Does the filing allow policy loans?",
        answer_caller=_stub_caller({"answer": "unused"}),
    )
    assert result["intent"] == chat.INTENT_FILING_FACT
    assert "not in the documents" in result["answer"]


def test_absence_model_question_not_in_the_documents() -> None:
    ctx = _context()
    result = chat.answer_question(
        ctx, "How is the surrender charge calculated?",
        answer_caller=_stub_caller({"answer": "unused"}),
    )
    assert result["intent"] == chat.INTENT_MODEL_FACT
    assert "not in the documents" in result["answer"]


def test_ledger_question_without_a_run_states_the_absence() -> None:
    ctx = _context(snapshot={})
    result = chat.answer_question(
        ctx, "Why does the cash value dip in year 9?",
        answer_caller=_stub_caller({"answer": "unused"}),
    )
    assert "no presented projection" in result["answer"]


def test_out_of_scope_redirects() -> None:
    ctx = _context()
    result = chat.answer_question(
        ctx, "What's the weather in Chicago?",
        answer_caller=_stub_caller({"answer": "unused"}),
    )
    assert result["intent"] == chat.INTENT_OUT_OF_SCOPE
    assert "outside what I can answer" in result["answer"]


# ---------------------------------------------------------------------------
# Product overview (the Nov 5 live-test gap)
# ---------------------------------------------------------------------------

FRAMING_TEXT = (
    "The Promise UL is a flexible premium adjustable life insurance "
    "policy. It provides a death benefit, and its account value "
    "grows as premiums are paid and interest is credited."
)


def _overview_context(**overrides) -> chat.ChatContext:
    slices = [
        _slice(FRAMING_TEXT, page=1, filename="specimen-base.pdf"),
        _slice(NAR_STATEMENT, page=5, filename="specimen-base.pdf"),
    ]
    overrides.setdefault("slices", slices)
    return _context(**overrides)


def test_overview_answer_quotes_framing_and_cites_it() -> None:
    """The overview answers from the filings' framing passages and
    the model in force, with citations — and the grounding pass
    still applies: a fabricated figure is dropped and disclosed."""

    ctx = _overview_context()
    caller = _stub_caller({
        "answer": (
            "The Promise UL is a flexible premium adjustable life "
            "insurance policy. The presented scenario covers a "
            "45-year-old insured. It also pays a $777,777 loyalty "
            "bonus."
        ),
        "citations": [
            {"kind": "filing", "document": "specimen-base.pdf", "page": 1}
        ],
    })
    result = chat.answer_question(
        ctx, "Summarize this insurance product.", answer_caller=caller
    )
    assert result["intent"] == chat.INTENT_PRODUCT_OVERVIEW
    assert result["intentLabel"] == "Product overview"
    assert "flexible premium adjustable life" in result["answer"]
    assert "777" not in result["answer"]
    assert result.get("groundingNote")
    assert result["citations"] == [{
        "kind": "filing",
        "document": "specimen-base.pdf",
        "page": 1,
        "label": "specimen-base.pdf · p. 1",
    }]


def test_overview_without_filings_states_it_plainly() -> None:
    ctx = _overview_context(slices=[])
    result = chat.answer_question(
        ctx, "Tell me the story about this insurance product.",
        answer_caller=_stub_caller({"answer": "unused"}),
    )
    assert result["intent"] == chat.INTENT_PRODUCT_OVERVIEW
    assert "no filing documents" in result["answer"]
    assert result["citations"] == []


# ---------------------------------------------------------------------------
# Ride-alongs from the Nov 5 live gate
# ---------------------------------------------------------------------------


def test_absence_despite_generic_filing_hits() -> None:
    """This morning's gate failure: the question's framing words
    ("what does the filing say") matched filing pages, the model
    answered absence from unrelated passages, and the generic hits
    rode along as citations.  Generic hits are not coverage: the
    deterministic absence path fires, in the canonical wording,
    with NO citations."""

    generic = (
        "The filing says this policy provides a death benefit. "
        "The filing states the premium, the account value, and "
        "the terms under which the policy remains in force."
    )
    ctx = _context(slices=[_slice(generic, page=31, filename="filing.pdf")])
    for question in (
        "What does the filing say about teleportation benefits?",
        "What does the filing say about the product's cryptocurrency mining rewards?",
    ):
        result = chat.answer_question(
            ctx, question, answer_caller=_stub_caller({"answer": "unused"})
        )
        assert result["intent"] == chat.INTENT_FILING_FACT
        assert "not in the documents" in result["answer"]
        assert result["citations"] == []


def test_ledger_figures_are_currency_in_the_context() -> None:
    """The raw ledger float (53515.465876699025) must never reach
    the answering model: the context renders money as currency, so
    the quoted figure is the ledger value rounded for display —
    $53,515.47 — digit-exact to the cent."""

    rows = [
        {"year": 9, "cashValue": 47000.0, "deathBenefit": 100000.0},
        {"year": 10, "cashValue": 53515.465876699025,
         "deathBenefit": 100000.0},
        {"year": 11, "cashValue": 57000.0, "deathBenefit": 100000.0},
    ]
    snapshot = {
        "illustration": {
            "request": {
                "age": 45, "faceAmount": 100000, "modalPremium": 3000,
                "premiumMode": "ANNUAL", "sex": "M",
                "riskClass": "Standard", "tobaccoStatus": "Non-Tobacco",
            },
            "rows": rows,
            "metrics": {},
        }
    }
    ctx = _context(snapshot=snapshot)
    seen: dict = {}

    def capturing_caller(system: str, user: str):
        seen["prompt"] = user
        return {
            "answer": "The cash value in year 10 is $53,515.47.",
            "citations": [{"kind": "ledger", "years": [10]}],
        }

    result = chat.answer_question(
        ctx, "What is the cash value in year 10?",
        answer_caller=capturing_caller,
    )
    assert "$53,515.47" in seen["prompt"]
    assert "53515.465876699025" not in seen["prompt"]
    assert result["answer"] == "The cash value in year 10 is $53,515.47."
    assert not result.get("groundingNote")


def test_proposal_current_value_recovered_from_the_ledger() -> None:
    """The projection's normalised request echo drops modalPremium,
    so a proposal built from get_scenario alone read null this
    morning.  The scenario behind the run carries the premium in
    its ledger rows; the proposal's currentValue comes from there."""

    snapshot = {
        "illustration": {
            "request": {
                # The normalised echo: no modalPremium key at all.
                "age": 45, "faceAmount": 100000,
                "premiumMode": "SEMIANNUAL", "sex": "M",
                "riskClass": "Standard", "tobaccoStatus": "Non-Tobacco",
            },
            "rows": [
                {"year": 1, "attainedAge": 45, "modalPremium": 1500.0,
                 "cashValue": 1200.0},
                {"year": 2, "attainedAge": 46, "modalPremium": 1500.0,
                 "cashValue": 2600.0},
            ],
            "metrics": {},
        }
    }
    ctx = _context(snapshot=snapshot)
    result = chat.answer_question(
        ctx, "What if the premium were $5,000 a year?",
        answer_caller=_stub_caller({"answer": "unused"}),
    )
    assert result["intent"] == chat.INTENT_SCENARIO_CHANGE
    changes = result["scenario_proposal"]["changes"]
    assert changes[0]["field"] == "premium"
    assert changes[0]["currentValue"] == 1500.0
    assert changes[0]["newValue"] == 5000.0


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def chat_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        server, "get_workspace",
        lambda wid: {
            "id": wid,
            "latest_snapshot_json": _context().snapshot,
            "inferred_product_code": "ICC18 P18PR UL",
            "inferred_product_type": "UL",
        } if wid == "ws-chat" else None,
    )
    monkeypatch.setattr(
        server, "load_workspace_executable_mechanics",
        lambda wid: _artifact(),
    )
    monkeypatch.setattr(
        server, "_load_workspace_slices",
        lambda wid: [_slice(NAR_STATEMENT, page=5, filename="specimen-base.pdf")],
    )
    monkeypatch.setattr(
        server, "_document_coverage",
        lambda artifact, slices: _coverage(),
    )
    return TestClient(server.app)


def test_chat_endpoint_scenario_proposal(chat_client: TestClient) -> None:
    resp = chat_client.post(
        "/api/workspaces/ws-chat/chat",
        json={"message": "What if the premium were $5,000 a year?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "scenario_change"
    assert body["intentLabel"] == "Scenario change"
    assert body["scenario_proposal"]["changes"][0]["field"] == "premium"


def test_chat_endpoint_absence(chat_client: TestClient) -> None:
    resp = chat_client.post(
        "/api/workspaces/ws-chat/chat",
        json={"message": "Does the filing allow policy loans?"},
    )
    assert resp.status_code == 200, resp.text
    assert "not in the documents" in resp.json()["answer"]


def test_chat_endpoint_unknown_workspace_404(chat_client: TestClient) -> None:
    resp = chat_client.post(
        "/api/workspaces/ws-nope/chat", json={"message": "hello"}
    )
    assert resp.status_code == 404
