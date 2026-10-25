"""Phase 5 (the validation harness): test-case packs for a workspace.

Eddy's working discipline (Aug 7, 2026) is "refine, refine until it
matches": actuaries keep test cases with expected results — from the
carrier's own illustration, the admin system, or the filing itself —
and check the model against them.  Three systems (admin, illustration,
actuarial models) must agree, and auditors back the math out of the
contract.  This module productises that discipline:

* A **pack** is a versioned, file-based document stored with the
  workspace (object store, alongside the analysis artifacts).  Each
  case names a scenario (policy inputs plus the mechanics state it
  assumes) and a list of expectations: a field at a duration, the
  expected value, the *source* of that expectation (filing page,
  illustration, admin-system export — provenance is mandatory), and a
  tolerance.
* The **runner** executes each case through the existing projection
  path and reads actuals from the Phase 1 ledger — the same numbers
  the actuary sees in the product, never a parallel calculation.  It
  is deterministic and involves no model.
* The **diff** compares expected vs actual cell by cell with signed
  deltas and per-field tolerances, and records the ledger basis of
  every actual (filed / synthetic / workspace table / corrected /
  placeholder / scenario / calculated).  A mismatch on a placeholder
  line explains itself: the number rests on a stand-in, not a filed
  value.  That explanation is a deliverable, not an excuse.
* A **run** is persisted with the workspace: pack identity and
  version, the rule-bank switches the run executed (Phase 4's
  appliedMechanics), a fingerprint of the mechanics state each case
  ran against, who ran it and when, and — versus the previous run of
  the same pack — which expectations newly pass, newly fail, and which
  cases' mechanics moved.  Re-running a pack after a slot edit, a
  correction, or a bank change is the regression story.

Pack format version 1 (``formatVersion``).  Unknown versions are
rejected with a specific error rather than silently misread.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import uuid


PACK_FORMAT_VERSION = 1

# ---------------------------------------------------------------------------
# Expectation fields
#
# A pack expectation names a field in product language; the registry
# maps it to the Phase 1 ledger row key that carries the actual and
# the ledger component whose derivation (and basis) explains it.  New
# fields enter by extending this registry only.
# ---------------------------------------------------------------------------

# field -> (ledger row key, ledger component id or None, display label)
FIELD_REGISTRY: Dict[str, Tuple[str, Optional[str], str]] = {
    "accountValue": ("endingValue", "ending_value", "Account value"),
    "beginningValue": ("beginningValue", "opening_value", "Beginning account value"),
    "premium": ("premium", "premium", "Premium paid"),
    "premiumLoad": ("premiumLoad", "premium_load", "Premium expense charge"),
    "policyFee": ("policyFee", "policy_fee", "Policy and admin fees"),
    "coiCharge": ("coiCharge", "coi", "Cost of insurance (COI)"),
    "interestCredited": ("interestCredited", "interest", "Interest credited"),
    "surrenderCharge": ("surrenderCharge", "surrender_charge", "Surrender charge"),
    "surrenderValue": ("surrenderValue", "surrender_value", "Surrender value"),
    "deathBenefit": ("deathBenefit", "death_benefit", "Death benefit"),
    "netAmountAtRisk": ("netAmountAtRisk", "net_amount_at_risk", "Net amount at risk"),
    "cumulativePremium": ("cumulativePremium", None, "Cumulative premium"),
}

DEFAULT_TOLERANCE = {"absolute": 0.01, "relative": 0.0}

MAX_CASES_PER_PACK = 50
MAX_EXPECTATIONS_PER_CASE = 500
MAX_DURATION = 200

# Float-representation guard: a delta within this of the tolerance
# band still counts as inside it.  Far below any actuarial tolerance.
_EPSILON = 1e-9

_STANDIN_BASES = {"placeholder", "synthetic"}


class PackValidationError(ValueError):
    """A pack document that fails validation, with every problem named."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = [str(problem) for problem in problems]
        super().__init__("; ".join(self.problems))


