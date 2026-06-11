from __future__ import annotations

"""High-level helpers to derive AssumptionSets from MinIO-backed filings.

This module is intentionally product-agnostic:

- It discovers filing documents for a given product_code (and optional
  filing_id) under the docs/ prefix in MinIO.
- It extracts text from a small set of representative documents.
- It calls the existing LLM-based extraction helper to propose an
  AssumptionSet.
- It upserts that AssumptionSet into the MinIO-backed registry so runtime
  projection code can pick it up without further code changes.

The goal is that adding a new product is a data/filing operation plus an
assumption-extraction run, not a Python code change.
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from actuarypoc.config.assumptions import AssumptionSet, upsert_assumption_set
from actuarypoc.extract.assumptions_extractor import (
    assumption_set_to_json,
    extract_assumption_set_from_text,
    read_document_text,
)
from actuarypoc.storage.minio_client import get_bucket_name, get_minio_client


def discover_docs_for_product(
    *, product_code: str, filing_id: Optional[str] = None, max_docs: int = 8
) -> List[str]:
    """Return a list of MinIO object keys under docs/ for this product.

    This is intentionally heuristic:

    - We scan the docs/ prefix for objects whose path contains the
      product_code string (case-insensitive).
    - When filing_id is provided, we prefer objects whose path also
      contains that filing id.

    The returned list is limited to max_docs entries to keep extraction
    prompts manageable.
    """

    client = get_minio_client()
    bucket = get_bucket_name()

    code_norm = (product_code or "").strip().lower()
    filing_norm = (filing_id or "").strip().lower() or None

    candidates: List[str] = []
    for obj in client.list_objects(bucket, prefix="docs/", recursive=True):
        name = obj.object_name
        low = name.lower()
        if code_norm and code_norm not in low:
            continue
        if filing_norm and filing_norm not in low:
            continue
        candidates.append(name)

    # If filing_id-based filter yields nothing, fall back to all product docs.
    if not candidates and filing_norm is not None:
        for obj in client.list_objects(bucket, prefix="docs/", recursive=True):
            name = obj.object_name
            low = name.lower()
            if code_norm and code_norm not in low:
                continue
            candidates.append(name)

    # Basic prioritisation: prefer actuarial memos / SOV / spec pages.
    priority = [
        "actuarial memo",
        "actuarial_memo",
        "actuarial",
        "sov",
        "spec",
        "promise ul",
        "statement of variability",
    ]

    def _score(name: str) -> int:
        low = name.lower()
        score = 0
        for i, token in enumerate(priority):
            if token in low:
                score += 10 - i
        return score

    candidates.sort(key=_score, reverse=True)
    return candidates[:max_docs]


def _download_minio_object(bucket: str, object_name: str, dest_dir: Path) -> Path:
    client = get_minio_client()
    response = client.get_object(bucket, object_name)
    try:
        suffix = Path(object_name).suffix or ""
        dest = dest_dir / (Path(object_name).name or "doc" + suffix)
        with dest.open("wb") as f:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                f.write(chunk)
        return dest
    finally:
        try:
            response.close()
            response.release_conn()
        except Exception:
            pass


def load_filing_text_from_minio(
    *, product_code: str, filing_id: Optional[str] = None, max_chars: int = 50000
) -> str:
    """Load and concatenate filing text for a product from MinIO.

    This uses discover_docs_for_product to find a handful of relevant
    documents, downloads them to a temporary directory, and extracts text
    via read_document_text. The combined text is truncated to max_chars to
    keep prompts bounded.
    """

    bucket = get_bucket_name()
    docs = discover_docs_for_product(product_code=product_code, filing_id=filing_id)
    if not docs:
        raise RuntimeError(f"No filing documents found in MinIO for product_code '{product_code}'.")

    chunks: List[str] = []
    with tempfile.TemporaryDirectory(prefix="assumptions_filing_") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        for name in docs:
            try:
                local_path = _download_minio_object(bucket, name, tmpdir)
                text = read_document_text(str(local_path))
                label = f"[DOCUMENT: {name}]\n"
                chunks.append(label + text.strip() + "\n\n")
            except Exception:
                # Best-effort: skip unreadable documents.
                continue

    combined = "\n".join(chunks).strip()
    if len(combined) > max_chars:
        combined = combined[:max_chars]
    return combined


def generate_assumption_set_for_product(
    *,
    product_code: str,
    filing_id: Optional[str] = None,
    set_id: Optional[str] = None,
    description_hint: Optional[str] = None,
    model: Optional[str] = None,
    auto_upsert: bool = True,
) -> AssumptionSet:
    """Derive a draft AssumptionSet for a product from its filings.

    This helper:

    - loads filing text from MinIO for the given product_code/filing_id,
    - calls the OpenAI-backed extraction helper to construct an AssumptionSet,
    - optionally upserts it into the MinIO-backed registry.

    The returned AssumptionSet is a draft: status/is_current can be
    promoted later via the existing approval workflow.
    """

    code_norm = (product_code or "").strip().upper()
    if not code_norm:
        raise ValueError("product_code is required")

    text = load_filing_text_from_minio(product_code=code_norm, filing_id=filing_id)

    # Stable-ish default id if caller does not provide one.
    if not set_id:
        base = code_norm.replace(" ", "-").lower()
        set_id = f"{base}-v1"

    asn = extract_assumption_set_from_text(
        product_code=code_norm,
        text=text,
        set_id=set_id,
        description_hint=description_hint,
        model=model,
    )

    if auto_upsert:
        asn = upsert_assumption_set(asn)

    return asn


def main(argv: Optional[List[str]] = None) -> int:
    """Simple CLI entrypoint for local/testing use.

    Example:

        python -m actuarypoc.extract.assumptions_for_product \
            --product-code "ICC18 P18PRUL" \
            --filing-id "PALD-131619832"
    """

    import argparse

    parser = argparse.ArgumentParser(description="Extract AssumptionSet from MinIO-backed filings.")
    parser.add_argument("--product-code", required=True, help="Product code to extract assumptions for.")
    parser.add_argument("--filing-id", required=False, help="Optional filing id to narrow docs.")
    parser.add_argument("--set-id", required=False, help="Explicit assumption set id to use.")
    parser.add_argument("--model", required=False, help="Override OpenAI model id.")
    parser.add_argument(
        "--no-upsert",
        dest="auto_upsert",
        action="store_false",
        help="Do not write the resulting AssumptionSet to MinIO; just print JSON.",
    )

    args = parser.parse_args(argv)

    asn = generate_assumption_set_for_product(
        product_code=args.product_code,
        filing_id=args.filing_id,
        set_id=args.set_id,
        model=args.model,
        auto_upsert=args.auto_upsert,
    )

    print(assumption_set_to_json(asn))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI glue
    raise SystemExit(main())
