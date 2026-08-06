"""Strict extraction of executable UL mechanics from workspace tables.

Only explicitly labelled tabular data is accepted.  Narrative PDF text is
deliberately excluded: losing table boundaries or units can turn a citation
into an invented actuarial assumption.
"""

from __future__ import annotations

import io
import math
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from PyPDF2 import PdfReader


MAX_DURATION = 121
COI_UNITS = {"per_1000_monthly", "per_1000_annual", "percent_nar_annual"}
SURRENDER_UNITS = {"percent_face", "per_1000_face", "fixed"}
FEE_UNITS = {"annual_fixed", "monthly_fixed", "modal_fixed", "per_1000_face_annual", "percent_premium"}
PDF_REVIEW_REQUIRED = "review_required"


def _name(value: Any) -> str:
    return "_".join(str(value or "").strip().lower().replace("-", " ").split())


def _number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _integer(value: Any, field: str, low: int, high: int) -> int:
    result = _number(value, field)
    if not result.is_integer() or not low <= result <= high:
        raise ValueError(f"{field} must be an integer from {low} through {high}")
    return int(result)


def _text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    result = str(value).strip()
    return result or None


def _read_tables(filename: str, content: bytes) -> List[Tuple[str, pd.DataFrame]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return [("CSV", pd.read_csv(io.BytesIO(content), dtype=object))]
    if suffix == ".tsv":
        return [("TSV", pd.read_csv(io.BytesIO(content), sep="\t", dtype=object))]
    if suffix in {".xlsx", ".xlsm"}:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, dtype=object)
        return [(str(name), frame) for name, frame in sheets.items()]
    return []


def _pdf_provenance(filename: str, page: int, heading: str) -> Dict[str, Any]:
    return {
        "filename": filename,
        "page": page,
        "tableHeading": heading,
        "sourceType": "filed_pdf",
        "evidenceClass": "specimen_filed_table",
        "valueBasis": "guaranteed_maximum",
        "reviewStatus": PDF_REVIEW_REQUIRED,
    }


def _pdf_policy_selectors(text: str) -> Dict[str, str]:
    """Read table applicability selectors from the specimen policy information."""

    selectors: Dict[str, str] = {}
    sex_match = re.search(r"\bSex\s*:\s*\[?\s*(Male|Female)\b", text or "", re.IGNORECASE)
    if sex_match:
        selectors["sex"] = "M" if sex_match.group(1).lower() == "male" else "F"
    risk_match = re.search(r"Risk\s+Class\s*:\s*\[([^\n]+?)\]", text or "", re.IGNORECASE)
    if risk_match:
        raw_risk = re.sub(r"\s+", " ", risk_match.group(1)).strip()
        lowered = raw_risk.lower()
        if "no nicotine use" in lowered or "non-tobacco" in lowered or "nonsmoker" in lowered:
            selectors["tobacco_status"] = "Non-Tobacco"
        elif "nicotine use" in lowered or "tobacco" in lowered or "smoker" in lowered:
            selectors["tobacco_status"] = "Tobacco"
        risk_class = re.sub(
            r"\b(?:no\s+)?nicotine\s+use\b|\bnon[- ]?tobacco\b|\bnon[- ]?smoker\b|\btobacco\b|\bsmoker\b",
            "",
            raw_risk,
            flags=re.IGNORECASE,
        ).strip(" -/")
        if risk_class:
            selectors["risk_class"] = risk_class
    return selectors


def _number_pairs(section: str) -> List[Tuple[int, float, bool]]:
    """Read repeated duration/value pairs while preserving an explicit '+' terminal row."""

    pairs: List[Tuple[int, float, bool]] = []
    for raw_duration, plus, raw_value in re.findall(
        r"(?<![\d.])(\d{1,3})(\+?)\]?\s+\[?\$?([0-9]+(?:\.[0-9]+)?)\]?",
        section,
    ):
        duration = int(raw_duration)
        if 1 <= duration <= MAX_DURATION:
            pairs.append((duration, float(raw_value), plus == "+"))
    return pairs


