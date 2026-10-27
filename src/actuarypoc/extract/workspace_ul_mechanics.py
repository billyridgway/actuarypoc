"""Strict extraction of executable UL mechanics from workspace tables.

Only explicitly labelled tabular data is accepted.  Narrative PDF text is
deliberately excluded: losing table boundaries or units can turn a citation
into an invented actuarial assumption.
"""

from __future__ import annotations

import io
import json
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
SURRENDER_UNITS = {"percent_face", "percent_account_value", "per_1000_face", "fixed"}
FEE_UNITS = {"annual_fixed", "monthly_fixed", "modal_fixed", "per_1000_face_annual", "percent_premium"}
MECHANIC_KEYS = ("coi", "surrender", "fees", "nar_factors", "corridor")
PDF_REVIEW_REQUIRED = "review_required"
PDF_REVIEW_SUPERSEDED = "superseded"

#: The fields that identify one row of a table (its lookup key), and
#: the fields that carry the row's value, per mechanic.  Two rows with
#: the same selector AND the same value are the same row filed twice;
#: the same selector with a different value is a genuine conflict.
ROW_SELECTOR_FIELDS = (
    "component", "duration", "attained_age", "sex", "risk_class",
    "tobacco_status", "issue_age", "premium_mode",
)
ROW_VALUE_FIELDS: Dict[str, Tuple[str, ...]] = {
    "coi": ("rate", "rate_unit"),
    "surrender": ("charge", "charge_unit"),
    "fees": ("amount", "fee_unit"),
    "nar_factors": ("factor",),
    "corridor": ("percentage",),
}


def row_selector_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    return tuple(row.get(field) for field in ROW_SELECTOR_FIELDS)


def row_value_key(mechanic: str, row: Dict[str, Any]) -> Tuple[Any, ...]:
    return tuple(row.get(field) for field in ROW_VALUE_FIELDS.get(mechanic, ()))


def _provenance_identity(provenance: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        provenance.get("filename"), provenance.get("page"),
        provenance.get("tableHeading"), provenance.get("candidateId"),
        provenance.get("sourceType"),
    )


def dedupe_rows(rows: List[Dict[str, Any]], mechanic: str) -> List[Dict[str, Any]]:
    """Collapse identical rows (same selector, same value) into one.

    The surviving row keeps the first provenance and gains an
    ``alsoFiledAs`` list naming every other provenance the identical
    row was filed under — the row is counted once, and no source is
    lost.  Rows that share a selector but carry different values are
    NOT merged (that is a conflict, decided by the caller).
    """

    merged: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    order: List[Tuple[Any, ...]] = []
    for row in rows or []:
        key = (row_selector_key(row), row_value_key(mechanic, row))
        existing = merged.get(key)
        if existing is None:
            merged[key] = deepcopy(row)
            order.append(key)
            continue
        provenance = row.get("provenance") or {}
        kept = merged[key].setdefault("provenance", {})
        if _provenance_identity(provenance) != _provenance_identity(kept):
            also = kept.setdefault("alsoFiledAs", [])
            if _provenance_identity(provenance) not in {
                _provenance_identity(item) for item in also
            }:
                also.append(deepcopy(provenance))
    return [merged[key] for key in order]


def candidate_group_key(mechanic: str, candidate: Dict[str, Any]) -> Tuple[str, frozenset]:
    """The alternative-group a filed candidate belongs to.

    Candidates in one group file THE SAME table — specimen variants
    of one product — so they are alternatives in a single choice,
    never a sequence of acceptances.  For fees, candidates covering
    different components are different tables (additive); candidates
    covering the same component set are alternatives.  Every other
    mechanic's candidates are one group per mechanic.
    """

    if mechanic == "fees":
        components = frozenset(
            str(row.get("component") or "policy_fee")
            for row in (candidate or {}).get("rows") or []
        )
        return (mechanic, components)
    return (mechanic, frozenset())


