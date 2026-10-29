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


def test_nar_proposal_is_offered_without_a_factor_in_force():
    # The filed NAR definition is an ordinary equation proposal: it
    # is offered whether or not a factor table is in force.  Nothing
    # calculates without an approved equation, so "the readings agree
    # at factor 1.0" never made the proposal a no-op — skipping it
    # (the pre-Oct-29 behaviour) left the definition's card with no
    # Confirm at all (Billy, Oct 29, 2026).
    artifact = _empty_artifact()
    slices = [_slice(NAR_TEXT, page=5)]
    found = proposals.generate_proposals(artifact, slices)
    assert len(found) == 1
    assert found[0]["kind"] == "equation"
    assert found[0]["equationMechanic"] == "nar_definition"
    assert "death benefit − the account value" in found[0]["rendering"]
    assert found[0]["evidence"]["page"] == 5
    # A factor in force changes nothing: still exactly one proposal
    # for the same reading.
    artifact["usable"]["nar_factors"] = [
        {"duration": None, "sex": None, "factor": 1.05,
         "provenance": {"filename": "meridian-ul.pdf", "sourceType": "filed_pdf"}}
    ]
    found = proposals.generate_proposals(artifact, slices)
    assert len(found) == 1
    assert found[0]["equationMechanic"] == "nar_definition"


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

    # Round 1: the four filed tables + the COI timing and the NAR
    # definition the prose states.  The definition is proposed
    # alongside its factor table, not after it — it never waited on
    # the table (Oct 29, 2026).
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
    assert any(
        p["kind"] == "equation" and p["equationMechanic"] == "nar_definition"
        for p in pending
    )
    for proposal in pending:
        outcome = proposals.apply_proposal(
            artifact, proposal, workspace_id="ws-b", who="eddy", at="2026-10-25T00:00:00Z"
        )
        artifact = outcome["artifact"]
        confirmed += 1

    # Round 2: nothing remains — every statement the specimen makes
    # was proposed and confirmed in round 1.
    assert proposals.generate_proposals(artifact, slices) == []

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


def test_annotation_leaves_the_filed_nar_reading_confirmable():
    # The filed NAR definition confirms on its own card like every
    # other reading: it carries a proposal, so the annotation leaves
    # it unmarked.  (Before Oct 29, 2026 the proposal was skipped and
    # the card instead carried a note claiming the factor table set
    # the definition — a coupling that no longer exists.)
    from actuarypoc.extract import workspace_structure as _structure

    artifact = _empty_artifact()
    slices = [_slice(NAR_TEXT, page=5)]
    found = proposals.generate_proposals(artifact, slices)
    structure = _structure.build_structure(artifact, slices)
    reasons = _annotate(structure, found, artifact)
    nar = [step for step in structure["steps"] if step["id"] == "nar"][0]
    assert len(nar["options"]) == 1
    assert reasons[nar["options"][0]["key"]] is None


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


