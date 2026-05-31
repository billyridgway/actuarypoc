from __future__ import annotations

"""Simple in-process ProductDefinition registry.

For now this is a lightweight loader that discovers JSON ProductDefinition
files under ``examples/product-definitions/`` in the repo and exposes a
lookup by product_code.

There is deliberately **no** MinIO or database wiring here yet; the goal is
to centralise the local POC ProductDefinition handling so that callers like
the AuditRecord builder do not need to know about hard-coded file-system
paths or P12TRF-specific logic.
"""

from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Dict, Optional


def _definitions_base_dir() -> Path:
    """Return the base directory for bundled ProductDefinition JSON files.

    This is resolved relative to the repo root so that it works both in
    local development and inside the container image.
    """

    # ``src/actuarypoc`` → repo root is ``parents[2]``.
    return Path(__file__).resolve().parents[2] / "examples" / "product-definitions"


@lru_cache(maxsize=1)
def _load_registry() -> Dict[str, Dict[str, Any]]:
    """Load all ProductDefinition JSONs into a simple in-memory registry.

    Keys are upper-cased ``product_code`` values. Files that cannot be read
    or parsed are skipped; this is a best-effort helper.
    """

    base = _definitions_base_dir()
    registry: Dict[str, Dict[str, Any]] = {}

    if not base.exists():
        return registry

    for path in base.glob("*.json"):
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            # Best-effort only; ignore malformed files.
            continue

        code = str(payload.get("product_code") or "").upper()
        if not code:
            continue

        # Last one wins if duplicates exist for the same product code.
        registry[code] = payload

    return registry


def get_product_definition(product_code: str) -> Optional[Dict[str, Any]]:
    """Return the ProductDefinition for a given product code, if any.

    The lookup is case-insensitive. Returns ``None`` when there is no
    matching definition in the local registry.
    """

    if not product_code:
        return None

    registry = _load_registry()
    return registry.get(str(product_code).upper())
