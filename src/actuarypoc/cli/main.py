from __future__ import annotations

import json
import os
from datetime import datetime
from dataclasses import asdict
from pathlib import Path

import typer

from actuarypoc.connectors.base import CSVConnector
from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.pipeline.ingest import ingest_csv
from actuarypoc.projection.engine import ProjectionEngine
from actuarypoc.projection.mortality import build_term23_surface
from actuarypoc.projection.premium import load_premium_table_from_csv, PremiumLookupService, select_face_band
from actuarypoc.projection.service import (
    build_projection_summary,
    store_projection,
    store_json_metadata,
    build_audit_from_summary,
    build_input_snapshot_from_summary,
    build_audit_record_from_summary,
    store_audit_record,
)
from actuarypoc.projection.object_keys import (
    projection_object_key,
    audit_object_key,
    input_snapshot_object_key,
)
from actuarypoc.storage.postgres_client import record_illustration_run
from actuarypoc.extract.assumptions_extractor import (
    extract_assumption_set_from_doc,
    extract_assumption_set_from_text,
    assumption_set_to_json,
)
from actuarypoc.config.assumptions import AssumptionSet, upsert_assumption_set, approve_assumption_set
from actuarypoc.storage.minio_client import get_minio_client, get_bucket_name

app = typer.Typer(help="Actuary POC helpers")


@app.command()
def load_sample(path: str = typer.Argument(..., help="Path to CSV")):
    """Ingest a CSV file into MinIO using a prefix derived from the filename.

    This is primarily for POC/demo usage. The filename is mapped to a logical
    prefix so downstream projection helpers (which read from PAS / actuarial /
    rate / CRM prefixes) can find the latest objects. For unknown filenames we
    fall back to the generic ``ingest/`` prefix.
    """

    p = Path(path)
    stem = p.stem

    # Optional override to force a specific prefix (useful in tests).
    forced_prefix = os.getenv("INGEST_PREFIX")
    if forced_prefix:
        prefix = forced_prefix if forced_prefix.endswith("/") else forced_prefix + "/"
    else:
        # Heuristic mapping from sample filenames → logical prefixes.
        if "pas_export" in stem:
            prefix = "pas_export/"
        elif "actuarial_tables_term23" in stem:
            prefix = "actuarial_tables_term23/"
        elif "actuarial_tables" in stem:
            prefix = "actuarial_tables/"
        elif "crm_accounts" in stem:
            prefix = "crm_accounts/"
        elif "rate_curves" in stem:
            prefix = "rate_curves/"
        elif "policies_p12trf" in stem:
            # Allow POLICIES_PREFIX env to steer where P12TRF policies land.
            pol_prefix = os.getenv("POLICIES_PREFIX", "p12trf/")
            prefix = pol_prefix if pol_prefix.endswith("/") else pol_prefix + "/"
        else:
            prefix = "ingest/"

    object_name = f"{prefix}{stem}-{int(datetime.utcnow().timestamp())}.json"
    obj_name = ingest_csv(path, object_name=object_name)
    typer.echo(f"Uploaded: {obj_name}")


@app.command()
def project(policy_json: str, formula_path: str, years: int = 20):
    """Run a projection for a single policy record (JSON string)."""
    record = json.loads(policy_json)
    formula = load_formula(formula_path)
    engine = ProjectionEngine(formula)
    result = engine.project(record, horizon=years)
    typer.echo(result)


