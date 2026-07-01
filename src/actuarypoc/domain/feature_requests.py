from __future__ import annotations

"""Feature request emission helpers.

This module converts capability assessment items into durable feature
request artefacts stored in object storage (MinIO).

These artefacts are intended for OpenClaw or other automation to scan
and translate into backlog items / engine work.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List

from actuarypoc.domain.capabilities import CapabilityAssessmentItem
from actuarypoc.domain.life_product_models import BaseLifeProductModel


@dataclass
class FeatureRequest:
    product_code: str
    product_type: str
    capability_id: str
    title: str
    description: str
    impact: str
    status: str = "proposed"  # proposed | approved | rejected | in_progress | complete | deferred
    source_requirement_ids: List[str] = field(default_factory=list)
    source_requirement_text: str | None = None
    source_document: str | None = None
    source_reference: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    )


def _object_key_for_feature_request(fr: FeatureRequest) -> str:
    """Return the MinIO object key for a feature request.

    Layout:
        feature-requests/{product_type}/{product_code}/{capability_id}.json
    """

    ptype = (fr.product_type or "unknown").lower()
    code = (fr.product_code or "UNKNOWN").upper()
    cid = (fr.capability_id or "UNKNOWN").upper()
    return f"feature-requests/{ptype}/{code}/{cid}.json"


def emit_feature_requests_to_minio(
    product: BaseLifeProductModel,
    assessments: List[CapabilityAssessmentItem],
) -> List[FeatureRequest]:
    """Persist feature requests derived from capability assessments.

    Only "partial" and "unsupported" items are emitted. Supported items
    do not result in feature requests.

    Returns the list of FeatureRequest objects written. Errors talking to
    MinIO are swallowed; callers should treat this as best-effort.
    """

    from actuarypoc.storage.minio_client import ensure_bucket, get_bucket_name, get_minio_client

    client = get_minio_client()
    bucket = get_bucket_name()
    ensure_bucket(client)

    out: List[FeatureRequest] = []

    for item in assessments:
        status = (item.status or "").lower()
        if status not in {"partial", "unsupported"}:
            continue

        fr = FeatureRequest(
            product_code=product.product_code,
            product_type=product.product_type,
            capability_id=item.capability_id,
            title=f"Engine support for {item.name}",
            description=item.reason,
            impact=item.impact,
            source_requirement_ids=list(item.source_requirement_ids or []),
            source_requirement_text=item.source_requirement_text,
            source_document=item.source_document,
            source_reference=item.source_reference,
        )

        key = _object_key_for_feature_request(fr)
        body = ("%s\n" % asdict(fr)).encode("utf-8")

        try:
            import io as _io

            client.put_object(
                bucket,
                key,
                _io.BytesIO(body),
                length=len(body),
                content_type="application/json",
            )
            out.append(fr)
        except Exception:
            # Best-effort only; log at INFO via calling code if needed.
            continue

    return out


__all__ = [
    "FeatureRequest",
    "emit_feature_requests_to_minio",
]
