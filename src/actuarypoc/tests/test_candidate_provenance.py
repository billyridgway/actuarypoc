"""Candidate provenance — an approval must show its evidence.

Oct 27, 2026 (Billy, verified live that morning): three of the
eight filed-table candidates on a Promise UL workspace were
presented for approval with NO source evidence — the proposal said
"from the filing", the panel payload carried filename=None /
page=None, and the change history recorded "(evidence: None)" for
their accepts.  The three shapes are the tables filed IDENTICALLY
in both specimen documents (surrender schedule, the 1-row
administrative charge, the NAR factor): construction merged each
pair of identical extractions into one candidate and nulled its
filename/page, keeping the documents only on ``sources`` — a field
no consumer read.  The rows always knew their document and page.

Contracts pinned here:

* a merged candidate's proposal, confirm-back, panel views, and
  accept change record show the real document + page + heading;
* construction no longer nulls a merged candidate's filename/page;
* a candidate with no provenance anywhere says "source not
  recorded" plainly in every surface — the string "None" never
  appears as evidence, and neither does the vague "the filing".
"""

from __future__ import annotations

import pytest

from actuarypoc.extract import workspace_mechanics_proposals as proposals
from actuarypoc.extract.workspace_mechanics_panel import (
    _candidate_views,
    _pending_candidate_views,
)
from actuarypoc.extract.workspace_ul_mechanics import candidate_provenance
from actuarypoc.ui import server


BASE = "ICC18 S18PRUL.pdf"
NICOTINE = "ICC18 S18PRUL Nicotine.pdf"


def _empty_artifact() -> dict:
    return {
        "version": 1,
        "mechanics": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
        "warnings": [],
        "usable": {},
        "candidates": {"coi": [], "surrender": [], "fees": [], "nar_factors": [], "corridor": []},
        "status": {},
    }


def _merged_candidate(mechanic: str, candidate_id: str, rows: list, *,
                      heading: str, page: int) -> dict:
    """A candidate exactly as pre-fix construction stored it: the
    identical table filed in both specimen PDFs, merged into one
    candidate whose filename/page were nulled, with the documents
    kept only on ``sources`` and on each row's provenance."""

    sources = [
        {"filename": BASE, "page": page, "tableHeading": heading},
        {"filename": NICOTINE, "page": page, "tableHeading": heading},
    ]
    stamped = []
    for row in rows:
        row = dict(row)
        row["provenance"] = {
            "filename": BASE, "page": page, "tableHeading": heading,
            "sourceType": "filed_pdf", "reviewStatus": "review_required",
            "valueBasis": "guaranteed_maximum",
            "supportingSources": sources,
        }
        stamped.append(row)
    return {
        "id": candidate_id,
        "mechanic": mechanic,
        "filename": None,
        "page": None,
        "tableHeading": heading,
        "rowCount": len(stamped),
        "valueBasis": "guaranteed_maximum",
        "reviewStatus": "review_required",
        "sourceCount": 2,
        "sources": sources,
        "rows": stamped,
    }


def _surrender_candidate() -> dict:
    rows = [
        {"duration": d, "issue_age": None, "sex": None,
         "charge": 0.09 - 0.005 * (d - 1), "charge_unit": "percent_face"}
        for d in range(1, 4)
    ]
    return _merged_candidate(
        "surrender", "cand-surrender", rows,
        heading="Surrender Charge Rates", page=3,
    )


def _fees_admin_candidate() -> dict:
    rows = [{"component": "administrative", "duration": None,
             "premium_mode": None, "amount": 8.0, "fee_unit": "monthly_fixed"}]
    return _merged_candidate(
        "fees", "cand-fees-admin", rows,
        heading="Administrative Charge Per Month", page=2,
    )


def _nar_candidate() -> dict:
    rows = [{"duration": None, "factor": 1.0016516}]
    return _merged_candidate(
        "nar_factors", "cand-nar", rows,
        heading="Net Amount at Risk Factor", page=2,
    )


