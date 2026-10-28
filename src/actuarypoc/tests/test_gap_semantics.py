"""Gap semantics (Billy, Oct 27, 2026): "missing" means missing FROM
THE DOCUMENTS.

A fresh workspace over a complete filing showed all seven mechanics
as open "equation missing" gaps purely because their equations were
not APPROVED yet — while the documents stated each mechanic, the
evidence was extracted, and the equation sat in the suggestions.
Three states are now separated:

1. covered by the documents (evidenced candidate held) — NOT a gap,
   whatever the approval state;
2. not in the documents — the genuine gap, worded as not stated /
   not covered by the documents;
3. stated but not extracted — OUR extraction gap, labeled distinctly.

(i) a document-covered workspace gets zero missing-equation gaps
    before any approvals (run-time missingMechanics is unchanged);
(ii) a mechanic with no candidate gets a not-covered gap;
(iii) a stated-but-not-extracted mechanic gets the extraction-gap
    wording;
(iv) the compliance summary's missing count excludes document-covered
    requirements — they carry the distinct "covered" state.
"""

from __future__ import annotations

from actuarypoc.domain import equations as eq
from actuarypoc.extract import workspace_equations as ws_eq
from actuarypoc.extract import workspace_mechanics_panel as panel
from actuarypoc.extract.workspace_mechanics_corrections import (
    executable_mechanics_view,
)
from actuarypoc.ui import server

from actuarypoc.tests.test_workspace_mechanics_proposals import _slice


AT = "2026-10-27T22:30:00Z"

PREMIUM_10 = (
    "The Premium Expense Charge is currently set at 10% for new "
    "issues, applied to each premium."
)


def _record(mechanic: str, *, state: str = "pending", body=None,
            filename: str = "filing.pdf", page: int = 2) -> dict:
    return ws_eq.new_record(
        mechanic=mechanic,
        body=body,
        state=state,
        source={
            "kind": "document",
            "statement": f"The filing states the {mechanic} calculation.",
            "filename": filename,
            "page": page,
        },
        at=AT,
    )


def _covered_artifact() -> dict:
    """Every mechanic holds an evidenced pending candidate, and the
    three table requirements hold filed candidates — the fresh
    Promise UL analysis shape, before any approvals."""

    return {
        "version": 1,
        "equations": [
            _record(mechanic, body={"const": 0}) for mechanic in eq.MECHANICS
        ],
        "candidates": {
            "coi": [{"id": "cand-coi", "rows": [{"duration": 1}]}],
            "surrender": [{"id": "cand-surr", "rows": [{"duration": 1}]}],
            "fees": [{"id": "cand-fees", "rows": [{"duration": 1}]}],
            "nar_factors": [],
            "corridor": [],
        },
        "usable": {},
    }


def _view(artifact: dict, coverage):
    request = {
        "_workspaceExecutableMechanics": executable_mechanics_view(artifact),
        "_documentCoverage": coverage,
    }
    return server._build_ul_projection_view("ICC18 P18PR UL", request)


def test_document_covered_mechanics_emit_no_missing_equation_gaps() -> None:
    artifact = _covered_artifact()
    coverage = panel.document_coverage(artifact, [])
    assert {
        mechanic: entry["state"]
        for mechanic, entry in coverage["equations"].items()
    } == {mechanic: "covered" for mechanic in eq.MECHANICS}

    projection, _mechanics, _warnings, _notes, gaps = _view(artifact, coverage)

    missing_equation_ids = {
        f"missing_{mechanic}_equation" for mechanic in eq.MECHANICS
    }
    assert not ({gap["id"] for gap in gaps} & missing_equation_ids)
    # Run-time truth is unchanged: the projection still names every
    # unapproved mechanic — that is about calculation, not documents.
    assert {m["mechanic"] for m in projection["missingMechanics"]} == set(
        eq.MECHANICS
    )
    assert all(
        m["reason"] == "no_approved_equation"
        for m in projection["missingMechanics"]
    )


def test_harvest_statement_covers_and_absence_does_not() -> None:
    slices = [_slice(PREMIUM_10, page=2, filename="memo.pdf")]
    coverage = ws_eq.equation_document_coverage({}, slices)
    assert coverage["premium_load"]["state"] == "covered"
    assert coverage["premium_load"]["filename"] == "memo.pdf"

    empty = ws_eq.equation_document_coverage({}, [])
    assert empty["premium_load"]["state"] == "absent"


def test_filed_tables_cover_their_equation_mechanics() -> None:
    """The fresh-analysis shape: no records, no prose candidates —
    only filed table candidates.  Accepting a filed table puts its
    transcription in force, so the table's mechanic is covered.
    premium_load (chassis percentage; the filed percentage is prose)
    and crediting (no governing table) are NOT table-covered."""

    artifact = {
        "version": 1,
        "equations": [],
        "candidates": {
            "coi": [{
                "id": "cand-coi", "filename": "specimen.pdf", "page": 4,
                "rows": [{"duration": 1, "rate": 0.19,
                          "rate_unit": "per_1000_monthly"}],
            }],
            "surrender": [{
                "id": "cand-surr", "filename": "specimen.pdf", "page": 3,
                "rows": [{"duration": 1, "charge": 10,
                          "charge_unit": "percent_face"}],
            }],
            "fees": [{
                "id": "cand-fees", "filename": "specimen.pdf", "page": 5,
                "rows": [{"duration": 1, "amount": 5}],
            }],
            "nar_factors": [{
                "id": "cand-nar", "filename": "specimen.pdf", "page": 8,
                "rows": [{"factor": 1.0}],
            }],
            "corridor": [{
                "id": "cand-corr", "filename": "specimen.pdf", "page": 6,
                "rows": [{"duration": 1, "percentage": 2.5}],
            }],
        },
        "usable": {},
    }
    coverage = ws_eq.equation_document_coverage(artifact, [])
    states = {m: e["state"] for m, e in coverage.items()}
    assert states == {
        "coi_charge": "covered",
        "surrender_charge": "covered",
        "policy_fees": "covered",
        "nar_definition": "covered",
        "death_benefit": "covered",
        "premium_load": "absent",
        "crediting": "absent",
    }

    _projection, _m, _w, _n, gaps = _view(
        artifact, panel.document_coverage(artifact, []))
    assert {gap["id"] for gap in gaps} == {
        "missing_premium_load_equation",
        "missing_crediting_equation",
    }
    assert all(
        gap["coverage"] == "not_in_documents" for gap in gaps
    )


