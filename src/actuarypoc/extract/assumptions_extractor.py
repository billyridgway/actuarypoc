from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from openai import OpenAI

from actuarypoc.config.assumptions import AssumptionSet


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "config" / "assumption_schema.json"


def _client_timeout() -> float:
    """Per-call client timeout (seconds); see mechanics_extractor."""

    try:
        return float(os.getenv("ACTUARYPOC_EXTRACT_TIMEOUT_S", "180"))
    except ValueError:
        return 180.0


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
        "  \"description\": string,         // human summary of this set\n"
        "  \"dsl_file\": string,           // DSL file name, e.g. 'whole_life.yaml'\n"
        "  \"actuarial_prefix\": string|null, // MinIO prefix for actuarial tables\n"
        "  \"status\": string,             // 'draft' | 'approved' | 'deprecated' (usually 'draft')\n"
        "  \"is_current\": boolean,        // typically false for new sets\n"
        "  \"created_at\": string|null,    // leave null; system will fill\n"
        "  \"created_by\": string|null,    // leave null or 'llm-extractor'\n"
        "  \"approved_at\": string|null,    // null for drafts\n"
        "  \"approved_by\": string|null    // null for drafts\n"
        "}\n\n"
        "If something is not present in the filing, choose a sensible draft "
        "placeholder and mention the uncertainty in the description."
    )


