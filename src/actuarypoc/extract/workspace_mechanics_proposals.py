"""Extraction proposals — Phase 4, re-expressed by Phase 7.

From a workspace's extracted mechanics and Phase 0 document slices,
the system PROPOSES slot values and equations, each with page
evidence, for the actuary to confirm in the panel.  A proposal is the
confirm-back pattern applied to extraction: the proposal restates
what it would put in force in actuarial language, and nothing
applies until the user confirms — confirming applies it through the
exact same paths as a manual action (a filed-candidate acceptance,
or the Phase 7 equation approval), with the proposal's evidence
recorded in the applied record's provenance.

Signals are DETERMINISTIC FIRST:

* filed table candidates extracted from the documents (headings,
  schedule shapes) become "accept this filed table" proposals
  (confirming one also puts the table's equation transcription in
  force, as a manual acceptance does);
* stated calculations found by equation harvesting — a COI
  deduction timing phrase, a net-amount-at-risk definition, a
  surrender percentage with its grading period — become EQUATION
  proposals: confirming one approves the equation (the Phase 7
  harvest candidates, plus any pending harvested records already on
  the artifact).

A configured model may additionally propose at AUTHORING time, but a
proposal is data, not authority: whatever its origin, the actuary
confirms before anything applies.  The projection path never sees
proposals — only confirmed mechanics and approved equations.

Dismissals persist on the artifact (``dismissedProposals``) so a
dismissed proposal does not regenerate.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional

from actuarypoc.domain import equations as _eq
from actuarypoc.extract import workspace_equations as _ws_equations
from actuarypoc.extract import workspace_mechanics_corrections as _corrections
from actuarypoc.extract.workspace_mechanics_panel import (
    SLOT_BY_ID,
    _change_record,
    _slot_status,
    _summarize_rows,
)
from actuarypoc.extract.workspace_ul_mechanics import (
    accept_filed_mechanic,
    candidate_diff,
    candidate_effective_rows,
    candidate_provenance,
    candidate_selector_summary,
    conflicting_row_selectors,
    rows_coverage_text,
)


#: How a missing source is stated, everywhere a proposal, a card, or
#: a change record names where a table or equation came from.  A
#: missing value must be said plainly — never rendered as "None"
#: and never dressed up as a vague "the filing".
SOURCE_NOT_RECORDED = "source not recorded"


def _from_phrase(filename: Optional[str]) -> str:
    """Sentence fragment naming a table's source: "from FILE", or
    the plain statement that no source was recorded."""

    return f"from {filename}" if filename else f"({SOURCE_NOT_RECORDED})"


def _was_clause(description: str) -> str:
    """The "before" clause of a table confirm-back.

    ``describe_current`` reports an empty slot's state as "nothing is
    in force"; embedded in a summary that reads "was nothing is in
    force".  State the empty case plainly instead — the was/now
    information stays, the grammar goes (Billy, Oct 27, 2026).
    """

    if description == "nothing is in force":
        return "nothing was in force before"
    return f"was {description}"


def _evidence_summary(evidence: Optional[Dict[str, Any]]) -> str:
    """The change-history evidence parenthetical for a proposal:
    "(evidence: FILE, p. N)" — or, when no source was recorded,
    "(evidence: source not recorded)".  Never "(evidence: None)"."""

    evidence = evidence or {}
    filename = evidence.get("filename")
    if not filename:
        return f"(evidence: {SOURCE_NOT_RECORDED})"
    text = f"(evidence: {filename}"
    if evidence.get("page"):
        text += f", p. {evidence['page']}"
    return text + ")"


PROPOSAL_KIND_FILED_TABLE = "filed_table"
#: Filed-table proposals are one per pending candidate (see
#: _filed_table_proposals); the kind name is kept from the revamp.
PROPOSAL_KIND_FILED_TABLE_CHOICE = "filed_table_choice"
PROPOSAL_KIND_EQUATION = "equation"
# Retired by Phase 7 (kept as a name so old payloads stay readable):
PROPOSAL_KIND_SWITCH = "switch_setting"

_EQUATION_SLOT_BY_MECHANIC: Dict[str, str] = {
    "coi_charge": "coi",
    "surrender_charge": "surrender",
    "premium_load": "fees",
    "policy_fees": "fees",
    "nar_definition": "nar",
    "death_benefit": "corridor",
    "crediting": "crediting",
}

_MECHANIC_SLOTS: Dict[str, Dict[str, Any]] = {
    str(slot.get("mechanic")): slot for slot in SLOT_BY_ID.values() if slot.get("mechanic")
}


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------


def _page_at(slice_: Dict[str, Any], offset: int) -> Optional[int]:
    page = slice_.get("page_start")
    for rel, pg in slice_.get("page_offsets") or []:
        if offset >= int(rel):
            page = int(pg)
        else:
            break
    return page


def _evidence(slice_: Dict[str, Any], start: int, end: int) -> Dict[str, Any]:
    text = str(slice_.get("text") or "")
    snippet_start = max(0, start - 80)
    snippet_end = min(len(text), end + 80)
    snippet = " ".join(text[snippet_start:snippet_end].split())
    return {
        "filename": slice_.get("document_hint"),
        "page": _page_at(slice_, start),
        "heading": slice_.get("heading"),
        "snippet": snippet,
    }


def _proposal_id(kind: str, payload: Dict[str, Any]) -> str:
    canonical = json.dumps({"kind": kind, **payload}, sort_keys=True, default=str)
    return "prop-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Proposal generation — filed table candidates
# ---------------------------------------------------------------------------


def _filed_table_proposals(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One proposal per PENDING filed candidate — slices, not versions.

    Candidates are selector slices of one table (Oct 27, 2026 model
    correction): the base specimen's Non-Tobacco COI rows and the
    Nicotine specimen's Tobacco rows are complementary coverage, so
    each pending candidate is proposed on its own and accepting one
    never displaces another — the table in force is the union.  The
    unification revamp's one-choice-per-group shape survives only
    where a choice is genuinely required: a pending candidate that
    prices a selector differently from a candidate already in force
    is proposed as a conflict choice between the version in force
    and the challenger, over exactly the rows where they disagree.
    """

    proposals: List[Dict[str, Any]] = []
    candidates_by_mechanic = artifact.get("candidates") or {}
    for mechanic, candidates in candidates_by_mechanic.items():
        slot = _MECHANIC_SLOTS.get(str(mechanic))
        if slot is None:
            continue
        if _slot_status(artifact, str(mechanic)) == "corrected":
            # A correction is the actuary's own statement of how this
            # mechanic works; proposing a filed table over it would
            # fight the correction.
            continue
        usable_ids = {
            str((row.get("provenance") or {}).get("candidateId"))
            for row in (artifact.get("usable") or {}).get(mechanic) or []
        }
        accepted = [
            candidate
            for candidate in candidates or []
            if isinstance(candidate, dict)
            and candidate.get("reviewStatus") == "accepted"
        ]
        was = _corrections.describe_current(artifact, slot)
        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("id") or "")
            if not candidate_id or candidate.get("reviewStatus") != "review_required":
                continue
            if candidate_id in usable_ids:
                continue
            # Provenance comes from the candidate as a whole — its
            # own fields, the sources its identical table was filed
            # under, and its rows — so a candidate merged from
            # several documents still shows the real document, page,
            # and heading its rows carry (Oct 27, 2026: the merged
            # surrender / administrative-fee / NAR-factor candidates
            # were proposed with no evidence at all).
            source = candidate_provenance(candidate)
            rows = list(candidate.get("rows") or [])
            evidence = {
                "filename": source["filename"],
                "page": source["page"],
                "heading": candidate.get("tableHeading") or source["tableHeading"],
                "sources": source["sources"],
                "snippet": (
                    f"{candidate.get('rowCount')} rows extracted"
                    + (f" under “{candidate.get('tableHeading')}”" if candidate.get("tableHeading") else "")
                    + (f" ({candidate.get('valueBasis')})" if candidate.get("valueBasis") else "")
                ),
            }
            option = {
                "candidateId": candidate_id,
                "filename": evidence["filename"],
                "page": evidence["page"],
                "tableHeading": candidate.get("tableHeading"),
                "sources": source["sources"],
                "rowCount": candidate.get("rowCount") or len(rows),
                "valueBasis": candidate.get("valueBasis"),
                "coverageText": rows_coverage_text(rows),
                "selectors": candidate_selector_summary(rows),
                "evidence": evidence,
                "inForce": False,
            }
            # Genuine conflicts only: rows this candidate and a
            # candidate in force both carry, priced differently.
            conflicts: List[Dict[str, Any]] = []
            differing_total = 0
            for incumbent in accepted:
                incumbent_rows = candidate_effective_rows(incumbent)
                conf = conflicting_row_selectors(str(mechanic), rows, incumbent_rows)
                if not conf:
                    continue
                diff = candidate_diff(rows, incumbent_rows, str(mechanic))
                incumbent_source = candidate_provenance(incumbent)
                conflicts.append({
                    "candidateId": str(incumbent.get("id") or ""),
                    "filename": incumbent_source["filename"],
                    "page": incumbent_source["page"],
                    "differingRows": len(conf),
                    "examples": diff["examples"],
                })
                differing_total += len(conf)
            if not conflicts:
                option["confirmBack"] = (
                    f"{slot['label']}: {_was_clause(was['description'])}; now the filed table"
                    f" of {candidate.get('rowCount')} rows"
                    + (
                        f" from {evidence['filename']}"
                        + (f", p. {evidence['page']}" if evidence.get("page") else "")
                        if evidence.get("filename")
                        else f" ({SOURCE_NOT_RECORDED})"
                    )
                    + ", accepted on your confirmation. It adds its coverage to"
                    " the table in force — versions already accepted stay in force."
                )
                proposals.append({
                    "id": _proposal_id(PROPOSAL_KIND_FILED_TABLE_CHOICE, {
                        "slot": slot["id"], "candidateId": candidate_id,
                    }),
                    "kind": PROPOSAL_KIND_FILED_TABLE_CHOICE,
                    "slot": slot["id"],
                    "mechanic": mechanic,
                    "candidateId": candidate_id,
                    "options": [option],
                    "optionDiffs": [],
                    "switch": None,
                    "variant": None,
                    "params": None,
                    "label": (
                        f"Accept the filed {slot['label'].lower()} table"
                        + (
                            f" from {evidence['filename']}"
                            + (f" (p. {evidence['page']})" if evidence.get("page") else "")
                            if evidence.get("filename")
                            else f" ({SOURCE_NOT_RECORDED})"
                        )
                    ),
                    "confirmBack": option["confirmBack"],
                    "evidence": evidence,
                    "status": "pending",
                })
                continue
            incumbent = conflicts[0]
            incumbent_candidate = next(
                item for item in accepted
                if str(item.get("id") or "") == incumbent["candidateId"]
            )
            incumbent_rows = list(incumbent_candidate.get("rows") or [])
            full_diff = candidate_diff(rows, incumbent_rows, str(mechanic))
            incumbent_source = candidate_provenance(incumbent_candidate)
            incumbent_option = {
                "candidateId": incumbent["candidateId"],
                "filename": incumbent["filename"],
                "page": incumbent["page"],
                "tableHeading": incumbent_candidate.get("tableHeading"),
                "sources": incumbent_source["sources"],
                "rowCount": incumbent_candidate.get("rowCount") or len(incumbent_rows),
                "valueBasis": incumbent_candidate.get("valueBasis"),
                "coverageText": rows_coverage_text(incumbent_rows),
                "selectors": candidate_selector_summary(incumbent_rows),
                "evidence": {
                    "filename": incumbent["filename"],
                    "page": incumbent["page"],
                    "heading": incumbent_candidate.get("tableHeading"),
                    "sources": incumbent_source["sources"],
                    "snippet": (
                        f"{incumbent_candidate.get('rowCount')} rows extracted"
                        + " — already in force"
                    ),
                },
                "inForce": True,
                "confirmBack": (
                    f"{slot['label']}: keep the filed table"
                    f" {_from_phrase(incumbent['filename'])} as the version"
                    f" that governs the {differing_total} row(s) where the two"
                    f" filings disagree; the table"
                    f" {_from_phrase(evidence['filename'])} is not accepted"
                    " for those rows."
                ),
            }
            option["confirmBack"] = (
                f"{slot['label']}: accept the filed table"
                f" of {candidate.get('rowCount')} rows"
                f" {_from_phrase(evidence['filename'])}"
                + (f", p. {evidence['page']}" if evidence.get("page") else "")
                + f"; where its rows disagree with the table in force"
                f" {_from_phrase(incumbent['filename'])}"
                f" ({differing_total} row(s)), this version's rows govern"
                " and the in-force version's are overridden."
            )
            proposals.append({
                "id": _proposal_id(PROPOSAL_KIND_FILED_TABLE_CHOICE, {
                    "slot": slot["id"],
                    "candidateId": candidate_id,
                    "conflictWith": incumbent["candidateId"],
                }),
                "kind": PROPOSAL_KIND_FILED_TABLE_CHOICE,
                "slot": slot["id"],
                "mechanic": mechanic,
                "candidateId": None,
                "options": [incumbent_option, option],
                "optionDiffs": [{
                    "candidateId": candidate_id,
                    "comparedTo": incumbent["candidateId"],
                    "identicalRows": full_diff["identicalRows"],
                    "differingRows": differing_total,
                    "onlyInFirst": full_diff["onlyInB"],
                    "onlyInOption": full_diff["onlyInA"],
                    "examples": incumbent["examples"],
                }],
                "conflict": {
                    "candidateId": candidate_id,
                    "incumbentCandidateIds": [item["candidateId"] for item in conflicts],
                    "differingRows": differing_total,
                    "examples": incumbent["examples"],
                },
                "switch": None,
                "variant": None,
                "params": None,
                "label": (
                    f"Conflicting filed {slot['label'].lower()} tables — choose"
                    f" which governs the {differing_total} row(s) where they disagree"
                ),
                "confirmBack": (
                    f"{slot['label']}: two filed versions disagree on"
                    f" {differing_total} row(s) where their coverage overlaps."
                    " Choose which version governs those rows."
                ),
                "evidence": evidence,
                "status": "pending",
            })
    return proposals


