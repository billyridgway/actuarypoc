from __future__ import annotations

from typing import Any, Dict


def _get_registry_module():
    # Import via helper to mirror the psycopg-stubbing pattern used elsewhere
    # if we ever need it; currently this is a simple direct import.
    from actuarypoc import product_registry  # type: ignore

    return product_registry


def test_product_registry_p12trf_lookup() -> None:
    registry = _get_registry_module()

    pd: Dict[str, Any] | None = registry.get_product_definition("P12TRF")
    assert pd is not None
    assert pd.get("product_code") == "P12TRF"
    assert pd.get("product_definition_id") == "P12TRF-def-v1-poc"

    # Case-insensitive lookup should also work.
    pd_lower = registry.get_product_definition("p12trf")
    assert pd_lower is not None
    assert pd_lower.get("product_definition_id") == "P12TRF-def-v1-poc"


def test_product_registry_unknown_returns_none() -> None:
    registry = _get_registry_module()
    assert registry.get_product_definition("UNKNOWN_PRODUCT_CODE") is None

