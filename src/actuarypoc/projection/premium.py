from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from actuarypoc.connectors.base import CSVConnector


# (issue_age, gender, risk_class, face_band, level_period)
PremiumKey = Tuple[int, str, str, int, int]


def _norm_gender(value: Any) -> str:
    """Normalize gender values to a compact canonical form.

    This keeps the table tolerant of inputs like "M" / "Male" / "MALE" and
    "F" / "Female" / "FEMALE" without being product-specific.
    """

    s = str(value).strip().upper()
    if s in {"M", "MALE"}:
        return "M"
    if s in {"F", "FEMALE"}:
        return "F"
    return s


def select_face_band(meta: Dict[str, Any], face_amount: float) -> Optional[int]:
    """Select a face band based on DSL/meta configuration.

    Expects ``meta.get("face_bands")`` to be a list of dicts with at least:

    - ``band``: identifier (typically an int)
    - ``min``: minimum face amount (inclusive)
    - ``max``: maximum face amount (inclusive; ``null``/None means no upper bound)

    Returns the matching ``band`` or ``None`` if no band configuration is
    present or no band matches.
    """

    bands = meta.get("face_bands") if isinstance(meta, dict) else None
    if not isinstance(bands, list):
        return None

    for band_def in bands:
        if not isinstance(band_def, dict):
            continue
        band_id = band_def.get("band")
        try:
            band_id_int = int(band_id)
        except (TypeError, ValueError):
            continue

        try:
            min_amt = float(band_def.get("min", 0.0) or 0.0)
        except (TypeError, ValueError):
            min_amt = 0.0
        max_raw = band_def.get("max", None)
        if max_raw is None:
            max_amt = None
        else:
            try:
                max_amt = float(max_raw)
            except (TypeError, ValueError):
                max_amt = None

        if face_amount < min_amt:
            continue
        if max_amt is not None and face_amount > max_amt:
            continue
        return band_id_int

    return None


@dataclass
class PremiumTable:
    """Thin in-memory lookup for per-1000 premiums.

    Keys on (issue_age, gender, risk_class, face_band, level_period).
    Values are premiums per $1,000 of face amount.

    The schema is intentionally generic; product-specific details (e.g. the
    exact set of risk classes or face bands) live in CSVs and DSL/Assumption
    config, not in this class.
    """

    rows: Dict[PremiumKey, float]

    def premium_per_1000(
        self,
        *,
        issue_age: int,
        gender: str,
        risk_class: str,
        face_band: int,
        level_period: int,
    ) -> Optional[float]:
        key: PremiumKey = (
            int(issue_age),
            _norm_gender(gender),
            str(risk_class).strip(),
            int(face_band),
            int(level_period),
        )
        return self.rows.get(key)


def build_premium_table(records: Iterable[Mapping[str, Any]]) -> Optional[PremiumTable]:
    """Construct a premium lookup table from tabular records.

    Expected columns (case-sensitive in this POC):

    - issue_age
    - gender
    - risk_class
    - face_band
    - level_period
    - premium_per_1000

    Returns None if no valid records are provided.
    """

    rows: Dict[PremiumKey, float] = {}

    for rec in records:
        try:
            issue_age = int(rec["issue_age"])
            gender = _norm_gender(rec["gender"])
            risk_class = str(rec["risk_class"]).strip()
            face_band = int(rec["face_band"])
            level_period = int(rec["level_period"])
            prem = float(rec["premium_per_1000"])
        except KeyError:
            # Skip malformed rows in early POC data.
            continue

        key: PremiumKey = (issue_age, gender, risk_class, face_band, level_period)
        rows[key] = prem

    if not rows:
        return None

    return PremiumTable(rows=rows)


def load_premium_table_from_csv(path: str) -> Optional[PremiumTable]:
    """Helper for tests / CLIs: build a PremiumTable from a CSV file.

    This uses the same tolerant CSVConnector as other sample-data readers so
    early POC files with comments or minor glitches still work.
    """

    connector = CSVConnector(path)
    records = list(connector.fetch())
    return build_premium_table(records)


@dataclass
class PremiumLookupService:
    """Generic premium lookup service.

    Given basic policy attributes (issue age, gender, risk class, face band,
    level period), returns the premium per $1,000 using an in-memory table.

    This component is intentionally product-agnostic. Product-specific table
    wiring (which CSV to load, which prefixes to use, etc.) should be driven
    by DSL/meta or AssumptionSets, not by hard-coded product ids here.
    """

    table: PremiumTable

    def premium_per_1000(
        self,
        *,
        issue_age: int,
        gender: str,
        risk_class: str,
        face_band: int,
        level_period: int,
    ) -> Optional[float]:
        return self.table.premium_per_1000(
            issue_age=issue_age,
            gender=gender,
            risk_class=risk_class,
            face_band=face_band,
            level_period=level_period,
        )
