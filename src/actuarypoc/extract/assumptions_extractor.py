from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from openai import OpenAI

from actuarypoc.config.assumptions import AssumptionSet


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "config" / "assumption_schema.json"


def _load_schema() -> Dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _build_system_prompt() -> str:
    """Return a concise system prompt for extracting an AssumptionSet.

    We don't embed the full JSON Schema to keep prompts small; instead we
    describe the key fields and rely on validation via AssumptionSet.
    """

    return (
        "You are an actuarial assistant helping configure a life insurance "
        "illustration engine. From product filings and actuarial memos, "
        "you extract a single structured AssumptionSet in JSON."
        "\n\n"
        "The JSON you return MUST be a single object with this shape (no "
        "extra commentary):\n"
        "{\n"
        "  \"id\": string,                  // stable id like 'wl-elite-v1'\n"
        "  \"product_code\": string,        // PAS product code, e.g. 'WL-ELITE'\n"
        "  \"description\": string,        // human summary of this set\n"
        "  \"dsl_file\": string,           // DSL file name, e.g. 'whole_life.yaml'\n"
        "  \"actuarial_prefix\": string|null, // MinIO prefix for actuarial tables\n"
        "  \"status\": string,             // 'draft' | 'approved' | 'deprecated' (usually 'draft')\n"
        "  \"is_current\": boolean,        // typically false for new sets\n"
        "  \"created_at\": string|null,    // leave null; system will fill\n"
        "  \"created_by\": string|null,    // leave null or 'llm-extractor'\n"
        "  \"approved_at\": string|null,   // null for drafts\n"
        "  \"approved_by\": string|null    // null for drafts\n"
        "}\n\n"
        "If something is not present in the filing, choose a sensible draft "
        "placeholder and mention the uncertainty in the description."
    )


def extract_assumption_set_from_text(
    *,
    product_code: str,
    text: str,
    set_id: str,
    description_hint: str | None = None,
    model: str | None = None,
) -> AssumptionSet:
    """Use OpenAI to extract a single AssumptionSet from raw filing text.

    This is intentionally simple: it prompts for one JSON object and then
    validates it against the AssumptionSet dataclass. Any validation errors
    are raised to the caller.
    """

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")

    client = OpenAI(api_key=api_key)
    model = model or os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini")

    user_prompt = [
        f"Target product_code: {product_code}",
        f"Desired assumption set id: {set_id}",
    ]
    if description_hint:
        user_prompt.append(f"Description hint: {description_hint}")
    user_prompt.append("\n=== FILING TEXT START ===\n")
    user_prompt.append(text.strip())
    user_prompt.append("\n=== FILING TEXT END ===\n")

    messages = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user", "content": "\n".join(user_prompt)},
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
    )

    raw = resp.choices[0].message.content or ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM response was not valid JSON: {exc}\nRaw: {raw}") from exc

    # Ensure mandatory fields line up with our target product/id.
    data.setdefault("product_code", product_code)
    data.setdefault("id", set_id)

    return AssumptionSet.from_dict(data)


def read_document_text(path: str) -> str:
    """Read a local document into plain text for extraction.

    Supports .txt/.md directly and .pdf via PyPDF2. Other types can be
    added later.
    """

    from PyPDF2 import PdfReader

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)

    suffix = p.suffix.lower()
    if suffix in {".txt", ".md"}:
        return p.read_text(encoding="utf-8")

    if suffix == ".pdf":
        reader = PdfReader(str(p))
        chunks: list[str] = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(chunks)

    raise ValueError(f"Unsupported document type for extraction: {suffix}")


def extract_assumption_set_from_doc(
    *,
    doc_path: str,
    product_code: str,
    set_id: str,
    description_hint: str | None = None,
    model: str | None = None,
) -> AssumptionSet:
    """High-level helper: doc file path → AssumptionSet instance."""

    text = read_document_text(doc_path)
    return extract_assumption_set_from_text(
        product_code=product_code,
        text=text,
        set_id=set_id,
        description_hint=description_hint,
        model=model,
    )


def assumption_set_to_json(asn: AssumptionSet) -> str:
    """Serialize an AssumptionSet as pretty JSON string."""

    return json.dumps(asn.to_dict(), indent=2, sort_keys=True)