def new_pack_id() -> str:
    return f"pack-{uuid.uuid4().hex[:8]}"


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Validation + normalisation
# ---------------------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _validate_tolerance(
    raw: Any, where: str, problems: List[str]
) -> Optional[Dict[str, float]]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        problems.append(
            f"{where}: tolerance must be an object with 'absolute' and/or 'relative'"
        )
        return None
    out: Dict[str, float] = {}
    for key in ("absolute", "relative"):
        value = raw.get(key)
        if value is None:
            continue
        if not _is_number(value) or float(value) < 0:
            problems.append(f"{where}: tolerance.{key} must be a number >= 0")
            continue
        out[key] = float(value)
    unknown = sorted(set(raw) - {"absolute", "relative"})
    if unknown:
        problems.append(f"{where}: tolerance has unknown keys: {', '.join(unknown)}")
    return out or None


def _validate_inputs(raw: Any, where: str, problems: List[str]) -> Dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        problems.append(f"{where}: inputs must be an object")
        return {}
    inputs: Dict[str, Any] = {
        "issueAge": 45,
        "faceAmount": 100_000.0,
        "premiumMode": "ANNUAL",
        "modalPremium": None,
        "sex": None,
        "riskClass": None,
        "tobaccoStatus": None,
        "policyFeeAnnual": None,
    }
    age = raw.get("issueAge")
    if age is not None:
        if not isinstance(age, int) or isinstance(age, bool) or age < 0 or age > 120:
            problems.append(f"{where}: inputs.issueAge must be an integer between 0 and 120")
        else:
            inputs["issueAge"] = age
    face = raw.get("faceAmount")
    if face is not None:
        if not _is_number(face) or float(face) <= 0:
            problems.append(f"{where}: inputs.faceAmount must be a number greater than zero")
        else:
            inputs["faceAmount"] = float(face)
    mode = raw.get("premiumMode")
    if mode is not None:
        if not isinstance(mode, str) or not mode.strip():
            problems.append(f"{where}: inputs.premiumMode must be a non-empty string")
        else:
            inputs["premiumMode"] = mode.strip().upper()
    modal = raw.get("modalPremium")
    if modal is not None:
        if not _is_number(modal) or float(modal) <= 0:
            problems.append(
                f"{where}: inputs.modalPremium must be a number greater than zero (or null)"
            )
        else:
            inputs["modalPremium"] = float(modal)
    fee = raw.get("policyFeeAnnual")
    if fee is not None:
        if not _is_number(fee) or float(fee) < 0:
            problems.append(f"{where}: inputs.policyFeeAnnual must be a number >= 0 (or null)")
        else:
            inputs["policyFeeAnnual"] = float(fee)
    for key in ("sex", "riskClass", "tobaccoStatus"):
        value = raw.get(key)
        if value is not None:
            if not isinstance(value, str):
                problems.append(f"{where}: inputs.{key} must be a string (or null)")
            else:
                inputs[key] = value
    unknown = sorted(set(raw) - set(inputs))
    if unknown:
        problems.append(f"{where}: inputs has unknown keys: {', '.join(unknown)}")
    return inputs


def _validate_expectation(
    raw: Any, where: str, problems: List[str]
) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        problems.append(f"{where}: expectation must be an object")
        return None
    duration = raw.get("duration")
    if (
        not isinstance(duration, int)
        or isinstance(duration, bool)
        or duration < 1
        or duration > MAX_DURATION
    ):
        problems.append(
            f"{where}: duration must be an integer between 1 and {MAX_DURATION}"
        )
        duration = None
    field = raw.get("field")
    if field not in FIELD_REGISTRY:
        problems.append(
            f"{where}: field must be one of: {', '.join(sorted(FIELD_REGISTRY))}"
            f" (got {field!r})"
        )
        field = None
    value = raw.get("value")
    if not _is_number(value):
        problems.append(f"{where}: value must be a finite number")
        value = None
    source = raw.get("source")
    source_view: Optional[Dict[str, Any]] = None
    if not isinstance(source, dict) or not str(source.get("description") or "").strip():
        problems.append(
            f"{where}: source.description is required — every expectation must state "
            "where the expected value comes from (filing page, illustration, "
            "admin-system export)"
        )
    else:
        source_view = {"description": str(source.get("description")).strip()}
        document = source.get("document")
        if document is not None:
            if not isinstance(document, str):
                problems.append(f"{where}: source.document must be a string")
            else:
                source_view["document"] = document
        page = source.get("page")
        if page is not None:
            if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                problems.append(f"{where}: source.page must be a positive integer")
            else:
                source_view["page"] = page
    tolerance = _validate_tolerance(raw.get("tolerance"), where, problems)
    if duration is None or field is None or value is None or source_view is None:
        return None
    expectation: Dict[str, Any] = {
        "duration": duration,
        "field": field,
        "value": float(value),
        "source": source_view,
    }
    if tolerance is not None:
        expectation["tolerance"] = tolerance
    return expectation