def _extract_pdf_page(filename: str, page_number: int, text: str) -> Dict[str, List[Dict[str, Any]]]:
    """Extract only recognized, explicitly headed UL tables from one PDF page."""

    mechanics: Dict[str, List[Dict[str, Any]]] = {"coi": [], "surrender": [], "fees": []}
    compact = re.sub(r"[ \t]+", " ", text or "")
    no_space = re.sub(r"\s+", "", compact).upper()
    if "ICC18S18PRUL" not in no_space or "SPECIMEN" not in no_space:
        return mechanics

    surrender_heading = "Surrender Charge Rates"
    surrender_end = re.search(r"Surrender\s+Char\s*ge\s+Calculation", compact, re.IGNORECASE)
    if surrender_heading in compact and "Coverage" in compact and surrender_end:
        section = compact.split(surrender_heading, 1)[1][: surrender_end.start()]
        pairs = _number_pairs(section)
        durations = [duration for duration, _, _ in pairs]
        if durations and durations == list(range(1, max(durations) + 1)):
            provenance = _pdf_provenance(filename, page_number, surrender_heading)
            mechanics["surrender"] = [
                {
                    "duration": duration,
                    "issue_age": None,
                    "sex": None,
                    "charge": value,
                    "charge_unit": "per_1000_face",
                    "provenance": dict(provenance),
                }
                for duration, value, _ in pairs
            ]

    coi_heading = "Table of Cost of Insurance (COI) Rates"
    coi_start = re.search(r"Table\s+of\s+Cost\s+of\s+Insu\s*rance\s+\(COI\)\s+Rates", compact, re.IGNORECASE)
    if coi_start and "MAXIMUMMONTHLYCOSTOFINSURANCERATESPER$1000" in no_space:
        section = compact[coi_start.end():]
        pairs = _number_pairs(section)
        # Ignore heading numbers such as $1000 and accept only a complete 1..terminal schedule.
        by_duration = {duration: (value, terminal) for duration, value, terminal in pairs}
        terminal = max(by_duration, default=0)
        if terminal and set(range(1, terminal + 1)) <= set(by_duration):
            provenance = _pdf_provenance(filename, page_number, coi_heading)
            for duration in range(1, terminal + 1):
                value, is_terminal = by_duration[duration]
                mechanics["coi"].append({
                    "duration": duration,
                    "attained_age": None,
                    "sex": None,
                    "risk_class": None,
                    "tobacco_status": None,
                    "rate": value,
                    "rate_unit": "per_1000_monthly",
                    "provenance": dict(provenance),
                })
                if is_terminal:
                    for later_duration in range(duration + 1, MAX_DURATION + 1):
                        mechanics["coi"].append({
                            "duration": later_duration,
                            "attained_age": None,
                            "sex": None,
                            "risk_class": None,
                            "tobacco_status": None,
                            "rate": value,
                            "rate_unit": "per_1000_monthly",
                            "provenance": {**provenance, "expandedFrom": f"{duration}+"},
                        })

    expense_heading = "Table of Maximum Monthly Expense Charges"
    expense_start = re.search(
        r"Table\s+of\s+Maximum\s+Monthly\s+Expense\s+Charges",
        compact,
        re.IGNORECASE,
    )
    if expense_start and "POLICYYEAR" in no_space and "EXPENSECHARGE" in no_space:
        pairs = _number_pairs(compact[expense_start.end():])
        by_duration = {duration: (value, terminal) for duration, value, terminal in pairs}
        terminal = max(by_duration, default=0)
        if terminal and set(range(1, terminal + 1)) <= set(by_duration):
            provenance = _pdf_provenance(filename, page_number, expense_heading)
            for duration in range(1, terminal + 1):
                value, is_terminal = by_duration[duration]
                mechanics["fees"].append({
                    "component": "monthly_expense",
                    "duration": duration,
                    "premium_mode": None,
                    "amount": value,
                    "fee_unit": "monthly_fixed",
                    "provenance": dict(provenance),
                })
                if is_terminal:
                    for later_duration in range(duration + 1, MAX_DURATION + 1):
                        mechanics["fees"].append({
                            "component": "monthly_expense",
                            "duration": later_duration,
                            "premium_mode": None,
                            "amount": value,
                            "fee_unit": "monthly_fixed",
                            "provenance": {**provenance, "expandedFrom": f"{duration}+"},
                        })
    return mechanics


