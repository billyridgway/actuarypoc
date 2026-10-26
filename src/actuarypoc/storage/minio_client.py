from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from minio import Minio


def _get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_minio_client() -> Minio:
    endpoint = _get_env("MINIO_ENDPOINT")
    access_key = _get_env("MINIO_ACCESS_KEY")
    secret_key = _get_env("MINIO_SECRET_KEY")
    secure = os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes"}

    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)


@lru_cache(maxsize=1)
def get_bucket_name() -> str:
    return _get_env("MINIO_BUCKET")


def ensure_bucket(minio_client: Minio) -> None:
    bucket = get_bucket_name()
    if not minio_client.bucket_exists(bucket):
        minio_client.make_bucket(bucket)


def document_object_location(document: dict, default_bucket: str) -> tuple[str, str]:
    """Where a workspace document's bytes live.

    Source-referenced documents (docs/workspace-sources.md) read from
    their recorded ``source`` bucket/key; uploaded documents read from
    the app bucket at their ``object_path``. The bytes themselves are
    never copied into the workspace for a source document.
    """

    source = document.get("source") if isinstance(document, dict) else None
    if isinstance(source, dict) and source.get("bucket") and source.get("key"):
        return str(source["bucket"]), str(source["key"])
    return default_bucket, str((document or {}).get("object_path") or "")


def fetch_document_bytes(client: Minio, document: dict, default_bucket: str) -> bytes:
    """Fetch a document's bytes from its resolved location."""

    bucket, key = document_object_location(document, default_bucket)
    response = client.get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