def test_mechanic_without_candidate_gap_is_not_stated_in_documents() -> None:
    artifact = {"version": 1, "equations": [], "candidates": {}, "usable": {}}
    coverage = panel.document_coverage(artifact, [])
    assert coverage["equations"]["premium_load"]["state"] == "absent"

    _projection, _m, _w, _n, gaps = _view(artifact, coverage)
    by_id = {gap["id"]: gap for gap in gaps}
    gap = by_id["missing_premium_load_equation"]
    assert gap["title"] == "Premium load equation not stated in the documents"
    assert "do not state" in gap["whyItMatters"]
    assert gap["coverage"] == "not_in_documents"
    # The genuine gap keeps the remedy the uploads list exists for.
    assert gap["suggestedUploads"]


def test_stated_but_not_extracted_gap_is_an_extraction_gap() -> None:
    artifact = {
        "version": 1,
        "equations": [
            _record(
                "nar_definition",
                state="unmapped",
                body=None,
                filename="policy-form.pdf",
                page=9,
            )
        ],
        "candidates": {},
        "usable": {},
    }
    coverage = panel.document_coverage(artifact, [])
    assert coverage["equations"]["nar_definition"]["state"] == "stated"

    _projection, _m, _w, _n, gaps = _view(artifact, coverage)
    by_id = {gap["id"]: gap for gap in gaps}
    gap = by_id["missing_nar_equation"]
    assert gap["title"] == (
        "Net amount at risk equation stated in the documents but not extracted"
    )
    assert gap["coverage"] == "stated_not_extracted"
    assert "policy-form.pdf" in gap["whyItMatters"]
    # The document is already here; adding documents is not the remedy.
    assert gap["suggestedUploads"] == []


def _missing_requirement(req_id: str, name: str, evidence_id: str) -> dict:
    return {
        "id": req_id,
        "name": name,
        "status": "missing",
        "impact": "high",
        "classification": {"implementationState": "not_implemented"},
        "evidence": [{"id": evidence_id, "status": "missing"}],
    }


def test_compliance_missing_count_excludes_document_covered() -> None:
    snapshot = {
        "complianceMatrix": {
            "requirements": [
                _missing_requirement("coi_table", "COI rate table", "coi_rates"),
                _missing_requirement(
                    "surrender_schedule", "Surrender charge schedule",
                    "surrender_schedule",
                ),
                _missing_requirement(
                    "policy_admin_fees", "Policy / admin fees",
                    "policy_admin_fee",
                ),
                {
                    "id": "unslotted_requirement",
                    "name": "Something the documents do not cover",
                    "status": "missing",
                    "impact": "low",
                    "classification": {"implementationState": "not_implemented"},
                    "evidence": [],
                },
            ]
        },
        "readinessDashboard": {},
        "pmrReadiness": {"messages": []},
        "requirementsClassification": {
            "all": [
                {"id": "coi_table", "implementationState": "not_implemented"},
            ]
        },
    }
    coverage = panel.document_coverage(_covered_artifact(), [])
    panel.apply_document_coverage_to_requirements(snapshot, coverage)

    statuses = {
        r["id"]: r["status"]
        for r in snapshot["complianceMatrix"]["requirements"]
    }
    assert statuses == {
        "coi_table": "covered",
        "surrender_schedule": "covered",
        "policy_admin_fees": "covered",
        "unslotted_requirement": "missing",
    }
    classified = snapshot["requirementsClassification"]["all"][0]
    assert classified["implementationState"] == "covered"

    server._reconcile_workspace_readiness(snapshot)
    summary = snapshot["complianceMatrix"]["summary"]
    assert summary["missing"] == 1
    assert summary["covered"] == 3
    assert snapshot["pmrReadiness"]["messages"][-1] == (
        "Compliance summary: implemented=0, partial=0, covered=3, "
        "missing=1, overall status=yellow."
    )


def test_reconciliation_names_covered_requirement_now_in_force() -> None:
    snapshot = {
        "complianceMatrix": {
            "requirements": [
                {
                    "id": "coi_table",
                    "name": "COI rate table",
                    "status": "covered",
                    "classification": {"implementationState": "covered"},
                    "evidence": [{"id": "coi_rates"}],
                }
            ],
            "summary": {
                "implemented": 3, "partial": 0, "covered": 1,
                "missing": 0, "overallStatus": "yellow",
            },
        },
        "gaps": {"items": []},
    }
    artifact = {
        "usable": {"coi": [{"duration": 1}]},
        "equations": [
            _record("coi_charge", state="approved", body={"const": 0})
        ],
    }
    result = panel.filing_review_reconciliation(snapshot, artifact)
    assert result["coveredAtAnalysis"] == 1
    assert result["text"] == (
        "1 covered at analysis — now in force: COI rate table"
    )
