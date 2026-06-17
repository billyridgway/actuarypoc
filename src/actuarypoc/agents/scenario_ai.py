from __future__ import annotations

"""AI helpers for proposing Product Review scenarios.

These helpers are intentionally product-agnostic: they read filing text
for a product (and optional filing id) from MinIO and ask an LLM to
propose a small set of representative scenarios in the ScenarioConfig
shape used by the UI.

They support feedback-driven retries: callers can pass a previous
scenario list plus human feedback, and the model is asked to correct or
refine its prior proposal accordingly.
"""

from typing import Any, Dict, List, Optional
import json
import os

from openai import OpenAI

from actuarypoc.extract.assumptions_for_product import load_filing_text_from_minio


def _get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")
    return OpenAI(api_key=api_key)


def _scenario_system_prompt() -> str:
    return (
        "You are an actuarial assistant. From life insurance product "
        "filings and actuarial memos, you propose a small set of "
        "representative scenarios for a Product Model Review.\n\n"
        "Each scenario should be suitable for exercising key dimensions "
        "of the product (age, coverage duration when applicable, "
        "risk/smoker class, face amount, and the way the policy is "
        "funded). Not all products have a level term or premium mode; for "
        "those products, it is fine to leave levelPeriod or premiumMode "
        "as null.\n\n"
        "Always make sure each scenario supplies a realistic faceAmount "
        "and an initial funding amount: for recurring-premium products, "
        "this is usually modalPremium; for single-premium or deposit "
        "products, treat modalPremium as the initial deposit and set an "
        "appropriate premiumMode such as 'SINGLE' when the filing "
        "supports it.\n\n"
        "Your output MUST be a single JSON array of objects, no extra "
        "commentary. Each object MUST have this shape:\n"
        "{\n"
        "  \"id\": string,\n"
        "  \"name\": string,\n"
        "  \"age\": number | null,\n"
        "  \"sex\": string | null,\n"
        "  \"smokerClass\": string | null,\n"
        "  \"riskClass\": string | null,\n"
        "  \"faceAmount\": number | null,\n"
        "  \"levelPeriod\": number | null,\n"
        "  \"premiumMode\": string | null,\n"
        "  \"modalPremium\": number | null,\n"
        "  \"purpose\": string | null,\n"
        "  \"dimensionsExercised\": [string, ...] | null,\n"
        "  \"source\": string | null\n"
        "}\n\n"
        "Return 3–10 scenarios. Use ids like 'S1', 'S2', ... and brief "
        "names. If something is unknown from the filing, use null rather "
        "than guessing values."
    )


def propose_scenarios_from_text(
    *,
    product_code: str,
    product_type: Optional[str],
    text: str,
    model: Optional[str] = None,
    feedback: Optional[str] = None,
    previous: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Use OpenAI to propose ScenarioConfig-style scenarios from filing text."""

    client = _get_openai_client()
    model = model or os.getenv("SCENARIO_EXTRACT_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini"))

    user_lines: List[str] = []
    user_lines.append(f"Target product_code: {product_code}")
    if product_type:
        user_lines.append(f"Product type: {product_type}")
    if previous is not None or feedback:
        user_lines.append("")
        user_lines.append("Previous scenario set (may be incorrect):")
        try:
            user_lines.append(json.dumps(previous or [], indent=2, sort_keys=True))
        except Exception:
            user_lines.append(str(previous))
        user_lines.append("")
        user_lines.append("Reviewer feedback:")
        user_lines.append(feedback or "(none provided)")
        user_lines.append("")
        user_lines.append("Please correct or refine the scenarios accordingly based on this feedback.")
        user_lines.append("")
    user_lines.append("=== FILING TEXT START ===")
    user_lines.append(text[:50000])
    user_lines.append("=== FILING TEXT END ===")

    messages = [
        {"role": "system", "content": _scenario_system_prompt()},
        {"role": "user", "content": "\n".join(user_lines)},
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
    )

    raw = resp.choices[0].message.content or ""

    # The model sometimes wraps the JSON array in Markdown-style code
    # fences (```json ... ```). Strip those fences before attempting to
    # parse so that callers see a clean error only when the inner content
    # is truly invalid JSON.
    def _strip_code_fences(text: str) -> str:
        s = text.strip()
        if s.startswith("```"):
            # Drop the first line (``` or ```json)
            parts = s.split("\n", 1)
            s = parts[1] if len(parts) == 2 else ""
        s = s.strip()
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
        return s.strip()

    clean = _strip_code_fences(raw)

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:  # noqa: BLE001
        raise RuntimeError(f"LLM scenario proposal was not valid JSON: {exc}\nRaw: {raw}") from exc

    if not isinstance(data, list):
        raise RuntimeError("LLM scenario proposal did not return a JSON array.")

    scenarios: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        scen: Dict[str, Any] = {}
        scen["id"] = str(item.get("id") or "").strip() or None
        scen["name"] = item.get("name")
        scen["age"] = item.get("age")
        scen["sex"] = item.get("sex")
        scen["smokerClass"] = item.get("smokerClass")
        scen["riskClass"] = item.get("riskClass")
        scen["faceAmount"] = item.get("faceAmount")
        scen["levelPeriod"] = item.get("levelPeriod")
        scen["premiumMode"] = item.get("premiumMode")
        scen["modalPremium"] = item.get("modalPremium")
        scen["purpose"] = item.get("purpose")
        scen["dimensionsExercised"] = item.get("dimensionsExercised")
        scen["source"] = item.get("source")
        scenarios.append(scen)

    # Filter out entries without ids to keep the UI simple.
    scenarios = [s for s in scenarios if s.get("id")]
    return scenarios


def generate_scenarios_for_product(
    *,
    product_code: str,
    filing_id: Optional[str] = None,
    product_type: Optional[str] = None,
    model: Optional[str] = None,
    feedback: Optional[str] = None,
    previous: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """High-level helper: (product, filing) → list of scenario dicts."""

    code_norm = (product_code or "").strip().upper()
    if not code_norm:
        raise ValueError("product_code is required")

    text = load_filing_text_from_minio(product_code=code_norm, filing_id=filing_id)
    return propose_scenarios_from_text(
        product_code=code_norm,
        product_type=product_type,
        text=text,
        model=model,
        feedback=feedback,
        previous=previous,
    )
