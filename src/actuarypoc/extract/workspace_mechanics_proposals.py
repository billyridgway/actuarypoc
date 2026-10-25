"""Extraction proposals — Phase 4 of the Eddy improvement plan.

From a workspace's extracted mechanics and Phase 0 document slices,
the system PROPOSES slot values and rule-bank switch settings, each
with page evidence, for the actuary to confirm in the panel.  A
proposal is the Phase 3 confirm-back pattern applied to extraction:
the proposal restates what it would set in actuarial language, and
nothing applies until the user confirms — confirming applies it
through the exact same paths as a manual action (a filed-candidate
acceptance, or a Phase 3 correction), with the proposal's evidence
recorded in the applied record's provenance.

Signals are DETERMINISTIC FIRST:

* filed table candidates extracted from the documents (headings,
  schedule shapes) become "accept this filed table" proposals;
* prose statements in the filing's slices — a COI deduction timing
  phrase, a net-amount-at-risk definition, a surrender percentage
  with its grading period — become switch-setting proposals.

A configured model may additionally propose at AUTHORING time (a
human or a model-assisted authoring step drafting a proposal for the
panel), but a proposal is data, not authority: whatever its origin,
the actuary confirms the mapping before anything applies, and with no
model configured the deterministic proposals above still work.  The
projection path never sees proposals — only confirmed mechanics.

Dismissals persist on the artifact (``dismissedProposals``) so a
dismissed proposal does not regenerate.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional

from actuarypoc.extract import workspace_mechanics_corrections as _corrections
from actuarypoc.extract.workspace_mechanics_panel import (
    SLOT_BY_ID,
    _change_record,
    _slot_status,
    _summarize_rows,
)
from actuarypoc.extract.workspace_ul_mechanics import accept_filed_mechanic


PROPOSAL_KIND_FILED_TABLE = "filed_table"
PROPOSAL_KIND_SWITCH = "switch_setting"

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
        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("reviewStatus") != "review_required":
                continue
            candidate_id = str(candidate.get("id") or "")
            if not candidate_id or candidate_id in usable_ids:
                continue
            provenance = candidate.get("provenance") or {}
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
            was = _corrections.describe_current(artifact, slot)
            label = (
                f"Accept the filed {slot['label'].lower()} table"
                f" from {evidence['filename'] or 'the filing'}"
                + (f" (p. {evidence['page']})" if evidence.get("page") else "")
            )
            confirm_back = (
                f"{slot['label']}: was {was['description']}; now the filed table"
                f" of {candidate.get('rowCount')} rows"
                + (f" from {evidence['filename']}" if evidence.get("filename") else "")
                + (f", p. {evidence['page']}" if evidence.get("page") else "")
                + ", accepted on your confirmation."
            )
            proposals.append({
                "id": _proposal_id(PROPOSAL_KIND_FILED_TABLE, {
                    "slot": slot["id"], "candidateId": candidate_id,
                }),
                "kind": PROPOSAL_KIND_FILED_TABLE,
                "slot": slot["id"],
                "mechanic": mechanic,
                "candidateId": candidate_id,
                "switch": None,
                "variant": None,
                "params": None,
                "label": label,
                "confirmBack": confirm_back,
                "evidence": evidence,
                "status": "pending",
            })
    return proposals


# ---------------------------------------------------------------------------
# Proposal generation — prose switch signals in the slices
# ---------------------------------------------------------------------------

# Each signal: (regex over the slice text, required context words in the
# same slice, variant, params builder).  The patterns are deliberately
# narrow — a signal that does not fire costs a manual correction; a
# signal that fires wrongly costs trust.
_TIMING_SIGNALS = [
    (re.compile(r"deduct\w*\s+(?:monthly\s+)?in advance|beginning of (?:the|each) (?:policy )?month|before interest is credited", re.I), "beginning"),
    (re.compile(r"in arrears|end of (?:the|each) (?:policy )?month|after interest (?:is )?credited", re.I), "end"),
    (re.compile(r"middle of (?:the|each) (?:policy )?month|mid-month", re.I), "middle"),
]

_NAR_PROSE = re.compile(
    r"net amount at risk[^.]{0,160}?(?:death benefit|benefit payable)[^.]{0,80}?"
    r"(?:less|minus|reduced by)[^.]{0,40}?account value",
    re.I | re.S,
)

_SURRENDER_PCT = re.compile(
    r"surrender charge[^.]{0,120}?(\d+(?:\.\d+)?)\s*%\s*of the account value",
    re.I | re.S,
)
_SURRENDER_GRADING = re.compile(
    r"grad\w+ to (?:zero|0)\s*(?:%|percent)?\s*over (\d{1,2}) years",
    re.I,
)


def _in_force_factor(artifact: Dict[str, Any]) -> float:
    rows = list((artifact.get("usable") or {}).get("nar_factors") or [])
    if rows:
        try:
            return float(rows[0].get("factor") or 1.0)
        except (TypeError, ValueError):
            return 1.0
    return 1.0


def _switch_proposals(
    artifact: Dict[str, Any], slices: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    corrections = artifact.get("corrections") or {}

    def already_corrected(mechanic: str) -> bool:
        return (corrections.get(mechanic) or {}).get("variant") is not None

    settings = _corrections.executable_settings(artifact)
    current_timing = str(settings.get("coiTiming") or "beginning")
    current_definition = str(settings.get("narDefinition") or "factor_adjusted")

    for slice_ in slices or []:
        text = str(slice_.get("text") or "")
        if not text:
            continue
        lowered = text.lower()

        # --- COI deduction timing -------------------------------------
        if not already_corrected("coi") and (
            "cost of insurance" in lowered or "coi" in lowered
        ):
            for pattern, timing in _TIMING_SIGNALS:
                match = pattern.search(text)
                if not match or timing == current_timing:
                    continue
                slot = SLOT_BY_ID["coi"]
                spec = {"variant": "coi_timing", "params": {"timing": timing}}
                try:
                    preview = _corrections.preview_correction(
                        artifact, slot, spec, who="extraction", at=""
                    )
                except ValueError:
                    continue
                proposals.append({
                    "id": _proposal_id(PROPOSAL_KIND_SWITCH, {
                        "slot": "coi", "variant": "coi_timing",
                        "params": {"timing": timing},
                    }),
                    "kind": PROPOSAL_KIND_SWITCH,
                    "slot": "coi",
                    "mechanic": "coi",
                    "candidateId": None,
                    "switch": f"coi.timing.{timing}",
                    "variant": "coi_timing",
                    "params": {"timing": timing},
                    "label": f"Set COI deduction timing to {timing} of month",
                    "confirmBack": preview["confirmBack"],
                    "evidence": _evidence(slice_, match.start(), match.end()),
                    "status": "pending",
                })
                break

        # --- NAR definition -------------------------------------------
        if not already_corrected("nar_factors") and current_definition != "unadjusted":
            match = _NAR_PROSE.search(text)
            if match and _in_force_factor(artifact) > 1.0:
                slot = SLOT_BY_ID["nar"]
                spec = {"variant": "nar_definition", "params": {"definition": "unadjusted"}}
                try:
                    preview = _corrections.preview_correction(
                        artifact, slot, spec, who="extraction", at=""
                    )
                except ValueError:
                    preview = None
                if preview is not None:
                    proposals.append({
                        "id": _proposal_id(PROPOSAL_KIND_SWITCH, {
                            "slot": "nar", "variant": "nar_definition",
                            "params": {"definition": "unadjusted"},
                        }),
                        "kind": PROPOSAL_KIND_SWITCH,
                        "slot": "nar",
                        "mechanic": "nar_factors",
                        "candidateId": None,
                        "switch": "nar.definition.unadjusted",
                        "variant": "nar_definition",
                        "params": {"definition": "unadjusted"},
                        "label": "Set net amount at risk to death benefit − account value",
                        "confirmBack": preview["confirmBack"],
                        "evidence": _evidence(slice_, match.start(), match.end()),
                        "status": "pending",
                    })

        # --- Surrender basis ------------------------------------------
        if not already_corrected("surrender"):
            pct_match = _SURRENDER_PCT.search(text)
            grade_match = _SURRENDER_GRADING.search(text)
            if pct_match and grade_match:
                percent = float(pct_match.group(1)) / 100.0
                grading_years = int(grade_match.group(1))
                if 0 < percent <= 1 and 1 <= grading_years <= 40:
                    slot = SLOT_BY_ID["surrender"]
                    params = {
                        "basis": "percent_account_value",
                        "percent": percent,
                        "gradingYears": grading_years,
                    }
                    spec = {"variant": "surrender_basis", "params": params}
                    try:
                        preview = _corrections.preview_correction(
                            artifact, slot, spec, who="extraction", at=""
                        )
                    except ValueError:
                        preview = None
                    if preview is not None:
                        proposals.append({
                            "id": _proposal_id(PROPOSAL_KIND_SWITCH, {
                                "slot": "surrender", "variant": "surrender_basis",
                                "params": params,
                            }),
                            "kind": PROPOSAL_KIND_SWITCH,
                            "slot": "surrender",
                            "mechanic": "surrender",
                            "candidateId": None,
                            "switch": "surrender.schedule.graded",
                            "variant": "surrender_basis",
                            "params": params,
                            "label": (
                                f"Set surrender charge to {percent * 100:g}% of account "
                                f"value, grading to 0 over {grading_years} years"
                            ),
                            "confirmBack": preview["confirmBack"],
                            "evidence": _evidence(
                                slice_, pct_match.start(), pct_match.end()
                            ),
                            "status": "pending",
                        })
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
    proposals = _filed_table_proposals(artifact) + _switch_proposals(artifact, slices or [])
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
) -> Dict[str, Any]:
    """Apply a CONFIRMED proposal; returns {"artifact", "change", ...}.

    Filed-table proposals apply through the same acceptance path as a
    manual review acceptance; switch proposals apply through the
    Phase 3 correction machinery, with the proposal's origin and
    evidence stamped onto the correction record.  The caller (the API)
    enforces the confirmation gate before calling this.
    """

    slot = SLOT_BY_ID[str(proposal["slot"])]
    mechanic = str(proposal["mechanic"])

    if proposal["kind"] == PROPOSAL_KIND_FILED_TABLE:
        result = accept_filed_mechanic(
            deepcopy(artifact or {}),
            mechanic,
            candidate_id=str(proposal["candidateId"]),
            reviewed_by=who,
        )
        change = _change_record(
            workspace_id=workspace_id,
            slot=slot,
            kind="proposal_accept",
            who=who,
            at=at,
            summary=(
                f"Confirmed extraction proposal: {proposal['confirmBack']} "
                f"(evidence: {proposal['evidence'].get('filename')}"
                + (f", p. {proposal['evidence'].get('page')}" if proposal["evidence"].get("page") else "")
                + ")"
            ),
            prior=_summarize_rows(
                list(((artifact or {}).get("usable") or {}).get(mechanic) or [])
            ),
            new={
                "status": (result.get("status") or {}).get(mechanic),
                "proposalId": proposal["id"],
                "candidateId": proposal["candidateId"],
            },
        )
        change["proposalId"] = proposal["id"]
        return {"artifact": result, "change": change, "proposal": proposal}

    if proposal["kind"] == PROPOSAL_KIND_SWITCH:
        spec = {
            "variant": proposal["variant"],
            "params": deepcopy(proposal["params"]),
            "text": None,
        }
        applied = _corrections.apply_correction(
            artifact or {}, slot, spec, workspace_id=workspace_id, who=who, at=at
        )
        record = applied["correction"]
        # The same record object lives in the returned artifact's
        # corrections map — stamp the proposal provenance on it.
        record["origin"] = "extraction_proposal"
        record["proposalId"] = proposal["id"]
        record["proposalEvidence"] = deepcopy(proposal["evidence"])
        change = applied["change"]
        change["kind"] = "proposal_correction"
        change["proposalId"] = proposal["id"]
        change["summary"] = (
            f"Confirmed extraction proposal: {change['summary']} "
            f"(evidence: {proposal['evidence'].get('filename')}"
            + (f", p. {proposal['evidence'].get('page')}" if proposal["evidence"].get("page") else "")
            + ")"
        )
        return {
            "artifact": applied["artifact"],
            "change": change,
            "correction": record,
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
