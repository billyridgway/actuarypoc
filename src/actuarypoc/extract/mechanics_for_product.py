from __future__ import annotations

"""High-level helpers to derive ProductMechanics from MinIO-backed filings.

This mirrors the pattern used by assumptions_for_product but targets
ProductMechanic extraction and a MinIO-backed registry under
``mechanics/{product_code}/...``.
"""

from typing import Any, Dict, List, Optional

from pathlib import Path

from actuarypoc.extract.assumptions_for_product import (
    discover_docs_for_product,
    _download_minio_object,  # type: ignore[attr-defined]
)
from actuarypoc.extract.assumptions_extractor import read_document_text
from actuarypoc.domain.product_mechanics import ProductMechanic, save_mechanics_to_minio
from actuarypoc.extract.mechanics_extractor import extract_mechanics_from_text
from actuarypoc.storage.minio_client import get_bucket_name


def load_filing_text_for_mechanics(
    *, product_code: str, filing_id: Optional[str] = None, max_chars: int = 50000
) -> str:
    """Load and concatenate filing text for mechanics extraction.

    This reuses the same discovery + PDF/text extraction path as the
    assumptions extractor but is tuned for mechanics extraction. The
    combined text is truncated to max_chars.
    """

    bucket = get_bucket_name()
    docs = discover_docs_for_product(product_code=product_code, filing_id=filing_id)
    if not docs:
        raise RuntimeError(f"No filing documents found in MinIO for product_code '{product_code}'.")

    from tempfile import TemporaryDirectory

    chunks: List[str] = []
    with TemporaryDirectory(prefix="mechanics_filing_") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        for name in docs:
            try:
                local_path = _download_minio_object(bucket, name, tmpdir)  # type: ignore[misc]
                text = read_document_text(str(local_path))
                label = f"[DOCUMENT: {name}]\n"
                chunks.append(label + text.strip() + "\n\n")
            except Exception:
                continue

    combined = "\n".join(chunks).strip()
    if len(combined) > max_chars:
        combined = combined[:max_chars]
    return combined


def generate_mechanics_for_product(
    *,
    product_code: str,
    filing_id: Optional[str] = None,
    model: Optional[str] = None,
    auto_persist_candidates: bool = True,
) -> List[ProductMechanic]:
    """Derive a draft mechanics set for a product from its filings.

    This helper:

    - discovers relevant filing documents in MinIO,
    - extracts text,
    - calls the LLM-backed extractor to propose ProductMechanic entries,
    - optionally persists them as a candidate set under
      ``mechanics/{product_code}/candidates/latest.json``.

    Returned mechanics are in "candidate" status and should be reviewed
    by an actuary before being promoted to an approved mechanics
    registry for the product.
    """

    code_norm = (product_code or "").strip().upper()
    if not code_norm:
        raise ValueError("product_code is required")

    text = load_filing_text_for_mechanics(product_code=code_norm, filing_id=filing_id)
    mechanics = extract_mechanics_from_text(product_code=code_norm, text=text, model=model)

    if auto_persist_candidates:
        save_mechanics_to_minio(code_norm, mechanics, kind="candidates")

    return mechanics
