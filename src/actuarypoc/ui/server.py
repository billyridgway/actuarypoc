from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import io
import json
import logging
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from actuarypoc.connectors.base import CSVConnector
from actuarypoc.domain.product_definition_v1 import ProductDefinitionLineage, ProductDefinitionV1
from actuarypoc.product_registry import get_product_definition
from actuarypoc.storage.minio_client import ensure_bucket, get_minio_client, get_bucket_name
from actuarypoc.config.assumptions import list_assumption_sets, approve_assumption_set
from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.domain.product_mechanics import (
    load_mechanics_for_product,
    mechanics_to_json,
    validate_mechanics_against_dsl,
)
from actuarypoc.projection.engine import ProjectionEngine
from actuarypoc.projection.mortality import build_term23_surface
from actuarypoc.projection.premium import PremiumLookupService, build_premium_table, load_premium_table_from_csv, select_face_band
from actuarypoc.projection.service import store_projection
from actuarypoc.extract.assumptions_for_product import (
    generate_product_metadata_from_minio,
    generate_assumption_set_for_product,
)
from actuarypoc.agents.pmr_ai import summarise_pmr, propose_decision
from actuarypoc.agents.scenario_ai import generate_scenarios_for_product
from actuarypoc.storage.postgres_client import (
    get_last_product_model_review_decision,
    list_product_model_review_decisions,
    get_product_model_review_decision,
    get_product_review,
    list_filing_rule_evidence,
    list_product_documents,
    relabel_documents_product,
    record_document_upload,
    record_filing_rule_evidence,
    record_product_model_review_decision,
    update_product_model_review_bundle,
    upsert_product_review_draft,
)

try:  # FastAPI can be configured with either Pydantic v1 or v2
    from pydantic import BaseModel
except Exception:  # pragma: no cover - extremely unlikely in this env
    BaseModel = object  # type: ignore[assignment]


app = FastAPI(title="ActuaryPOC Projection Viewer", version="0.1.0")

# Simple runtime marker so UIs can distinguish deployments without needing
# access to git metadata. This is initialised when the process starts,
# which is sufficient for "did the pod restart?" checks.
BUILD_STARTED_AT = datetime.utcnow().isoformat() + "Z"


# Mount built React UI (if present) under /web. This expects `vite build`
# to have been run in the `web/` directory at the project root, producing
# `web/dist`. In the Docker image we build the UI from `/opt/dagster/app/web`,
# so at runtime the dist directory is `/opt/dagster/app/web/dist`.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DIST_DIR = _PROJECT_ROOT / "web" / "dist"
if _DIST_DIR.exists():  # pragma: no cover - environment dependent
    # Serve the SPA HTML under /web and static assets under /assets so
    # that the Vite-generated <script src="/assets/..."> references
    # resolve correctly when the app is hosted at the FastAPI root.
    app.mount("/web", StaticFiles(directory=_DIST_DIR, html=True), name="web")
    assets_dir = _DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir, html=False), name="web-assets")


# ---------------------------------------------------------------------------
# POC: Product Model Review – P12TRF
#
# This endpoint assembles a minimal, actuary-facing JSON payload for the
# Product Model Review UI. For v0.1 it is still POC-focused, but sections
# such as Product Scope, Scenario Evidence, and internal Rate
# Reconciliation are now derived from real P12TRF assets where possible
# instead of being entirely static text.
# ---------------------------------------------------------------------------

_P12TRF_DEFINITION_PATH = _PROJECT_ROOT / "examples" / "product-definitions" / "p12trf-product-definition.json"


_PRODUCT_REGISTRY: List[Dict[str, Any]] = [
    {
        "productCode": "P12TRF",
        "productName": "Pacific Life ICC12 P12TRF Term (POC)",
        "status": "implemented",
        "reviewEndpoint": "/api/product-model-review/P12TRF",
    },
    {
        "productCode": "DEMO-TERM",
        "productName": "Demo Term Product",
        "status": "not_implemented",
        "reviewEndpoint": None,
    },
]


def _get_product_config(product_code: str) -> Optional[Dict[str, Any]]:
    code_norm = (product_code or "").strip().upper()
    for entry in _PRODUCT_REGISTRY:
        if (entry.get("productCode") or "").upper() == code_norm:
            return entry
    # For ad‑hoc product codes that aren't yet in the static registry,
    # synthesise a minimal config so they can still participate in the
    # Product Review / Model Review flows.
    return {
        "productCode": code_norm,
        "productName": code_norm,
        "status": "unknown",
        "reviewEndpoint": f"/api/product-model-review/{code_norm}",
    }


def _product_definition_object_key(product_code: str, filing_id: str) -> str:
    return f"product-definitions/{product_code.upper()}/{filing_id}/product-definition.json"


def _product_definition_build_report_key(product_code: str, filing_id: str) -> str:
    return f"product-definitions/{product_code.upper()}/{filing_id}/build-report.json"


def _coverage_matrix_object_key(product_code: str, filing_id: str) -> str:
    return f"product-definitions/{product_code.upper()}/{filing_id}/coverage-matrix.json"


def _validation_report_object_key(product_code: str, filing_id: str) -> str:
    return f"product-definitions/{product_code.upper()}/{filing_id}/validation-report.json"


def _load_or_seed_product_definition(product_code: str, filing_id: str) -> Optional[ProductDefinitionV1]:
    """Best-effort load of a ProductDefinition artefact for (product, filing).

    For v1 this prefers the MinIO-backed artefact. When none exists and the
    product has no stored ProductDefinition, we seed a minimal artefact using
    whatever base definition is available for that product. For historical
    reasons the bundled P12TRF ProductDefinition JSON is still used as a
    fallback *only* when no product-specific definition is available and the
    product code itself is P12TRF.
    """

    product_code = (product_code or "").upper()
    filing_id = (filing_id or "").strip()
    if not product_code or not filing_id:
        return None

    minio_client = get_minio_client()
    ensure_bucket(minio_client)
    bucket = get_bucket_name()
    obj_key = _product_definition_object_key(product_code, filing_id)

    # First try to read any existing artefact.
    try:
        if minio_client.stat_object(bucket, obj_key):  # type: ignore[truthy-function]
            response = minio_client.get_object(bucket, obj_key)
            try:
                import json

                payload = json.loads(response.read())
            finally:
                response.close()
                response.release_conn()
            return ProductDefinitionV1(**payload)
    except Exception:
        # Missing object or MinIO not configured; fall through to seed logic
        # where possible.
        pass

    # Seed a minimal artefact when we have a base ProductDefinition shape
    # available for this product. For P12TRF we fall back to the bundled
    # fixture when no database-backed definition exists.
    base_def = get_product_definition(product_code)
    if base_def is None and product_code == "P12TRF":
        base_def = _load_p12trf_definition()
    if base_def is None:
        # No base definition to seed from for this product.
        return None
    issue_limits = base_def.get("issue_age_limits") or {}
    underwriting = base_def.get("underwriting_classes") or []

    # Derive additional dimensionality from the bundled P12TRF scenarios
    # fixture so that the ProductDefinition reflects the same term
    # periods, risk/smoker classes, premium modes, and face amount ranges
    # used by the POC Product Model Review.
    term_periods: List[int] = []
    risk_classes: List[str] = []
    smoker_classes: List[str] = []
    premium_modes: List[str] = []
    face_amounts: List[float] = []

    try:
        import json

        scenarios_path = _PROJECT_ROOT / "examples" / "p12trf_scenarios.json"
        if scenarios_path.exists():
            payload = json.loads(scenarios_path.read_text(encoding="utf-8"))
            scenarios = payload.get("scenarios") or []
            for s in scenarios:
                policy = (s or {}).get("policy") or {}
                lp = policy.get("level_period")
                try:
                    lp_int = int(lp) if lp is not None else None
                except (TypeError, ValueError):
                    lp_int = None
                if lp_int and lp_int > 0:
                    term_periods.append(lp_int)

                rc = policy.get("risk_class")
                if isinstance(rc, str) and rc.strip():
                    risk_classes.append(rc.strip())

                sc = policy.get("smoker_class")
                if isinstance(sc, str) and sc.strip():
                    smoker_classes.append(sc.strip())

                pm = policy.get("premium_mode")
                if isinstance(pm, str) and pm.strip():
                    premium_modes.append(pm.strip().upper())

                fa = policy.get("face_amount")
                try:
                    fa_val = float(fa) if fa is not None else None
                except (TypeError, ValueError):
                    fa_val = None
                if fa_val is not None and fa_val > 0:
                    face_amounts.append(fa_val)
    except Exception:
        # Best-effort only; if the fixture is missing or malformed we keep
        # the minimal dimensionality.
        pass

    # Normalise sets.
    def _sorted_unique(values: List[Any]) -> List[Any]:
        seen = set()
        out: List[Any] = []
        for v in values:
            if v in seen:
                continue
            seen.add(v)
            out.append(v)
        try:
            return sorted(out)
        except Exception:
            return out

    term_periods = _sorted_unique(term_periods) or [20]
    risk_classes = _sorted_unique(risk_classes)
    smoker_classes = _sorted_unique(smoker_classes) or ["non_smoker", "smoker"]
    premium_modes = _sorted_unique(premium_modes) or ["ANNUAL"]

    face_min = min(face_amounts) if face_amounts else None
    face_max = max(face_amounts) if face_amounts else None

    pd = ProductDefinitionV1(
        product_code=product_code,
        filing_id=filing_id,
        coverages=[
            {
                "id": "base_term",
                "name": base_def.get("marketing_name") or f"{product_code} Term (base)",
                "kind": "base",
                "term_periods": term_periods,
                "notes": "POC base term coverage for P12TRF; term periods inferred from default scenarios.",
            }
        ],
        issue_age_min=issue_limits.get("min"),
        issue_age_max=issue_limits.get("max"),
        term_periods=term_periods,
        underwriting_classes=list(underwriting),
        risk_classes=risk_classes,
        smoker_classes=smoker_classes,
        premium_modes=premium_modes,
        face_amount_min=face_min,
        face_amount_max=face_max,
        source_documents=[],
        evidence_refs=[],
        extra={
            "unmodeled_coverages": base_def.get("riders") or [],
        },
    )

    # Attach document and evidence links based on the current Product
    # Review state where possible.
    try:
        # Documents for this product/filing become source_documents.
        docs = list_product_documents(product_code, filing_id=filing_id)
        pd.source_documents = [
            {
                "document_path": str(d.get("object_path")),
                "description": d.get("description"),
                "filing_id": d.get("serff_id") or filing_id,
            }
            for d in docs
            if d.get("object_path")
        ]

        # filing_rule_evidence entries become evidence_refs keyed off
        # simple feature IDs so the Trust Surface can group them.
        ev_rows = list_filing_rule_evidence(product_code, filing_id=filing_id)
        refs: List[Dict[str, Any]] = []
        for ev in ev_rows:
            rule_id = ev.get("rule_id")
            if rule_id not in {"rule_death_benefit_term", "rule_level_premiums"}:
                continue
            feature_id = "base_term_coverage" if rule_id == "rule_death_benefit_term" else "level_premiums"
            refs.append(
                {
                    "feature_id": feature_id,
                    "rule_id": rule_id,
                    "document_path": ev.get("document_path"),
                    "page_reference": ev.get("page_reference"),
                }
            )
        pd.evidence_refs = refs
    except Exception:
        # Best-effort only; absence of Postgres should not break POC flows.
        pass

    try:
        import json

        body = json.dumps(pd.dict()).encode("utf-8")  # type: ignore[call-arg]
        minio_client.put_object(bucket, obj_key, data=body, length=len(body), content_type="application/json")
    except Exception:
        # If MinIO is unavailable we still want the Trust Surface to render
        # using the in-memory ProductDefinition.
        pass

    return pd


class ProductModelReviewDecisionRequest(BaseModel):  # type: ignore[misc]
    reviewer: Optional[str]
    decision: str
    exclusions: Optional[str] = None
    comments: Optional[str] = None


class ProductModelReviewDecisionResponse(BaseModel):  # type: ignore[misc]
    id: Optional[int] = None
    product_code: str
    reviewer: Optional[str] = None
    decision: str
    exclusions: Optional[str] = None
    comments: Optional[str] = None
    created_at: Optional[str] = None
    filing_id: Optional[str] = None
    generation_id: Optional[str] = None
    pd_generated_at: Optional[str] = None
    pd_generator_version: Optional[str] = None
    pd_warning_count: Optional[int] = None
    coverage_covered_count: Optional[int] = None
    coverage_partial_count: Optional[int] = None
    coverage_gap_count: Optional[int] = None
    coverage_not_applicable_count: Optional[int] = None
    validation_status: Optional[str] = None
    validation_pass_count: Optional[int] = None
    validation_warning_count: Optional[int] = None
    validation_fail_count: Optional[int] = None

    # Scenario validation snapshot at decision time
    scenario_validation_status: Optional[str] = None
    scenario_validation_pass_count: Optional[int] = None
    scenario_validation_warning_count: Optional[int] = None
    scenario_validation_fail_count: Optional[int] = None

    # Immutable evidence snapshot fields
    product_definition_path: Optional[str] = None
    product_definition_hash: Optional[str] = None
    build_report_path: Optional[str] = None
    build_report_hash: Optional[str] = None
    coverage_matrix_path: Optional[str] = None
    coverage_matrix_hash: Optional[str] = None
    validation_report_path: Optional[str] = None
    validation_snapshot_hash: Optional[str] = None
    bundle_path: Optional[str] = None
    bundle_hash: Optional[str] = None


class ProductReviewDraftRequest(BaseModel):  # type: ignore[misc]
    carrier_name: str
    product_name: str
    product_code: str
    product_type: str
    filing_id: Optional[str] = None


class ProductReviewMetadataSuggestionRequest(BaseModel):  # type: ignore[misc]
    productCodeHint: Optional[str] = None
    filingIdHint: Optional[str] = None
    model: Optional[str] = None
    feedback: Optional[str] = None
    previous: Optional[Dict[str, Any]] = None


class ProductModelReviewAISummaryRequest(BaseModel):  # type: ignore[misc]
    modelSummary: Optional[str] = None  # explicit model override for summary stage
    modelDecision: Optional[str] = None  # explicit model override for decision stage
    feedback: Optional[str] = None
    previousSummary: Optional[Dict[str, Any]] = None
    previousDecision: Optional[Dict[str, Any]] = None


class ProductCodeFinalizeRequest(BaseModel):  # type: ignore[misc]
    oldProductCode: str
    newProductCode: str


class ProductAssumptionsAIGenerateRequest(BaseModel):  # type: ignore[misc]
    productCode: str
    filingId: Optional[str] = None
    setId: Optional[str] = None
    model: Optional[str] = None
    feedback: Optional[str] = None
    previous: Optional[Dict[str, Any]] = None


class ProductScenariosAIGenerateRequest(BaseModel):  # type: ignore[misc]
    productCode: str
    filingId: Optional[str] = None
    productType: Optional[str] = None
    model: Optional[str] = None
    feedback: Optional[str] = None
    previous: Optional[List[Dict[str, Any]]] = None


class ScenarioConfig(BaseModel):  # type: ignore[misc]
    id: Optional[str] = None
    name: Optional[str] = None
    age: Optional[int] = None
    sex: Optional[str] = None
    smokerClass: Optional[str] = None
    riskClass: Optional[str] = None
    faceAmount: Optional[float] = None
    levelPeriod: Optional[int] = None
    premiumMode: Optional[str] = None
    modalPremium: Optional[float] = None
    # Some products are funded via a single deposit rather than recurring
    # modal premiums. For those cases the UI can treat modalPremium as the
    # recurring amount (when present) and initialDeposit as the up-front
    # funding amount.
    initialDeposit: Optional[float] = None
    # Derived banding based on DSL/meta.face_bands; populated server-side
    # for term-style products so actuaries can see which face band each
    # scenario falls into.
    faceBand: Optional[str] = None
    purpose: Optional[str] = None
    dimensionsExercised: Optional[List[str]] = None
    source: Optional[str] = None


class ScenarioConfigPayload(BaseModel):  # type: ignore[misc]
    scenarios: List[ScenarioConfig]


class IllustrationRequest(BaseModel):  # type: ignore[misc]
    age: Optional[int] = None
    termYears: Optional[int] = None
    riskClass: Optional[str] = None
    smokerClass: Optional[str] = None
    faceAmount: Optional[float] = None
    premiumMode: Optional[str] = None


_ALLOWED_PMR_DECISIONS = {
    "approve_for_poc",
    "approve_with_exclusions",
    "request_changes",
    "reject",
}


def _canonical_json_sha256(obj: Any) -> Optional[str]:
    """Return a stable SHA256 hash for a JSON-serialisable object.

    Uses sorted keys and compact separators so that semantically identical
    structures produce the same hash regardless of key order or
    whitespace. When the object cannot be serialised, returns None.
    """

    try:
        import json

        payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except Exception:
        return None
    return sha256(payload).hexdigest()


