from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import json


# Minimal Product Mechanics v0.1 – intentionally small and file-backed.
#
# The data model and loader are product-agnostic by design. For v0.1 we
# only ship a curated mechanics fixture for P12TRF, but any product code
# can be supported by adding an ``examples/{product_code_lower}_mechanics.json``
# file or wiring a different backing store in future iterations.


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

    # Optional expectations for specific DSL paths, keyed by the same
    # dotted path used in MechanicDslRef.path (e.g. "meta.policy_fee").
    # When present, these expectations can be validated against the
    # executable DSL.
    expected: Optional[Dict[str, Any]] = None

    upstream_ids: List[str]
    downstream_ids: List[str]

    confidence: float = 0.8


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _mechanics_fixture_path_for_product(product_code: str) -> Optional[Path]:
    """Return the mechanics JSON fixture path for a given product.

    v0.1 uses a simple convention-only lookup:

        examples/{product_code_lower}_mechanics.json

    For example, P12TRF uses ``examples/p12trf_mechanics.json``. If no
    mechanics file exists yet for a product, callers should treat that as
    "not populated yet", not "unsupported".
    """

    code = (product_code or "").strip()
    if not code:
        return None
    name = f"{code.lower()}_mechanics.json"
    return _PROJECT_ROOT / "examples" / name


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

        expected_raw = raw.get("expected") if isinstance(raw, dict) else None
        expected: Optional[Dict[str, Any]]
        if isinstance(expected_raw, dict):
            expected = expected_raw
        else:
            expected = None

        try:
            mech = ProductMechanic(
                id=str(raw.get("id")),
                product_code=str(raw.get("product_code")),
                name=str(raw.get("name")),
                type=str(raw.get("type")),
                description=str(raw.get("description")),
                filing_sources=fs_list,
                dsl_refs=dsl_list,
                expected=expected,
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


def _resolve_dsl_path(formula: Any, path: str) -> Any:
    """Best-effort resolve a dotted DSL path against a loaded formula.

    v0.1 intentionally supports a very small subset of paths used by
    mechanics expectations, primarily under ``meta.*``. Unknown or
    unresolvable paths return a sentinel value ``_MISSING`` so callers
    can distinguish "missing" from ``None``.
    """

    # Sentinel for missing values
    _MISSING = object()

    if not isinstance(path, str) or not path:
        return _MISSING

    # Meta paths: meta.foo or meta.foo.bar
    if path.startswith("meta."):
        meta = getattr(formula, "meta", None) or {}
        if not isinstance(meta, dict):
            return _MISSING
        current: Any = meta
        for part in path.split(".")[1:]:
            if not isinstance(current, dict):
                return _MISSING
            if part not in current:
                return _MISSING
            current = current[part]
        return current

    # Flags or other fields can be added later; for now treat as missing.
    return _MISSING


def validate_mechanics_against_dsl(product_code: str) -> List[Dict[str, Any]]:
    """Validate mechanics expectations against the current DSL.

    This is **Mechanics Validation v0.1**: mechanics remain advisory but
    act as a contract against executable DSL fields. The function is
    product-agnostic; it relies on mechanics + DSL fixtures being
    present for the given product_code.
    """

    from actuarypoc.dsl.policy_dsl import load_formula  # local import to avoid cycles

    checks: List[Dict[str, Any]] = []
    mechanics = load_mechanics_for_product(product_code)
    if not mechanics:
        return checks

    # Pre-load formulas per DSL file to avoid repeated disk I/O.
    formula_cache: Dict[str, Any] = {}

    for mech in mechanics:
        expected = mech.expected or {}
        if not isinstance(expected, dict):
            # Mechanic has no expectations; emit an informational check
            # so UIs can show that validation is incomplete.
            checks.append(
                {
                    "mechanicId": mech.id,
                    "mechanicName": mech.name,
                    "dslFile": None,
                    "dslPath": None,
                    "status": "mechanic_expected_missing",
                    "expectedValue": None,
                    "actualValue": None,
                    "message": "Mechanic has DSL refs but no expected values configured.",
                }
            )
            continue

        for dsl_path, expected_value in expected.items():
            # Find a DSL ref that matches this path so we know which file
            # to load. When multiple refs share a path, we arbitrarily
            # pick the first.
            ref = None
            for r in mech.dsl_refs:
                if r.path == dsl_path:
                    ref = r
                    break

            if ref is None:
                checks.append(
                    {
                        "mechanicId": mech.id,
                        "mechanicName": mech.name,
                        "dslFile": None,
                        "dslPath": dsl_path,
                        "status": "dsl_missing",
                        "expectedValue": expected_value,
                        "actualValue": None,
                        "message": "No DSL reference found for expected path on this mechanic.",
                    }
                )
                continue

            dsl_file = ref.file
            try:
                if dsl_file not in formula_cache:
                    formula_cache[dsl_file] = load_formula(str(_PROJECT_ROOT / dsl_file))
                formula = formula_cache[dsl_file]
                actual_value = _resolve_dsl_path(formula, dsl_path)
            except Exception as exc:  # defensive; should not break PMR
                checks.append(
                    {
                        "mechanicId": mech.id,
                        "mechanicName": mech.name,
                        "dslFile": dsl_file,
                        "dslPath": dsl_path,
                        "status": "error",
                        "expectedValue": expected_value,
                        "actualValue": None,
                        "message": f"Error while loading DSL or resolving path: {exc}",
                    }
                )
                continue

            _MISSING = object()
            if actual_value is _MISSING:
                checks.append(
                    {
                        "mechanicId": mech.id,
                        "mechanicName": mech.name,
                        "dslFile": dsl_file,
                        "dslPath": dsl_path,
                        "status": "dsl_missing",
                        "expectedValue": expected_value,
                        "actualValue": None,
                        "message": "DSL path could not be resolved for this mechanic.",
                    }
                )
                continue

            # Shallow equality comparison is sufficient for v0.1 because
            # expected values are shaped to match the DSL meta structures.
            if actual_value == expected_value:
                status = "ok"
                message = "Mechanic expected value matches DSL."
            else:
                status = "mismatch"
                message = "Mechanic expected value differs from DSL."

            checks.append(
                {
                    "mechanicId": mech.id,
                    "mechanicName": mech.name,
                    "dslFile": dsl_file,
                    "dslPath": dsl_path,
                    "status": status,
                    "expectedValue": expected_value,
                    "actualValue": actual_value,
                    "message": message,
                }
            )

    return checks


def generate_dsl_fragments_from_mechanics(product_code: str, dsl_paths: List[str]) -> List[Dict[str, Any]]:
    """Generate small DSL fragments from mechanics expectations.

    Mechanics-Generated DSL v0.1 is intentionally tiny and advisory:

    - For now it only supports paths where mechanics.expected[...] is
      populated (e.g. ``meta.policy_fee`` for P12TRF).
    - It does not modify DSL files or influence projections; it simply
      returns a preview of what the DSL *would* look like if driven from
      mechanics, alongside the current DSL value.

    The function is product-agnostic: any product with a populated
    mechanics fixture and expectations for the requested paths will
    participate.
    """

    from actuarypoc.dsl.policy_dsl import load_formula  # local import to avoid cycles

    fragments: List[Dict[str, Any]] = []
    mechanics = load_mechanics_for_product(product_code)
    if not mechanics or not dsl_paths:
        return fragments

    formula_cache: Dict[str, Any] = {}

    for path in dsl_paths:
        # Find a mechanic that carries an expected value for this path.
        mech: Optional[ProductMechanic] = None
        for m in mechanics:
            if isinstance(m.expected, dict) and path in m.expected:
                mech = m
                break

        if mech is None:
            fragments.append(
                {
                    "dslPath": path,
                    "sourceMechanicId": None,
                    "sourceMechanicName": None,
                    "generatedValue": None,
                    "currentDslValue": None,
                    "status": "mechanic_missing",
                    "message": "No mechanic with expectations for this DSL path.",
                }
            )
            continue

        expected_value = mech.expected.get(path) if isinstance(mech.expected, dict) else None
        if expected_value is None:
            fragments.append(
                {
                    "dslPath": path,
                    "sourceMechanicId": mech.id,
                    "sourceMechanicName": mech.name,
                    "generatedValue": None,
                    "currentDslValue": None,
                    "status": "expected_missing",
                    "message": "Mechanic does not define an expected value for this DSL path.",
                }
            )
            continue

        # Identify a DSL file to compare against using the first matching
        # DSL ref for this path.
        ref = None
        for r in mech.dsl_refs:
            if r.path == path:
                ref = r
                break

        current_value: Any = None
        status: str
        message: str

        if ref is None:
            status = "dsl_missing"
            message = "No DSL reference recorded for this path; cannot compare against current DSL."
        else:
            dsl_file = ref.file
            try:
                if dsl_file not in formula_cache:
                    formula_cache[dsl_file] = load_formula(str(_PROJECT_ROOT / dsl_file))
                formula = formula_cache[dsl_file]
                resolved = _resolve_dsl_path(formula, path)
                _MISSING = object()
                if resolved is _MISSING:
                    status = "dsl_missing"
                    message = "DSL path could not be resolved from the current formula."
                else:
                    current_value = resolved
                    if current_value == expected_value:
                        status = "matches_current_dsl"
                        message = "Generated DSL fragment matches current DSL value."
                    else:
                        status = "differs_from_current_dsl"
                        message = "Generated DSL fragment differs from current DSL value."
            except Exception as exc:  # defensive; preview only
                status = "error"
                message = f"Error while loading DSL or resolving path: {exc}"

        fragments.append(
            {
                "dslPath": path,
                "sourceMechanicId": mech.id,
                "sourceMechanicName": mech.name,
                "generatedValue": expected_value,
                "currentDslValue": current_value,
                "status": status,
                "message": message,
            }
        )

    return fragments
