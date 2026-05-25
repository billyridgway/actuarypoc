from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from actuarypoc.connectors.base import CSVConnector, Record
from actuarypoc.storage.minio_client import ensure_bucket, get_bucket_name, get_minio_client


def _serialize(records: Iterable[Record]) -> bytes:
    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "records": list(records),
    }
    return json.dumps(payload, indent=2).encode("utf-8")


def ingest_csv(path: str, *, object_name: str | None = None) -> str:
    connector = CSVConnector(path)
    records = list(connector.fetch())

    client = get_minio_client()
    ensure_bucket(client)
    bucket = get_bucket_name()

    object_name = object_name or f"ingest/{Path(path).stem}-{int(datetime.utcnow().timestamp())}.json"
    payload = _serialize(records)

    client.put_object(
        bucket,
        object_name,
        data=io.BytesIO(payload),
        length=len(payload),
        content_type="application/json",
    )

    return object_name


if __name__ == "__main__":
    sample_path = Path(__file__).resolve().parents[1] / "sample_data" / "policies.csv"
    obj = ingest_csv(str(sample_path))
    print(f"Uploaded sample data to s3://{get_bucket_name()}/{obj}")