@app.command()
def project_p12trf_sample(years: int = 40):
    """Run a P12TRF sample projection using bundled CSV + DSL.

    This is a convenience wrapper around ``project`` that:
    - reads the first record from ``sample_data/policies_p12trf.csv``
    - uses ``dsl/examples/p12trf_term.yaml`` as the product formula
    """

    base = Path(__file__).resolve().parents[1]
    csv_path = base / "sample_data" / "policies_p12trf.csv"
    dsl_path = base / "dsl" / "examples" / "p12trf_term.yaml"

    connector = CSVConnector(str(csv_path))
    try:
        record = next(iter(connector.fetch()))
    except StopIteration:
        raise typer.Exit("No records found in policies_p12trf.csv")

    formula = load_formula(str(dsl_path))

    # Try to build a Term23 mortality surface from the bundled sample data so
    # that the P12TRF sample projection uses real q_x-driven survival instead
    # of a flat approximation. If the file is missing we gracefully fall back
    # to the original behaviour.
    term23_path = base / "sample_data" / "actuarial_tables_term23.csv"
    term23_records = list(CSVConnector(str(term23_path)).fetch()) if term23_path.exists() else []
    mortality_surface = build_term23_surface(term23_records) if term23_records else None

    # Optional premium lookup: use a synthetic P12TRF grid for POC wiring so
    # we can compare table-derived premiums against the PAS modal premium.
    premium_table = None
    premium_sample_rel = (formula.meta or {}).get("premium_table_sample_csv") if getattr(formula, "meta", None) else None
    if premium_sample_rel:
        premium_csv = base / premium_sample_rel
        if premium_csv.exists():
            premium_table = load_premium_table_from_csv(str(premium_csv))

    premium_service = PremiumLookupService(premium_table) if premium_table is not None else None

    # Derive a face band from DSL/meta configuration so banding remains
    # data-driven and product-specific thresholds do not leak into Python.
    try:
        face_amount = float(record.get("face_amount", 0))
    except (TypeError, ValueError):
        face_amount = 0.0
    face_band = select_face_band(getattr(formula, "meta", {}) or {}, face_amount) or 1

    warnings: list[str] = []

    # Compute a table-derived premium when we have a premium grid available.
    if premium_service is not None:
        try:
            issue_age = int(record.get("issue_age", 0))
        except (TypeError, ValueError):
            issue_age = 0
        gender = str(record.get("gender", ""))
        risk_class = str(record.get("risk_class", ""))
        try:
            level_period = int(record.get("level_period", 0))
        except (TypeError, ValueError):
            level_period = 0

        table_p_per_1000 = premium_service.premium_per_1000(
            issue_age=issue_age,
            gender=gender,
            risk_class=risk_class,
            face_band=face_band,
            level_period=level_period,
        )

        if table_p_per_1000 is not None and face_amount > 0:
            annual_table_premium = float(table_p_per_1000) * (face_amount / 1000.0)
            # Simple POC modalisation: assume MONTHLY = annual / 12 when
            # premium_mode is MONTHLY; otherwise treat PAS modal_premium as
            # already annual.
            mode = str(record.get("premium_mode", "")).upper()
            if mode == "MONTHLY":
                expected_modal = annual_table_premium / 12.0
            else:
                expected_modal = annual_table_premium

            try:
                pas_modal = float(record.get("modal_premium", 0.0))
            except (TypeError, ValueError):
                pas_modal = 0.0

            diff = abs(expected_modal - pas_modal)
            material_threshold = max(0.01, 0.001 * expected_modal)
            if diff > material_threshold:
                warnings.append(
                    "premium_mismatch: table-derived expected_modal={} vs PAS modal_premium={}".format(
                        round(expected_modal, 6), round(pas_modal, 6)
                    )
                )

            # Precedence rule for POC: use table premium for projections when
            # available, but keep PAS modal premium as an observed input.
            record["premium"] = annual_table_premium

    engine = ProjectionEngine(formula, mortality_surface=mortality_surface)
    result = engine.project(record, horizon=years)

    # Surface any premium warnings before the raw result so humans can see
    # why the projection may differ from PAS inputs.
    for msg in warnings:
        typer.echo(f"WARNING: {msg}")

    typer.echo(result)


