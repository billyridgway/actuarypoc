from __future__ import annotations

"""LLM-backed extraction of ProductMechanic candidates from filing text.

This is intentionally minimal and product-agnostic for v0.1. It mirrors the
pattern used by the assumptions extractor but targets ProductMechanic-shaped
JSON objects instead of AssumptionSets.

Since the slice-extraction upgrade (see ``docs/slice-extraction-plan.md``),
extraction is dispatched per document slice and merged; the single-call
core below is shared by both the slice dispatcher
(``actuarypoc.extract.slice_extraction``) and the ``from_text`` entry
point, which now slices its input instead of truncating it to 50,000
chars.
"""

from typing import Any, Dict, List, Optional

import json
import os

from openai import OpenAI

from actuarypoc.domain.product_mechanics import FilingSource, ProductMechanic


def _client_timeout() -> float:
    """Per-call client timeout (seconds).

    Extraction-length generations against a slow local model must fail
    fast and measurably instead of hanging until a proxy gives up
    (observed: ~378 s Cloudflare 524s through the public facade). The
    in-cluster route has no proxy ceiling, so this timeout is the bound.
    """

    try:
        return float(os.getenv("ACTUARYPOC_EXTRACT_TIMEOUT_S", "180"))
    except ValueError:
        return 180.0


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


def _strip_code_fence(raw: str) -> str:
    """Best-effort removal of markdown code fences around JSON.

    Some models occasionally wrap the JSON payload in ```json ... ``` even
    when asked not to. This helper strips a single top-level fenced block so
    that json.loads can succeed.
    """

    s = (raw or "").strip()
    if not s.startswith("```"):
        return s

    # Drop opening fence line (e.g. ``` or ```json)
    first_nl = s.find("\n")
    if first_nl == -1:
        return s
    s = s[first_nl + 1 :]

    # Trim trailing fence if present
    end = s.rfind("```")
    if end != -1:
        s = s[:end]

    return s.strip()


def _parse_mechanics_payload(data: Any, *, product_code: str) -> List[ProductMechanic]:
    """Build ProductMechanic objects from a decoded JSON payload."""

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
                product_code=product_code,
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


def _extract_mechanics_single_call(
    *,
    product_code: str,
    text: str,
    model: Optional[str] = None,
) -> List[ProductMechanic]:
    """One model call over one text block (a slice dispatch unit).

    This is the exact prompt/parse behaviour the pre-slice extractor had;
    it is shared by every dispatch path so output shape cannot drift.
    Failures raise RuntimeError.
    """

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")

    client = OpenAI(api_key=api_key, timeout=_client_timeout())
    model = model or os.getenv("MECHANICS_EXTRACT_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini"))

    code_norm = (product_code or "").strip().upper()
    if not code_norm:
        raise ValueError("product_code is required")

    system_prompt = _build_mechanics_system_prompt()

    user_content = (
        f"Target product_code: {code_norm}\n\n"
        "Extract a concise set of ProductMechanic objects for this product.\n\n"
        "=== FILING TEXT START ===\n"
        f"{text}\n"
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
    cleaned = _strip_code_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM response was not valid JSON: {exc}\nRaw: {raw}") from exc

    return _parse_mechanics_payload(data, product_code=code_norm)


def extract_mechanics_from_text(
    *,
    product_code: str,
    text: str,
    model: Optional[str] = None,
) -> List[ProductMechanic]:
    """Extract ProductMechanic candidates from raw filing text.

    The text is sliced into bounded, page-less windows and extraction is
    dispatched per window and merged (see
    ``docs/slice-extraction-plan.md``) — the whole text is covered; the
    historical ``text[:50000]`` truncation is gone.

    Returns a list of ProductMechanic instances. When every dispatch
    unit fails, the first failure is raised as RuntimeError so callers
    keep the historical fail-loud contract.
    """

    from actuarypoc.extract.document_map import build_document_map
    from actuarypoc.extract.slice_extraction import extract_mechanics_from_slices

    code_norm = (product_code or "").strip().upper()
    if not code_norm:
        raise ValueError("product_code is required")

    doc_map = build_document_map(
        doc_id="text",
        document_hint="provided text",
        pages=[text or ""],
        paged=False,
    )
    result = extract_mechanics_from_slices(
        product_code=code_norm, slices=doc_map.slices, model=model
    )
    if result["failed_units"] and not result["succeeded_units"]:
        raise RuntimeError(result["failed_units"][0]["error"])
    return result["mechanics"]