def _read_pdf_mechanics(filename: str, content: bytes) -> Dict[str, Any]:
    mechanics: Dict[str, List[Dict[str, Any]]] = {"coi": [], "surrender": [], "fees": []}
    warnings: List[str] = []
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001
        return {"mechanics": mechanics, "warnings": [f"{filename}: PDF could not be read: {exc}"]}
    page_texts: List[str] = []
    for page in reader.pages:
        try:
            page_texts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            page_texts.append("")
    selectors = _pdf_policy_selectors("\n".join(page_texts))
    for page_number, text in enumerate(page_texts, 1):
        try:
            extracted = _extract_pdf_page(filename, page_number, text)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{filename} page {page_number}: PDF table extraction rejected: {exc}")
            continue
        for mechanic, rows in extracted.items():
            if mechanic == "coi" and selectors or mechanic == "fees" and selectors:
                for row in rows:
                    if mechanic == "coi" or row.get("component") == "monthly_expense":
                        row.update(selectors)
                    row["provenance"] = {
                        **(row.get("provenance") or {}),
                        **({"selectorEvidence": selectors} if row.get("component") == "monthly_expense" or mechanic == "coi" else {}),
                    }
            mechanics[mechanic].extend(rows)
    full_text = "\n".join(page_texts)
    period_match = re.search(r"Initial\s+Expense\s+Charge\s+Period\s*:\s*\[?\s*(\d+)\s+Policy\s+Years", full_text, re.IGNORECASE)
    premium_match = re.search(r"Premium\s+Expense\s+Charge\s+Rate\s*:\s*\[?\s*([0-9]+(?:\.[0-9]+)?)\s*\]?%", full_text, re.IGNORECASE)
    if premium_match and period_match:
        page_number = next((index for index, text in enumerate(page_texts, 1) if "Premium Expense Charge" in text), 1)
        rate = float(premium_match.group(1)) / 100.0
        period = min(MAX_DURATION, int(period_match.group(1)))
        provenance = _pdf_provenance(filename, page_number, "Premium Expense Charge Rate")
        mechanics["fees"].extend({
            "component": "premium_expense", "duration": duration, "premium_mode": None,
            "amount": rate, "fee_unit": "percent_premium", "provenance": dict(provenance),
        } for duration in range(1, period + 1))
    admin_match = re.search(r"Administrative\s+Charge\s+Per\s+Month\s*:\s*\$?\[?\s*([0-9]+(?:\.[0-9]+)?)", full_text, re.IGNORECASE)
    if admin_match:
        page_number = next((index for index, text in enumerate(page_texts, 1) if "Administrative Charge Per Month" in text), 1)
        provenance = _pdf_provenance(filename, page_number, "Administrative Charge Per Month")
        mechanics["fees"].append({
            "component": "administrative", "duration": None, "premium_mode": None,
            "amount": float(admin_match.group(1)), "fee_unit": "monthly_fixed", "provenance": provenance,
        })
    return {"mechanics": mechanics, "warnings": warnings}


def extract_ul_mechanics(filename: str, content: bytes) -> Dict[str, Any]:
    """Return validated mechanics plus non-fatal extraction warnings."""

    if Path(filename).suffix.lower() == ".pdf":
        extracted = _read_pdf_mechanics(filename, content)
        return {"version": 2, **extracted}

    mechanics: Dict[str, List[Dict[str, Any]]] = {"coi": [], "surrender": [], "fees": []}
    warnings: List[str] = []
    for sheet, frame in _read_tables(filename, content):
        frame = frame.rename(columns={column: _name(column) for column in frame.columns})
        columns = set(frame.columns)
        kind = _name(sheet)
        if "mechanic" in columns:
            groups = frame.groupby(frame["mechanic"].map(_name), dropna=False)
        elif "coi" in kind:
            groups = [("coi", frame)]
        elif "surrender" in kind:
            groups = [("surrender", frame)]
        elif "fee" in kind or "admin" in kind:
            groups = [("fees", frame)]
        else:
            warnings.append(f"{filename} sheet {sheet}: no recognized mechanic label")
            continue

        for raw_kind, group in groups:
            mechanic = {"policy_fee": "fees", "admin_fee": "fees", "fee": "fees"}.get(
                _name(raw_kind), _name(raw_kind)
            )
            if mechanic not in mechanics:
                warnings.append(f"{filename} sheet {sheet}: unrecognized mechanic {raw_kind!r}")
                continue
            for index, raw in group.iterrows():
                row_number = int(index) + 2
                try:
                    row = _parse_row(mechanic, raw.to_dict())
                except ValueError as exc:
                    warnings.append(f"{filename} sheet {sheet} row {row_number}: {exc}")
                    continue
                row["provenance"] = {
                    "filename": filename,
                    "sheet": sheet,
                    "row": row_number,
                }
                mechanics[mechanic].append(row)

    for mechanic, rows in mechanics.items():
        keys: set[tuple[Any, ...]] = set()
        for row in rows:
            key = tuple(
                row.get(field)
                for field in (
                    "duration", "attained_age", "sex", "risk_class",
                    "tobacco_status", "premium_mode",
                )
            )
            if key in keys:
                raise ValueError(f"duplicate {mechanic} selector {key}")
            keys.add(key)
    return {"version": 1, "mechanics": mechanics, "warnings": warnings}