def _parse_iso8601_timestamp(value: Any) -> Optional[datetime]:
    """Best-effort parse of an ISO-8601-like timestamp.

    Returns a timezone-aware ``datetime`` when possible. On any failure
    returns ``None`` instead of raising.
    """

    # Allow callers to pass through native ``datetime`` instances
    # without additional parsing.
    if isinstance(value, datetime):
        return value

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    try:
        # Normalise ``Z`` suffix into an explicit UTC offset so that
        # ``datetime.fromisoformat`` accepts it.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _build_review_freshness(
    review_meta: Dict[str, Any],
    documents: List[Dict[str, Any]],
    product_definition_build: Optional[Dict[str, Any]],
    last_decision: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Derive a lightweight "review freshness" status for the Trust Surface.

    This compares the current Product Review generation against document
    uploads, ProductDefinition builds, and the latest recorded decision
    snapshot. It intentionally prefers robustness over precision: any
    parsing failures result in ``None`` timestamps and are treated as
    "unknown" rather than surfacing errors to the caller.
    """

    status: str = "fresh"
    messages: List[str] = []

    # Core generation timestamps from review metadata.
    generated_at_raw = review_meta.get("generatedAt")
    generation_ts = _parse_iso8601_timestamp(generated_at_raw)

    # Latest document upload time (if any).
    latest_doc_ts: Optional[datetime] = None
    latest_doc_raw: Optional[str] = None
    for d in documents or []:
        raw = d.get("created_at") or d.get("createdAt")
        ts = _parse_iso8601_timestamp(raw)
        if ts is not None and (latest_doc_ts is None or ts > latest_doc_ts):
            latest_doc_ts = ts
            latest_doc_raw = raw

    # ProductDefinition build timestamp (if a lineage-backed build exists).
    pd_generated_raw: Optional[str] = None
    pd_generated_ts: Optional[datetime] = None
    if isinstance(product_definition_build, dict):
        pd_generated_raw = product_definition_build.get("generatedAt")
        pd_generated_ts = _parse_iso8601_timestamp(pd_generated_raw)

    # Latest decision timestamps (when a decision snapshot exists).
    decision_created_raw: Optional[str] = None
    decision_created_ts: Optional[datetime] = None
    decision_pd_generated_raw: Optional[str] = None
    decision_pd_generated_ts: Optional[datetime] = None
    if isinstance(last_decision, dict):
        decision_created_raw = last_decision.get("created_at")
        decision_created_ts = _parse_iso8601_timestamp(decision_created_raw)
        decision_pd_generated_raw = last_decision.get("pd_generated_at")
        decision_pd_generated_ts = _parse_iso8601_timestamp(decision_pd_generated_raw)

    # If we have never generated a Product Review, we cannot be "fresh".
    if generation_ts is None:
        status = "warning"
        messages.append(
            "Product Review has not been generated yet; generate a Product Review before relying on the Trust Surface."
        )
    else:
        # Documents uploaded after the current generation make the
        # evidence set stale.
        if latest_doc_ts is not None and latest_doc_ts > generation_ts:
            status = "stale"
            messages.append("A document was uploaded after the current Product Review generation.")

        # A newer ProductDefinition build than the current generation also
        # indicates that the Trust Surface may be stale.
        if pd_generated_ts is not None and pd_generated_ts > generation_ts:
            status = "stale"
            messages.append("The ProductDefinition build is newer than the current Product Review generation.")

    # Decisions made against an older generation/build are warnings: the
    # Trust Surface may be up-to-date, but the *recorded* decision is
    # lagging behind it.
    if generation_ts is not None and decision_created_ts is not None and generation_ts > decision_created_ts:
        if status == "fresh":
            status = "warning"
        messages.append(
            "A newer Product Review generation exists after the latest decision; record a new decision if you rely on the updated evidence set."
        )

    if pd_generated_ts is not None and decision_pd_generated_ts is not None and pd_generated_ts > decision_pd_generated_ts:
        if status == "fresh":
            status = "warning"
        messages.append(
            "The ProductDefinition build is newer than the ProductDefinition build recorded with the latest decision."
        )

    # For a clean "fresh" state, avoid emitting noise messages.
    if status == "fresh":
        messages = []

    return {
        "status": status,
        "messages": messages,
        "latestDocumentUploadedAt": latest_doc_raw,
        "currentGeneration": review_meta.get("currentGeneration"),
        "generatedAt": generated_at_raw,
        "productDefinitionGeneratedAt": pd_generated_raw,
        "latestDecisionCreatedAt": decision_created_raw,
    }


def _load_p12trf_definition() -> Dict[str, Any]:
    import json

    try:
        with open(_P12TRF_DEFINITION_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        # Fall back to a minimal stub if the file cannot be read.
        return {
            "product_definition_id": "P12TRF-def-v1-poc",
            "product_code": "P12TRF",
            "marketing_name": "P12TRF Term Life (definition missing)",
            "issue_age_limits": {"min": 0, "max": 0},
            "riders": [],
            "filing_refs": [],
        }


def _build_p12trf_scope(defn: Dict[str, Any]) -> Dict[str, Any]:
    """Build the Product Scope & Gap coverage map from ProductDefinition.

    This replaces static, hard-coded text with values derived from the
    current ProductDefinition where possible, while remaining honest that
    riders and other advanced features are not yet modeled.
    """

    filings = []
    for ref in defn.get("filing_refs", []) or []:
        filings.append(
            {
                "id": ref.get("filing_id") or "P12TRF-POC",
                "name": ref.get("note") or "P12TRF filing (POC)",
            }
        )

    issue_limits = defn.get("issue_age_limits") or {}
    min_age = issue_limits.get("min")
    max_age = issue_limits.get("max")

    features_modeled = [
        f"Base term life product for {defn.get('product_code', 'P12TRF')}",
    ]
    if min_age is not None and max_age is not None:
        features_modeled.append(f"Issue ages {min_age}–{max_age} (POC range)")
    features_modeled.append("Level term premiums (POC synthetic rates)")

    riders = defn.get("riders") or []
    features_not_modeled = []
    if riders:
        features_not_modeled.extend([f"Rider not modeled: {r}" for r in riders])
    features_not_modeled.append("Other advanced features not yet modeled in this POC")

    return {
        "filings": filings or [
            {"id": "P12TRF-POC", "name": "P12TRF filing (POC placeholder)"}
        ],
        "featuresModeled": features_modeled,
        "featuresNotModeled": features_not_modeled,
        "confidence": "medium",
        "pocLabel": "Scope derived from current P12TRF ProductDefinition (POC).",
    }


_P12TRF_SCENARIO_CONFIG: List[Dict[str, Any]] = [
    {
        "id": "S1",
        "name": "Typical mid-age non-smoker",
        # Scenario projection built from configurable fixture inputs
        # (historical P12TRF alias; generation-scoped keys are under
        # projections/{product_code}/reviews/{generation_id}/scenarios/).
        "projection_key": "projections/p12trf/scenarios/S1.json",
    },
    {
        "id": "S2",
        "name": "Young short-term coverage",
        # Scenario projection built from configurable fixture inputs
        "projection_key": "projections/p12trf/scenarios/S2.json",
    },
    {
        "id": "S3",
        "name": "Edge older age smoker",
        # Scenario projection built from configurable fixture inputs
        "projection_key": "projections/p12trf/scenarios/S3.json",
    },
]


def _default_p12trf_scenarios_from_product_definition(
    product_code: str,
    filing_id: Optional[str],
) -> List[Dict[str, Any]]:
    """Generate default P12TRF scenarios from the ProductDefinition.

    This is a deterministic, P12TRF-specific helper that uses the
    ProductDefinition's dimensionality to suggest three scenarios:

    - S1: mid-age non-smoker, longest term, higher face amount
    - S2: younger non-smoker, shortest term, mid-range face amount
    - S3: older smoker, shortest term, lower face amount

    The caller is still free to override these scenarios via the
    onboarding UI; this helper is only used when no scenarios have been
    persisted for the current Product Review.
    """

    if not filing_id:
        return []

    pd = _load_or_seed_product_definition(product_code, filing_id)
    if pd is None:
        return []

    ages_min = pd.issue_age_min or 18
    ages_max = pd.issue_age_max or max(ages_min, 75)
    term_periods = sorted(pd.term_periods or [20])
    long_term = term_periods[-1]
    short_term = term_periods[0]

    smoker_classes = list(pd.smoker_classes or [])
    ns = smoker_classes[0] if smoker_classes else "NS"
    s = smoker_classes[-1] if len(smoker_classes) > 1 else ns

    risk_classes = list(pd.risk_classes or [])
    best_rc = risk_classes[0] if risk_classes else "SUPER_PREFERRED_NON_TOBACCO"
    std_rc = risk_classes[1] if len(risk_classes) > 1 else (risk_classes[0] if risk_classes else "STANDARD_NON_TOBACCO")

    modes = list(pd.premium_modes or [])
    mode = (modes[0] if modes else "ANNUAL").upper()

    fa_min = pd.face_amount_min or 100_000.0
    fa_max = pd.face_amount_max or 450_000.0
    fa_mid = (fa_min + fa_max) / 2.0 if fa_min and fa_max else fa_max

    # Simple age choices: lower-third, mid, upper-third of allowed range.
    span = max(0, ages_max - ages_min)
    age_young = ages_min + max(0, span // 5)
    age_mid = ages_min + max(0, span // 2)
    age_old = ages_max - max(0, span // 5)

    dimensions = [
        "issue_age",
        "term_period",
        "smoker_class",
        "risk_class",
        "face_amount",
        "premium_mode",
    ]

    return [
        {
            "id": "S1",
            "name": "Mid-age non-smoker, base coverage",
            "age": age_mid,
            "sex": "M",
            "smokerClass": ns,
            "riskClass": best_rc,
            "faceAmount": fa_max,
            "levelPeriod": long_term,
            "premiumMode": mode,
            "modalPremium": None,
            "purpose": "Typical mid-age non-smoker exercising base term coverage at the longest available term.",
            "dimensionsExercised": dimensions,
            "source": "product_definition",
        },
        {
            "id": "S2",
            "name": "Younger non-smoker, short-term coverage",
            "age": age_young,
            "sex": "F",
            "smokerClass": ns,
            "riskClass": std_rc,
            "faceAmount": fa_mid,
            "levelPeriod": short_term,
            "premiumMode": mode,
            "modalPremium": None,
            "purpose": "Younger non-smoker testing shorter term coverage and mid-range face amount.",
            "dimensionsExercised": dimensions,
            "source": "product_definition",
        },
        {
            "id": "S3",
            "name": "Older smoker, short-term coverage",
            "age": age_old,
            "sex": "M",
            "smokerClass": s,
            "riskClass": std_rc,
            "faceAmount": fa_min,
            "levelPeriod": short_term,
            "premiumMode": mode,
            "modalPremium": None,
            "purpose": "Edge-case older smoker at lower face amount and shortest term.",
            "dimensionsExercised": dimensions,
            "source": "product_definition",
        },
    ]


def _default_p12trf_scenarios_for_ui() -> List[Dict[str, Any]]:
    """Return default P12TRF scenarios in UI-friendly shape.

    This reads the bundled ``examples/p12trf_scenarios.json`` fixture and
    exposes only the fields needed for the onboarding Scenario Configuration
    table. When the fixture is missing or invalid, a small empty list is
    returned instead of failing the UI.
    """

    try:
        scenarios_path = _PROJECT_ROOT / "examples" / "p12trf_scenarios.json"
        if not scenarios_path.exists():
            return []
        import json

        payload = json.loads(scenarios_path.read_text(encoding="utf-8"))
        scenarios = payload.get("scenarios") or []
    except Exception:
        return []

    ui_rows: List[Dict[str, Any]] = []
    for idx, s in enumerate(scenarios):
        sid = str(s.get("id") or f"S{idx + 1}")
        name = str(s.get("name") or f"Scenario {sid}")
        policy = s.get("policy") or {}
        ui_rows.append(
            {
                "id": sid,
                "name": name,
                "age": policy.get("issue_age"),
                "sex": policy.get("gender"),
                "smokerClass": policy.get("smoker_class"),
                "riskClass": policy.get("risk_class"),
                "faceAmount": policy.get("face_amount"),
                "levelPeriod": policy.get("level_period"),
                "premiumMode": policy.get("premium_mode"),
                "modalPremium": policy.get("modal_premium"),
            }
        )
    return ui_rows


def _ui_scenarios_to_internal(product_code: str, scenarios: List[ScenarioConfig]) -> List[Dict[str, Any]]:
    """Convert UI ScenarioConfig models into internal policy dicts.

    The internal representation mirrors ``examples/p12trf_scenarios.json`` so
    we can reuse the same scenario projection wiring for any term-style
    product. The underlying projection engine is parameterised by
    ``product_code`` so artefacts are always tagged with the correct
    product, even though the DSL and actuarial tables are currently shared
    across term products.
    """

    internal: List[Dict[str, Any]] = []
    # For historical reasons the DSL type for the POC term product is
    # "p12trf_term". For all other products we default to the lowercased
    # product code so future DSLs can plug in cleanly without changing
    # stored policies.
    base_policy_type = "p12trf_term" if product_code.upper() == "P12TRF" else product_code.lower()
    for idx, s in enumerate(scenarios):
        sid_raw = (s.id or f"S{idx + 1}").strip()
        sid = sid_raw or f"S{idx + 1}"
        name = (s.name or f"Scenario {sid}").strip() or f"Scenario {sid}"
        policy_number = f"{product_code}-{sid}"
        policy: Dict[str, Any] = {
            "policy_number": policy_number,
            "product_type": base_policy_type,
            "issue_age": s.age,
            "gender": s.sex,
            "smoker_class": s.smokerClass,
            "risk_class": s.riskClass,
            "level_period": s.levelPeriod,
            "face_amount": s.faceAmount,
            "modal_premium": s.modalPremium,
            "premium_mode": s.premiumMode,
        }
        if s.initialDeposit is not None:
            policy["initial_deposit"] = s.initialDeposit
        if s.faceBand is not None:
            policy["face_band"] = s.faceBand
        entry: Dict[str, Any] = {"id": sid, "name": name, "policy": policy}
        if s.purpose is not None:
            entry["purpose"] = s.purpose
        if s.dimensionsExercised is not None:
            entry["dimensions_exercised"] = list(s.dimensionsExercised)
        if s.source is not None:
            entry["source"] = s.source
        internal.append(entry)
    return internal


def _generate_term_scenarios_from_config(
    scenarios: List[Dict[str, Any]],
    years: int = 40,
    *,
    generation_id: Optional[str] = None,
    product_code: str = "P12TRF",
    generated_at: Optional[str] = None,
) -> List[str]:
    """Project configured term-style scenarios and persist them to MinIO.

    This is a thin, API-friendly wrapper around the internal projection
    engine used by the original P12TRF POC. It expects ``scenarios`` to be a
    list of objects with ``id``, optional ``name``, and a ``policy`` block
    mirroring ``examples/p12trf_scenarios.json``.

    It returns the list of *generation-scoped* object keys written under the
    ``projections/{product_code_lower}/reviews/{generation_id}/scenarios/``
    prefix. For backward compatibility with the existing Product Model
    Review Trust Surface, it also writes "latest" alias objects under the
    legacy ``projections/p12trf/scenarios/{scenario_id}.json`` paths when
    ``product_code == "P12TRF"``.
    """

    if not scenarios:
        return []

    base = Path(__file__).resolve().parents[1]

    dsl_path = base / "dsl" / "examples" / "p12trf_term.yaml"
    formula = load_formula(str(dsl_path))

    term23_path = base / "sample_data" / "actuarial_tables_term23.csv"
    term23_records = list(CSVConnector(str(term23_path)).fetch()) if term23_path.exists() else []
    mortality_surface = build_term23_surface(term23_records) if term23_records else None

    premium_table = None
    premium_sample_rel = (formula.meta or {}).get("premium_table_sample_csv") if getattr(formula, "meta", None) else None
    if premium_sample_rel:
        premium_csv = base / premium_sample_rel
        if premium_csv.exists():
            premium_table = load_premium_table_from_csv(str(premium_csv))

    premium_service = PremiumLookupService(premium_table) if premium_table is not None else None

    engine = ProjectionEngine(formula, mortality_surface=mortality_surface)

    object_keys: List[str] = []
    env_label = None

    product_code_norm = (product_code or "P12TRF").upper()
    product_code_lower = product_code_norm.lower()

    gen_id = generation_id or datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    gen_ts = generated_at or datetime.utcnow().isoformat() + "Z"

    for scenario in scenarios:
        sid = str(scenario.get("id") or "").strip()
        label = str(scenario.get("name") or sid or "Scenario").strip() or "Scenario"
        policy = dict(scenario.get("policy") or {})

        if not sid or not policy:
            continue

        policy_inputs = {
            "issue_age": policy.get("issue_age"),
            "gender": policy.get("gender"),
            "smoker_class": policy.get("smoker_class"),
            "risk_class": policy.get("risk_class"),
            "level_period": policy.get("level_period"),
            "face_amount": policy.get("face_amount"),
            "premium_mode": policy.get("premium_mode"),
        }

        warnings: List[str] = []
        if premium_service is not None:
            try:
                face_amount = float(policy.get("face_amount", 0) or 0.0)
            except (TypeError, ValueError):
                face_amount = 0.0

            face_band = select_face_band(getattr(formula, "meta", {}) or {}, face_amount)

            if face_band is not None and face_amount > 0:
                try:
                    issue_age = int(policy.get("issue_age", 0) or 0)
                except (TypeError, ValueError):
                    issue_age = 0
                gender = str(policy.get("gender", ""))
                risk_class = str(policy.get("risk_class", ""))
                try:
                    level_period = int(policy.get("level_period", 0) or 0)
                except (TypeError, ValueError):
                    level_period = 0

                table_p_per_1000 = premium_service.premium_per_1000(
                    issue_age=issue_age,
                    gender=gender,
                    risk_class=risk_class,
                    face_band=face_band,
                    level_period=level_period,
                )

                if table_p_per_1000 is not None:
                    annual_table_premium = float(table_p_per_1000) * (face_amount / 1000.0)
                    mode = str(policy.get("premium_mode", "")).upper()
                    if mode == "MONTHLY":
                        expected_modal = annual_table_premium / 12.0
                    else:
                        expected_modal = annual_table_premium

                    try:
                        pas_modal = float(policy.get("modal_premium", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        pas_modal = 0.0

                    diff = abs(expected_modal - pas_modal)
                    material_threshold = max(0.01, 0.001 * expected_modal)
                    if diff > material_threshold:
                        warnings.append(
                            "premium_mismatch: table-derived expected_modal={} vs configured modal_premium={}".format(
                                round(expected_modal, 6), round(pas_modal, 6)
                            )
                        )

        result = engine.project(policy, horizon=years)

        summary = {
            # Top-level generation metadata so downstream tooling (including
            # generic projection viewers) can recover which UI generation
            # produced this artefact.
            "product_code": product_code_norm,
            "generation_id": gen_id,
            "scenario_id": sid,
            "scenario_label": label,
            "generated_at": gen_ts,
            "inputs": {
                "pas_object": None,
                "actuarial_object": None,
                "rate_object": None,
                "crm_object": None,
                "term23_actuarial_object": None,
                "premium_table_object": None,
                "policy_id": policy.get("policy_number") or sid,
                # Tag artefacts with the *actual* product, even though the
                # underlying DSL and actuarial tables are currently shared
                # across term products.
                "product_id": product_code_norm,
                "product_code": product_code_norm,
                "formula_path": str(dsl_path),
                "assumption_set_id": None,
                "run_id": f"{product_code_lower}-scenario-{sid}",
                "scenario_id": sid,
                "scenario_label": label,
                "policy_inputs": policy_inputs,
            },
            "metadata": {
                "environment": env_label,
                "product_code": product_code_norm,
                "generation_id": gen_id,
                "scenario_id": sid,
                "scenario_label": label,
            },
            "warnings": warnings,
            "projection": asdict(result),
        }

        # Generation-scoped key for this scenario.
        object_name = f"projections/{product_code_lower}/reviews/{gen_id}/scenarios/{sid}.json"
        key = store_projection(summary, object_name=object_name)
        object_keys.append(key)

        # Backward-compatible alias for the existing P12TRF PMR wiring so the
        # Trust Surface can continue to read from the static scenario paths
        # while history is preserved under the generation-scoped prefix.
        if product_code_norm == "P12TRF":
            alias_name = f"projections/p12trf/scenarios/{sid}.json"
            store_projection(summary, object_name=alias_name)

    return object_keys


def _build_p12trf_scenarios_and_rates() -> Dict[str, Any]:
    """Build Scenario Evidence and a small internal rate reconciliation.

    For each configured scenario, this function:

    - Loads the corresponding projection from MinIO using the existing
      get_projection / _build_run_detail helpers.
    - Extracts real inputs (age, term, face, class, premium mode) and a
      short summary of model behavior.
    - Applies simple, objective checks (e.g. no death benefit after term)
      to derive a PASS/FAIL status.
    - Reuses the internal premium_comparison block from RunDetail to
      generate a small reconciliation sample.
    """

    scenarios: List[Dict[str, Any]] = []
    spot_checks: List[Dict[str, Any]] = []
    exceptions: List[Dict[str, Any]] = []

    for cfg in _P12TRF_SCENARIO_CONFIG:
        proj_key = cfg["projection_key"]
        try:
            data = get_projection(proj_key)
            rd = _build_run_detail(proj_key, data)
        except Exception:
            # If we cannot load this scenario, mark it as unavailable but
            # keep the rest of the page responsive.
            scenarios.append(
                {
                    "id": cfg["id"],
                    "name": cfg["name"],
                    "inputs": {},
                    "expectedBehavior": [
                        "Scenario could not be loaded from current P12TRF runs (POC).",
                    ],
                    "modelBehaviorSummary": "Unavailable",
                    "status": "unknown",
                    "ruleIds": ["rule_death_benefit_term", "rule_level_premiums"],
                }
            )
            continue

        policy_input = (rd.get("policy_input") or {})
        core = policy_input.get("core_fields") or {}
        pas_premium = policy_input.get("pas_premium") or {}
        proj = rd.get("projection_summary") or {}

        years = proj.get("years") or []
        death_benefits = proj.get("death_benefits") or []

        # The current P12TRF POC runs do not yet persist a rich set of
        # policy attributes (age, gender, smoker class, level period) into
        # the PAS export. At the moment we only have a face amount and
        # premium mode. To keep the Trust Surface honest while still being
        # useful, we:
        #
        #  - derive level_term from the projection horizon when the stored
        #    level_period is 0/empty, and
        #  - normalise placeholder values like "None"/0 into more explicit
        #    "unknown" labels instead of silently treating them as real
        #    inputs.
        #
        # This makes the scenario inputs reflect all *real* information we
        # have today, and avoids misleading "age 0 / smoker None" style
        # outputs in the Product Model Review UI.

        raw_level_period = core.get("level_period")
        try:
            level_period = int(raw_level_period or 0)
        except (TypeError, ValueError):
            level_period = 0

        if level_period <= 0 and years:
            # Fallback: treat the current projection horizon as the term.
            # This is intentionally simple for the POC but at least
            # produces a realistic, non-zero term length.
            try:
                level_period = max(int(y) for y in years if y is not None)
            except Exception:
                level_period = 0

        try:
            face_amount = float(core.get("face_amount") or 0.0)
        except (TypeError, ValueError):
            face_amount = 0.0

        issue_age = core.get("issue_age")
        age_value: Any
        if isinstance(issue_age, (int, float)) and issue_age > 0:
            age_value = int(issue_age)
        else:
            # Age is not currently captured for these POC runs; represent
            # it explicitly as unknown instead of an obviously-invalid 0.
            age_value = "unknown"

        raw_gender = str(core.get("gender")) if "gender" in core else ""
        gender_norm = (raw_gender or "").strip()
        if not gender_norm or gender_norm.lower() == "none":
            sex_value = "unknown"
        else:
            # Normalise a few common variants while keeping free-form
            # strings intact for anything else.
            low = gender_norm.lower()
            if low in {"m", "male"}:
                sex_value = "male"
            elif low in {"f", "female"}:
                sex_value = "female"
            else:
                sex_value = gender_norm

        raw_smoker = str(core.get("smoker_class")) if "smoker_class" in core else ""
        smoker_norm = (raw_smoker or "").strip()
        if not smoker_norm or smoker_norm.lower() == "none":
            smoker_value = "unknown"
        else:
            smoker_value = smoker_norm

        # Objective checks (intentionally simple for POC):
        #  - no positive death benefit after the level period
        #  - death benefit during the level period is reasonably close to
        #    the face amount when non-zero
        after_term_ok = True
        during_term_ok = True
        for year, db in zip(years, death_benefits):
            try:
                y = int(year)
                dbv = float(db or 0.0)
            except (TypeError, ValueError):
                continue
            if y > level_period and dbv > 1e-6:
                after_term_ok = False
            if 1 <= y <= level_period and dbv > 1e-6 and face_amount > 0:
                ratio = dbv / face_amount
                if ratio < 0.95 or ratio > 1.05:
                    during_term_ok = False

        status = "pass" if after_term_ok and during_term_ok else "needs_review"

        premium_mode_raw = core.get("premium_mode") or pas_premium.get("mode") or ""
        premium_mode_norm = str(premium_mode_raw or "").strip().upper() or "UNKNOWN"

        scenario_inputs = {
            "age": age_value,
            "sex": sex_value,
            "smokerClass": smoker_value,
            "termYears": level_period,
            "faceAmount": face_amount,
            "premiumMode": premium_mode_norm,
        }

        behavior_summary_parts: List[str] = []
        if face_amount > 0 and years:
            behavior_summary_parts.append(
                f"Death benefit is approximately level at face amount (${int(face_amount):,}) during the {level_period or len(years)}-year term."
            )
        if not after_term_ok:
            behavior_summary_parts.append("Non-zero death benefit detected after the level term (should be reviewed).")
        if not during_term_ok:
            behavior_summary_parts.append("Death benefit during term deviates materially from face amount (should be reviewed).")
        if not behavior_summary_parts:
            behavior_summary_parts.append("Model behavior appears consistent with a level term pattern for this scenario (POC).")

        # Build a compact projection table for drill-down using the full
        # projection artefact when available. We avoid fabricating fields:
        # when a value is not present in the artefact or derivable from
        # stored inputs, we leave it null so the UI can render "not
        # available" or omit the column.
        full_proj = data.get("projection") or {}
        proj_years = full_proj.get("years") or years or []
        proj_db = full_proj.get("death_benefits") or death_benefits or []
        proj_cash = full_proj.get("cash_values") or []
        proj_prem = full_proj.get("expected_premiums") or full_proj.get("premiums") or []

        projection_table: List[Dict[str, Any]] = []
        for idx, y in enumerate(proj_years):
            if y is None:
                continue
            try:
                year_int = int(y)
            except (TypeError, ValueError):
                year_int = y  # keep as-is if it cannot be coerced

            # Attained age is only derivable when we have a numeric
            # issue_age; otherwise we leave it null.
            attained_age: Optional[int] = None
            if isinstance(issue_age, (int, float)) and issue_age > 0 and isinstance(year_int, int):
                attained_age = int(issue_age) + max(0, year_int - 1)

            premium = proj_prem[idx] if idx < len(proj_prem) else None
            dbv = proj_db[idx] if idx < len(proj_db) else None

            # Term / in-force status: only label when level_period is a
            # positive integer; otherwise leave status null.
            status_label: Optional[str] = None
            if isinstance(level_period, int) and level_period > 0 and isinstance(year_int, int):
                if year_int <= level_period:
                    status_label = "in_force_term"
                else:
                    status_label = "post_term"

            row: Dict[str, Any] = {
                "year": year_int,
                "attainedAge": attained_age,
                "premium": premium,
                "deathBenefit": dbv,
                "status": status_label,
            }

            # Include cash value when present in the artefact.
            if idx < len(proj_cash):
                row["cashValue"] = proj_cash[idx]

            projection_table.append(row)

        scenarios.append(
            {
                "id": cfg["id"],
                "name": cfg["name"],
                "inputs": scenario_inputs,
                "expectedBehavior": [
                    f"Flat term coverage for {level_period} years with face amount approximately equal to the death benefit.",
                    "No death benefit after the end of the level term.",
                ],
                "modelBehaviorSummary": " ".join(behavior_summary_parts),
                "status": status,
                # Minimal drill-down data so that every PASS can be
                # explained from the Trust Surface without calling
                # additional endpoints.
                "runId": (rd.get("run") or {}).get("run_id"),
                "projectionKey": proj_key,
                "checks": {
                    "noDeathBenefitAfterTerm": after_term_ok,
                    "deathBenefitApproxFaceDuringTerm": during_term_ok,
                },
                "projection": {
                    "years": years,
                    "deathBenefits": death_benefits,
                },
                "projectionTable": projection_table,
                "ruleIds": ["rule_death_benefit_term", "rule_level_premiums"],
            }
        )

        # Internal premium reconciliation sample based on RunDetail's
        # premium_comparison block.
        prem = rd.get("premium_comparison") or {}
        table_prem = prem.get("table_premium") or {}
        pas = prem.get("pas_premium") or {}
        if table_prem and pas:
            filed = float(table_prem.get("expected_modal_premium") or 0.0)
            model = float(pas.get("modal_premium") or 0.0)
            diff = model - filed
            spot = {
                "age": int(core.get("issue_age") or 0),
                "termYears": level_period,
                "riskClass": str(core.get("risk_class") or ""),
                "faceAmount": face_amount,
                "filedPremium": filed,
                "modelPremium": model,
                "diff": diff,
                "status": "ok" if abs(diff) <= max(0.01, 0.001 * filed) else "mismatch",
            }
            spot_checks.append(spot)
            if spot["status"] == "mismatch":
                exceptions.append({"kind": "premium_mismatch", "details": spot})

    cells_checked = len(spot_checks)
    cells_matched = sum(1 for s in spot_checks if s["status"] == "ok")

    rates = {
        "cellsChecked": cells_checked,
        "cellsMatched": cells_matched,
        "exceptions": exceptions,
        "spotChecks": spot_checks,
    }

    return {"scenarios": scenarios, "rates": rates}


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """Safe field accessor for dicts and Pydantic models.

    Handles both mapping-style objects (with .get) and attribute-style
    objects (e.g. Pydantic BaseModel instances) so validation logic can
    work against either dicts or strongly-typed models.
    """

    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _validate_p12trf_product_definition(
    pd: Optional[ProductDefinitionV1],
    scenarios: List[Dict[str, Any]],
    docs: List[Dict[str, Any]],
    evidence_rows: List[Dict[str, Any]],
    traceability_rules: List[Dict[str, Any]],
    coverage_matrix: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Run deterministic validation checks for the P12TRF ProductDefinition.

    This is intentionally conservative and P12TRF-specific. It does not
    attempt to infer missing information; instead it reports explicit
    pass/warning/fail statuses for a small set of sanity checks.
    """

    if pd is None:
        return None

    checks: List[Dict[str, Any]] = []

    def add_check(cid: str, label: str, status: str, message: str) -> None:
        checks.append({"id": cid, "label": label, "status": status, "message": message})

    # Scenario vs ProductDefinition dimensionality.
    issue_min = pd.issue_age_min
    issue_max = pd.issue_age_max
    ages: List[int] = []
    terms: List[int] = []
    smokers: List[str] = []
    risks: List[str] = []
    modes: List[str] = []
    faces: List[float] = []

    for s in scenarios:
        inp = s.get("inputs") or {}
        age = inp.get("age")
        try:
            if isinstance(age, (int, float)):
                ages.append(int(age))
        except Exception:
            pass
        term = inp.get("termYears")
        try:
            if isinstance(term, (int, float)):
                terms.append(int(term))
        except Exception:
            pass
        sc = inp.get("smokerClass")
        if isinstance(sc, str) and sc.strip():
            smokers.append(sc.strip())
        rc = inp.get("riskClass")
        if isinstance(rc, str) and rc.strip():
            risks.append(rc.strip())
        pm = inp.get("premiumMode")
        if isinstance(pm, str) and pm.strip():
            modes.append(pm.strip().upper())
        fa = inp.get("faceAmount")
        try:
            if isinstance(fa, (int, float)):
                faces.append(float(fa))
        except Exception:
            pass

    # Age bounds.
    if not ages or issue_min is None or issue_max is None:
        add_check(
            "scenario_age_bounds",
            "Scenario ages within ProductDefinition issue age bounds",
            "warning",
            "Issue age bounds or scenario ages are missing; check skipped.",
        )
    else:
        min_age = min(ages)
        max_age = max(ages)
        if min_age < issue_min or max_age > issue_max:
            add_check(
                "scenario_age_bounds",
                "Scenario ages within ProductDefinition issue age bounds",
                "fail",
                f"Scenario ages {min_age}–{max_age} fall outside {issue_min}–{issue_max}.",
            )
        else:
            add_check(
                "scenario_age_bounds",
                "Scenario ages within ProductDefinition issue age bounds",
                "pass",
                f"All scenario ages are within {issue_min}–{issue_max}.",
            )

    # Term periods.
    pd_terms = set(pd.term_periods or [])
    scen_terms = set(terms)
    if not pd_terms or not scen_terms:
        add_check(
            "scenario_term_periods",
            "Scenario term periods within ProductDefinition term periods",
            "warning",
            "Term periods missing from ProductDefinition or scenarios; check skipped.",
        )
    else:
        extra_terms = sorted(t for t in scen_terms if t not in pd_terms)
        if extra_terms:
            add_check(
                "scenario_term_periods",
                "Scenario term periods within ProductDefinition term periods",
                "fail",
                f"Scenario term periods {extra_terms} are not listed in ProductDefinition term periods {sorted(pd_terms)}.",
            )
        else:
            add_check(
                "scenario_term_periods",
                "Scenario term periods within ProductDefinition term periods",
                "pass",
                f"All scenario term periods are within ProductDefinition term periods {sorted(pd_terms)}.",
            )

    # Smoker classes.
    pd_smokers = set(pd.smoker_classes or [])
    scen_smokers = set(smokers)
    if not pd_smokers or not scen_smokers:
        add_check(
            "scenario_smoker_classes",
            "Scenario smoker classes within ProductDefinition smoker classes",
            "warning",
            "Smoker classes missing from ProductDefinition or scenarios; check skipped.",
        )
    else:
        extra_sc = sorted(s for s in scen_smokers if s not in pd_smokers)
        if extra_sc:
            add_check(
                "scenario_smoker_classes",
                "Scenario smoker classes within ProductDefinition smoker classes",
                "fail",
                f"Scenario smoker classes {extra_sc} are not listed in ProductDefinition smoker classes {sorted(pd_smokers)}.",
            )
        else:
            add_check(
                "scenario_smoker_classes",
                "Scenario smoker classes within ProductDefinition smoker classes",
                "pass",
                f"All scenario smoker classes are within ProductDefinition smoker classes {sorted(pd_smokers)}.",
            )

    # Risk classes.
    pd_risks = set(pd.risk_classes or [])
    scen_risks = set(risks)
    if not pd_risks or not scen_risks:
        add_check(
            "scenario_risk_classes",
            "Scenario risk classes within ProductDefinition risk classes",
            "warning",
            "Risk classes missing from ProductDefinition or scenarios; check skipped.",
        )
    else:
        extra_rc = sorted(r for r in scen_risks if r not in pd_risks)
        if extra_rc:
            add_check(
                "scenario_risk_classes",
                "Scenario risk classes within ProductDefinition risk classes",
                "fail",
                f"Scenario risk classes {extra_rc} are not listed in ProductDefinition risk classes {sorted(pd_risks)}.",
            )
        else:
            add_check(
                "scenario_risk_classes",
                "Scenario risk classes within ProductDefinition risk classes",
                "pass",
                f"All scenario risk classes are within ProductDefinition risk classes {sorted(pd_risks)}.",
            )

    # Premium modes.
    pd_modes = set(m.upper() for m in (pd.premium_modes or []))
    scen_modes = set(modes)
    if not pd_modes or not scen_modes:
        add_check(
            "scenario_premium_modes",
            "Scenario premium modes within ProductDefinition premium modes",
            "warning",
            "Premium modes missing from ProductDefinition or scenarios; check skipped.",
        )
    else:
        extra_modes = sorted(m for m in scen_modes if m not in pd_modes)
        if extra_modes:
            add_check(
                "scenario_premium_modes",
                "Scenario premium modes within ProductDefinition premium modes",
                "fail",
                f"Scenario premium modes {extra_modes} are not listed in ProductDefinition premium modes {sorted(pd_modes)}.",
            )
        else:
            add_check(
                "scenario_premium_modes",
                "Scenario premium modes within ProductDefinition premium modes",
                "pass",
                f"All scenario premium modes are within ProductDefinition premium modes {sorted(pd_modes)}.",
            )

    # Face amount bounds.
    fa_min = pd.face_amount_min
    fa_max = pd.face_amount_max
    if not faces or fa_min is None or fa_max is None:
        add_check(
            "scenario_face_amount_bounds",
            "Scenario face amounts within ProductDefinition face amount range",
            "warning",
            "Face amounts or ProductDefinition face amount range missing; check skipped.",
        )
    else:
        min_f = min(faces)
        max_f = max(faces)
        if min_f < fa_min or max_f > fa_max:
            add_check(
                "scenario_face_amount_bounds",
                "Scenario face amounts within ProductDefinition face amount range",
                "fail",
                f"Scenario face amounts {min_f}–{max_f} fall outside {fa_min}–{fa_max}.",
            )
        else:
            add_check(
                "scenario_face_amount_bounds",
                "Scenario face amounts within ProductDefinition face amount range",
                "pass",
                f"All scenario face amounts are within {fa_min}–{fa_max}.",
            )

    # Evidence references.
    doc_paths_pd = { _field(d, "document_path") for d in (pd.source_documents or []) if _field(d, "document_path") }
    doc_paths_docs = { _field(d, "object_path") for d in docs if _field(d, "object_path") }
    doc_paths_all = {p for p in (doc_paths_pd | doc_paths_docs) if p}

    missing_doc_path = 0
    missing_doc_object = 0
    missing_rule = 0
    missing_page_ref = 0

    rule_ids = {r.get("id") for r in traceability_rules if r.get("id")}

    for ev in pd.evidence_refs or []:
        dp = ev.document_path
        if not dp:
            missing_doc_path += 1
        elif dp not in doc_paths_all:
            missing_doc_object += 1
        if ev.rule_id not in rule_ids:
            missing_rule += 1
        if not ev.page_reference:
            missing_page_ref += 1

    # Evidence: document_path presence.
    if missing_doc_path == 0:
        add_check(
            "evidence_document_paths",
            "Evidence refs have document_path",
            "pass",
            "All evidence refs include a document_path.",
        )
    else:
        add_check(
            "evidence_document_paths",
            "Evidence refs have document_path",
            "fail",
            f"{missing_doc_path} evidence ref(s) are missing document_path.",
        )

    # Evidence: document_path resolves.
    if missing_doc_object == 0:
        add_check(
            "evidence_document_resolves",
            "Evidence document paths resolve to uploaded/source documents",
            "pass",
            "All evidence document paths resolve to known source or uploaded documents.",
        )
    else:
        add_check(
            "evidence_document_resolves",
            "Evidence document paths resolve to uploaded/source documents",
            "fail",
            f"{missing_doc_object} evidence ref(s) reference unknown document_path values.",
        )

    # Evidence: rule IDs.
    if missing_rule == 0:
        add_check(
            "evidence_rule_ids",
            "Evidence refs point at known traceability rule IDs",
            "pass",
            "All evidence refs reference known traceability rules.",
        )
    else:
        add_check(
            "evidence_rule_ids",
            "Evidence refs point at known traceability rule IDs",
            "fail",
            f"{missing_rule} evidence ref(s) reference unknown rule IDs.",
        )

    # Evidence: page_reference.
    if missing_page_ref == 0:
        add_check(
            "evidence_page_reference",
            "Evidence refs include page_reference when available",
            "pass",
            "All evidence refs include a page_reference.",
        )
    else:
        add_check(
            "evidence_page_reference",
            "Evidence refs include page_reference when available",
            "warning",
            f"{missing_page_ref} evidence ref(s) are missing page_reference.",
        )

    # Coverage matrix consistency.
    covered_ok = True
    gap_ok = True
    partial_ok = True

    for row in coverage_matrix or []:
        status = (row.get("status") or "").lower()
        ev = (row.get("evidence") or "").strip()
        model_support = (row.get("modelSupport") or "").strip()

        if status == "covered" and not ev:
            covered_ok = False
        if status == "gap" and model_support and "not currently modeled" not in model_support.lower():
            gap_ok = False
        if status == "partial" and not (ev or model_support):
            partial_ok = False

    add_check(
        "coverage_covered_has_evidence",
        "Covered coverageMatrix rows have evidence",
        "pass" if covered_ok else "fail",
        "All covered coverageMatrix rows include evidence." if covered_ok else "At least one covered row is missing evidence.",
    )
    add_check(
        "coverage_gap_not_fully_modeled",
        "Gap coverageMatrix rows are not described as fully modeled",
        "pass" if gap_ok else "fail",
        "All gap rows are described as not currently modeled." if gap_ok else "At least one gap row is described as fully modeled.",
    )
    add_check(
        "coverage_partial_has_reason",
        "Partial coverageMatrix rows include an explicit reason",
        "pass" if partial_ok else "warning",
        "All partial rows include model support or evidence text." if partial_ok else "Some partial rows lack an explicit reason.",
    )

    # Lineage presence.
    ln = getattr(pd, "lineage", None)
    if ln is None:
        add_check(
            "lineage_present",
            "ProductDefinition lineage (build metadata) present",
            "warning",
            "No lineage present; ProductDefinition builder may not have been run.",
        )
    else:
        missing_bits: List[str] = []
        if not ln.generatedAt:
            missing_bits.append("generatedAt")
        if not ln.generatorVersion:
            missing_bits.append("generatorVersion")
        src = ln.sources or {}
        for key in ("documents", "evidence", "scenarios"):
            if key not in src:
                missing_bits.append(f"sources.{key}")
        if missing_bits:
            add_check(
                "lineage_present",
                "ProductDefinition lineage (build metadata) present",
                "warning",
                "Missing lineage fields: " + ", ".join(sorted(missing_bits)),
            )
        else:
            add_check(
                "lineage_present",
                "ProductDefinition lineage (build metadata) present",
                "pass",
                "Lineage metadata present for ProductDefinition build.",
            )

    # Overall status.
    status_counts = {"pass": 0, "warning": 0, "fail": 0}
    for c in checks:
        st = (c.get("status") or "").lower()
        if st in status_counts:
            status_counts[st] += 1

    overall_status = "pass"
    if status_counts["fail"] > 0:
        overall_status = "fail"
    elif status_counts["warning"] > 0:
        overall_status = "warning"

    return {
        "status": overall_status,
        "checks": checks,
        "summary": status_counts,
    }


