"""AI-assisted, deterministic synthetic COI table generation.

The model proposes a compact parameter set. Application code validates those
parameters and expands them into executable rows, so generated rates are
reproducible and never confused with filed evidence.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from openai import OpenAI


DEFAULT_PARAMETERS: Dict[str, Any] = {
    "base_rate_per_1000_annual": 0.35,
    "reference_age": 40,
    "annual_age_growth": 0.075,
    "male_multiplier": 1.12,
    "tobacco_multiplier": 2.20,
    "risk_class_multipliers": {"Preferred": 0.80, "Standard": 1.00},
    "minimum_rate": 0.05,
    "maximum_rate": 75.0,
    "rationale": "Conservative synthetic scenario parameters; not filed rates.",
}


def _validate_parameters(raw: Mapping[str, Any], risk_classes: Sequence[str]) -> Dict[str, Any]:
    parameters = dict(DEFAULT_PARAMETERS)
    parameters.update({key: value for key, value in raw.items() if value is not None})
    numeric_bounds = {
        "base_rate_per_1000_annual": (0.001, 10.0),
        "reference_age": (0, 120),
        "annual_age_growth": (0.0, 0.25),
        "male_multiplier": (0.5, 2.0),
        "tobacco_multiplier": (1.0, 5.0),
        "minimum_rate": (0.0, 10.0),
        "maximum_rate": (0.1, 200.0),
    }
    for field, (minimum, maximum) in numeric_bounds.items():
        value = float(parameters[field])
        if not minimum <= value <= maximum:
            raise ValueError(f"{field} must be between {minimum} and {maximum}")
        parameters[field] = int(value) if field == "reference_age" else value
    if parameters["minimum_rate"] >= parameters["maximum_rate"]:
        raise ValueError("minimum_rate must be less than maximum_rate")
    proposed = parameters.get("risk_class_multipliers") or {}
    normalized: Dict[str, float] = {}
    for risk_class in risk_classes:
        fallback = 0.8 if "preferred" in risk_class.lower() else 1.0
        multiplier = float(proposed.get(risk_class, fallback))
        if not 0.4 <= multiplier <= 3.0:
            raise ValueError(f"Risk-class multiplier for {risk_class} must be between 0.4 and 3.0")
        normalized[risk_class] = multiplier
    parameters["risk_class_multipliers"] = normalized
    parameters["rationale"] = str(parameters.get("rationale") or DEFAULT_PARAMETERS["rationale"])
    return parameters


def propose_synthetic_coi_parameters(
    *, product_code: str, product_context: str, risk_classes: Sequence[str], model: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask OpenAI for bounded parameters, falling back is deliberately not automatic."""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")
    selected_model = model or os.getenv("SYNTHETIC_COI_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini"))
    prompt = (
        "Propose conservative synthetic annual COI rate parameters for projection testing only. "
        "They are not filed rates and must not be described as evidence. Return one JSON object with: "
        "base_rate_per_1000_annual, reference_age, annual_age_growth, male_multiplier, "
        "tobacco_multiplier, risk_class_multipliers (object keyed by the supplied classes), "
        "minimum_rate, maximum_rate, and rationale.\n"
        f"Product: {product_code}\nRisk classes: {list(risk_classes)}\nContext:\n{product_context[:20000]}"
    )
    response = OpenAI(api_key=api_key).chat.completions.create(
        model=selected_model,
        messages=[
            {"role": "system", "content": "You are an actuarial modeling assistant. Output valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )
    content = (response.choices[0].message.content or "").strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else ""
        content = content.rsplit("```", 1)[0].strip()
    try:
        proposed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI COI proposal was not valid JSON: {exc}") from exc
    if not isinstance(proposed, dict):
        raise RuntimeError("AI COI proposal must be a JSON object")
    validated = _validate_parameters(proposed, risk_classes)
    validated["model"] = selected_model
    return validated


def build_synthetic_coi_table(
    *, parameters: Mapping[str, Any], risk_classes: Sequence[str], minimum_age: int = 0, maximum_age: int = 120,
) -> List[Dict[str, Any]]:
    """Expand validated parameters into a complete executable COI table."""

    if not 0 <= minimum_age <= maximum_age <= 120:
        raise ValueError("Synthetic COI ages must be between 0 and 120")
    classes = [str(value).strip() for value in risk_classes if str(value).strip()] or ["Standard"]
    validated = _validate_parameters(parameters, classes)
    rows: List[Dict[str, Any]] = []
    for attained_age in range(minimum_age, maximum_age + 1):
        age_factor = (1.0 + validated["annual_age_growth"]) ** (attained_age - validated["reference_age"])
        for sex in ("F", "M"):
            for risk_class in classes:
                for tobacco_status in ("Non-Tobacco", "Tobacco"):
                    rate = validated["base_rate_per_1000_annual"] * age_factor
                    if sex == "M":
                        rate *= validated["male_multiplier"]
                    rate *= validated["risk_class_multipliers"][risk_class]
                    if tobacco_status == "Tobacco":
                        rate *= validated["tobacco_multiplier"]
                    rate = min(validated["maximum_rate"], max(validated["minimum_rate"], rate))
                    rows.append({
                        "duration": None,
                        "attained_age": attained_age,
                        "sex": sex,
                        "risk_class": risk_class,
                        "tobacco_status": tobacco_status,
                        "rate": round(rate, 6),
                        "rate_unit": "per_1000_annual",
                        "provenance": {
                            "filename": "AI-generated synthetic COI table",
                            "sourceType": "ai_synthetic",
                        },
                    })
    return rows


def synthetic_coi_preview(*, parameters: Mapping[str, Any], risk_classes: Sequence[str]) -> Dict[str, Any]:
    rows = build_synthetic_coi_table(parameters=parameters, risk_classes=risk_classes)
    rates = [row["rate"] for row in rows]
    return {
        "parameters": _validate_parameters(parameters, risk_classes or ["Standard"]),
        "rowCount": len(rows),
        "minimumRate": min(rates),
        "maximumRate": max(rates),
        "sampleRows": [rows[0], rows[len(rows) // 2], rows[-1]],
        "rows": rows,
        "disclaimer": "Synthetic AI-generated scenario data. Not filed, approved, or evidenced rates.",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["build_synthetic_coi_table", "propose_synthetic_coi_parameters", "synthetic_coi_preview"]