# ---------------------------------------------------------------------------
# The helper: candidate fields, then sources, then rows
# ---------------------------------------------------------------------------


def test_candidate_provenance_reads_sources_when_fields_nulled():
    view = candidate_provenance(_surrender_candidate())
    assert view["filename"] == BASE
    assert view["page"] == 3
    assert view["tableHeading"] == "Surrender Charge Rates"
    assert [s["filename"] for s in view["sources"]] == [BASE, NICOTINE]


def test_candidate_provenance_reads_rows_when_no_sources_list():
    candidate = _surrender_candidate()
    del candidate["sources"]
    view = candidate_provenance(candidate)
    assert view["filename"] == BASE
    assert view["page"] == 3
    assert view["sources"]


def test_candidate_provenance_empty_when_nothing_recorded():
    view = candidate_provenance({"id": "x", "rows": [{"duration": 1}]})
    assert view["filename"] is None
    assert view["page"] is None
    assert view["tableHeading"] is None
    assert view["sources"] == []


# ---------------------------------------------------------------------------
# Proposals + panel: the three previously-vague shapes show evidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "make,mechanic,heading,page",
    [
        (_surrender_candidate, "surrender", "Surrender Charge Rates", 3),
        (_fees_admin_candidate, "fees", "Administrative Charge Per Month", 2),
        (_nar_candidate, "nar_factors", "Net Amount at Risk Factor", 2),
    ],
)
def test_merged_candidate_proposal_shows_real_evidence(make, mechanic, heading, page):
    artifact = _empty_artifact()
    artifact["candidates"][mechanic].append(make())

    found = proposals.generate_proposals(artifact, [])
    assert len(found) == 1
    proposal = found[0]
    assert proposal["evidence"]["filename"] == BASE
    assert proposal["evidence"]["page"] == page
    assert proposal["evidence"]["heading"] == heading
    assert len(proposal["evidence"]["sources"]) == 2
    assert BASE in proposal["label"]
    assert f"(p. {page})" in proposal["label"]
    assert BASE in proposal["confirmBack"]
    assert f"p. {page}" in proposal["confirmBack"]
    assert "the filing" not in proposal["label"]
    assert "None" not in proposal["label"]
    assert "None" not in proposal["confirmBack"]
    option = proposal["options"][0]
    assert option["filename"] == BASE
    assert option["page"] == page
    assert len(option["sources"]) == 2


@pytest.mark.parametrize(
    "make,mechanic,page",
    [
        (_surrender_candidate, "surrender", 3),
        (_fees_admin_candidate, "fees", 2),
        (_nar_candidate, "nar_factors", 2),
    ],
)
def test_merged_candidate_panel_views_show_real_source(make, mechanic, page):
    artifact = _empty_artifact()
    artifact["candidates"][mechanic].append(make())

    for views in (
        _candidate_views(artifact, mechanic),
        _pending_candidate_views(artifact, mechanic),
    ):
        assert len(views) == 1
        assert views[0]["filename"] == BASE
        assert views[0]["page"] == page
        assert len(views[0]["sources"]) == 2


def test_accept_of_merged_candidate_records_real_evidence():
    artifact = _empty_artifact()
    artifact["candidates"]["surrender"].append(_surrender_candidate())
    proposal = proposals.generate_proposals(artifact, [])[0]

    outcome = proposals.apply_proposal(
        artifact, proposal, workspace_id="ws-prov", who="billy",
        at="2026-10-27T15:00:00Z",
    )
    summary = outcome["change"]["summary"]
    assert f"(evidence: {BASE}, p. 3)" in summary
    assert "(evidence: None)" not in summary
    assert "the filing" not in summary
    assert outcome["artifact"]["usable"]["surrender"]


# ---------------------------------------------------------------------------
# No provenance anywhere: "source not recorded", said plainly
# ---------------------------------------------------------------------------


