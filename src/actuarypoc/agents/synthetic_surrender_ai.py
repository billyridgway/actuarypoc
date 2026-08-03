"""AI-assisted deterministic synthetic surrender-charge schedules."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from openai import OpenAI


DEFAULT_PARAMETERS: Dict[str, Any] = {
    "initial_charge_percent_face": 0.10,
    "terminal_charge_percent_face": 0.0,
    "period_years": 15,
    "curve_shape": "linear",
    "rationale": "Synthetic declining surrender schedule for scenario testing only.",
}


def _validate_parameters(raw: Mapping[str, Any]) -> Dict[str, Any]:
    parameters = dict(DEFAULT_PARAMETERS)
    parameters.update({key: value for key, value in raw.items() if value is not None})
    initial = float(parameters["initial_charge_percent_face"])
    terminal = float(parameters["terminal_charge_percent_face"])
    period = int(parameters["period_years"])
    shape = str(parameters["curve_shape"]).lower().strip()
    if not 0.0 <= terminal <= initial <= 0.50:
        raise ValueError("Surrender charge percentages must satisfy 0 <= terminal <= initial <= 0.50")
    if not 1 <= period <= 40:
        raise ValueError("period_years must be between 1 and 40")
    if shape not in {"linear", "front_loaded", "back_loaded"}:
        raise ValueError("curve_shape must be linear, front_loaded, or back_loaded")
    parameters.update({
        "initial_charge_percent_face": initial,
        "terminal_charge_percent_face": terminal,
        "period_years": period,
        "curve_shape": shape,
        "rationale": str(parameters.get("rationale") or DEFAULT_PARAMETERS["rationale"]),
    })
    return parameters


def _repair_agent_parameters(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert a plausible but invalid agent proposal into safe bounded inputs."""

    repaired = dict(raw)
    try:
        initial = float(repaired.get("initial_charge_percent_face", DEFAULT_PARAMETERS["initial_charge_percent_face"]))
        terminal = float(repaired.get("terminal_charge_percent_face", DEFAULT_PARAMETERS["terminal_charge_percent_face"]))
    except (TypeError, ValueError):
        initial = float(DEFAULT_PARAMETERS["initial_charge_percent_face"])
        terminal = float(DEFAULT_PARAMETERS["terminal_charge_percent_face"])
    # Models sometimes return whole percentages (10) rather than decimals (.10).
    if initial > 1.0:
        initial /= 100.0
    if terminal > 1.0:
        terminal /= 100.0
    initial = min(0.50, max(0.0, initial))
    terminal = min(0.50, max(0.0, terminal))
    if terminal > initial:
        initial, terminal = terminal, initial
    try:
        period = min(40, max(1, int(repaired.get("period_years", DEFAULT_PARAMETERS["period_years"]))))
    except (TypeError, ValueError):
        period = int(DEFAULT_PARAMETERS["period_years"])
    shape = str(repaired.get("curve_shape") or "linear").lower().strip()
    if shape not in {"linear", "front_loaded", "back_loaded"}:
        shape = "linear"
    repaired.update({
        "initial_charge_percent_face": initial,
        "terminal_charge_percent_face": terminal,
        "period_years": period,
        "curve_shape": shape,
        "rationale": str(repaired.get("rationale") or DEFAULT_PARAMETERS["rationale"]),
        "agentParametersAdjusted": True,
    })
    return _validate_parameters(repaired)


def propose_synthetic_surrender_parameters(
    *, product_code: str, product_context: str, model: Optional[str] = None,
) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")
    selected_model = model or os.getenv("SYNTHETIC_SURRENDER_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini"))
    prompt = (
        "Propose a conservative synthetic surrender-charge schedule for projection testing only. "
        "It is not filed evidence. Return one JSON object containing initial_charge_percent_face, "
        "terminal_charge_percent_face, period_years, curve_shape (linear, front_loaded, or back_loaded), "
        f"and rationale.\nProduct: {product_code}\nContext:\n{product_context[:20000]}"
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
        raise RuntimeError(f"AI surrender proposal was not valid JSON: {exc}") from exc
    if not isinstance(proposed, dict):
        raise RuntimeError("AI surrender proposal must be a JSON object")
    try:
        validated = _validate_parameters(proposed)
    except (TypeError, ValueError):
        validated = _repair_agent_parameters(proposed)
    validated["model"] = selected_model
    return validated


def build_synthetic_surrender_schedule(*, parameters: Mapping[str, Any]) -> List[Dict[str, Any]]:
    validated = _validate_parameters(parameters)
    period = validated["period_years"]
    rows: List[Dict[str, Any]] = []
    for duration in range(1, period + 1):
        progress = 1.0 if period == 1 else (duration - 1) / (period - 1)
        remaining = 1.0 - progress
        if validated["curve_shape"] == "front_loaded":
            remaining = remaining ** 1.5
        elif validated["curve_shape"] == "back_loaded":
            remaining = remaining ** 0.65
        charge = validated["terminal_charge_percent_face"] + (
            validated["initial_charge_percent_face"] - validated["terminal_charge_percent_face"]
        ) * remaining
        rows.append({
            "duration": duration,
            "issue_age": None,
            "sex": None,
            "charge": round(charge, 8),
            "charge_unit": "percent_face",
            "provenance": {
                "filename": "AI-generated synthetic surrender schedule",
                "sourceType": "ai_synthetic",
            },
        })
    return rows


def synthetic_surrender_preview(*, parameters: Mapping[str, Any]) -> Dict[str, Any]:
    rows = build_synthetic_surrender_schedule(parameters=parameters)
    return {
        "mechanic": "surrender",
        "parameters": _validate_parameters(parameters),
        "rowCount": len(rows),
        "maximumCharge": max(row["charge"] for row in rows),
        "minimumCharge": min(row["charge"] for row in rows),
        "sampleRows": rows[:3] + ([] if len(rows) <= 4 else [rows[-1]]),
        "rows": rows,
        "disclaimer": "Synthetic AI-generated scenario data. Not a filed, approved, or evidenced surrender schedule.",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["build_synthetic_surrender_schedule", "propose_synthetic_surrender_parameters", "synthetic_surrender_preview"]