def _parse_row(mechanic: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    if mechanic == "coi":
        if "rate" not in raw or "rate_unit" not in raw:
            raise ValueError("COI rows require rate and rate_unit")
        duration = _text(raw.get("duration"))
        age = _text(raw.get("attained_age"))
        if bool(duration) == bool(age):
            raise ValueError("COI rows require exactly one of duration or attained_age")
        unit = _name(raw.get("rate_unit"))
        if unit not in COI_UNITS:
            raise ValueError(f"unsupported COI rate_unit {unit!r}")
        rate = _number(raw.get("rate"), "rate")
        upper = 1000.0 if unit.startswith("per_1000") else 1.0
        if not 0 <= rate <= upper:
            raise ValueError(f"COI rate must be between 0 and {upper:g}")
        return {
            "duration": _integer(duration, "duration", 1, MAX_DURATION) if duration else None,
            "attained_age": _integer(age, "attained_age", 0, 130) if age else None,
            "sex": _text(raw.get("sex")),
            "risk_class": _text(raw.get("risk_class")),
            "tobacco_status": _text(raw.get("tobacco_status")),
            "rate": rate,
            "rate_unit": unit,
        }
    if mechanic == "surrender":
        required = {"duration", "charge", "charge_unit"}
        if not required <= set(raw):
            raise ValueError("surrender rows require duration, charge, and charge_unit")
        unit = _name(raw.get("charge_unit"))
        if unit not in SURRENDER_UNITS:
            raise ValueError(f"unsupported surrender charge_unit {unit!r}")
        charge = _number(raw.get("charge"), "charge")
        upper = 1.0 if unit == "percent_face" else 1_000_000.0
        if not 0 <= charge <= upper:
            raise ValueError(f"surrender charge must be between 0 and {upper:g}")
        return {
            "duration": _integer(raw.get("duration"), "duration", 1, MAX_DURATION),
            "issue_age": _integer(raw["issue_age"], "issue_age", 0, 120) if _text(raw.get("issue_age")) else None,
            "sex": _text(raw.get("sex")),
            "charge": charge,
            "charge_unit": unit,
        }
    required = {"amount", "fee_unit"}
    if not required <= set(raw):
        raise ValueError("fee rows require amount and fee_unit")
    unit = _name(raw.get("fee_unit"))
    if unit not in FEE_UNITS:
        raise ValueError(f"unsupported fee_unit {unit!r}")
    amount = _number(raw.get("amount"), "amount")
    if not 0 <= amount <= 1_000_000:
        raise ValueError("fee amount must be between 0 and 1000000")
    return {
        "component": _text(raw.get("component")) or "policy_fee",
        "duration": _integer(raw["duration"], "duration", 1, MAX_DURATION) if _text(raw.get("duration")) else None,
        "premium_mode": _text(raw.get("premium_mode")),
        "amount": amount,
        "fee_unit": unit,
    }


def usable_mechanics(extracted: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only complete schedules; partial tables remain evidence, not inputs."""

    raw = extracted.get("mechanics") or {}
    usable: Dict[str, Any] = {}
    coi = [row for row in (raw.get("coi") or []) if (row.get("provenance") or {}).get("reviewStatus") != PDF_REVIEW_REQUIRED]
    if coi:
        usable["coi"] = coi
    surrender = [row for row in (raw.get("surrender") or []) if (row.get("provenance") or {}).get("reviewStatus") != PDF_REVIEW_REQUIRED]
    surrender_durations = sorted({row.get("duration") for row in surrender})
    if surrender and surrender_durations == list(range(1, max(surrender_durations) + 1)):
        usable["surrender"] = surrender
    fees = [row for row in (raw.get("fees") or []) if (row.get("provenance") or {}).get("reviewStatus") != PDF_REVIEW_REQUIRED]
    components: Dict[str, List[Dict[str, Any]]] = {}
    for row in fees:
        components.setdefault(str(row.get("component") or "policy_fee"), []).append(row)
    complete_components = True
    for rows in components.values():
        durations = sorted({row.get("duration") for row in rows if row.get("duration") is not None})
        if not any(row.get("duration") is None for row in rows) and (
            not durations or durations != list(range(1, max(durations) + 1))
        ):
            complete_components = False
    if fees and complete_components:
        usable["fees"] = fees
    return usable


def accept_filed_mechanic(
    artifact: Dict[str, Any], mechanic: str, *, candidate_id: str | None = None,
    reviewed_by: str = "workspace_user",
) -> Dict[str, Any]:
    """Accept one complete filed-PDF candidate set and make only that mechanic executable."""

    if mechanic not in {"coi", "surrender", "fees"}:
        raise ValueError("mechanic must be coi, surrender, or fees")
    result = deepcopy(artifact)
    candidates = list((result.get("candidates") or {}).get(mechanic) or [])
    candidate = None
    if candidates:
        if candidate_id:
            candidate = next((item for item in candidates if item.get("id") == candidate_id), None)
            if candidate is None:
                raise ValueError(f"Filed {mechanic} candidate was not found")
        elif len(candidates) == 1:
            candidate = candidates[0]
        else:
            raise ValueError(f"Select one of the {len(candidates)} filed {mechanic} candidates")
    rows = list((candidate or {}).get("rows") or (result.get("mechanics") or {}).get(mechanic) or [])
    if not rows:
        raise ValueError(f"No filed {mechanic} candidate is available")
    if any((row.get("provenance") or {}).get("sourceType") != "filed_pdf" for row in rows):
        raise ValueError("Only filed-PDF candidates can be accepted by this workflow")
    if any((row.get("provenance") or {}).get("reviewStatus") != PDF_REVIEW_REQUIRED for row in rows):
        raise ValueError(f"Filed {mechanic} candidate is not awaiting review")
    durations = sorted({row.get("duration") for row in rows if row.get("duration") is not None})
    if mechanic in {"coi", "surrender"} and durations:
        expected = list(range(1, max(durations) + 1))
        if durations != expected:
            raise ValueError(f"Filed {mechanic} candidate has gaps in its duration schedule")

    accepted_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        row["provenance"] = {
            **(row.get("provenance") or {}),
            "reviewStatus": "accepted",
            "reviewedBy": reviewed_by,
            "reviewedAt": accepted_at,
        }
    if candidate is not None:
        candidate["rows"] = rows
        candidate["reviewStatus"] = "accepted"
    active_rows = rows
    if candidate is not None:
        active_rows = [
            row
            for item in candidates
            if item.get("reviewStatus") == "accepted"
            for row in (item.get("rows") or [])
        ]
    selector_fields = (
        "component", "duration", "attained_age", "sex", "risk_class", "tobacco_status",
        "issue_age", "premium_mode",
    )
    value_fields = {
        "coi": ("rate", "rate_unit"),
        "surrender": ("charge", "charge_unit"),
        "fees": ("amount", "fee_unit"),
    }[mechanic]
    deduplicated: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for active_row in active_rows:
        selector = tuple(active_row.get(field) for field in selector_fields)
        existing = deduplicated.get(selector)
        if existing is not None:
            existing_value = tuple(existing.get(field) for field in value_fields)
            incoming_value = tuple(active_row.get(field) for field in value_fields)
            if existing_value != incoming_value:
                raise ValueError(
                    f"Filed {mechanic} candidates conflict for selector {selector}"
                )
            continue
        deduplicated[selector] = active_row
    active_rows = list(deduplicated.values())
    validation_artifact = {"mechanics": {mechanic: active_rows}}
    validated = usable_mechanics(validation_artifact)
    if mechanic not in validated:
        raise ValueError(f"Filed {mechanic} candidate is incomplete and cannot be executed")
    result.setdefault("usable", {})[mechanic] = active_rows
    synthetic = result.get("synthetic") or {}
    synthetic.pop(mechanic, None)
    result.setdefault("status", {})[mechanic] = "executable"
    review_key = str((candidate or {}).get("id") or mechanic)
    result.setdefault("reviews", {})[review_key] = {
        "status": "accepted",
        "candidateId": (candidate or {}).get("id"),
        "mechanic": mechanic,
        "reviewedBy": reviewed_by,
        "reviewedAt": accepted_at,
        "rowCount": len(rows),
        "activeRowCount": len(active_rows),
        "sourceType": "filed_pdf",
    }
    return result
