from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple


Key = Tuple[str, str, str, int, int, int]


def _norm_str(value: Any) -> str:
    return str(value).strip()


@dataclass
class Term23MortalitySurface:
    """Thin in-memory lookup for Term23 2017 CSO mortality.

    Keys on (gender, smoker_class, risk_class, face_band, issue_age, duration).
    Values are annual q_x.
    """

    rows: Dict[Key, float]
    nonforfeiture_rate: float = 0.0

    def q_2017_cso(
        self,
        *,
        gender: str,
        smoker_class: str,
        risk_class: str,
        face_band: int,
        issue_age: int,
        duration: int,
    ) -> Optional[float]:
        key: Key = (
            _norm_str(gender),
            _norm_str(smoker_class),
            _norm_str(risk_class),
            int(face_band),
            int(issue_age),
            int(duration),
        )
        return self.rows.get(key)


def build_term23_surface(records: Iterable[Mapping[str, Any]]) -> Optional[Term23MortalitySurface]:
    """Construct a Term23 mortality surface from actuarial_tables_term23 records.

    The expected record schema is documented in docs/actuarial_tables_term23_schema.md.
    Returns None if no records are provided.
    """

    rows: Dict[Key, float] = {}
    nf_rate: float = 0.0
    seen_rate = False

    for rec in records:
        try:
            gender = _norm_str(rec["gender"])
            smoker_class = _norm_str(rec["smoker_class"])
            risk_class = _norm_str(rec["risk_class"])
            face_band = int(rec["face_band"])
            issue_age = int(rec["issue_age"])
            duration = int(rec["duration"])
            qx = float(rec["qx"])
        except KeyError:
            # Skip malformed rows in early POC data.
            continue

        key: Key = (gender, smoker_class, risk_class, face_band, issue_age, duration)
        rows[key] = qx

        if not seen_rate and "nonforfeiture_int_rate" in rec:
            try:
                nf_rate = float(rec["nonforfeiture_int_rate"])
                seen_rate = True
            except (TypeError, ValueError):
                pass

    if not rows:
        return None

    return Term23MortalitySurface(rows=rows, nonforfeiture_rate=nf_rate)
