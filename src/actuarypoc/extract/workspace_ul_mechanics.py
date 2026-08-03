"""Strict extraction of executable UL mechanics from workspace tables.

Only explicitly labelled tabular data is accepted.  Narrative PDF text is
deliberately excluded: losing table boundaries or units can turn a citation
into an invented actuarial assumption.
"""

from __future__ import annotations

import io
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from PyPDF2 import PdfReader


MAX_DURATION = 121
COI_UNITS = {"per_1000_monthly", "per_1000_annual", "percent_nar_annual"}
SURRENDER_UNITS = {"percent_face", "per_1000_face", "fixed"}
FEE_UNITS = {"annual_fixed", "modal_fixed", "per_1000_face_annual"}
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
    return mechanics


def _read_pdf_mechanics(filename: str, content: bytes) -> Dict[str, Any]:
    mechanics: Dict[str, List[Dict[str, Any]]] = {"coi": [], "surrender": [], "fees": []}
    warnings: List[str] = []
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001
        return {"mechanics": mechanics, "warnings": [f"{filename}: PDF could not be read: {exc}"]}
    for page_number, page in enumerate(reader.pages, 1):
        try:
            extracted = _extract_pdf_page(filename, page_number, page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{filename} page {page_number}: PDF table extraction rejected: {exc}")
            continue
        for mechanic, rows in extracted.items():
            mechanics[mechanic].extend(rows)
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
    fee_durations = sorted({row.get("duration") for row in fees if row.get("duration") is not None})
    if fees and (
        any(row.get("duration") is None for row in fees)
        or fee_durations == list(range(1, 31))
    ):
        usable["fees"] = fees
    return usable
