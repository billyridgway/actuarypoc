from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import json


# Minimal Product Mechanics v0.1 – intentionally small and file-backed.
# This module is P12TRF-focused for now but the data model is generic
# enough to support additional products via per-product JSON fixtures.


@dataclass
class FilingSource:
    id: str
    document_hint: str
    page: Optional[str] = None
    snippet: Optional[str] = None
    confidence: float = 0.8


@dataclass
class MechanicDslRef:
    id: str
    file: str
    path: str
    description: Optional[str] = None
    # Optional preview of the current DSL value; v0.1 leaves this
    # unpopulated and treats it as a future enhancement.
    valuePreview: Optional[Any] = None  # JSON-serialisable


@dataclass
class ProductMechanic:
    id: str
    product_code: str
    name: str
    type: str  # e.g. "charge", "benefit", "structure", "feature"
    description: str

    filing_sources: List[FilingSource]
    dsl_refs: List[MechanicDslRef]

    upstream_ids: List[str]
    downstream_ids: List[str]

    confidence: float = 0.8


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _mechanics_fixture_path_for_product(product_code: str) -> Optional[Path]:
    """Return the mechanics JSON fixture path for a given product.

    v0.1 is intentionally minimal: only P12TRF is wired up via
    ``examples/p12trf_mechanics.json``. Other products simply return
    ``None`` so callers can treat mechanics as advisory.
    """

    code = (product_code or "").strip().upper()
    if code == "P12TRF":
        return _PROJECT_ROOT / "examples" / "p12trf_mechanics.json"
    return None


def load_mechanics_for_product(product_code: str) -> List[ProductMechanic]:
    """Load ProductMechanic entries for a product from a JSON fixture.

    Failures are treated as "no mechanics" rather than errors: this
    layer is advisory and should not break core flows.
    """

    path = _mechanics_fixture_path_for_product(product_code)
    if path is None or not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    items = data.get("mechanics") or []
    mechanics: List[ProductMechanic] = []

    for raw in items:
        if not isinstance(raw, dict):
            continue

        fs_list: List[FilingSource] = []
        for fs in raw.get("filing_sources", []) or []:
            if not isinstance(fs, dict):
                continue
            try:
                fs_list.append(
                    FilingSource(
                        id=str(fs.get("id")),
                        document_hint=str(fs.get("document_hint")),
                        page=fs.get("page"),
                        snippet=fs.get("snippet"),
                        confidence=float(fs.get("confidence", 0.8)),
                    )
                )
            except Exception:
                continue

        dsl_list: List[MechanicDslRef] = []
        for dr in raw.get("dsl_refs", []) or []:
            if not isinstance(dr, dict):
                continue
            try:
                dsl_list.append(
                    MechanicDslRef(
                        id=str(dr.get("id")),
                        file=str(dr.get("file")),
                        path=str(dr.get("path")),
                        description=dr.get("description"),
                        valuePreview=dr.get("valuePreview"),
                    )
                )
            except Exception:
                continue

        try:
            mech = ProductMechanic(
                id=str(raw.get("id")),
                product_code=str(raw.get("product_code")),
                name=str(raw.get("name")),
                type=str(raw.get("type")),
                description=str(raw.get("description")),
                filing_sources=fs_list,
                dsl_refs=dsl_list,
                upstream_ids=[str(x) for x in (raw.get("upstream_ids") or [])],
                downstream_ids=[str(x) for x in (raw.get("downstream_ids") or [])],
                confidence=float(raw.get("confidence", 0.8)),
            )
        except Exception:
            continue

        mechanics.append(mech)

    return mechanics


def mechanics_to_json(mechanics: List[ProductMechanic]) -> List[Dict[str, Any]]:
    """Serialise mechanics into JSON-safe dicts.

    This is a thin wrapper over ``asdict`` so the API surface remains
    stable if we later add extra fields to the dataclasses.
    """

    return [asdict(m) for m in mechanics]
