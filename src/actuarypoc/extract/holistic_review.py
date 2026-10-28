"""Holistic review pass — background self-checking (Oct 27, 2026).

Design note: ``docs/holistic-review-pass.md`` (and the design record
in ``actuarypoc-deploy/holistic-review-pass-design-2026-10-27.md``).

The pass runs INSIDE the background analysis job, after extraction
and candidate assembly, before the job finalizes.  It is a REVIEWER,
never an extractor and never an authority:

* every harvested suggestion is independently re-read under a
  DIFFERENT slicing (wider, document-grouped units; overlapping
  pairs; cross-referenced documents dispatched together) and the
  agreement — or the disagreement — is attached to the suggestion as
  verification evidence;
* a disagreement opens a reconciliation case.  Cases are work items
  for the pipeline, resolved by a ladder (deterministic rules ->
  joint re-read -> bounded repair -> source standing -> reasoned
  judgment), in that order.  A reconciled case presents ONE
  suggestion; the losing reading and the rationale stay in its
  provenance and in the decision log — visible, never deleted;
* a case the ladder genuinely cannot settle — above all two filed
  sources truly contradicting each other — escalates to a human
  review flag carrying the quoted evidence.  Flagged items are
  excluded from bulk approval (named in its summary) until a person
  reviews them individually;
* the review also reconciles the compliance header: a requirement
  the analysis snapshotted as missing whose equation the review's
  own re-read actually FOUND is named as found-by-review in the
  filing-review reconciliation (see
  ``workspace_mechanics_panel.filing_review_reconciliation``);
* NOTHING is auto-approved anywhere.  Human approvals remain the
  only path into force, exactly as the equation doctrine requires.
  Human clicks are logged as workflow data, never as correctness
  labels: the decision log records verifiable features (dual-slicing
  convergence, arithmetic constraints, filed-source corroboration)
  so a future calibrated decision model can be evaluated against
  them in shadow.

Judgment calls sit behind a typed decision interface
(:class:`DecisionProvider`: choose / score / truth-probability).
The interim implementation wraps the current backend; its outputs
are treated as UNcalibrated — a judgment-tier resolution requires
two independent runs to agree AND filed corroboration for the
winner, else the case escalates.  A Jev-class calibrated model can
replace the provider without redesign.  Pre-approval is HELD (see
the design note) and is not implemented here.

If the pass cannot run (disabled by env, or the backend profile is
too small), the job records its absence plainly — never silently.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Sequence

from actuarypoc.domain import equations as _eq
from actuarypoc.extract import workspace_equations as _ws_eq
from actuarypoc.extract.workspace_ul_mechanics import (
    candidate_effective_rows,
    conflicting_row_selectors,
)

__all__ = [
    "DecisionProvider",
    "InterimDecisionProvider",
    "review_availability",
    "run_holistic_review",
    "regroup_slices_wider",
    "REVIEW_ENV",
]

REVIEW_ENV = "ACTUARYPOC_HOLISTIC_REVIEW"

_MAX_REPAIRS = 5
_MAX_JUDGED_CASES = 3

# Mechanic keywords used by the framing-loss scan: a qualification
# sentence must name the charge it qualifies to open a case.
_MECHANIC_KEYWORDS: Dict[str, Sequence[str]] = {
    "coi_charge": ("cost of insurance", "coi charge", "coi rate"),
    "surrender_charge": ("surrender charge",),
    "premium_load": ("premium expense", "premium load"),
    "policy_fees": ("policy fee", "administrative charge", "expense charge", "policy fees"),
    "nar_definition": ("net amount at risk",),
    "death_benefit": ("death benefit",),
    "crediting": ("credited rate", "interest is credited", "crediting"),
}

_QUALIFICATION_MARKERS = (
    "only if", "provided that", "except when", "except that",
    "unless", "subject to",
)

# Product forms a UL workspace's suggestions must not silently be
# about.  A mention alone is not a case — only a suggestion whose
# own source statement names a different product.
_OTHER_PRODUCTS: Dict[str, str] = {
    "term life": "term life",
    "term insurance": "term life",
    "whole life": "whole life",
    "variable universal life": "variable universal life",
    "indexed universal life": "indexed universal life",
}


# ---------------------------------------------------------------------------
# Typed decision interface (choose / score / truth-probability)
# ---------------------------------------------------------------------------


class DecisionProvider:
    """The typed interface every judgment-tier decision goes through.

    Shapes mirror the calibrated-decision-model role in the design
    note: ``choose`` picks one option id (or None to abstain),
    ``score`` rates one option, ``truth_probability`` prices a
    claim.  Implementations must be able to abstain — an abstention
    escalates; it never guesses.
    """

    def choose(
        self, options: Sequence[Dict[str, Any]], context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def score(self, option: Dict[str, Any], context: Dict[str, Any]) -> float:
        raise NotImplementedError

    def truth_probability(self, claim: str, context: Dict[str, Any]) -> float:
        raise NotImplementedError


class InterimDecisionProvider(DecisionProvider):
    """The current backend as interim judge — UNcalibrated by design.

    ``judge`` is a callable taking a structured context dict and
    returning ``{"choice": <option id>, "rationale": str}`` (or
    None).  ``choose`` runs it TWICE independently and accepts the
    outcome only when both runs agree — self-consistency standing in
    for the calibration this provider does not have.  With no judge
    callable, ``choose`` abstains and the caller escalates.
    """

    def __init__(self, judge: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None):
        self._judge = judge

    def choose(self, options, context):
        if self._judge is None or not options:
            return None
        verdicts: List[Dict[str, Any]] = []
        for _ in range(2):
            try:
                verdict = self._judge(deepcopy(context))
            except Exception:  # noqa: BLE001 - a failing judge abstains
                return None
            if not verdict or verdict.get("choice") not in {o["id"] for o in options}:
                return None
            verdicts.append(verdict)
        if verdicts[0].get("choice") != verdicts[1].get("choice"):
            return None
        return {
            "choice": verdicts[0]["choice"],
            "rationale": str(verdicts[0].get("rationale") or ""),
            "runsAgreed": 2,
            "calibrated": False,
        }

    def score(self, option, context):
        # Corroboration strength, not self-reported confidence: the
        # share of independent documents in the context that carry
        # this option's reading.
        docs = {
            str(c.get("filename"))
            for c in context.get("candidates") or []
            if c.get("filename")
        }
        own = str(option.get("filename") or "")
        if not docs:
            return 0.0
        return 1.0 / len(docs) if own in docs else 0.0

    def truth_probability(self, claim, context):
        # The interim provider has no calibrated probability to give;
        # 0.5 is an honest abstention, and no gate thresholds on it.
        return 0.5


def _openai_judge() -> Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]]:
    """Build a judge callable on the configured model backend.

    Returns None when no backend key is configured — the judgment
    tier then abstains and cases escalate, which is the honest
    outcome for an uncalibrated-or-absent judge.
    """

    if not os.getenv("OPENAI_API_KEY"):
        return None

    def judge(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from actuarypoc.extract.workspace_equations import (
            _chat_json,
            _openai_client_and_model,
        )

        client, model = _openai_client_and_model()
        options = context.get("candidates") or []
        listing = "\n".join(
            f"- id={c.get('id')}: mechanic={c.get('mechanic')} "
            f"reading={c.get('rendering')!r} source={c.get('filename')} "
            f"p.{c.get('page')} statement={str(c.get('statement') or '')[:300]!r}"
            for c in options
        )
        payload = _chat_json(client, model, [
            {"role": "system", "content": (
                "You reconcile two conflicting readings of one insurance "
                "filing mechanic. Choose the reading the filed text best "
                "supports, or abstain. Reply with JSON only: "
                '{"choice": "<id or null>", "rationale": "<one sentence>"}'
            )},
            {"role": "user", "content": (
                f"Mechanic: {context.get('mechanic')}\nCandidates:\n{listing}\n"
                f"Evidence: {json.dumps(context.get('evidence') or [], default=str)[:2000]}"
            )},
        ])
        if not isinstance(payload, dict):
            return None
        return {"choice": payload.get("choice"), "rationale": payload.get("rationale")}

    return judge


# ---------------------------------------------------------------------------
# Availability — stated absence, never silence
# ---------------------------------------------------------------------------


def review_availability() -> "tuple[bool, Optional[str]]":
    """Whether the review pass can run in this process, and if not, why.

    Disabled by ``ACTUARYPOC_HOLISTIC_REVIEW=off`` (or 0/false/no), or
    the backend profile is a small on-prem profile — bounded local
    models are exactly the profiles that cannot spare a second pass —
    unless the review is explicitly forced on.
    """

    mode = os.getenv(REVIEW_ENV, "").strip().lower()
    if mode in {"0", "off", "disabled", "false", "no"}:
        return False, f"disabled by {REVIEW_ENV}"
    profile = os.getenv("ACTUARYPOC_BACKEND_PROFILE", "").strip().lower()
    if profile in {"onprem_small", "small", "appliance_small"} and mode not in {
        "on", "enabled", "force", "1", "true",
    }:
        return False, (
            f"the backend profile ({profile}) is too small for the "
            "holistic review pass"
        )
    return True, None


# ---------------------------------------------------------------------------
# Re-extraction under different slicing
# ---------------------------------------------------------------------------


def _merged_slice(slices: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Concatenate slices into one pseudo-slice with a page-offset map."""

    text_parts: List[str] = []
    page_offsets: List[List[Any]] = []
    offset = 0
    for slice_ in slices:
        text = str(slice_.get("text") or "")
        page = slice_.get("page_start")
        if page is not None:
            page_offsets.append([offset, page])
        text_parts.append(text)
        offset += len(text) + 1
    first = slices[0] if slices else {}
    return {
        "slice_id": "review-merged",
        "doc_id": first.get("doc_id"),
        "document_hint": first.get("document_hint"),
        "page_start": first.get("page_start"),
        "page_end": slices[-1].get("page_end") if slices else None,
        "heading": first.get("heading"),
        "char_start": 0,
        "char_end": offset,
        "text": "\n".join(text_parts),
        "page_offsets": page_offsets,
    }


