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
    candidate_group_key,
    candidate_selector_summary,
    rows_coverage_text,
)


PROPOSAL_KIND_FILED_TABLE = "filed_table"
#: Unification revamp: filed-table proposals are one CHOICE per
#: alternative group (see _filed_table_proposals).
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
    """One CHOICE proposal per group of alternative filed tables.

    Unification revamp: two documents filing the same table (the
    base specimen and its Nicotine variant) used to generate one
    proposal EACH, so the user confirmed a sequence of alternatives
    and accepting both stacked their rows.  Now candidates in one
    alternative group (same mechanic; for fees, the same component
    set) form a single proposal whose options are the candidates,
    with a computed diff between them.  Once any candidate in the
    group is in force, the group leaves the queue — choosing or
    switching is then a slot-card action, not a recurring proposal.
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
        groups: Dict[Any, List[Dict[str, Any]]] = {}
        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue
            groups.setdefault(candidate_group_key(str(mechanic), candidate), []).append(candidate)
        for group_key, members in groups.items():
            if any(member.get("reviewStatus") == "accepted" for member in members):
                continue  # a choice was made; switching lives on the slot card
            pending = [
                member for member in members
                if member.get("reviewStatus") == "review_required"
                and str(member.get("id") or "")
                and str(member.get("id")) not in usable_ids
            ]
            if not pending:
                continue
            was = _corrections.describe_current(artifact, slot)
            options: List[Dict[str, Any]] = []
            for candidate in pending:
                candidate_id = str(candidate.get("id") or "")
                provenance = candidate.get("provenance") or {}
                rows = list(candidate.get("rows") or [])
                evidence = {
                    "filename": candidate.get("filename") or provenance.get("filename"),
                    "page": candidate.get("page") or provenance.get("page"),
                    "heading": candidate.get("tableHeading"),
                    "snippet": (
                        f"{candidate.get('rowCount')} rows extracted"
                        + (f" under “{candidate.get('tableHeading')}”" if candidate.get("tableHeading") else "")
                        + (f" ({candidate.get('valueBasis')})" if candidate.get("valueBasis") else "")
                    ),
                }
                options.append({
                    "candidateId": candidate_id,
                    "filename": evidence["filename"],
                    "page": evidence["page"],
                    "tableHeading": candidate.get("tableHeading"),
                    "rowCount": candidate.get("rowCount") or len(rows),
                    "valueBasis": candidate.get("valueBasis"),
                    "coverageText": rows_coverage_text(rows),
                    "selectors": candidate_selector_summary(rows),
                    "evidence": evidence,
                    "confirmBack": (
                        f"{slot['label']}: was {was['description']}; now the filed table"
                        f" of {candidate.get('rowCount')} rows"
                        + (f" from {evidence['filename']}" if evidence.get("filename") else "")
                        + (f", p. {evidence['page']}" if evidence.get("page") else "")
                        + ", accepted on your confirmation."
                    ),
                })
            first_rows = list(pending[0].get("rows") or [])
            option_diffs: List[Dict[str, Any]] = []
            for candidate in pending[1:]:
                diff = candidate_diff(first_rows, list(candidate.get("rows") or []), str(mechanic))
                option_diffs.append({
                    "candidateId": str(candidate.get("id") or ""),
                    "comparedTo": str(pending[0].get("id") or ""),
                    "identicalRows": diff["identicalRows"],
                    "differingRows": diff["differingRows"],
                    "onlyInFirst": diff["onlyInA"],
                    "onlyInOption": diff["onlyInB"],
                    "examples": diff["examples"],
                })
            if len(options) == 1:
                label = (
                    f"Accept the filed {slot['label'].lower()} table"
                    f" from {options[0]['filename'] or 'the filing'}"
                    + (f" (p. {options[0]['page']})" if options[0].get("page") else "")
                )
                confirm_back = options[0]["confirmBack"]
            else:
                label = (
                    f"Choose the filed {slot['label'].lower()} table — "
                    f"{len(options)} filed versions"
                )
                confirm_back = (
                    f"{slot['label']}: was {was['description']}; now the filed table "
                    "you choose below, accepted on your confirmation."
                )
            proposals.append({
                "id": _proposal_id(PROPOSAL_KIND_FILED_TABLE_CHOICE, {
                    "slot": slot["id"],
                    "group": [str(part) for part in group_key[1]] or ["-"],
                    "candidateIds": sorted(option["candidateId"] for option in options),
                }),
                "kind": PROPOSAL_KIND_FILED_TABLE_CHOICE,
                "slot": slot["id"],
                "mechanic": mechanic,
                "candidateId": options[0]["candidateId"] if len(options) == 1 else None,
                "options": options,
                "optionDiffs": option_diffs,
                "switch": None,
                "variant": None,
                "params": None,
                "label": label,
                "confirmBack": confirm_back,
                "evidence": options[0]["evidence"],
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
            f"{label} equation: was {_current_text(artifact, mechanic)}; "
            f"now {rendering}"
            + (f" — as stated in {filename}" if filename else "")
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

    A filed-table CHOICE proposal additionally requires the chosen
    option (``option_candidate_id``) unless it carries exactly one
    option — the choice is the user's, never a default.
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
        accepted = accept_filed_mechanic(
            deepcopy(artifact or {}),
            mechanic,
            candidate_id=candidate_id,
            reviewed_by=who,
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
                f"(evidence: {evidence.get('filename')}"
                + (f", p. {evidence.get('page')}" if evidence.get("page") else "")
                + ")"
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
                f"(evidence: {proposal['evidence'].get('filename')}"
                + (f", p. {proposal['evidence'].get('page')}" if proposal["evidence"].get("page") else "")
                + ")"
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
