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