def candidate_selector_summary(rows: List[Dict[str, Any]]) -> Dict[str, List[Any]]:
    """Distinct selector values a candidate's rows carry, per field.

    This is what makes two specimen variants visibly different on a
    choice card ("Tobacco" vs "Non-Tobacco") without opening either
    table.
    """

    summary: Dict[str, List[Any]] = {}
    for field in ("sex", "risk_class", "tobacco_status", "issue_age", "premium_mode", "component"):
        values = sorted(
            {row.get(field) for row in rows or [] if row.get(field) not in (None, "")},
            key=str,
        )
        if values:
            summary[field] = values
    return summary


def candidate_diff(
    rows_a: List[Dict[str, Any]], rows_b: List[Dict[str, Any]], mechanic: str,
) -> Dict[str, Any]:
    """Compare two candidates' rows selector-by-selector.

    Counts identical rows (same selector, same value), differing
    rows (same selector, different value) and rows present on only
    one side, with a few differing examples — the difference a user
    is actually choosing between when two documents file the same
    table.
    """

    def keyed(rows: List[Dict[str, Any]]) -> Dict[Tuple[Any, ...], Dict[str, Any]]:
        result: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        for row in rows or []:
            result.setdefault(row_selector_key(row), row)
        return result

    a, b = keyed(rows_a), keyed(rows_b)
    identical = 0
    differing = 0
    examples: List[Dict[str, Any]] = []
    for selector in sorted(set(a) & set(b), key=str):
        value_a = row_value_key(mechanic, a[selector])
        value_b = row_value_key(mechanic, b[selector])
        if value_a == value_b:
            identical += 1
        else:
            differing += 1
            if len(examples) < 4:
                examples.append({
                    "selector": {
                        field: a[selector].get(field)
                        for field in ROW_SELECTOR_FIELDS
                        if a[selector].get(field) is not None
                    },
                    "values": {
                        "a": {field: a[selector].get(field) for field in ROW_VALUE_FIELDS.get(mechanic, ())},
                        "b": {field: b[selector].get(field) for field in ROW_VALUE_FIELDS.get(mechanic, ())},
                    },
                })
    return {
        "identicalRows": identical,
        "differingRows": differing,
        "onlyInA": len(set(a) - set(b)),
        "onlyInB": len(set(b) - set(a)),
        "examples": examples,
    }


def conflicting_row_selectors(
    mechanic: str,
    rows_a: List[Dict[str, Any]],
    rows_b: List[Dict[str, Any]],
) -> List[Tuple[Any, ...]]:
    """Selector keys where two row sets carry DIFFERENT values.

    This is the only genuine conflict between two filed candidates:
    the same lookup key priced two ways.  Rows that merely cover
    different selectors (the base specimen's Non-Tobacco slice vs
    the Nicotine specimen's Tobacco slice) do not conflict — they
    are complementary parts of one table.  Rows identical on both
    sides do not conflict either; they dedupe.
    """

    a = {row_selector_key(row): row for row in rows_a or []}
    b = {row_selector_key(row): row for row in rows_b or []}
    return [
        selector
        for selector in sorted(set(a) & set(b), key=str)
        if row_value_key(mechanic, a[selector]) != row_value_key(mechanic, b[selector])
    ]


def _overridden_selector_keys(candidate: Dict[str, Any]) -> set:
    """The selector keys a candidate's accepted rows have lost to an
    override (stored JSON-shaped on the candidate as lists)."""

    return {
        tuple(item)
        for item in (candidate or {}).get("overriddenSelectors") or []
        if isinstance(item, (list, tuple))
    }