def _build_p12trf_scenario_validation(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive a deterministic scenario validation summary for P12TRF.

    This inspects the existing Scenario Evidence block (projection,
    checks, ruleIds, and projectionTable) and emits a flat list of
    checks that can be rendered on the Trust Surface without additional
    backend calls.

    Overall status is derived from the most severe check status:

    - ``fail`` if any check fails
    - ``warning`` if no failures but at least one warning
    - ``pass`` otherwise
    """

    checks: List[Dict[str, Any]] = []
    summary = {"pass": 0, "warning": 0, "fail": 0}

    def _add_check(
        scenario_id: str,
        suffix: str,
        label: str,
        status: str,
        message: str,
    ) -> None:
        status_norm = (status or "").strip().lower() or "warning"
        if status_norm not in {"pass", "warning", "fail"}:
            status_norm = "warning"
        checks.append(
            {
                "id": f"scenario_{scenario_id}_{suffix}",
                "scenarioId": scenario_id,
                "label": label,
                "status": status_norm,
                "message": message,
            }
        )
        summary[status_norm] += 1

    for scen in scenarios or []:
        sid = str((scen.get("id") or "").strip() or "unknown")
        inputs = scen.get("inputs") or {}
        term_years = inputs.get("termYears")
        try:
            term_years_int = int(term_years) if term_years is not None else None
        except (TypeError, ValueError):
            term_years_int = None

        proj = scen.get("projection") or {}
        years = list(proj.get("years") or [])
        proj_table = list(scen.get("projectionTable") or [])
        rule_ids = list(scen.get("ruleIds") or [])

        # Projection basics: data presence, non-negative premiums and
        # death benefits, basic year continuity, and traceability rule IDs.
        projection_issue: Optional[str] = None

        if not years or not proj_table:
            projection_issue = "Projection data is missing or incomplete for this scenario."
            proj_status = "fail"
        else:
            # Non-negative premiums and death benefits.
            neg_prem = False
            neg_db = False
            for row in proj_table:
                p = row.get("premium")
                if isinstance(p, (int, float)) and p < -1e-9:
                    neg_prem = True
                    break
            for row in proj_table:
                dbv = row.get("deathBenefit")
                if isinstance(dbv, (int, float)) and dbv < -1e-9:
                    neg_db = True
                    break

            missing_years = False
            int_years: List[int] = []
            for y in years:
                try:
                    int_years.append(int(y))
                except (TypeError, ValueError):
                    # Non-integer years are treated as a warning rather
                    # than a hard failure.
                    missing_years = True
            if int_years:
                int_years_sorted = sorted(set(int_years))
                expected = list(range(int_years_sorted[0], int_years_sorted[-1] + 1))
                if int_years_sorted != expected:
                    missing_years = True

            missing_rules = not rule_ids

            if neg_db:
                projection_issue = "Negative death benefit values detected in projection rows."
                proj_status = "fail"
            elif neg_prem:
                projection_issue = "Negative premium values detected in projection rows."
                proj_status = "fail"
            elif missing_years:
                projection_issue = "Projection years appear to have gaps or non-integer entries."
                proj_status = "warning"
            elif missing_rules:
                projection_issue = "No traceability ruleIds recorded for this scenario."
                proj_status = "warning"
            else:
                projection_issue = "Projection data, values, and years look structurally consistent for this scenario."
                proj_status = "pass"

        _add_check(
            sid,
            "projection_basics",
            "Projection data and numeric sanity",
            proj_status,
            projection_issue or "Projection data could not be evaluated.",
        )

        # Level term death benefit behaviour – reuse the per-scenario
        # objective checks that already compare the projection against
        # the face amount and level term.
        scen_checks = scen.get("checks") or {}
        after_term_ok = bool(scen_checks.get("noDeathBenefitAfterTerm")) if scen_checks is not None else None
        during_term_ok = bool(scen_checks.get("deathBenefitApproxFaceDuringTerm")) if scen_checks is not None else None

        if after_term_ok and during_term_ok:
            lt_status = "pass"
            lt_message = (
                "Death benefit remains positive during the level term and drops after term as expected."
            )
        elif not after_term_ok:
            lt_status = "fail"
            lt_message = (
                "Non-zero death benefit persists after the level term; review scenario outputs before approving."
            )
        elif not during_term_ok:
            lt_status = "warning"
            lt_message = (
                "Death benefit during the level term deviates materially from the face amount; review before approving."
            )
        else:
            lt_status = "warning"
            lt_message = (
                "Unable to confirm level-term death benefit behaviour from stored checks; review projection shape manually."
            )

        _add_check(
            sid,
            "level_term_death_benefit",
            "Death benefit behavior during/after level term",
            lt_status,
            lt_message,
        )

        # Cash value – for the P12TRF term product we do not expect a
        # surrender value; any non-zero cash value is treated as a
        # warning so the actuary can confirm that it is an internal
        # metric rather than a contractual value.
        has_nonzero_cash = False
        for row in proj_table:
            cv = row.get("cashValue")
            if isinstance(cv, (int, float)) and abs(cv) > 1e-9:
                has_nonzero_cash = True
                break

        if has_nonzero_cash:
            cv_status = "warning"
            cv_message = (
                "Non-zero cash value is present for this P12TRF term scenario; treat as an internal metric and review before relying on it."
            )
        else:
            cv_status = "pass"
            cv_message = "No cash value present for this term scenario (expected for P12TRF)."

        _add_check(
            sid,
            "cash_value_term_product",
            "Cash value treatment for term product",
            cv_status,
            cv_message,
        )

    # Derive the overall status from the summary counts.
    if summary["fail"] > 0:
        overall_status = "fail"
    elif summary["warning"] > 0:
        overall_status = "warning"
    else:
        overall_status = "pass"

    return {
        "status": overall_status,
        "summary": summary,
        "checks": checks,
    }


def _build_decision_risk(decision: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Derive a compact risk summary for a PMR decision.

    This is intentionally deterministic and based only on the immutable
    snapshot fields stored with each decision row. It does not perform
    any additional I/O or re-validation work.

    Status precedence:
    - ``fail`` when any failing condition is present
    - ``warning`` when no failures but at least one warning condition
    - ``incomplete`` when required bundle/snapshot fields are missing
    - ``clean`` only when none of the above apply
    """

    if not isinstance(decision, dict):
        return None

    reasons: List[str] = []

    # Core snapshot fields.
    sv_status = str((decision.get("scenario_validation_status") or "")).strip().lower()
    validation_status = str((decision.get("validation_status") or "")).strip().lower()

    try:
        validation_fail_count = int(decision.get("validation_fail_count") or 0)
    except Exception:
        validation_fail_count = 0
    try:
        validation_warning_count = int(decision.get("validation_warning_count") or 0)
    except Exception:
        validation_warning_count = 0
    try:
        coverage_gap_count = int(decision.get("coverage_gap_count") or 0)
    except Exception:
        coverage_gap_count = 0

    bundle_path = decision.get("bundle_path")
    bundle_hash = decision.get("bundle_hash")
    pd_hash = decision.get("product_definition_hash")
    build_hash = decision.get("build_report_hash")
    coverage_hash = decision.get("coverage_matrix_hash")
    validation_hash = decision.get("validation_snapshot_hash")

    has_bundle_meta = bool(bundle_path and bundle_hash)
    has_pd = bool(pd_hash)
    has_build = bool(build_hash)
    has_coverage = bool(coverage_hash)
    has_validation = bool(validation_hash)

    missing_fields: List[str] = []
    if not has_bundle_meta:
        if not bundle_path:
            missing_fields.append("evidence bundle path")
        if not bundle_hash:
            missing_fields.append("evidence bundle hash")
    if not has_pd:
        missing_fields.append("product-definition.json hash")
    if not has_build:
        missing_fields.append("build-report.json hash")
    if not has_coverage:
        missing_fields.append("coverage-matrix.json hash")
    if not has_validation:
        missing_fields.append("validation-report.json hash")

    # Fail-level conditions.
    fail_flags: List[str] = []
    if sv_status == "fail":
        fail_flags.append("scenario_validation_fail")
        reasons.append("Scenario validation status was fail at decision time.")
    if validation_fail_count > 0:
        fail_flags.append("validation_failures")
        if validation_fail_count == 1:
            reasons.append("ProductDefinition validation had 1 failing check at decision time.")
        else:
            reasons.append(
                f"ProductDefinition validation had {validation_fail_count} failing checks at decision time."
            )

    # Warning-level conditions.
    warning_flags: List[str] = []
    if sv_status == "warning":
        warning_flags.append("scenario_validation_warning")
        reasons.append("Scenario validation status was warning at decision time.")
    if validation_status == "warning":
        warning_flags.append("validation_status_warning")
        reasons.append("ProductDefinition validation status was warning at decision time.")
    if validation_warning_count > 0:
        warning_flags.append("validation_warnings")
        if validation_warning_count == 1:
            reasons.append("ProductDefinition validation had 1 warning at decision time.")
        else:
            reasons.append(
                f"ProductDefinition validation had {validation_warning_count} warnings at decision time."
            )
    if coverage_gap_count > 0:
        warning_flags.append("coverage_gaps")
        if coverage_gap_count == 1:
            reasons.append("Coverage matrix had 1 gap at decision time.")
        else:
            reasons.append(f"Coverage matrix had {coverage_gap_count} gaps at decision time.")

    # Incomplete semantics are based on missing bundle/snapshot metadata.
    incomplete = bool(missing_fields)
    if incomplete:
        missing_desc = ", ".join(sorted(missing_fields))
        reasons.append(f"Evidence bundle or snapshot metadata is incomplete: missing {missing_desc}.")

    # Positive signal when everything we expect is present.
    if has_bundle_meta and has_pd and has_build and has_coverage and has_validation:
        reasons.append("Evidence bundle exists and is hash-verifiable.")

    # Pick overall status with clear precedence.
    if fail_flags:
        status = "fail"
    elif warning_flags:
        status = "warning"
    elif incomplete:
        status = "incomplete"
    else:
        status = "clean"
        if not reasons:
            reasons.append("No validation, coverage, or scenario issues detected at decision time.")

    return {
        "status": status,
        "reasons": reasons,
    }


def _build_decision_timeline(decision_history: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Build a simple chronological decision timeline for the PMR Trust Surface.

    The severity ordering for decisionRisk.status is:

        clean < warning < incomplete < fail

    where *fail* is treated as strictly worse than *incomplete* to
    reflect an explicit model or validation failure.
    """

    if not isinstance(decision_history, list) or not decision_history:
        return None

    # Normalise decisions into a working list and sort oldest -> newest
    # using created_at when available, otherwise by id.
    def _sort_key(row: Dict[str, Any]) -> Any:
        ts = row.get("created_at") or ""
        if isinstance(ts, str) and ts:
            try:
                return _parse_iso8601_timestamp(ts) or ts
            except Exception:
                return ts
        return row.get("id") or 0

    rows = [r for r in decision_history if isinstance(r, dict)]
    if not rows:
        return None
    rows.sort(key=_sort_key)

    def _risk_status(row: Dict[str, Any]) -> str:
        dr = row.get("decisionRisk") or {}
        status = dr.get("status") if isinstance(dr, dict) else None
        if not isinstance(status, str) or not status:
            return "unknown"
        return status.lower()

    severity_order = {
        "clean": 0,
        "warning": 1,
        "incomplete": 2,
        "fail": 3,
    }

    def _severity(status: str) -> int:
        return severity_order.get(status.lower(), 1)

    points: List[Dict[str, Any]] = []
    clean_count = 0
    warning_count = 0
    incomplete_count = 0
    fail_count = 0

    for row in rows:
        status = _risk_status(row)
        if status == "clean":
            clean_count += 1
        elif status == "warning":
            warning_count += 1
        elif status == "incomplete":
            incomplete_count += 1
        elif status == "fail":
            fail_count += 1

        bundle_present = bool(row.get("bundle_path") and row.get("bundle_hash"))

        points.append(
            {
                "id": row.get("id"),
                "createdAt": row.get("created_at"),
                "decision": row.get("decision"),
                "reviewer": row.get("reviewer"),
                "riskStatus": status,
                "scenarioValidationStatus": row.get("scenario_validation_status"),
                "productDefinitionValidationStatus": row.get("validation_status"),
                "coverageGapCount": row.get("coverage_gap_count") or 0,
                "bundlePresent": bundle_present,
                "comments": row.get("comments"),
            }
        )

    latest_point = points[-1]
    latest_risk_status = latest_point.get("riskStatus") or "unknown"

    summary = {
        "latestRiskStatus": latest_risk_status,
        "decisionCount": len(points),
        "cleanCount": clean_count,
        "warningCount": warning_count,
        "failCount": fail_count,
        "incompleteCount": incomplete_count,
    }

    transitions: List[Dict[str, Any]] = []
    for prev, curr in zip(points, points[1:]):
        prev_status = str(prev.get("riskStatus") or "unknown").lower()
        curr_status = str(curr.get("riskStatus") or "unknown").lower()
        prev_sev = _severity(prev_status)
        curr_sev = _severity(curr_status)

        if curr_sev < prev_sev:
            change = "improved"
            reason = f"Decision risk changed from {prev_status} to {curr_status}."
        elif curr_sev > prev_sev:
            change = "regressed"
            reason = f"Decision risk changed from {prev_status} to {curr_status}."
        else:
            change = "unchanged"
            reason = f"Decision risk stayed {prev_status}."

        transitions.append(
            {
                "fromDecisionId": prev.get("id"),
                "toDecisionId": curr.get("id"),
                "change": change,
                "reason": reason,
            }
        )

    return {
        "points": points,
        "summary": summary,
        "transitions": transitions,
    }


@app.get("/api/products")
def api_products() -> Dict[str, Any]:
    """Return a simple product catalog for the dashboard.

    Uses the static product registry as the source of truth and enriches
    implemented products (currently P12TRF only) with PMR state.
    """

    products: List[Dict[str, Any]] = []

    pmr: Optional[Dict[str, Any]] = None
    try:
        # Only load the P12TRF PMR snapshot once; other products either do
        # not have a review yet or will be wired up in future items.
        pmr = api_product_model_review_p12trf()
    except Exception:
        pmr = None

    for entry in _PRODUCT_REGISTRY:
        code = entry.get("productCode")
        name = entry.get("productName")
        status = entry.get("status") or "unknown"
        code_norm = (code or "").strip().upper()
        builder = _get_product_model_review_builder(code_norm)
        builder_registered = builder is not None
        review_endpoint: Optional[str]
        if status == "implemented" and code_norm:
            review_endpoint = f"/api/product-model-review/{code_norm}"
        else:
            review_endpoint = None

        if code_norm == "P12TRF" and status == "implemented" and pmr is not None:
            product_block = pmr.get("product") or {}
            review_meta = pmr.get("reviewMeta") or {}
            last_decision = pmr.get("lastDecision") or {}
            review_freshness = pmr.get("reviewFreshness") or {}
            decision_risk = (last_decision.get("decisionRisk") or {}) if isinstance(last_decision, dict) else {}

            products.append(
                {
                    "productCode": product_block.get("code"),
                    "productName": product_block.get("name"),
                    "status": "implemented",
                    "reviewEndpoint": review_endpoint,
                    "builderRegistered": builder_registered,
                    "filingId": review_meta.get("filingId"),
                    "latestGeneration": review_meta.get("currentGeneration"),
                    "latestDecisionId": last_decision.get("id"),
                    "latestDecision": last_decision.get("decision"),
                    "latestRiskStatus": decision_risk.get("status"),
                    "reviewFreshnessStatus": review_freshness.get("status"),
                    "bundlePath": last_decision.get("bundle_path"),
                }
            )
        else:
            products.append(
                {
                    "productCode": code,
                    "productName": name,
                    "status": status,
                    "reviewEndpoint": review_endpoint,
                    "builderRegistered": builder_registered,
                    "filingId": None,
                    "latestGeneration": None,
                    "latestDecisionId": None,
                    "latestDecision": None,
                    "latestRiskStatus": None,
                    "reviewFreshnessStatus": None,
                    "bundlePath": None,
                }
            )

    return {"products": products}


@app.get("/api/products/{product_code}")
def api_product_detail(product_code: str) -> Dict[str, Any]:
    """Return product-level detail for the Product Catalog view.

    Currently this is implemented for P12TRF only but uses a
    product-generic response shape so additional products can be added
    later without breaking consumers.
    """

    cfg = _get_product_config(product_code)
    if cfg is None:
        # Unknown product from the static catalog; still surface a generic
        # product shell so that ad‑hoc product codes can participate in the
        # Product Review / Model Review flows.
        code_norm = (product_code or "").strip().upper()
        status = "unknown"
        cfg = {"productCode": code_norm, "productName": code_norm, "status": status, "reviewEndpoint": None}
    else:
        status = cfg.get("status") or "unknown"
        code_norm = (cfg.get("productCode") or product_code or "").strip().upper()
    builder = _get_product_model_review_builder(code_norm)
    builder_registered = builder is not None
    review_endpoint: Optional[str]
    if status == "implemented" and code_norm:
        review_endpoint = f"/api/product-model-review/{code_norm}"
    else:
        review_endpoint = None

    if status != "implemented" or code_norm != "P12TRF":
        # Known but not yet implemented product: return a friendly shell
        # with no versions/decisions instead of a 404.
        return {
            "product": {
                "productCode": cfg.get("productCode"),
                "productName": cfg.get("productName"),
                "status": status,
                "reviewEndpoint": review_endpoint,
                "builderRegistered": builder_registered,
            },
            "latestVersion": None,
            "versions": [],
            "decisions": [],
            "timeline": None,
            "message": "Product review is not implemented for this product yet.",
        }

    # Implemented P12TRF Product Model Review detail.
    pmr = api_product_model_review_p12trf()
    product_block = pmr.get("product") or {}
    review_meta = pmr.get("reviewMeta") or {}
    review_freshness = pmr.get("reviewFreshness") or {}
    last_decision = pmr.get("lastDecision") or {}
    decision_history = pmr.get("decisionHistory") or []
    decision_timeline = pmr.get("decisionTimeline") or None

    decision_risk = (last_decision.get("decisionRisk") or {}) if isinstance(last_decision, dict) else {}

    latest_version: Optional[Dict[str, Any]] = None
    versions: List[Dict[str, Any]] = []

    version = {
        "generationId": review_meta.get("currentGeneration"),
        "generatedAt": review_meta.get("generatedAt"),
        "filingId": review_meta.get("filingId"),
        "documentCount": review_meta.get("documentCount"),
        "scenarioCount": review_meta.get("scenarioCount"),
        "latestDecisionId": last_decision.get("id"),
        "latestDecisionCreatedAt": last_decision.get("created_at"),
        "riskStatus": decision_risk.get("status"),
        "freshnessStatus": review_freshness.get("status"),
        "bundlePath": last_decision.get("bundle_path"),
    }

    if version.get("generationId") or version.get("filingId"):
        versions.append(version)
        latest_version = version

    decisions: List[Dict[str, Any]] = []
    if isinstance(decision_history, list):
        for row in decision_history:
            if not isinstance(row, dict):
                continue
            dr = row.get("decisionRisk") or {}
            decisions.append(
                {
                    "id": row.get("id"),
                    "createdAt": row.get("created_at"),
                    "decision": row.get("decision"),
                    "reviewer": row.get("reviewer"),
                    "riskStatus": dr.get("status"),
                    "bundlePath": row.get("bundle_path"),
                    "comments": row.get("comments"),
                }
            )

    product_summary = {
        "productCode": product_block.get("code"),
        "productName": product_block.get("name"),
        "filingId": review_meta.get("filingId"),
        "status": "implemented",
        "reviewEndpoint": review_endpoint,
        "builderRegistered": builder_registered,
    }

    return {
        "product": product_summary,
        "latestVersion": latest_version,
        "versions": versions,
        "decisions": decisions,
        "timeline": decision_timeline,
    }


@app.get("/api/product-definition/{product_code}")
def api_get_product_definition(product_code: str, filing_id: str = Query(...)) -> Dict[str, Any]:
    """Return the v1 ProductDefinition artefact for a product+filing, if any.

    For P12TRF, this will seed a minimal artefact into MinIO when one does
    not yet exist, so that the Trust Surface and future tools have a stable
    object to reference.
    """

    pd = _load_or_seed_product_definition(product_code, filing_id)
    if pd is None:
        raise HTTPException(status_code=404, detail="No ProductDefinition available for this product/filing")
    return {"productDefinition": pd.dict()}  # type: ignore[call-arg]


@app.post("/api/product-definition/{product_code}/build")
def api_build_product_definition(product_code: str) -> Dict[str, Any]:
    """Rebuild a ProductDefinition artefact for the current filing context.

    This endpoint is intentionally P12TRF-first and deterministic. It:

    - looks up the current Product Review for the given product,
    - derives the active filing_id,
    - reads filing-scoped documents, evidence, and scenarios, and
    - assembles an enriched ProductDefinitionV1 with lineage metadata.

    The updated ProductDefinition and a build-report.json artefact are
    written to MinIO. Re-running the build overwrites the same keys for
    the product+filing, making this endpoint idempotent.
    """

    code = (product_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="product_code is required")
    if code != "P12TRF":
        raise HTTPException(status_code=400, detail="ProductDefinition builder is only implemented for P12TRF in this MVP")

    rec = get_product_review(code)
    if rec is None:
        raise HTTPException(status_code=400, detail="No Product Review draft found for this product")

    meta = rec.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    review_state = meta.get("review") or {}
    if not isinstance(review_state, dict):
        review_state = {}

    filing_id = review_state.get("filing_id") if isinstance(review_state, dict) else None
    if isinstance(filing_id, str):
        filing_id = filing_id.strip() or None
    if not filing_id:
        raise HTTPException(status_code=400, detail="No filing_id configured on current Product Review")

    # Source inputs for the builder.
    docs = list_product_documents(code, filing_id=filing_id)
    evidence_rows = list_filing_rule_evidence(code, filing_id=filing_id)
    internal_scenarios = review_state.get("scenarios") if isinstance(review_state, dict) else None
    if not isinstance(internal_scenarios, list):
        internal_scenarios = []

    base_def = get_product_definition(code) or _load_p12trf_definition()
    issue_limits = base_def.get("issue_age_limits") or {}
    underwriting = base_def.get("underwriting_classes") or []

    # Dimensionality from scenarios (prefer saved scenarios, fall back to
    # the bundled fixture).
    term_periods: List[int] = []
    risk_classes: List[str] = []
    smoker_classes: List[str] = []
    premium_modes: List[str] = []
    face_amounts: List[float] = []

    scenario_source_count = 0

    def _harvest_from_policy(policy: Dict[str, Any]) -> None:
        nonlocal scenario_source_count
        scenario_source_count += 1
        lp = policy.get("level_period")
        try:
            lp_int = int(lp) if lp is not None else None
        except (TypeError, ValueError):
            lp_int = None
        if lp_int and lp_int > 0:
            term_periods.append(lp_int)

        rc = policy.get("risk_class")
        if isinstance(rc, str) and rc.strip():
            risk_classes.append(rc.strip())

        sc = policy.get("smoker_class")
        if isinstance(sc, str) and sc.strip():
            smoker_classes.append(sc.strip())

        pm = policy.get("premium_mode")
        if isinstance(pm, str) and pm.strip():
            premium_modes.append(pm.strip().upper())

        fa = policy.get("face_amount")
        try:
            fa_val = float(fa) if fa is not None else None
        except (TypeError, ValueError):
            fa_val = None
        if fa_val is not None and fa_val > 0:
            face_amounts.append(fa_val)

    # Prefer saved scenarios from the Product Review.
    if internal_scenarios:
        for s in internal_scenarios:
            if not isinstance(s, dict):
                continue
            policy = s.get("policy") or {}
            if not isinstance(policy, dict):
                continue
            _harvest_from_policy(policy)
    else:
        # Fall back to the P12TRF fixture.
        for s in _default_p12trf_scenarios_for_ui():
            policy = {
                "issue_age": s.get("age"),
                "gender": s.get("sex"),
                "smoker_class": s.get("smokerClass"),
                "risk_class": s.get("riskClass"),
                "face_amount": s.get("faceAmount"),
                "level_period": s.get("levelPeriod"),
                "premium_mode": s.get("premiumMode"),
                "modal_premium": s.get("modalPremium"),
            }
            _harvest_from_policy(policy)

    # Normalise sets.
    def _sorted_unique(values: List[Any]) -> List[Any]:
        seen = set()
        out: List[Any] = []
        for v in values:
            if v in seen:
                continue
            seen.add(v)
            out.append(v)
        try:
            return sorted(out)
        except Exception:
            return out

    term_periods = _sorted_unique(term_periods)
    risk_classes = _sorted_unique(risk_classes)
    smoker_classes = _sorted_unique(smoker_classes)
    premium_modes = _sorted_unique(premium_modes)

    face_min = min(face_amounts) if face_amounts else None
    face_max = max(face_amounts) if face_amounts else None

    pd = ProductDefinitionV1(
        schema_version="product-definition-v1",
        product_code=code,
        filing_id=filing_id,
        coverages=[
            {
                "id": "base_term",
                "name": base_def.get("marketing_name") or f"{code} Term (base)",
                "kind": "base",
                "term_periods": term_periods or [20],
                "notes": "Base term coverage for P12TRF; term periods inferred from scenarios.",
            }
        ],
        issue_age_min=issue_limits.get("min"),
        issue_age_max=issue_limits.get("max"),
        term_periods=term_periods or [20],
        underwriting_classes=list(underwriting),
        risk_classes=risk_classes,
        smoker_classes=smoker_classes,
        premium_modes=premium_modes or ["ANNUAL"],
        face_amount_min=face_min,
        face_amount_max=face_max,
        source_documents=[],
        evidence_refs=[],
        extra={
            "unmodeled_coverages": base_def.get("riders") or [],
        },
    )

    # Attach documents and evidence.
    pd.source_documents = [
        {
            "document_path": str(d.get("object_path")),
            "description": d.get("description"),
            "filing_id": d.get("serff_id") or filing_id,
        }
        for d in docs
        if d.get("object_path")
    ]

    refs: List[Dict[str, Any]] = []
    for ev in evidence_rows:
        rule_id = ev.get("rule_id")
        if rule_id not in {"rule_death_benefit_term", "rule_level_premiums"}:
            continue
        feature_id = "base_term_coverage" if rule_id == "rule_death_benefit_term" else "level_premiums"
        refs.append(
            {
                "feature_id": feature_id,
                "rule_id": rule_id,
                "document_path": ev.get("document_path"),
                "page_reference": ev.get("page_reference"),
            }
        )
    pd.evidence_refs = refs

    # Lineage / build metadata.
    generated_at = datetime.utcnow().isoformat() + "Z"
    generator_version = "v1"

    warnings: List[str] = []
    if not docs:
        warnings.append("no uploaded documents")
    if not evidence_rows:
        warnings.append("no filing rule evidence")
    if not internal_scenarios:
        warnings.append("no saved scenarios; used fixture scenarios instead")
    if not pd.source_documents:
        warnings.append("no source documents linked to ProductDefinition")
    if not pd.evidence_refs:
        warnings.append("no evidence refs linked to ProductDefinition")

    pd.lineage = ProductDefinitionLineage(
        generatedAt=generated_at,
        generatorVersion=generator_version,
        sources={
            "documents": len(docs),
            "evidence": len(evidence_rows),
            "scenarios": scenario_source_count,
        },
        warnings=warnings,
    )

    # Persist ProductDefinition and build-report to MinIO (idempotent).
    minio_client = get_minio_client()
    ensure_bucket(minio_client)
    bucket = get_bucket_name()

    pd_key = _product_definition_object_key(code, filing_id)
    report_key = _product_definition_build_report_key(code, filing_id)

    import io
    import json

    pd_body = json.dumps(pd.dict()).encode("utf-8")  # type: ignore[call-arg]
    report = {
        "productCode": code,
        "filingId": filing_id,
        "generatedAt": generated_at,
        "generatorVersion": generator_version,
        "sources": {
            "documents": len(docs),
            "evidence": len(evidence_rows),
            "scenarios": scenario_source_count,
        },
        "warnings": warnings,
        "summary": pd.summary(),
    }
    report_body = json.dumps(report).encode("utf-8")

    minio_client.put_object(bucket, pd_key, data=io.BytesIO(pd_body), length=len(pd_body), content_type="application/json")
    minio_client.put_object(bucket, report_key, data=io.BytesIO(report_body), length=len(report_body), content_type="application/json")

    return {
        "productCode": code,
        "filingId": filing_id,
        "productDefinition": pd.dict(),
        "buildReport": report,
    }


@app.get("/api/debug/p12trf/scenario-suggestions")
def api_debug_p12trf_scenario_suggestions() -> Dict[str, Any]:
    """Debug helper: show ProductDefinition-driven scenario suggestions.

    This endpoint is **read-only** and does not modify Postgres or MinIO
    state. It is intended to validate the ProductDefinition-driven
    scenario generator in a live environment without disturbing the
    existing P12TRF demo state.
    """

    product_code = "P12TRF"
    rec = get_product_review(product_code)
    meta = (rec or {}).get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    review_state = meta.get("review") or {}
    if not isinstance(review_state, dict):
        review_state = {}

    filing_id = review_state.get("filing_id") if isinstance(review_state, dict) else None
    if isinstance(filing_id, str):
        filing_id = filing_id.strip() or None

    if not filing_id:
        raise HTTPException(status_code=400, detail="No filing_id on current Product Review for P12TRF")

    pd_scenarios = _default_p12trf_scenarios_from_product_definition(product_code, filing_id)
    fixture_scenarios = _default_p12trf_scenarios_for_ui()

    return {
        "productCode": product_code,
        "filingId": filing_id,
        "fromProductDefinition": pd_scenarios,
        "fromFixture": fixture_scenarios,
    }


@app.get("/api/product-model-review/p12trf")
def api_product_model_review_p12trf() -> Dict[str, Any]:
    """Return a Product Model Review payload for P12TRF.

    This endpoint is still POC-focused but now derives key sections from
    real P12TRF assets:

    - Product Scope & Gaps from the P12TRF ProductDefinition
    - Scenario Evidence from actual P12TRF projection runs
    - A small internal rate reconciliation from the current premium logic
    """

    defn = _load_p12trf_definition()
    scope = _build_p12trf_scope(defn)

    # Static traceability rows remain POC text at this stage.
    traceability = {
        "rules": [
            {
                "id": "rule_death_benefit_term",
                "name": "Death benefit during term",
                "filingId": "P12TRF-2020-01 (POC)",
                "page": 22,
                "section": "Death Benefit (POC)",
                "snippet": "If the Insured dies while this policy is in force and before the end of the level term period, we will pay the Face Amount shown on the Policy Schedule.",
                "interpretation": "Pay face amount if death occurs during the level term; no benefit after term expiry.",
                "confidence": "high",
                "reviewStatus": "not_reviewed",
            },
            {
                "id": "rule_level_premiums",
                "name": "Level premiums",
                "filingId": "P12TRF-2020-01 (POC)",
                "page": 12,
                "section": "Annual Premium per $1,000 – Level Term (POC)",
                "snippet": "Annual Premium per $1,000 – 20-Year Level Term.",
                "interpretation": "Premium is level each year; equal to rate per $1,000 times face amount divided by 1,000.",
                "confidence": "high",
                "reviewStatus": "not_reviewed",
            },
        ]
    }

    scen_and_rates = _build_p12trf_scenarios_and_rates()

    # Assumptions and gaps remain mostly static POC hints for now but are
    # clearly labeled as such.
    assumptions = {
        "filed": [],
        "aiProposed": [
            {
                "id": "mortality",
                "name": "Mortality basis",
                "value": "2015 VBT, ANB (POC placeholder)",
                "source": "ai_default",
                "sensitivitySummary": "PV impact is small for reasonable alternatives (POC).",
                "humanApproval": "pending",
            },
            {
                "id": "lapse",
                "name": "Lapse pattern",
                "value": "5% annually after year 3 (POC placeholder)",
                "source": "ai_default",
                "sensitivitySummary": "PV impact is moderate; should be reviewed for production.",
                "humanApproval": "pending",
            },
        ],
    }

    gaps = {
        "missingFeatures": [
            {
                "id": "gap_riders_not_modeled",
                "description": "Optional riders (e.g. waiver of premium, child term) from the ProductDefinition are not yet modeled in this POC.",
                "severity": "medium",
            }
        ],
        "ambiguousLanguage": [],
    }

    product_block = {
        "code": defn.get("product_code", "P12TRF"),
        "name": defn.get("marketing_name", "Term Life (POC)"),
        "definitionId": defn.get("product_definition_id", "term-def-v1-poc"),
    }

    # Optional review metadata: tie the Trust Surface back to the latest
    # Product Review generation when Postgres is configured.
    review_meta: Dict[str, Any] = {
        "filingId": None,
        "currentGeneration": None,
        "generatedAt": None,
        "documentCount": 0,
        "scenarioCount": len(scen_and_rates["scenarios"]),
        "traceableRuleCount": 0,
        "unattributedRuleCount": len(traceability["rules"]),
    }
    documents_payload: List[Dict[str, Any]] = []
    product_definition_summary: Optional[Dict[str, Any]] = None
    product_definition_full: Optional[ProductDefinitionV1] = None
    product_definition_build: Optional[Dict[str, Any]] = None
    product_definition_validation: Optional[Dict[str, Any]] = None
    docs: List[Dict[str, Any]] = []
    evidence_rows: List[Dict[str, Any]] = []
    rules: List[Dict[str, Any]] = traceability.get("rules", []) or []
    coverage_matrix: List[Dict[str, Any]] = []
    try:
        rec = get_product_review(product_block["code"])
        meta = (rec or {}).get("metadata") or {}
        filing_id: Optional[str] = None
        if isinstance(meta, dict):
            rs = meta.get("review") or {}
            if isinstance(rs, dict):
                filing_id = rs.get("filing_id")
                review_meta["currentGeneration"] = rs.get("current_generation")
                review_meta["generatedAt"] = rs.get("generated_at")
        review_meta["filingId"] = filing_id

        # Attach scenario-level metadata (purpose, dimensions, source)
        # from the Product Review draft to the Scenario Evidence block
        # so that the Trust Surface can explain why each scenario exists.
        internal_scenarios = None
        if isinstance(meta, dict):
            rs2 = meta.get("review") or {}
            if isinstance(rs2, dict):
                internal_scenarios = rs2.get("scenarios")
        meta_by_id: Dict[str, Dict[str, Any]] = {}
        if isinstance(internal_scenarios, list):
            for s in internal_scenarios:
                if not isinstance(s, dict):
                    continue
                sid = str(s.get("id") or "").strip()
                if not sid:
                    continue
                meta_by_id[sid] = {
                    "purpose": s.get("purpose"),
                    "dimensionsExercised": s.get("dimensions_exercised"),
                    "source": s.get("source"),
                }

        for scen in scen_and_rates["scenarios"]:
            sid = scen.get("id")
            if not isinstance(sid, str):
                continue
            extra = meta_by_id.get(sid)
            if not extra:
                continue
            for key, value in extra.items():
                if value is not None:
                    scen[key] = value

        # Load or seed a ProductDefinition artefact for this (product, filing)
        # pair so that the Trust Surface can show a concise product
        # dimensionality summary.
        if filing_id:
            try:
                pd = _load_or_seed_product_definition(product_block["code"], filing_id)
            except Exception:
                pd = None
            if pd is not None:
                product_definition_full = pd
                product_definition_summary = pd.summary()

        docs = list_product_documents(product_block["code"], filing_id=filing_id)
        review_meta["documentCount"] = len(docs)
        for d in docs:
            documents_payload.append(
                {
                    "id": d.get("id"),
                    "kind": d.get("kind"),
                    "description": d.get("description"),
                    "objectPath": d.get("object_path"),
                    "createdAt": d.get("created_at"),
                    "filingId": d.get("serff_id") or filing_id,
                }
            )

        # Load any filing rule evidence for this product/filing and attach
        # it to the static traceability rules so the UI can render
        # document-linked evidence without changing rule IDs.
        evidence_rows = list_filing_rule_evidence(product_block["code"], filing_id=filing_id)
        by_rule: Dict[str, List[Dict[str, Any]]] = {}
        for ev in evidence_rows:
            rid = ev.get("rule_id")
            if not isinstance(rid, str) or not rid:
                continue
            by_rule.setdefault(rid, []).append(
                {
                    "id": ev.get("id"),
                    "documentPath": ev.get("document_path"),
                    "pageReference": ev.get("page_reference"),
                    "sourceSnippet": ev.get("source_snippet"),
                    "aiInterpretation": ev.get("ai_interpretation"),
                    "confidence": ev.get("confidence"),
                }
            )

        rules = traceability.get("rules", []) or []
        traceable = 0
        for rule in rules:
            rid = rule.get("id")
            ev_list = by_rule.get(rid, [])
            if ev_list:
                traceable += 1
            rule["evidence"] = ev_list
        review_meta["traceableRuleCount"] = traceable
        review_meta["unattributedRuleCount"] = max(0, len(rules) - traceable)

        # Build a simple coverage matrix from the ProductDefinition, model
        # behaviour, and available document-linked evidence. This is
        # intentionally P12TRF-specific and conservative: dimensions
        # without direct filing evidence are marked "partial", not
        # silently treated as fully covered.
        if product_definition_full is not None:
            pd = product_definition_full

            def _row(feature: str, pd_value: str, model: str, evidence_text: str, status: str) -> Dict[str, Any]:
                return {
                    "feature": feature,
                    "productDefinitionValue": pd_value,
                    "modelSupport": model,
                    "evidence": evidence_text,
                    "status": status,
                }

            # Map evidence rows by rule_id for quick lookup.
            ev_by_rule: Dict[str, List[Dict[str, Any]]] = {}
            for ev in evidence_rows:
                rid2 = ev.get("rule_id")
                if not isinstance(rid2, str) or not rid2:
                    continue
                ev_by_rule.setdefault(rid2, []).append(ev)

            def _evidence_for(rule_id: str) -> str:
                items = ev_by_rule.get(rule_id) or []
                parts: List[str] = []
                for ev in items:
                    doc_path = ev.get("document_path") or ""
                    page = ev.get("page_reference") or ""
                    frag = ev.get("source_snippet") or ""
                    bits = [f"rule={rule_id}"]
                    if page:
                        bits.append(f"page={page}")
                    if doc_path:
                        bits.append(f"doc={doc_path}")
                    if frag:
                        bits.append("snippet=…")
                    parts.append("; ".join(bits))
                return " | ".join(parts) if parts else "(no direct filing evidence)"

            # Base term coverage.
            base_cov_names = [c.name for c in (pd.coverages or [])]
            base_desc = ", ".join(base_cov_names) if base_cov_names else "(none)"
            cov_ev = _evidence_for("rule_death_benefit_term")
            coverage_matrix.append(
                _row(
                    "Base term coverage",
                    base_desc,
                    "Modeled via P12TRF term DSL and scenario projections.",
                    cov_ev,
                    "covered" if ev_by_rule.get("rule_death_benefit_term") else "partial",
                )
            )

            # Level premiums.
            lvl_ev = _evidence_for("rule_level_premiums")
            coverage_matrix.append(
                _row(
                    "Level premiums",
                    "Premiums defined as level-term table rates (POC).",
                    "Modeled via premium lookup table and scenario projections.",
                    lvl_ev,
                    "covered" if ev_by_rule.get("rule_level_premiums") else "partial",
                )
            )

            # Term periods.
            term_vals = ", ".join(str(t) for t in (pd.term_periods or [])) or "(none)"
            scen_terms = sorted({s.get("inputs", {}).get("termYears") for s in scen_and_rates["scenarios"]})
            scen_terms_str = ", ".join(str(t) for t in scen_terms if t) or "(none)"
            coverage_matrix.append(
                _row(
                    "Term periods",
                    f"Allowed: {term_vals}",
                    f"Scenario terms: {scen_terms_str}",
                    "(no direct filing evidence; inferred from scenarios)",
                    "partial",
                )
            )

            # Issue ages.
            age_min = pd.issue_age_min
            age_max = pd.issue_age_max
            scen_ages = sorted({s.get("inputs", {}).get("age") for s in scen_and_rates["scenarios"]})
            scen_age_str = ", ".join(str(a) for a in scen_ages if a) or "(none)"
            coverage_matrix.append(
                _row(
                    "Issue ages",
                    f"Allowed: {age_min}–{age_max}",
                    f"Scenario ages: {scen_age_str}",
                    "(no direct filing evidence; inferred from scenarios)",
                    "partial",
                )
            )

            # Underwriting / risk classes.
            uw = ", ".join(pd.underwriting_classes or []) or "(none)"
            rc = ", ".join(pd.risk_classes or []) or "(none)"
            coverage_matrix.append(
                _row(
                    "Underwriting / risk classes",
                    f"Underwriting: {uw}; Risk: {rc}",
                    "Scenario set exercises a subset of risk classes.",
                    "(no direct filing evidence; inferred from scenarios)",
                    "partial",
                )
            )

            # Smoker classes.
            sm = ", ".join(pd.smoker_classes or []) or "(none)"
            coverage_matrix.append(
                _row(
                    "Smoker classes",
                    f"ProductDefinition: {sm}",
                    "Scenarios include both non-smoker and smoker cases.",
                    "(no direct filing evidence; inferred from scenarios)",
                    "partial",
                )
            )

            # Premium modes.
            modes = ", ".join(pd.premium_modes or []) or "(none)"
            coverage_matrix.append(
                _row(
                    "Premium modes",
                    f"ProductDefinition: {modes}",
                    "Current scenarios exercise the primary premium mode only.",
                    "(no direct filing evidence; inferred from scenarios)",
                    "partial",
                )
            )

            # Face amount range.
            coverage_matrix.append(
                _row(
                    "Face amount range",
                    f"Allowed: {pd.face_amount_min}–{pd.face_amount_max}",
                    "Scenario set spans low/mid/high face amounts.",
                    "(no direct filing evidence; inferred from scenarios)",
                    "partial",
                )
            )

            # Riders / unmodeled coverages.
            unmodeled = []
            extra = getattr(pd, "extra", {}) or {}
            if isinstance(extra, dict):
                unmodeled = list(extra.get("unmodeled_coverages") or [])
            unmodeled_str = ", ".join(unmodeled) if unmodeled else "(none recorded)"
            coverage_matrix.append(
                _row(
                    "Riders / unmodeled coverages",
                    unmodeled_str,
                    "Not currently modeled in the P12TRF POC.",
                    "(no filing rule evidence wired yet)",
                    "gap",
                )
            )

            # Derive simple coverage status counts for the Review Summary.
            covered = sum(1 for r in coverage_matrix if r.get("status") == "covered")
            partial = sum(1 for r in coverage_matrix if r.get("status") == "partial")
            gaps = sum(1 for r in coverage_matrix if r.get("status") == "gap")
            not_app = sum(1 for r in coverage_matrix if r.get("status") == "not_applicable")
            review_meta["coverageCoveredCount"] = covered
            review_meta["coveragePartialCount"] = partial
            review_meta["coverageGapCount"] = gaps
            review_meta["coverageNotApplicableCount"] = not_app

    except Exception:
        # Best-effort only; Trust Surface must remain robust when Postgres
        # is not configured.
        pass

    # ProductDefinition validation (best-effort, not hidden behind the
    # broader Postgres try/except). When a ProductDefinition exists we
    # always return a non-null validation object, even if a runtime error
    # occurs inside the helper.
    if product_definition_full is not None:
        try:
            product_definition_validation = _validate_p12trf_product_definition(
                product_definition_full,
                scen_and_rates["scenarios"],
                docs,
                evidence_rows,
                rules,
                coverage_matrix,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            # Log the exception so it is visible in pod logs while still
            # returning a deterministic validation payload.
            print(f"ProductDefinition validation runtime error: {exc!r}")
            product_definition_validation = {
                "status": "fail",
                "checks": [
                    {
                        "id": "validation_runtime_error",
                        "label": "ProductDefinition validation runtime error",
                        "status": "fail",
                        "message": str(exc),
                    }
                ],
                "summary": {"pass": 0, "warning": 0, "fail": 1},
            }

        if product_definition_validation is None:
            # Defensive: ensure we never surface a null validation object
            # when a ProductDefinition exists, even if the helper returned
            # an unexpected null.
            product_definition_validation = {
                "status": "fail",
                "checks": [
                    {
                        "id": "validation_runtime_error",
                        "label": "ProductDefinition validation returned null",
                        "status": "fail",
                        "message": "Validation helper returned no result.",
                    }
                ],
                "summary": {"pass": 0, "warning": 0, "fail": 1},
            }

    # ProductDefinition build metadata (when lineage is present).
    if product_definition_full is not None and getattr(product_definition_full, "lineage", None) is not None:  # type: ignore[truthy-function]
        ln = product_definition_full.lineage  # type: ignore[assignment]
        if ln is not None:
            sources = ln.sources or {}
            product_definition_build = {
                "generatedAt": ln.generatedAt,
                "generatorVersion": ln.generatorVersion,
                "documentCount": len(product_definition_full.source_documents or []),
                "evidenceCount": len(product_definition_full.evidence_refs or []),
                "scenarioCount": int(sources.get("scenarios", 0)),
                "warningCount": len(ln.warnings or []),
                "warnings": list(ln.warnings or []),
            }

    # Derive a lightweight progress checklist so the UI can show how
    # complete this review feels from a workflow perspective.
    try:
        last_decision = get_last_product_model_review_decision(product_block["code"])
        decision_history = list_product_model_review_decisions(product_block["code"])
    except Exception:
        last_decision = None
        decision_history = []

    # Derived decision risk summary (clean / warning / fail / incomplete)
    # based on immutable snapshot fields stored with each decision.
    if isinstance(last_decision, dict):
        last_decision["decisionRisk"] = _build_decision_risk(last_decision)
    if isinstance(decision_history, list):
        for row in decision_history:
            if isinstance(row, dict):
                row["decisionRisk"] = _build_decision_risk(row)

    # Chronological decision timeline derived from decisionHistory.
    decision_timeline = _build_decision_timeline(decision_history)

    completed_steps = 0
    total_steps = 6

    filing_ok = bool(review_meta.get("filingId"))
    docs_ok = (review_meta.get("documentCount") or 0) > 0
    scenarios_ok = (review_meta.get("scenarioCount") or 0) > 0
    generation_ok = bool(review_meta.get("currentGeneration"))
    evidence_ok = (review_meta.get("traceableRuleCount") or 0) > 0
    decision_ok = last_decision is not None

    for flag in (filing_ok, docs_ok, scenarios_ok, generation_ok, evidence_ok, decision_ok):
        if flag:
            completed_steps += 1

    review_progress = {
        "filingContextEstablished": filing_ok,
        "documentsUploaded": docs_ok,
        "scenariosConfigured": scenarios_ok,
        "reviewGenerated": generation_ok,
        "ruleEvidencePresent": evidence_ok,
        "finalDecisionRecorded": decision_ok,
        "completedSteps": completed_steps,
        "totalSteps": total_steps,
    }

    # Derive a lightweight freshness view so the UI can highlight when
    # the current Trust Surface may be stale or when the latest decision
    # was made against an older evidence set.
    review_freshness = _build_review_freshness(
        review_meta=review_meta,
        documents=docs,
        product_definition_build=product_definition_build,
        last_decision=last_decision,
    )

    # Deterministic scenario validation so the Trust Surface can expose a
    # simple model-behaviour health signal alongside freshness and
    # ProductDefinition validation.
    scenario_validation = _build_p12trf_scenario_validation(scen_and_rates["scenarios"])

    # Advisory Product Mechanics Graph v0.1: load any curated mechanics
    # set available for this product that links filings ↔ mechanics ↔ DSL.
    # This is intentionally minimal and file-backed and should not break
    # core PMR flows when unavailable. P12TRF is the first product with a
    # populated mechanics fixture.
    try:
        mechanics = load_mechanics_for_product(product_block["code"])
        mechanics_payload = mechanics_to_json(mechanics)
        mechanics_checks = validate_mechanics_against_dsl(product_block["code"])
    except Exception:
        mechanics_payload = []
        mechanics_checks = []

    return {
        "product": product_block,
        "scope": scope,
        "traceability": traceability,
        "rates": scen_and_rates["rates"],
        "scenarios": scen_and_rates["scenarios"],
        "assumptions": assumptions,
        "gaps": gaps,
        "reviewMeta": review_meta,
        "reviewFreshness": review_freshness,
        "scenarioValidation": scenario_validation,
        "documents": documents_payload,
        "lastDecision": last_decision,
        "decisionHistory": decision_history,
        "decisionTimeline": decision_timeline,
        "reviewProgress": review_progress,
        "productMechanics": mechanics_payload,
        "mechanicsValidation": {
            "productCode": product_block["code"],
            "checks": mechanics_checks,
        },
        "productDefinition": product_definition_summary,
        "productDefinitionBuild": product_definition_build,
        "productDefinitionValidation": product_definition_validation,
        "coverageMatrix": coverage_matrix,
    }


ProductModelReviewBuilder = Callable[[], Dict[str, Any]]
ProductRequirementsProvider = Callable[[str], Dict[str, Any]]
ProductDefinitionEvidenceProvider = Callable[[str], Dict[str, Any]]
ProductProjectionEvidenceProvider = Callable[[str], Dict[str, Any]]
ProductIllustrationEvidenceProvider = Callable[[str], Dict[str, Any]]
ProductIllustrationProvider = Callable[[str, Dict[str, Any]], Dict[str, Any]]


_PRODUCT_MODEL_REVIEW_BUILDERS: Dict[str, ProductModelReviewBuilder] = {
    "P12TRF": api_product_model_review_p12trf,
}

_PRODUCT_REQUIREMENTS_PROVIDERS: Dict[str, ProductRequirementsProvider] = {}
_PRODUCT_DEFINITION_EVIDENCE_PROVIDERS: Dict[str, ProductDefinitionEvidenceProvider] = {}
_PRODUCT_PROJECTION_EVIDENCE_PROVIDERS: Dict[str, ProductProjectionEvidenceProvider] = {}
_PRODUCT_ILLUSTRATION_EVIDENCE_PROVIDERS: Dict[str, ProductIllustrationEvidenceProvider] = {}
_ILLUSTRATION_PROVIDERS: Dict[str, ProductIllustrationProvider] = {}


def _get_product_model_review_builder(product_code: str) -> Optional[ProductModelReviewBuilder]:
    """Resolve a Product Model Review builder for the given product code.

    This is intentionally minimal for now: only P12TRF is wired up, but the
    registry shape allows additional products to plug in cleanly once they
    have a PMR implementation.
    """

    code_norm = (product_code or "").strip().upper()
    return _PRODUCT_MODEL_REVIEW_BUILDERS.get(code_norm)


def _get_product_requirements_provider(product_code: str) -> Optional[ProductRequirementsProvider]:
    """Resolve a Filing Requirements provider for the given product code."""

    code_norm = (product_code or "").strip().upper()
    return _PRODUCT_REQUIREMENTS_PROVIDERS.get(code_norm)


def _get_product_definition_evidence_provider(product_code: str) -> Optional[ProductDefinitionEvidenceProvider]:
    """Resolve a ProductDefinition evidence provider for the given product code."""

    code_norm = (product_code or "").strip().upper()
    return _PRODUCT_DEFINITION_EVIDENCE_PROVIDERS.get(code_norm)


def _get_product_projection_evidence_provider(product_code: str) -> Optional[ProductProjectionEvidenceProvider]:
    """Resolve a projection logic evidence provider for the given product code."""

    code_norm = (product_code or "").strip().upper()
    return _PRODUCT_PROJECTION_EVIDENCE_PROVIDERS.get(code_norm)


def _get_product_illustration_evidence_provider(product_code: str) -> Optional[ProductIllustrationEvidenceProvider]:
    """Resolve an illustration comparison evidence provider for the given product code."""

    code_norm = (product_code or "").strip().upper()
    return _PRODUCT_ILLUSTRATION_EVIDENCE_PROVIDERS.get(code_norm)


def _get_illustration_provider(product_code: str) -> Optional[ProductIllustrationProvider]:
    """Resolve an on-demand illustration provider for the given product code."""

    code_norm = (product_code or "").strip().upper()
    return _ILLUSTRATION_PROVIDERS.get(code_norm)


def _build_projection_inputs_and_table_from_summary(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Derive scenario-like inputs and a compact projection table from a
    projection summary JSON object.

    This is intentionally product-agnostic and only assumes a
    term-style projection with ``years``, ``death_benefits``, optional
    ``cash_values``, and either ``expected_premiums`` or ``premiums``.
    """

    inputs = data.get("inputs") or {}
    policy_inputs = inputs.get("policy_inputs") or {}
    if not isinstance(policy_inputs, dict):
        policy_inputs = {}

    issue_age = policy_inputs.get("issue_age")
    gender = policy_inputs.get("gender")
    smoker_class = policy_inputs.get("smoker_class")
    risk_class = policy_inputs.get("risk_class")
    level_period = policy_inputs.get("level_period")
    face_amount = policy_inputs.get("face_amount")
    premium_mode_raw = policy_inputs.get("premium_mode") or ""
    premium_mode = str(premium_mode_raw or "").strip().upper() or "UNKNOWN"

    scenario_inputs = {
        "age": issue_age if isinstance(issue_age, (int, float)) else "unknown",
        "sex": str(gender).strip() or "unknown",
        "smokerClass": str(smoker_class).strip() or "unknown",
        "termYears": level_period or 0,
        "faceAmount": face_amount or 0.0,
        "premiumMode": premium_mode,
    }

    full_proj = data.get("projection") or {}
    proj_years = full_proj.get("years") or []
    proj_db = full_proj.get("death_benefits") or []
    proj_cash = full_proj.get("cash_values") or []
    proj_prem = full_proj.get("expected_premiums") or full_proj.get("premiums") or []

    projection_table: List[Dict[str, Any]] = []
    for idx, y in enumerate(proj_years):
        if y is None:
            continue
        try:
            year_int = int(y)
        except (TypeError, ValueError):
            year_int = y  # keep as-is if it cannot be coerced

        attained_age: Optional[int] = None
        if isinstance(issue_age, (int, float)) and isinstance(year_int, int):
            try:
                attained_age = int(issue_age) + max(0, year_int - 1)
            except Exception:
                attained_age = None

        premium = proj_prem[idx] if idx < len(proj_prem) else None
        dbv = proj_db[idx] if idx < len(proj_db) else None

        status_label: Optional[str] = None
        if isinstance(level_period, int) and level_period > 0 and isinstance(year_int, int):
            status_label = "in_force_term" if year_int <= level_period else "post_term"

        row: Dict[str, Any] = {
            "year": year_int,
            "attainedAge": attained_age,
            "premium": premium,
            "deathBenefit": dbv,
            "status": status_label,
        }

        if idx < len(proj_cash):
            row["cashValue"] = proj_cash[idx]

        projection_table.append(row)

    return scenario_inputs, projection_table


def api_product_model_review_generic(product_code: str) -> Dict[str, Any]:
    """Generic Product Model Review builder for ad-hoc products.

    This uses the same Product Review draft state as the P12TRF builder but
    avoids product-specific assumptions beyond the core term-style
    dimensionality (age, term, classes, face amount, premium mode). Where
    richer artefacts (ProductDefinition, coverage matrix, evidence) are not
    available, it returns empty shells instead of failing.
    """

    code = (product_code or "").strip().upper()

    rec = get_product_review(code)
    meta = (rec or {}).get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    review_state = meta.get("review") or {}
    if not isinstance(review_state, dict):
        review_state = {}

    filing_id = review_state.get("filing_id") if isinstance(review_state, dict) else None
    if isinstance(filing_id, str):
        filing_id = filing_id.strip() or None

    current_generation = review_state.get("current_generation") if isinstance(review_state, dict) else None
    generated_at = review_state.get("generated_at") if isinstance(review_state, dict) else None
    internal_scenarios = review_state.get("scenarios") if isinstance(review_state, dict) else None

    # Build a minimal scenario evidence block from the stored scenarios and
    # any generation-scoped projections we can find.
    scenarios: List[Dict[str, Any]] = []
    code_lower = code.lower()
    if isinstance(internal_scenarios, list):
        for s in internal_scenarios:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id") or "").strip()
            if not sid:
                continue
            name = str(s.get("name") or sid)
            policy = s.get("policy") or {}

            inputs = {
                "age": policy.get("issue_age", "unknown"),
                "sex": policy.get("gender", "unknown"),
                "smokerClass": policy.get("smoker_class", "unknown"),
                "termYears": policy.get("level_period") or 0,
                "faceAmount": policy.get("face_amount") or 0,
                "premiumMode": (policy.get("premium_mode") or "UNKNOWN").upper(),
            }

            projection_key = None
            if current_generation:
                projection_key = f"projections/{code_lower}/reviews/{current_generation}/scenarios/{sid}.json"

            scen_entry: Dict[str, Any] = {
                "id": sid,
                "name": name,
                "purpose": s.get("purpose"),
                "dimensionsExercised": s.get("dimensions_exercised"),
                "source": s.get("source"),
                "inputs": inputs,
                "expectedBehavior": [],
                "modelBehaviorSummary": "",
                "status": "unknown",
                "ruleIds": [],
                "runId": None,
                "projectionKey": projection_key,
                "checks": {},
                "projection": {},
                "projectionTable": [],
            }

            scenarios.append(scen_entry)

    # Best-effort ProductDefinition load; when unavailable we surface a
    # null definition and empty coverage matrix.
    product_definition_summary: Optional[Dict[str, Any]] = None
    product_definition_full: Optional[ProductDefinitionV1] = None
    coverage_matrix: List[Dict[str, Any]] = []
    if filing_id:
        try:
            pd = _load_or_seed_product_definition(code, filing_id)
        except Exception:
            pd = None
        if pd is not None:
            product_definition_full = pd
            product_definition_summary = pd.summary()

    # Documents associated with this product / filing.
    documents_payload: List[Dict[str, Any]] = []
    docs: List[Dict[str, Any]] = []
    try:
        docs = list_product_documents(code, filing_id=filing_id)
        for d in docs:
            documents_payload.append(
                {
                    "id": d.get("id"),
                    "kind": d.get("kind"),
                    "description": d.get("description"),
                    "objectPath": d.get("object_path"),
                    "createdAt": d.get("created_at"),
                    "filingId": d.get("serff_id") or filing_id,
                }
            )
    except Exception:
        docs = []

    review_meta: Dict[str, Any] = {
        "filingId": filing_id,
        "currentGeneration": current_generation,
        "generatedAt": generated_at,
        "documentCount": len(docs),
        "scenarioCount": len(scenarios),
        "traceableRuleCount": 0,
        "unattributedRuleCount": 0,
    }

    product_block = {
        "code": code,
        "name": (meta.get("name") or code) if isinstance(meta, dict) else code,
        "definitionId": None,
    }

    # Minimal, generic shells for sections that the UI expects.
    traceability = {"rules": []}
    rates = {"cellsChecked": 0, "cellsMatched": 0, "exceptions": [], "spotChecks": []}
    assumptions = {"filed": [], "aiProposed": []}
    gaps = {"missingFeatures": [], "ambiguousLanguage": []}
    review_freshness = {
        "status": "unknown",
        "messages": [],
        "latestDocumentUploadedAt": None,
        "currentGeneration": current_generation,
        "generatedAt": generated_at,
        "productDefinitionGeneratedAt": None,
        "latestDecisionCreatedAt": None,
    }

    return {
        "product": product_block,
        "scope": {
            "filings": ([{"id": filing_id, "name": filing_id}] if filing_id else []),
            "featuresModeled": [],
            "featuresNotModeled": [],
            "confidence": "medium",
            "pocLabel": "generic-term-poc",
        },
        "traceability": traceability,
        "rates": rates,
        "scenarios": scenarios,
        "assumptions": assumptions,
        "gaps": gaps,
        "reviewMeta": review_meta,
        "reviewFreshness": review_freshness,
        "productDefinition": product_definition_summary,
        "coverageMatrix": coverage_matrix,
        "productDefinitionBuild": None,
        "productDefinitionValidation": None,
        "scenarioValidation": None,
        "decisionTimeline": None,
    }


@app.get("/api/product-model-review/{product_code}")
def api_product_model_review_product(product_code: str) -> Dict[str, Any]:
    """Product-aware Product Model Review entrypoint.

    Uses the static product registry to distinguish between implemented
    products, known-but-unimplemented products, and unknown codes, and
    then resolves a PMR builder from the builder registry.
    """

    cfg = _get_product_config(product_code)
    code_norm = (cfg.get("productCode") if cfg else product_code or "").strip().upper()

    # Prefer a product-specific builder when one is registered (currently
    # P12TRF), but fall back to a generic builder so any product with a
    # Product Review can still surface a model review snapshot.
    builder = _get_product_model_review_builder(code_norm)
    if builder is not None:
        return builder()

    return api_product_model_review_generic(code_norm)


@app.post("/api/product-model-review/{product_code}/ai-summary")
def api_product_model_review_ai_summary(
    product_code: str,
    payload: ProductModelReviewAISummaryRequest,
) -> Dict[str, Any]:
    """Run multi-level AI agents on top of the PMR for this product.

    This endpoint:
    - builds the current PMR payload for the product, and
    - runs two AI stages over it:
      1) structured PMR summary
      2) draft decision suggestion.

    It returns a JSON object containing the original PMR payload plus the
    AI-derived summary and suggestion. No database writes are performed;
    callers remain responsible for persisting any accepted decision.
    """

    # Reuse the product-aware PMR entrypoint to assemble the base payload.
    pmr = api_product_model_review_product(product_code)

    feedback = (payload.feedback or "").strip() or None
    previous_summary = payload.previousSummary or None
    previous_decision = payload.previousDecision or None

    try:
        summary = summarise_pmr(
            pmr,
            model=payload.modelSummary,
            feedback=feedback,
            previous=previous_summary,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to summarise PMR via OpenAI: {exc}") from exc

    try:
        decision = propose_decision(
            pmr,
            summary,
            model=payload.modelDecision,
            feedback=feedback,
            previous=previous_decision,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to propose decision via OpenAI: {exc}") from exc

    return {
        "pmr": pmr,
        "aiSummary": summary,
        "aiDecision": decision,
    }


@app.post("/api/product-review/finalize-product-code")
def api_product_review_finalize_product_code(payload: ProductCodeFinalizeRequest) -> Dict[str, Any]:
    """Migrate documents from a temporary product code to a final one.

    This endpoint supports flows where filings were uploaded under a
    temporary product identifier (e.g. TMP-*) and the metadata stage then
    identifies the canonical product code from the filings.

    It:
    - moves MinIO objects under docs/{old}/... to docs/{new}/..., and
    - updates the documents.product_id column from old → new.
    """

    old = (payload.oldProductCode or "").strip().upper()
    new = (payload.newProductCode or "").strip().upper()

    if not old or not new:
        raise HTTPException(status_code=400, detail="oldProductCode and newProductCode are required")

    if old == new:
        # Nothing to do.
        return {"movedObjects": 0, "updatedRows": 0, "skipped": True}

    client = get_minio_client()
    ensure_bucket(client)
    bucket = get_bucket_name()

    old_prefix = f"docs/{old}/"
    new_prefix = f"docs/{new}/"

    moved = 0
    try:
        # Move all objects under docs/{old}/ to docs/{new}/.
        for obj in client.list_objects(bucket, prefix=old_prefix, recursive=True):
            old_name = obj.object_name
            if not old_name.startswith(old_prefix):
                continue
            suffix = old_name[len(old_prefix) :]
            new_name = f"{new_prefix}{suffix}"

            # Copy contents then delete the old object.
            try:
                response = client.get_object(bucket, old_name)
                body = response.read()
            finally:
                try:
                    response.close()
                    response.release_conn()
                except Exception:
                    pass

            import io as _io

            client.put_object(
                bucket,
                new_name,
                _io.BytesIO(body),
                length=len(body),
                content_type=obj.content_type or "application/octet-stream",
            )
            client.remove_object(bucket, old_name)
            moved += 1
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to migrate MinIO objects from {old} to {new}: {exc}") from exc

    # Relabel documents rows in Postgres.
    updated_rows = relabel_documents_product(old, new)

    return {"movedObjects": moved, "updatedRows": updated_rows, "skipped": False}


@app.get("/api/products/{product_code}/requirements")
def api_product_requirements_product(product_code: str) -> Dict[str, Any]:
    """Product-aware Filing Requirements entrypoint.

    Uses the product registry and requirements provider registry to
    distinguish implemented vs not-implemented products and to resolve a
    product-specific requirements provider.
    """

    cfg = _get_product_config(product_code)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown product_code '{product_code}'.")

    status = cfg.get("status") or "unknown"
    code_norm = (cfg.get("productCode") or product_code or "").strip().upper()

    if status != "implemented":
        # Known but not yet implemented product.
        raise HTTPException(
            status_code=501,
            detail="Product requirements surface is not implemented for this product yet.",
        )

    provider = _get_product_requirements_provider(code_norm)
    if provider is None:
        raise HTTPException(
            status_code=501,
            detail="Product requirements provider is not registered for this product yet.",
        )

    return provider(code_norm)


@app.get("/api/product-requirements/{product_code}")
def api_product_requirements(product_code: str) -> Dict[str, Any]:
    """Backwards-compatible alias for the product requirements endpoint."""

    return api_product_requirements_product(product_code)


@app.get("/api/products/{product_code}/product-definition-evidence")
def api_product_definition_evidence_product(product_code: str) -> Dict[str, Any]:
    """Product-aware ProductDefinition evidence entrypoint."""

    cfg = _get_product_config(product_code)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown product_code '{product_code}'.")

    status = cfg.get("status") or "unknown"
    code_norm = (cfg.get("productCode") or product_code or "").strip().upper()

    if status != "implemented":
        raise HTTPException(
            status_code=501,
            detail="ProductDefinition evidence surface is not implemented for this product yet.",
        )

    provider = _get_product_definition_evidence_provider(code_norm)
    if provider is None:
        raise HTTPException(
            status_code=501,
            detail="ProductDefinition evidence provider is not registered for this product yet.",
        )

    return provider(code_norm)


@app.get("/api/products/{product_code}/projection-logic-evidence")
def api_product_projection_evidence_product(product_code: str) -> Dict[str, Any]:
    """Product-aware projection logic evidence entrypoint."""

    cfg = _get_product_config(product_code)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown product_code '{product_code}'.")

    status = cfg.get("status") or "unknown"
    code_norm = (cfg.get("productCode") or product_code or "").strip().upper()

    if status != "implemented":
        raise HTTPException(
            status_code=501,
            detail="Projection logic evidence surface is not implemented for this product yet.",
        )

    provider = _get_product_projection_evidence_provider(code_norm)
    if provider is None:
        raise HTTPException(
            status_code=501,
            detail="Projection logic evidence provider is not registered for this product yet.",
        )

    return provider(code_norm)


@app.get("/api/products/{product_code}/illustration-evidence")
def api_product_illustration_evidence_product(product_code: str) -> Dict[str, Any]:
    """Product-aware illustration comparison evidence entrypoint."""

    cfg = _get_product_config(product_code)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown product_code '{product_code}'.")

    status = cfg.get("status") or "unknown"
    code_norm = (cfg.get("productCode") or product_code or "").strip().upper()

    if status != "implemented":
        raise HTTPException(
            status_code=501,
            detail="Illustration comparison evidence surface is not implemented for this product yet.",
        )

    provider = _get_product_illustration_evidence_provider(code_norm)
    if provider is None:
        raise HTTPException(
            status_code=501,
            detail="Illustration comparison evidence provider is not registered for this product yet.",
        )

    return provider(code_norm)


@app.post("/api/illustrations/{product_code}")
def api_product_illustration(product_code: str, payload: IllustrationRequest) -> Dict[str, Any]:
    """Generic on-demand illustration endpoint.

    This is product-aware and delegates to a per-product illustration
    provider registered in the illustration provider registry. Products
    that are known but do not yet support on-demand illustration return
    a 501; unknown products return 404.
    """

    cfg = _get_product_config(product_code)
    status = cfg.get("status") or "unknown"
    code_norm = (cfg.get("productCode") or product_code or "").strip().upper()

    # Prefer a product-specific illustration provider when one is
    # registered (currently P12TRF), but fall back to a generic term
    # illustration provider for any product that has term-style
    # projections. Unknown / experimental products are therefore
    # supported on a best-effort basis instead of returning 501.
    provider = _get_illustration_provider(code_norm)
    if provider is None:
        provider = build_generic_term_illustration

    try:
        request_dict = payload.dict()  # type: ignore[call-arg]
    except Exception:
        request_dict = {
            "age": payload.age,
            "termYears": payload.termYears,
            "riskClass": payload.riskClass,
            "smokerClass": payload.smokerClass,
            "faceAmount": payload.faceAmount,
            "premiumMode": payload.premiumMode,
        }

    return provider(code_norm, request_dict)


def build_p12trf_requirements(product_code: str) -> Dict[str, Any]:
    """P12TRF-specific Filing Requirements provider.

    This reuses the P12TRF PMR builder so that ProductDefinition,
    coverage matrix, and traceability are derived in one place, then
    projects that into a generic requirements payload.
    """

    pmr = api_product_model_review_p12trf()
    product_block = pmr.get("product") or {}
    review_meta = pmr.get("reviewMeta") or {}
    filing_id = review_meta.get("filingId")
    product_definition = pmr.get("productDefinition") or {}
    coverage_matrix = pmr.get("coverageMatrix") or []

    def _cm_row(feature: str) -> Optional[Dict[str, Any]]:
        for row in coverage_matrix or []:
            if isinstance(row, dict) and str(row.get("feature")) == feature:
                return row
        return None

    def _impl_status(feature: str) -> str:
        row = _cm_row(feature)
        cm_status = str((row or {}).get("status") or "").lower()
        if cm_status == "covered":
            return "implemented"
        if cm_status == "partial":
            return "partial"
        if cm_status in {"gap", "not_applicable"}:
            return "missing"
        return "missing"

    def _pd_value(path: str) -> Any:
        # Simple one-level lookup for now; future adapters can support
        # dotted paths. For this POC, top-level keys are enough.
        key = path.split(".")[0]
        return (product_definition or {}).get(key)

    def _mapping(path: str) -> Dict[str, Any]:
        return {"path": path, "value": _pd_value(path)}

    requirements: List[Dict[str, Any]] = []

    # Level term periods
    requirements.append(
        {
            "requirementId": "req_term_periods",
            "requirementText": "Level term periods for this product.",
            "category": "coverage",
            "source": {
                "documentPath": None,
                "filingLocation": f"{filing_id or 'P12TRF filing (POC)'} – Term periods section",
            },
            "productDefinitionMappings": [_mapping("termPeriods")],
            "evidenceRuleIds": [],
            "implementationStatus": _impl_status("Term periods"),
            "notes": f"ProductDefinition termPeriods={_pd_value('termPeriods')!r}",
        }
    )

    # Issue age range
    requirements.append(
        {
            "requirementId": "req_issue_ages",
            "requirementText": "Issue age range for base coverage.",
            "category": "eligibility",
            "source": {
                "documentPath": None,
                "filingLocation": f"{filing_id or 'P12TRF filing (POC)'} – Issue ages table",
            },
            "productDefinitionMappings": [_mapping("issueAges")],
            "evidenceRuleIds": [],
            "implementationStatus": _impl_status("Issue ages"),
            "notes": f"ProductDefinition issueAges={_pd_value('issueAges')!r}",
        }
    )

    # Risk / underwriting classes
    requirements.append(
        {
            "requirementId": "req_risk_classes",
            "requirementText": "Underwriting and risk classes supported by the product.",
            "category": "eligibility",
            "source": {
                "documentPath": None,
                "filingLocation": f"{filing_id or 'P12TRF filing (POC)'} – Risk class definitions",
            },
            "productDefinitionMappings": [_mapping("underwritingClasses"), _mapping("riskClasses")],
            "evidenceRuleIds": [],
            "implementationStatus": _impl_status("Underwriting / risk classes"),
            "notes": f"ProductDefinition underwritingClasses={_pd_value('underwritingClasses')!r}",
        }
    )

    # Smoker classes
    requirements.append(
        {
            "requirementId": "req_smoker_classes",
            "requirementText": "Smoker / non-smoker classes.",
            "category": "eligibility",
            "source": {
                "documentPath": None,
                "filingLocation": f"{filing_id or 'P12TRF filing (POC)'} – Smoker class definitions",
            },
            "productDefinitionMappings": [_mapping("smokerClasses")],
            "evidenceRuleIds": [],
            "implementationStatus": _impl_status("Smoker classes"),
            "notes": f"ProductDefinition smokerClasses={_pd_value('smokerClasses')!r}",
        }
    )

    # Premium modes
    requirements.append(
        {
            "requirementId": "req_premium_modes",
            "requirementText": "Premium payment modes (e.g. annual).",
            "category": "premium",
            "source": {
                "documentPath": None,
                "filingLocation": f"{filing_id or 'P12TRF filing (POC)'} – Premium mode definitions",
            },
            "productDefinitionMappings": [_mapping("premiumModes")],
            "evidenceRuleIds": [],
            "implementationStatus": _impl_status("Premium modes"),
            "notes": f"ProductDefinition premiumModes={_pd_value('premiumModes')!r}",
        }
    )

    # Face amount range
    requirements.append(
        {
            "requirementId": "req_face_amount_range",
            "requirementText": "Minimum and maximum face amounts.",
            "category": "eligibility",
            "source": {
                "documentPath": None,
                "filingLocation": f"{filing_id or 'P12TRF filing (POC)'} – Face amount limits",
            },
            "productDefinitionMappings": [_mapping("faceAmounts")],
            "evidenceRuleIds": [],
            "implementationStatus": _impl_status("Face amount range"),
            "notes": f"ProductDefinition faceAmounts={_pd_value('faceAmounts')!r}",
        }
    )

    # Base term death benefit
    requirements.append(
        {
            "requirementId": "req_base_term_death_benefit",
            "requirementText": "Base term death benefit payable during the level term.",
            "category": "coverage",
            "source": {
                "documentPath": None,
                "filingLocation": f"{filing_id or 'P12TRF filing (POC)'} – Death benefit during term",
            },
            "productDefinitionMappings": [_mapping("coverages")],
            "evidenceRuleIds": ["rule_death_benefit_term"],
            "implementationStatus": _impl_status("Base term coverage"),
            "notes": f"ProductDefinition coverages={_pd_value('coverages')!r}",
        }
    )

    # Level premiums
    requirements.append(
        {
            "requirementId": "req_level_premiums",
            "requirementText": "Premiums remain level during the term.",
            "category": "premium",
            "source": {
                "documentPath": None,
                "filingLocation": f"{filing_id or 'P12TRF filing (POC)'} – Level premium table",
            },
            "productDefinitionMappings": [_mapping("premiumModes")],
            "evidenceRuleIds": ["rule_level_premiums"],
            "implementationStatus": _impl_status("Level premiums"),
            "notes": "Derived from premium lookup table and rate reconciliation checks.",
        }
    )

    # Riders / unmodeled coverages
    requirements.append(
        {
            "requirementId": "req_riders_unmodeled",
            "requirementText": "Riders and unmodeled coverages recorded in the filing.",
            "category": "rider",
            "source": {
                "documentPath": None,
                "filingLocation": f"{filing_id or 'P12TRF filing (POC)'} – Rider and supplemental benefit sections",
            },
            "productDefinitionMappings": [_mapping("extra")],
            "evidenceRuleIds": [],
            "implementationStatus": _impl_status("Riders / unmodeled coverages"),
            "notes": "Unmodeled coverages are tracked but not projected in this POC.",
        }
    )

    # Convertibility – currently a documented placeholder only.
    requirements.append(
        {
            "requirementId": "req_convertibility",
            "requirementText": "Convertibility privilege during the level term.",
            "category": "rider",
            "source": {
                "documentPath": None,
                "filingLocation": f"{filing_id or 'P12TRF filing (POC)'} – Convertibility provisions",
            },
            "productDefinitionMappings": [_mapping("extra")],
            "evidenceRuleIds": [],
            "implementationStatus": "missing",
            "notes": "Convertibility is acknowledged conceptually but not modeled in the current P12TRF POC.",
        }
    )

    total = len(requirements)
    implemented = sum(1 for r in requirements if str(r.get("implementationStatus")) == "implemented")
    partial = sum(1 for r in requirements if str(r.get("implementationStatus")) == "partial")
    missing = sum(1 for r in requirements if str(r.get("implementationStatus")) == "missing")

    return {
        "productCode": product_block.get("code") or product_code,
        "productName": product_block.get("name"),
        "filingId": filing_id,
        "status": "available",
        "requirements": requirements,
        "summary": {
            "total": total,
            "implemented": implemented,
            "partial": partial,
            "missing": missing,
        },
    }


_PRODUCT_REQUIREMENTS_PROVIDERS["P12TRF"] = build_p12trf_requirements


def build_p12trf_product_definition_evidence(product_code: str) -> Dict[str, Any]:
    """P12TRF-specific ProductDefinition evidence provider.

    Projects the existing ProductDefinition summary, build metadata, and
    validation into a generic evidence payload, and links PD fields back
    to filing requirements where possible.
    """

    pmr = api_product_model_review_p12trf()
    product_block = pmr.get("product") or {}
    review_meta = pmr.get("reviewMeta") or {}
    filing_id = review_meta.get("filingId")
    pd_summary = pmr.get("productDefinition") or {}
    pd_build = pmr.get("productDefinitionBuild") or {}
    pd_validation = pmr.get("productDefinitionValidation") or {}

    # Pull requirements so we can invert ProductDefinition mappings into
    # linkedRequirementIds for each PD field.
    requirements_payload: Dict[str, Any] = {}
    try:
        provider = _get_product_requirements_provider(product_code)
        if provider is not None:
            requirements_payload = provider(product_code)
    except Exception:
        requirements_payload = {}

    reqs = requirements_payload.get("requirements") or []
    reqs_by_path: Dict[str, List[str]] = {}
    if isinstance(reqs, list):
        for r in reqs:
            if not isinstance(r, dict):
                continue
            rid = r.get("requirementId") or r.get("id")
            if not rid:
                continue
            mappings = r.get("productDefinitionMappings") or []
            if isinstance(mappings, list):
                for m in mappings:
                    if not isinstance(m, dict):
                        continue
                    path = str(m.get("path") or "").strip()
                    if not path:
                        continue
                    bucket = reqs_by_path.setdefault(path, [])
                    if rid not in bucket:
                        bucket.append(rid)

    def _field(path: str, label: str) -> Dict[str, Any]:
        # For this POC we only look at the top-level key in the summary
        # object; more complex adapters can support dotted paths later.
        key = path.split(".")[0]
        value = pd_summary.get(key)
        linked_ids = reqs_by_path.get(path, [])
        return {
            "path": path,
            "label": label,
            "value": value,
            "linkedRequirementIds": linked_ids,
        }

    fields: List[Dict[str, Any]] = []
    fields.append(_field("termPeriods", "Level term periods"))
    fields.append(_field("issueAges", "Issue ages"))
    fields.append(_field("underwritingClasses", "Underwriting classes"))
    fields.append(_field("riskClasses", "Risk classes"))
    fields.append(_field("smokerClasses", "Smoker classes"))
    fields.append(_field("premiumModes", "Premium modes"))
    fields.append(_field("faceAmounts", "Face amount range"))
    fields.append(_field("coverages", "Coverages"))
    fields.append(_field("extra", "Additional product details / riders / convertibility"))

    field_count = len(fields)
    linked_field_count = sum(1 for f in fields if f.get("linkedRequirementIds"))
    validation_status = str((pd_validation or {}).get("status") or "unknown")

    return {
        "productCode": product_block.get("code") or product_code,
        "productName": product_block.get("name"),
        "filingId": filing_id,
        "status": "available",
        "productDefinition": pd_summary,
        "build": pd_build,
        "validation": pd_validation,
        "fields": fields,
        "summary": {
            "fieldCount": field_count,
            "linkedFieldCount": linked_field_count,
            "validationStatus": validation_status,
        },
    }


_PRODUCT_DEFINITION_EVIDENCE_PROVIDERS["P12TRF"] = build_p12trf_product_definition_evidence


def build_p12trf_projection_logic_evidence(product_code: str) -> Dict[str, Any]:
    """P12TRF-specific projection logic evidence provider.

    This is an explanatory layer that links filing requirements and
    ProductDefinition fields to the high-level projection behaviour, so
    an actuary can see how the model implements key contract features.
    """

    pmr = api_product_model_review_p12trf()
    product_block = pmr.get("product") or {}
    review_meta = pmr.get("reviewMeta") or {}
    filing_id = review_meta.get("filingId")

    behaviors: List[Dict[str, Any]] = []

    # Base term death benefit logic.
    behaviors.append(
        {
            "id": "behav_base_term_death_benefit",
            "label": "Death benefit during level term",
            "category": "coverage",
            "requirementIds": ["req_base_term_death_benefit", "req_term_periods"],
            "productDefinitionPaths": ["coverages", "termPeriods"],
            "projectionLogic": {
                "description": (
                    "While duration is within a modeled term period, the death benefit equals the face "
                    "amount from the ProductDefinition coverage; after term expiry the death benefit is zero."
                ),
                "pseudoCode": (
                    "if duration_years <= level_term_years:\n"
                    "    death_benefit = face_amount\n"
                    "else:\n"
                    "    death_benefit = 0"
                ),
                "notes": (
                    "Implemented via the term coverage in ProductDefinition coverages and exercised by the "
                    "scenario set used in the Trust Surface projections."
                ),
            },
        }
    )

    # Level premium logic.
    behaviors.append(
        {
            "id": "behav_level_premiums",
            "label": "Level premiums during term",
            "category": "premium",
            "requirementIds": ["req_level_premiums", "req_premium_modes"],
            "productDefinitionPaths": ["premiumModes"],
            "projectionLogic": {
                "description": (
                    "Premiums are level over the modeled term, determined by a rate table by age, risk class, "
                    "smoker class, and term period, and then applied at the configured premium mode."
                ),
                "pseudoCode": (
                    "rate = lookup_rate(age, risk_class, smoker_class, term_years)\n"
                    "annual_premium = rate * face_amount / 1000\n"
                    "premium = apply_mode(annual_premium, premium_mode)"
                ),
                "notes": (
                    "Implemented via the premium lookup table and premiumModes in the ProductDefinition, "
                    "and validated by the rate reconciliation checks on the Trust Surface."
                ),
            },
        }
    )

    # Eligibility / issue age logic (simplified).
    behaviors.append(
        {
            "id": "behav_issue_age_eligibility",
            "label": "Issue age eligibility",
            "category": "eligibility",
            "requirementIds": ["req_issue_ages"],
            "productDefinitionPaths": ["issueAges"],
            "projectionLogic": {
                "description": (
                    "Policies are only projected when the issue age falls within the ProductDefinition "
                    "issueAges[min, max] range; scenarios outside this range are treated as invalid."
                ),
                "pseudoCode": (
                    "if age < issueAgeMin or age > issueAgeMax:\n"
                    "    reject_case('age out of bounds')\n"
                    "else:\n"
                    "    proceed_with_projection()"
                ),
                "notes": (
                    "The POC scenarios all fall within 18–75, and the ProductDefinition validation "
                    "explicitly checks that scenario ages respect these bounds."
                ),
            },
        }
    )

    # Risk and smoker class handling (simplified mapping).
    behaviors.append(
        {
            "id": "behav_risk_smoker_classes",
            "label": "Risk and smoker class mapping",
            "category": "eligibility",
            "requirementIds": ["req_risk_classes", "req_smoker_classes"],
            "productDefinitionPaths": ["underwritingClasses", "riskClasses", "smokerClasses"],
            "projectionLogic": {
                "description": (
                    "Risk and smoker classes in scenarios are mapped into the ProductDefinition risk and "
                    "smoker classes before rate lookup; unsupported combinations are treated as out of "
                    "scope for this POC."
                ),
                "pseudoCode": (
                    "uw_class = map_underwriting_class(input_uw)\n"
                    "risk_class = map_risk_class(input_risk)\n"
                    "smoker_class = map_smoker_class(input_smoker)\n"
                    "# lookup_rate uses these mapped classes"
                ),
                "notes": (
                    "The mapping is implicitly exercised by the P12TRF scenarios and validated via the "
                    "ProductDefinition validation checks for risk and smoker classes."
                ),
            },
        }
    )

    # Placeholder for riders / unmodeled coverage logic.
    behaviors.append(
        {
            "id": "behav_unmodeled_riders",
            "label": "Unmodeled riders and supplemental benefits",
            "category": "rider",
            "requirementIds": ["req_riders_unmodeled"],
            "productDefinitionPaths": ["extra"],
            "projectionLogic": {
                "description": (
                    "Riders and supplemental benefits recorded in the filing are not projected in this POC; "
                    "the projection engine ignores them and only models the base term coverage."
                ),
                "pseudoCode": (
                    "# riders listed in ProductDefinition.extra.unmodeled_coverages\n"
                    "# are not included in projection cash flows in this POC"
                ),
                "notes": (
                    "This behaviour is explicitly called out in the coverage matrix and requirements "
                    "surface as missing/unmodeled."
                ),
            },
        }
    )

    # Convertibility logic (currently unmodeled in projections).
    behaviors.append(
        {
            "id": "behav_convertibility",
            "label": "Convertibility during level term",
            "category": "rider",
            "requirementIds": ["req_convertibility"],
            "productDefinitionPaths": ["extra"],
            "projectionLogic": {
                "description": (
                    "Convertibility provisions are documented in the filing but are not "
                    "projected in this POC; only the base term coverage cash flows are modeled."
                ),
                "pseudoCode": (
                    "# convertibility terms recorded in ProductDefinition.extra.convertibility\n"
                    "# are not exercised in the projection engine in this POC"
                ),
                "notes": (
                    "This behaviour is tied to req_convertibility and will be updated once "
                    "convertibility cash flows are explicitly modeled."
                ),
            },
        }
    )

    return {
        "productCode": product_block.get("code") or product_code,
        "productName": product_block.get("name"),
        "filingId": filing_id,
        "status": "available",
        "behaviors": behaviors,
        "summary": {
            "behaviorCount": len(behaviors),
        },
    }


_PRODUCT_PROJECTION_EVIDENCE_PROVIDERS["P12TRF"] = build_p12trf_projection_logic_evidence


def build_p12trf_illustration_evidence(product_code: str) -> Dict[str, Any]:
    """P12TRF-specific illustration comparison evidence provider.

    Projects the existing rate spot checks into a generic comparison
    payload so an actuary can see where modelled premiums align with
    filed illustration points and where they diverge.
    """

    pmr = api_product_model_review_p12trf()
    product_block = pmr.get("product") or {}
    review_meta = pmr.get("reviewMeta") or {}
    filing_id = review_meta.get("filingId")

    rates = pmr.get("rates") or {}
    spot_checks = rates.get("spotChecks") or []

    cases: List[Dict[str, Any]] = []

    if isinstance(spot_checks, list):
        for idx, sc in enumerate(spot_checks):
            if not isinstance(sc, dict):
                continue

            age = sc.get("age")
            term_years = sc.get("termYears")
            risk_class = sc.get("riskClass")
            face_amount = sc.get("faceAmount")
            filed_prem = sc.get("filedPremium")
            model_prem = sc.get("modelPremium")
            raw_status = str(sc.get("status") or "").lower() or "unknown"

            abs_diff: Optional[float] = None
            pct_diff: Optional[float] = None
            if isinstance(filed_prem, (int, float)) and isinstance(model_prem, (int, float)):
                try:
                    abs_diff = float(model_prem) - float(filed_prem)
                    pct_diff = (abs_diff / float(filed_prem)) if filed_prem not in (0, 0.0) else None
                except Exception:
                    abs_diff = None
                    pct_diff = None

            # Normalise to a coarse within_tolerance vs mismatch view.
            if raw_status in {"ok", "match", "within_tolerance"}:
                norm_status = "within_tolerance"
            elif raw_status in {"mismatch", "fail", "error"}:
                norm_status = "mismatch"
            else:
                norm_status = raw_status or "unknown"

            case_id = sc.get("id") or f"case_{idx + 1}"

            cases.append(
                {
                    "id": case_id,
                    "label": sc.get("label")
                    or f"Age {age}, term {term_years}y, {risk_class or 'risk'} {face_amount}",
                    "inputs": {
                        "age": age,
                        "termYears": term_years,
                        "riskClass": risk_class,
                        "faceAmount": face_amount,
                    },
                    "trusted": {
                        "annualPremium": filed_prem,
                    },
                    "model": {
                        "annualPremium": model_prem,
                    },
                    "difference": {
                        "absolute": abs_diff,
                        "percent": pct_diff,
                    },
                    "status": norm_status,
                    # For this POC, all comparison cases support the
                    # same premium-related requirements.
                    "linkedRequirementIds": [
                        "req_level_premiums",
                        "req_premium_modes",
                    ],
                }
            )

    case_count = len(cases)
    within_tolerance = sum(1 for c in cases if str(c.get("status")) == "within_tolerance")
    mismatch = sum(1 for c in cases if str(c.get("status")) == "mismatch")

    return {
        "productCode": product_block.get("code") or product_code,
        "productName": product_block.get("name"),
        "filingId": filing_id,
        "status": "available" if case_count > 0 else "no_cases",
        "cases": cases,
        "summary": {
            "caseCount": case_count,
            "withinTolerance": within_tolerance,
            "mismatch": mismatch,
        },
    }


_PRODUCT_ILLUSTRATION_EVIDENCE_PROVIDERS["P12TRF"] = build_p12trf_illustration_evidence


@app.post("/api/client-error")
async def api_client_error(request: Request) -> Dict[str, Any]:
    """Receive client-side errors and log them to the server logs.

    This lets us diagnose "blank screen" issues from pod logs without
    needing direct access to the browser console.
    """

    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": await request.body()}  # type: ignore[assignment]

    logger = logging.getLogger("client-errors")
    try:
        logger.error("Client error: %s", json.dumps(payload, sort_keys=True, separators=(",", ":")))
    except Exception:
        logger.error("Client error (unserializable payload): %r", payload)

    return {"status": "ok"}


def build_p12trf_illustration(product_code: str, request: Dict[str, Any]) -> Dict[str, Any]:
    """P12TRF-specific on-demand illustration provider.

    This reuses the existing scenario projections as templates and
    scales face-dependent fields to the requested face amount. It is a
    POC-only approximation but uses the generic illustration shape so
    other products can plug in richer behaviour later.
    """

    pmr = api_product_model_review_p12trf()
    product_block = pmr.get("product") or {}

    # Normalise request inputs with conservative defaults.
    age_req = request.get("age")
    try:
        age_norm = int(age_req) if age_req is not None else None
    except (TypeError, ValueError):
        age_norm = None

    term_req = request.get("termYears")
    try:
        term_years = int(term_req) if term_req is not None else None
    except (TypeError, ValueError):
        term_years = None

    risk_class = (request.get("riskClass") or "").strip() or None
    smoker_class = (request.get("smokerClass") or "").strip() or None
    premium_mode_raw = (request.get("premiumMode") or "").strip()
    premium_mode = premium_mode_raw.upper() or "ANNUAL"

    face_req = request.get("faceAmount")
    try:
        face_amount = float(face_req) if face_req is not None else None
    except (TypeError, ValueError):
        face_amount = None

    if term_years is None or term_years <= 0:
        raise HTTPException(status_code=400, detail="termYears must be a positive integer.")
    if face_amount is None or face_amount <= 0:
        raise HTTPException(status_code=400, detail="faceAmount must be a positive number.")

    # Reuse existing scenarios & projections as templates.
    scen_and_rates = _build_p12trf_scenarios_and_rates()
    scenarios = scen_and_rates.get("scenarios") or []
    if not isinstance(scenarios, list) or not scenarios:
        raise HTTPException(status_code=500, detail="No scenarios available for illustration.")

    # Find a template scenario with matching term and, when possible,
    # matching premium mode.
    def _score_template(s: Dict[str, Any]) -> int:
        score = 0
        inputs = s.get("inputs") or {}
        s_term = inputs.get("termYears")
        s_mode = (inputs.get("premiumMode") or "").upper()
        if isinstance(s_term, int) and s_term == term_years:
            score += 10
        if s_mode == premium_mode:
            score += 3
        return score

    best: Optional[Dict[str, Any]] = None
    best_score = -1
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        score = _score_template(s)
        if score > best_score:
            best_score = score
            best = s

    if not best or best_score <= 0:
        raise HTTPException(
            status_code=400,
            detail="No compatible scenario template found for requested termYears/premiumMode.",
        )

    inputs = best.get("inputs") or {}
    try:
        template_face = float(inputs.get("faceAmount") or 0.0)
    except (TypeError, ValueError):
        template_face = 0.0

    if template_face <= 0.0:
        template_face = face_amount

    scale = face_amount / template_face if template_face not in (0.0, None) else 1.0

    # Build scaled projection rows, enriching them with illustration-friendly
    # columns such as cumulative premium, surrender value, and net amount at
    # risk so the output table looks and feels like a real illustration grid.
    projection_table = best.get("projectionTable") or []
    rows: List[Dict[str, Any]] = []
    cumulative_premium: Optional[float] = 0.0
    for row in projection_table:
        if not isinstance(row, dict):
            continue
        year = row.get("year")
        attained_age = row.get("attainedAge")
        premium = row.get("premium")
        death_benefit = row.get("deathBenefit")
        cash_value = row.get("cashValue")

        # Adjust attained age if a numeric age was provided.
        if age_norm is not None and isinstance(inputs.get("age"), int) and isinstance(attained_age, int):
            base_issue_age = inputs.get("age")
            try:
                delta = age_norm - int(base_issue_age)
                attained_age = attained_age + delta
            except Exception:
                pass

        def _scaled(x: Any) -> Any:
            try:
                return float(x) * scale if x is not None else None
            except Exception:
                return x

        scaled_premium = _scaled(premium)
        scaled_death_benefit = _scaled(death_benefit)
        scaled_cash_value = _scaled(cash_value)

        # Track cumulative premium using numeric premiums only; when a row
        # has a non-numeric premium we keep the last cumulative value.
        cumulative_premium_value: Optional[float]
        if isinstance(scaled_premium, (int, float)):
            if cumulative_premium is None:
                cumulative_premium = float(scaled_premium)
            else:
                cumulative_premium += float(scaled_premium)
            cumulative_premium_value = cumulative_premium
        else:
            cumulative_premium_value = cumulative_premium

        # For this POC term product we do not yet have explicit surrender
        # charge modelling, so we expose a surrenderValue column that equals
        # the cash value when it is present. This keeps the grid shape close
        # to a real illustration without fabricating extra behaviour.
        surrender_value: Optional[float]
        if isinstance(scaled_cash_value, (int, float)):
            surrender_value = float(scaled_cash_value)
        else:
            surrender_value = None

        net_amount_at_risk: Optional[float]
        if isinstance(scaled_death_benefit, (int, float)) and isinstance(scaled_cash_value, (int, float)):
            net_amount_at_risk = float(scaled_death_benefit) - float(scaled_cash_value)
        else:
            net_amount_at_risk = None

        rows.append(
            {
                "year": year,
                "attainedAge": attained_age,
                "premium": scaled_premium,
                "cumulativePremium": cumulative_premium_value,
                "deathBenefit": scaled_death_benefit,
                "cashValue": scaled_cash_value,
                "surrenderValue": surrender_value,
                "netAmountAtRisk": net_amount_at_risk,
                "status": row.get("status"),
            }
        )

    years: List[Any] = []
    for r in rows:
        y = r.get("year")
        if y is not None:
            years.append(y)

    # Lightweight decision hooks so a single projection is more actionable
    # for an actuary or product partner.

    def _first_break_even_year() -> Optional[int]:
        """Return the first policy year where cash value >= cumulative premium.

        This is intentionally simple and only considers rows with numeric
        cumulativePremium and cashValue.
        """

        for r in rows:
            year_val = r.get("year")
            cv = r.get("cashValue")
            cp = r.get("cumulativePremium")
            if not isinstance(year_val, int):
                continue
            if not isinstance(cv, (int, float)) or not isinstance(cp, (int, float)):
                continue
            try:
                if float(cv) >= float(cp):
                    return year_val
            except Exception:
                continue
        return None

    def _compute_irr_for_horizon(horizon_year: int) -> Optional[float]:
        """Approximate an IRR on premiums to cash value at a given horizon.

        Cash flows are modelled as level outflows (premiums) each policy
        year, with a single inflow equal to cash value at the horizon year.
        The result is an annual effective rate when a sign change exists.
        """

        if horizon_year <= 0:
            return None

        # Index rows by year for quick lookup.
        by_year: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            y_val = r.get("year")
            if isinstance(y_val, int):
                by_year[y_val] = r

        if horizon_year not in by_year:
            return None

        cashflows: List[float] = []
        has_positive = False
        has_negative = False

        for y in range(1, horizon_year + 1):
            row = by_year.get(y) or {}
            prem = row.get("premium")
            try:
                prem_val = float(prem) if isinstance(prem, (int, float)) else 0.0
            except Exception:
                prem_val = 0.0
            cf = -prem_val
            if cf > 0:
                has_positive = True
            if cf < 0:
                has_negative = True
            cashflows.append(cf)

        # Add terminal cash value at the same time as the last premium.
        terminal = by_year.get(horizon_year) or {}
        cv_term = terminal.get("cashValue")
        try:
            term_val = float(cv_term) if isinstance(cv_term, (int, float)) else 0.0
        except Exception:
            term_val = 0.0

        if cashflows:
            cashflows[-1] += term_val
            if term_val > 0:
                has_positive = True

        if not (has_positive and has_negative):
            return None

        def _npv(rate: float) -> float:
            total = 0.0
            for t, cf in enumerate(cashflows):
                try:
                    total += cf / ((1.0 + rate) ** t)
                except Exception:
                    # Extremely unlikely (e.g. rate ~= -1); treat as large
                    # magnitude to steer bisection away.
                    total += float("inf") if cf > 0 else float("-inf")
            return total

        # Simple bisection between -99.9% and +100% annual effective rate.
        low = -0.999
        high = 1.0
        npv_low = _npv(low)
        npv_high = _npv(high)

        if npv_low == 0.0:
            return low
        if npv_high == 0.0:
            return high
        if npv_low * npv_high > 0:
            # No sign change → no guaranteed root in this range.
            return None

        mid = 0.0
        for _ in range(60):
            mid = (low + high) / 2.0
            npv_mid = _npv(mid)
            if abs(npv_mid) < 1e-6:
                break
            if npv_low * npv_mid < 0:
                high = mid
                npv_high = npv_mid
            else:
                low = mid
                npv_low = npv_mid
        return mid

    max_year: Optional[int] = None
    for r in rows:
        y_val = r.get("year")
        if isinstance(y_val, int):
            if max_year is None or y_val > max_year:
                max_year = y_val

    break_even_year = _first_break_even_year()

    irr_to_10: Optional[float] = None
    irr_to_20: Optional[float] = None
    irr_to_final: Optional[float] = None
    if max_year is not None:
        if max_year >= 10:
            irr_to_10 = _compute_irr_for_horizon(10)
        if max_year >= 20:
            irr_to_20 = _compute_irr_for_horizon(20)
        irr_to_final = _compute_irr_for_horizon(max_year)

    return {
        "productCode": product_block.get("code") or product_code,
        "productName": product_block.get("name"),
        "request": {
            "age": age_norm,
            "termYears": term_years,
            "riskClass": risk_class,
            "smokerClass": smoker_class,
            "faceAmount": face_amount,
            "premiumMode": premium_mode,
        },
        "templateScenarioId": best.get("id"),
        "projection": {
            "years": years,
            "rows": rows,
            "metrics": {
                "breakEvenYear": break_even_year,
                "maximumYear": max_year,
                "irr": {
                    "toYear10": irr_to_10,
                    "toYear20": irr_to_20,
                    "toFinalYear": irr_to_final,
                },
            },
        },
    }


_ILLUSTRATION_PROVIDERS["P12TRF"] = build_p12trf_illustration


def build_generic_term_illustration(product_code: str, request: Dict[str, Any]) -> Dict[str, Any]:
    """Generic on-demand illustration provider for term-style products.

    This reuses existing projections under ``projections/{product}/reviews``
    as templates and scales face-dependent fields to the requested face
    amount. It is intentionally conservative: when no compatible template
    exists for the requested term/premium mode, it returns a 400.
    """

    code = (product_code or "").strip().upper()
    code_lower = code.lower()

    # Normalise request inputs with conservative defaults.
    age_req = request.get("age")
    try:
        age_norm = int(age_req) if age_req is not None else None
    except (TypeError, ValueError):
        age_norm = None

    term_req = request.get("termYears")
    try:
        term_years = int(term_req) if term_req is not None else None
    except (TypeError, ValueError):
        term_years = None

    risk_class = (request.get("riskClass") or "").strip() or None
    smoker_class = (request.get("smokerClass") or "").strip() or None
    premium_mode_raw = (request.get("premiumMode") or "").strip()
    premium_mode = premium_mode_raw.upper() or "ANNUAL"

    face_req = request.get("faceAmount")
    try:
        face_amount = float(face_req) if face_req is not None else None
    except (TypeError, ValueError):
        face_amount = None

    if term_years is None or term_years <= 0:
        raise HTTPException(status_code=400, detail="termYears must be a positive integer.")
    if face_amount is None or face_amount <= 0:
        raise HTTPException(status_code=400, detail="faceAmount must be a positive number.")

    # Discover candidate projection artefacts for this product.
    prefix = f"projections/{code_lower}/reviews/"
    object_names = [name for name in _list_projection_objects(prefix=prefix) if name.endswith(".json")]
    if not object_names:
        raise HTTPException(status_code=400, detail="No projections available for this product.")

    candidates: List[Dict[str, Any]] = []
    for obj_name in object_names:
        try:
            data = get_projection(obj_name)
            scen_inputs, proj_table = _build_projection_inputs_and_table_from_summary(data)
        except Exception:
            continue
        if not proj_table:
            continue
        candidates.append({"object_name": obj_name, "inputs": scen_inputs, "projectionTable": proj_table})

    if not candidates:
        raise HTTPException(status_code=400, detail="No usable projection templates available for illustration.")

    def _score_template(entry: Dict[str, Any]) -> int:
        score = 0
        inputs = entry.get("inputs") or {}
        s_term = inputs.get("termYears")
        s_mode = (inputs.get("premiumMode") or "").upper()
        if isinstance(s_term, int) and s_term == term_years:
            score += 10
        if s_mode == premium_mode:
            score += 3
        return score

    best: Optional[Dict[str, Any]] = None
    best_score = -1
    for entry in candidates:
        score = _score_template(entry)
        if score > best_score:
            best_score = score
            best = entry

    if not best or best_score <= 0:
        raise HTTPException(
            status_code=400,
            detail="No compatible scenario template found for requested termYears/premiumMode.",
        )

    inputs = best.get("inputs") or {}
    projection_table = best.get("projectionTable") or []

    try:
        template_face = float(inputs.get("faceAmount") or 0.0)
    except (TypeError, ValueError):
        template_face = 0.0

    if template_face <= 0.0:
        template_face = face_amount

    scale = face_amount / template_face if template_face not in (0.0, None) else 1.0

    rows: List[Dict[str, Any]] = []
    cumulative_premium: Optional[float] = 0.0
    years: List[Any] = []

    for row in projection_table:
        if not isinstance(row, dict):
            continue
        year = row.get("year")
        attained_age = row.get("attainedAge")
        premium = row.get("premium")
        death_benefit = row.get("deathBenefit")
        cash_value = row.get("cashValue")

        # Adjust attained age if a numeric age was provided.
        if age_norm is not None and isinstance(inputs.get("age"), int) and isinstance(attained_age, int):
            base_issue_age = inputs.get("age")
            try:
                delta = age_norm - int(base_issue_age)
                attained_age = attained_age + delta
            except Exception:
                pass

        def _scaled(x: Any) -> Any:
            try:
                return float(x) * scale if x is not None else None
            except Exception:
                return x

        scaled_premium = _scaled(premium)
        scaled_death_benefit = _scaled(death_benefit)
        scaled_cash_value = _scaled(cash_value)

        cumulative_premium_value: Optional[float]
        if isinstance(scaled_premium, (int, float)):
            if cumulative_premium is None:
                cumulative_premium = float(scaled_premium)
            else:
                cumulative_premium += float(scaled_premium)
            cumulative_premium_value = cumulative_premium
        else:
            cumulative_premium_value = cumulative_premium

        if isinstance(scaled_cash_value, (int, float)):
            surrender_value: Optional[float] = float(scaled_cash_value)
        else:
            surrender_value = None

        if isinstance(scaled_death_benefit, (int, float)) and isinstance(scaled_cash_value, (int, float)):
            net_amount_at_risk: Optional[float] = float(scaled_death_benefit) - float(scaled_cash_value)
        else:
            net_amount_at_risk = None

        rows.append(
            {
                "year": year,
                "attainedAge": attained_age,
                "premium": scaled_premium,
                "cumulativePremium": cumulative_premium_value,
                "deathBenefit": scaled_death_benefit,
                "cashValue": scaled_cash_value,
                "surrenderValue": surrender_value,
                "netAmountAtRisk": net_amount_at_risk,
                "status": row.get("status"),
            }
        )

        if year is not None:
            years.append(year)

    # Lightweight decision hooks so a single projection is more actionable
    # for an actuary or product partner.

    def _first_break_even_year() -> Optional[int]:
        for r in rows:
            year_val = r.get("year")
            cv = r.get("cashValue")
            cp = r.get("cumulativePremium")
            if not isinstance(year_val, int):
                continue
            if not isinstance(cv, (int, float)) or not isinstance(cp, (int, float)):
                continue
            try:
                if float(cv) >= float(cp):
                    return year_val
            except Exception:
                continue
        return None

    def _compute_irr_for_horizon(horizon_year: int) -> Optional[float]:
        if horizon_year <= 0:
            return None

        by_year: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            y_val = r.get("year")
            if isinstance(y_val, int):
                by_year[y_val] = r

        if horizon_year not in by_year:
            return None

        cashflows: List[float] = []
        has_positive = False
        has_negative = False

        for y in range(1, horizon_year + 1):
            row = by_year.get(y) or {}
            prem = row.get("premium")
            try:
                prem_val = float(prem) if isinstance(prem, (int, float)) else 0.0
            except Exception:
                prem_val = 0.0
            cf = -prem_val
            if cf > 0:
                has_positive = True
            if cf < 0:
                has_negative = True
            cashflows.append(cf)

        terminal = by_year.get(horizon_year) or {}
        cv_term = terminal.get("cashValue")
        try:
            term_val = float(cv_term) if isinstance(cv_term, (int, float)) else 0.0
        except Exception:
            term_val = 0.0

        if cashflows:
            cashflows[-1] += term_val
            if term_val > 0:
                has_positive = True

        if not (has_positive and has_negative):
            return None

        def _npv(rate: float) -> float:
            total = 0.0
            for t, cf in enumerate(cashflows):
                try:
                    total += cf / ((1.0 + rate) ** t)
                except Exception:
                    total += float("inf") if cf > 0 else float("-inf")
            return total

        low = -0.999
        high = 1.0
        npv_low = _npv(low)
        npv_high = _npv(high)

        if npv_low == 0.0:
            return low
        if npv_high == 0.0:
            return high
        if npv_low * npv_high > 0:
            return None

        mid = 0.0
        for _ in range(60):
            mid = (low + high) / 2.0
            npv_mid = _npv(mid)
            if abs(npv_mid) < 1e-6:
                break
            if npv_low * npv_mid < 0:
                high = mid
                npv_high = npv_mid
            else:
                low = mid
                npv_low = npv_mid
        return mid

    max_year: Optional[int] = None
    for r in rows:
        y_val = r.get("year")
        if isinstance(y_val, int):
            if max_year is None or y_val > max_year:
                max_year = y_val

    break_even_year = _first_break_even_year()

    irr_to_10: Optional[float] = None
    irr_to_20: Optional[float] = None
    irr_to_final: Optional[float] = None
    if max_year is not None:
        if max_year >= 10:
            irr_to_10 = _compute_irr_for_horizon(10)
        if max_year >= 20:
            irr_to_20 = _compute_irr_for_horizon(20)
        irr_to_final = _compute_irr_for_horizon(max_year)

    product_block = {"code": code, "name": code}

    return {
        "productCode": product_block.get("code") or code,
        "productName": product_block.get("name"),
        "request": {
            "age": age_norm,
            "termYears": term_years,
            "riskClass": risk_class,
            "smokerClass": smoker_class,
            "faceAmount": face_amount,
            "premiumMode": premium_mode,
        },
        "templateScenarioId": None,
        "projection": {
            "years": years,
            "rows": rows,
            "metrics": {
                "breakEvenYear": break_even_year,
                "maximumYear": max_year,
                "irr": {
                    "toYear10": irr_to_10,
                    "toYear20": irr_to_20,
                    "toFinalYear": irr_to_final,
                },
            },
        },
    }


@app.post("/api/product-model-review/p12trf/evidence/seed")
def api_product_model_review_p12trf_seed_evidence() -> Dict[str, Any]:
    """Seed a small set of filing rule evidence rows for P12TRF.

    This is MVP-only and exists to prove the evidence model. It:
    - looks up the current Product Review for P12TRF,
    - uses the active filing_id and first document (when present), and
    - writes a couple of evidence rows linking that document to the
      traceability rules used in the Trust Surface.
    """

    product_code = "P12TRF"
    rec = get_product_review(product_code)
    if rec is None:
        raise HTTPException(status_code=400, detail="No Product Review draft found for P12TRF")

    meta = rec.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    review_state = meta.get("review") or {}
    if not isinstance(review_state, dict):
        review_state = {}

    filing_id = review_state.get("filing_id") if isinstance(review_state, dict) else None
    if isinstance(filing_id, str):
        filing_id = filing_id.strip() or None

    # Pick a representative document for this filing context.
    docs = list_product_documents(product_code, filing_id=filing_id)
    if not docs:
        raise HTTPException(status_code=400, detail="No documents available for current filing context")

    doc = docs[0]
    doc_path = str(doc.get("object_path") or "")
    if not doc_path:
        raise HTTPException(status_code=400, detail="Selected document has no object_path")

    # Best-effort clean slate: avoid duplicate seed rows for the same
    # product + filing in this MVP.
    try:
        from actuarypoc.storage.postgres_client import _conn  # type: ignore

        with _conn() as conn:  # type: ignore[call-arg]
            if conn is not None:
                with conn.cursor() as cur:  # type: ignore[assignment]
                    cur.execute(
                        "DELETE FROM filing_rule_evidence WHERE product_code = %s AND (filing_id = %s OR (%s IS NULL AND filing_id IS NULL))",
                        (product_code, filing_id, filing_id),
                    )
    except Exception:
        # If cleanup fails we still proceed with inserts; duplicates are
        # acceptable in this POC.
        pass

    seeded: List[Dict[str, Any]] = []

    # Seed two example evidence links to the existing POC traceability
    # rules so the UI can show document-tied rule evidence.
    seeded.append(
        record_filing_rule_evidence(
            product_code=product_code,
            filing_id=filing_id,
            document_path=doc_path,
            rule_id="rule_death_benefit_term",
            page_reference="p.22 (demo)",
            source_snippet=(
                "If the Insured dies while this policy is in force and before the end of the level term period, "
                "we will pay the Face Amount shown on the Policy Schedule."
            ),
            ai_interpretation="Confirms that death benefit equals the filed face amount during the level term only.",
            confidence="high",
        )
        or {}
    )

    seeded.append(
        record_filing_rule_evidence(
            product_code=product_code,
            filing_id=filing_id,
            document_path=doc_path,
            rule_id="rule_level_premiums",
            page_reference="p.12 (demo)",
            source_snippet="Annual Premium per $1,000 – 20-Year Level Term.",
            ai_interpretation="Confirms that premiums are level and driven by a rate per $1,000 of face.",
            confidence="high",
        )
        or {}
    )

    # Lightweight response summarising what was created.
    created = [s for s in seeded if s]
    return {
        "ok": True,
        "product_code": product_code,
        "filing_id": filing_id,
        "document_path": doc_path,
        "evidenceCount": len(created),
        "evidence": created,
    }


@app.post("/api/product-model-review/{product_code}/decision", response_model=ProductModelReviewDecisionResponse)
def api_product_model_review_decision(product_code: str, payload: ProductModelReviewDecisionRequest) -> ProductModelReviewDecisionResponse:  # type: ignore[valid-type]
    """Persist a simple Product Model Review decision for a product.

    This is intentionally MVP-only: a single reviewer records a decision
    for a given product, along with optional exclusions and free-text
    comments. There is no workflow engine, multi-user coordination, or
    permissions model at this stage.
    """

    decision = (payload.decision or "").strip().lower()
    if decision not in _ALLOWED_PMR_DECISIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported decision value '{payload.decision}'. Expected one of: {sorted(_ALLOWED_PMR_DECISIONS)}",
        )

    reviewer = (payload.reviewer or "").strip() or None
    exclusions = (payload.exclusions or "").strip() or None
    comments = (payload.comments or "").strip() or None

    # Capture the current evidence context (filing/generation, ProductDefinition
    # build, coverage summary, and validation summary) at decision time so that
    # the approved "package" is clearly linked to the decision.
    filing_id: Optional[str] = None
    generation_id: Optional[str] = None
    pd_generated_at: Optional[str] = None
    pd_generator_version: Optional[str] = None
    pd_warning_count: Optional[int] = None
    coverage_covered_count: Optional[int] = None
    coverage_partial_count: Optional[int] = None
    coverage_gap_count: Optional[int] = None
    coverage_not_applicable_count: Optional[int] = None
    validation_status: Optional[str] = None
    validation_pass_count: Optional[int] = None
    validation_warning_count: Optional[int] = None
    validation_fail_count: Optional[int] = None

    # Immutable evidence snapshot fields. For P12TRF we now require
    # these snapshots to be persisted successfully; failures surface as
    # 5xx responses instead of being silently ignored.
    product_definition_path: Optional[str] = None
    product_definition_hash: Optional[str] = None
    build_report_path: Optional[str] = None
    build_report_hash: Optional[str] = None
    coverage_matrix_path: Optional[str] = None
    coverage_matrix_hash: Optional[str] = None
    validation_report_path: Optional[str] = None
    validation_snapshot_hash: Optional[str] = None

    # For now the richer context (including snapshot persistence) is
    # only implemented for P12TRF; other products keep the simpler
    # decision record. Decisions are always stored using an
    # upper-cased product_code so that last-decision lookups remain
    # consistent regardless of the casing used at the API boundary.
    scenario_validation_snapshot: Optional[Dict[str, Any]] = None
    code_norm = product_code.strip().upper()
    if code_norm == "P12TRF":
        try:
            pmr = api_product_model_review_p12trf()
            review_meta = pmr.get("reviewMeta") or {}
            if isinstance(review_meta, dict):
                filing_id = review_meta.get("filingId")
                generation_id = review_meta.get("currentGeneration")
                coverage_covered_count = review_meta.get("coverageCoveredCount")
                coverage_partial_count = review_meta.get("coveragePartialCount")
                coverage_gap_count = review_meta.get("coverageGapCount")
                coverage_not_applicable_count = review_meta.get("coverageNotApplicableCount")

            pd_build = pmr.get("productDefinitionBuild") or {}
            if isinstance(pd_build, dict):
                pd_generated_at = pd_build.get("generatedAt")
                pd_generator_version = pd_build.get("generatorVersion")
                pd_warning_count = pd_build.get("warningCount")

            v = pmr.get("productDefinitionValidation") or None
            if isinstance(v, dict):
                validation_status = v.get("status")
                summary = v.get("summary") or {}
                if isinstance(summary, dict):
                    validation_pass_count = summary.get("pass")
                    validation_warning_count = summary.get("warning")
                    validation_fail_count = summary.get("fail")

            # Scenario validation snapshot: capture overall status and
            # summary counts so that decisions reflect model-behaviour
            # health at approval time.
            sv = pmr.get("scenarioValidation") or None
            if isinstance(sv, dict):
                scenario_validation_snapshot = sv
                scenario_validation_status = sv.get("status")
                sv_summary = sv.get("summary") or {}
                if isinstance(sv_summary, dict):
                    scenario_validation_pass_count = sv_summary.get("pass")
                    scenario_validation_warning_count = sv_summary.get("warning")
                    scenario_validation_fail_count = sv_summary.get("fail")

            # Immutable evidence snapshot fields: capture the exact
            # ProductDefinition/build artefacts and stable snapshots for
            # coverageMatrix and productDefinitionValidation. For P12TRF
            # we treat failures as fatal for the decision save.

            # Resolve artefact paths from the current filing context.
            if isinstance(filing_id, str):
                filing_norm = filing_id.strip()
            else:
                filing_norm = None

            if not filing_norm:
                raise HTTPException(
                    status_code=500,
                    detail="PMR decision snapshot missing filing_id for P12TRF",
                )

            product_definition_path = _product_definition_object_key(code_norm, filing_norm)
            build_report_path = _product_definition_build_report_key(code_norm, filing_norm)

            try:
                minio_client = get_minio_client()
                ensure_bucket(minio_client)
                bucket = get_bucket_name()
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[pmr_decision_snapshot] minio_init_failed product_code={code_norm} "
                    f"filing_id={filing_norm}: {exc}",
                    flush=True,
                )
                raise HTTPException(
                    status_code=500,
                    detail="Failed to initialise MinIO client for PMR decision snapshot",
                ) from exc

            # Hash exact JSON bytes for existing ProductDefinition artefact.
            try:
                response = minio_client.get_object(bucket, product_definition_path)
                try:
                    body = response.read()
                    if body:
                        product_definition_hash = sha256(body).hexdigest()
                finally:
                    response.close()
                    response.release_conn()
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[pmr_decision_snapshot] product_definition_hash_failed key={product_definition_path}: {exc}",
                    flush=True,
                )
                raise HTTPException(
                    status_code=500,
                    detail="Failed to read ProductDefinition artefact for PMR decision snapshot",
                ) from exc

            # Hash exact JSON bytes for existing build-report artefact.
            try:
                response = minio_client.get_object(bucket, build_report_path)
                try:
                    body = response.read()
                    if body:
                        build_report_hash = sha256(body).hexdigest()
                finally:
                    response.close()
                    response.release_conn()
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[pmr_decision_snapshot] build_report_hash_failed key={build_report_path}: {exc}",
                    flush=True,
                )
                raise HTTPException(
                    status_code=500,
                    detail="Failed to read ProductDefinition build-report for PMR decision snapshot",
                ) from exc

            # Persist coverageMatrix snapshot.
            import io
            import json

            coverage_matrix = pmr.get("coverageMatrix")
            if coverage_matrix is None:
                print(
                    f"[pmr_decision_snapshot] coverage_matrix_missing product_code={code_norm} "
                    f"filing_id={filing_norm}",
                    flush=True,
                )
                raise HTTPException(
                    status_code=500,
                    detail="PMR decision snapshot missing coverageMatrix for P12TRF",
                )

            coverage_matrix_path = _coverage_matrix_object_key(code_norm, filing_norm)
            try:
                body = json.dumps(
                    coverage_matrix,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                minio_client.put_object(
                    bucket,
                    coverage_matrix_path,
                    data=io.BytesIO(body),
                    length=len(body),
                    content_type="application/json",
                )
                coverage_matrix_hash = sha256(body).hexdigest()
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[pmr_decision_snapshot] coverage_matrix_write_failed key={coverage_matrix_path}: {exc}",
                    flush=True,
                )
                raise HTTPException(
                    status_code=500,
                    detail="Failed to persist coverageMatrix snapshot for PMR decision",
                ) from exc

            # Persist validation snapshot.
            validation_snapshot = pmr.get("productDefinitionValidation")
            if validation_snapshot is None:
                print(
                    f"[pmr_decision_snapshot] validation_snapshot_missing product_code={code_norm} "
                    f"filing_id={filing_norm}",
                    flush=True,
                )
                raise HTTPException(
                    status_code=500,
                    detail="PMR decision snapshot missing productDefinitionValidation for P12TRF",
                )

            validation_report_path = _validation_report_object_key(code_norm, filing_norm)
            try:
                body = json.dumps(
                    validation_snapshot,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                minio_client.put_object(
                    bucket,
                    validation_report_path,
                    data=io.BytesIO(body),
                    length=len(body),
                    content_type="application/json",
                )
                validation_snapshot_hash = sha256(body).hexdigest()
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[pmr_decision_snapshot] validation_report_write_failed key={validation_report_path}: {exc}",
                    flush=True,
                )
                raise HTTPException(
                    status_code=500,
                    detail="Failed to persist validation snapshot for PMR decision",
                ) from exc

            if not (
                coverage_matrix_path
                and coverage_matrix_hash
                and validation_report_path
                and validation_snapshot_hash
            ):
                raise HTTPException(
                    status_code=500,
                    detail="PMR decision snapshot incomplete for P12TRF (expected coverage and validation artefacts)",
                )

            print(
                "[pmr_decision_snapshot_debug] "
                f"code_norm={code_norm} filing_norm={filing_norm} "
                f"coverage_matrix_path={coverage_matrix_path} "
                f"coverage_matrix_hash={coverage_matrix_hash} "
                f"validation_report_path={validation_report_path} "
                f"validation_snapshot_hash={validation_snapshot_hash}",
                flush=True,
            )
        except HTTPException:
            # Re-raise FastAPI HTTP errors untouched.
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[pmr_decision_snapshot] unexpected_error: {exc}", flush=True)
            raise HTTPException(
                status_code=500,
                detail="Unexpected error while building PMR decision snapshot",
            ) from exc

    # Best-effort Postgres persistence. If Postgres is not configured or
    # unavailable, we still return a 200-level response with the echoed
    # payload so that the UI remains responsive, but in the Pi cluster we
    # expect POSTGRES_DSN to be set and the insert to succeed.
    rec = record_product_model_review_decision(
        product_code=code_norm,
        reviewer=reviewer,
        decision=decision,
        exclusions=exclusions,
        comments=comments,
        filing_id=filing_id,
        generation_id=generation_id,
        pd_generated_at=pd_generated_at,
        pd_generator_version=pd_generator_version,
        pd_warning_count=pd_warning_count,
        coverage_covered_count=coverage_covered_count,
        coverage_partial_count=coverage_partial_count,
        coverage_gap_count=coverage_gap_count,
        coverage_not_applicable_count=coverage_not_applicable_count,
        validation_status=validation_status,
        validation_pass_count=validation_pass_count,
        validation_warning_count=validation_warning_count,
        validation_fail_count=validation_fail_count,
        scenario_validation_status=scenario_validation_status,
        scenario_validation_pass_count=scenario_validation_pass_count,
        scenario_validation_warning_count=scenario_validation_warning_count,
        scenario_validation_fail_count=scenario_validation_fail_count,
        product_definition_path=product_definition_path,
        product_definition_hash=product_definition_hash,
        build_report_path=build_report_path,
        build_report_hash=build_report_hash,
        coverage_matrix_path=coverage_matrix_path,
        coverage_matrix_hash=coverage_matrix_hash,
        validation_report_path=validation_report_path,
        validation_snapshot_hash=validation_snapshot_hash,
    )

    # When Postgres persistence fails we still return a 200-level
    # response with the computed context, but we cannot build an
    # immutable evidence bundle without a stored decision ID.
    if rec is None:
        return ProductModelReviewDecisionResponse(
            id=None,
            product_code=product_code,
            reviewer=reviewer,
            decision=decision,
            exclusions=exclusions,
            comments=comments,
            created_at=None,
            filing_id=filing_id,
            generation_id=generation_id,
            pd_generated_at=pd_generated_at,
            pd_generator_version=pd_generator_version,
            pd_warning_count=pd_warning_count,
            coverage_covered_count=coverage_covered_count,
            coverage_partial_count=coverage_partial_count,
            coverage_gap_count=coverage_gap_count,
            coverage_not_applicable_count=coverage_not_applicable_count,
            validation_status=validation_status,
            validation_pass_count=validation_pass_count,
            validation_warning_count=validation_warning_count,
            validation_fail_count=validation_fail_count,
            scenario_validation_status=scenario_validation_status,
            scenario_validation_pass_count=scenario_validation_pass_count,
            scenario_validation_warning_count=scenario_validation_warning_count,
            scenario_validation_fail_count=scenario_validation_fail_count,
            product_definition_path=product_definition_path,
            product_definition_hash=product_definition_hash,
            build_report_path=build_report_path,
            build_report_hash=build_report_hash,
            coverage_matrix_path=coverage_matrix_path,
            coverage_matrix_hash=coverage_matrix_hash,
            validation_report_path=validation_report_path,
            validation_snapshot_hash=validation_snapshot_hash,
            bundle_path=None,
            bundle_hash=None,
        )

    # Build an immutable evidence bundle at decision time for P12TRF
    # decisions. Best-effort: failures are logged but do not block the
    # decision response.
    bundle_path: Optional[str] = None
    bundle_hash: Optional[str] = None
    try:
        if rec.get("product_code", "").strip().upper() == "P12TRF":
            decision_id = rec.get("id")
            filing_id_val = rec.get("filing_id") or filing_id
            generation_val = rec.get("generation_id") or generation_id

            if isinstance(decision_id, int) and isinstance(filing_id_val, str):
                bucket = get_bucket_name()
                minio_client = get_minio_client()
                ensure_bucket(minio_client)

                # Collect artefact bytes from MinIO using the paths
                # recorded with the decision.
                artefacts: Dict[str, bytes] = {}

                def _read_bytes(key: Optional[str], label: str) -> None:
                    if not key:
                        return
                    resp = minio_client.get_object(bucket, key)
                    try:
                        data = resp.read()
                    finally:
                        resp.close()
                        resp.release_conn()
                    artefacts[label] = data or b""

                _read_bytes(rec.get("product_definition_path"), "product-definition.json")
                _read_bytes(rec.get("build_report_path"), "build-report.json")
                _read_bytes(rec.get("coverage_matrix_path"), "coverage-matrix.json")
                _read_bytes(rec.get("validation_report_path"), "validation-report.json")

                # decision.json – frozen view of the decision record.
                decision_payload = {
                    k: v
                    for k, v in rec.items()
                    if k not in {"created_at"}
                }
                artefacts["decision.json"] = json.dumps(
                    decision_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")

                # manifest.json
                manifest = {
                    "bundleVersion": "v1",
                    "productCode": rec.get("product_code", product_code),
                    "filingId": filing_id_val,
                    "decisionId": decision_id,
                    "createdAt": rec.get("created_at") or datetime.utcnow().isoformat() + "Z",
                    "generationId": generation_val,
                }
                artefacts["manifest.json"] = json.dumps(
                    manifest,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")

                # scenario-validation.json – deterministic snapshot of
                # scenarioValidation at decision time. This is built
                # from the same PMR snapshot that fed the decision
                # context so that the bundle reflects model-behaviour
                # health "as approved".
                if scenario_validation_snapshot is not None:
                    try:
                        artefacts["scenario-validation.json"] = json.dumps(
                            scenario_validation_snapshot,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ).encode("utf-8")
                    except Exception:
                        # Best-effort only: failure to serialise the
                        # scenario validation snapshot should not
                        # block bundle creation.
                        pass

                # hashes.json – SHA256 for every file in the bundle.
                hashes: Dict[str, str] = {}
                for name, data in artefacts.items():
                    hashes[name] = sha256(data).hexdigest()
                artefacts["hashes.json"] = json.dumps(
                    hashes,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")

                # Build ZIP in-memory.
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for name, data in artefacts.items():
                        zf.writestr(name, data)
                bundle_bytes = buf.getvalue()
                bundle_hash = sha256(bundle_bytes).hexdigest()
                bundle_created_ts = datetime.utcnow().isoformat() + "Z"

                bundle_path = f"evidence-bundles/{code_norm}/{decision_id}/bundle.zip"
                minio_client.put_object(
                    bucket,
                    bundle_path,
                    data=io.BytesIO(bundle_bytes),
                    length=len(bundle_bytes),
                    content_type="application/zip",
                )

                # Persist bundle metadata back to Postgres.
                update_product_model_review_bundle(
                    decision_id=decision_id,
                    bundle_path=bundle_path,
                    bundle_hash=bundle_hash,
                    bundle_created_at=bundle_created_ts,
                )
    except Exception:
        # Best-effort only; bundle generation and metadata persistence
        # should not prevent the decision from being recorded.
        pass

    response = ProductModelReviewDecisionResponse(
        id=rec.get("id"),
        product_code=rec.get("product_code", product_code),
        reviewer=rec.get("reviewer", reviewer),
        decision=rec.get("decision", decision),
        exclusions=rec.get("exclusions", exclusions),
        comments=rec.get("comments", comments),
        created_at=str(rec.get("created_at")) if rec.get("created_at") is not None else None,
        filing_id=rec.get("filing_id"),
        generation_id=rec.get("generation_id"),
        pd_generated_at=rec.get("pd_generated_at"),
        pd_generator_version=rec.get("pd_generator_version"),
        pd_warning_count=rec.get("pd_warning_count"),
        coverage_covered_count=rec.get("coverage_covered_count"),
        coverage_partial_count=rec.get("coverage_partial_count"),
        coverage_gap_count=rec.get("coverage_gap_count"),
        coverage_not_applicable_count=rec.get("coverage_not_applicable_count"),
        validation_status=rec.get("validation_status"),
        validation_pass_count=rec.get("validation_pass_count"),
        validation_warning_count=rec.get("validation_warning_count"),
        validation_fail_count=rec.get("validation_fail_count"),
        scenario_validation_status=rec.get("scenario_validation_status"),
        scenario_validation_pass_count=rec.get("scenario_validation_pass_count"),
        scenario_validation_warning_count=rec.get("scenario_validation_warning_count"),
        scenario_validation_fail_count=rec.get("scenario_validation_fail_count"),
        product_definition_path=rec.get("product_definition_path"),
        product_definition_hash=rec.get("product_definition_hash"),
        build_report_path=rec.get("build_report_path"),
        build_report_hash=rec.get("build_report_hash"),
        coverage_matrix_path=rec.get("coverage_matrix_path"),
        coverage_matrix_hash=rec.get("coverage_matrix_hash"),
        validation_report_path=rec.get("validation_report_path"),
        validation_snapshot_hash=rec.get("validation_snapshot_hash"),
        bundle_path=bundle_path or rec.get("bundle_path"),
        bundle_hash=bundle_hash or rec.get("bundle_hash"),
    )

    return response


@app.get("/api/product-model-review/{product_code}/decisions/{decision_id}/bundle")
def api_product_model_review_decision_bundle(product_code: str, decision_id: int) -> Response:
    """Download the immutable evidence bundle ZIP for a specific decision.

    The decision is looked up case-insensitively by ``product_code`` and
    constrained by ``decision_id``. When a bundle exists, the exact ZIP bytes
    stored in MinIO are returned as ``application/zip`` with a stable
    filename.
    """

    code_norm = (product_code or "").strip().upper()
    if not code_norm:
        raise HTTPException(status_code=400, detail="product_code is required")

    rec = get_product_model_review_decision(code_norm, decision_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Decision not found for product")

    rec_code = (rec.get("product_code") or "").strip().upper()
    if rec_code != code_norm:
        raise HTTPException(status_code=404, detail="Decision product_code mismatch")

    bundle_path = rec.get("bundle_path")
    if not bundle_path:
        raise HTTPException(status_code=404, detail="Decision does not have an evidence bundle")

    try:
        minio_client = get_minio_client()
        ensure_bucket(minio_client)
        bucket = get_bucket_name()

        obj = minio_client.get_object(bucket, bundle_path)
        try:
            data = obj.read() or b""
        finally:
            obj.close()
            obj.release_conn()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        print(
            f"[pmr_bundle_download] failed product_code={code_norm} "
            f"decision_id={decision_id} bundle_path={bundle_path}: {exc}",
            flush=True,
        )
        raise HTTPException(status_code=500, detail="Failed to read evidence bundle from storage") from exc

    filename = f"{code_norm}-decision-{decision_id}-evidence-bundle.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return Response(content=data, media_type="application/zip", headers=headers)


@app.get("/api/product-model-review/{product_code}/decisions/{decision_id}/bundle/manifest")
def api_product_model_review_decision_bundle_manifest(product_code: str, decision_id: int) -> Dict[str, Any]:
    """Return manifest + hashes metadata for a decision's evidence bundle.

    This is a convenience endpoint for the Trust Surface UI so that users can
    quickly inspect which artefacts are included in a bundle without
    downloading the ZIP.
    """

    code_norm = (product_code or "").strip().upper()
    if not code_norm:
        raise HTTPException(status_code=400, detail="product_code is required")

    rec = get_product_model_review_decision(code_norm, decision_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Decision not found for product")

    rec_code = (rec.get("product_code") or "").strip().upper()
    if rec_code != code_norm:
        raise HTTPException(status_code=404, detail="Decision product_code mismatch")

    bundle_path = rec.get("bundle_path")
    if not bundle_path:
        raise HTTPException(status_code=404, detail="Decision does not have an evidence bundle")

    try:
        minio_client = get_minio_client()
        ensure_bucket(minio_client)
        bucket = get_bucket_name()

        obj = minio_client.get_object(bucket, bundle_path)
        try:
            bundle_bytes = obj.read() or b""
        finally:
            obj.close()
            obj.release_conn()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        print(
            f"[pmr_bundle_manifest] failed product_code={code_norm} "
            f"decision_id={decision_id} bundle_path={bundle_path}: {exc}",
            flush=True,
        )
        raise HTTPException(status_code=500, detail="Failed to read evidence bundle from storage") from exc

    entries: List[str] = []
    manifest: Dict[str, Any] = {}
    hashes: Dict[str, Any] = {}

    try:
        zf = zipfile.ZipFile(io.BytesIO(bundle_bytes), "r")
        entries = sorted(zf.namelist())

        if "manifest.json" in entries:
            try:
                manifest = json.loads(zf.read("manifest.json"))
            except Exception as exc:  # noqa: BLE001
                print(f"[pmr_bundle_manifest] manifest_parse_failed: {exc}", flush=True)
                manifest = {}

        if "hashes.json" in entries:
            try:
                hashes = json.loads(zf.read("hashes.json"))
            except Exception as exc:  # noqa: BLE001
                print(f"[pmr_bundle_manifest] hashes_parse_failed: {exc}", flush=True)
                hashes = {}
    except Exception as exc:  # noqa: BLE001
        print(f"[pmr_bundle_manifest] zip_inspect_failed: {exc}", flush=True)
        raise HTTPException(status_code=500, detail="Failed to inspect evidence bundle contents") from exc

    return {
        "decision_id": rec.get("id"),
        "product_code": rec.get("product_code"),
        "bundle_path": bundle_path,
        "entries": entries,
        "manifest": manifest,
        "hashes": hashes,
    }


# ---------------------------------------------------------------------------
# Product Review onboarding (MVP)
#
# These endpoints provide a lightweight, demo-focused flow that lets a user:
# - capture basic product metadata,
# - upload source documents into MinIO,
# - configure P12TRF PMR scenarios via a form instead of raw JSON, and
# - trigger scenario projections before landing in the existing Trust Surface.
#
# This deliberately avoids building a generic document management system,
# authentication, permissions, or multi-reviewer workflow.
# ---------------------------------------------------------------------------


@app.post("/api/product-review/draft")
def api_product_review_draft(payload: ProductReviewDraftRequest) -> Dict[str, Any]:
    product_code = (payload.product_code or "").strip().upper()
    if not product_code:
        raise HTTPException(status_code=400, detail="product_code is required")

    filing_id = (payload.filing_id or "").strip() or None

    review_meta: Dict[str, Any] = {"status": "draft"}
    if filing_id is not None:
        review_meta["filing_id"] = filing_id

    rec = upsert_product_review_draft(
        product_id=product_code,
        carrier=payload.carrier_name,
        product_name=payload.product_name,
        product_type=payload.product_type,
        review_metadata=review_meta,
    )
    if rec is None:
        # When Postgres is not configured we treat this as unavailable for
        # the MVP onboarding flow rather than trying to fake persistence.
        raise HTTPException(status_code=500, detail="Postgres not configured for Product Review drafts")

    meta = rec.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    review_state = meta.get("review") or {}
    if not isinstance(review_state, dict):
        review_state = {"status": "draft"}

    return {
        "product": {
            "code": rec.get("product_id", product_code),
            "name": meta.get("name") or payload.product_name,
            "type": meta.get("type") or payload.product_type,
            "carrier": rec.get("carrier") or payload.carrier_name,
        },
        "review": {
            "status": review_state.get("status", "draft"),
            "version": rec.get("version"),
            "filingId": review_state.get("filing_id"),
        },
    }


@app.post("/api/product-review/metadata/suggest")
def api_product_review_metadata_suggest(payload: ProductReviewMetadataSuggestionRequest) -> Dict[str, Any]:
    """Suggest basic Product Review metadata from filings via OpenAI.

    This endpoint uses MinIO-backed filings plus the OpenAI API to infer
    carrier_name, product_name, product_code, product_type, and a
    primary_filing_id for pre-filling the onboarding UI.
    """

    product_code_hint = (payload.productCodeHint or "").strip()
    filing_id_hint = (payload.filingIdHint or "").strip() or None
    model = (payload.model or "").strip() or None
    feedback = (payload.feedback or "").strip() or None
    previous = payload.previous or None

    if not product_code_hint:
        raise HTTPException(status_code=400, detail="productCodeHint is required")

    try:
        meta = generate_product_metadata_from_minio(
            product_code=product_code_hint,
            filing_id=filing_id_hint,
            model=model,
            feedback=feedback,
            previous=previous,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to derive metadata from filings: {exc}") from exc

    return meta


@app.post("/api/product-assumptions/ai-generate")
def api_product_assumptions_ai_generate(payload: ProductAssumptionsAIGenerateRequest) -> Dict[str, Any]:
    """Generate a draft AssumptionSet for a product using filings + OpenAI.

    This stage reads filings from MinIO for the hinted product/filing,
    calls the LLM-backed extractor to propose an AssumptionSet, and, by
    default, upserts it into the MinIO-backed registry. The resulting
    AssumptionSet is returned as JSON for inspection.
    """

    code = (payload.productCode or "").strip()
    filing = (payload.filingId or "").strip() or None
    set_id = (payload.setId or "").strip() or None
    model = (payload.model or "").strip() or None
    feedback = (payload.feedback or "").strip() or None
    previous = payload.previous or None

    if not code:
        raise HTTPException(status_code=400, detail="productCode is required")

    try:
        asn = generate_assumption_set_for_product(
            product_code=code,
            filing_id=filing,
            set_id=set_id,
            model=model,
            auto_upsert=True,
            feedback=feedback,
            previous=previous,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to generate AssumptionSet via OpenAI: {exc}") from exc

    # Best-effort DSL inspection so the AI Review Agent UI can show
    # *actual* assumptions (risk class mappings, face bands, etc.)
    # instead of only the registry JSON shell. This is advisory only
    # and should never block assumption extraction.
    dsl_preview: Dict[str, Any] = {}
    try:
        dsl_rel = (getattr(asn, "dsl_file", "") or "").strip()
    except Exception:
        dsl_rel = ""

    if dsl_rel:
        try:
            base = Path(__file__).resolve().parents[1]
            dsl_path = base / "dsl" / "examples" / dsl_rel
            if dsl_path.exists():
                formula = load_formula(str(dsl_path))

                meta_section = getattr(formula, "meta", None)
                meta_dict: Dict[str, Any] = meta_section if isinstance(meta_section, dict) else {}

                charges_preview: List[Dict[str, Any]] = []
                for ch in getattr(formula, "charges", []) or []:
                    charges_preview.append(
                        {
                            "name": getattr(ch, "name", None),
                            "formula": getattr(ch, "formula", None),
                            "description": getattr(ch, "description", None),
                            "optional": bool(getattr(ch, "optional", False)),
                        }
                    )

                rates_preview: List[Dict[str, Any]] = []
                for rate in getattr(formula, "credit_rates", []) or []:
                    rates_preview.append(
                        {
                            "rate_type": getattr(rate, "rate_type", None),
                            "expression": getattr(rate, "expression", None),
                            "description": getattr(rate, "description", None),
                        }
                    )

                dsl_preview = {
                    "dslFile": dsl_rel,
                    "meta": meta_dict,
                    "charges": charges_preview,
                    "creditRates": rates_preview,
                }
        except Exception:
            # DSL inspection is best-effort only.
            dsl_preview = {}

    return {"assumptionSet": asn.to_dict(), "dslPreview": dsl_preview}


@app.post("/api/product-scenarios/ai-generate")
def api_product_scenarios_ai_generate(payload: ProductScenariosAIGenerateRequest) -> Dict[str, Any]:
    """Generate a draft set of scenarios for a product using filings + OpenAI.

    This stage derives ScenarioConfig-style entries suitable for the
    onboarding UI. It supports feedback-driven retries by accepting a
    previous scenario list plus reviewer feedback.
    """

    code = (payload.productCode or "").strip()
    filing = (payload.filingId or "").strip() or None
    product_type = (payload.productType or "").strip() or None
    model = (payload.model or "").strip() or None
    feedback = (payload.feedback or "").strip() or None
    previous = payload.previous or None

    if not code:
        raise HTTPException(status_code=400, detail="productCode is required")

    try:
        scenarios = generate_scenarios_for_product(
            product_code=code,
            filing_id=filing,
            product_type=product_type,
            model=model,
            feedback=feedback,
            previous=previous,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to generate scenarios via OpenAI: {exc}") from exc

    return {"scenarios": scenarios}


@app.get("/api/product-mechanics/{product_code}")
def api_get_product_mechanics(product_code: str) -> Dict[str, Any]:
    """Return ProductMechanic entries for a product (advisory only).

    v0.1 supports a curated P12TRF mechanics file. For other products this
    returns an empty mechanics list; callers should treat the response as a
    best-effort preview, not a required contract.
    """

    code = (product_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="product_code is required")

    try:
        mechanics = load_mechanics_for_product(code)
        payload = mechanics_to_json(mechanics)
    except Exception:
        payload = []

    return {"productCode": code, "mechanics": payload}


def _build_product_review_payload(product_code: str) -> Dict[str, Any]:
    code = product_code.strip().upper()

    rec = get_product_review(code)
    meta = (rec or {}).get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    review_state = meta.get("review") or {}
    if not isinstance(review_state, dict):
        review_state = {}

    filing_id = review_state.get("filing_id") if isinstance(review_state, dict) else None
    if isinstance(filing_id, str):
        filing_id = filing_id.strip() or None

    docs = list_product_documents(code, filing_id=filing_id)

    # Map stored internal scenarios (when present) back into the
    # UI-friendly ScenarioConfig shape. When none are present we first
    # try ProductDefinition-driven defaults, then fall back to the
    # bundled P12TRF fixture.
    scenarios_ui: List[Dict[str, Any]] = []
    internal_scenarios = review_state.get("scenarios") if isinstance(review_state, dict) else None
    if isinstance(internal_scenarios, list) and internal_scenarios:
        for s in internal_scenarios:
            try:
                sid = str(s.get("id")) if isinstance(s, dict) else ""
            except Exception:  # pragma: no cover - extremely defensive
                sid = ""
            if not sid:
                continue
            name = s.get("name") if isinstance(s, dict) else None
            policy = s.get("policy") if isinstance(s, dict) else None
            if not isinstance(policy, dict):
                policy = {}
            scenarios_ui.append(
                {
                    "id": sid,
                    "name": name or f"Scenario {sid}",
                    "age": policy.get("issue_age"),
                    "sex": policy.get("gender"),
                    "smokerClass": policy.get("smoker_class"),
                    "riskClass": policy.get("risk_class"),
                    "faceAmount": policy.get("face_amount"),
                    "levelPeriod": policy.get("level_period"),
                    "premiumMode": policy.get("premium_mode"),
                    "modalPremium": policy.get("modal_premium"),
                    "initialDeposit": policy.get("initial_deposit"),
                    "faceBand": policy.get("face_band"),
                    "purpose": s.get("purpose"),
                    "dimensionsExercised": s.get("dimensions_exercised"),
                    "source": s.get("source"),
                }
            )

    # When no scenarios have been configured yet, prefer
    # ProductDefinition-driven suggestions when available. For the
    # historical P12TRF POC, we fall back to the bundled fixture.
    if not scenarios_ui:
        pd_scenarios = _default_p12trf_scenarios_from_product_definition(code, filing_id)
        if code == "P12TRF":
            scenarios_ui = pd_scenarios or _default_p12trf_scenarios_for_ui()
        else:
            scenarios_ui = pd_scenarios

    # Derive lightweight "upload insights" for the onboarding flow. These
    # are intentionally advisory and best-effort only; failures should not
    # break the core Product Review API.
    upload_insights: Dict[str, Any] = {
        "productCode": code,
        "productName": meta.get("name") or code,
        "productType": meta.get("type") or "",
        "carrierName": (rec or {}).get("carrier") or "",
    }

    # Surface DSL-backed formulas (charges and credit rates) so the
    # Document Upload step can show actuaries which fees/interest/COI
    # structures the engine is currently using for this product.
    dsl_charges: List[Dict[str, Any]] = []
    dsl_rates: List[Dict[str, Any]] = []
    missing_docs: List[Dict[str, Any]] = []

    try:
        base = Path(__file__).resolve().parents[1]
        # For the historical P12TRF POC we know the DSL file explicitly.
        # For other products we fall back to a conventional
        # ``{product_code_lower}.yaml`` name when present.
        if code == "P12TRF":
            dsl_path = base / "dsl" / "examples" / "p12trf_term.yaml"
        else:
            dsl_path = base / "dsl" / "examples" / f"{code.lower()}.yaml"
        if dsl_path.exists():
            formula = load_formula(str(dsl_path))
            for ch in getattr(formula, "charges", []) or []:
                dsl_charges.append(
                    {
                        "name": getattr(ch, "name", None),
                        "formula": getattr(ch, "formula", None),
                        "description": getattr(ch, "description", None),
                        "optional": bool(getattr(ch, "optional", False)),
                    }
                )
            for rate in getattr(formula, "credit_rates", []) or []:
                dsl_rates.append(
                    {
                        "rate_type": getattr(rate, "rate_type", None),
                        "expression": getattr(rate, "expression", None),
                        "description": getattr(rate, "description", None),
                    }
                )

            # When the DSL exposes source_documents in meta, treat these as
            # a desired checklist and flag any that do not appear among the
            # currently uploaded documents for this Product Review.
            meta_section = getattr(formula, "meta", None) or {}
            src_docs = meta_section.get("source_documents") if isinstance(meta_section, dict) else None
            if isinstance(src_docs, dict):
                # Build a set of uploaded basenames for quick matching.
                uploaded_basenames = []
                for d in docs:
                    op = d.get("object_path") or ""
                    try:
                        uploaded_basenames.append(Path(str(op)).name.lower())
                    except Exception:
                        continue

                for key, path_value in src_docs.items():
                    try:
                        basename = Path(str(path_value)).name.lower()
                    except Exception:
                        basename = str(path_value).lower()
                    found = False
                    for ub in uploaded_basenames:
                        if not ub:
                            continue
                        # Treat either an exact filename match or a
                        # substring match as satisfying the requirement;
                        # this keeps things resilient to timestamped
                        # prefixes in MinIO object names.
                        if ub == basename or basename in ub or ub in basename:
                            found = True
                            break
                    if not found:
                        missing_docs.append(
                            {
                                "id": str(key),
                                "expectedPath": str(path_value),
                            }
                        )

            # Compute face bands for scenarios from DSL meta.face_bands
            # where available. This gives actuaries quick feedback on
            # which band a given scenario's face amount falls into without
            # having to cross-reference tables.
            if isinstance(meta_section, dict):
                fb_cfg = meta_section.get("face_bands")

                def _band_for_face(face: Any) -> Optional[Any]:
                    if not isinstance(fb_cfg, list):
                        return None
                    try:
                        fa_val = float(face)
                    except (TypeError, ValueError):
                        return None
                    for band_def in fb_cfg:
                        if not isinstance(band_def, dict):
                            continue
                        band_id = band_def.get("band")
                        try:
                            mn = float(band_def.get("min")) if band_def.get("min") is not None else None
                        except (TypeError, ValueError):
                            mn = None
                        try:
                            mx = float(band_def.get("max")) if band_def.get("max") is not None else None
                        except (TypeError, ValueError):
                            mx = None
                        if mn is not None and fa_val < mn:
                            continue
                        if mx is not None and fa_val > mx:
                            continue
                        return band_id
                    return None

                if isinstance(scenarios_ui, list) and fb_cfg:
                    for row in scenarios_ui:
                        try:
                            fa = row.get("faceAmount") if isinstance(row, dict) else None
                        except Exception:
                            fa = None
                        if fa is None:
                            continue
                        band_id = _band_for_face(fa)
                        if band_id is not None:
                            row.setdefault("faceBand", band_id)
    except Exception:
        # DSL inspection is advisory only; ignore any failures here.
        pass

    upload_insights["dslCharges"] = dsl_charges
    upload_insights["dslCreditRates"] = dsl_rates
    upload_insights["missingDocuments"] = missing_docs

    # Show which AssumptionSets currently exist for this product so the
    # onboarding flow can call out gaps in assumption coverage.
    try:
        asn_for_product: List[Dict[str, Any]] = []
        for a in list_assumption_sets():
            try:
                if (a.product_code or "").strip().upper() != code:
                    continue
            except Exception:
                continue
            asn_for_product.append(
                {
                    "id": a.id,
                    "description": a.description,
                    "dsl_file": a.dsl_file,
                    "actuarial_prefix": a.actuarial_prefix,
                    "status": a.status,
                    "is_current": a.is_current,
                }
            )
        upload_insights["assumptionSets"] = asn_for_product
    except Exception:
        # MinIO/Postgres may not be configured; treat as advisory only.
        upload_insights["assumptionSets"] = []

    # Optionally surface a tiny sample projection for validation based on
    # the existing P12TRF scenario artefacts when present. This avoids
    # triggering additional projection work from the onboarding step while
    # still giving actuaries something concrete to compare against.
    sample_projection: Optional[Dict[str, Any]] = None
    if code == "P12TRF":
        try:
            proj_key = "projections/p12trf/scenarios/S1.json"
            data = get_projection(proj_key)
            rd = _build_run_detail(proj_key, data)
            policy_input = (rd.get("policy_input") or {})
            core = policy_input.get("core_fields") or {}
            proj_summary = rd.get("projection_summary") or {}
            years = proj_summary.get("years") or []
            death_benefits = proj_summary.get("death_benefits") or []
            premiums = proj_summary.get("expected_premiums") or []

            sample_projection = {
                "key": proj_key,
                "inputs": {
                    "issue_age": core.get("issue_age"),
                    "gender": core.get("gender"),
                    "smoker_class": core.get("smoker_class"),
                    "risk_class": core.get("risk_class"),
                    "face_amount": core.get("face_amount"),
                    "level_period": core.get("level_period"),
                    "premium_mode": core.get("premium_mode"),
                },
                "projection": {
                    "years": years[:5],
                    "death_benefits": death_benefits[:5],
                    "expected_premiums": premiums[:5],
                },
            }
        except Exception:
            sample_projection = None

    upload_insights["sampleProjection"] = sample_projection

    return {
        "product": {
            "code": code,
            "name": meta.get("name") or code,
            "type": meta.get("type") or "",
            "carrier": (rec or {}).get("carrier") or "",
        },
        "review": {
            "status": review_state.get("status", "draft"),
            "filingId": review_state.get("filing_id"),
            "currentGeneration": review_state.get("current_generation"),
            "generatedAt": review_state.get("generated_at"),
            "writtenKeys": review_state.get("written_keys") or [],
        },
        "documents": [
            {
                "id": d.get("id"),
                "kind": d.get("kind"),
                "description": d.get("description"),
                "objectPath": d.get("object_path"),
                "createdAt": d.get("created_at"),
            }
            for d in docs
        ],
        "scenarios": scenarios_ui,
        "uploadInsights": upload_insights,
    }


@app.get("/api/product-review/{product_code}")
def api_get_product_review(product_code: str) -> Dict[str, Any]:
    code = (product_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="product_code is required")
    return _build_product_review_payload(code)


@app.post("/api/product-review/{product_code}/documents")
async def api_upload_product_review_document(
    product_code: str,
    file: UploadFile = File(...),
    kind: str = Form("filing"),
    description: str = Form(""),
) -> Dict[str, Any]:
    code = (product_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="product_code is required")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    # Filing context from the current Product Review, when available.
    existing = get_product_review(code) or {}
    meta = existing.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    review_state = meta.get("review") or {}
    if not isinstance(review_state, dict):
        review_state = {}
    filing_id_val = review_state.get("filing_id") if isinstance(review_state, dict) else None
    if isinstance(filing_id_val, str):
        filing_id_val = filing_id_val.strip() or None

    suffix = (Path(file.filename).suffix or "").lower()
    allowed_suffixes = {".pdf", ".docx", ".xlsx", ".csv"}
    if suffix not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="Unsupported file type; expected PDF, DOCX, XLSX, or CSV")

    client = get_minio_client()
    ensure_bucket(client)
    bucket = get_bucket_name()

    safe_name = Path(file.filename).name
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")

    if filing_id_val is not None:
        object_name = f"docs/{code}/{filing_id_val}/{timestamp}-{safe_name}"
    else:
        object_name = f"docs/{code}/unassigned/{timestamp}-{safe_name}"

    content = await file.read()
    size = len(content)
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty file upload is not allowed")

    import io as _io

    client.put_object(
        bucket,
        object_name,
        _io.BytesIO(content),
        length=size,
        content_type=file.content_type or "application/octet-stream",
    )

    meta_description = description or safe_name
    doc_rec = record_document_upload(
        product_id=code,
        kind=kind or "filing",
        description=meta_description,
        object_path=object_name,
        object_hash=None,
        filing_id=filing_id_val,
    )

    # Return the updated view for convenience.
    payload = _build_product_review_payload(code)
    if doc_rec is not None:
        payload["lastUploaded"] = {
            "id": doc_rec.get("id"),
            "kind": doc_rec.get("kind"),
            "description": doc_rec.get("description"),
            "objectPath": doc_rec.get("object_path"),
            "createdAt": doc_rec.get("created_at"),
        }
    return payload


@app.put("/api/product-review/{product_code}/scenarios")
def api_save_product_review_scenarios(product_code: str, payload: ScenarioConfigPayload) -> Dict[str, Any]:
    code = (product_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="product_code is required")

    existing = get_product_review(code) or {}
    meta = existing.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    review_state = meta.get("review") or {}
    if not isinstance(review_state, dict):
        review_state = {}

    internal_scenarios = _ui_scenarios_to_internal(code, payload.scenarios or [])
    review_state = dict(review_state)
    review_state["scenarios"] = internal_scenarios
    review_state.setdefault("status", "draft")

    # Preserve basic product strings when available.
    product_name = meta.get("name") or code
    product_type = meta.get("type") or ""
    carrier = existing.get("carrier") or ""

    rec = upsert_product_review_draft(
        product_id=code,
        carrier=carrier,
        product_name=product_name,
        product_type=product_type,
        review_metadata=review_state,
    )
    if rec is None:
        raise HTTPException(status_code=500, detail="Failed to persist scenario configuration")

    return _build_product_review_payload(code)


@app.post("/api/product-review/{product_code}/generate")
def api_generate_product_review(product_code: str) -> Dict[str, Any]:
    code = (product_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="product_code is required")

    # Generation identifier for this Product Review run. We use an
    # ISO-like UTC timestamp that is easy to read and sort.
    now = datetime.utcnow()
    generation_id = now.strftime("%Y%m%dT%H%M%SZ")
    generated_at = now.isoformat() + "Z"

    rec = get_product_review(code)
    meta = (rec or {}).get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    review_state = meta.get("review") or {}
    if not isinstance(review_state, dict):
        review_state = {}

    internal_scenarios = review_state.get("scenarios") if isinstance(review_state, dict) else None
    if not isinstance(internal_scenarios, list) or not internal_scenarios:
        # Fallback to bundled defaults when UI-configured scenarios are
        # missing. This keeps the demo usable even if the onboarding flow
        # was partially completed.
        from pathlib import Path as _Path
        import json as _json

        scenarios_path = _PROJECT_ROOT / "examples" / "p12trf_scenarios.json"
        if not scenarios_path.exists():
            raise HTTPException(status_code=400, detail="No scenarios configured for P12TRF and default fixture is missing")
        try:
            payload = _json.loads(scenarios_path.read_text(encoding="utf-8"))
            internal_scenarios = payload.get("scenarios") or []
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to load default scenarios: {exc}") from exc

    if not internal_scenarios:
        raise HTTPException(status_code=400, detail="No scenarios available for Product Review generation")

    written_keys = _generate_term_scenarios_from_config(
        internal_scenarios,
        years=40,
        generation_id=generation_id,
        product_code=code,
        generated_at=generated_at,
    )

    # Best-effort: mark the review as generated so future GETs can reflect
    # that state. We deliberately do not fail the call if this update fails.
    try:
        review_state = dict(review_state)
        review_state["status"] = "generated"
        review_state["current_generation"] = generation_id
        review_state["generated_at"] = generated_at
        review_state["written_keys"] = written_keys
        product_name = meta.get("name") or code
        product_type = meta.get("type") or ""
        carrier = (rec or {}).get("carrier") or ""
        upsert_product_review_draft(
            product_id=code,
            carrier=carrier,
            product_name=product_name,
            product_type=product_type,
            review_metadata=review_state,
        )
    except Exception:
        # Log via the shared failure counter but otherwise ignore.
        pass

    # Include the product code in the default redirect so the Trust Surface
    # can open directly on the relevant product.
    return {
        "ok": True,
        "generation_id": generation_id,
        "generated_at": generated_at,
        "written": written_keys,
        "redirectUrl": f"/web?view=product-model&productCode={code}",
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": getattr(app, "version", None),
        "started_at": BUILD_STARTED_AT,
    }


def _list_projection_objects(prefix: str = "projections/") -> List[str]:
    client = get_minio_client()
    bucket = get_bucket_name()
    objects = []
    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        objects.append(obj.object_name)
    return sorted(objects)


def _list_minio_prefix(prefix: str = "") -> Dict[str, Any]:
    """Return a shallow listing of the MinIO bucket under a given prefix.

    This is a dev-only helper used by the /ui/dev object browser and
    /api/dev/objects endpoint. It discovers immediate child "directories"
    and objects under the supplied prefix without recursing arbitrarily
    deep into the tree.
    """

    client = get_minio_client()
    bucket = get_bucket_name()

    norm_prefix = prefix or ""
    dirs: set[str] = set()
    files: List[Dict[str, Any]] = []

    for obj in client.list_objects(bucket, prefix=norm_prefix, recursive=True):
        name = obj.object_name
        if not name.startswith(norm_prefix):
            continue
        remainder = name[len(norm_prefix) :]
        if "/" in remainder:
            head = remainder.split("/", 1)[0]
            dirs.add(f"{norm_prefix}{head}/")
        else:
            files.append(
                {
                    "name": name,
                    "size": getattr(obj, "size", None),
                    "lastModified": getattr(obj, "last_modified", None).isoformat()
                    if getattr(obj, "last_modified", None)
                    else None,
                }
            )

    return {
        "bucket": bucket,
        "prefix": norm_prefix,
        "directories": sorted(dirs),
        "objects": files,
    }


def _load_projection_summary(object_name: str) -> Optional[Dict[str, Any]]:
    """Load one projection and extract a small summary.

    Returns None if the object cannot be parsed as JSON.
    """
    from json import JSONDecodeError
    import json

    if not object_name.startswith("projections/"):
        object_name = f"projections/{object_name}"

    client = get_minio_client()
    bucket = get_bucket_name()
    try:
        response = client.get_object(bucket, object_name)
    except Exception:
        return None

    try:
        data = json.loads(response.read().decode("utf-8"))
    except JSONDecodeError:
        return None
    finally:
        response.close()
        response.release_conn()

    inputs = data.get("inputs", {})
    return {
        "object_name": object_name,
        "generated_at": data.get("generated_at"),
        "policy_id": inputs.get("policy_id"),
        "product_code": inputs.get("product_code"),
        "assumption_set_id": inputs.get("assumption_set_id"),
    }


def _load_json_from_minio(object_name: str) -> Dict[str, Any]:
    """Load a JSON object from MinIO by key.

    Raises HTTPException if the object cannot be found or parsed.
    """

    import json
    from json import JSONDecodeError

    client = get_minio_client()
    bucket = get_bucket_name()
    try:
        response = client.get_object(bucket, object_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"Object not found: {object_name}") from exc

    try:
        data = json.loads(response.read().decode("utf-8"))
    except JSONDecodeError as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Invalid JSON object: {object_name}") from exc
    finally:
        response.close()
        response.release_conn()

    return data


@app.get("/projections")
def list_projections() -> Dict[str, Any]:
    """Return a list of available projection JSON objects in MinIO."""
    objs = _list_projection_objects()
    return {"count": len(objs), "objects": objs}


@app.get("/api/dev/objects")
def api_dev_objects(prefix: str = Query("", description="Object key prefix to browse")) -> Dict[str, Any]:
    """List immediate prefixes and objects under a MinIO prefix (dev-only).

    This endpoint is intentionally simple and unpaginated; it is meant for
    local debugging and exploration of the object store, not as a
    production-grade listing API.
    """

    try:
        return _list_minio_prefix(prefix)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to list objects from MinIO: {exc}") from exc


@app.get("/api/dev/object")
def api_dev_object(key: str = Query(..., description="Exact object key to download")) -> Response:
    """Download a single object from MinIO as an HTTP response (dev-only)."""

    client = get_minio_client()
    bucket = get_bucket_name()

    try:
        resp = client.get_object(bucket, key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"Object not found: {key}") from exc

    try:
        body = resp.read()
        content_type = resp.headers.get("Content-Type", "application/octet-stream")  # type: ignore[union-attr]
    finally:
        try:
            resp.close()
            resp.release_conn()
        except Exception:
            pass

    filename = Path(key).name or "object"
    headers = {"Content-Disposition": f"attachment; filename=\"{filename}\""}
    return Response(content=body, media_type=content_type, headers=headers)


@app.get("/projections/{object_name:path}")
def get_projection(object_name: str) -> Dict[str, Any]:
    """Fetch a specific projection JSON by its object key under projections/."""
    if not object_name.startswith("projections/"):
        object_name = f"projections/{object_name}"

    client = get_minio_client()
    bucket = get_bucket_name()
    try:
        response = client.get_object(bucket, object_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"Projection not found: {object_name}") from exc

    import json

    try:
        data = json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
        response.release_conn()

    return data


@app.get("/api/run-detail/{object_name:path}")
def api_run_detail(object_name: str) -> Dict[str, Any]:
    """Return a RunDetail-style JSON payload for a given projection object.

    This is a UI-facing endpoint: it interprets existing projection snapshots
    and associated inputs; it does not trigger new projections.
    """

    if not object_name.startswith("projections/"):
        object_name = f"projections/{object_name}"

    data = get_projection(object_name)
    return _build_run_detail(object_name, data)


@app.get("/api/run-detail")
def api_run_detail_query(key: str = Query(..., description="Projection object key under projections/")) -> Dict[str, Any]:
    """Query-param variant of run-detail endpoint.

    This is friendlier for front-ends that want to pass an object key as a
    query parameter instead of part of the path.
    """

    object_name = key
    if not object_name.startswith("projections/"):
        object_name = f"projections/{object_name}"

    data = get_projection(object_name)
    return _build_run_detail(object_name, data)


def _load_pas_record(pas_ref: Optional[str], policy_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Load a single PAS record used for a run, if available.

    pas_ref is either a MinIO object key or a file:// path to a local JSON
    document with a top-level "records" list.
    """

    if not pas_ref:
        return None

    import json
    from json import JSONDecodeError
    import os

    # File-based PAS snapshot
    if pas_ref.startswith("file://"):
        path = pas_ref[len("file://") :]
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, JSONDecodeError):  # pragma: no cover - defensive
            return None
    else:
        # MinIO-based PAS snapshot
        client = get_minio_client()
        bucket = get_bucket_name()
        try:
            response = client.get_object(bucket, pas_ref)
        except Exception:  # noqa: BLE001
            return None
        try:
            payload = json.loads(response.read().decode("utf-8"))
        except JSONDecodeError:  # noqa: BLE001
            return None
        finally:
            response.close()
            response.release_conn()

    records = payload.get("records", []) if isinstance(payload, dict) else []
    if not records:
        return None

    # Prefer an exact policy_id match when available.
    if policy_id:
        for rec in records:
            if str(rec.get("policy_id")) == str(policy_id) or str(rec.get("policy_number")) == str(policy_id):
                return rec

    # Fallback: just take the first record.
    return records[0]


def _build_audit_summary(product_code: str, run_id: str) -> Optional[Dict[str, Any]]:
    """Load a small AuditRecord summary for a given product/run.

    This reads ``audit/<product_code>/<run_id>/audit_record.json`` when
    present and extracts only metadata fields that are safe for the
    RunDetail/UI layer. Missing or invalid objects result in ``None``.
    """

    if not product_code or not run_id:
        return None

    object_name = f"audit/{product_code}/{run_id}/audit_record.json"

    try:
        record = _load_json_from_minio(object_name)
    except HTTPException:
        # No AuditRecord for this run – treat as "no audit" rather than
        # failing the RunDetail API.
        return None
    except Exception:
        return None

    product = record.get("product") or {}
    engine = record.get("engine") or {}
    assumptions = record.get("assumptions") or []
    dsl = record.get("dsl") or {}

    assumption_ids: List[str] = []
    for a in assumptions or []:
        if isinstance(a, dict):
            asn_id = a.get("assumption_set_id")
            if asn_id:
                assumption_ids.append(str(asn_id))

    return {
        "run_id": record.get("run_id") or run_id,
        "audit_record_object": object_name,
        "product_code": product.get("product_code") or product_code,
        "assumption_set_ids": assumption_ids,
        "dsl_file": dsl.get("file"),
        "engine_version": engine.get("engine_version"),
        "runner_image": engine.get("runner_image"),
        "created_at": record.get("created_at") or record.get("generated_at"),
    }


def _build_run_detail(object_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Construct a RunDetail-style payload from a stored projection summary.

    This endpoint is intentionally read-only and UI-focused: it does not
    write anything back to MinIO; it interprets existing projection snapshots
    and associated inputs.
    """

    inputs = data.get("inputs", {}) or {}
    projection = data.get("projection", {}) or {}
    metadata = data.get("metadata", {}) or {}
    warnings = data.get("warnings", []) or []

    # Stable run identifier for downstream artefacts.
    run_id = str(inputs.get("run_id") or object_name)

    # 1) Policy input via PAS
    pas_ref = inputs.get("pas_object")
    policy_id = inputs.get("policy_id")
    pas_rec = _load_pas_record(pas_ref, policy_id)

    policy_inputs = inputs.get("policy_inputs") if isinstance(inputs, dict) else None
    if not isinstance(policy_inputs, dict):
        policy_inputs = {}

    policy_number = str(pas_rec.get("policy_number") if pas_rec else policy_id or "")
    product_code = str(inputs.get("product_code") or pas_rec.get("product_code") if pas_rec else "")
    product_type = str(pas_rec.get("product_type") if pas_rec else "")

    def _num(rec: Optional[Dict[str, Any]], key: str, default: float = 0.0, fallback: Optional[Any] = None) -> float:
        """Numeric helper with optional fallback from policy_inputs.

        Prefer PAS values when present; when PAS is thin (e.g. POC exports
        that only carry a subset of fields), fall back to any value surfaced
        in the projection summary's policy_inputs block. We deliberately do
        not fabricate values: when neither source has a usable number, we
        return the provided default.
        """

        raw = None
        if rec:
            raw = rec.get(key, None)
        if (raw is None or raw == "" or raw == 0) and fallback is not None:
            raw = fallback
        if raw is None or raw == "" or raw == 0:
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def _int(rec: Optional[Dict[str, Any]], key: str, default: int = 0, fallback: Optional[Any] = None) -> int:
        raw = None
        if rec:
            raw = rec.get(key, None)
        if (raw is None or raw == "" or raw == 0) and fallback is not None:
            raw = fallback
        if raw is None or raw == "" or raw == 0:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    issue_age = _int(pas_rec, "issue_age", 0, fallback=policy_inputs.get("issue_age"))

    def _str_field(primary_rec: Optional[Dict[str, Any]], key: str, fallback_key: str) -> str:
        if primary_rec is not None:
            val = primary_rec.get(key)
            if isinstance(val, str) and val.strip():
                return val
        val = policy_inputs.get(fallback_key)
        if isinstance(val, str) and val.strip():
            return val
        return ""

    gender = _str_field(pas_rec, "gender", "gender")
    smoker_class = _str_field(pas_rec, "smoker_class", "smoker_class")
    risk_class = _str_field(pas_rec, "risk_class", "risk_class")

    face_amount = _num(pas_rec, "face_amount", 0.0, fallback=policy_inputs.get("face_amount"))
    level_period = _int(pas_rec, "level_period", 0, fallback=policy_inputs.get("level_period"))

    premium_mode_raw = None
    if pas_rec is not None:
        premium_mode_raw = pas_rec.get("premium_mode")
    if not premium_mode_raw:
        premium_mode_raw = policy_inputs.get("premium_mode")
    premium_mode = str(premium_mode_raw or "")

    pas_modal_premium = _num(pas_rec, "modal_premium", 0.0)

    # 2) Formula + meta for premium table + docs
    formula_path = inputs.get("formula_path")
    formula_meta: Dict[str, Any] = {}
    try:
        if formula_path:
            formula = load_formula(str(formula_path))
            formula_meta = getattr(formula, "meta", {}) or {}
    except Exception:
        formula_meta = {}

    premium_table_cfg = formula_meta.get("premium_table") if isinstance(formula_meta, dict) else None

    premium_service: Optional[PremiumLookupService] = None
    premium_table_object: Optional[str] = inputs.get("premium_table_object")

    # Build a premium lookup service from MinIO when premium_table is configured.
    if isinstance(premium_table_cfg, dict) and premium_table_cfg.get("source") == "minio" and premium_table_cfg.get("format") == "csv":
        import csv
        import io as _io

        client = get_minio_client()
        bucket = get_bucket_name()

        # Prefer the exact object recorded in the projection summary when present.
        obj_name = premium_table_object
        if not obj_name:
            prefix = premium_table_cfg.get("prefix")
            if prefix:
                latest = None
                for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
                    if latest is None or obj.last_modified > latest.last_modified:
                        latest = obj
                if latest is not None:
                    obj_name = latest.object_name

        if obj_name:
            try:
                response = client.get_object(bucket, obj_name)
                text = response.read().decode("utf-8", errors="ignore")
                reader = csv.DictReader(_io.StringIO(text))
                records = list(reader)
                table = build_premium_table(records)
                if table is not None:
                    premium_service = PremiumLookupService(table)
                    premium_table_object = obj_name
            except Exception:
                premium_service = None
            finally:
                try:
                    response.close()
                    response.release_conn()
                except Exception:
                    pass

    # 3) Premium reconciliation
    table_p_per_1000: Optional[float] = None
    annual_table_premium: Optional[float] = None
    expected_modal: Optional[float] = None
    mismatch: Optional[Dict[str, Any]] = None

    if premium_service is not None and face_amount > 0:
        face_band = select_face_band(formula_meta, face_amount)
        if face_band is not None:
            table_p_per_1000 = premium_service.premium_per_1000(
                issue_age=issue_age,
                gender=gender,
                risk_class=risk_class,
                face_band=face_band,
                level_period=level_period,
            )
            if table_p_per_1000 is not None:
                annual_table_premium = float(table_p_per_1000) * (face_amount / 1000.0)

                basis = str(premium_table_cfg.get("basis", "annual_per_1000")) if premium_table_cfg else "annual_per_1000"
                modalization = premium_table_cfg.get("modalization", {}) if isinstance(premium_table_cfg, dict) else {}
                mode = premium_mode.upper()
                rule = str(modalization.get(mode, "none")).lower() if isinstance(modalization, dict) else "none"

                annual = annual_table_premium if basis == "annual_per_1000" else annual_table_premium
                if rule == "divide_by_12":
                    expected_modal = annual / 12.0
                else:
                    expected_modal = annual

                diff = abs((expected_modal or 0.0) - pas_modal_premium)
                threshold = max(0.01, 0.001 * (expected_modal or 0.0))
                material = diff > threshold
                if material:
                    mismatch = {
                        "code": "premium_mismatch",
                        "expected_modal": expected_modal,
                        "pas_modal": pas_modal_premium,
                        "threshold": threshold,
                        "material": True,
                        "source": "premium_table",
                    }

    # 4) Trust status
    trust_reasons: List[str] = []
    trust_status = "clean"

    if isinstance(premium_table_cfg, dict) and premium_service is None:
        trust_status = "missing_premium_table"
        trust_reasons.append("missing_premium_table")
    if mismatch and mismatch.get("material"):
        trust_status = "warnings_found"
        trust_reasons.append("premium_mismatch")
    if warnings:
        if trust_status == "clean":
            trust_status = "warnings_found"
        if "warnings_present" not in trust_reasons:
            trust_reasons.append("warnings_present")

    # 5) Audit docs from DSL meta
    source_docs = formula_meta.get("source_documents", {}) if isinstance(formula_meta, dict) else {}

    # 6) Projection summary mapping
    proj_years = projection.get("years", []) or []
    proj_cash = projection.get("cash_values", []) or []
    proj_db = projection.get("death_benefits", []) or []
    proj_qx = projection.get("mortality_rates", []) or []
    proj_surv = projection.get("survival_probabilities", []) or []
    net_level_premium = projection.get("net_level_premium")

    # 7) Assumptions block (simple summary of the assumption set used, when known).
    assumption_set_id = inputs.get("assumption_set_id")
    assumptions_block: Dict[str, Any] = {
        "assumption_set_id": assumption_set_id,
        "status": None,
        "approved_by": None,
        "approved_at": None,
    }

    if assumption_set_id:
        try:
            # list_assumption_sets returns AssumptionSet instances; we only
            # need a minimal subset of fields for the UI.
            for a in list_assumption_sets():
                if a.id == assumption_set_id:
                    assumptions_block["status"] = a.status
                    assumptions_block["approved_by"] = a.approved_by
                    assumptions_block["approved_at"] = a.approved_at
                    break
        except Exception:
            # If the registry is unavailable, we still return the id and
            # leave the other fields as None rather than failing the run.
            pass

    # 8) Build RunDetail payload
    run_info = {
        "run_id": run_id,
        # Execution status: this endpoint only reads existing snapshots, so
        # by the time we get here the run itself has succeeded. Trust
        # concerns are reported separately via trust_status.
        "status": "succeeded",
        "created_at": data.get("generated_at"),
        "engine_version": metadata.get("engine_version") or "unknown",
        "product_code": product_code,
        "product_type": product_type,
        "policy_id": policy_id or policy_number,
        "environment": metadata.get("environment") or "unknown",
        "triggered_by": inputs.get("triggered_by") or "unknown",
    }

    trust = {
        "status": trust_status,
        "headline": f"Trust Status: {trust_status.replace('_', ' ').title()}",
        "reasons": trust_reasons,
    }

    policy_input = {
        "identifiers": {
            "policy_number": policy_number,
            "product_code": product_code,
            "product_type": product_type,
        },
        "core_fields": {
            "issue_age": issue_age,
            "gender": gender,
            "smoker_class": smoker_class,
            "risk_class": risk_class,
            "face_amount": face_amount,
            "level_period": level_period,
            "premium_mode": premium_mode,
        },
        "pas_premium": {
            "modal_premium": pas_modal_premium,
            "currency": "USD",
        },
        "raw_record": None,
    }

    table_premium = None
    if table_p_per_1000 is not None and annual_table_premium is not None and expected_modal is not None:
        table_premium = {
            "per_1000": table_p_per_1000,
            "basis": premium_table_cfg.get("basis", "annual_per_1000") if isinstance(premium_table_cfg, dict) else "annual_per_1000",
            "annual_premium": annual_table_premium,
            "expected_modal_premium": expected_modal,
            "modalization_rule": "divide_by_12" if premium_mode.upper() == "MONTHLY" else "none",
            "mode": premium_mode,
            "currency": "USD",
            "premium_table_is_synthetic": bool(formula_meta.get("premium_table_sample_csv")),
            "premium_table_label": "Synthetic premium grid (NOT FILED RATES)" if formula_meta.get("premium_table_sample_csv") else None,
            "source": {
                "type": "premium_table",
                "object": premium_table_object,
                "prefix": (premium_table_cfg or {}).get("prefix") if isinstance(premium_table_cfg, dict) else None,
                "value_column": (premium_table_cfg or {}).get("value_column", "premium_per_1000") if isinstance(premium_table_cfg, dict) else "premium_per_1000",
                "keys": (premium_table_cfg or {}).get("keys", []) if isinstance(premium_table_cfg, dict) else [],
            },
        }

    premium_comparison = {
        "table_premium": table_premium,
        "pas_premium": {
            "modal_premium": pas_modal_premium,
            "mode": premium_mode,
            "currency": "USD",
        },
        "used_for_projection": "table_annual_premium" if table_premium else "pas_premium",
        "mismatch": mismatch,
    }

    # Optional AuditRecord summary derived from MinIO, when present. Missing
    # or unreadable records simply result in a null audit_summary field.
    try:
        audit_summary = _build_audit_summary(product_code, run_id)
    except Exception:
        audit_summary = None

    audit_sources = {
        "objects": {
            "pas_object": pas_ref,
            "actuarial_object": inputs.get("actuarial_object"),
            "term23_actuarial_object": inputs.get("term23_actuarial_object"),
            "rate_object": inputs.get("rate_object"),
            "crm_object": inputs.get("crm_object"),
            "premium_table_object": premium_table_object,
            "projection_object": object_name,
            "audit_object": (audit_summary or {}).get("audit_record_object"),
        },
        "documents": {
            "actuarial_memo": source_docs.get("actuarial_memo"),
            "risk_mapping": source_docs.get("risk_mapping"),
            "premiums": source_docs.get("premiums"),
        },
    }

    projection_summary = {
        "years": proj_years,
        "cash_values": proj_cash,
        "death_benefits": proj_db,
        "mortality_rates": proj_qx or None,
        "survival_probabilities": proj_surv or None,
        "net_level_premium": net_level_premium,
        "links": {
            "projection_object": object_name,
        },
    }

    return {
        "run": run_info,
        "trust_status": trust,
        "policy_input": policy_input,
        "premium_comparison": premium_comparison,
        "warnings": warnings,
        "assumptions": assumptions_block,
        "audit_sources": audit_sources,
        "projection_summary": projection_summary,
        "audit_summary": audit_summary,
    }


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
async def ui_root() -> HTMLResponse:
    """Redirect the top-level UI to the React app under /web.

    For the Product Review onboarding MVP we default the base URL to the
    Create Product Review flow instead of jumping straight into the most
    recent projection object. This makes the demo entry point stable while
    still keeping direct /web?key=... links working for existing flows.
    """

    url = "/web?view=create-review"
    return RedirectResponse(url=url, status_code=307)


@app.get("/ui/list", response_class=HTMLResponse)
async def ui_list(policy_id: Optional[str] = Query(None, description="Filter by policy_id")) -> HTMLResponse:
    """Basic HTML listing of projections, kept as a debugging aid.

    The richer, production-oriented UI is served by the React app under /web;
    this endpoint remains as a quick way to eyeball available objects.
    """
    objs = _list_projection_objects()

    summaries = []
    for name in objs:
        summary = _load_projection_summary(name)
        if summary is None:
            continue
        if policy_id and summary.get("policy_id") != policy_id:
            continue
        summaries.append(summary)

    if not summaries:
        rows = "<tr><td colspan='5'><em>No projections found.</em></td></tr>"
    else:
        rows = "".join(
            f"<tr>"
            f"<td><a href='/web?key={s['object_name']}'>{s['object_name']}</a></td>"
            f"<td>{s.get('policy_id') or ''}</td>"
            f"<td>{s.get('product_code') or ''}</td>"
            f"<td>{s.get('assumption_set_id') or ''}</td>"
            f"<td>{s.get('generated_at') or ''}</td>"
            f"</tr>" for s in summaries
        )

    html = f"""
    <html>
      <head>
        <title>ActuaryPOC Projection Viewer</title>
        <style>
          body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; }}
          code {{ background: #f5f5f5; padding: 0.1rem 0.3rem; }}
          table {{ border-collapse: collapse; width: 100%; }}
          th, td {{ border: 1px solid #ddd; padding: 0.5rem; font-size: 0.9rem; }}
          th {{ background: #f5f5f5; text-align: left; }}
          form {{ margin-bottom: 1rem; }}
        </style>
      </head>
      <body>
        <h1>ActuaryPOC Projection Viewer</h1>
        <p>This is the legacy HTML listing. For the full React UI, go to <code>/web?key=...</code>.</p>
        <form method="get" action="/ui/list">
          <label>Filter by policy_id: <input type="text" name="policy_id" value="{policy_id or ''}" /></label>
          <button type="submit">Apply</button>
          <a href="/ui/list">Clear</a>
        </form>
        <table>
          <thead>
            <tr>
              <th>Object</th>
              <th>Policy ID</th>
              <th>Product Code</th>
              <th>Assumption Set</th>
              <th>Generated At</th>
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/ui/assumptions", response_class=HTMLResponse)
async def ui_assumptions() -> HTMLResponse:
    sets = list_assumption_sets()
    rows = []
    for a in sets:
        approve_link = f"/api/assumptions/{a.id}/approve?approved_by=ui"
        rows.append(
            f"<tr>"
            f"<td>{a.id}</td>"
            f"<td>{a.product_code}</td>"
            f"<td>{a.description}</td>"
            f"<td>{a.dsl_file}</td>"
            f"<td>{a.actuarial_prefix or ''}</td>"
            f"<td>{a.status}</td>"
            f"<td>{'yes' if a.is_current else ''}</td>"
            f"<td>{a.approved_at or ''}</td>"
            f"<td><a href='{approve_link}'>Approve &amp; set current</a></td>"
            f"</tr>"
        )
    rows_html = "".join(rows) or "<tr><td colspan='9'><em>No assumption sets defined.</em></td></tr>"
    html = f"""
    <html>
      <head>
        <title>Assumption Sets</title>
        <style>
          body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; }}
          table {{ border-collapse: collapse; width: 100%; }}
          th, td {{ border: 1px solid #ddd; padding: 0.4rem; font-size: 0.85rem; }}
          th {{ background: #f5f5f5; text-align: left; }}
        </style>
      </head>
      <body>
        <p><a href="/ui">&larr; Back to projections</a></p>
        <h1>Assumption Sets</h1>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Product Code</th>
              <th>Description</th>
              <th>DSL File</th>
              <th>Actuarial Prefix</th>
              <th>Status</th>
              <th>Current?</th>
              <th>Approved At</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows_html}
          </tbody>
        </table>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/ui/dev", response_class=HTMLResponse)
async def ui_dev(prefix: str = Query("", description="Prefix to browse in the MinIO bucket")) -> HTMLResponse:
    """Simple dev-only object store browser.

    This view lets developers walk the MinIO-backed bucket hierarchy and
    download individual objects for inspection.
    """

    try:
        listing = _list_minio_prefix(prefix)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to list objects from MinIO: {exc}") from exc

    bucket = listing.get("bucket")
    norm_prefix = listing.get("prefix") or ""
    dirs = listing.get("directories") or []
    objects = listing.get("objects") or []

    def _escape(text: Any) -> str:
        from html import escape as _esc

        return _esc(str(text))

    rows_dirs = "".join(
        f"<tr><td>dir</td><td colspan='3'><a href='/ui/dev?prefix={_escape(d)}'>{_escape(d)}</a></td></tr>" for d in dirs
    ) or "<tr><td colspan='4'><em>No sub-directories under this prefix.</em></td></tr>"

    file_rows = []
    for obj in objects:
        name = obj.get("name")
        size = obj.get("size")
        lm = obj.get("lastModified")
        href = f"/api/dev/object?key={_escape(name)}"
        file_rows.append(
            f"<tr><td>file</td><td>{_escape(name)}</td><td>{_escape(size) if size is not None else ''}</td>"
            f"<td>{_escape(lm or '')}</td><td><a href='{href}'>download</a></td></tr>"
        )
    rows_files = "".join(file_rows) or "<tr><td colspan='5'><em>No objects under this prefix.</em></td></tr>"

    parent_link = ""
    if norm_prefix:
        parent = norm_prefix.rstrip("/")
        if "/" in parent:
            parent = parent.rsplit("/", 1)[0] + "/"
        else:
            parent = ""
        parent_link = f"<a href='/ui/dev?prefix={_escape(parent)}'>&larr; Up to '{_escape(parent or '/')}""</a>"

    html = f"""
    <html>
      <head>
        <title>Object Store Browser (dev)</title>
        <style>
          body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; }}
          table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
          th, td {{ border: 1px solid #ddd; padding: 0.4rem; font-size: 0.85rem; }}
          th {{ background: #f5f5f5; text-align: left; }}
          caption {{ text-align: left; font-weight: 600; margin-bottom: 0.5rem; }}
          .muted {{ color: #666; font-size: 0.85rem; }}
        </style>
      </head>
      <body>
        <p><a href="/ui">&larr; Back to UI home</a></p>
        <h1>Object Store Browser (dev)</h1>
        <p class="muted">Bucket: <code>{_escape(bucket)}</code> &nbsp;·&nbsp; Prefix: <code>{_escape(norm_prefix or '/')}</code></p>
        <p>{parent_link}</p>

        <table>
          <caption>Directories under this prefix</caption>
          <thead>
            <tr>
              <th>Type</th>
              <th colspan="3">Name</th>
            </tr>
          </thead>
          <tbody>
            {rows_dirs}
          </tbody>
        </table>

        <table>
          <caption>Objects under this prefix</caption>
          <thead>
            <tr>
              <th>Type</th>
              <th>Key</th>
              <th>Size (bytes)</th>
              <th>Last modified</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows_files}
          </tbody>
        </table>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/api/assumptions", response_model=List[Dict[str, Any]])
async def api_assumptions() -> List[Dict[str, Any]]:
    return [a.to_dict() for a in list_assumption_sets()]


@app.post("/api/assumptions/{set_id}/approve", response_model=Dict[str, Any])
async def api_approve_assumption(set_id: str, approved_by: str = Query("api")) -> Dict[str, Any]:
    result = approve_assumption_set(set_id, approved_by)
    if result is None:
        raise HTTPException(status_code=404, detail="Assumption set not found")
    return result.to_dict()


@app.get("/ui/view", response_class=HTMLResponse)
async def ui_view(key: str, view: str = Query("actuarial", description="View mode: actuarial or agent")) -> HTMLResponse:
    import json

    view_mode = view.lower()

    data = get_projection(key)
    inputs = data.get("inputs", {})
    projection = data.get("projection", {})

    years = projection.get("years", [])
    surv = projection.get("survival_probabilities", []) or []
    qx = projection.get("mortality_rates", []) or []
    exp_prem = projection.get("expected_premiums", []) or []
    exp_claim = projection.get("expected_claims", []) or []
    gross_res = projection.get("cash_values", []) or []
    nf_res = projection.get("nf_reserves", []) or []
    death_benefits = projection.get("death_benefits", []) or []
    net_level_premium = projection.get("net_level_premium")

    # Build rows for the selected view
    rows = []
    if view_mode == "agent":
        # Agent view: simpler table, emphasize premium and death benefit.
        for i, year in enumerate(years):
            if i >= 20:
                break
            rows.append(
                f"<tr>"
                f"<td>{year}</td>"
                f"<td>{exp_prem[i] if i < len(exp_prem) else ''}</td>"
                f"<td>{death_benefits[i] if i < len(death_benefits) else ''}</td>"
                f"<td>{gross_res[i] if i < len(gross_res) else ''}</td>"
                f"</tr>"
            )
        header_html = """
          <thead>
            <tr>
              <th>Year</th>
              <th>E[Premium]</th>
              <th>Death Benefit (illustrative)</th>
              <th>Value / Reserve</th>
            </tr>
          </thead>
        """
    else:
        # Actuarial view: full detail with mortality and reserves.
        for i, year in enumerate(years):
            if i >= 20:
                break
            rows.append(
                f"<tr>"
                f"<td>{year}</td>"
                f"<td>{surv[i] if i < len(surv) else ''}</td>"
                f"<td>{qx[i] if i < len(qx) else ''}</td>"
                f"<td>{exp_prem[i] if i < len(exp_prem) else ''}</td>"
                f"<td>{exp_claim[i] if i < len(exp_claim) else ''}</td>"
                f"<td>{gross_res[i] if i < len(gross_res) else ''}</td>"
                f"<td>{nf_res[i] if i < len(nf_res) else ''}</td>"
                f"</tr>"
            )
        header_html = """
          <thead>
            <tr>
              <th>Year</th>
              <th>Survival</th>
              <th>q_x</th>
              <th>E[Premium]</th>
              <th>E[Claim]</th>
              <th>Gross Reserve</th>
              <th>NF Reserve</th>
            </tr>
          </thead>
        """

    rows_html = "".join(rows) or "<tr><td colspan='7'><em>No projection rows available.</em></td></tr>"

    pretty = json.dumps(data, indent=2)

    agent_link = f"/ui/view?key={key}&view=agent"
    actuarial_link = f"/ui/view?key={key}&view=actuarial"

    html = f"""
    <html>
      <head>
        <title>Projection: {key}</title>
        <style>
          body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; }}
          pre {{ background: #f5f5f5; padding: 1rem; border-radius: 4px; overflow-x: auto; }}
          a {{ text-decoration: none; color: #0366d6; }}
          table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
          th, td {{ border: 1px solid #ddd; padding: 0.4rem; font-size: 0.85rem; }}
          th {{ background: #f5f5f5; text-align: right; }}
          td:first-child, th:first-child {{ text-align: left; }}
          .tabs a {{ margin-right: 1rem; }}
          .tabs .active {{ font-weight: 600; }}
        </style>
      </head>
      <body>
        <p><a href="/ui">&larr; Back to list</a></p>
        <h1>Projection</h1>
        <p><code>{key}</code></p>
        <div class="tabs">
          <a href="{actuarial_link}" class="{'active' if view_mode == 'actuarial' else ''}">Actuarial view</a>
          <a href="{agent_link}" class="{'active' if view_mode == 'agent' else ''}">Agent view</a>
        </div>
        <h2>Summary</h2>
        <ul>
          <li><strong>Policy ID:</strong> {inputs.get('policy_id') or ''}</li>
          <li><strong>Product Code:</strong> {inputs.get('product_code') or ''}</li>
          <li><strong>Formula Path:</strong> {inputs.get('formula_path') or ''}</li>
          <li><strong>Net Level Premium (per policy issued):</strong> {net_level_premium if net_level_premium is not None else ''}</li>
        </ul>
        <h2>Year-by-year view (first 20 years)</h2>
        <table>
          {header_html}
          <tbody>
            {rows_html}
          </tbody>
        </table>
        <h2>Raw JSON</h2>
        <pre>{pretty}</pre>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
