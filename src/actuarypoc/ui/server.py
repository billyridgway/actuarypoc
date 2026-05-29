from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from actuarypoc.storage.minio_client import get_minio_client, get_bucket_name
from actuarypoc.config.assumptions import list_assumption_sets, approve_assumption_set
from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.projection.premium import PremiumLookupService, build_premium_table, select_face_band


app = FastAPI(title="ActuaryPOC Projection Viewer", version="0.1.0")


# Mount built React UI (if present) under /web. This expects `vite build`
# to have been run in the `web/` directory, producing `web/dist`.
_DIST_DIR = Path(__file__).resolve().parents[2] / "web" / "dist"
if _DIST_DIR.exists():  # pragma: no cover - environment dependent
    app.mount("/web", StaticFiles(directory=_DIST_DIR, html=True), name="web")


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

    # 1) Policy input via PAS
    pas_ref = inputs.get("pas_object")
    policy_id = inputs.get("policy_id")
    pas_rec = _load_pas_record(pas_ref, policy_id)

    policy_number = str(pas_rec.get("policy_number") if pas_rec else policy_id or "")
    product_code = str(inputs.get("product_code") or pas_rec.get("product_code") if pas_rec else "")
    product_type = str(pas_rec.get("product_type") if pas_rec else "")

    def _num(rec: Optional[Dict[str, Any]], key: str, default: float = 0.0) -> float:
        if not rec:
            return default
        try:
            return float(rec.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    def _int(rec: Optional[Dict[str, Any]], key: str, default: int = 0) -> int:
        if not rec:
            return default
        try:
            return int(rec.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    issue_age = _int(pas_rec, "issue_age", 0)
    gender = str(pas_rec.get("gender") if pas_rec else "")
    smoker_class = str(pas_rec.get("smoker_class") if pas_rec else "")
    risk_class = str(pas_rec.get("risk_class") if pas_rec else "")
    face_amount = _num(pas_rec, "face_amount", 0.0)
    level_period = _int(pas_rec, "level_period", 0)
    premium_mode = str(pas_rec.get("premium_mode") if pas_rec else "")
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
        "run_id": inputs.get("run_id") or object_name,
        # Execution status: this endpoint only reads existing snapshots, so
        # by the time we get here the run itself has succeeded. Trust
        # concerns are reported separately via trust_status.
        "status": "succeeded",
        "created_at": data.get("generated_at"),
        "engine_version": metadata.get("engine_version") or "unknown",
        "product_code": product_code,
        "product_type": product_type,
        "policy_id": policy_id or policy_number,
        "environment": "unknown",
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

    audit_sources = {
        "objects": {
            "pas_object": pas_ref,
            "actuarial_object": inputs.get("actuarial_object"),
            "term23_actuarial_object": inputs.get("term23_actuarial_object"),
            "rate_object": inputs.get("rate_object"),
            "crm_object": inputs.get("crm_object"),
            "premium_table_object": premium_table_object,
            "projection_object": object_name,
            "audit_object": None,
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
    }


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
async def ui() -> HTMLResponse:
    """Very simple HTML UI for browsing projections."""
    objs = _list_projection_objects()
    items = "".join(
        f'<li><a href="/ui/view?key={name}">{name}</a></li>' for name in objs
    ) or "<li><em>No projections found.</em></li>"
    html = f"""
    <html>
      <head>
        <title>ActuaryPOC Projection Viewer</title>
        <style>
          body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; }}
          code {{ background: #f5f5f5; padding: 0.1rem 0.3rem; }}
        </style>
      </head>
      <body>
        <h1>ActuaryPOC Projection Viewer</h1>
        <p>Available projection objects in MinIO (<code>projections/</code> prefix):</p>
        <ul>
          {items}
        </ul>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
async def ui(policy_id: Optional[str] = Query(None, description="Filter by policy_id")) -> HTMLResponse:
    """HTML UI for browsing projections, optionally filtered by policy_id."""
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
        rows = "<tr><td colspan='4'><em>No projections found.</em></td></tr>"
    else:
        rows = "".join(
            f"<tr>"
            f"<td><a href='/ui/view?key={s['object_name']}'>{s['object_name']}</a></td>"
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
        <form method="get" action="/ui">
          <label>Filter by policy_id: <input type="text" name="policy_id" value="{policy_id or ''}" /></label>
          <button type="submit">Apply</button>
          <a href="/ui">Clear</a>
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
