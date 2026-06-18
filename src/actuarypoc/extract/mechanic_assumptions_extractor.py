from __future__ import annotations

"""LLM-backed extraction of concrete assumptions per Product Mechanic.

This module takes approved Product Mechanics (including filing evidence)
for a product and asks the LLM to extract concrete assumptions for each
mechanic: rates, tables, schedules, limits, formulas, constraints,
eligibility rules, and timing/order-of-operations details.

The goal is Product Assumption Discovery, *not* executable DSL or a
projection model. The output is designed for review in the AI Review
Agent Stage 3.
"""

from typing import Any, Dict, List, Optional

import json
import os

from openai import OpenAI

from actuarypoc.storage.minio_client import get_minio_client, get_bucket_name
from actuarypoc.extract.assumptions_for_product import (
    _download_minio_object,  # type: ignore[attr-defined]
    discover_docs_for_product,
)
from actuarypoc.extract.assumptions_extractor import read_document_text
from tempfile import TemporaryDirectory


def _strip_code_fence(raw: str) -> str:
    """Best-effort removal of markdown code fences around JSON.

    Some models occasionally wrap JSON payloads in ```json ... ``` even
    when asked not to. This helper strips a single top-level fenced
    block so that json.loads can succeed.
    """

    s = (raw or "").strip()
    if not s.startswith("```"):
        return s

    first_nl = s.find("\n")
    if first_nl == -1:
        return s
    s = s[first_nl + 1 :]

    end = s.rfind("```")
    if end != -1:
        s = s[:end]

    return s.strip()


def _build_system_prompt() -> str:
    return (
        "You are an actuarial assistant extracting concrete PRODUCT ASSUMPTIONS "
        "from life/UL product filings. You are given a set of PRODUCT MECHANICS, "
        "each with a name, type, description, and filing evidence (document, "
        "page, snippet). For each mechanic, extract the *assumptions* implied "
        "by the filing evidence.\n\n"
        "Focus on: rates, mortality bases, tables, schedules, limits, formulas, "
        "constraints, eligibility rules, timing, and order-of-operations. "
        "Avoid generic guidance like 'specify X'; instead, state what the filing "
        "actually says or strongly implies.\n\n"
        "Return a JSON array. Each entry MUST have this shape (no extra keys):\n"
        "[\n"
        "  {\n"
        "    \"mechanicId\": string,          // id of the mechanic this applies to\n"
        "    \"assumptions\": [ string, ... ] // concise bullet-style assumptions\n"
        "  }\n"
        "]\n\n"
        "If the filing evidence does not provide any concrete assumption for a "
        "mechanic, return an empty assumptions array for that mechanic. Do not "
        "invent values that are not supported by the text."
    )