@app.command("project-p12trf-scenarios-minio")
def project_p12trf_scenarios_minio(
    scenarios_path: str = typer.Option(
        "",
        "--scenarios-path",
        help="Path to P12TRF scenarios JSON; defaults to bundled examples/p12trf_scenarios.json",
    ),
    projections_prefix: str = typer.Option(
        "projections/p12trf/scenarios/",
        "--projections-prefix",
        envvar="P12TRF_SCENARIOS_PREFIX",
        help="MinIO prefix under which to write P12TRF scenario projections",
    ),
    years: int = typer.Option(40, "--horizon-years", help="Projection horizon in years"),
):
    """Project configured P12TRF PMR scenarios and persist them to MinIO.

    This command treats scenario inputs as explicit, configurable policy
    test-cases for P12TRF rather than deriving them from PAS or SERFF.

    For each scenario in the fixture, we:
    - Load the P12TRF DSL and Term23 mortality slice (when available)
    - Project the scenario policy record for the requested horizon
    - Write a projection summary JSON under the given prefix, including a
      `policy_inputs` block that mirrors the configured inputs.

    The resulting projection objects are suitable for consumption by the
    RunDetail API and the Product Model Review Trust Surface.
    """

    base = Path(__file__).resolve().parents[1]
    # Default bundled fixture under examples/ when no explicit path is given.
    if scenarios_path:
        scenarios_file = Path(scenarios_path)
    else:
        scenarios_file = base / "examples" / "p12trf_scenarios.json"

    if not scenarios_file.exists():
        raise typer.Exit(f"Scenario fixture not found: {scenarios_file}")

    data = json.loads(scenarios_file.read_text(encoding="utf-8"))
    scenarios = data.get("scenarios") or []

    if not scenarios:
        raise typer.Exit(f"No scenarios defined in {scenarios_file}")

    # DSL + mortality surface wiring mirrors project_p12trf_sample so that
    # scenario behaviour stays aligned with the P12TRF product configuration.
    dsl_path = base / "dsl" / "examples" / "p12trf_term.yaml"
    formula = load_formula(str(dsl_path))

    term23_path = base / "sample_data" / "actuarial_tables_term23.csv"
    term23_records = list(CSVConnector(str(term23_path)).fetch()) if term23_path.exists() else []
    mortality_surface = build_term23_surface(term23_records) if term23_records else None

    # Optional premium grid wiring, as in project_p12trf_sample; this keeps
    # warnings/net-level-premium behaviour consistent where used.
    premium_table = None
    premium_sample_rel = (formula.meta or {}).get("premium_table_sample_csv") if getattr(formula, "meta", None) else None
    if premium_sample_rel:
        premium_csv = base / premium_sample_rel
        if premium_csv.exists():
            premium_table = load_premium_table_from_csv(str(premium_csv))

    premium_service = PremiumLookupService(premium_table) if premium_table is not None else None

    engine = ProjectionEngine(formula, mortality_surface=mortality_surface)

    env_label = os.getenv("ILLUSTRATION_ENVIRONMENT") or os.getenv("ENVIRONMENT") or None

    if not projections_prefix.endswith("/"):
        projections_prefix = projections_prefix + "/"

    for scenario in scenarios:
        sid = str(scenario.get("id") or "").strip()
        label = str(scenario.get("name") or sid)
        policy = dict(scenario.get("policy") or {})

        if not sid or not policy:
            continue

        # Build policy_inputs directly from the configured scenario policy.
        policy_inputs = {
            "issue_age": policy.get("issue_age"),
            "gender": policy.get("gender"),
            "smoker_class": policy.get("smoker_class"),
            "risk_class": policy.get("risk_class"),
            "level_period": policy.get("level_period"),
            "face_amount": policy.get("face_amount"),
            "premium_mode": policy.get("premium_mode"),
        }

        # Optionally compute table-derived premium warnings similar to
        # project_p12trf_sample. For the scenario Trust Surface, this is
        # mainly useful for keeping behaviour consistent; we do not mutate
        # the configured modal_premium.
        warnings: list[str] = []
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
            "generated_at": datetime.utcnow().isoformat(),
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
            },
            "warnings": warnings,
            "projection": asdict(result),
        }

        object_name = f"{projections_prefix}{sid}.json"
        key = store_projection(summary, object_name=object_name)
        typer.echo(f"{sid}: {key}")