def regroup_slices_wider(slices: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The review's slicing: different from the pipeline's, on purpose.

    Two regroupings, unioned: (1) each document's slices dispatched
    TOGETHER as one wide unit — cross-references inside a document
    sit in the same context; (2) overlapping consecutive pairs, so a
    statement the first pass cut at a slice boundary is whole in at
    least one unit.  The deterministic harvest over these units is
    the independent re-read the originals are checked against.
    """

    slices = [s for s in slices or [] if isinstance(s, dict)]
    regrouped: List[Dict[str, Any]] = []
    by_document: Dict[str, List[Dict[str, Any]]] = {}
    for slice_ in slices:
        by_document.setdefault(str(slice_.get("document_hint") or ""), []).append(slice_)
    for document_slices in by_document.values():
        if len(document_slices) > 1:
            regrouped.append(_merged_slice(document_slices))
        elif document_slices:
            regrouped.append(document_slices[0])
    for index in range(len(slices) - 1):
        pair = [slices[index], slices[index + 1]]
        if str(pair[0].get("document_hint")) == str(pair[1].get("document_hint")):
            regrouped.append(_merged_slice(pair))
    return regrouped


def _default_reread(slices: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic harvest over the regrouped slices."""

    return list(_ws_eq.deterministic_harvest(regroup_slices_wider(slices)))


def _joint_reread(
    slices: Sequence[Dict[str, Any]], filenames: Sequence[Any]
) -> List[Dict[str, Any]]:
    """Harvest with the named documents' slices dispatched together."""

    wanted = {str(name) for name in filenames if name}
    chosen = [s for s in slices or [] if str(s.get("document_hint")) in wanted]
    if not chosen:
        return []
    return list(_ws_eq.deterministic_harvest([_merged_slice(chosen)]))


# ---------------------------------------------------------------------------
# The suggestion universe — readings the review checks
# ---------------------------------------------------------------------------


def _rendering_for(mechanic: str, body: Optional[Dict[str, Any]], timing: Any) -> Optional[str]:
    if body is None:
        return None
    try:
        if mechanic == "coi_charge":
            return _eq.render_with_timing(body, timing)
        return _eq.render_equation(body, mechanic)
    except Exception:  # noqa: BLE001 - an unrenderable body is not a reading
        return None


def _reading_key(reading: Dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            "mechanic": reading.get("mechanic"),
            "rendering": reading.get("rendering"),
            "statement": " ".join(str(reading.get("statement") or "").lower().split()),
        },
        sort_keys=True, default=str,
    )
    return "rd-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _equation_readings(
    artifact: Dict[str, Any], slices: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Pending equation suggestions: harvested records + fresh harvest."""

    readings: List[Dict[str, Any]] = []
    seen: set = set()

    def add(reading: Dict[str, Any]) -> None:
        key = _reading_key(reading)
        if key in seen:
            return
        seen.add(key)
        reading["id"] = key
        readings.append(reading)

    for record in _ws_eq.records(artifact):
        if record.get("state") != "pending" or record.get("body") is None:
            continue
        source = record.get("source") or {}
        add({
            "kind": "equation",
            "mechanic": str(record.get("mechanic")),
            "rendering": record.get("rendering")
            or _rendering_for(str(record.get("mechanic")), record.get("body"), record.get("timing")),
            "body": deepcopy(record.get("body")),
            "timing": record.get("timing"),
            "statement": source.get("statement"),
            "filename": source.get("filename"),
            "page": source.get("page"),
            "origin": "record",
            "recordId": record.get("id"),
        })
    for candidate in _ws_eq.deterministic_harvest(slices or []):
        mechanic = str(candidate.get("mechanic") or "")
        body = candidate.get("body")
        if body is None and mechanic != "coi_charge":
            continue
        rendering = _rendering_for(mechanic, body, candidate.get("timing"))
        if rendering is None and body is not None:
            continue
        add({
            "kind": "equation",
            "mechanic": mechanic,
            "rendering": rendering,
            "body": deepcopy(body),
            "timing": candidate.get("timing"),
            "statement": candidate.get("statement"),
            "filename": candidate.get("filename"),
            "page": candidate.get("page"),
            "origin": "harvest",
            "recordId": None,
            "assist": candidate.get("assist"),
        })
    return readings


def _reread_readings(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    readings: List[Dict[str, Any]] = []
    seen: set = set()
    for candidate in candidates or []:
        mechanic = str(candidate.get("mechanic") or "")
        body = candidate.get("body")
        if body is None and mechanic != "coi_charge":
            continue
        rendering = _rendering_for(mechanic, body, candidate.get("timing"))
        if rendering is None and body is not None:
            continue
        reading = {
            "kind": "equation",
            "mechanic": mechanic,
            "rendering": rendering,
            "body": deepcopy(body),
            "timing": candidate.get("timing"),
            "statement": candidate.get("statement"),
            "filename": candidate.get("filename"),
            "page": candidate.get("page"),
            "origin": "reread",
            "recordId": None,
            "assist": candidate.get("assist"),
        }
        # Re-reads are per-document evidence: the same statement in
        # a second document is corroboration, not a duplicate, so
        # dedupe is by (reading, document) here — unlike the
        # original universe, where one reading is one suggestion.
        key = (_reading_key(reading), str(candidate.get("filename")))
        if key in seen:
            continue
        seen.add(key)
        reading["id"] = _reading_key(reading)
        readings.append(reading)
    return readings


def _table_readings(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    readings: List[Dict[str, Any]] = []
    for mechanic, candidates in (artifact.get("candidates") or {}).items():
        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("reviewStatus") != "review_required":
                continue
            readings.append({
                "kind": "filed_table",
                "mechanic": str(mechanic),
                "candidateId": str(candidate.get("id") or ""),
                "rowCount": candidate.get("rowCount") or len(candidate.get("rows") or []),
                "filename": candidate.get("filename"),
                "page": candidate.get("page"),
                "rows": list(candidate.get("rows") or []),
            })
    return readings


# ---------------------------------------------------------------------------
# Reconciliation ladder helpers
# ---------------------------------------------------------------------------


def _standing(reading: Dict[str, Any]) -> "tuple[int, List[str]]":
    """Source standing: a document that DEFINES a mechanic governs
    over one that mentions or illustrates it."""

    score = 0
    reasons: List[str] = []
    statement = str(reading.get("statement") or "").lower()
    filename = str(reading.get("filename") or "").lower()
    if any(phrase in statement for phrase in (
        "is defined as", "means", "is calculated as", "is equal to",
        "charge is", "equals",
    )):
        score += 2
        reasons.append("its statement is definitional")
    if any(token in filename for token in ("spec", "form", "policy")):
        score += 1
        reasons.append("it is filed in the policy form / specifications")
    if "memo" in filename or "memorandum" in filename:
        score += 1
        reasons.append("it is filed in the actuarial memorandum")
    if any(phrase in statement for phrase in (
        "for example", "illustrat", "summary of", "approximately",
    )):
        score -= 2
        reasons.append("its statement mentions / illustrates rather than defines")
    return score, reasons


def _percent_of_premium(body: Any) -> Optional[float]:
    """The const percentage of a premium-load style body, if it is one."""

    if not isinstance(body, dict):
        return None
    mul = body.get("mul")
    if isinstance(mul, list):
        for node in mul:
            if isinstance(node, dict) and isinstance(node.get("const"), (int, float)):
                return float(node["const"])
    if isinstance(body.get("const"), (int, float)):
        return float(body["const"])
    return None


def _filed_premium_percent(artifact: Dict[str, Any]) -> Optional[float]:
    """The premium-expense percentage the filed fee TABLE carries —
    the deterministic channel's arithmetic constraint on prose readings."""

    for candidate in (artifact.get("candidates") or {}).get("fees") or []:
        for row in candidate.get("rows") or []:
            if str(row.get("component") or "") != "premium_expense":
                continue
            if str(row.get("fee_unit") or "") != "percent_premium":
                continue
            amount = row.get("amount")
            if isinstance(amount, (int, float)):
                return float(amount) / 100.0 if float(amount) > 1 else float(amount)
    for row in (artifact.get("usable") or {}).get("fees") or []:
        if str(row.get("component") or "") != "premium_expense":
            continue
        if str(row.get("fee_unit") or "") != "percent_premium":
            continue
        amount = row.get("amount")
        if isinstance(amount, (int, float)):
            return float(amount) / 100.0 if float(amount) > 1 else float(amount)
    return None