# ---------------------------------------------------------------------------
# Proposal generation — equation proposals from harvesting
#
# Phase 7: the rule-shaped proposals are equation proposals.  Sources:
# the deterministic harvest over the workspace's slices (the canonical
# prose patterns live in workspace_equations), plus pending harvested
# records already on the artifact (e.g. from POST /equations/harvest,
# including model readings).  A proposal whose equation is already in
# force, or whose mechanic is governed by a correction (the actuary's
# own statement outranks an extraction proposal), is not proposed.
# ---------------------------------------------------------------------------


def _current_text(artifact: Dict[str, Any], mechanic: str) -> str:
    current = _ws_equations.in_force(artifact, mechanic)
    if current is None:
        return "no approved equation in force — the mechanic is not calculated"
    return str(current.get("rendering") or "an approved equation")


def _equation_before_clause(artifact: Dict[str, Any], mechanic: str) -> str:
    """The "before" clause of an equation confirm-back, plainly stated.

    The empty case gets its own sentence shape — "nothing was in
    force before" — rather than the shorthand "was no approved
    equation in force" (Billy, Oct 27, 2026).
    """

    if _ws_equations.in_force(artifact, mechanic) is None:
        return "nothing was in force before — the mechanic is not calculated"
    return f"was {_current_text(artifact, mechanic)}"


