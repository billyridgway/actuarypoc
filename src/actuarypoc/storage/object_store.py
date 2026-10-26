"""Object-store browsing + source resolution for workspace sources.

See ``docs/workspace-sources.md``. These helpers take an explicit MinIO
client so endpoints and tests share one implementation. They only ever
*read* the store: listing, stat-ing, and resolving a selection into the
concrete ``{bucket, key, etag, size, lastModified}`` references a
workspace records. Source bytes are never copied by this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

# One browsing page. Filings buckets can be large; the picker navigates
# by prefix instead of enumerating everything, and the flag says when a
# page was cut.
LIST_PAGE_CAP = 500

# A prefix selection resolves to its object list at creation time. This
# cap keeps a creation request from pinning an unbounded set; beyond it
# the caller must narrow the prefix.
MAX_PREFIX_OBJECTS = 1000


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _clean_etag(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value).strip().strip('"') or None


def list_store_buckets(client: Any) -> List[Dict[str, Any]]:
    """Buckets visible to the client's identity, name + creation date."""

    buckets: List[Dict[str, Any]] = []
    for bucket in client.list_buckets():
        buckets.append(
            {
                "name": bucket.name,
                "createdAt": _iso(getattr(bucket, "creation_date", None)),
            }
        )
    return sorted(buckets, key=lambda row: row["name"])


def list_store_objects(
    client: Any,
    bucket: str,
    prefix: str = "",
    *,
    recursive: bool = False,
    cap: int = LIST_PAGE_CAP,
) -> Dict[str, Any]:
    """One listing page: file entries + (non-recursive) sub-prefixes.

    Non-recursive listing is the picker's navigation step: entries with
    ``isPrefix`` are folders to descend into. ``truncated`` is set when
    the page cap cut the listing short.
    """

    entries: List[Dict[str, Any]] = []
    truncated = False
    for obj in client.list_objects(bucket, prefix=prefix, recursive=recursive):
        if len(entries) >= cap:
            truncated = True
            break
        name = str(obj.object_name)
        if getattr(obj, "is_dir", False):
            entries.append({"key": name, "isPrefix": True})
            continue
        entries.append(
            {
                "key": name,
                "isPrefix": False,
                "size": getattr(obj, "size", None),
                "lastModified": _iso(getattr(obj, "last_modified", None)),
                "etag": _clean_etag(getattr(obj, "etag", None)),
            }
        )
    return {
        "bucket": bucket,
        "prefix": prefix,
        "entries": entries,
        "truncated": truncated,
    }


def stat_store_object(client: Any, bucket: str, key: str) -> Dict[str, Any]:
    """The reference facts for one object (raises the client's error)."""

    stat = client.stat_object(bucket, key)
    return {
        "bucket": bucket,
        "key": key,
        "etag": _clean_etag(getattr(stat, "etag", None)),
        "size": getattr(stat, "size", None),
        "lastModified": _iso(getattr(stat, "last_modified", None)),
    }


def resolve_source_selections(
    client: Any,
    selections: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Resolve picker selections into concrete source references.

    Each selection is ``{bucket, keys: [...]}`` (explicit objects) or
    ``{bucket, prefix: "..."}`` (everything under the prefix, resolved
    NOW — the recorded references are the resolved keys, so a later
    change under the prefix never silently joins the workspace).
    Raises ``ValueError`` with a caller-facing message on any problem:
    a missing object, an over-cap prefix, a malformed selection.
    Duplicate (bucket, key) pairs collapse to one reference.
    """

    resolved: List[Dict[str, Any]] = []
    seen: set = set()

    def _add(ref: Dict[str, Any]) -> None:
        marker = (ref["bucket"], ref["key"])
        if marker in seen:
            return
        seen.add(marker)
        resolved.append(ref)

    for selection in selections or []:
        if not isinstance(selection, dict):
            raise ValueError("Each source selection must be an object.")
        bucket = str(selection.get("bucket") or "").strip()
        if not bucket:
            raise ValueError("Each source selection needs a bucket.")
        keys = selection.get("keys") or []
        prefix = selection.get("prefix")
        if keys:
            for key in keys:
                key = str(key or "").strip()
                if not key:
                    raise ValueError(f"Empty object key in selection for bucket {bucket}.")
                try:
                    _add(stat_store_object(client, bucket, key))
                except Exception as exc:  # noqa: BLE001 - surface as 400 text
                    raise ValueError(
                        f"Object not readable: {bucket}/{key} ({getattr(exc, 'code', None) or exc})"
                    ) from exc
        elif prefix is not None:
            prefix = str(prefix)
            listing = list_store_objects(
                client, bucket, prefix, recursive=True, cap=MAX_PREFIX_OBJECTS + 1
            )
            files = [e for e in listing["entries"] if not e.get("isPrefix")]
            if listing["truncated"] or len(files) > MAX_PREFIX_OBJECTS:
                raise ValueError(
                    f"Prefix {bucket}/{prefix} holds more than {MAX_PREFIX_OBJECTS} "
                    "objects; narrow the prefix or pick objects explicitly."
                )
            if not files:
                raise ValueError(f"No objects found under {bucket}/{prefix}.")
            for entry in files:
                _add(
                    {
                        "bucket": bucket,
                        "key": entry["key"],
                        "etag": entry.get("etag"),
                        "size": entry.get("size"),
                        "lastModified": entry.get("lastModified"),
                    }
                )
        else:
            raise ValueError(
                f"Selection for bucket {bucket} needs either keys or a prefix."
            )
    return resolved