def candidate_effective_rows(candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A candidate's rows as they contribute to the table in force:
    all of them, minus the selectors another candidate's acceptance
    explicitly overrode."""

    overridden = _overridden_selector_keys(candidate)
    if not overridden:
        return list((candidate or {}).get("rows") or [])
    return [
        row
        for row in (candidate or {}).get("rows") or []
        if row_selector_key(row) not in overridden
    ]


def accepted_union_rows(
    candidates: List[Dict[str, Any]], mechanic: str
) -> Tuple[List[Dict[str, Any]], List[Tuple[Any, ...]]]:
    """The table in force for a mechanic: the UNION of every accepted
    candidate's effective rows, identical rows deduped with merged
    provenance.

    Returns ``(rows, conflicts)`` — selector keys on which two
    accepted candidates still disagree.  Callers decide what a
    conflict means (acceptance refuses; analysis carry-over leaves
    the mechanic out rather than merging silently); this helper
    never picks a winner.
    """

    merged: List[Dict[str, Any]] = []
    seen_values: Dict[Tuple[Any, ...], Tuple[Any, ...]] = {}
    conflicts: List[Tuple[Any, ...]] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("reviewStatus") != "accepted":
            continue
        for row in candidate_effective_rows(candidate):
            selector = row_selector_key(row)
            value = row_value_key(mechanic, row)
            if selector in seen_values and seen_values[selector] != value:
                if selector not in conflicts:
                    conflicts.append(selector)
                continue
            seen_values[selector] = value
            merged.append(row)
    return dedupe_rows(merged, mechanic), conflicts


def rows_coverage_text(rows: List[Dict[str, Any]]) -> str:
    """Say what a row count counts: rows, plus their duration span.

    Replaces the old phrasing that summed rows as years ("values in
    force over 242 years" for a 242-row table filed by two
    documents).
    """

    rows = list(rows or [])
    count = len(rows)
    word = "row" if count == 1 else "rows"
    durations = sorted({row.get("duration") for row in rows if row.get("duration") is not None})
    if durations:
        if count == 1:
            return f"1 row at duration {durations[0]}"
        span = (
            f"duration {durations[0]}"
            if durations[0] == durations[-1]
            else f"durations {durations[0]}–{durations[-1]}"
        )
        contiguous = durations == list(range(durations[0], durations[-1] + 1))
        if len(durations) == count and contiguous:
            return f"{count} {word} covering {span}"
        return f"{count} {word} across {span}"
    ages = sorted({row.get("attained_age") for row in rows if row.get("attained_age") is not None})
    if ages:
        if count == 1:
            return f"1 row at attained age {ages[0]}"
        return f"{count} {word} covering attained ages {ages[0]}–{ages[-1]}"
    return f"{count} {word}"


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

    mechanics: Dict[str, List[Dict[str, Any]]] = {key: [] for key in MECHANIC_KEYS}
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
    mechanics: Dict[str, List[Dict[str, Any]]] = {key: [] for key in MECHANIC_KEYS}
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
    nar_heading_match = re.search(r"Net\s+Amount\s+at\s+Risk\s+Factor\s*:", full_text, re.IGNORECASE)
    nar_factor = None
    if nar_heading_match:
        # Multi-column specification pages can place adjacent headings before
        # their values. Select the factor-shaped bracketed value from the
        # nearby block instead of assuming it immediately follows the label.
        nearby = full_text[nar_heading_match.end():nar_heading_match.end() + 240]
        nar_factor = next(
            (value for raw in re.findall(r"\[\s*([0-9]+(?:\.[0-9]+)?)\s*\]", nearby)
             for value in [float(raw)] if 1.0 <= value <= 1.1),
            None,
        )
    if nar_factor is not None:
        page_number = next((index for index, text in enumerate(page_texts, 1) if "Net Amount at Risk Factor" in text), 1)
        provenance = _pdf_provenance(filename, page_number, "Net Amount at Risk Factor")
        mechanics["nar_factors"].append({"factor": nar_factor, "provenance": provenance})

    corridor_heading = "Table of Minimum Death Benefit Percentages"
    corridor_page = next(
        ((index, text) for index, text in enumerate(page_texts, 1) if corridor_heading in text),
        None,
    )
    if corridor_page:
        page_number, page_text = corridor_page
        pairs = _number_pairs(page_text.split(corridor_heading, 1)[1])
        by_duration = {duration: (value, terminal) for duration, value, terminal in pairs}
        terminal = max(by_duration, default=0)
        if terminal and set(range(1, terminal + 1)) <= set(by_duration):
            provenance = _pdf_provenance(filename, page_number, corridor_heading)
            for duration in range(1, terminal + 1):
                value, is_terminal = by_duration[duration]
                mechanics["corridor"].append({
                    "duration": duration,
                    "percentage": value / 100.0,
                    "provenance": dict(provenance),
                })
                if is_terminal:
                    for later_duration in range(duration + 1, MAX_DURATION + 1):
                        mechanics["corridor"].append({
                            "duration": later_duration,
                            "percentage": value / 100.0,
                            "provenance": {**provenance, "expandedFrom": f"{duration}+"},
                        })
    return {"mechanics": mechanics, "warnings": warnings}


def extract_ul_mechanics(filename: str, content: bytes) -> Dict[str, Any]:
    """Return validated mechanics plus non-fatal extraction warnings."""

    if Path(filename).suffix.lower() == ".pdf":
        extracted = _read_pdf_mechanics(filename, content)
        return {"version": 2, **extracted}

    mechanics: Dict[str, List[Dict[str, Any]]] = {key: [] for key in MECHANIC_KEYS}
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
        upper = 1.0 if unit in {"percent_face", "percent_account_value"} else 1_000_000.0
        if not 0 <= charge <= upper:
            raise ValueError(f"surrender charge must be between 0 and {upper:g}")
        return {
            "duration": _integer(raw.get("duration"), "duration", 1, MAX_DURATION),
            "issue_age": _integer(raw["issue_age"], "issue_age", 0, 120) if _text(raw.get("issue_age")) else None,
            "sex": _text(raw.get("sex")),
            "charge": charge,
            "charge_unit": unit,
        }
    if mechanic == "corridor":
        if "percentage" not in raw:
            raise ValueError("corridor rows require percentage")
        percentage = _number(raw.get("percentage"), "percentage")
        if not 0 < percentage <= 10.0:
            raise ValueError("corridor percentage must be greater than 0 and at most 10")
        return {
            "duration": _integer(raw.get("duration"), "duration", 1, MAX_DURATION),
            "percentage": percentage,
        }
    if mechanic == "nar_factors":
        if "factor" not in raw:
            raise ValueError("nar_factors rows require factor")
        factor = _number(raw.get("factor"), "factor")
        if not 0 < factor <= 2.0:
            raise ValueError("NAR factor must be greater than 0 and at most 2.0")
        return {"factor": factor}
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
        usable["coi"] = dedupe_rows(coi, "coi")
    surrender = [row for row in (raw.get("surrender") or []) if (row.get("provenance") or {}).get("reviewStatus") != PDF_REVIEW_REQUIRED]
    surrender_durations = sorted({row.get("duration") for row in surrender})
    if surrender and surrender_durations == list(range(1, max(surrender_durations) + 1)):
        usable["surrender"] = dedupe_rows(surrender, "surrender")
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
        usable["fees"] = dedupe_rows(fees, "fees")
    nar_factors = [row for row in (raw.get("nar_factors") or []) if (row.get("provenance") or {}).get("reviewStatus") != PDF_REVIEW_REQUIRED]
    if nar_factors:
        usable["nar_factors"] = dedupe_rows(nar_factors, "nar_factors")
    corridor = [row for row in (raw.get("corridor") or []) if (row.get("provenance") or {}).get("reviewStatus") != PDF_REVIEW_REQUIRED]
    corridor_durations = sorted({row.get("duration") for row in corridor})
    if corridor and corridor_durations == list(range(1, max(corridor_durations) + 1)):
        usable["corridor"] = dedupe_rows(corridor, "corridor")
    return usable


def accept_filed_mechanic(
    artifact: Dict[str, Any], mechanic: str, *, candidate_id: str | None = None,
    reviewed_by: str = "workspace_user",
    resolve_conflict: bool = False,
) -> Dict[str, Any]:
    """Accept one filed-PDF candidate into the mechanic's table in force.

    Candidates are SELECTOR SLICES of one table, not competing
    versions (Oct 27, 2026 model correction): the base specimen's
    Non-Tobacco COI rows and the Nicotine specimen's Tobacco rows
    are complementary halves of the coverage.  Accepting a
    candidate therefore never displaces another accepted candidate
    — the table in force is the union of every accepted candidate's
    rows, identical rows deduped.  The one genuine decision is an
    overlap where two filings price the SAME selector differently:
    that conflict refuses here unless ``resolve_conflict`` carries
    the user's explicit choice, in which case this candidate's rows
    govern the contested selectors (the losing candidate's rows are
    recorded as overridden; a candidate that loses every row is
    superseded — genuinely replaced as a slice).
    """

    if mechanic not in set(MECHANIC_KEYS):
        raise ValueError(f"mechanic must be one of {', '.join(MECHANIC_KEYS)}")
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
    # A superseded candidate may be chosen again (switching back is
    # the same choice made again); an accepted one re-accepts
    # idempotently.  Anything else is not in a reviewable state.
    if any(
        (row.get("provenance") or {}).get("reviewStatus")
        not in {PDF_REVIEW_REQUIRED, PDF_REVIEW_SUPERSEDED, "accepted"}
        for row in rows
    ):
        raise ValueError(f"Filed {mechanic} candidate is not awaiting review")
    durations = sorted({row.get("duration") for row in rows if row.get("duration") is not None})
    if mechanic in {"coi", "surrender", "corridor"} and durations:
        expected = list(range(1, max(durations) + 1))
        if durations != expected:
            raise ValueError(f"Filed {mechanic} candidate has gaps in its duration schedule")

    accepted_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        provenance = {
            **(row.get("provenance") or {}),
            "reviewStatus": "accepted",
            "reviewedBy": reviewed_by,
            "reviewedAt": accepted_at,
        }
        provenance.pop("supersededBy", None)
        provenance.pop("supersededAt", None)
        row["provenance"] = provenance
    superseded_ids: List[str] = []
    overridden_ids: List[str] = []
    if candidate is not None:
        prior_status = candidate.get("reviewStatus")
        candidate["rows"] = rows
        candidate["reviewStatus"] = "accepted"
        # Selector slices accumulate: this acceptance displaces
        # nothing by itself.  What it can do is DISAGREE with an
        # already-accepted candidate on rows both carry — the one
        # genuine decision in the model.  A candidate that is not
        # currently in force asserts ALL its rows on acceptance
        # (a superseded candidate's rows were all overridden, so
        # re-accepting it is exactly that decision again); one that
        # is in force asserts its effective rows.
        if resolve_conflict and candidate.get("overriddenSelectors"):
            # Re-deciding in this candidate's favour restores its
            # overridden rows; the conflict computation below then
            # re-decides them against the current holder.
            candidate.pop("overriddenSelectors", None)
            candidate.pop("overriddenBy", None)
            candidate.pop("overriddenAt", None)
        effective_rows = (
            list(rows)
            if prior_status != "accepted"
            else candidate_effective_rows(candidate)
        )
        conflicts_by_other: Dict[str, Tuple[Dict[str, Any], List[Tuple[Any, ...]]]] = {}
        for other in candidates:
            if other is candidate or other.get("reviewStatus") != "accepted":
                continue
            conf = conflicting_row_selectors(
                mechanic, effective_rows, candidate_effective_rows(other)
            )
            if conf:
                conflicts_by_other[str(other.get("id"))] = (other, conf)
        if conflicts_by_other and not resolve_conflict:
            other, conf = next(iter(conflicts_by_other.values()))
            example = ", ".join(
                f"{field} {value}"
                for field, value in zip(ROW_SELECTOR_FIELDS, conf[0])
                if value is not None
            )
            total = sum(len(item_conf) for _, item_conf in conflicts_by_other.values())
            raise ValueError(
                f"Filed {mechanic} candidate conflicts with the accepted table"
                f" from {other.get('filename') or 'the filing'}"
                f" on {total} row(s) (e.g. {example}): the filings disagree"
                " on those rows. Accept it with conflict resolution to let"
                " this candidate's rows govern where they disagree, or keep"
                " the version in force."
            )
        reviews = result.setdefault("reviews", {})
        for other_id, (other, conf) in conflicts_by_other.items():
            overridden = _overridden_selector_keys(other)
            overridden.update(conf)
            other["overriddenSelectors"] = sorted(
                (list(key) for key in overridden), key=str
            )
            other["overriddenBy"] = candidate.get("id")
            other["overriddenAt"] = accepted_at
            overridden_ids.append(other_id)
            other_rows = list(other.get("rows") or [])
            if other_rows and all(
                row_selector_key(row) in overridden for row in other_rows
            ):
                # Every row lost the override: the candidate is
                # genuinely replaced — the same slice, corrected —
                # which is the one case "superseded" names.
                other["reviewStatus"] = PDF_REVIEW_SUPERSEDED
                for other_row in other_rows:
                    other_row["provenance"] = {
                        **(other_row.get("provenance") or {}),
                        "reviewStatus": PDF_REVIEW_SUPERSEDED,
                        "supersededBy": candidate.get("id"),
                        "supersededAt": accepted_at,
                    }
                superseded_ids.append(other_id)
                prior_review = reviews.get(other_id)
                if isinstance(prior_review, dict):
                    prior_review["status"] = PDF_REVIEW_SUPERSEDED
                    prior_review["supersededBy"] = candidate.get("id")
                    prior_review["supersededAt"] = accepted_at
        active_rows, residual = accepted_union_rows(candidates, mechanic)
        if residual:
            raise ValueError(
                f"Filed {mechanic} candidates conflict for selector {residual[0]}"
            )
    else:
        active_rows = dedupe_rows(rows, mechanic)
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
        "supersededCandidateIds": superseded_ids,
        "overriddenCandidateIds": overridden_ids,
    }
    return result


def _row_identity_key(row: Dict[str, Any]) -> str:
    """A row's identity without its provenance — the same
    canonicalisation the candidate-id signature uses, so a row from
    a re-extraction matches its prior incarnation exactly."""

    canonical = {key: value for key, value in row.items() if key != "provenance"}
    return json.dumps(canonical, sort_keys=True, default=str)


#: Row-provenance fields a review decision writes; a carry-over
#: transplants exactly these from the prior row to its re-extracted
#: twin, leaving the fresh extraction's own provenance intact.
_REVIEW_PROVENANCE_FIELDS = (
    "reviewStatus", "reviewedBy", "reviewedAt", "supersededBy", "supersededAt",
)


def carry_over_decision_state(
    fresh_artifact: Dict[str, Any], prior_artifact: Dict[str, Any]
) -> Dict[str, Any]:
    """Carry a workspace's confirmed decision state across an
    analysis rebuild, merged by candidate identity.

    Analysis rebuilds the mechanics artifact from the documents;
    without this step a re-run silently discards every human
    decision that lives on the artifact (the Oct 27, 2026 defect:
    equation approvals were carried over, table acceptances were
    not, so one re-run un-filed every table).  Candidate ids are
    content hashes of their rows, so a re-extraction of unchanged
    documents reproduces the same ids and decisions transplant by
    id: candidate review state (accepted / superseded, override
    records), the per-row review provenance, the ``reviews`` log,
    proposal dismissals, and any synthetic table state.  The table
    in force is then rebuilt as the union of the accepted
    candidates, exactly as an acceptance builds it.

    A decision whose candidate no longer exists in the fresh
    extraction (its document changed or went away) is NOT carried
    and NOT silently dropped either: it is named in the returned
    ``notes`` so the analysis result can state it.  Workspace edits
    and corrections are carried by their own re-apply steps, which
    run after this one and win their mechanics' usable rows, exactly
    as they did when first applied.
    """

    result = deepcopy(fresh_artifact or {})
    prior = prior_artifact or {}
    notes: List[str] = []

    # Synthetic tables are confirmed state too (a reviewed synthetic
    # schedule the user accepted); their rows exist nowhere in the
    # documents, so they transplant with their usable rows.
    prior_synthetic = prior.get("synthetic") or {}
    if prior_synthetic:
        result["synthetic"] = deepcopy(prior_synthetic)
        for mechanic in prior_synthetic:
            rows = list((prior.get("usable") or {}).get(mechanic) or [])
            if rows:
                result.setdefault("usable", {})[mechanic] = deepcopy(rows)
                result.setdefault("status", {})[mechanic] = (
                    (prior.get("status") or {}).get(mechanic) or "synthetic_scenario"
                )

    # Proposal dismissals persist so a dismissed proposal does not
    # regenerate after a re-run.
    if prior.get("dismissedProposals"):
        result["dismissedProposals"] = deepcopy(prior["dismissedProposals"])

    for mechanic in MECHANIC_KEYS:
        fresh_candidates = [
            candidate
            for candidate in (result.get("candidates") or {}).get(mechanic) or []
            if isinstance(candidate, dict)
        ]
        prior_by_id = {
            str(candidate.get("id")): candidate
            for candidate in (prior.get("candidates") or {}).get(mechanic) or []
            if isinstance(candidate, dict) and candidate.get("id")
        }
        decided_ids: List[str] = []
        for candidate in fresh_candidates:
            prior_candidate = prior_by_id.get(str(candidate.get("id")))
            if prior_candidate is None:
                continue
            prior_status = prior_candidate.get("reviewStatus")
            if prior_status not in ("accepted", PDF_REVIEW_SUPERSEDED):
                continue
            candidate["reviewStatus"] = prior_status
            for field in ("overriddenSelectors", "overriddenBy", "overriddenAt"):
                if field in prior_candidate:
                    candidate[field] = deepcopy(prior_candidate[field])
            prior_rows = {}
            for prior_row in prior_candidate.get("rows") or []:
                prior_rows.setdefault(_row_identity_key(prior_row), prior_row)
            for row in candidate.get("rows") or []:
                prior_row = prior_rows.get(_row_identity_key(row))
                if prior_row is None:
                    continue
                prior_provenance = prior_row.get("provenance") or {}
                provenance = dict(row.get("provenance") or {})
                for field in _REVIEW_PROVENANCE_FIELDS:
                    if field in prior_provenance:
                        provenance[field] = prior_provenance[field]
                    else:
                        provenance.pop(field, None)
                row["provenance"] = provenance
            decided_ids.append(str(candidate.get("id")))
        fresh_ids = {str(candidate.get("id")) for candidate in fresh_candidates}
        for prior_id, prior_candidate in prior_by_id.items():
            if (
                prior_candidate.get("reviewStatus")
                in ("accepted", PDF_REVIEW_SUPERSEDED)
                and prior_id not in fresh_ids
            ):
                notes.append(
                    f"A previously {prior_candidate.get('reviewStatus')} filed "
                    f"{mechanic} table (candidate {prior_id}) is no longer "
                    "extracted from the workspace's documents; its review "
                    "decision was not carried over."
                )
        if any(c.get("reviewStatus") == "accepted" for c in fresh_candidates):
            union_rows, conflicts = accepted_union_rows(fresh_candidates, mechanic)
            if conflicts:
                # Stored state that disagrees with itself must not be
                # merged silently; the mechanic states its absence
                # until a human re-decides the contested rows.
                notes.append(
                    f"The carried-over accepted {mechanic} tables disagree on "
                    f"{len(conflicts)} row(s); the mechanic was left without "
                    "a table in force rather than merging contradictory rows."
                )
            else:
                result.setdefault("usable", {})[mechanic] = union_rows
                result.setdefault("status", {})[mechanic] = "executable"
                (result.get("synthetic") or {}).pop(mechanic, None)
        if decided_ids:
            for key, review in (prior.get("reviews") or {}).items():
                if key in decided_ids or (
                    isinstance(review, dict)
                    and str(review.get("candidateId")) in decided_ids
                ):
                    result.setdefault("reviews", {})[key] = deepcopy(review)
    return {"artifact": result, "notes": notes}
