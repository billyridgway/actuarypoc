from __future__ import annotations

"""Helpers to extract text from P12TRF filing PDFs.

These functions are designed to run inside the Dagster pod in the k8s
cluster. They assume that the P12TRF filings (ZIPs or PDFs) are present in
(or mounted into) the container filesystem, typically via a git checkout
of this repo plus a sibling/overlay directory that holds the SERFF
packets.

For the POC we treat this as a simple, reproducible way to:
- read the key P12TRF filing PDFs
- extract their text content with PyPDF2
- push the extracted text into MinIO so downstream steps can consume it
  without re-parsing PDFs.
"""

import io
from pathlib import Path
from typing import Dict, List

from PyPDF2 import PdfReader

from actuarypoc.storage.minio_client import ensure_bucket, get_bucket_name, get_minio_client


# Default base directory for P12TRF filings. In the current dev setup this
# lives as a sibling of the actuarypoc repo:
#   /workspace/
#     actuarypoc/
#     actuarydocs/P12TRF/...
#
# In the k8s cluster this can be mounted or included in the image at the
# same relative path, or overridden via the P12TRF_FILINGS_ROOT env var.


def _get_filings_root() -> Path:
    import os

    env_root = os.getenv("P12TRF_FILINGS_ROOT")
    if env_root:
        return Path(env_root)

    # Fallback: sibling actuarydocs/P12TRF next to the repo root.
    return Path(__file__).resolve().parents[2] / "actuarydocs" / "P12TRF"


def _candidate_pdfs(root: Path) -> Dict[str, Path]:
    """Return the key P12TRF-related PDFs we know how to parse.

    Keys are short identifiers; values are absolute paths.
    """

    unzipped = root / "unzipped"
    return {
        "p12trf_act_memo": unzipped
        / "PALD-132202799"
        / "StateRequiredSupportingDocuments"
        / "ICC12 P12TRF - Act Memo.pdf",
        "p12trf_spec_sov": unzipped
        / "PALD-132202799"
        / "StateRequiredSupportingDocuments"
        / "Statement of Variability - Specification Pages.pdf",
        "p12trf_sov_iiprc": unzipped
        / "PALD-132386861"
        / "StateRequiredSupportingDocuments"
        / "ICC12 P12TRF SOV - IIPRC.pdf",
        "p12trf_sov_redline": unzipped
        / "PALD-132386861"
        / "AdditionalSupportingDocuments"
        / "ICC12 P12TRF SOV - IIPRC Redline.pdf",
        "pet_risk_class_mapping": unzipped
        / "PALD-133240079"
        / "AdditionalSupportingDocuments"
        / "Risk Class Mapping - Term - PET.pdf",
    }


def extract_p12trf_filings_to_minio(prefix: str = "filings/p12trf/") -> List[str]:
    """Extract text from key P12TRF filing PDFs and store in MinIO.

    Returns a list of object names written to MinIO. Files that are missing
    or fail extraction are skipped but logged via the returned mapping.
    """

    root = _get_filings_root()
    pdfs = _candidate_pdfs(root)

    client = get_minio_client()
    ensure_bucket(client)
    bucket = get_bucket_name()

    written: List[str] = []

    for key, path in pdfs.items():
        if not path.exists():
            # In cluster, this likely means the filings directory has not
            # been mounted or the expected structure differs.
            continue

        try:
            reader = PdfReader(str(path))
            text_parts: List[str] = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
            text = "\n".join(text_parts)
        except Exception:
            # Skip problematic PDFs; the POC can still run on the others.
            continue

        object_name = f"{prefix}{key}.txt"
        payload = text.encode("utf-8")
        client.put_object(
            bucket,
            object_name,
            data=io.BytesIO(payload),
            length=len(payload),
            content_type="text/plain; charset=utf-8",
        )
        written.append(object_name)

    return written