def _validate_case(raw: Any, index: int, problems: List[str]) -> Optional[Dict[str, Any]]:
    where = f"cases[{index}]"
    if not isinstance(raw, dict):
        problems.append(f"{where}: case must be an object")
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append(f"{where}: name is required")
        name = ""
    else:
        name = name.strip()
        where = f"case '{name}'"
    case_id = raw.get("id")
    if case_id is not None and (not isinstance(case_id, str) or not case_id.strip()):
        problems.append(f"{where}: id must be a non-empty string")
        case_id = None
    inputs = _validate_inputs(raw.get("inputs"), where, problems)

    mechanics: Dict[str, Any] = {"mode": "workspace"}
    raw_mechanics = raw.get("mechanics")
    if raw_mechanics is not None:
        if not isinstance(raw_mechanics, dict):
            problems.append(f"{where}: mechanics must be an object")
        else:
            mode = str(raw_mechanics.get("mode") or "workspace")
            if mode not in {"workspace", "pinned"}:
                problems.append(
                    f"{where}: mechanics.mode must be 'workspace' or 'pinned' (got {mode!r})"
                )
            elif mode == "pinned":
                pinned = raw_mechanics.get("executableMechanics")
                if not isinstance(pinned, dict):
                    problems.append(
                        f"{where}: mechanics.executableMechanics is required (an object) "
                        "when mechanics.mode is 'pinned'"
                    )
                else:
                    mechanics = {"mode": "pinned", "executableMechanics": deepcopy(pinned)}

    raw_expectations = raw.get("expectations")
    expectations: List[Dict[str, Any]] = []
    if not isinstance(raw_expectations, list) or not raw_expectations:
        problems.append(f"{where}: expectations must be a non-empty list")
    elif len(raw_expectations) > MAX_EXPECTATIONS_PER_CASE:
        problems.append(
            f"{where}: expectations has {len(raw_expectations)} entries; "
            f"the maximum is {MAX_EXPECTATIONS_PER_CASE}"
        )
    else:
        seen: set = set()
        for exp_index, raw_exp in enumerate(raw_expectations):
            expectation = _validate_expectation(
                raw_exp, f"{where} expectations[{exp_index}]", problems
            )
            if expectation is None:
                continue
            key = (expectation["duration"], expectation["field"])
            if key in seen:
                problems.append(
                    f"{where}: duplicate expectation for duration "
                    f"{expectation['duration']} field '{expectation['field']}'"
                )
                continue
            seen.add(key)
            expectations.append(expectation)

    case: Dict[str, Any] = {
        "id": str(case_id).strip() if case_id else f"case-{index + 1}",
        "name": name,
        "inputs": inputs,
        "mechanics": mechanics,
        "expectations": expectations,
    }
    if isinstance(raw.get("description"), str) and raw.get("description").strip():
        case["description"] = raw["description"].strip()
    return case