def _unrecorded_candidate() -> dict:
    return {
        "id": "cand-unrecorded",
        "mechanic": "surrender",
        "filename": None,
        "page": None,
        "tableHeading": "Surrender Charge Rates",
        "rowCount": 1,
        "valueBasis": "guaranteed_maximum",
        "reviewStatus": "review_required",
        "rows": [{
            "duration": 1, "issue_age": None, "sex": None,
            "charge": 0.09, "charge_unit": "percent_face",
            "provenance": {"sourceType": "filed_pdf",
                           "reviewStatus": "review_required"},
        }],
    }


def test_unrecorded_candidate_says_source_not_recorded_everywhere():
    artifact = _empty_artifact()
    artifact["candidates"]["surrender"].append(_unrecorded_candidate())

    proposal = proposals.generate_proposals(artifact, [])[0]
    assert proposal["evidence"]["filename"] is None
    assert "source not recorded" in proposal["label"]
    assert "source not recorded" in proposal["confirmBack"]
    assert "the filing" not in proposal["label"]
    assert "None" not in proposal["label"]
    assert "None" not in proposal["confirmBack"]

    views = _candidate_views(artifact, "surrender")
    assert views[0]["filename"] is None
    assert views[0]["sources"] == []

    outcome = proposals.apply_proposal(
        artifact, proposal, workspace_id="ws-prov", who="billy",
        at="2026-10-27T15:00:00Z",
    )
    summary = outcome["change"]["summary"]
    assert "(evidence: source not recorded)" in summary
    assert "(evidence: None)" not in summary


def test_evidence_summary_never_renders_none():
    assert proposals._evidence_summary({"filename": "a.pdf", "page": 5}) == "(evidence: a.pdf, p. 5)"
    assert proposals._evidence_summary({"filename": "a.pdf", "page": None}) == "(evidence: a.pdf)"
    assert proposals._evidence_summary({"filename": None, "page": None}) == "(evidence: source not recorded)"
    assert proposals._evidence_summary({}) == "(evidence: source not recorded)"
    assert proposals._evidence_summary(None) == "(evidence: source not recorded)"


# ---------------------------------------------------------------------------
# Construction: identical tables in two documents keep a real source
# ---------------------------------------------------------------------------


def test_construction_keeps_filename_for_identical_tables(monkeypatch):
    class Response:
        def read(self) -> bytes: return b"filed PDF bytes"
        def close(self) -> None: pass
        def release_conn(self) -> None: pass

    class Client:
        def get_object(self, bucket: str, object_path: str) -> Response: return Response()

    def extracted(filename: str, content: bytes) -> dict:
        row = {
            "duration": 1, "issue_age": None, "sex": None,
            "charge": 0.09, "charge_unit": "percent_face",
            "provenance": {
                "filename": filename, "page": 3,
                "tableHeading": "Surrender Charge Rates",
                "reviewStatus": "review_required", "sourceType": "filed_pdf",
                "valueBasis": "guaranteed_maximum",
            },
        }
        return {"version": 2, "mechanics": {
            "coi": [], "surrender": [row], "fees": [],
            "nar_factors": [], "corridor": [],
        }, "warnings": []}

    monkeypatch.setattr(server, "get_minio_client", lambda: Client())
    monkeypatch.setattr(server, "ensure_bucket", lambda client: None)
    monkeypatch.setattr(server, "get_bucket_name", lambda: "workspace-bucket")
    monkeypatch.setattr(server, "extract_ul_mechanics", extracted)

    artifact = server._extract_workspace_executable_mechanics([
        {"description": BASE, "object_path": "documents/base.pdf"},
        {"description": NICOTINE, "object_path": "documents/nicotine.pdf"},
    ])

    candidates = artifact["candidates"]["surrender"]
    assert len(candidates) == 1
    candidate = candidates[0]
    # The merged candidate names the document its rows came from —
    # not None — and keeps every filing of the table on sources.
    assert candidate["filename"] == BASE
    assert candidate["page"] == 3
    assert candidate["sourceCount"] == 2
    assert {s["filename"] for s in candidate["sources"]} == {BASE, NICOTINE}