def _new_case(
    *, kind: str, mechanic: str, candidates: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]], localized: bool,
) -> Dict[str, Any]:
    canonical = json.dumps(
        {"kind": kind, "mechanic": mechanic,
         "candidates": sorted(c.get("id") or c.get("candidateId") or "" for c in candidates)},
        sort_keys=True, default=str,
    )
    return {
        "id": "case-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12],
        "kind": kind,
        "mechanic": mechanic,
        "candidates": [
            {
                "id": c.get("id") or c.get("candidateId"),
                "kind": c.get("kind"),
                "rendering": c.get("rendering"),
                "candidateId": c.get("candidateId"),
                "recordId": c.get("recordId"),
                "filename": c.get("filename"),
                "page": c.get("page"),
                "statement": c.get("statement"),
                "origin": c.get("origin"),
            }
            for c in candidates
        ],
        "evidence": evidence,
        "localized": bool(localized),
        "status": "open",
        "ladderStep": None,
        "rationale": None,
        "winnerId": None,
        "loserIds": [],
        "repairAttempted": False,
        "repairProducedRival": False,
        "verificationOutcome": None,
        # Features recorded for later calibration / shadow evaluation
        # against VERIFIABLE outcomes.  Human clicks are workflow
        # data and are never written here as correctness labels.
        "evidenceFeatures": {
            "candidateCount": len(candidates),
            "distinctDocuments": len({
                str(c.get("filename")) for c in candidates if c.get("filename")
            }),
            "origins": sorted({str(c.get("origin") or "") for c in candidates}),
        },
    }


