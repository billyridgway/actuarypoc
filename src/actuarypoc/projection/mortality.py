from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from actuarypoc.connectors.base import CSVConnector
from actuarypoc.dsl.policy_dsl import PolicyFormula


Key = Tuple[str, str, str, int, int, int]


def _norm_str(value: Any) -> str:
    return str(value).strip()


def _norm_gender(value: Any) -> str:
    """Normalize gender values to a compact canonical form.

    This keeps the table tolerant of inputs like "M" / "Male" / "MALE" and
    "F" / "Female" / "FEMALE".
    """

    s = str(value).strip().upper()
    if s in {"M", "MALE"}:
        return "M"
    if s in {"F", "FEMALE"}:
        return "F"
    return s


def _norm_smoker_class(value: Any) -> str:
    """Normalize smoker / tobacco classes to NS / S.

    The Term23 schema uses "Nontobacco" / "Tobacco"; P12TRF sample policies
    use abbreviations like "NS" / "S". We collapse all of these to a small
    canonical alphabet so the mortality surface can be shared.
    """

    s = str(value).strip().upper()
    if s in {"NONTABACCO", "NONTobacco", "NONTOBACCO", "NONS MOKER", "NONSMOKER", "NS"}:
        return "NS"
    if s in {"TOBACCO", "SMOKER", "S"}:
        return "S"
    return s


def _norm_risk_class(value: Any) -> str:
    """Normalize risk class labels into a canonical bucket.

    This helper is intentionally generic and product-agnostic. For the
    Term23 2017 CSO slice we expect human-readable labels like "Standard";
    product-specific mappings (e.g. P12TRF filed classes → Standard /
    Preferred cells) should live in the DSL, actuarial tables, or
    AssumptionSets rather than here.
    """

    s = str(value).strip().upper()

    # Term23 textual labels – keep them distinct so a richer grid can be
    # wired later without changing how the surface keys are built.
    if s.replace(" ", "") == "SUPERPREFERRED":
        return "SUPER_PREFERRED"
    if s.replace(" ", "") == "PREFERRED":
        return "PREFERRED"
    if s.replace(" ", "") in {"SUPERSTANDARD", "STANDARDPLUS"}:
        return "SUPER_STANDARD"
    if s.replace(" ", "") == "STANDARD":
        return "STANDARD"

    return s


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
            _norm_gender(gender),
            _norm_smoker_class(smoker_class),
            _norm_risk_class(risk_class),
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
            gender = _norm_gender(rec["gender"])
            smoker_class = _norm_smoker_class(rec["smoker_class"])
            risk_class = _norm_risk_class(rec["risk_class"])
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


def load_term23_surface_from_csv(path: str) -> Optional[Term23MortalitySurface]:
    """Helper for tests / CLIs: build a Term23 mortality surface from a CSV.

    This uses the same tolerant CSVConnector as other sample-data readers so
    early POC files with comments or minor glitches still work.
    """

    connector = CSVConnector(path)
    records = list(connector.fetch())
    return build_term23_surface(records)


def resolve_mortality_risk_class(formula: PolicyFormula, raw_risk_class: str) -> str:
    """Resolve a raw risk class into the key used by mortality tables.

    This is intentionally generic and data-driven:

    - It looks for a ``mortality_risk_class_mapping`` dictionary in the
      DSL ``meta`` section for the loaded :class:`PolicyFormula`.
    - If present, it uses that mapping (case-insensitively on keys) to map
      the raw PAS / policy risk class into whatever label the mortality
      surface expects (e.g. "Standard").
    - If no mapping is present, or the value is not found, the raw value is
      returned unchanged.

    Python never needs to know which product (e.g. P12TRF) is being
    projected; all product-specific mapping lives in DSL / AssumptionSets.
    """

    meta = getattr(formula, "meta", None) or {}
    mapping = meta.get("mortality_risk_class_mapping")
    if not isinstance(mapping, dict):
        return raw_risk_class

    raw = str(raw_risk_class)

    # Direct key lookup first.
    if raw in mapping:
        return str(mapping[raw])

    # Fallback to case-insensitive match without mutating the original dict.
    raw_lower = raw.lower()
    for key, value in mapping.items():
        try:
            if str(key).lower() == raw_lower:
                return str(value)
        except Exception:
            continue

    return raw
