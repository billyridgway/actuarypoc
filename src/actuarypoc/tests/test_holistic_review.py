"""Holistic review pass (Oct 27, 2026).

Background self-checking inside the analysis job: harvested
suggestions are independently re-read under wider slicing,
divergences are reconciled by the ladder (deterministic rules ->
joint re-read -> bounded repair -> source standing -> uncalibrated
judgment with corroboration) or escalated as flags with quoted
evidence, flagged items are excluded from bulk approval by name,
the review reconciles the compliance header for what it found,
and its absence is stated plainly.  Nothing is ever auto-approved.
"""

from __future__ import annotations

import pytest

from actuarypoc.domain import equations as eq
from actuarypoc.extract import workspace_equations as ws_eq
from actuarypoc.extract import workspace_mechanics_proposals as proposals
from actuarypoc.extract.holistic_review import (
    InterimDecisionProvider,
    run_holistic_review,
)
from actuarypoc.extract.workspace_mechanics_panel import (
    filing_review_reconciliation,
)

from actuarypoc.tests.test_analysis_state_persistence import (
    _extracted_artifact,
)
from actuarypoc.tests.test_workspace_mechanics_proposals import (
    _candidate,
    _empty_artifact,
    _slice,
)

AT = "2026-10-27T21:00:00Z"

PREMIUM_10 = (
    "The Premium Expense Charge is currently set at 10% for new "
    "issues, applied to each premium."
)
PREMIUM_12 = (
    "The Premium Expense Charge is currently set at 12% for new "
    "issues, applied to each premium."
)
PREMIUM_15 = (
    "The Premium Expense Charge is currently set at 15% for new "
    "issues, applied to each premium."
)


def _run(artifact, slices, **kwargs):
    kwargs.setdefault("at", AT)
    kwargs.setdefault("judge", lambda context: None)
    return run_holistic_review(artifact, slices, **kwargs)


def _premium_cases(review):
    return [c for c in review["cases"] if c["mechanic"] == "premium_load"]


# ---------------------------------------------------------------------------
# Self-check: agreement attaches verification evidence
# ---------------------------------------------------------------------------


def test_agreement_attaches_verification_evidence():
    slices = [_slice(PREMIUM_10, page=2, filename="memo.pdf")]
    outcome = _run(_empty_artifact(), slices)
    review = outcome["review"]
    assert review["status"] == "ran"
    verified = [
        v for v in review["verifications"]
        if v["mechanic"] == "premium_load" and v["status"] == "verified"
    ]
    assert len(verified) == 1
    assert "independently re-read with wider context — identical" in verified[0]["evidence"]

    found = proposals.generate_proposals(outcome["artifact"], slices)
    premium = [p for p in found if p.get("equationMechanic") == "premium_load"]
    assert len(premium) == 1
    assert premium[0]["review"]["status"] == "verified"
    assert "independently re-read" in premium[0]["review"]["evidence"]
    assert "reviewFlag" not in premium[0]


def test_agreement_names_corroborating_document():
    slices = [
        _slice(PREMIUM_10, page=2, filename="memo.pdf"),
        _slice(PREMIUM_10, page=5, filename="spec.pdf"),
    ]
    outcome = _run(_empty_artifact(), slices)
    verified = [
        v for v in outcome["review"]["verifications"]
        if v["mechanic"] == "premium_load" and v["status"] == "verified"
    ]
    assert verified
    assert any("also stated in" in v["evidence"] for v in verified)


# ---------------------------------------------------------------------------
# Reconciliation ladder — deterministic rule
# ---------------------------------------------------------------------------