def _evidence_for(reading: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "filename": reading.get("filename"),
        "page": reading.get("page"),
        "snippet": str(reading.get("statement") or "")[:300] or None,
        "rendering": reading.get("rendering"),
    }


def _resolve(
    case: Dict[str, Any], *, step: str, winner: Dict[str, Any],
    losers: List[Dict[str, Any]], rationale: str,
) -> None:
    case["status"] = "resolved"
    case["ladderStep"] = step
    case["rationale"] = rationale
    case["winnerId"] = winner.get("id") or winner.get("candidateId")
    case["loserIds"] = [
        loser.get("id") or loser.get("candidateId") for loser in losers
    ]
    case["verificationOutcome"] = "reconciled"


def _escalate(case: Dict[str, Any], *, rationale: str) -> None:
    case["status"] = "escalated"
    case["ladderStep"] = "escalation"
    case["rationale"] = rationale
    case["verificationOutcome"] = "escalated_to_human"


def _supported_by_text(
    candidates: List[Dict[str, Any]], text: str
) -> List[Dict[str, Any]]:
    """Which candidates' own statements the combined text carries.

    The joint / repair re-reads dispatch several documents as one
    unit; the deterministic harvest over such a unit reports only
    the first match per pattern, which would crown whichever
    statement happens to come first.  Support is therefore judged
    by containment: a candidate is supported when its verbatim
    statement is present in the combined text.
    """

    canon = _ws_eq.canon_text(text)
    supported: List[Dict[str, Any]] = []
    for candidate in candidates:
        statement = candidate.get("statement")
        if not statement:
            continue
        needle = _ws_eq.canon_text(statement)
        if needle and needle in canon:
            supported.append(candidate)
    return supported