@app.command("project-minio")
def project_minio(
    pas_prefix: str = typer.Option("pas_export/", envvar="PAS_PREFIX", help="MinIO prefix for PAS exports"),
    actuarial_prefix: str = typer.Option(
        "actuarial_tables/",
        envvar="ACTUARIAL_PREFIX",
        help="MinIO prefix for actuarial tables",
    ),
    rate_prefix: str = typer.Option("rate_curves/", envvar="RATE_PREFIX", help="MinIO prefix for rate curves"),
    crm_prefix: str = typer.Option("crm_accounts/", envvar="CRM_PREFIX", help="MinIO prefix for CRM accounts"),
    term23_actuarial_prefix: str = typer.Option(
        "actuarial_tables_term23/",
        envvar="TERM23_ACTUARIAL_PREFIX",
        help="MinIO prefix for Term23 actuarial slice (optional)",
    ),
    object_name: str = typer.Option(
        "",
        "--object-name",
        envvar="PROJECTION_OBJECT_NAME",
        help="Full MinIO object key to write; defaults under projections/ if empty",
    ),
    audit_object_name: str = typer.Option(
        "",
        "--audit-object-name",
        envvar="AUDIT_OBJECT_NAME",
        help="Optional MinIO object key for a sanitized audit document",
    ),
    input_snapshot_object_name: str = typer.Option(
        "",
        "--input-snapshot-object-name",
        envvar="INPUT_SNAPSHOT_OBJECT_NAME",
        help="Optional MinIO object key for an input snapshot document",
    ),
):
    """Build a projection summary from MinIO inputs and persist it.

    This wires together the generic PAS + actuarial + rate + CRM prefixes and
    stores a single projection JSON object back into MinIO. The resulting
    object key is printed to stdout so callers (e.g. the operator's Job) can
    capture it if desired.
    """

    run_id = os.getenv("RUN_ID")
    product_id = os.getenv("PRODUCT_ID") or ""
    project_name = os.getenv("PROJECT_NAME")

    try:
        summary = build_projection_summary(
            pas_prefix=pas_prefix,
            actuarial_prefix=actuarial_prefix,
            rate_prefix=rate_prefix,
            crm_prefix=crm_prefix,
            term23_actuarial_prefix=term23_actuarial_prefix,
        )
        # Decide canonical object keys when explicit names are not supplied.
        effective_object_name = object_name
        effective_audit_object_name = audit_object_name
        effective_input_snapshot_name = input_snapshot_object_name

        if not effective_object_name and product_id and run_id:
            effective_object_name = projection_object_key(product_id, run_id)

        if not effective_audit_object_name and product_id and run_id:
            effective_audit_object_name = audit_object_key(product_id, run_id)

        if not effective_input_snapshot_name and product_id and run_id:
            effective_input_snapshot_name = input_snapshot_object_key(product_id, run_id)

        key = store_projection(summary, object_name=effective_object_name or None)
        # Optionally emit separate audit + input snapshot artefacts. These are
        # derived from the summary and are intentionally metadata-only.
        if effective_audit_object_name:
            audit_doc = build_audit_from_summary(summary)
            store_json_metadata(audit_doc, effective_audit_object_name)
        if effective_input_snapshot_name:
            snapshot_doc = build_input_snapshot_from_summary(summary)
            store_json_metadata(snapshot_doc, effective_input_snapshot_name)

        # Persist a canonical AuditRecord when we have enough identifiers to
        # write it meaningfully. This is a metadata-only document that avoids
        # embedding raw PAS or projection data.
        try:
            product_code = (summary.get("inputs", {}) or {}).get("product_code") or (os.getenv("PRODUCT_ID") or "")
            if run_id and product_code:
                audit_record = build_audit_record_from_summary(
                    summary,
                    projection_object=key,
                    audit_object=effective_audit_object_name or None,
                    input_snapshot_object=effective_input_snapshot_name or None,
                )
                store_audit_record(audit_record, product_code=product_code, run_id=run_id)
        except Exception:
            # Do not fail the projection if AuditRecord writing fails.
            pass

        # Best-effort: record this run in Postgres when configured so that
        # illustration history can be queried. We rely on the operator to
        # provide a stable RUN_ID and PRODUCT_ID when running in-cluster.
        try:
            if run_id and product_id:
                record_illustration_run(
                    run_id=run_id,
                    product_id=product_id,
                    project_name=project_name,
                    status="succeeded",
                    projection_object_path=key,
                    audit_object_path=effective_audit_object_name or None,
                    input_snapshot_path=effective_input_snapshot_name or None,
                    error=None,
                )
        except Exception:
            # Do not fail the projection if Postgres is unavailable.
            pass

        typer.echo(key)

    except Exception as exc:
        # On failure, best-effort record a failed run with the error message.
        try:
            if run_id and product_id:
                record_illustration_run(
                    run_id=run_id,
                    product_id=product_id,
                    project_name=project_name,
                    status="failed",
                    projection_object_path=None,
                    audit_object_path=None,
                    input_snapshot_path=None,
                    error=str(exc)[:2000],
                )
        except Exception:
            pass
        # Re-raise so the CLI/Job still fails visibly.
        raise


@app.command("extract-assumptions")
def extract_assumptions(
    doc_path: str = typer.Argument(..., help="Path to source document (PDF or text)"),
    product_code: str = typer.Option(..., "--product-code", "-p", help="Target PAS product code"),
    set_id: str = typer.Option(..., "--id", help="Identifier for the new assumption set"),
    description_hint: str = typer.Option(
        "",
        "--description-hint",
        help="Optional free-text hint about how this assumption set should be described",
    ),
    model: str = typer.Option(
        "",
        "--model",
        help="Override OpenAI model (defaults from ASSUMPTION_EXTRACT_MODEL or gpt-4o-mini)",
    ),
    output_path: str = typer.Option(
        "",
        "--output",
        "-o",
        help="Optional path to write the resulting AssumptionSet JSON; prints to stdout when omitted",
    ),
):
    """Extract an AssumptionSet JSON from a filing or product memo using OpenAI.

    This is an offline helper for LLM-assisted parsing. It reads a local
    document (PDF or text), calls the OpenAI API to produce a single
    AssumptionSet object, validates it, and then prints or writes the JSON.
    """

    asn = extract_assumption_set_from_doc(
        doc_path=doc_path,
        product_code=product_code,
        set_id=set_id,
        description_hint=description_hint or None,
        model=model or None,
    )

    payload = assumption_set_to_json(asn)
    if output_path:
        Path(output_path).write_text(payload, encoding="utf-8")
        typer.echo(f"Wrote AssumptionSet JSON to {output_path}")
    else:
        typer.echo(payload)


