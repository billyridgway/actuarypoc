"""Strict extraction of executable UL mechanics from workspace tables.

Only explicitly labelled tabular data is accepted.  Narrative PDF text is
deliberately excluded: losing table boundaries or units can turn a citation
into an invented actuarial assumption.
"""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd


MAX_DURATION = 121
COI_UNITS = {"per_1000_monthly", "per_1000_annual", "percent_nar_annual"}
SURRENDER_UNITS = {"percent_face", "per_1000_face", "fixed"}
FEE_UNITS = {"annual_fixed", "modal_fixed", "per_1000_face_annual"}


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


def extract_ul_mechanics(filename: str, content: bytes) -> Dict[str, Any]:
    """Return validated mechanics plus non-fatal extraction warnings."""

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
    coi = list(raw.get("coi") or [])
    if coi:
        usable["coi"] = coi
    surrender = list(raw.get("surrender") or [])
    surrender_durations = sorted({row.get("duration") for row in surrender})
    if surrender and surrender_durations == list(range(1, max(surrender_durations) + 1)):
        usable["surrender"] = surrender
    fees = list(raw.get("fees") or [])
    fee_durations = sorted({row.get("duration") for row in fees if row.get("duration") is not None})
    if fees and (
        any(row.get("duration") is None for row in fees)
        or fee_durations == list(range(1, 31))
    ):
        usable["fees"] = fees
    return usable