def _run_equation_ladder(
    case: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    *,
    artifact: Dict[str, Any],
    slices: Sequence[Dict[str, Any]],
    rereads: List[Dict[str, Any]],
    provider: DecisionProvider,
    repair_state: Dict[str, Any],
    add_rival: Callable[[Dict[str, Any], Dict[str, Any]], Optional[Dict[str, Any]]],
    judge_budget: Dict[str, int],
) -> None:
    """Walk the reconciliation ladder for one divergence case.

    Order (Billy, Oct 27, 2026): deterministic rules -> joint re-read
    -> one bounded repair round (localized cases) -> source standing
    -> reasoned judgment (uncalibrated: two agreeing runs plus filed
    corroboration).  Anything else escalates.
    """

    mechanic = str(case.get("mechanic") or "")

    # (a) Deterministic — filed arithmetic constraints.  For a
    # premium-load divergence, the filed fee table's premium-expense
    # percentage is a deterministic fact of the deterministic
    # channel: the prose reading that satisfies it wins.
    if mechanic == "premium_load":
        filed_pct = _filed_premium_percent(artifact)
        if filed_pct is not None:
            matching = [
                c for c in candidates
                if _percent_of_premium(c.get("body")) is not None
                and abs(float(_percent_of_premium(c.get("body"))) - filed_pct) < 1e-9
            ]
            if len(matching) == 1 and len(candidates) > 1:
                winner = matching[0]
                _resolve(
                    case, step="deterministic_arithmetic", winner=winner,
                    losers=[c for c in candidates if c is not winner],
                    rationale=(
                        "The filed fee table carries the premium-expense "
                        f"charge at {filed_pct:.0%} of premium; only one "
                        "reading satisfies that filed arithmetic, so it "
                        "stands and the other is withdrawn."
                    ),
                )
                return

    # (b) Joint re-read — both sources dispatched together; the
    # reading the combined text supports stands.
    filenames = [c.get("filename") for c in candidates if c.get("filename")]
    if slices and filenames:
        joint_slices = [
            s for s in slices
            if str(s.get("document_hint")) in {str(f) for f in filenames}
        ]
        joint_text = "\n".join(str(s.get("text") or "") for s in joint_slices)
        supported = _supported_by_text(candidates, joint_text)
        if not supported:
            joint = _reread_readings(_joint_reread(slices, filenames))
            joint_renderings = {
                r.get("rendering") for r in joint if r.get("mechanic") == mechanic
            }
            supported = [
                c for c in candidates if c.get("rendering") in joint_renderings
            ]
        if len(supported) == 1 and len(candidates) > 1:
            winner = supported[0]
            _resolve(
                case, step="joint_reread", winner=winner,
                losers=[c for c in candidates if c is not winner],
                rationale=(
                    "Re-read with both sources dispatched together, the "
                    "combined text supports only this reading; the other "
                    "is withdrawn."
                ),
            )
            return

    # Repair — ONE bounded round for a localized case: every source
    # dispatched as one cross-referenced unit (framing pages in the
    # same context as the statements).  A new reading arrives as a
    # RIVAL beside the originals, never a replacement — and a case
    # with a live rival is a human's, so it escalates with the rival
    # named in its evidence.
    if case.get("localized") and repair_state["used"] < _MAX_REPAIRS and slices:
        repair_state["used"] += 1
        case["repairAttempted"] = True
        repair_readings = _reread_readings(
            _ws_eq.deterministic_harvest([_merged_slice(list(slices))])
        )
        known = {c.get("rendering") for c in candidates}
        fresh = [
            r for r in repair_readings
            if r.get("mechanic") == mechanic
            and r.get("rendering") not in known
            and r.get("body") is not None
        ]
        if fresh:
            rival = add_rival(case, fresh[0])
            case["repairProducedRival"] = True
            if rival is not None:
                case["evidence"] = list(case.get("evidence") or []) + [
                    _evidence_for(rival)
                ]
            _escalate(
                case,
                rationale=(
                    "A repair re-read with the cross-referenced documents "
                    "together produced a further reading, which now stands "
                    "as a rival beside the originals — a person chooses "
                    "between rival readings."
                ),
            )
            return
        repair_text = "\n".join(str(s.get("text") or "") for s in slices)
        supported = _supported_by_text(candidates, repair_text)
        if not supported:
            repair_renderings = {
                r.get("rendering") for r in repair_readings
                if r.get("mechanic") == mechanic
            }
            supported = [
                c for c in candidates if c.get("rendering") in repair_renderings
            ]
        if len(supported) == 1 and len(candidates) > 1:
            winner = supported[0]
            _resolve(
                case, step="repair_reread", winner=winner,
                losers=[c for c in candidates if c is not winner],
                rationale=(
                    "A repair re-read with the documents dispatched "
                    "together supports only this reading; the other is "
                    "withdrawn."
                ),
            )
            return

    # (c) Source standing — the defining document governs over one
    # that mentions or illustrates.
    scored = [(_standing(c), c) for c in candidates]
    scored.sort(key=lambda item: item[0][0], reverse=True)
    if len(scored) > 1 and scored[0][0][0] - scored[1][0][0] >= 2:
        (score, reasons), winner = scored[0]
        _resolve(
            case, step="source_standing", winner=winner,
            losers=[c for _, c in scored[1:]],
            rationale=(
                "Source standing: the winning reading's document governs "
                f"({'; '.join(reasons) or 'it defines the mechanic'}), "
                "while the other mentions or illustrates it."
            ),
        )
        return

    # (d) Reasoned judgment — uncalibrated, so structure compensates:
    # two independent runs must agree, and the winner must carry
    # filed corroboration (its reading stated in at least two
    # distinct documents across the original and wider re-reads).
    if judge_budget["used"] < _MAX_JUDGED_CASES:
        judge_budget["used"] += 1
        options = [
            {
                "id": c.get("id"), "mechanic": mechanic,
                "rendering": c.get("rendering"), "filename": c.get("filename"),
            }
            for c in candidates
        ]
        verdict = provider.choose(options, {
            "mechanic": mechanic,
            "candidates": case.get("candidates") or [],
            "evidence": case.get("evidence") or [],
        })
        if verdict is not None:
            winner = next(
                (c for c in candidates if c.get("id") == verdict.get("choice")),
                None,
            )
            if winner is not None:
                docs = {
                    str(r.get("filename"))
                    for r in list(candidates) + list(rereads)
                    if r.get("mechanic") == mechanic
                    and r.get("rendering") == winner.get("rendering")
                    and r.get("filename")
                }
                if len(docs) >= 2:
                    _resolve(
                        case, step="reasoned_judgment", winner=winner,
                        losers=[c for c in candidates if c is not winner],
                        rationale=(
                            "Reasoned judgment (uncalibrated backend; two "
                            "independent runs agreed) with filed "
                            f"corroboration in {len(docs)} documents: "
                            + str(verdict.get("rationale") or "")
                        ).strip(),
                    )
                    return

    _escalate(
        case,
        rationale=(
            "The reconciliation ladder could not settle this divergence: "
            "no deterministic rule decides it, the joint re-read supports "
            "no single reading, source standing does not separate the "
            "sources, and judgment is unavailable, divided, or "
            "uncorroborated. Two filed sources may truly contradict each "
            "other — a person must decide."
        ),
    )


# ---------------------------------------------------------------------------
# The pass itself
# ---------------------------------------------------------------------------

_EQUATION_SLOT: Dict[str, str] = {
    "coi_charge": "coi",
    "surrender_charge": "surrender",
    "premium_load": "fees",
    "policy_fees": "fees",
    "nar_definition": "nar",
    "death_benefit": "corridor",
    "crediting": "crediting",
}