def extract_mechanic_assumptions(
    *, product_code: str, mechanics: List[Dict[str, Any]], model: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Extract concrete assumptions per mechanic using filing evidence.

    ``mechanics`` should be a JSON-serialisable list, typically obtained
    via ``mechanics_to_json(load_mechanics_for_product(product_code))``.

    Returns a list of dicts with keys ``mechanicId`` and ``assumptions``.
    Failures raise RuntimeError so the caller can surface a clear error
    or fall back gracefully.
    """

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")

    code_norm = (product_code or "").strip().upper()
    if not code_norm:
        raise ValueError("product_code is required")

    # Load full-text filings up front so we can expand short snippets
    # into richer per-mechanic evidence instead of relying solely on
    # the tiny ``filing_sources.snippet``.
    doc_texts: Dict[str, str] = {}
    try:
        client_m = get_minio_client()
        bucket = get_bucket_name()
        doc_keys = discover_docs_for_product(product_code=code_norm)
        if doc_keys:
            with TemporaryDirectory(prefix="mech_docs_") as tmpdir_str:
                from pathlib import Path as _Path

                tmpdir = _Path(tmpdir_str)
                for key in doc_keys:
                    try:
                        local = _download_minio_object(bucket, key, tmpdir)  # type: ignore[misc]
                        text = read_document_text(str(local))
                        doc_texts[key] = text or ""
                    except Exception:
                        continue
    except Exception:
        doc_texts = {}

    # Build a compact mechanic context list for the LLM, including
    # expanded evidence per mechanic when possible.
    mechanic_contexts: List[Dict[str, Any]] = []
    for m in mechanics:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        name = m.get("name")
        if not mid or not name:
            continue
        ctx: Dict[str, Any] = {
            "mechanicId": mid,
            "name": name,
            "type": m.get("type"),
            "description": m.get("description"),
            "product_code": code_norm,
        }

        fs_list: List[Dict[str, Any]] = []
        expanded_chunks: List[str] = []
        for fs in m.get("filing_sources", []) or []:
            if not isinstance(fs, dict):
                continue
            snippet = fs.get("snippet") or ""
            page = fs.get("page") or ""
            hint = (fs.get("document_hint") or "").lower()
            fs_entry = {
                "id": fs.get("id"),
                "document_hint": fs.get("document_hint"),
                "page": page,
                "snippet": snippet,
            }
            fs_list.append(fs_entry)

            # Try to expand this snippet within the underlying filing
            # documents: prefer docs whose object path contains the
            # document_hint, then fall back to any doc that contains
            # the snippet text.
            snippet_key = (snippet or "").strip()
            if not snippet_key:
                continue

            best_match: Optional[str] = None
            for key, text in doc_texts.items():
                low_key = key.lower()
                if hint and hint not in low_key:
                    continue
                if snippet_key in text:
                    best_match = key
                    break
            if best_match is None:
                for key, text in doc_texts.items():
                    if snippet_key in text:
                        best_match = key
                        break

            if best_match is not None:
                text = doc_texts.get(best_match, "")
                idx = text.find(snippet_key)
                if idx != -1:
                    window = 1200
                    start = max(0, idx - window)
                    end = min(len(text), idx + len(snippet_key) + window)
                    expanded = text[start:end].strip()
                    if expanded:
                        label = f"[EVIDENCE: {best_match} p.{page or '?'}]\n"
                        expanded_chunks.append(label + expanded + "\n\n")

        if fs_list:
            ctx["filing_sources"] = fs_list

        if expanded_chunks:
            # Trim per-mechanic expanded evidence to keep prompts
            # bounded while still providing richer context than the raw
            # snippet alone.
            expanded_combined = "".join(expanded_chunks)
            max_chars = 4000
            ctx["expanded_evidence"] = expanded_combined[:max_chars]

        mechanic_contexts.append(ctx)

    if not mechanic_contexts:
        return []

    # Load additional assumption support documents from MinIO, when
    # present, and append their text as global context. We do not yet
    # map individual support files to specific mechanics; the LLM sees
    # them as shared context.
    support_text_chunks: List[str] = []
    try:
        client_m = get_minio_client()
        bucket = get_bucket_name()
        prefix = f"assumption-support/{code_norm}/"
        objects = list(client_m.list_objects(bucket, prefix=prefix, recursive=True))[:5]
        if objects:
            with TemporaryDirectory(prefix="mech_support_") as tmpdir_str:
                from pathlib import Path as _Path

                tmpdir = _Path(tmpdir_str)
                for obj in objects:
                    name = obj.object_name
                    try:
                        local = _download_minio_object(bucket, name, tmpdir)  # type: ignore[misc]
                        text = read_document_text(str(local))
                        label = f"[SUPPORT: {name}]\n"
                        support_text_chunks.append(label + text.strip() + "\n\n")
                    except Exception:
                        continue
    except Exception:
        support_text_chunks = []

    support_text = "".join(support_text_chunks).strip()

    client = OpenAI(api_key=api_key)
    model = model or os.getenv("MECHANIC_ASSUMPTION_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini"))

    system_prompt = _build_system_prompt()

    user_content_lines = [
        f"Target product_code: {code_norm}",
        "", 
        "Mechanics with filing evidence:",
        json.dumps(mechanic_contexts, indent=2, ensure_ascii=False),
    ]
    if support_text:
        user_content_lines.append("")
        user_content_lines.append("Additional assumption support documents (may contain COI tables, surrender schedules, interest crediting details, etc.):")
        # Truncate to keep prompts bounded.
        max_chars = 40000
        user_content_lines.append(support_text[:max_chars])

    user_content = "\n".join(user_content_lines)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
    )

    raw = resp.choices[0].message.content or ""
    cleaned = _strip_code_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM response was not valid JSON: {exc}\nRaw: {raw}") from exc

    if not isinstance(data, list):
        raise RuntimeError(f"Expected a JSON array of mechanic assumptions, got: {type(data)}")

    results: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        mid = item.get("mechanicId")
        if not mid:
            continue
        assumptions = item.get("assumptions") or []
        if not isinstance(assumptions, list):
            assumptions = []
        assumptions_str = [str(a).strip() for a in assumptions if str(a).strip()]
        results.append({"mechanicId": str(mid), "assumptions": assumptions_str})

    return results