def test_divergence_reconciled_by_deterministic_arithmetic():
    artifact = _empty_artifact()
    artifact["candidates"]["fees"].append(_candidate("fees", "cand-fees", [
        {"duration": None, "component": "premium_expense", "amount": 10.0,
         "fee_unit": "percent_premium",
         "provenance": {"filename": "spec.pdf", "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
    ], page=5, heading="Policy and Administrative Charges"))
    slices = [
        _slice(PREMIUM_10, page=2, filename="memo.pdf"),
        _slice(PREMIUM_12, page=3, filename="spec.pdf"),
    ]
    outcome = _run(artifact, slices)
    cases = _premium_cases(outcome["review"])
    assert len(cases) == 1
    case = cases[0]
    assert case["status"] == "resolved"
    assert case["ladderStep"] == "deterministic_arithmetic"
    assert "filed fee table" in case["rationale"]
    assert case["losingReadings"]

    # ONE suggestion is presented, carrying the reconciliation.
    found = proposals.generate_proposals(outcome["artifact"], slices)
    premium = [p for p in found if p.get("equationMechanic") == "premium_load"]
    assert len(premium) == 1
    assert premium[0]["candidate"]["body"] == {
        "mul": [{"qty": "premium_due"}, {"const": 0.1}]
    }
    assert premium[0]["review"]["status"] == "reconciled"
    assert "deterministic_arithmetic" in premium[0]["review"]["note"]


def test_joint_reread_resolves_when_only_one_statement_is_in_the_text():
    # A pending model reading whose statement appears nowhere in the
    # filing vs the harvested reading whose statement is verbatim:
    # the joint re-read supports only the real one.
    artifact = _empty_artifact()
    artifact["equations"] = [ws_eq.new_record(
        mechanic="premium_load",
        body={"mul": [{"qty": "premium_due"}, {"const": 0.12}]},
        state="pending",
        source={"kind": "document",
                "statement": "The premium expense charge is 12% of each premium.",
                "filename": "model-notes.pdf", "page": 1},
        at=AT,
    )]
    slices = [_slice(PREMIUM_10, page=2, filename="memo.pdf")]
    outcome = _run(artifact, slices)
    cases = _premium_cases(outcome["review"])
    assert len(cases) == 1
    assert cases[0]["status"] == "resolved"
    assert cases[0]["ladderStep"] == "joint_reread"
    # The losing record is superseded — preserved, never deleted —
    # and the winner carries the reconciliation in its provenance.
    records = ws_eq.records(outcome["artifact"])
    assert len(records) == 1
    assert records[0]["state"] == "superseded"
    assert records[0]["source"]["reviewReconciliation"]["ladderStep"] == "joint_reread"


def test_judgment_resolves_only_with_agreement_and_corroboration():
    def agreeing_judge(context):
        for candidate in context["candidates"]:
            if candidate.get("statement") and "10%" in candidate["statement"]:
                return {"choice": candidate["id"], "rationale": "two filings state 10%"}
        return None

    slices = [
        _slice(PREMIUM_10, page=2, filename="memo-a.pdf"),
        _slice(PREMIUM_12, page=3, filename="memo-b.pdf"),
        _slice(PREMIUM_10, page=7, filename="memo-c.pdf"),
    ]
    outcome = _run(_empty_artifact(), slices, judge=agreeing_judge)
    cases = _premium_cases(outcome["review"])
    assert len(cases) == 1
    assert cases[0]["status"] == "resolved"
    assert cases[0]["ladderStep"] == "reasoned_judgment"


# ---------------------------------------------------------------------------
# Escalation — the ladder genuinely cannot settle it
# ---------------------------------------------------------------------------


def test_true_contradiction_escalates_with_evidence():
    slices = [
        _slice(PREMIUM_10, page=2, filename="memo-a.pdf"),
        _slice(PREMIUM_15, page=4, filename="memo-b.pdf"),
    ]
    outcome = _run(_empty_artifact(), slices)
    cases = _premium_cases(outcome["review"])
    assert len(cases) == 1
    case = cases[0]
    assert case["status"] == "escalated"
    assert case["verificationOutcome"] == "escalated_to_human"
    flags = outcome["review"]["flags"]
    assert len(flags) == 1
    flag = flags[0]
    assert flag["status"] == "unresolved"
    assert flag["mechanic"] == "premium_load"
    snippets = [str(e.get("snippet") or "") for e in flag["evidence"]]
    assert any("10%" in s for s in snippets)
    assert any("15%" in s for s in snippets)
    # Both rival suggestions carry the flag; nothing was approved.
    found = proposals.generate_proposals(outcome["artifact"], slices)
    premium = [p for p in found if p.get("equationMechanic") == "premium_load"]
    assert len(premium) == 2
    assert all("reviewFlag" in p for p in premium)
    assert ws_eq.in_force(outcome["artifact"], "premium_load") is None


def test_bulk_approve_excludes_the_flagged_item_by_name():
    artifact = _empty_artifact()
    artifact["candidates"]["fees"].append(_candidate("fees", "cand-fees", [
        {"duration": 1, "component": "policy_fee", "amount": 60.0,
         "fee_unit": "annual_fixed",
         "provenance": {"filename": "spec.pdf", "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
    ], page=5, heading="Policy and Administrative Charges"))
    slices = [
        _slice(PREMIUM_10, page=2, filename="memo-a.pdf"),
        _slice(PREMIUM_15, page=4, filename="memo-b.pdf"),
    ]
    outcome = _run(artifact, slices)
    plan = proposals.plan_bulk_approval(outcome["artifact"], slices)
    eligible_ids = {item["candidateId"] for item in plan["eligible"]}
    assert "cand-fees" in eligible_ids  # the rest still applies
    flagged = [
        item for item in plan["excluded"]
        if "holistic review flag" in item["reason"]
    ]
    assert len(flagged) == 2
    assert all(item["mechanic"] == "premium_load" for item in flagged)
    assert all(item["label"] for item in flagged)
    summary = proposals.bulk_summary(plan)
    assert any("holistic review flag" in e["reason"] for e in summary["excluded"])


# ---------------------------------------------------------------------------
# Repair round — a rival beside the original, never a replacement
# ---------------------------------------------------------------------------


def test_repair_round_produces_a_rival_not_a_replacement():
    slices = [
        # Cross-boundary statement: whole only when every document
        # is dispatched together (the repair unit).  Neither the
        # first pass nor the per-document re-read can see "18%".
        _slice("The Premium Expense Charge is currently set at 1",
               page=9, filename="memo-a.pdf"),
        _slice("8% for new issues, applied to each premium.",
               page=1, filename="memo-b.pdf"),
        _slice(PREMIUM_10, page=2, filename="memo-a.pdf"),
        _slice(PREMIUM_12, page=3, filename="memo-b.pdf"),
    ]
    outcome = _run(_empty_artifact(), slices)
    cases = _premium_cases(outcome["review"])
    assert len(cases) == 1
    case = cases[0]
    assert case["repairAttempted"] is True
    assert case["repairProducedRival"] is True
    assert case["status"] == "escalated"

    records = [
        r for r in ws_eq.records(outcome["artifact"])
        if (r.get("source") or {}).get("assist") == "holistic_review_repair"
    ]
    assert len(records) == 1
    rival = records[0]
    assert rival["state"] == "pending"  # a suggestion, never in force
    assert rival["body"] == {"mul": [{"qty": "premium_due"}, {"const": 0.18}]}
    # The originals are untouched: no record was edited or approved,
    # and both original readings are still offered as proposals.
    assert ws_eq.in_force(outcome["artifact"], "premium_load") is None
    found = proposals.generate_proposals(outcome["artifact"], slices)
    renderings = {
        p["rendering"] for p in found if p.get("equationMechanic") == "premium_load"
    }
    assert len(renderings) == 3  # 10%, 12%, and the repair rival 18%


# ---------------------------------------------------------------------------
# Stated absence
# ---------------------------------------------------------------------------


def test_stated_absence_when_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ACTUARYPOC_HOLISTIC_REVIEW", "off")
    outcome = _run(_empty_artifact(), [_slice(PREMIUM_10, filename="memo.pdf")])
    review = outcome["review"]
    assert review["status"] == "absent"
    assert "did not run" in review["statement"]
    assert "ACTUARYPOC_HOLISTIC_REVIEW" in review["reason"]
    assert review["flags"] == [] and review["cases"] == []


def test_stated_absence_when_backend_profile_too_small(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("ACTUARYPOC_HOLISTIC_REVIEW", raising=False)
    monkeypatch.setenv("ACTUARYPOC_BACKEND_PROFILE", "onprem_small")
    outcome = _run(_empty_artifact(), [_slice(PREMIUM_10, filename="memo.pdf")])
    assert outcome["review"]["status"] == "absent"
    assert "too small" in outcome["review"]["reason"]


# ---------------------------------------------------------------------------
# The review reconciles the compliance header
# ---------------------------------------------------------------------------


def _nar_snapshot() -> dict:
    return {
        "complianceMatrix": {
            "summary": {"implemented": 3, "partial": 0, "missing": 3,
                        "overallStatus": "red"},
            "requirements": [
                {"id": "coi_table", "name": "COI rate table",
                 "classification": {"implementationState": "not_implemented"},
                 "evidence": [{"id": "coi_rates"}]},
            ],
        },
        "gaps": {"items": [
            {"id": "missing_nar_equation",
             "title": "Net amount at risk equation missing",
             "status": "missing"},
        ]},
    }


# The NAR definition split across two slices: the first pass reads
# each slice alone and misses it; the wider re-read dispatches the
# document's slices together and finds it whole.
_NAR_SPLIT = [
    _slice(
        "The net amount at risk is the death benefit payable less "
        "the account",
        page=5, filename="spec.pdf",
    ),
    _slice(
        "value on the monthly processing date.",
        page=5, filename="spec.pdf",
    ),
]


def test_review_finds_missing_mechanic_and_header_names_it():
    outcome = _run(_empty_artifact(), _NAR_SPLIT)
    review = outcome["review"]
    assert len(review["found"]) == 1
    found_entry = review["found"][0]
    assert found_entry["mechanic"] == "nar_definition"
    assert found_entry["check"] == "self_check_reread"
    # The found reading is an ordinary pending suggestion.
    records = ws_eq.records_for(outcome["artifact"], "nar_definition")
    assert len(records) == 1 and records[0]["state"] == "pending"

    # BEFORE any approval, the header reconciliation names what the
    # review itself found — separately from anything in force.
    reconciliation = filing_review_reconciliation(
        _nar_snapshot(), outcome["artifact"]
    )
    assert reconciliation["resolvedRequirements"] == []
    assert reconciliation["reviewResolvedRequirements"] == []
    assert [g["id"] for g in reconciliation["reviewResolvedGaps"]] == [
        "missing_nar_equation"
    ]
    assert "found by the holistic review" in reconciliation["text"]
    # The honest boundary: the COI requirement the review did NOT
    # find stays missing — it is in neither reconciliation list.
    assert "COI rate table" not in reconciliation["text"]


def test_no_review_entries_when_the_review_finds_nothing_new():
    outcome = _run(
        _empty_artifact(), [_slice(PREMIUM_10, page=2, filename="memo.pdf")]
    )
    assert outcome["review"]["found"] == []
    reconciliation = filing_review_reconciliation(
        _nar_snapshot(), outcome["artifact"]
    )
    assert reconciliation["reviewResolvedRequirements"] == []
    assert reconciliation["reviewResolvedGaps"] == []
    assert reconciliation["text"] is None


# ---------------------------------------------------------------------------
# Filed tables — deterministic slice relations
# ---------------------------------------------------------------------------


def test_selector_disjoint_slices_reconcile_as_a_union():
    outcome = _run(_extracted_artifact(), [])
    review = outcome["review"]
    unions = [
        c for c in review["cases"]
        if c["ladderStep"] == "deterministic_selector_union"
    ]
    assert unions, review["cases"]
    assert all(c["status"] == "resolved" for c in unions)
    coi_verified = [
        v for v in review["verifications"]
        if v["targetKind"] == "filed_table" and v["mechanic"] == "coi"
    ]
    assert len(coi_verified) == 2
    assert not [
        f for f in review["flags"] if f["mechanic"] == "coi"
    ]


# ---------------------------------------------------------------------------
# Cross-product + decision interface shapes
# ---------------------------------------------------------------------------


def test_cross_product_suggestion_is_flagged():
    text = (
        "For the term life product, the premium expense charge is "
        "currently set at 10% for new issues, applied to each premium."
    )
    # The harvest pattern needs the charge named as in the filing;
    # use a statement that both harvests and names another product.
    text = (
        "The Premium Expense Charge is currently set at 10% for new "
        "issues, applied to each premium under the term life form."
    )
    snapshot = {"product": {"name": "Promise UL", "type": "UL"}}
    outcome = _run(
        _empty_artifact(), [_slice(text, page=2, filename="other-form.pdf")],
        snapshot=snapshot,
    )
    cross = [
        c for c in outcome["review"]["cases"]
        if c["kind"] == "cross_product_mention"
    ]
    assert len(cross) == 1
    assert cross[0]["status"] == "escalated"
    assert outcome["review"]["flags"]


def test_interim_provider_abstains_without_a_judge():
    provider = InterimDecisionProvider()
    assert provider.choose([{"id": "a"}], {"candidates": []}) is None
    assert provider.truth_probability("anything", {}) == 0.5
    assert isinstance(provider.score({"filename": "a.pdf"}, {"candidates": []}), float)


def test_nothing_is_ever_auto_approved():
    slices = [
        _slice(PREMIUM_10, page=2, filename="memo.pdf"),
        _slice(PREMIUM_12, page=3, filename="spec.pdf"),
    ]
    outcome = _run(_extracted_artifact(), slices)
    artifact = outcome["artifact"]
    assert not (artifact.get("usable") or {}).get("coi")
    for record in ws_eq.records(artifact):
        assert record["state"] != "approved" or record.get("approval")
    assert artifact["holisticReview"]["decisionLog"] == artifact["holisticReview"]["cases"]