def _assumption_set_single_call(
    *,
    product_code: str,
    text: str,
    set_id: str,
    description_hint: str | None = None,
    model: str | None = None,
    feedback: str | None = None,
    previous: Dict[str, Any] | None = None,
) -> AssumptionSet:
    """One model call over one text block (a slice dispatch unit).

    Prompt/parse behaviour is identical to the historical single-call
    extractor; it is shared by every dispatch path.
    """

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")

    client = OpenAI(api_key=api_key, timeout=_client_timeout())
    model = model or os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini")

    user_lines = [
        f"Target product_code: {product_code}",
        f"Desired assumption set id: {set_id}",
    ]
    if description_hint:
        user_lines.append(f"Description hint: {description_hint}")
    if previous is not None or feedback:
        user_lines.append("")
        user_lines.append("Previous AssumptionSet draft (may be incorrect):")
        try:
            user_lines.append(json.dumps(previous or {}, indent=2, sort_keys=True))
        except Exception:
            user_lines.append(str(previous))
        user_lines.append("")
        user_lines.append("Reviewer feedback:")
        user_lines.append(feedback or "(none provided)")
    user_lines.append("\n=== FILING TEXT START ===\n")
    user_lines.append(text.strip())
    user_lines.append("\n=== FILING TEXT END ===\n")

    messages = [
        {"role": "system", "content": _build_system_prompt()},
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
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM response was not valid JSON: {exc}\nRaw: {raw}") from exc

    # Ensure mandatory fields line up with our target product/id.
    data.setdefault("product_code", product_code)
    data.setdefault("id", set_id)

    return AssumptionSet.from_dict(data)


def extract_assumption_set_from_text(
    *,
    product_code: str,
    text: str,
    set_id: str,
    description_hint: str | None = None,
    model: str | None = None,
    feedback: str | None = None,
    previous: Dict[str, Any] | None = None,
) -> AssumptionSet:
    """Extract a single AssumptionSet from raw filing text.

    The text is sliced into bounded windows, extraction is dispatched
    per window, and the per-window sets are merged (see
    ``docs/slice-extraction-plan.md``) — the whole text is covered
    instead of only its head. Reviewer-feedback calls keep the
    historical single-call behaviour (feedback is about one draft).
    When every dispatch unit fails, the first failure is raised.
    """

    if feedback is not None or previous is not None:
        return _assumption_set_single_call(
            product_code=product_code,
            text=text,
            set_id=set_id,
            description_hint=description_hint,
            model=model,
            feedback=feedback,
            previous=previous,
        )

    from actuarypoc.extract.document_map import build_document_map
    from actuarypoc.extract.slice_extraction import (
        extract_assumption_set_from_slices,
    )

    doc_map = build_document_map(
        doc_id="text",
        document_hint="provided text",
        pages=[text or ""],
        paged=False,
    )
    result = extract_assumption_set_from_slices(
        product_code=product_code,
        set_id=set_id,
        slices=doc_map.slices,
        description_hint=description_hint,
        model=model,
    )
    if result["assumption_set"] is None:
        if result["failed_units"]:
            raise RuntimeError(result["failed_units"][0]["error"])
        raise RuntimeError("Assumption extraction produced no result (empty text?)")
    return result["assumption_set"]


def _build_metadata_system_prompt() -> str:
    """System prompt for extracting basic product metadata from filings.

    The model must return a single JSON object with a fixed set of fields
    so that the UI can pre-fill Product Review metadata without any
    product-specific branches in Python.
    """

    return (
        "You are an actuarial assistant helping configure a life insurance "
        "illustration engine. From product filings and actuarial memos, "
        "you extract a single structured JSON object describing the "
        "carrier and product metadata.\n\n"
        "The JSON you return MUST be a single object with this shape (no "
        "extra commentary):\n"
        "{\n"
        "  \"carrier_name\": string | null,\n"
        "  \"product_name\": string | null,\n"
        "  \"product_code\": string | null,\n"
        "  \"product_type\": string | null,   // e.g. 'Term Life', 'Universal Life'\n"
        "  \"primary_filing_id\": string | null  // SERFF/filing id when present\n"
        "}\n\n"
        "If the filing does not clearly specify a field, return null for "
        "that field instead of guessing. Use the text and document names "
        "to recover realistic values when possible."
    )


_METADATA_FIELDS = (
    "carrier_name",
    "product_name",
    "product_code",
    "product_type",
    "primary_filing_id",
)


def _extract_metadata_single_call(
    *, text: str, model: str | None = None, feedback: str | None = None, previous: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """One model call over one text block (a slice dispatch unit).

    Prompt/parse behaviour matches the historical metadata extractor.
    """

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")

    client = OpenAI(api_key=api_key, timeout=_client_timeout())
    model = model or os.getenv("METADATA_EXTRACT_MODEL", os.getenv("ASSUMPTION_EXTRACT_MODEL", "gpt-4o-mini"))

    user_parts = []
    if previous is not None or feedback:
        user_parts.append("Previous metadata draft (may be incorrect):")
        if previous is not None:
            try:
                user_parts.append(json.dumps(previous, indent=2, sort_keys=True))
            except Exception:
                user_parts.append(str(previous))
        user_parts.append("")
        user_parts.append("Reviewer feedback:")
        user_parts.append(feedback or "(none provided)")
        user_parts.append("")
        user_parts.append("Please correct or refine the metadata accordingly based on this feedback.")
        user_parts.append("")
        user_parts.append("=== FILING TEXT START ===")
        user_parts.append(text)
        user_parts.append("=== FILING TEXT END ===")
        user_content = "\n".join(user_parts)
    else:
        user_content = text

    messages = [
        {"role": "system", "content": _build_metadata_system_prompt()},
        {"role": "user", "content": user_content},
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.1,
    )

    raw = resp.choices[0].message.content or ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM response was not valid JSON: {exc}\nRaw: {raw}") from exc

    # Normalise shape: ensure all expected keys are present.
    meta: Dict[str, Any] = {}
    for field_name in _METADATA_FIELDS:
        meta[field_name] = data.get(field_name) if isinstance(data, dict) else None

    return meta


def extract_product_metadata_from_text(
    *, text: str, model: str | None = None, feedback: str | None = None, previous: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """Extract basic product metadata from filing text.

    Returns a plain dict with keys: carrier_name, product_name,
    product_code, product_type, primary_filing_id.

    The text is sliced into bounded windows and extraction is dispatched
    per window and merged field-wise (first non-null value wins), so
    metadata stated late in a long filing is found — the historical
    ``text[:50000]`` truncation is gone. Reviewer-feedback calls keep
    the historical single-call behaviour.
    """

    if feedback is not None or previous is not None:
        return _extract_metadata_single_call(
            text=text, model=model, feedback=feedback, previous=previous
        )

    from actuarypoc.extract.document_map import build_document_map
    from actuarypoc.extract.slice_extraction import (
        extract_product_metadata_from_slices,
    )

    doc_map = build_document_map(
        doc_id="text",
        document_hint="provided text",
        pages=[text or ""],
        paged=False,
    )
    if not doc_map.slices:
        return {field_name: None for field_name in _METADATA_FIELDS}
    result = extract_product_metadata_from_slices(slices=doc_map.slices, model=model)
    if result["failed_units"] and not result["succeeded_units"]:
        raise RuntimeError(result["failed_units"][0]["error"])
    return result["metadata"]


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
