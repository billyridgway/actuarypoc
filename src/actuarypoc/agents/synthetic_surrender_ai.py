"""AI-assisted deterministic synthetic surrender-charge schedules."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from openai import OpenAI


# Label persisted wherever a proposal's model is recorded when the model
# never produced the parameters: the deterministic fallback below. It must
# never read as an AI generation.
FALLBACK_MODEL_LABEL = "Deterministic fallback (AI model unavailable)"

# The product context is a JSON dump of the whole workspace snapshot; only
# a bounded excerpt goes to the model (CPU prefill cost on local models).
_CONTEXT_EXCERPT_CHARS = 6000


def _agent_timeout_seconds() -> float:
    """Per-call timeout for the synthetic-agent model request.

    Bounded so the generate flow always answers: the production model
    endpoint serialises requests and sleeps when idle, and the OpenAI SDK
    default (~600s, with retries) turned a slow or cold call into a button
    that hung for minutes. Override with SYNTHETIC_AGENT_TIMEOUT_S.
    """

    try:
        return float(os.getenv("SYNTHETIC_AGENT_TIMEOUT_S", "45"))
    except ValueError:
        return 45.0


DEFAULT_PARAMETERS: Dict[str, Any] = {
    "initial_charge_percent_account_value": 0.10,
    "terminal_charge_percent_account_value": 0.0,
    "period_years": 15,
    "curve_shape": "linear",
    "rationale": "Synthetic declining surrender schedule for scenario testing only.",
}

# Pre-Phase-1 parameter spellings expressed the synthetic schedule as a
# percentage of face amount. Eddy (actuary reviewer, Aug 7 2026) corrected
# that basis: surrender charges are a percentage of the account value. The
# legacy keys are still accepted on input as aliases for the same numeric
# percentages so stored proposals and older clients keep working.
_LEGACY_PARAMETER_ALIASES = {
    "initial_charge_percent_face": "initial_charge_percent_account_value",
    "terminal_charge_percent_face": "terminal_charge_percent_account_value",
}


def _canonicalise_parameters(raw: Mapping[str, Any]) -> Dict[str, Any]:
    parameters = dict(raw)
    for legacy_key, canonical_key in _LEGACY_PARAMETER_ALIASES.items():
        if parameters.get(canonical_key) is None and parameters.get(legacy_key) is not None:
            parameters[canonical_key] = parameters[legacy_key]
        parameters.pop(legacy_key, None)
    return parameters


def _validate_parameters(raw: Mapping[str, Any]) -> Dict[str, Any]:
    parameters = dict(DEFAULT_PARAMETERS)
    parameters.update({key: value for key, value in _canonicalise_parameters(raw).items() if value is not None})
    initial = float(parameters["initial_charge_percent_account_value"])
    terminal = float(parameters["terminal_charge_percent_account_value"])
    period = int(parameters["period_years"])
    shape = str(parameters["curve_shape"]).lower().strip()
    if not 0.0 <= terminal <= initial <= 0.50:
        raise ValueError("Surrender charge percentages must satisfy 0 <= terminal <= initial <= 0.50")
    if not 1 <= period <= 40:
        raise ValueError("period_years must be between 1 and 40")
    if shape not in {"linear", "front_loaded", "back_loaded"}:
        raise ValueError("curve_shape must be linear, front_loaded, or back_loaded")
    parameters.update({
        "initial_charge_percent_account_value": initial,
        "terminal_charge_percent_account_value": terminal,
        "period_years": period,
        "curve_shape": shape,
        "rationale": str(parameters.get("rationale") or DEFAULT_PARAMETERS["rationale"]),
    })
    return parameters


def _repair_agent_parameters(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert a plausible but invalid agent proposal into safe bounded inputs."""

    repaired = _canonicalise_parameters(raw)
    try:
        initial = float(repaired.get("initial_charge_percent_account_value", DEFAULT_PARAMETERS["initial_charge_percent_account_value"]))
        terminal = float(repaired.get("terminal_charge_percent_account_value", DEFAULT_PARAMETERS["terminal_charge_percent_account_value"]))
    except (TypeError, ValueError):
        initial = float(DEFAULT_PARAMETERS["initial_charge_percent_account_value"])
        terminal = float(DEFAULT_PARAMETERS["terminal_charge_percent_account_value"])
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
        "initial_charge_percent_account_value": initial,
        "terminal_charge_percent_account_value": terminal,
        "period_years": period,
        "curve_shape": shape,
        "rationale": str(repaired.get("rationale") or DEFAULT_PARAMETERS["rationale"]),
        "agentParametersAdjusted": True,
    })
    return _validate_parameters(repaired)


