from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from actuarypoc.connectors.base import CSVConnector
from actuarypoc.storage.minio_client import ensure_bucket, get_minio_client, get_bucket_name
from actuarypoc.config.assumptions import list_assumption_sets, approve_assumption_set
from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.projection.engine import ProjectionEngine
from actuarypoc.projection.mortality import build_term23_surface
from actuarypoc.projection.premium import PremiumLookupService, build_premium_table, load_premium_table_from_csv, select_face_band
from actuarypoc.projection.service import store_projection
from actuarypoc.storage.postgres_client import (
    get_product_review,
    list_product_documents,
    record_document_upload,
    record_product_model_review_decision,
    upsert_product_review_draft,
)

try:  # FastAPI can be configured with either Pydantic v1 or v2
    from pydantic import BaseModel
except Exception:  # pragma: no cover - extremely unlikely in this env
    BaseModel = object  # type: ignore[assignment]


app = FastAPI(title="ActuaryPOC Projection Viewer", version="0.1.0")


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


class ProductReviewDraftRequest(BaseModel):  # type: ignore[misc]
    carrier_name: str
    product_name: str
    product_code: str
    product_type: str
    filing_id: Optional[str] = None


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


class ScenarioConfigPayload(BaseModel):  # type: ignore[misc]
    scenarios: List[ScenarioConfig]


_ALLOWED_PMR_DECISIONS = {
    "approve_for_poc",
    "approve_with_exclusions",
    "request_changes",
    "reject",
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
    we can reuse the same scenario projection wiring.
    """

    internal: List[Dict[str, Any]] = []
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
        internal.append({"id": sid, "name": name, "policy": policy})
    return internal


def _generate_p12trf_scenarios_from_config(
    scenarios: List[Dict[str, Any]],
    years: int = 40,
    *,
    generation_id: Optional[str] = None,
    product_code: str = "P12TRF",
    generated_at: Optional[str] = None,
) -> List[str]:
    """Project configured P12TRF scenarios and persist them to MinIO.

    This is a thin, API-friendly wrapper around the CLI helper
    ``project-p12trf-scenarios-minio``. It expects ``scenarios`` to be a
    list of objects with ``id``, optional ``name``, and a ``policy`` block
    mirroring ``examples/p12trf_scenarios.json``.

    It returns the list of *generation-scoped* object keys written under the
    ``projections/{product_code_lower}/reviews/{generation_id}/scenarios/``
    prefix. For backward compatibility with the existing Product Model
    Review Trust Surface, it also writes "latest" alias objects under the
    legacy ``projections/p12trf/scenarios/{scenario_id}.json`` paths when
    product_code == "P12TRF".
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
                "product_id": "P12TRF",
                "product_code": "P12TRF",
                "formula_path": str(dsl_path),
                "assumption_set_id": None,
                "run_id": f"p12trf-scenario-{sid}",
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
                "description": "Optional riders (e.g. waiver of premium, child term) from the P12TRF ProductDefinition are not yet modeled in this POC.",
                "severity": "medium",
            }
        ],
        "ambiguousLanguage": [],
    }

    product_block = {
        "code": defn.get("product_code", "P12TRF"),
        "name": defn.get("marketing_name", "P12TRF Term Life (POC)"),
        "definitionId": defn.get("product_definition_id", "P12TRF-def-v1-poc"),
    }

    # Optional review metadata: tie the Trust Surface back to the latest
    # Product Review generation when Postgres is configured.
    review_meta: Dict[str, Any] = {
        "filingId": None,
        "currentGeneration": None,
        "generatedAt": None,
        "documentCount": 0,
        "scenarioCount": len(scen_and_rates["scenarios"]),
    }
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
        docs = list_product_documents(product_block["code"], filing_id=filing_id)
        review_meta["documentCount"] = len(docs)
    except Exception:
        # Best-effort only; Trust Surface must remain robust when Postgres
        # is not configured.
        pass

    return {
        "product": product_block,
        "scope": scope,
        "traceability": traceability,
        "rates": scen_and_rates["rates"],
        "scenarios": scen_and_rates["scenarios"],
        "assumptions": assumptions,
        "gaps": gaps,
        "reviewMeta": review_meta,
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

    # Best-effort Postgres persistence. If Postgres is not configured or
    # unavailable, we still return a 200-level response with the echoed
    # payload so that the UI remains responsive, but in the Pi cluster we
    # expect POSTGRES_DSN to be set and the insert to succeed.
    rec = record_product_model_review_decision(
        product_code=product_code,
        reviewer=reviewer,
        decision=decision,
        exclusions=exclusions,
        comments=comments,
    )

    if rec is None:
        return ProductModelReviewDecisionResponse(
            id=None,
            product_code=product_code,
            reviewer=reviewer,
            decision=decision,
            exclusions=exclusions,
            comments=comments,
            created_at=None,
        )

    return ProductModelReviewDecisionResponse(
        id=rec.get("id"),
        product_code=rec.get("product_code", product_code),
        reviewer=rec.get("reviewer", reviewer),
        decision=rec.get("decision", decision),
        exclusions=rec.get("exclusions", exclusions),
        comments=rec.get("comments", comments),
        created_at=str(rec.get("created_at")) if rec.get("created_at") is not None else None,
    )


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
    # UI-friendly ScenarioConfig shape. When none are present we fall
    # back to the bundled default P12TRF scenarios.
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
                }
            )

    if not scenarios_ui and code == "P12TRF":
        scenarios_ui = _default_p12trf_scenarios_for_ui()

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

    # MVP restriction: we only support P12TRF for now, reusing the existing
    # scenario projection wiring and Product Model Review Trust Surface.
    if code != "P12TRF":
        raise HTTPException(status_code=400, detail="Generate Product Review is only implemented for P12TRF in this MVP")

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

    written_keys = _generate_p12trf_scenarios_from_config(
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

    return {
        "ok": True,
        "generation_id": generation_id,
        "generated_at": generated_at,
        "written": written_keys,
        "redirectUrl": "/web?view=product-model",
    }


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def _list_projection_objects(prefix: str = "projections/") -> List[str]:
    client = get_minio_client()
    bucket = get_bucket_name()
    objects = []
    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        objects.append(obj.object_name)
    return sorted(objects)


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

    If projections exist, we default to the most recent object's key so that
    /ui immediately opens a concrete run in the SPA.
    """
    from urllib.parse import quote

    objs = _list_projection_objects()
    if objs:
        latest = objs[-1]
        url = f"/web?key={quote(latest)}"
    else:
        url = "/web"

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
