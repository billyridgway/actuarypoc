from __future__ import annotations

"""LLM-backed extraction of ProductMechanic candidates from filing text.

This is intentionally minimal and product-agnostic for v0.1. It mirrors the
pattern used by the assumptions extractor but targets ProductMechanic-shaped
JSON objects instead of AssumptionSets.
"""

from typing import Any, Dict, List, Optional

import json
import os

from openai import OpenAI

from actuarypoc.domain.product_mechanics import FilingSource, ProductMechanic


def _build_mechanics_system_prompt() -> str:
    return (
        "You are an actuarial assistant helping to understand insurance products "
        "from their filings (forms, actuarial memos, SOV, rate grids, riders).\n\n"
        "From the provided text, extract a small set of PRODUCT MECHANICS that "
        "describe how the product works. Mechanics should cover:\n"
        "- inputs (issue age, risk class, face amount, account value inputs, etc.)\n"
        "- charges (cost of insurance, loads, policy fees, rider charges, surrender charges)\n"
        "- benefits (death benefits, cash values, riders, guarantees)\n"
        "- structures (level term periods, maturity, bands, account structures)\n"
        "- constraints (eligibility rules, limits, conditions)\n"
        "- features (conversion, riders, no-lapse guarantees, loans, etc.)\n\n"
        "Return a JSON array of mechanics. Each mechanic MUST be a single object "
        "with this shape (no extra commentary):\n"
        "[\n"
        "  {\n"
        "    \"id\": string,                  // stable id like 'p12trf_issue_age' or 'promiseul_account_value'\n"
        "    \"product_code\": string,        // e.g. 'P12TRF', 'PROMISE-UL'\n"
        "    \"name\": string,                // human label, e.g. 'Issue Age', 'Account Value'\n"
        "    \"type\": string,                // 'input' | 'charge' | 'benefit' | 'structure' | 'feature' | 'state' | 'constraint'\n"
        "    \"description\": string,         // natural-language summary of the mechanic\n"
        "    \"filing_sources\": [            // where this mechanic came from in filings\n"
        "      {\n"
        "        \"id\": string,              // internal id, e.g. 'promiseul_memo_account_value'\n"
        "        \"document_hint\": string,   // filename or label\n"
        "        \"page\": string | null,     // page or section\n"
        "        \"snippet\": string | null,  // short text from the filing\n"
        "        \"confidence\": number       // 0.0–1.0 confidence\n"
        "      }\n"
        "    ],\n"
        "    \"upstream_ids\": string[],      // ids of mechanics this depends on (best-effort)\n"
        "    \"downstream_ids\": string[],    // ids of mechanics that depend on this (best-effort)\n"
        "    \"confidence\": number,          // 0.0–1.0 confidence in this mechanic\n"
        "    \"source\": \"ai_extracted\",   // for v0.1, always 'ai_extracted'\n"
        "    \"status\": \"candidate\"       // for v0.1, always 'candidate'\n"
        "  }\n"
        "]\n\n"
        "Focus on a small, high-value set of mechanics that would help an actuary "
        "understand the product's behaviour, rather than enumerating every detail."
    )


def extract_mechanics_from_text(
    *,
    product_code: str,
    text: str,
    model: Optional[str] = None,
) -> List[ProductMechanic]:
    """Use OpenAI to extract ProductMechanic candidates from raw filing text.

    Returns a list of ProductMechanic instances. Failures raise RuntimeError
    so that callers can surface a clear error to reviewers.
    """

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")

    client = OpenAI(api_key=api_key)
    model = model or os.getenv("MECHANICS_EXTRACT_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini"))

    code_norm = (product_code or "").strip().upper()
    if not code_norm:
        raise ValueError("product_code is required")

    system_prompt = _build_mechanics_system_prompt()

    user_content = (
        f"Target product_code: {code_norm}\n\n"
        "Extract a concise set of ProductMechanic objects for this product.\n\n"
        "=== FILING TEXT START ===\n"
        f"{text[:50000]}\n"
        "=== FILING TEXT END ===\n"
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
    )

    raw = resp.choices[0].message.content or ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM response was not valid JSON: {exc}\nRaw: {raw}") from exc

    if not isinstance(data, list):
        raise RuntimeError(f"Expected a JSON array of mechanics, got: {type(data)}")

    mechanics: List[ProductMechanic] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        fs_list: List[FilingSource] = []
        for fs in item.get("filing_sources", []) or []:
            if not isinstance(fs, dict):
                continue
            try:
                fs_list.append(
                    FilingSource(
                        id=str(fs.get("id")),
                        document_hint=str(fs.get("document_hint")),
                        page=fs.get("page"),
                        snippet=fs.get("snippet"),
                        confidence=float(fs.get("confidence", 0.8)),
                    )
                )
            except Exception:
                continue

        try:
            mech = ProductMechanic(
                id=str(item.get("id")),
                product_code=code_norm,
                name=str(item.get("name")),
                type=str(item.get("type")),
                description=str(item.get("description")),
                filing_sources=fs_list,
                dsl_refs=[],
                expected=None,
                upstream_ids=[str(x) for x in (item.get("upstream_ids") or [])],
                downstream_ids=[str(x) for x in (item.get("downstream_ids") or [])],
                confidence=float(item.get("confidence", 0.8)),
                source="ai_extracted",
                status="candidate",
            )
        except Exception:
            continue

        mechanics.append(mech)

    return mechanics