def _fallback_parameters(*, reason: str) -> Dict[str, Any]:
    """Deterministic stand-in proposal, truthfully labelled as a fallback.

    Used whenever the model cannot produce parameters. The model field
    names the fallback (never a model), ``agentFallback`` is set, and the
    rationale states that the model was unavailable and the standard
    default parameters were used — so a schedule built from these
    parameters is never mistaken for an AI generation downstream.
    """

    parameters = _validate_parameters({})
    parameters["rationale"] = (
        f"AI model unavailable ({reason}); standard default parameters were used. "
        f"{DEFAULT_PARAMETERS['rationale']}"
    )
    parameters["agentFallback"] = True
    parameters["model"] = FALLBACK_MODEL_LABEL
    return parameters


def propose_synthetic_surrender_parameters(
    *, product_code: str, product_context: str, model: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask the model for bounded schedule parameters, with a bounded wait.

    The client is constructed with an explicit timeout and no retries.
    ANY model failure — timeout, connection error, invalid JSON, missing
    API key — returns the deterministic fallback parameters instead of
    raising, so the generate flow always answers.
    """

    selected_model = model or os.getenv("SYNTHETIC_SURRENDER_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini"))
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return _fallback_parameters(reason="no API key is configured")
    prompt = (
        "Propose a conservative synthetic surrender-charge schedule for projection testing only. "
        "Surrender charges are expressed as a percentage of the policy account value. "
        "It is not filed evidence. Return one JSON object containing initial_charge_percent_account_value, "
        "terminal_charge_percent_account_value, period_years, curve_shape (linear, front_loaded, or back_loaded), "
        f"and rationale.\nProduct: {product_code}\nContext:\n{product_context[:_CONTEXT_EXCERPT_CHARS]}"
    )
    try:
        response = OpenAI(
            api_key=api_key, timeout=_agent_timeout_seconds(), max_retries=0,
        ).chat.completions.create(
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
        proposed = json.loads(content)
        if not isinstance(proposed, dict):
            raise RuntimeError("AI surrender proposal must be a JSON object")
    except Exception as exc:
        return _fallback_parameters(reason=f"model request failed: {type(exc).__name__}")
    try:
        validated = _validate_parameters(proposed)
    except (TypeError, ValueError):
        validated = _repair_agent_parameters(proposed)
    validated["model"] = selected_model
    return validated


def build_synthetic_surrender_schedule(*, parameters: Mapping[str, Any]) -> List[Dict[str, Any]]:
    validated = _validate_parameters(parameters)
    if validated.get("agentFallback"):
        # The model never produced these parameters; the rows must not be
        # stamped as an AI generation.
        provenance = {
            "filename": "Deterministic fallback synthetic surrender schedule (AI model unavailable; standard parameters)",
            "sourceType": "deterministic_fallback",
        }
    else:
        provenance = {
            "filename": "AI-generated synthetic surrender schedule",
            "sourceType": "ai_synthetic",
        }
    period = validated["period_years"]
    rows: List[Dict[str, Any]] = []
    for duration in range(1, period + 1):
        progress = 1.0 if period == 1 else (duration - 1) / (period - 1)
        remaining = 1.0 - progress
        if validated["curve_shape"] == "front_loaded":
            remaining = remaining ** 1.5
        elif validated["curve_shape"] == "back_loaded":
            remaining = remaining ** 0.65
        charge = validated["terminal_charge_percent_account_value"] + (
            validated["initial_charge_percent_account_value"] - validated["terminal_charge_percent_account_value"]
        ) * remaining
        rows.append({
            "duration": duration,
            "issue_age": None,
            "sex": None,
            "charge": round(charge, 8),
            "charge_unit": "percent_account_value",
            "provenance": dict(provenance),
        })
    return rows


def synthetic_surrender_preview(*, parameters: Mapping[str, Any]) -> Dict[str, Any]:
    rows = build_synthetic_surrender_schedule(parameters=parameters)
    validated = _validate_parameters(parameters)
    fallback = bool(validated.get("agentFallback"))
    return {
        "mechanic": "surrender",
        "parameters": validated,
        "agentFallback": fallback,
        "rowCount": len(rows),
        "maximumCharge": max(row["charge"] for row in rows),
        "minimumCharge": min(row["charge"] for row in rows),
        "sampleRows": rows[:3] + ([] if len(rows) <= 4 else [rows[-1]]),
        "rows": rows,
        "disclaimer": (
            "Synthetic scenario data built from standard default parameters because the AI model "
            "was unavailable. Not a filed, approved, or evidenced surrender schedule."
            if fallback else
            "Synthetic AI-generated scenario data. Not a filed, approved, or evidenced surrender schedule."
        ),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["FALLBACK_MODEL_LABEL", "build_synthetic_surrender_schedule", "propose_synthetic_surrender_parameters", "synthetic_surrender_preview"]