def run_holistic_review(
    artifact: Dict[str, Any],
    slices: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    snapshot: Optional[Dict[str, Any]] = None,
    at: str = "",
    provider: Optional[DecisionProvider] = None,
    judge: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
    reread: Optional[Callable[[Sequence[Dict[str, Any]]], List[Dict[str, Any]]]] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Run the review pass over one analysis's candidates.

    Returns ``{"artifact", "review"}`` — the artifact is a copy with
    the review record persisted on it (``holisticReview``) and the
    verification / reconciliation / flag outcomes attached to the
    records and candidates they concern.  Nothing is approved,
    accepted, or put in force here, ever.
    """

    result = deepcopy(artifact or {})
    slices = list(slices or [])
    available, reason = review_availability()
    if not available:
        review: Dict[str, Any] = {
            "status": "absent",
            "reason": reason,
            "statement": (
                f"Holistic review did not run: {reason}. The suggestions "
                "below carry no independent re-read or reconciliation."
            ),
            "ranAt": at or None,
            "verifications": [],
            "cases": [],
            "flags": [],
            "found": [],
            "decisionLog": [],
        }
        result["holisticReview"] = review
        return {"artifact": result, "review": review}

    def _emit(detail: str) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback({"stage": "holistic_review", "detail": detail})
        except Exception:  # noqa: BLE001 - progress must never fail the run
            pass

    _emit("Holistic review — independently re-reading the suggestions")
    if provider is None:
        provider = InterimDecisionProvider(
            judge if judge is not None else _openai_judge()
        )
    reread_fn = reread or _default_reread

    originals = _equation_readings(result, slices)
    table_readings = _table_readings(result)
    rereads = _reread_readings(reread_fn(slices) if slices else [])

    verifications: List[Dict[str, Any]] = []
    cases: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []
    found: List[Dict[str, Any]] = []

    def _record(record_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not record_id:
            return None
        return next(
            (r for r in _ws_eq.records(result) if r.get("id") == record_id),
            None,
        )

    def _attach_verification(reading: Dict[str, Any], entry: Dict[str, Any]) -> None:
        record = _record(reading.get("recordId"))
        if record is not None:
            (record.setdefault("source", {}))["reviewVerification"] = {
                "status": entry["status"],
                "evidence": entry["evidence"],
                "at": at or None,
            }

    # -- Self-check: agreement attaches verification evidence --------
    for reading in originals:
        if not reading.get("rendering"):
            continue
        matches = [
            r for r in rereads
            if r.get("mechanic") == reading.get("mechanic")
            and r.get("rendering") == reading.get("rendering")
        ]
        if not matches:
            continue
        also = next(
            (m for m in matches
             if m.get("filename") and m.get("filename") != reading.get("filename")),
            None,
        )
        evidence = "independently re-read with wider context — identical"
        if also is not None:
            evidence += f"; also stated in {also.get('filename')}, p. {also.get('page')}"
        entry = {
            "targetKind": "equation",
            "mechanic": reading.get("mechanic"),
            "rendering": reading.get("rendering"),
            "recordId": reading.get("recordId"),
            "status": "verified",
            "evidence": evidence,
            "alsoStatedIn": (
                {"filename": also.get("filename"), "page": also.get("page")}
                if also is not None else None
            ),
        }
        verifications.append(entry)
        _attach_verification(reading, entry)

    # -- Self-check: a mechanic the first pass missed, found by the
    # wider re-read.  It materializes as an ordinary PENDING record
    # (a suggestion, never an approval) and reconciles the header.
    original_mechanics = {r.get("mechanic") for r in originals}
    for reading in rereads:
        mechanic = str(reading.get("mechanic") or "")
        if mechanic in original_mechanics or reading.get("body") is None:
            continue
        original_mechanics.add(mechanic)
        record = _ws_eq.new_record(
            mechanic=mechanic,
            body=reading.get("body"),
            state="pending",
            source={
                "kind": "document",
                "statement": reading.get("statement"),
                "filename": reading.get("filename"),
                "page": reading.get("page"),
                "assist": "holistic_review_reread",
                "note": (
                    "Found by the holistic review's wider re-read; the "
                    "first-pass slicing did not surface this statement."
                ),
            },
            at=at or "",
            timing=reading.get("timing"),
        )
        result.setdefault("equations", []).append(record)
        found.append({
            "mechanic": mechanic,
            "slot": _EQUATION_SLOT.get(mechanic),
            "check": "self_check_reread",
            "rationale": (
                "The wider re-read found a stated "
                f"{_eq.MECHANIC_LABELS.get(mechanic, mechanic)} the first "
                "pass missed; it is now a pending suggestion."
            ),
            "filename": reading.get("filename"),
            "page": reading.get("page"),
            "recordId": record.get("id"),
        })
        verifications.append({
            "targetKind": "equation",
            "mechanic": mechanic,
            "rendering": reading.get("rendering"),
            "recordId": record.get("id"),
            "status": "found_by_review",
            "evidence": (
                "found by the holistic review's wider re-read in "
                f"{reading.get('filename')}, p. {reading.get('page')}"
            ),
            "alsoStatedIn": None,
        })

    # -- Filed tables: deterministic self-check + slice relations ---
    def _candidate_dict(reading: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for candidate in (result.get("candidates") or {}).get(
            str(reading.get("mechanic")) or ""
        ) or []:
            if str(candidate.get("id") or "") == str(reading.get("candidateId") or ""):
                return candidate
        return None

    for reading in table_readings:
        rows = list(reading.get("rows") or [])
        by_selector: Dict[Any, Dict[str, Any]] = {}
        internal_conflicts = 0
        from actuarypoc.extract.workspace_ul_mechanics import (
            row_selector_key,
            row_value_key,
        )

        for row in rows:
            key = row_selector_key(row)
            if key in by_selector and row_value_key(
                str(reading.get("mechanic")), by_selector[key]
            ) != row_value_key(str(reading.get("mechanic")), row):
                internal_conflicts += 1
            by_selector.setdefault(key, row)
        candidate = _candidate_dict(reading)
        if internal_conflicts:
            case = _new_case(
                kind="filed_table_internal_conflict",
                mechanic=str(reading.get("mechanic")),
                candidates=[reading],
                evidence=[{
                    "filename": reading.get("filename"),
                    "page": reading.get("page"),
                    "snippet": (
                        f"{internal_conflicts} selector(s) priced two ways "
                        "inside this one filed table"
                    ),
                    "rendering": None,
                }],
                localized=True,
            )
            _escalate(case, rationale=(
                "This filed table prices the same selector two different "
                "ways within itself; no deterministic rule can choose "
                "between a filing's own rows."
            ))
            cases.append(case)
            continue
        entry = {
            "targetKind": "filed_table",
            "mechanic": reading.get("mechanic"),
            "candidateId": reading.get("candidateId"),
            "status": "verified",
            "evidence": (
                f"rows re-checked deterministically — {len(rows)} rows, "
                "no selector priced two ways"
            ),
            "alsoStatedIn": None,
        }
        verifications.append(entry)
        if candidate is not None:
            candidate["reviewVerification"] = {
                "status": "verified",
                "evidence": entry["evidence"],
                "at": at or None,
            }

    by_mechanic_tables: Dict[str, List[Dict[str, Any]]] = {}
    for reading in table_readings:
        by_mechanic_tables.setdefault(str(reading.get("mechanic")), []).append(reading)
    for mechanic, group in by_mechanic_tables.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                conflicts = conflicting_row_selectors(
                    mechanic,
                    candidate_effective_rows(_candidate_dict(a) or a),
                    candidate_effective_rows(_candidate_dict(b) or b),
                )
                if not conflicts:
                    identical = (
                        json.dumps(a.get("rows"), sort_keys=True, default=str)
                        == json.dumps(b.get("rows"), sort_keys=True, default=str)
                    )
                    case = _new_case(
                        kind="table_slice_relationship",
                        mechanic=mechanic, candidates=[a, b],
                        evidence=[_evidence_for(a), _evidence_for(b)],
                        localized=True,
                    )
                    case["status"] = "resolved"
                    case["ladderStep"] = "deterministic_identical_merge" if identical else "deterministic_selector_union"
                    case["rationale"] = (
                        "Identical content filed twice — one slice, not "
                        "two readings." if identical else
                        "Selector-disjoint slices of one table — they "
                        "union; they do not conflict."
                    )
                    case["verificationOutcome"] = "reconciled"
                    cases.append(case)
                    continue
                case = _new_case(
                    kind="filed_table_conflict",
                    mechanic=mechanic, candidates=[a, b],
                    evidence=[_evidence_for(a), _evidence_for(b)],
                    localized=True,
                )
                _escalate(case, rationale=(
                    f"Two filed tables price {len(conflicts)} selector(s) "
                    "differently where their coverage overlaps. The "
                    "deterministic table channel is never re-sliced by "
                    "the model, and picking a winner would invent the "
                    "carrier's intent — a person chooses which governs."
                ))
                cases.append(case)


    # -- Equation divergences -> reconciliation cases ----------------
    repair_state = {"used": 0}
    judge_budget = {"used": 0}

    def _add_rival(case: Dict[str, Any], fresh: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        mechanic = str(fresh.get("mechanic") or "")
        if fresh.get("body") is None:
            return None
        errors = _eq.validate_equation(mechanic, fresh["body"])
        if errors:
            return None
        record = _ws_eq.new_record(
            mechanic=mechanic,
            body=fresh.get("body"),
            state="pending",
            source={
                "kind": "document",
                "statement": fresh.get("statement"),
                "filename": fresh.get("filename"),
                "page": fresh.get("page"),
                "assist": "holistic_review_repair",
                "reviewCaseId": case.get("id"),
                "note": (
                    "Produced by the holistic review's repair re-read "
                    f"for case {case.get('id')}; it stands as a rival "
                    "beside the original reading, never a replacement."
                ),
            },
            at=at or "",
            timing=fresh.get("timing"),
        )
        result.setdefault("equations", []).append(record)
        rival = dict(fresh)
        rival["origin"] = "repair"
        rival["recordId"] = record.get("id")
        rival["id"] = _reading_key(rival)
        return rival

    by_mechanic: Dict[str, List[Dict[str, Any]]] = {}
    for reading in originals:
        by_mechanic.setdefault(str(reading.get("mechanic")), []).append(reading)
    for reading in rereads:
        mechanic = str(reading.get("mechanic"))
        group = by_mechanic.setdefault(mechanic, [])
        if reading.get("rendering") and reading.get("rendering") not in {
            r.get("rendering") for r in group
        }:
            group.append(reading)

    divergence_cases: List[Any] = []
    for mechanic, group in by_mechanic.items():
        distinct: Dict[str, Dict[str, Any]] = {}
        for reading in group:
            if reading.get("rendering"):
                distinct.setdefault(str(reading["rendering"]), reading)
        if len(distinct) < 2:
            continue
        candidates = list(distinct.values())
        case = _new_case(
            kind="self_check_divergence",
            mechanic=mechanic,
            candidates=candidates,
            evidence=[_evidence_for(c) for c in candidates],
            localized=all(
                c.get("filename") and c.get("statement") for c in candidates
            ),
        )
        divergence_cases.append((case, candidates))
        cases.append(case)

    for case, candidates in divergence_cases:
        _run_equation_ladder(
            case, candidates,
            artifact=result, slices=slices, rereads=rereads,
            provider=provider, repair_state=repair_state,
            add_rival=_add_rival, judge_budget=judge_budget,
        )

    # -- Cross-product mentions --------------------------------------
    product = (snapshot or {}).get("product") or {}
    product_type = str(product.get("type") or "").strip().lower()
    product_name = str(product.get("name") or "").strip().lower()
    for reading in originals:
        statement = str(reading.get("statement") or "").lower()
        if not statement:
            continue
        for term, label in _OTHER_PRODUCTS.items():
            if term not in statement:
                continue
            if label in product_type or label in product_name:
                continue
            case = _new_case(
                kind="cross_product_mention",
                mechanic=str(reading.get("mechanic")),
                candidates=[reading],
                evidence=[_evidence_for(reading)],
                localized=bool(reading.get("filename")),
            )
            if any(marker in statement for marker in ("unlike", "compared")):
                case["status"] = "resolved"
                case["ladderStep"] = "deterministic_framing"
                case["rationale"] = (
                    f"The source mentions {label} comparatively; the "
                    "reading itself is this product's."
                )
                case["verificationOutcome"] = "reconciled"
            else:
                _escalate(case, rationale=(
                    f"This suggestion's own source statement names a "
                    f"different product ({label}); whether it belongs "
                    "to this workspace's product is a person's call."
                ))
            cases.append(case)
            break

    # -- Framing loss -------------------------------------------------
    canon_statement: Dict[str, str] = {
        str(r.get("id")): _ws_eq.canon_text(r.get("statement") or "")
        for r in originals
    }
    for reading in originals:
        mechanic = str(reading.get("mechanic"))
        keywords = _MECHANIC_KEYWORDS.get(mechanic) or ()
        if not keywords:
            continue
        found_case = False
        for slice_ in slices:
            if str(slice_.get("document_hint")) == str(reading.get("filename")):
                continue
            text = str(slice_.get("text") or "")
            for sentence in re.split(r"(?<=[.!?])\s+", text):
                lowered = sentence.lower()
                if not any(keyword in lowered for keyword in keywords):
                    continue
                if not any(marker in lowered for marker in _QUALIFICATION_MARKERS):
                    continue
                if _ws_eq.canon_text(sentence) in canon_statement.get(str(reading.get("id")), ""):
                    continue
                qualification = " ".join(sentence.split())[:300]
                case = _new_case(
                    kind="framing_loss",
                    mechanic=mechanic,
                    candidates=[reading],
                    evidence=[_evidence_for(reading), {
                        "filename": slice_.get("document_hint"),
                        "page": slice_.get("page_start"),
                        "snippet": qualification,
                        "rendering": None,
                    }],
                    localized=True,
                )
                # Joint re-read of both documents together: if the
                # combined text still supports the reading, the
                # qualification is recorded in its provenance and
                # the case resolves; otherwise it escalates with
                # the missing text quoted.
                joint = _reread_readings(_joint_reread(
                    slices, [reading.get("filename"), slice_.get("document_hint")]
                ))
                if any(
                    r.get("mechanic") == mechanic
                    and r.get("rendering") == reading.get("rendering")
                    for r in joint
                ):
                    case["status"] = "resolved"
                    case["ladderStep"] = "joint_reread"
                    case["rationale"] = (
                        "Re-read with both documents together, the "
                        "reading stands; the qualification stated in "
                        f"{slice_.get('document_hint')} is recorded "
                        "with it: “" + qualification + "”"
                    )
                    case["verificationOutcome"] = "reconciled"
                    record = _record(reading.get("recordId"))
                    if record is not None:
                        (record.setdefault("source", {}))["framingNote"] = qualification
                else:
                    _escalate(case, rationale=(
                        "A qualification stated in "
                        f"{slice_.get('document_hint')} does not reach "
                        "this suggestion, and a joint re-read did not "
                        "settle how it applies — a person reviews it "
                        "with the qualification quoted in the evidence."
                    ))
                cases.append(case)
                found_case = True
                break
            if found_case:
                break


    # -- Apply case outcomes ------------------------------------------
    # A reconciled case presents ONE suggestion: the losing readings
    # are withdrawn as pending suggestions (a record loser is
    # superseded — preserved, never deleted) and the winner carries
    # the resolution in its provenance.  An escalated case raises a
    # flag on every candidate it names.
    all_readings: Dict[str, Dict[str, Any]] = {}
    for reading in originals + rereads:
        all_readings[str(reading.get("id"))] = reading

    for case in cases:
        if case.get("status") == "resolved" and case.get("winnerId"):
            winner = all_readings.get(str(case["winnerId"])) or next(
                (c for c in case.get("candidates") or []
                 if (c.get("id") or c.get("candidateId")) == case["winnerId"]),
                None,
            )
            losers = [
                c for c in case.get("candidates") or []
                if (c.get("id") or c.get("candidateId")) != case["winnerId"]
            ]
            case["losingReadings"] = [
                {
                    "rendering": loser.get("rendering"),
                    "filename": loser.get("filename"),
                    "page": loser.get("page"),
                    "statement": loser.get("statement"),
                }
                for loser in losers
            ]
            winner_record = _record((winner or {}).get("recordId"))
            if winner_record is not None:
                (winner_record.setdefault("source", {}))["reviewReconciliation"] = {
                    "caseId": case.get("id"),
                    "ladderStep": case.get("ladderStep"),
                    "rationale": case.get("rationale"),
                    "losingReadings": case["losingReadings"],
                }
            for loser in losers:
                loser_reading = all_readings.get(str(loser.get("id"))) or loser
                loser_record = _record(loser_reading.get("recordId"))
                if loser_record is not None and loser_record.get("state") == "pending":
                    loser_record["state"] = "superseded"
                    loser_record["updatedAt"] = at or loser_record.get("updatedAt")
                    source = loser_record.setdefault("source", {})
                    source["reviewReconciliation"] = {
                        "caseId": case.get("id"),
                        "ladderStep": case.get("ladderStep"),
                        "rationale": case.get("rationale"),
                        "outcome": "withdrawn — the reconciled reading stands",
                    }
        elif case.get("status") == "escalated":
            targets: List[Dict[str, Any]] = []
            for candidate in case.get("candidates") or []:
                target = {
                    "kind": candidate.get("kind"),
                    "mechanic": case.get("mechanic"),
                    "rendering": candidate.get("rendering"),
                    "candidateId": candidate.get("candidateId"),
                    "recordId": candidate.get("recordId"),
                }
                targets.append(target)
                reading = all_readings.get(str(candidate.get("id"))) or candidate
                record = _record(reading.get("recordId") or candidate.get("recordId"))
                if record is not None:
                    (record.setdefault("source", {}))["reviewFlag"] = {
                        "caseId": case.get("id"),
                        "reason": case.get("rationale"),
                    }
                if candidate.get("candidateId"):
                    table_reading = {
                        "mechanic": case.get("mechanic"),
                        "candidateId": candidate.get("candidateId"),
                    }
                    candidate_dict = _candidate_dict(table_reading)  # type: ignore[arg-type]
                    if candidate_dict is not None:
                        candidate_dict["reviewFlag"] = {
                            "caseId": case.get("id"),
                            "reason": case.get("rationale"),
                        }
            flags.append({
                "id": "flag-" + str(case.get("id"))[5:],
                "caseId": case.get("id"),
                "kind": case.get("kind"),
                "mechanic": case.get("mechanic"),
                "status": "unresolved",
                "reason": case.get("rationale"),
                "evidence": case.get("evidence") or [],
                "targets": targets,
            })

    _emit(
        "Holistic review — "
        f"{len(verifications)} verified, {len(cases)} case(s), "
        f"{len(flags)} flag(s)"
    )
    review = {
        "status": "ran",
        "reason": None,
        "statement": (
            "Holistic review ran: suggestions were independently "
            "re-read under wider slicing, divergences were reconciled "
            "by the ladder or escalated with their evidence, and "
            "nothing was approved by the review."
        ),
        "ranAt": at or None,
        "checks": [
            "self_check_reread", "cross_product_mentions",
            "framing_loss", "summary_contradictions",
        ],
        "verifications": verifications,
        "cases": cases,
        "flags": flags,
        "found": found,
        # The decision log IS the case list: candidates, evidence
        # features, the ladder step that resolved each case (or its
        # escalation), the rationale, and the verification outcome —
        # persisted with the analysis record for later calibration
        # and shadow evaluation against verifiable outcomes.
        "decisionLog": cases,
        "counts": {
            "verified": sum(1 for v in verifications if v.get("status") == "verified"),
            "foundByReview": len(found),
            "cases": len(cases),
            "resolved": sum(1 for c in cases if c.get("status") == "resolved"),
            "escalated": sum(1 for c in cases if c.get("status") == "escalated"),
            "flags": len(flags),
            "repairsAttempted": repair_state["used"],
        },
    }
    result["holisticReview"] = review
    return {"artifact": result, "review": review}