@app.command("import-assumption")
def import_assumption(
    path: str = typer.Argument(..., help="Path to AssumptionSet JSON file"),
    created_by: str = typer.Option(
        "llm-extractor",
        "--created-by",
        help="Identifier for who/what created this set (default: llm-extractor)",
    ),
):
    """Import or update an AssumptionSet in the MinIO-backed registry.

    The JSON file must contain a single object matching the AssumptionSet
    schema. If a set with the same id already exists, it is replaced; otherwise
    it is appended. created_at/created_by are populated when missing.
    """

    p = Path(path)
    if not p.exists():
        raise typer.Exit(f"File not found: {path}")

    data = json.loads(p.read_text(encoding="utf-8"))
    asn = AssumptionSet.from_dict(data)

    # Respect an existing created_by if present, otherwise use the CLI hint.
    if not asn.created_by:
        asn.created_by = created_by

    stored = upsert_assumption_set(asn)
    typer.echo(f"Imported assumption set id={stored.id} product_code={stored.product_code}")


@app.command("extract-assumptions-minio")
def extract_assumptions_minio(
    doc_prefix: str = typer.Option(
        ...,
        "--doc-prefix",
        envvar="LLM_DOC_PREFIX",
        help="MinIO prefix under which source docs live (e.g. docs/p12trf/)",
    ),
    product_code: str = typer.Option(
        ...,
        "--product-code",
        envvar="LLM_PRODUCT_CODE",
        help="Target PAS product code for the extracted assumption set",
    ),
    set_id: str = typer.Option(
        ...,
        "--id",
        envvar="LLM_ASSUMPTION_ID",
        help="Identifier for the new assumption set",
    ),
    description_hint: str = typer.Option(
        "",
        "--description-hint",
        envvar="LLM_DESCRIPTION_HINT",
        help="Optional free-text hint about the assumption set",
    ),
    model: str = typer.Option(
        "",
        "--model",
        envvar="ASSUMPTION_EXTRACT_MODEL",
        help="Override OpenAI model (default: gpt-4o-mini)",
    ),
):
    """Extract and upsert an AssumptionSet using a doc stored in MinIO.

    This helper finds the latest object under ``doc_prefix`` in MinIO,
    downloads its text content, runs the LLM extractor, and upserts the
    resulting AssumptionSet into the registry.
    """

    client = get_minio_client()
    bucket = get_bucket_name()

    latest = None
    for obj in client.list_objects(bucket, prefix=doc_prefix, recursive=True):
        if latest is None or obj.last_modified > latest.last_modified:
            latest = obj

    if latest is None:
        raise typer.Exit(f"No documents found under prefix '{doc_prefix}'")

    resp = client.get_object(bucket, latest.object_name)
    try:
        text = resp.read().decode("utf-8", errors="ignore")
    finally:
        resp.close()
        resp.release_conn()

    asn = extract_assumption_set_from_text(
        product_code=product_code,
        text=text,
        set_id=set_id,
        description_hint=description_hint or f"LLM-extracted assumptions from {latest.object_name}",
        model=model or None,
    )

    stored = upsert_assumption_set(asn)
    typer.echo(
        f"Imported assumption set id={stored.id} product_code={stored.product_code} "
        f"from {latest.object_name}"
    )


@app.command("approve-assumption")
def approve_assumption(
    set_id: str = typer.Argument(..., help="Identifier of the assumption set to approve"),
    approved_by: str = typer.Option(
        "human-review",
        "--approved-by",
        help="Identifier for who is approving this set (e.g. initials or SSO id)",
    ),
):
    """Mark an assumption set as approved + current for its product.

    This updates the MinIO-backed registry so that:

    - status → "approved"
    - is_current → true
    - any other current sets for the same product_code are cleared.

    Projections that call get_current_assumption_for_product(...) will then
    start using this set automatically for that product.
    """

    result = approve_assumption_set(set_id, approved_by)
    if result is None:
        raise typer.Exit(f"Assumption set not found: {set_id}")

    typer.echo(
        "Approved assumption set id={id} for product_code={code} as current (status={status})".format(
            id=result.id,
            code=result.product_code,
            status=result.status,
        )
    )


if __name__ == "__main__":
    app()
