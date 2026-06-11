from __future__ import annotations

"""AI helpers for Product Model Review (PMR) summarisation and decision support.

These helpers are intentionally product-agnostic: they operate on the
already-assembled PMR JSON payload and return lightweight, structured
summaries that the UI or CLI can surface to an actuary. They do *not*
write to Postgres or MinIO themselves; callers remain responsible for
persisting any accepted decisions.
"""

from typing import Any, Dict, List
import json
import os

from openai import OpenAI


def _get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")
    return OpenAI(api_key=api_key)


def _pmr_system_prompt() -> str:
    return (
        "You are an actuarial review assistant. You read a JSON payload "
        "representing a Product Model Review (PMR) for a life insurance "
        "product and produce a concise, structured summary for a human "
        "actuary.\n\n"
        "The PMR JSON includes product metadata, scenario evidence, "
        "projection summaries, assumptions, known gaps, and prior "
        "decisions.\n\n"
        "Your output MUST be a single JSON object with this shape (no "
        "extra commentary):\n"
        "{\n"
        "  \"summary\": string,\n"
        "  \"key_risks\": [string, ...],\n"
        "  \"key_gaps\": [string, ...],\n"
        "  \"scenario_highlights\": [string, ...],\n"
        "  \"data_quality_notes\": [string, ...]\n"
        "}\n\n"
        "Keep summary under ~300 words. key_risks and key_gaps should be "
        "short, actionable bullet points. If a section has nothing "
        "material, return an empty list for that section."
    )


def _decision_system_prompt() -> str:
    return (
        "You are an actuarial decision-support assistant. Based on a "
        "Product Model Review (PMR) JSON and a separate PMR summary, you "
        "propose a draft decision for an actuary. You do not replace the "
        "actuary; you provide a starting point.\n\n"
        "Your output MUST be a single JSON object with this shape (no "
        "extra commentary):\n"
        "{\n"
        "  \"suggested_decision\": string,    // e.g. 'approve_for_poc', 'approve_with_exclusions', 'request_changes', 'reject'\n"
        "  \"suggested_exclusions\": string | null,\n"
        "  \"rationale\": [string, ...],\n"
        "  \"risk_status\": string | null     // e.g. 'clean', 'warnings_found', 'high_risk'\n"
        "}\n\n"
        "Only choose from the allowed decision values; if unsure, use "
        "'request_changes' and explain what additional evidence or checks "
        "are needed."
    )


def summarise_pmr(
    pmr_payload: Dict[str, Any],
    model: str | None = None,
    feedback: str | None = None,
    previous: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return a structured AI-generated summary for a PMR payload.

    When feedback/previous are provided, they are included in the prompt
    so the model can correct or refine an earlier draft summary.
    """

    client = _get_openai_client()
    model = model or os.getenv("PMR_SUMMARY_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini"))

    try:
        pmr_text = json.dumps(pmr_payload, sort_keys=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to serialise PMR payload: {exc}") from exc

    user_lines = []
    if previous is not None or feedback:
        user_lines.append("Previous PMR summary (may be incorrect):")
        try:
            user_lines.append(json.dumps(previous or {}, indent=2, sort_keys=True))
        except Exception:
            user_lines.append(str(previous))
        user_lines.append("")
        user_lines.append("Reviewer feedback:")
        user_lines.append(feedback or "(none provided)")
        user_lines.append("")
        user_lines.append("Please correct or refine the summary accordingly based on this feedback.")
        user_lines.append("")
    user_lines.append("=== PMR JSON START ===")
    user_lines.append(pmr_text[:100000])
    user_lines.append("=== PMR JSON END ===")

    messages = [
        {"role": "system", "content": _pmr_system_prompt()},
        {"role": "user", "content": "\n".join(user_lines)},
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
    )

    raw = resp.choices[0].message.content or ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:  # noqa: BLE001
        raise RuntimeError(f"LLM PMR summary was not valid JSON: {exc}\nRaw: {raw}") from exc

    # Normalise expected keys with safe defaults.
    summary: Dict[str, Any] = {}
    summary["summary"] = data.get("summary") if isinstance(data, dict) else None
    summary["key_risks"] = data.get("key_risks") if isinstance(data, dict) else []
    summary["key_gaps"] = data.get("key_gaps") if isinstance(data, dict) else []
    summary["scenario_highlights"] = data.get("scenario_highlights") if isinstance(data, dict) else []
    summary["data_quality_notes"] = data.get("data_quality_notes") if isinstance(data, dict) else []

    # Ensure list types.
    for key in ("key_risks", "key_gaps", "scenario_highlights", "data_quality_notes"):
        val = summary.get(key)
        if not isinstance(val, list):
            summary[key] = []
    if not isinstance(summary.get("summary"), str):
        summary["summary"] = ""

    return summary


def propose_decision(
    pmr_payload: Dict[str, Any],
    pmr_summary: Dict[str, Any],
    model: str | None = None,
    feedback: str | None = None,
    previous: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return a draft decision suggestion based on PMR + its summary.

    When feedback/previous are provided, they are included in the prompt
    so the model can correct or refine an earlier draft decision.
    """

    client = _get_openai_client()
    model = model or os.getenv("PMR_DECISION_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini"))

    try:
        base = {"pmr": pmr_payload, "summary": pmr_summary}
        base_text = json.dumps(base, sort_keys=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to serialise PMR+summary payload: {exc}") from exc

    user_lines = []
    if previous is not None or feedback:
        user_lines.append("Previous decision suggestion (may be incorrect):")
        try:
            user_lines.append(json.dumps(previous or {}, indent=2, sort_keys=True))
        except Exception:
            user_lines.append(str(previous))
        user_lines.append("")
        user_lines.append("Reviewer feedback:")
        user_lines.append(feedback or "(none provided)")
        user_lines.append("")
        user_lines.append("Please correct or refine the decision suggestion accordingly.")
        user_lines.append("")
    user_lines.append("=== PMR+SUMMARY JSON START ===")
    user_lines.append(base_text[:100000])
    user_lines.append("=== PMR+SUMMARY JSON END ===")

    messages = [
        {"role": "system", "content": _decision_system_prompt()},
        {"role": "user", "content": "\n".join(user_lines)},
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
    )

    raw = resp.choices[0].message.content or ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:  # noqa: BLE001
        raise RuntimeError(f"LLM PMR decision suggestion was not valid JSON: {exc}\nRaw: {raw}") from exc

    result: Dict[str, Any] = {}
    result["suggested_decision"] = data.get("suggested_decision") if isinstance(data, dict) else None
    result["suggested_exclusions"] = data.get("suggested_exclusions") if isinstance(data, dict) else None
    result["rationale"] = data.get("rationale") if isinstance(data, dict) else []
    result["risk_status"] = data.get("risk_status") if isinstance(data, dict) else None

    if not isinstance(result.get("rationale"), list):
        result["rationale"] = []

    return result
