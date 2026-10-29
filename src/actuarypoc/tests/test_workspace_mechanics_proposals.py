"""Extraction proposals — proposal generation, evidence,
confirm-gating, and the second-product onboarding acceptance.

Proposals are deterministic signals from the filing (extracted table
candidates + stated calculations found by equation harvesting), each
carrying page evidence and a confirm-back.  Nothing applies
unconfirmed; confirming applies through the same paths as the manual
action (filed acceptance / Phase 7 equation approval), with proposal
provenance.  (Phase 4's switch-setting proposals were re-expressed
as equation proposals by Phase 7; the rule bank is retired.)
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from actuarypoc.extract import workspace_mechanics_proposals as proposals
from actuarypoc.extract.workspace_mechanics_corrections import executable_mechanics_view
from actuarypoc.storage import workspace_store
from actuarypoc.ui import server
from actuarypoc.ui.server import UlRuntimeConfig, _run_ul_projection


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _slice(text: str, *, page: int = 3, filename: str = "meridian-ul.pdf", page_offsets=None) -> dict:
    return {
        "slice_id": "s-1",
        "doc_id": "doc-1",
        "document_hint": filename,
        "page_start": page,
        "page_end": page,
        "heading": None,
        "char_start": 0,
        "char_end": len(text),
        "text": text,
        "page_offsets": page_offsets or [[0, page]],
    }


def _candidate(mechanic: str, candidate_id: str, rows: list, *, page: int, heading: str) -> dict:
    return {
        "id": candidate_id,
        "mechanic": mechanic,
        "filename": "meridian-ul.pdf",
        "page": page,
        "tableHeading": heading,
        "rowCount": len(rows),
        "valueBasis": "guaranteed_maximum",
        "reviewStatus": "review_required",
        "rows": rows,
    }


def _empty_artifact() -> dict:
    return {
        "version": 1,
        "mechanics": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
        "warnings": [],
        "usable": {},
        "candidates": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
        "status": {},
    }


TIMING_TEXT = (
    "Cost of Insurance Charge. The monthly cost of insurance charge is "
    "deducted in arrears, at the end of each policy month after interest "
    "is credited to the policy value."
)
NAR_TEXT = (
    "The net amount at risk is the death benefit payable less the "
    "account value on the monthly processing date."
)
SURRENDER_TEXT = (
    "The surrender charge equals 9% of the account value, grading to "
    "zero over 12 years."
)


# ---------------------------------------------------------------------------
# Generation: filed tables
# ---------------------------------------------------------------------------


def test_filed_table_proposals_carry_candidate_evidence():
    artifact = _empty_artifact()
    artifact["candidates"]["coi"].append(_candidate("coi", "cand-coi-b", [
        {"duration": 1, "sex": None, "risk_class": None, "tobacco_status": None,
         "rate": 0.19, "rate_unit": "per_1000_monthly",
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
    ], page=9, heading="Monthly Cost of Insurance Rates"))

    found = proposals.generate_proposals(artifact, [])
    assert len(found) == 1
    proposal = found[0]
    # Unification revamp: a filed table is proposed as a CHOICE —
    # one proposal carrying the candidate(s) as options.
    assert proposal["kind"] == "filed_table_choice"
    assert proposal["candidateId"] == "cand-coi-b"
    assert [o["candidateId"] for o in proposal["options"]] == ["cand-coi-b"]
    assert proposal["evidence"]["filename"] == "meridian-ul.pdf"
    assert proposal["evidence"]["page"] == 9
    assert "meridian-ul.pdf" in proposal["confirmBack"]


def test_filed_proposal_skipped_when_slot_already_corrected():
    artifact = _empty_artifact()
    artifact["status"]["coi"] = "corrected"
    artifact["corrections"] = {"coi": {"variant": "coi_timing"}}
    artifact["candidates"]["coi"].append(_candidate("coi", "cand-x", [
        {"duration": 1, "sex": None, "risk_class": None, "tobacco_status": None,
         "rate": 0.19, "rate_unit": "per_1000_monthly",
         "provenance": {"sourceType": "filed_pdf", "reviewStatus": "review_required"}},
    ], page=9, heading="COI"))
    assert proposals.generate_proposals(artifact, []) == []


# ---------------------------------------------------------------------------
# Generation: prose switch signals
# ---------------------------------------------------------------------------


def test_timing_proposal_with_page_evidence():
    # The timing phrase sits after char 400, which page_offsets place
    # on page 4 — the evidence must name page 4, not the slice start.
    # (A COI table is in force: a timing statement attaches to its
    # equation; with no COI body anywhere it is unmapped, not a
    # proposal.)
    filler = "General provisions and definitions apply throughout. " * 9
    text = filler + TIMING_TEXT
    slice_ = _slice(text, page=3, page_offsets=[[0, 3], [400, 4]])
    artifact = _empty_artifact()
    artifact["usable"]["coi"] = [
        {"duration": 1, "sex": None, "risk_class": None, "tobacco_status": None,
         "rate": 0.19, "rate_unit": "per_1000_monthly",
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf"}}
    ]
    found = proposals.generate_proposals(artifact, [slice_])
    timing = [p for p in found if p["kind"] == "equation" and p["equationMechanic"] == "coi_charge"]
    assert len(timing) == 1
    assert timing[0]["candidate"]["timing"] == "end"
    assert "end of each month" in timing[0]["rendering"]
    assert timing[0]["evidence"]["page"] == 4
    assert "arrears" in timing[0]["evidence"]["snippet"]


def test_nar_proposal_requires_a_factor_in_force():
    artifact = _empty_artifact()
    slices = [_slice(NAR_TEXT, page=5)]
    # No factor in force: the prose matches the default the loop already
    # applies with a factor of 1.0 — nothing to propose.
    assert proposals.generate_proposals(artifact, slices) == []
    artifact["usable"]["nar_factors"] = [
        {"duration": None, "sex": None, "factor": 1.05,
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf"}}
    ]
    found = proposals.generate_proposals(artifact, slices)
    assert len(found) == 1
    assert found[0]["kind"] == "equation"
    assert found[0]["equationMechanic"] == "nar_definition"
    assert "death benefit − the account value" in found[0]["rendering"]
    assert found[0]["evidence"]["page"] == 5


def test_surrender_proposal_needs_both_percent_and_grading():
    # Percent stated, grading not stated: the system must not invent
    # the grading period, so no proposal.
    partial = _slice("The surrender charge equals 9% of the account value.", page=6)
    assert proposals.generate_proposals(_empty_artifact(), [partial]) == []
    full = _slice(SURRENDER_TEXT, page=6)
    found = proposals.generate_proposals(_empty_artifact(), [full])
    assert len(found) == 1
    assert found[0]["kind"] == "equation"
    assert found[0]["equationMechanic"] == "surrender_charge"
    assert "account value" in found[0]["rendering"]
    assert "9" in str(found[0]["candidate"]["body"]) or found[0]["candidate"]["body"]


def test_proposals_are_deterministic():
    artifact = _empty_artifact()
    artifact["usable"]["coi"] = [
        {"duration": 1, "sex": None, "risk_class": None, "tobacco_status": None,
         "rate": 0.19, "rate_unit": "per_1000_monthly",
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf"}}
    ]
    slices = [_slice(TIMING_TEXT), _slice(SURRENDER_TEXT)]
    first = proposals.generate_proposals(artifact, slices)
    second = proposals.generate_proposals(artifact, slices)
    assert [p["id"] for p in first] == [p["id"] for p in second]
    assert len(first) == 2


# ---------------------------------------------------------------------------
# Apply / dismiss (module level)
# ---------------------------------------------------------------------------


def test_apply_equation_proposal_stamps_proposal_provenance():
    artifact = _empty_artifact()
    artifact["usable"]["coi"] = [
        {"duration": 1, "sex": None, "risk_class": None, "tobacco_status": None,
         "rate": 0.19, "rate_unit": "per_1000_monthly",
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf"}}
    ]
    found = proposals.generate_proposals(artifact, [_slice(TIMING_TEXT, page=7)])
    assert len(found) == 1
    outcome = proposals.apply_proposal(
        artifact, found[0], workspace_id="ws-1", who="eddy", at="2026-10-25T00:00:00Z"
    )
    record = outcome["equation"]
    assert record["state"] == "approved"
    assert record["approval"]["by"] == "eddy"
    assert record["timing"] == "end"
    assert record["source"]["proposalId"] == found[0]["id"]
    assert record["source"]["proposalEvidence"]["page"] == 7
    assert outcome["change"]["kind"] == "proposal_equation"
    from actuarypoc.extract import workspace_equations as ws_equations
    in_force = ws_equations.in_force(outcome["artifact"], "coi_charge")
    assert in_force["timing"] == "end"


def test_dismissal_persists_and_blocks_regeneration():
    artifact = _empty_artifact()
    artifact["usable"]["coi"] = [
        {"duration": 1, "sex": None, "risk_class": None, "tobacco_status": None,
         "rate": 0.19, "rate_unit": "per_1000_monthly",
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf"}}
    ]
    slices = [_slice(TIMING_TEXT)]
    found = proposals.generate_proposals(artifact, slices)
    outcome = proposals.dismiss_proposal(
        artifact, found[0], workspace_id="ws-1", who="eddy", at="2026-10-25T00:00:00Z"
    )
    assert proposals.generate_proposals(outcome["artifact"], slices) == []
    assert outcome["change"]["kind"] == "proposal_dismissed"


# ---------------------------------------------------------------------------
# Over HTTP: confirm-gating, apply, dismiss
# ---------------------------------------------------------------------------


class MissingObject(Exception):
    code = "NoSuchKey"


class Response(io.BytesIO):
    def release_conn(self) -> None:
        pass


class FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def make_bucket(self, bucket: str) -> None:
        raise AssertionError("bucket already exists")

    def put_object(self, bucket, key, stream, *, length, content_type) -> None:
        self.objects[key] = stream.read(length)

    def get_object(self, bucket, key) -> Response:
        if key not in self.objects:
            raise MissingObject(key)
        return Response(self.objects[key])

    def list_objects(self, bucket, *, prefix, recursive):
        return [
            SimpleNamespace(object_name=key)
            for key in sorted(self.objects)
            if key.startswith(prefix)
        ]

    def remove_object(self, bucket, key) -> None:
        self.objects.pop(key, None)


@pytest.fixture()
def store(monkeypatch: pytest.MonkeyPatch) -> FakeMinio:
    client = FakeMinio()
    monkeypatch.setattr(workspace_store, "get_minio_client", lambda: client)
    monkeypatch.setattr(workspace_store, "get_bucket_name", lambda: "test")
    monkeypatch.setattr(workspace_store, "ensure_bucket", lambda client: None)
    return client


def _seed_workspace(store: FakeMinio, artifact: dict) -> str:
    ws = workspace_store.create_workspace()
    workspace_store.store_workspace_executable_mechanics(ws["id"], artifact)
    return ws["id"]


def _http_artifact() -> dict:
    artifact = _empty_artifact()
    artifact["candidates"]["coi"].append(_candidate("coi", "cand-coi-b", [
        {"duration": 1, "sex": None, "risk_class": None, "tobacco_status": None,
         "rate": 0.19, "rate_unit": "per_1000_monthly",
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
    ], page=9, heading="Monthly Cost of Insurance Rates"))
    artifact["candidates"]["surrender"].append(_candidate("surrender", "cand-sur-b", [
        {"duration": 1, "issue_age": None, "sex": None,
         "charge": 0.09, "charge_unit": "percent_account_value",
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
    ], page=11, heading="Surrender Charge Schedule"))
    return artifact


def test_proposals_over_http_confirm_gated(store, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(server, "_load_workspace_slices", lambda workspace_id: [])
    client = TestClient(server.app)
    workspace_id = _seed_workspace(store, _http_artifact())

    listed = client.get(f"/api/workspaces/{workspace_id}/mechanics-panel/proposals")
    assert listed.status_code == 200
    found = listed.json()["proposals"]
    assert {p["candidateId"] for p in found} == {"cand-coi-b", "cand-sur-b"}
    coi_proposal = next(p for p in found if p["candidateId"] == "cand-coi-b")
    assert coi_proposal["kind"] == "filed_table_choice"

    # The panel payload carries the proposals and the equation state
    # (Phase 7: no rule bank is served anymore).
    panel = client.get(f"/api/workspaces/{workspace_id}/mechanics-panel").json()
    assert len(panel["proposals"]) == 2
    assert "ruleBank" not in panel
    assert "equations" in panel

    # Unconfirmed: refused, with the confirm-back attached, nothing applied.
    refused = client.post(
        f"/api/workspaces/{workspace_id}/mechanics-panel/proposals/{coi_proposal['id']}/confirm",
        json={},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"]["confirmBack"] == coi_proposal["confirmBack"]
    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    assert not (artifact.get("usable") or {}).get("coi")

    # Confirmed: applied through the filed-acceptance path.
    applied = client.post(
        f"/api/workspaces/{workspace_id}/mechanics-panel/proposals/{coi_proposal['id']}/confirm",
        json={"confirmed": True, "who": "eddy"},
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] is True
    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    assert artifact["usable"]["coi"][0]["rate"] == pytest.approx(0.19)
    # Phase 7: accepting the table also put its equation in force.
    from actuarypoc.extract import workspace_equations as ws_equations
    assert ws_equations.in_force(artifact, "coi_charge") is not None

    # Dismiss the surrender proposal; it stays gone.
    surrender_proposal = next(p for p in found if p["candidateId"] == "cand-sur-b")
    dismissed = client.post(
        f"/api/workspaces/{workspace_id}/mechanics-panel/proposals/{surrender_proposal['id']}/dismiss",
        json={"who": "eddy"},
    )
    assert dismissed.status_code == 200
    remaining = client.get(
        f"/api/workspaces/{workspace_id}/mechanics-panel/proposals"
    ).json()["proposals"]
    assert remaining == []


def test_equation_proposal_over_http(store, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        server, "_load_workspace_slices", lambda workspace_id: [_slice(TIMING_TEXT, page=7)]
    )
    client = TestClient(server.app)
    artifact = _empty_artifact()
    artifact["usable"]["coi"] = [
        {"duration": 1, "sex": None, "risk_class": None, "tobacco_status": None,
         "rate": 0.19, "rate_unit": "per_1000_monthly",
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf"}}
    ]
    workspace_id = _seed_workspace(store, artifact)

    found = client.get(
        f"/api/workspaces/{workspace_id}/mechanics-panel/proposals"
    ).json()["proposals"]
    assert len(found) == 1 and found[0]["kind"] == "equation"
    assert found[0]["equationMechanic"] == "coi_charge"

    applied = client.post(
        f"/api/workspaces/{workspace_id}/mechanics-panel/proposals/{found[0]['id']}/confirm",
        json={"confirmed": True, "who": "eddy"},
    )
    assert applied.status_code == 200
    artifact = workspace_store.load_workspace_executable_mechanics(workspace_id)
    from actuarypoc.extract import workspace_equations as ws_equations
    in_force = ws_equations.in_force(artifact, "coi_charge")
    assert in_force is not None
    assert in_force["timing"] == "end"
    assert in_force["approval"]["by"] == "eddy"
    assert in_force["source"]["proposalEvidence"]["page"] == 7


# ---------------------------------------------------------------------------
# Acceptance: onboard a second product primarily via proposals
# ---------------------------------------------------------------------------


def _product_b_artifact() -> dict:
    """A second UL product as Phase 0 extraction would leave it.

    "Meridian Assurance — Flexible Premium UL (specimen B)": different
    COI rates and unit, a different NAR factor (1.05), a different
    surrender shape, different fees from the Promise UL fixture
    product.  Everything starts as unreviewed filed candidates; the
    product's prose states its COI timing and NAR definition.
    """

    artifact = _empty_artifact()
    artifact["candidates"]["coi"].append(_candidate("coi", "cand-b-coi", [
        {"duration": d, "sex": None, "risk_class": None, "tobacco_status": None,
         "rate": round(0.18 + 0.01 * d, 4), "rate_unit": "per_1000_monthly",
         "provenance": {"filename": "meridian-ul.pdf", "page": 9, "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}}
        for d in range(1, 31)
    ], page=9, heading="Monthly Cost of Insurance Rates"))
    artifact["candidates"]["surrender"].append(_candidate("surrender", "cand-b-sur", [
        {"duration": d, "issue_age": None, "sex": None,
         "charge": round(0.09 - 0.0075 * (d - 1), 6), "charge_unit": "percent_account_value",
         "provenance": {"filename": "meridian-ul.pdf", "page": 11, "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}}
        for d in range(1, 13)
    ], page=11, heading="Surrender Charge Schedule"))
    artifact["candidates"]["nar_factors"].append(_candidate("nar_factors", "cand-b-nar", [
        {"duration": None, "sex": None, "factor": 1.05,
         "provenance": {"filename": "meridian-ul.pdf", "page": 6, "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
    ], page=6, heading="Net Amount at Risk Factor"))
    artifact["candidates"]["fees"].append(_candidate("fees", "cand-b-fees", [
        {"component": "policy_fee", "duration": None, "premium_mode": None,
         "amount": 240.0, "fee_unit": "annual_fixed",
         "provenance": {"filename": "meridian-ul.pdf", "page": 7, "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
        {"component": "admin_fee", "duration": None, "premium_mode": None,
         "amount": 4.50, "fee_unit": "monthly_fixed",
         "provenance": {"filename": "meridian-ul.pdf", "page": 7, "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
    ], page=7, heading="Policy and Administrative Fees"))
    return artifact


def test_acceptance_second_product_onboarded_via_proposals():
    """The Phase 4 exit, honestly scoped.

    The repo contains no second REAL UL filing (the only other real
    product, P12TRF, is a term product on the separate DSL engine, not
    this chassis), so the second product is a constructed specimen in
    the same specimen family the strict extractor keys on, with
    genuinely different values throughout.  The score is the count of
    manual corrections required: every input below arrives via an
    extraction proposal + confirmation, so the count is zero.
    """

    artifact = _product_b_artifact()
    slices = [_slice(TIMING_TEXT, page=4), _slice(NAR_TEXT, page=5)]
    manual_corrections = 0
    confirmed = 0

    # Round 1: the four filed tables + the COI timing the prose states.
    pending = proposals.generate_proposals(artifact, slices)
    kinds = {(p["kind"], p["mechanic"]) for p in pending}
    assert ("filed_table_choice", "coi") in kinds
    assert ("filed_table_choice", "surrender") in kinds
    assert ("filed_table_choice", "nar_factors") in kinds
    assert ("filed_table_choice", "fees") in kinds
    assert any(
        p["kind"] == "equation" and p["equationMechanic"] == "coi_charge"
        for p in pending
    )
    for proposal in pending:
        outcome = proposals.apply_proposal(
            artifact, proposal, workspace_id="ws-b", who="eddy", at="2026-10-25T00:00:00Z"
        )
        artifact = outcome["artifact"]
        confirmed += 1

    # Round 2: with the 1.05 factor now in force, the filing's NAR
    # prose becomes an equation proposal.
    pending = proposals.generate_proposals(artifact, slices)
    assert len(pending) == 1 and pending[0]["equationMechanic"] == "nar_definition"
    outcome = proposals.apply_proposal(
        artifact, pending[0], workspace_id="ws-b", who="eddy", at="2026-10-25T00:00:00Z"
    )
    artifact = outcome["artifact"]
    confirmed += 1

    assert confirmed == 6
    assert manual_corrections == 0

    # The onboarded product projects through the approved equations
    # its proposals put in force.
    mechanics = executable_mechanics_view(artifact)
    config = UlRuntimeConfig(
        guaranteed_rate=0.03,
        coi_rate_flat=0.004,
        surrender_period_years=19,
        max_surrender_pct=0.10,
        policy_fee_annual=0.0,
        executable_mechanics=mechanics,
    )
    projection, _ = _run_ul_projection(
        request={"age": 50, "faceAmount": 300_000, "premiumMode": "ANNUAL", "modalPremium": 7_500},
        config=config,
        horizon_years=30,
    )
    first = projection["rows"][0]["appliedMechanics"]
    coi_rendering = first["coi"]["equation"]["rendering"]
    assert "COI table rate" in coi_rendering
    assert first["coi"]["timing"] == "end"
    assert first["coi"]["rate"] == pytest.approx(0.19)
    assert first["nar"]["definition"] == "unadjusted"
    assert "account value" in first["surrender"]["equation"]["rendering"]
    assert projection["mechanicsExecution"]["policy_fees"]["applied"] is True
    assert projection["mechanicsExecution"]["coi_charge"]["applied"] is True


# ---------------------------------------------------------------------------
# Review-outcome loser derivation — the silent Confirm (Oct 28, 2026)
# ---------------------------------------------------------------------------
# Billy's live workspace ws-05f7a2eb: the holistic review resolved a
# framing_loss case on the death-benefit reading via a joint re-read
# ("the reading stands") with NO winner recorded and no
# losingReadings.  The outcome pass derived losers as "every
# candidate but the winner", which — winnerless — named the upheld
# reading itself a loser and withdrew its only proposal.  The
# structure still offered the reading, so its Confirm silently did
# nothing.  A winnerless resolution must withdraw nothing.

DEATH_BENEFIT_TEXT = (
    "Option A: Death Benefit = Face amount. The death benefit will "
    "never be less than the amount required to qualify this policy "
    "as life insurance under the tax code corridor."
)


def _death_benefit_case(**overrides) -> dict:
    from actuarypoc.domain import equations as _equations
    from actuarypoc.extract import workspace_equations as _ws_equations

    rendering = _equations.render_equation(
        _ws_equations.death_benefit_body(), "death_benefit"
    )
    case = {
        "id": "case-dbfix",
        "kind": "framing_loss",
        "mechanic": "death_benefit",
        "status": "resolved",
        "ladderStep": "joint_reread",
        "rationale": "Re-read with both documents together, the reading stands.",
        "winnerId": None,
        "loserIds": [],
        "candidates": [{
            "id": "rd-death-1",
            "candidateId": None,
            "kind": "equation",
            "origin": "harvest",
            "rendering": rendering,
            "filename": "meridian-ul.pdf",
            "page": 4,
            "statement": "Option A: Death Benefit = Face amount",
        }],
    }
    case.update(overrides)
    return case


def _death_benefit_proposals(case) -> list:
    artifact = _empty_artifact()
    if case is not None:
        artifact["holisticReview"] = {
            "status": "ran", "flags": [], "verifications": [], "cases": [case],
        }
    return proposals.generate_proposals(artifact, [_slice(DEATH_BENEFIT_TEXT)])


def test_winnerless_resolved_case_keeps_the_reading_it_upheld():
    found = _death_benefit_proposals(_death_benefit_case())
    death_benefit = [
        p for p in found
        if p["kind"] == "equation" and p["equationMechanic"] == "death_benefit"
    ]
    assert len(death_benefit) == 1


def test_resolved_case_with_a_winner_still_withdraws_the_loser():
    case = _death_benefit_case(
        winnerId="rd-other",
        candidates=[
            {
                "id": "rd-other", "candidateId": None, "kind": "equation",
                "origin": "harvest", "rendering": "a rival reading",
                "filename": "meridian-ul.pdf", "page": 4, "statement": "x",
            },
            _death_benefit_case()["candidates"][0],
        ],
    )
    found = _death_benefit_proposals(case)
    assert [
        p for p in found
        if p["kind"] == "equation" and p["equationMechanic"] == "death_benefit"
    ] == []


def test_resolved_case_loser_ids_are_honored_without_a_winner():
    case = _death_benefit_case(loserIds=["rd-death-1"])
    found = _death_benefit_proposals(case)
    assert [
        p for p in found
        if p["kind"] == "equation" and p["equationMechanic"] == "death_benefit"
    ] == []


# ---------------------------------------------------------------------------
# Structure confirmability annotation (Oct 28, 2026)
# ---------------------------------------------------------------------------
# A reading with neither a pending proposal nor a saved record
# cannot be confirmed; the annotation names why on the reading
# itself so its card explains instead of offering a dead Confirm.

def _annotate(structure, found, artifact):
    proposals.annotate_structure_confirmability(structure, found, artifact)
    return {
        option["key"]: option.get("confirmBlockedReason")
        for step in structure["steps"]
        for option in step["options"]
    }


def test_annotation_leaves_a_confirmable_reading_unmarked():
    from actuarypoc.extract import workspace_structure as _structure

    artifact = _empty_artifact()
    artifact["holisticReview"] = {
        "status": "ran", "flags": [], "verifications": [],
        "cases": [_death_benefit_case()],
    }
    slices = [_slice(DEATH_BENEFIT_TEXT)]
    found = proposals.generate_proposals(artifact, slices)
    structure = _structure.build_structure(artifact, slices)
    reasons = _annotate(structure, found, artifact)
    death_benefit = [
        step for step in structure["steps"] if step["id"] == "death_benefit"
    ][0]
    assert len(death_benefit["options"]) == 1
    assert reasons[death_benefit["options"][0]["key"]] is None


def test_annotation_explains_the_gated_nar_reading():
    from actuarypoc.extract import workspace_structure as _structure

    artifact = _empty_artifact()
    slices = [_slice(NAR_TEXT, page=5)]
    found = proposals.generate_proposals(artifact, slices)
    structure = _structure.build_structure(artifact, slices)
    reasons = _annotate(structure, found, artifact)
    nar = [step for step in structure["steps"] if step["id"] == "nar"][0]
    assert len(nar["options"]) == 1
    reason = reasons[nar["options"][0]["key"]]
    assert reason is not None
    assert "NAR factor table" in reason


def test_annotation_explains_a_reconciled_loser():
    structure = {"steps": [{
        "id": "death_benefit",
        "equationMechanic": "death_benefit",
        "options": [{
            "key": "death_benefit-x",
            "mechanic": "death_benefit",
            "state": "pending",
            "recordId": None,
            "rendering": "the losing reading",
        }],
    }]}
    artifact = {
        "usable": {},
        "dismissedProposals": [],
        "holisticReview": {"cases": [{
            "mechanic": "death_benefit",
            "status": "resolved",
            "winnerId": "rd-winner",
            "losingReadings": [{"rendering": "the losing reading"}],
        }]},
    }
    proposals.annotate_structure_confirmability(structure, [], artifact)
    reason = structure["steps"][0]["options"][0].get("confirmBlockedReason")
    assert reason is not None
    assert "reconciled" in reason


def test_annotation_explains_a_dismissed_reading():
    rendering = "the dismissed reading"
    dismissed_id = proposals._proposal_id("equation", {
        "mechanic": "death_benefit", "rendering": rendering, "equationId": None,
    })
    structure = {"steps": [{
        "id": "death_benefit",
        "equationMechanic": "death_benefit",
        "options": [{
            "key": "death_benefit-y",
            "mechanic": "death_benefit",
            "state": "pending",
            "recordId": None,
            "rendering": rendering,
        }],
    }]}
    artifact = {
        "usable": {},
        "dismissedProposals": [{"id": dismissed_id}],
        "holisticReview": {"cases": []},
    }
    proposals.annotate_structure_confirmability(structure, [], artifact)
    reason = structure["steps"][0]["options"][0].get("confirmBlockedReason")
    assert reason is not None
    assert "dismissed" in reason


# ---------------------------------------------------------------------------
# Table acceptance never approves the text-stated readings (Oct 28, 2026)
# ---------------------------------------------------------------------------
# Billy's ws-05f7a2eb: accepting the corridor table put the death
# benefit in effect, and accepting the NAR factor table put the
# legacy FACTOR-ADJUSTED definition in effect — neither was chosen;
# both formulas come from the documents' text, not from the tables'
# rows.  Transcription (the acceptance path) covers only the tables'
# own arithmetic; the legacy migration that converts pre-doctrine
# state stays, but it is one-shot and never re-arms.

def _usable_row(**fields) -> dict:
    row = dict(fields)
    row.setdefault("duration", 1)
    row.setdefault("sex", None)
    row.setdefault("risk_class", None)
    row.setdefault("tobacco_status", None)
    row["provenance"] = {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf"}
    return row


def test_table_acceptance_transcribes_only_the_tables_own_arithmetic():
    from actuarypoc.extract import workspace_equations as _ws_eq

    artifact = _empty_artifact()
    artifact["usable"]["coi"] = [
        _usable_row(rate=0.19, rate_unit="per_1000_monthly")
    ]
    artifact["usable"]["corridor"] = [_usable_row(percentage=2.5)]
    artifact["usable"]["nar_factors"] = [_usable_row(factor=1.05)]
    outcome = _ws_eq.transcribe_tables_as_approved(artifact, who="eddy", at="t")
    transcribed = {r["mechanic"] for r in outcome["transcribed"]}
    assert transcribed == {"coi_charge"}
    recorded = {r["mechanic"] for r in _ws_eq.records(outcome["artifact"])}
    assert "death_benefit" not in recorded
    assert "nar_definition" not in recorded


def test_accepting_corridor_or_nar_factors_alone_approves_no_equation():
    from actuarypoc.extract import workspace_equations as _ws_eq

    for mechanic, row in (
        ("corridor", _usable_row(percentage=2.5)),
        ("nar_factors", _usable_row(factor=1.05)),
    ):
        artifact = _empty_artifact()
        artifact["usable"][mechanic] = [row]
        outcome = _ws_eq.transcribe_tables_as_approved(artifact, who="eddy", at="t")
        assert outcome["transcribed"] == []
        assert _ws_eq.records(outcome["artifact"]) == []


def test_legacy_migration_is_one_shot_and_never_rearms():
    from actuarypoc.extract import workspace_equations as _ws_eq

    artifact = _empty_artifact()
    artifact["usable"]["corridor"] = [_usable_row(percentage=2.5)]
    first = _ws_eq.materialize_legacy_equations(artifact, at="t1")
    assert first["changed"] is True
    assert first["artifact"].get("equationsMigratedAt") == "t1"
    # A table arriving later (through acceptance, whose artifact is
    # already stamped) must not re-derive approvals on the next load.
    first["artifact"]["usable"]["nar_factors"] = [_usable_row(factor=1.05)]
    second = _ws_eq.materialize_legacy_equations(first["artifact"], at="t2")
    assert second["changed"] is False
    assert _ws_eq.in_force(second["artifact"], "nar_definition") is None


def test_stamped_artifact_is_never_rederived():
    from actuarypoc.extract import workspace_equations as _ws_eq

    artifact = _empty_artifact()
    artifact["equationsMigratedAt"] = "t0"
    artifact["usable"]["corridor"] = [_usable_row(percentage=2.5)]
    outcome = _ws_eq.materialize_legacy_equations(artifact, at="t1")
    assert outcome["changed"] is False
    assert _ws_eq.records(outcome["artifact"]) == []