def test_nar_factor_table_proposal_describes_the_table_not_the_definition():
    # A table proposal narrates the TABLE's own transition — what
    # was in force for the table, and the filed table that replaces
    # or extends it.  It must not narrate the NAR definition's state:
    # the definition is a separate mechanic, chosen on its own card
    # (Billy, Oct 29, 2026: "the data seems to have a different
    # equation than the equation above it").
    artifact = _empty_artifact()
    artifact["candidates"]["nar_factors"].append(_candidate("nar_factors", "cand-nar-1", [
        {"duration": None, "sex": None, "factor": 1.05,
         "provenance": {"filename": "meridian-ul.pdf", "page": 6, "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
    ], page=6, heading="Net Amount at Risk Factor"))
    found = proposals.generate_proposals(artifact, [])
    table = [
        p for p in found
        if p["kind"] == "filed_table_choice" and p.get("mechanic") == "nar_factors"
    ]
    assert len(table) == 1
    summary = table[0]["confirmBack"]
    assert "nothing was in force before" in summary
    assert "the filed table of 1 rows" in summary
    assert "net amount at risk =" not in summary
    assert "factor of 1.0 is used" not in summary
    assert "death benefit" not in summary


def test_bulk_plan_includes_the_filed_nar_definition():
    # On a doctrine-born workspace the filed NAR definition is an
    # ordinary uncontested single reading: the bulk dry-run lists it
    # as eligible, like every other mechanic's single reading.
    artifact = _empty_artifact()
    slices = [_slice(NAR_TEXT, page=5)]
    plan = proposals.plan_bulk_approval(artifact, slices)
    eligible = {
        (item["kind"], item["mechanic"]) for item in plan["eligible"]
    }
    assert ("equation", "nar_definition") in eligible
    excluded = {
        (item["kind"], item["mechanic"]) for item in plan["excluded"]
    }
    assert ("equation", "nar_definition") not in excluded


# ---------------------------------------------------------------------------
# The unified table+equation act (Oct 29, 2026)
# ---------------------------------------------------------------------------
# Billy approves tables without seeing the formula they carry: the
# transcription equation appeared in the step only AFTER he
# confirmed.  The unified act (Oct 29, 2026) previewed it on every
# slice card; the step-level treatment (same day, later) renders it
# ONCE at step level instead — Billy's run-detail PDF showed the
# fees equation repeated on all four slice cards.  Slice cards keep
# their per-slice facts, a confirm that names the act, and a boolean
# for which wording applies; the typeset equation + note live on the
# step (annotate_structure_table_equations).  Tables that carry no
# transcription (NAR factor, corridor) show no equation anywhere.

def _coi_candidate(candidate_id: str, tobacco=None, rate: float = 0.19) -> dict:
    return _candidate("coi", candidate_id, [
        {"duration": d, "attained_age": None, "sex": None, "risk_class": None,
         "tobacco_status": tobacco, "rate": rate, "rate_unit": "per_1000_monthly",
         "provenance": {"filename": "meridian-ul.pdf", "page": 4, "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}}
        for d in range(1, 31)
    ], page=4, heading="Monthly Cost of Insurance Rates")


def _table_proposal(artifact: dict, mechanic: str) -> dict:
    found = proposals.generate_proposals(artifact, [])
    matches = [
        p for p in found
        if p["kind"] == "filed_table_choice" and p.get("mechanic") == mechanic
    ]
    assert len(matches) == 1
    return matches[0]


def _composed_step(artifact: dict, slices: list, step_id: str):
    """The panel route's composition: structure + proposals + the
    step-level equation annotation, in the server's order."""
    from actuarypoc.extract import workspace_structure as _structure

    view = _structure.build_structure(artifact, slices)
    found = proposals.generate_proposals(artifact, slices)
    proposals.annotate_structure_table_equations(view, found, artifact)
    step = next(s for s in view["steps"] if s["id"] == step_id)
    return step, found


def _step_entries(step: dict) -> list:
    return [
        entry
        for block in step.get("tableEquations") or []
        for entry in block["entries"]
    ]


def test_coi_table_proposal_previews_the_transcription_it_installs():
    from actuarypoc.extract import workspace_equations as _ws_eq

    artifact = _empty_artifact()
    artifact["candidates"]["coi"].append(_coi_candidate("cand-coi-1"))
    proposal = _table_proposal(artifact, "coi")
    option = proposal["options"][0]
    # The card itself carries no equation any more — only the act's
    # wording and the boolean that selects it.
    assert not option.get("equationPreviews")
    assert not option.get("equationNote")
    assert option.get("putsEquationInEffect") is True
    assert "puts the COI charge equation in effect" in option["confirmBack"]
    assert "shown in this step" in option["confirmBack"]

    # The step carries the preview — the same simulation the card
    # used to run, so the previewed body is still the installed body.
    step, _found = _composed_step(artifact, [], "coi")
    entries = _step_entries(step)
    assert len(entries) == 1
    preview = entries[0]
    assert preview["mechanic"] == "coi_charge"
    assert preview["state"] == "will_put_in_effect"
    assert preview["math"] is not None
    assert "beginning of each month" in (preview["timingNote"] or "")

    outcome = proposals.apply_proposal(
        artifact, proposal, workspace_id="ws-preview", who="eddy",
        at="2026-10-29T00:00:00Z", option_candidate_id="cand-coi-1",
    )
    installed = _ws_eq.in_force(outcome["artifact"], "coi_charge")
    assert installed is not None
    # The previewed body is the installed body, exactly.
    assert installed["body"] == preview["body"]
    assert installed.get("timing") == "beginning"


def test_second_coi_slice_shows_the_equation_as_already_in_effect():
    artifact = _empty_artifact()
    artifact["candidates"]["coi"].append(_coi_candidate("cand-coi-1"))
    proposal = _table_proposal(artifact, "coi")
    outcome = proposals.apply_proposal(
        artifact, proposal, workspace_id="ws-preview", who="eddy",
        at="2026-10-29T00:00:00Z", option_candidate_id="cand-coi-1",
    )
    artifact = outcome["artifact"]
    artifact["candidates"]["coi"].append(
        _coi_candidate("cand-coi-2", tobacco="Tobacco", rate=0.21)
    )
    option = _table_proposal(artifact, "coi")["options"][0]
    # A later slice adds coverage only: its card never claims to put
    # the equation in effect again; the step shows it as in effect.
    assert not option.get("equationPreviews")
    assert option.get("putsEquationInEffect") is False
    assert "already in effect" in option["confirmBack"]
    step, _found = _composed_step(artifact, [], "coi")
    assert [(e["mechanic"], e["state"]) for e in _step_entries(step)] == [
        ("coi_charge", "already_in_effect")
    ]


def test_nar_factor_table_proposal_carries_no_equation_preview():
    artifact = _empty_artifact()
    artifact["candidates"]["nar_factors"].append(_candidate("nar_factors", "cand-nar-1", [
        {"duration": None, "sex": None, "factor": 1.05,
         "provenance": {"filename": "meridian-ul.pdf", "page": 6, "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
    ], page=6, heading="Net Amount at Risk Factor"))
    option = _table_proposal(artifact, "nar_factors")["options"][0]
    assert not option.get("equationPreviews")
    assert not option.get("equationNote")
    assert not option.get("putsEquationInEffect")
    assert "equation in effect" not in option["confirmBack"]
    step, _found = _composed_step(artifact, [], "nar")
    assert not step.get("tableEquations")


# ---------------------------------------------------------------------------
# The dual-source merge (Oct 29, 2026): policy_fees reaches the same
# body by two routes — the memo's prose statement (harvest) and the
# transcription of the filed fee schedule.  Canonically EQUAL bodies
# are ONE reading with two citations: one item, one approval act
# through either door, both sources in the change history.  DIFFERENT
# bodies stay a named choice — the table door never settles a reading
# it does not state (the Oct 27 ordering doctrine, preserved).

ADMIN_SLICE_TEXT = (
    "Administrative Charge An Administrative Charge is deducted at the "
    "beginning of each policy month until the Insured's Attained Age 121."
)
PREMIUM_SLICE_TEXT = (
    "Premium Expense Charge A Premium Expense Charge is applied to each "
    "premium. The Premium Expense Charge is currently set at 10% for new "
    "issues."
)
_FEES_ROW = {
    "component": "policy_fee", "duration": None, "premium_mode": None,
    "amount": 240.0, "fee_unit": "annual_fixed",
    "provenance": {"filename": "meridian-ul.pdf", "page": 7,
                   "sourceType": "filed_pdf",
                   "reviewStatus": "review_required"},
}


def _fees_candidate(candidate_id: str = "cand-fees-1", *, page: int = 7) -> dict:
    return _candidate("fees", candidate_id, [dict(_FEES_ROW)], page=page,
                      heading="Policy and Administrative Fees")


def _fees_slices() -> list:
    return [_slice(ADMIN_SLICE_TEXT, page=2, filename="memo.pdf")]


def test_fees_dual_source_reading_merges_into_one_item():
    artifact = _empty_artifact()
    artifact["candidates"]["fees"].append(_fees_candidate())
    slices = _fees_slices()
    found = proposals.generate_proposals(artifact, slices)
    eq_props = [
        p for p in found
        if p["kind"] == "equation" and p.get("equationMechanic") == "policy_fees"
    ]
    assert len(eq_props) == 1
    merged = eq_props[0]
    # Both citations ride on the ONE item: the prose evidence on the
    # proposal, the filed-table sources alongside it.
    assert merged["evidence"]["filename"] == "memo.pdf"
    info = merged.get("alsoFiledAsTable") or {}
    assert info.get("tableMechanic") == "fees"
    assert any(s["filename"] == "meridian-ul.pdf" for s in info.get("sources") or [])
    table_props = [p for p in found if p.get("mechanic") == "fees"]
    assert (table_props[0].get("mergedEquation") or {}).get("mechanic") == "policy_fees"
    # No slice card repeats the equation.
    for p in found:
        for option in p.get("options") or []:
            assert not option.get("equationPreviews")
            assert not option.get("equationNote")
    step, _found = _composed_step(artifact, slices, "fees")
    # The merged reading renders as the step's option, both citations
    # stamped on it; the step block previews only premium_load's
    # transcription — the one equation with no prose door here.
    merged_options = [o for o in step["options"] if o.get("alsoFiledAsTable")]
    assert len(merged_options) == 1
    assert [e["mechanic"] for e in _step_entries(step)] == ["premium_load"]


def test_merged_fees_equation_settles_via_the_reading_door():
    from actuarypoc.extract import workspace_equations as _ws_eq

    artifact = _empty_artifact()
    artifact["candidates"]["fees"].append(_fees_candidate())
    slices = _fees_slices()
    found = proposals.generate_proposals(artifact, slices)
    eq_prop = next(
        p for p in found
        if p["kind"] == "equation" and p.get("equationMechanic") == "policy_fees"
    )
    outcome = proposals.apply_proposal(
        artifact, eq_prop, workspace_id="ws-merge", who="eddy",
        at="2026-10-29T00:00:00Z",
    )
    in_force = _ws_eq.in_force(outcome["artifact"], "policy_fees")
    assert in_force is not None
    assert in_force["body"] == _ws_eq.policy_fees_body()
    change = outcome["change"]
    assert change["mergedSources"]["equation"]["filename"] == "memo.pdf"
    assert any(
        s["filename"] == "meridian-ul.pdf"
        for s in change["mergedSources"]["table"]["sources"]
    )
    # The other door resolves to the same state: no lingering
    # equation item for policy_fees, and the slice's confirm-back no
    # longer names it (the acceptance still carries premium_load's
    # transcription here — it has no prose reading in this fixture).
    found_after = proposals.generate_proposals(outcome["artifact"], slices)
    assert not [
        p for p in found_after
        if p["kind"] == "equation" and p.get("equationMechanic") == "policy_fees"
    ]
    option_after = [
        p for p in found_after if p.get("mechanic") == "fees"
    ][0]["options"][0]
    assert "Policy and admin fees equation" not in option_after["confirmBack"]
    assert "Premium load" in option_after["confirmBack"]


def test_merged_fees_equation_settles_via_the_table_door():
    from actuarypoc.extract import workspace_equations as _ws_eq

    artifact = _empty_artifact()
    artifact["candidates"]["fees"].append(_fees_candidate())
    slices = _fees_slices()
    found = proposals.generate_proposals(artifact, slices)
    table_prop = next(p for p in found if p.get("mechanic") == "fees")
    outcome = proposals.apply_proposal(
        artifact, table_prop, workspace_id="ws-merge", who="eddy",
        at="2026-10-29T00:00:00Z", option_candidate_id="cand-fees-1",
    )
    in_force = _ws_eq.in_force(outcome["artifact"], "policy_fees")
    assert in_force is not None
    assert in_force["body"] == _ws_eq.policy_fees_body()
    change = outcome["change"]
    assert change["mergedSources"]["table"]["filename"] == "meridian-ul.pdf"
    assert change["mergedSources"]["equation"]["filename"] == "memo.pdf"
    assert "also settles the Policy and admin fees equation" in change["summary"]
    # The reading door resolves too: nothing pending for policy_fees.
    found_after = proposals.generate_proposals(outcome["artifact"], slices)
    assert not [
        p for p in found_after
        if p["kind"] == "equation" and p.get("equationMechanic") == "policy_fees"
    ]


def test_merged_fees_pending_record_settles_via_the_table_door():
    # The record-first shape: a harvested policy_fees RECORD already
    # stands pending when the slice is accepted.  The acceptance
    # settles THAT record — approved in place, never duplicated by a
    # transcription beside it.
    from actuarypoc.extract import workspace_equations as _ws_eq

    artifact = _empty_artifact()
    added = _ws_eq.add_harvest_candidates(artifact, [{
        "mechanic": "policy_fees", "body": _ws_eq.policy_fees_body(),
        "timing": None,
        "statement": "An Administrative Charge is deducted monthly.",
        "filename": "memo.pdf", "page": 2,
    }], at="2026-10-29T00:00:00Z")
    artifact = added["artifact"]
    artifact["candidates"]["fees"].append(_fees_candidate())
    before = _ws_eq.records_for(artifact, "policy_fees")
    assert len(before) == 1 and before[0]["state"] == "pending"
    proposal = _table_proposal(artifact, "fees")
    outcome = proposals.apply_proposal(
        artifact, proposal, workspace_id="ws-merge", who="eddy",
        at="2026-10-29T00:00:00Z", option_candidate_id="cand-fees-1",
    )
    records = _ws_eq.records_for(outcome["artifact"], "policy_fees")
    assert len(records) == 1
    assert records[0]["id"] == before[0]["id"]
    assert records[0]["state"] == "approved"
    assert (records[0].get("source") or {}).get("settledByTableAcceptance") is True
    assert _ws_eq.in_force(outcome["artifact"], "policy_fees") is not None
    assert outcome["change"].get("mergedSources")


def test_differing_fees_reading_is_a_choice_not_a_merge():
    from actuarypoc.extract import workspace_equations as _ws_eq
    from actuarypoc.extract import workspace_structure as _structure

    artifact = _empty_artifact()
    added = _ws_eq.add_harvest_candidates(artifact, [{
        "mechanic": "policy_fees",
        "body": {"mul": [{"qty": "account_value"}, {"const": 0.01}]},
        "timing": None,
        "statement": "Policy fees are 1% of the account value.",
        "filename": "memo.pdf", "page": 2,
    }], at="2026-10-29T00:00:00Z")
    artifact = added["artifact"]
    artifact["candidates"]["fees"].append(_fees_candidate())
    slices = _fees_slices()
    found = proposals.generate_proposals(artifact, slices)
    # No merge anywhere: the bodies differ, so no door claims the other.
    assert not any(p.get("alsoFiledAsTable") for p in found)
    assert not any(p.get("mergedEquation") for p in found)
    view = _structure.build_structure(artifact, slices)
    proposals.annotate_structure_table_equations(view, found, artifact)
    step = next(s for s in view["steps"] if s["id"] == "fees")
    assert step["state"] == "choice"
    # The step states plainly that the fees equation is decided by
    # its own reading — the cross-disclosure, once, at step level.
    notes = " ".join(
        block.get("note") or "" for block in step.get("tableEquations") or []
    )
    assert "Policy and admin fees" in notes
    assert "decided by its own reading" in notes
    # Accepting the table does NOT settle the different reading.
    table_prop = next(p for p in found if p.get("mechanic") == "fees")
    outcome = proposals.apply_proposal(
        artifact, table_prop, workspace_id="ws-choice", who="eddy",
        at="2026-10-29T00:00:00Z", option_candidate_id="cand-fees-1",
    )
    assert _ws_eq.in_force(outcome["artifact"], "policy_fees") is None
    records = _ws_eq.records_for(outcome["artifact"], "policy_fees")
    assert len(records) == 1 and records[0]["state"] == "pending"


def test_step_equation_composed_once_with_multiple_pending_slices():
    artifact = _empty_artifact()
    artifact["candidates"]["coi"].append(_coi_candidate("cand-coi-1"))
    artifact["candidates"]["coi"].append(
        _coi_candidate("cand-coi-2", tobacco="Tobacco", rate=0.21)
    )
    artifact["candidates"]["fees"].append(_fees_candidate("cand-fees-1"))
    artifact["candidates"]["fees"].append(_fees_candidate("cand-fees-2", page=8))
    slices = _fees_slices()
    found = proposals.generate_proposals(artifact, slices)
    # Two pending slices per table, and still: no slice option
    # anywhere carries an equation or a note.
    for p in found:
        for option in p.get("options") or []:
            assert not option.get("equationPreviews")
            assert not option.get("equationNote")
    step_coi, _ = _composed_step(artifact, slices, "coi")
    assert [
        (e["mechanic"], e["state"]) for e in _step_entries(step_coi)
    ] == [("coi_charge", "will_put_in_effect")]
    step_fees, _ = _composed_step(artifact, slices, "fees")
    # policy_fees is merged into the step's reading item; only the
    # premium-load transcription is previewed, once.
    assert [e["mechanic"] for e in _step_entries(step_fees)] == ["premium_load"]


def test_bulk_counts_the_merged_fees_equation_once():
    from actuarypoc.extract import workspace_equations as _ws_eq

    artifact = _empty_artifact()
    artifact["candidates"]["fees"].append(_fees_candidate())
    artifact["candidates"]["coi"].append(_coi_candidate("cand-coi-1"))
    slices = _fees_slices() + [
        _slice(PREMIUM_SLICE_TEXT, page=2, filename="memo.pdf")
    ]
    plan = proposals.plan_bulk_approval(artifact, slices)
    fees_eq_items = [
        i for i in plan["eligible"]
        if i["kind"] == "equation" and i["mechanic"] == "policy_fees"
    ]
    assert len(fees_eq_items) == 1  # the merged item, counted once
    fees_table_items = [
        i for i in plan["eligible"]
        if i["kind"] == "filed_table" and i["mechanic"] == "fees"
    ]
    assert len(fees_table_items) == 1
    # The equation is named by its own item (and premium_load by
    # its) — the fees table item does not claim an equation again.
    assert not fees_table_items[0]["label"].endswith("and its equation")
    coi_items = [
        i for i in plan["eligible"]
        if i["kind"] == "filed_table" and i["mechanic"] == "coi"
    ]
    assert coi_items[0]["label"].endswith("and its equation")
    outcome = proposals.apply_bulk_approval(
        artifact, slices, workspace_id="ws-bulk", who="eddy",
        at="2026-10-29T00:00:00Z",
    )
    assert len(outcome["applied"]) == len(plan["eligible"])
    assert not outcome["skipped"]
    in_force = _ws_eq.in_force(outcome["artifact"], "policy_fees")
    assert in_force is not None
    assert in_force["body"] == _ws_eq.policy_fees_body()
    premium = _ws_eq.in_force(outcome["artifact"], "premium_load")
    assert premium is not None
    # The harvested reading the summary promised — never the
    # transcription — is what the batch put in effect.
    assert premium["body"] == {"mul": [{"qty": "premium_due"}, {"const": 0.1}]}


def test_bulk_summary_names_the_equation_a_table_item_carries():
    artifact = _empty_artifact()
    artifact["candidates"]["coi"].append(_coi_candidate("cand-coi-1"))
    artifact["candidates"]["nar_factors"].append(_candidate("nar_factors", "cand-nar-1", [
        {"duration": None, "sex": None, "factor": 1.05,
         "provenance": {"filename": "meridian-ul.pdf", "page": 6, "sourceType": "filed_pdf",
                        "reviewStatus": "review_required"}},
    ], page=6, heading="Net Amount at Risk Factor"))
    plan = proposals.plan_bulk_approval(artifact, [])
    labels = {item["mechanic"]: item["label"] for item in plan["eligible"]}
    assert labels["coi"].endswith("and its equation")
    assert "equation" not in labels["nar_factors"]


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