def validate_pack(payload: Any) -> Dict[str, Any]:
    """Validate a pack document and return its normalised form.

    Raises PackValidationError naming every problem found — a pack is
    accepted whole or rejected whole, like the slot edits before it.
    """

    problems: List[str] = []
    if not isinstance(payload, dict):
        raise PackValidationError(["pack must be a JSON object"])
    format_version = payload.get("formatVersion", PACK_FORMAT_VERSION)
    if format_version != PACK_FORMAT_VERSION:
        problems.append(
            f"formatVersion {format_version!r} is not supported "
            f"(this build reads format version {PACK_FORMAT_VERSION})"
        )
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append("name is required")
        name = ""
    version = payload.get("version")
    if version is None or not str(version).strip():
        problems.append("version is required (the pack author's version label)")
        version = ""
    default_tolerance = _validate_tolerance(
        payload.get("defaultTolerances"), "pack", problems
    )

    raw_cases = payload.get("cases")
    cases: List[Dict[str, Any]] = []
    if not isinstance(raw_cases, list) or not raw_cases:
        problems.append("cases must be a non-empty list")
    elif len(raw_cases) > MAX_CASES_PER_PACK:
        problems.append(
            f"cases has {len(raw_cases)} entries; the maximum is {MAX_CASES_PER_PACK}"
        )
    else:
        seen_ids: set = set()
        for index, raw_case in enumerate(raw_cases):
            case = _validate_case(raw_case, index, problems)
            if case is None:
                continue
            if case["id"] in seen_ids:
                problems.append(f"duplicate case id '{case['id']}'")
                continue
            seen_ids.add(case["id"])
            cases.append(case)

    if problems:
        raise PackValidationError(problems)

    pack: Dict[str, Any] = {
        "formatVersion": PACK_FORMAT_VERSION,
        "id": str(payload.get("id") or new_pack_id()),
        "name": str(name).strip(),
        "version": str(version).strip(),
        "productCode": (
            str(payload["productCode"]).strip()
            if isinstance(payload.get("productCode"), str) and payload["productCode"].strip()
            else None
        ),
        "defaultTolerances": default_tolerance or dict(DEFAULT_TOLERANCE),
        "cases": cases,
    }
    if isinstance(payload.get("description"), str) and payload["description"].strip():
        pack["description"] = payload["description"].strip()
    return pack


# ---------------------------------------------------------------------------
# Runner + diff
# ---------------------------------------------------------------------------