def _equation_proposals(
    artifact: Dict[str, Any], slices: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    seen_keys: set = set()

    def corrected_governed(mechanic: str) -> bool:
        current = _ws_equations.in_force(artifact, mechanic)
        return bool(current and (current.get("source") or {}).get("kind") == "correction")

    def add_proposal(
        *,
        mechanic: str,
        rendering: str,
        statement: Optional[str],
        filename: Optional[str],
        page: Optional[int],
        equation_id: Optional[str],
        candidate: Optional[Dict[str, Any]],
        body: Optional[Dict[str, Any]] = None,
        timing: Optional[str] = None,
    ) -> None:
        slot_id = _EQUATION_SLOT_BY_MECHANIC.get(mechanic)
        slot = SLOT_BY_ID.get(slot_id or "")
        if slot is None or corrected_governed(mechanic):
            return
        current = _ws_equations.in_force(artifact, mechanic)
        if current is not None and str(current.get("rendering") or "") == rendering:
            return  # already in force — nothing to propose
        key = (mechanic, rendering)
        if key in seen_keys:
            return
        seen_keys.add(key)
        label = _eq.MECHANIC_LABELS.get(mechanic, mechanic)
        evidence = {
            "filename": filename,
            "page": page,
            "heading": None,
            "snippet": statement,
        }
        confirm_back = (
            f"{label} equation: {_equation_before_clause(artifact, mechanic)}; "
            f"now {rendering}"
            + (f" — as stated in {filename}" if filename else f" ({SOURCE_NOT_RECORDED})")
            + (f", p. {page}" if page else "")
            + ", approved on your confirmation."
        )
        proposals.append({
            "id": _proposal_id(PROPOSAL_KIND_EQUATION, {
                "mechanic": mechanic, "rendering": rendering,
                "equationId": equation_id,
            }),
            "kind": PROPOSAL_KIND_EQUATION,
            "slot": slot["id"],
            "mechanic": slot.get("mechanic"),
            "candidateId": None,
            "switch": None,
            "variant": None,
            "params": None,
            "equationMechanic": mechanic,
            "equationId": equation_id,
            "candidate": candidate,
            "rendering": rendering,
            # The typeset form of the exact body a confirmation would
            # put in force — built by the same walker the in-force
            # record views use, so a suggestion is approved in the
            # same form it will run in (Oct 27, 2026).  None when the
            # body has a shape the walker does not know; the prose
            # rendering then stands alone, as on an in-force card.
            "math": (
                _eq.render_math_tree(body, mechanic) if body is not None else None
            ),
            "timingNote": _eq.timing_sentence(timing),
            "label": f"Approve the {label.lower()} equation from the filing",
            "confirmBack": confirm_back,
            "evidence": evidence,
            "status": "pending",
        })

    # Pending harvested records already on the artifact.
    for record in _ws_equations.records(artifact):
        if record.get("state") != "pending" or record.get("body") is None:
            continue
        source = record.get("source") or {}
        add_proposal(
            mechanic=str(record.get("mechanic")),
            rendering=str(record.get("rendering") or ""),
            statement=source.get("statement"),
            filename=source.get("filename"),
            page=source.get("page"),
            equation_id=str(record.get("id")),
            candidate=None,
            body=record.get("body"),
            timing=record.get("timing"),
        )

    # Fresh deterministic harvest candidates over the slices.
    for candidate in _ws_equations.deterministic_harvest(slices or []):
        mechanic = str(candidate.get("mechanic") or "")
        body = candidate.get("body")
        timing = candidate.get("timing")
        if mechanic == "nar_definition" and body is not None:
            # Proposing "death benefit − account value" when no NAR
            # factor above 1.0 is in force proposes a no-op (the two
            # readings agree at factor 1.0) — the harvest record keeps
            # the statement; no actionable proposal is generated.
            factor_rows = list((artifact.get("usable") or {}).get("nar_factors") or [])
            factors = [
                float(r.get("factor") or 1.0) for r in factor_rows
                if isinstance(r.get("factor"), (int, float))
            ]
            if not any(factor > 1.0 for factor in factors):
                continue
        if body is None and mechanic == "coi_charge" and timing:
            # A timing-only statement attaches to the COI body from the
            # table in force (or the in-force equation's body, or the
            # pending filed candidate's unit — confirming the timing
            # proposal creates the equation the table's own proposal
            # will feed).
            current = _ws_equations.in_force(artifact, "coi_charge")
            if current is not None and current.get("body") is not None:
                body = deepcopy(current["body"])
            else:
                coi_rows = list((artifact.get("usable") or {}).get("coi") or [])
                for candidate_rows in (artifact.get("candidates") or {}).get("coi") or []:
                    coi_rows = coi_rows + list(candidate_rows.get("rows") or [])
                units = {str(r.get("rate_unit")) for r in coi_rows if r.get("rate_unit")}
                if len(units) == 1:
                    body = _eq.coi_body_for_unit(units.pop())
            if body is None:
                continue  # unmapped until a COI equation exists
            rendering = _eq.render_with_timing(body, timing)
        elif body is None:
            continue  # unstructurable here; harvesting preserves it as unmapped
        else:
            rendering = _eq.render_equation(body, mechanic)
        add_proposal(
            mechanic=mechanic,
            rendering=rendering,
            statement=candidate.get("statement"),
            filename=candidate.get("filename"),
            page=candidate.get("page"),
            equation_id=None,
            candidate={
                "mechanic": mechanic,
                "body": body,
                "timing": timing,
                "statement": candidate.get("statement"),
                "filename": candidate.get("filename"),
                "page": candidate.get("page"),
                "assist": candidate.get("assist"),
            },
            body=body,
            timing=timing,
        )
    return proposals


def generate_proposals(
    artifact: Dict[str, Any],
    slices: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """All pending proposals for a workspace, dismissed ones excluded.

    Deterministic: the same artifact + slices always produce the same
    proposals with the same ids, so a confirm/dismiss round-trip can
    regenerate and match by id.
    """

    artifact = artifact or {}
    dismissed = {
        str(item.get("id"))
        for item in artifact.get("dismissedProposals") or []
        if isinstance(item, dict)
    }
    proposals = _filed_table_proposals(artifact) + _equation_proposals(artifact, slices or [])
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for proposal in proposals:
        if proposal["id"] in dismissed or proposal["id"] in seen:
            continue
        seen.add(proposal["id"])
        unique.append(proposal)
    return unique


# ---------------------------------------------------------------------------
# Apply / dismiss (both require the actuary's explicit action)
# ---------------------------------------------------------------------------


def apply_proposal(
    artifact: Dict[str, Any],
    proposal: Dict[str, Any],
    *,
    workspace_id: Optional[str],
    who: str,
    at: str,
    option_candidate_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply a CONFIRMED proposal; returns {"artifact", "change", ...}.

    Filed-table proposals apply through the same acceptance path as a
    manual review acceptance (which also puts the table's equation
    transcription in force).  Equation proposals apply through the
    Phase 7 approval machinery — the harvested record is approved, or
    the candidate is materialised and approved — with the proposal's
    origin and evidence stamped onto the equation record.  The caller
    (the API) enforces the confirmation gate before calling this.

    A filed-table proposal carries its candidate as the single
    option, or — where the candidate conflicts with a table in
    force — two options (the version in force vs the challenger);
    either way the chosen option (``option_candidate_id``) is
    required unless the proposal carries exactly one option — the
    choice is the user's, never a default.
    """

    slot = SLOT_BY_ID[str(proposal["slot"])]
    mechanic = str(proposal["mechanic"])

    if proposal["kind"] in {PROPOSAL_KIND_FILED_TABLE, PROPOSAL_KIND_FILED_TABLE_CHOICE}:
        if proposal["kind"] == PROPOSAL_KIND_FILED_TABLE_CHOICE:
            options = list(proposal.get("options") or [])
            chosen = option_candidate_id or (
                options[0]["candidateId"] if len(options) == 1 else None
            )
            if not chosen:
                raise ValueError(
                    "Choose which filed table to put in force before confirming"
                )
            option = next(
                (item for item in options if item.get("candidateId") == chosen), None
            )
            if option is None:
                raise ValueError("The chosen filed table is not one of the proposal's options")
            candidate_id = str(chosen)
            confirm_back = option.get("confirmBack") or proposal["confirmBack"]
            evidence = option.get("evidence") or proposal["evidence"]
        else:
            candidate_id = str(proposal["candidateId"])
            confirm_back = proposal["confirmBack"]
            evidence = proposal["evidence"]
        conflict = proposal.get("conflict") or {}
        incumbent_ids = {
            str(item) for item in conflict.get("incumbentCandidateIds") or []
        }
        if incumbent_ids and candidate_id in incumbent_ids:
            # The user chose the version in force for the contested
            # rows: the challenger is not accepted.  The decision is
            # recorded — a dismissal entry so the conflict proposal
            # does not regenerate, and a change record that states
            # what was decided.  Nothing about the tables changes.
            result = deepcopy(artifact or {})
            dismissed = result.setdefault("dismissedProposals", [])
            if not any(
                item.get("id") == proposal["id"]
                for item in dismissed if isinstance(item, dict)
            ):
                dismissed.append({"id": proposal["id"], "who": who, "at": at})
            change = _change_record(
                workspace_id=workspace_id,
                slot=slot,
                kind="proposal_conflict_kept",
                who=who,
                at=at,
                summary=(
                    f"Confirmed extraction proposal: {confirm_back} "
                    f"{_evidence_summary(evidence)}"
                ),
                prior=_summarize_rows(
                    list(((artifact or {}).get("usable") or {}).get(mechanic) or [])
                ),
                new={
                    "status": "kept_in_force",
                    "proposalId": proposal["id"],
                    "candidateId": conflict.get("candidateId"),
                    "keptCandidateId": candidate_id,
                },
            )
            change["proposalId"] = proposal["id"]
            return {"artifact": result, "change": change, "proposal": proposal}
        accepted = accept_filed_mechanic(
            deepcopy(artifact or {}),
            mechanic,
            candidate_id=candidate_id,
            reviewed_by=who,
            resolve_conflict=bool(incumbent_ids),
        )
        result = _ws_equations.transcribe_tables_as_approved(
            accepted, who=who, at=at
        )["artifact"]
        change = _change_record(
            workspace_id=workspace_id,
            slot=slot,
            kind="proposal_accept",
            who=who,
            at=at,
            summary=(
                f"Confirmed extraction proposal: {confirm_back} "
                f"{_evidence_summary(evidence)}"
            ),
            prior=_summarize_rows(
                list(((artifact or {}).get("usable") or {}).get(mechanic) or [])
            ),
            new={
                "status": (result.get("status") or {}).get(mechanic),
                "proposalId": proposal["id"],
                "candidateId": candidate_id,
            },
        )
        change["proposalId"] = proposal["id"]
        return {"artifact": result, "change": change, "proposal": proposal}

    if proposal["kind"] == PROPOSAL_KIND_EQUATION:
        equation_mechanic = str(proposal["equationMechanic"])
        if proposal.get("equationId"):
            approved = _ws_equations.approve_equation(
                artifact or {}, equation_mechanic,
                str(proposal["equationId"]), who=who, at=at,
            )
            result = approved["artifact"]
            record = approved["record"]
        elif proposal.get("candidate"):
            approved = _ws_equations.approve_harvest_candidate(
                artifact or {}, proposal["candidate"],
                who=who, at=at, proposal_id=proposal["id"],
            )
            result = approved["artifact"]
            record = approved["record"]
        else:
            raise ValueError("Equation proposal carries no equation or candidate")
        # Stamp the proposal provenance on the record that went in force.
        stored = next(
            (r for r in _ws_equations.records_for(result, equation_mechanic)
             if r.get("id") == record.get("id")),
            None,
        )
        if stored is not None:
            stored["source"]["proposalId"] = proposal["id"]
            stored["source"]["proposalEvidence"] = deepcopy(proposal["evidence"])
            record = stored
        change = _change_record(
            workspace_id=workspace_id,
            slot=slot,
            kind="proposal_equation",
            who=who,
            at=at,
            summary=(
                f"Confirmed extraction proposal: {proposal['confirmBack']} "
                f"{_evidence_summary(proposal['evidence'])}"
            ),
            prior={},
            new={
                "status": "approved",
                "proposalId": proposal["id"],
                "equationId": record.get("id"),
                "equationMechanic": equation_mechanic,
            },
        )
        change["proposalId"] = proposal["id"]
        change["equationId"] = record.get("id")
        return {
            "artifact": result,
            "change": change,
            "equation": record,
            "proposal": proposal,
        }

    raise ValueError(f"Unknown proposal kind: {proposal['kind']!r}")


# ---------------------------------------------------------------------------
# Bulk approval — "approve all uncontested"
#
# Billy (Oct 27, 2026): approving a fresh workspace's suggestions one
# by one is a ten-click slog, so the panel offers one bulk action —
# under the doctrine, not around it.  A human still approves
# everything that runs, having seen what it does: the first call
# PLANS (a summary — what will be approved, counted and listed by
# kind; what is excluded, named, and why) and changes nothing; only
# a confirmed call applies, through the same apply_proposal paths as
# individual confirmations, each item recorded individually in the
# change history and tagged with the batch id.
#
# Eligible: a filed-table candidate whose approval creates no value
# conflict with rows already in force, and an equation for a mechanic
# with exactly ONE pending reading and no different equation in
# force.  Excluded (left pending, named): competing readings for one
# mechanic — on an earlier workspace a model's wrong policy-fees
# reading sat beside the correct deterministic one, and bulk approval
# must never swallow a rival — a pending equation that would replace
# a different in-force equation, and a table candidate in genuine
# conflict with a table in force.
# ---------------------------------------------------------------------------


def _bulk_batch_id(workspace_id: Optional[str], who: str, at: str) -> str:
    canonical = json.dumps(
        {"workspace": workspace_id, "who": who, "at": at}, sort_keys=True
    )
    return "bulk-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _bulk_item(
    proposal: Dict[str, Any], kind: str, candidate_id: Optional[str] = None
) -> Dict[str, Any]:
    return {
        "proposalId": proposal["id"],
        "kind": kind,
        "slot": proposal.get("slot"),
        "mechanic": (
            str(proposal.get("equationMechanic"))
            if kind == "equation"
            else str(proposal.get("mechanic"))
        ),
        "label": proposal.get("label") or "",
        "candidateId": candidate_id,
    }


def plan_bulk_approval(
    artifact: Dict[str, Any],
    slices: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """What a bulk approval WOULD do — pure, changes nothing.

    Returns {"eligible", "excluded"} item lists; each excluded item
    carries the reason it stays pending, by name.
    """

    artifact = artifact or {}
    proposals = generate_proposals(artifact, slices or [])
    readings_per_mechanic: Dict[str, int] = {}
    for proposal in proposals:
        if proposal.get("kind") == PROPOSAL_KIND_EQUATION:
            mechanic = str(proposal.get("equationMechanic"))
            readings_per_mechanic[mechanic] = readings_per_mechanic.get(mechanic, 0) + 1

    eligible: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for proposal in proposals:
        kind = proposal.get("kind")
        if kind in {PROPOSAL_KIND_FILED_TABLE, PROPOSAL_KIND_FILED_TABLE_CHOICE}:
            conflict = proposal.get("conflict") or {}
            options = list(proposal.get("options") or [])
            if conflict:
                excluded.append({
                    **_bulk_item(
                        proposal, "filed_table",
                        str(conflict.get("candidateId") or "") or None,
                    ),
                    "reason": (
                        f"its rows disagree with a table already in force on "
                        f"{conflict.get('differingRows')} row(s) where the filings "
                        "differ — choose which governs, individually"
                    ),
                })
            elif kind == PROPOSAL_KIND_FILED_TABLE_CHOICE and len(options) != 1:
                excluded.append({
                    **_bulk_item(proposal, "filed_table"),
                    "reason": "it needs a choice between filed versions — decide individually",
                })
            else:
                candidate_id = (
                    str(options[0]["candidateId"]) if options
                    else str(proposal.get("candidateId") or "")
                )
                eligible.append(_bulk_item(proposal, "filed_table", candidate_id))
        elif kind == PROPOSAL_KIND_EQUATION:
            mechanic = str(proposal.get("equationMechanic"))
            label = _eq.MECHANIC_LABELS.get(mechanic, mechanic)
            rivals = readings_per_mechanic.get(mechanic, 0)
            if rivals > 1:
                excluded.append({
                    **_bulk_item(proposal, "equation"),
                    "reason": (
                        f"one of {rivals} competing readings for {label} — "
                        "approve the right one individually"
                    ),
                })
            elif _ws_equations.in_force(artifact, mechanic) is not None:
                excluded.append({
                    **_bulk_item(proposal, "equation"),
                    "reason": (
                        f"it would replace the {label} equation already in "
                        "force — approve the replacement individually"
                    ),
                })
            else:
                eligible.append(_bulk_item(proposal, "equation"))
        else:
            excluded.append({
                **_bulk_item(proposal, str(kind or "unknown")),
                "reason": "not eligible for bulk approval — decide individually",
            })
    return {"eligible": eligible, "excluded": excluded}


def bulk_summary(plan: Dict[str, Any]) -> Dict[str, Any]:
    """The confirm-back for a bulk plan: counts, the items, the text."""

    eligible = list(plan.get("eligible") or [])
    excluded = list(plan.get("excluded") or [])
    tables = [item for item in eligible if item["kind"] == "filed_table"]
    equations = [item for item in eligible if item["kind"] == "equation"]
    parts = [
        f"Approve all uncontested: {len(eligible)} item(s) will be approved"
        f" — {len(tables)} filed table(s), {len(equations)} equation(s)"
        " — each recorded in the change history as part of this one"
        " bulk approval. Nothing else changes."
    ]
    if excluded:
        parts.append(
            "Left pending: "
            + "; ".join(
                f"{item['label']} ({item['reason']})" for item in excluded
            )
            + "."
        )
    return {
        "eligibleCount": len(eligible),
        "tableCount": len(tables),
        "equationCount": len(equations),
        "eligible": eligible,
        "excluded": excluded,
        "confirmBack": " ".join(parts),
    }


def apply_bulk_approval(
    artifact: Dict[str, Any],
    slices: Optional[List[Dict[str, Any]]] = None,
    *,
    workspace_id: Optional[str],
    who: str,
    at: str,
) -> Dict[str, Any]:
    """Apply a planned bulk approval through the single-item paths.

    Items are applied one at a time against the evolving artifact,
    and each is RE-CHECKED before it applies: a proposal settled by
    an earlier item in the batch is skipped as settled; a table
    candidate that now conflicts with rows an earlier item put in
    force, or an equation whose mechanic gained a different in-force
    equation, is skipped and reported — never silently merged, never
    a silent replacement.

    Application order is EQUATIONS FIRST, then filed tables (live
    gate, Oct 27, 2026): accepting a table transcribes equations for
    every mechanic that has no record yet, so a batch that accepted
    tables first let transcription put ITS premium-load reading (the
    fee-table lookup) in force, and the harvested reading the
    summary had promised — the memo's stated percentage of premium —
    was displaced before its turn came.  Approving the confirmed
    equations first makes transcription defer to them (it never
    touches a mechanic that already has a record), so the batch
    delivers exactly the set the user confirmed.
    """

    slices = slices or []
    plan = plan_bulk_approval(artifact, slices)
    batch_id = _bulk_batch_id(workspace_id, who, at)
    result = deepcopy(artifact or {})
    changes: List[Dict[str, Any]] = []
    applied: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    ordered = sorted(
        plan["eligible"], key=lambda i: 0 if i["kind"] == "equation" else 1
    )
    for item in ordered:
        current = generate_proposals(result, slices)
        proposal = next(
            (p for p in current if p.get("id") == item["proposalId"]), None
        )
        if proposal is None and item["kind"] == "filed_table" and item.get("candidateId"):
            # A filed-table proposal's id changes when it turns into a
            # conflict choice mid-batch (an earlier item put a table in
            # force that this candidate now disagrees with).  Find it by
            # its candidate so the re-check below reports the contest
            # instead of a misleading "settled".
            for candidate_proposal in current:
                if candidate_proposal.get("kind") not in {
                    PROPOSAL_KIND_FILED_TABLE, PROPOSAL_KIND_FILED_TABLE_CHOICE,
                }:
                    continue
                option_ids = {
                    str(o.get("candidateId"))
                    for o in candidate_proposal.get("options") or []
                }
                challenger = str(
                    (candidate_proposal.get("conflict") or {}).get("candidateId") or ""
                )
                if item["candidateId"] in option_ids or item["candidateId"] == challenger:
                    proposal = candidate_proposal
                    break
        if proposal is None:
            skipped.append({
                **item,
                "reason": "settled by an earlier approval in this batch",
            })
            continue
        if item["kind"] == "filed_table":
            options = list(proposal.get("options") or [])
            if proposal.get("conflict") or (
                proposal.get("kind") == PROPOSAL_KIND_FILED_TABLE_CHOICE
                and len(options) != 1
            ):
                skipped.append({
                    **item,
                    "reason": (
                        "became contested during this batch — its rows "
                        "disagree with a table approved earlier in it; "
                        "decide individually"
                    ),
                })
                continue
            mechanic = str(proposal.get("mechanic"))
            candidate = next(
                (
                    c for c in (result.get("candidates") or {}).get(mechanic) or []
                    if isinstance(c, dict) and str(c.get("id") or "") == item["candidateId"]
                ),
                None,
            )
            usable_rows = list((result.get("usable") or {}).get(mechanic) or [])
            if candidate is not None and usable_rows:
                conf = conflicting_row_selectors(
                    mechanic, candidate_effective_rows(candidate), usable_rows
                )
                if conf:
                    skipped.append({
                        **item,
                        "reason": (
                            f"its rows disagree on {len(conf)} row(s) with a "
                            "table approved earlier in this batch — decide "
                            "individually"
                        ),
                    })
                    continue
            outcome = apply_proposal(
                result, proposal,
                workspace_id=workspace_id, who=who, at=at,
                option_candidate_id=item["candidateId"],
            )
        else:
            mechanic = str(proposal.get("equationMechanic"))
            rivals = [
                p for p in current
                if p.get("kind") == PROPOSAL_KIND_EQUATION
                and str(p.get("equationMechanic")) == mechanic
            ]
            in_force = _ws_equations.in_force(result, mechanic)
            if len(rivals) > 1:
                skipped.append({
                    **item,
                    "reason": "became contested during this batch — decide individually",
                })
                continue
            if in_force is not None and str(in_force.get("rendering") or "") != str(
                proposal.get("rendering") or ""
            ):
                skipped.append({
                    **item,
                    "reason": (
                        "a different equation for this mechanic went in force "
                        "earlier in this batch — decide individually"
                    ),
                })
                continue
            outcome = apply_proposal(
                result, proposal, workspace_id=workspace_id, who=who, at=at,
            )
        change = outcome["change"]
        change["batchId"] = batch_id
        change["bulkApproval"] = True
        changes.append(change)
        applied.append(item)
        result = outcome["artifact"]

    summary = bulk_summary(plan)
    summary["batchId"] = batch_id
    summary["appliedCount"] = len(applied)
    summary["applied"] = applied
    summary["skipped"] = skipped
    return {
        "artifact": result,
        "changes": changes,
        "batchId": batch_id,
        "applied": applied,
        "skipped": skipped,
        "excluded": plan["excluded"],
        "summary": summary,
    }


def dismiss_proposal(
    artifact: Dict[str, Any],
    proposal: Dict[str, Any],
    *,
    workspace_id: Optional[str],
    who: str,
    at: str,
) -> Dict[str, Any]:
    """Record a dismissal so the proposal does not regenerate."""

    result = deepcopy(artifact or {})
    dismissed = result.setdefault("dismissedProposals", [])
    if not any(item.get("id") == proposal["id"] for item in dismissed if isinstance(item, dict)):
        dismissed.append({"id": proposal["id"], "who": who, "at": at})
    slot = SLOT_BY_ID[str(proposal["slot"])]
    change = _change_record(
        workspace_id=workspace_id,
        slot=slot,
        kind="proposal_dismissed",
        who=who,
        at=at,
        summary=f"Dismissed extraction proposal: {proposal['label']}",
        prior={},
        new={"proposalId": proposal["id"], "status": "dismissed"},
    )
    change["proposalId"] = proposal["id"]
    return {"artifact": result, "change": change, "proposal": proposal}