def mechanics_fingerprint(mechanics_view: Dict[str, Any]) -> str:
    """A stable fingerprint of the exact mechanics state a case ran on."""

    canonical = json.dumps(mechanics_view or {}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _switches_used(projection: Dict[str, Any]) -> List[str]:
    """The rule-bank switches a projection executed (Phase 4 record)."""

    switches: set = set()
    for row in (projection or {}).get("rows") or []:
        applied = row.get("appliedMechanics") or {}
        coi = applied.get("coi") or {}
        for key in ("rateSwitch", "timingSwitch", "narSwitch"):
            if coi.get(key):
                switches.add(str(coi[key]))
        for fee in applied.get("fees") or []:
            if isinstance(fee, dict) and fee.get("unitSwitch"):
                switches.add(str(fee["unitSwitch"]))
        surrender = applied.get("surrender") or {}
        if surrender.get("basisSwitch"):
            switches.add(str(surrender["basisSwitch"]))
        crediting = applied.get("crediting") or {}
        if crediting.get("switch"):
            switches.add(str(crediting["switch"]))
    return sorted(switches)


def _component_basis(
    ledger_row: Optional[Dict[str, Any]], component_id: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    if not ledger_row or not component_id:
        return None, None
    for component in ledger_row.get("components") or []:
        if component.get("id") == component_id:
            return component.get("basis"), component.get("basisLabel")
    return None, None


_BASIS_EXPLANATIONS = {
    "placeholder": (
        "The {label} line for this year is a PLACEHOLDER in the ledger — no "
        "filed value is in force for it — so the actual is a stand-in figure, "
        "not contract math. Supply the real input (or correct the "
        "expectation's source) to close this mismatch."
    ),
    "synthetic": (
        "The {label} line for this year rests on a SYNTHETIC table (an "
        "AI-generated stand-in, not a filed table), so the actual is only as "
        "good as that stand-in. A filed table in force would make this a "
        "true comparison."
    ),
    "corrected": (
        "The {label} line for this year reflects a workspace CORRECTION — "
        "the comparison is against the corrected mechanics, not the filed "
        "ones. Check whether the expectation predates the correction."
    ),
    "filed": (
        "The {label} line for this year rests on the FILED table, so this "
        "is a genuine mismatch: either the expectation's source value is "
        "wrong for this scenario, or the extraction/engine disagrees with "
        "the filing. This is the triage item a validation pack exists to "
        "surface."
    ),
    "workspace_table": (
        "The {label} line for this year rests on a workspace-supplied table "
        "(validated, but without filed provenance). Check the table against "
        "the expectation's source."
    ),
}


def _mismatch_explanation(
    *,
    status: str,
    field_label: str,
    duration: int,
    expected: float,
    actual: Optional[float],
    delta: Optional[float],
    basis: Optional[str],
    source: Dict[str, Any],
    horizon: Optional[int],
) -> str:
    source_text = str(source.get("description") or "its stated source")
    if status == "missing":
        return (
            f"No actual exists: the projection produced no year-{duration} row"
            + (f" (horizon is {horizon} years)" if horizon else "")
            + f", so the expectation from {source_text} could not be compared."
        )
    basis_text = _BASIS_EXPLANATIONS.get(str(basis or ""))
    if basis_text is None:
        basis_text = (
            "The {label} line for this year is labelled "
            f"'{basis or 'calculated'}' in the ledger."
        )
    return (
        f"Expected {_money(expected)} from {source_text}; the engine produced "
        f"{_money(actual)} (delta {_signed_money(delta)}). "
        + basis_text.format(label=field_label)
    )


def _result_key(case_id: str, duration: int, field: str) -> str:
    return f"{case_id} / year {duration} / {field}"


def _result_change(
    current_cases: List[Dict[str, Any]], previous_run: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """What moved versus the previous run of the same pack."""

    if not previous_run:
        return None
    previous: Dict[str, str] = {}
    previous_fingerprints: Dict[str, str] = {}
    for case in previous_run.get("cases") or []:
        previous_fingerprints[str(case.get("caseId"))] = str(
            case.get("mechanicsFingerprint") or ""
        )
        for result in case.get("results") or []:
            previous[
                _result_key(
                    str(case.get("caseId")), int(result.get("duration") or 0),
                    str(result.get("field")),
                )
            ] = str(result.get("status"))
    newly_failing: List[str] = []
    newly_passing: List[str] = []
    mechanics_changed: List[str] = []
    for case in current_cases:
        case_id = str(case.get("caseId"))
        if (
            case_id in previous_fingerprints
            and previous_fingerprints[case_id] != str(case.get("mechanicsFingerprint") or "")
        ):
            mechanics_changed.append(case_id)
        for result in case.get("results") or []:
            key = _result_key(
                case_id, int(result.get("duration") or 0), str(result.get("field"))
            )
            before = previous.get(key)
            now = str(result.get("status"))
            if before == "pass" and now != "pass":
                newly_failing.append(key)
            elif before in {"fail", "missing"} and now == "pass":
                newly_passing.append(key)
    return {
        "previousRunId": previous_run.get("id"),
        "previousRanAt": previous_run.get("ranAt"),
        "newlyFailing": newly_failing,
        "newlyPassing": newly_passing,
        "mechanicsChangedCases": mechanics_changed,
    }


def run_validation_pack(
    pack: Dict[str, Any],
    *,
    project_case: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
    workspace_mechanics_view: Dict[str, Any],
    workspace_id: str,
    product_code: Optional[str],
    who: str,
    at: str,
    previous_run: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run every case of a validated pack and build the run report.

    ``project_case(inputs, mechanics_view)`` must return the projection
    view (the shape POST /projection returns as ``illustration``: raw
    ``rows`` plus the Phase 1 ``ledger``).  Actuals are read from the
    ledger only — the runner never calculates.
    """

    pack_tolerance = pack.get("defaultTolerances") or dict(DEFAULT_TOLERANCE)
    ledger_version: Optional[int] = None
    case_reports: List[Dict[str, Any]] = []
    all_switches: set = set()
    totals = {"expectations": 0, "pass": 0, "fail": 0, "missing": 0}
    passed_cases = 0
    basis_counts: Dict[str, int] = {}
    standin_lines: List[Dict[str, Any]] = []

    for case in pack.get("cases") or []:
        mechanics = case.get("mechanics") or {"mode": "workspace"}
        if mechanics.get("mode") == "pinned":
            view = deepcopy(mechanics.get("executableMechanics") or {})
        else:
            view = deepcopy(workspace_mechanics_view or {})
        fingerprint = mechanics_fingerprint(view)
        projection = project_case(deepcopy(case.get("inputs") or {}), view)
        ledger = projection.get("ledger") or {}
        if ledger.get("ledgerVersion") is not None:
            ledger_version = ledger["ledgerVersion"]
        ledger_rows = {
            int(row.get("year")): row
            for row in ledger.get("rows") or []
            if isinstance(row.get("year"), int)
        }
        horizon = max(ledger_rows) if ledger_rows else None
        case_switches = _switches_used(projection)
        all_switches.update(case_switches)

        results: List[Dict[str, Any]] = []
        case_status = "pass"
        for expectation in case.get("expectations") or []:
            duration = int(expectation["duration"])
            field = str(expectation["field"])
            row_key, component_id, label = FIELD_REGISTRY[field]
            expected = float(expectation["value"])
            tolerance = expectation.get("tolerance") or {}
            abs_tol = float(tolerance.get("absolute", pack_tolerance.get("absolute", 0.01)))
            rel_tol = float(tolerance.get("relative", pack_tolerance.get("relative", 0.0)))
            band = max(abs_tol, rel_tol * abs(expected))
            ledger_row = ledger_rows.get(duration)
            basis, basis_label = _component_basis(ledger_row, component_id)
            if ledger_row is None or ledger_row.get(row_key) is None:
                status = "missing"
                actual = None
                delta = None
            else:
                actual = float(ledger_row[row_key])
                delta = actual - expected
                status = "pass" if abs(delta) <= band + _EPSILON else "fail"
            if basis:
                basis_counts[basis] = basis_counts.get(basis, 0) + 1
            delta_rounded = None if delta is None else round(delta, 6)
            if delta_rounded == 0:
                delta_rounded = 0.0  # never report a "-0.00" delta
            result: Dict[str, Any] = {
                "duration": duration,
                "field": field,
                "fieldLabel": label,
                "expected": expected,
                "actual": actual,
                "delta": delta_rounded,
                "tolerance": {
                    "absolute": abs_tol,
                    "relative": rel_tol,
                    "band": round(band, 6),
                },
                "status": status,
                "basis": basis,
                "basisLabel": basis_label,
                "source": expectation.get("source") or {},
            }
            if status != "pass":
                result["explanation"] = _mismatch_explanation(
                    status=status,
                    field_label=label,
                    duration=duration,
                    expected=expected,
                    actual=actual,
                    delta=delta,
                    basis=basis,
                    source=expectation.get("source") or {},
                    horizon=horizon,
                )
                case_status = "fail"
            if basis in _STANDIN_BASES:
                standin_lines.append({
                    "caseId": case["id"],
                    "duration": duration,
                    "field": field,
                    "basis": basis,
                })
            totals["expectations"] += 1
            totals[status] += 1
            results.append(result)

        if case_status == "pass":
            passed_cases += 1
        case_reports.append({
            "caseId": case["id"],
            "name": case.get("name"),
            "status": case_status,
            "inputs": case.get("inputs") or {},
            "mechanicsMode": mechanics.get("mode") or "workspace",
            "mechanicsFingerprint": fingerprint,
            "switchesUsed": case_switches,
            "results": results,
        })

    total_cases = len(case_reports)
    summary = {
        "status": "pass" if passed_cases == total_cases and total_cases > 0 else "fail",
        "cases": total_cases,
        "passedCases": passed_cases,
        "failedCases": total_cases - passed_cases,
        "expectations": totals["expectations"],
        "passed": totals["pass"],
        "failed": totals["fail"],
        "missing": totals["missing"],
        "basisCounts": basis_counts,
    }
    report: Dict[str, Any] = {
        "id": run_id or new_run_id(),
        "packId": pack.get("id"),
        "packName": pack.get("name"),
        "packVersion": pack.get("version"),
        "packFormatVersion": pack.get("formatVersion"),
        "workspaceId": workspace_id,
        "productCode": pack.get("productCode") or product_code,
        "ranBy": who,
        "ranAt": at,
        "engine": {
            "ledgerVersion": ledger_version,
            "switchesUsed": sorted(all_switches),
        },
        "summary": summary,
        "standInLines": standin_lines,
        "cases": case_reports,
        "changeVsPreviousRun": _result_change(case_reports, previous_run),
    }
    return report


def pack_summary(
    pack: Dict[str, Any], *, last_run: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """The list-view shape for a pack: identity + case count + last run."""

    summary: Dict[str, Any] = {
        "id": pack.get("id"),
        "name": pack.get("name"),
        "version": pack.get("version"),
        "formatVersion": pack.get("formatVersion"),
        "productCode": pack.get("productCode"),
        "description": pack.get("description"),
        "caseCount": len(pack.get("cases") or []),
        "createdBy": pack.get("createdBy"),
        "createdAt": pack.get("createdAt"),
        "updatedAt": pack.get("updatedAt"),
        "lastRun": None,
    }
    if last_run:
        summary["lastRun"] = {
            "id": last_run.get("id"),
            "ranAt": last_run.get("ranAt"),
            "ranBy": last_run.get("ranBy"),
            "summary": last_run.get("summary"),
        }
    return summary


# ---------------------------------------------------------------------------
# Human-readable report (the audit-file rendering)
# ---------------------------------------------------------------------------


def _money(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.2f}"


def _signed_money(value: Optional[float]) -> str:
    if value is None:
        return "—"
    rounded = round(float(value), 2)
    if rounded == 0:
        rounded = 0.0  # a sub-cent delta displays as +0.00, never -0.00
    return f"{rounded:+,.2f}"


def _pad(text: str, width: int, *, right: bool = False) -> str:
    text = str(text)
    return text.rjust(width) if right else text.ljust(width)


def render_report_text(report: Dict[str, Any]) -> str:
    """Render a run report as plain text suitable for an audit file."""

    summary = report.get("summary") or {}
    engine = report.get("engine") or {}
    lines: List[str] = []
    lines.append("VALIDATION REPORT")
    lines.append("=" * 72)
    lines.append(f"Pack:        {report.get('packName')} (version {report.get('packVersion')})")
    lines.append(f"Pack id:     {report.get('packId')}  (format version {report.get('packFormatVersion')})")
    lines.append(f"Product:     {report.get('productCode') or '—'}")
    lines.append(f"Workspace:   {report.get('workspaceId')}")
    lines.append(f"Run:         {report.get('id')} at {report.get('ranAt')} by {report.get('ranBy')}")
    lines.append(
        f"Engine:      projection ledger version {engine.get('ledgerVersion')}; "
        "rule-bank switches used:"
    )
    for switch in engine.get("switchesUsed") or []:
        lines.append(f"               - {switch}")
    lines.append(
        f"Result:      {str(summary.get('status') or '').upper()} — "
        f"{summary.get('passedCases')}/{summary.get('cases')} cases passed; "
        f"{summary.get('passed')}/{summary.get('expectations')} expectations within "
        f"tolerance ({summary.get('failed')} failed, {summary.get('missing')} missing)"
    )
    basis_counts = summary.get("basisCounts") or {}
    if basis_counts:
        lines.append(
            "Basis of actuals: "
            + ", ".join(f"{basis} {count}" for basis, count in sorted(basis_counts.items()))
        )
    lines.append("")

    for case in report.get("cases") or []:
        inputs = case.get("inputs") or {}
        lines.append("-" * 72)
        lines.append(
            f"CASE {case.get('name')} — {str(case.get('status') or '').upper()}"
        )
        lines.append(
            "  Inputs: issue age {age}, face ${face}, premium mode {mode}, "
            "modal premium {modal}".format(
                age=inputs.get("issueAge"),
                face=_money(inputs.get("faceAmount")),
                mode=inputs.get("premiumMode"),
                modal=(
                    "$" + _money(inputs.get("modalPremium"))
                    if inputs.get("modalPremium") is not None
                    else "(derived)"
                ),
            )
        )
        lines.append(
            f"  Mechanics: {case.get('mechanicsMode')} state, "
            f"fingerprint {str(case.get('mechanicsFingerprint') or '')[:16]}…"
        )
        if case.get("switchesUsed"):
            lines.append(f"  Switches: {', '.join(case['switchesUsed'])}")
        lines.append("")
        header = (
            "  "
            + _pad("Yr", 4)
            + _pad("Field", 20)
            + _pad("Expected", 14, right=True)
            + _pad("Actual", 14, right=True)
            + _pad("Delta", 13, right=True)
            + "  "
            + _pad("Result", 8)
            + "Basis"
        )
        lines.append(header)
        for result in case.get("results") or []:
            lines.append(
                "  "
                + _pad(result.get("duration"), 4)
                + _pad(result.get("fieldLabel"), 20)
                + _pad(_money(result.get("expected")), 14, right=True)
                + _pad(_money(result.get("actual")), 14, right=True)
                + _pad(_signed_money(result.get("delta")), 13, right=True)
                + "  "
                + _pad(str(result.get("status") or "").upper(), 8)
                + str(result.get("basisLabel") or result.get("basis") or "—")
            )
        mismatches = [r for r in case.get("results") or [] if r.get("status") != "pass"]
        if mismatches:
            lines.append("")
            lines.append("  Mismatches:")
            for result in mismatches:
                source = result.get("source") or {}
                source_line = str(source.get("description") or "")
                if source.get("document"):
                    source_line = f"{source['document']}: {source_line}"
                lines.append(
                    f"    - Year {result.get('duration')} {result.get('fieldLabel')}: "
                    f"{result.get('explanation')}"
                )
                lines.append(f"      Source: {source_line}")
        lines.append("")

    standins = report.get("standInLines") or []
    if standins:
        lines.append("-" * 72)
        lines.append(
            "Lines resting on stand-ins (placeholder or synthetic basis) — "
            "these numbers are not filed values:"
        )
        for line in standins:
            lines.append(
                f"  - {line.get('caseId')} year {line.get('duration')} "
                f"{line.get('field')}: {line.get('basis')}"
            )
        lines.append("")

    change = report.get("changeVsPreviousRun")
    if change:
        lines.append("-" * 72)
        lines.append(
            f"Changes vs previous run {change.get('previousRunId')} "
            f"({change.get('previousRanAt')}):"
        )
        lines.append(
            f"  Newly failing: {len(change.get('newlyFailing') or [])}; "
            f"newly passing: {len(change.get('newlyPassing') or [])}; "
            f"cases whose mechanics changed: "
            f"{', '.join(change.get('mechanicsChangedCases') or []) or 'none'}"
        )
        for key in change.get("newlyFailing") or []:
            lines.append(f"    newly failing: {key}")
        for key in change.get("newlyPassing") or []:
            lines.append(f"    newly passing: {key}")
        lines.append("")

    lines.append("=" * 72)
    lines.append(
        "End of report. Expectations are only as authoritative as their "
        "stated sources; actuals are read from the projection ledger, "
        "whose per-line bases are recorded above."
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "FIELD_REGISTRY",
    "PACK_FORMAT_VERSION",
    "PackValidationError",
    "mechanics_fingerprint",
    "new_pack_id",
    "new_run_id",
    "pack_summary",
    "render_report_text",
    "run_validation_pack",
    "validate_pack",
]
