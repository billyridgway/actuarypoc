from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import typer

from actuarypoc.connectors.base import CSVConnector
from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.pipeline.ingest import ingest_csv
from actuarypoc.projection.engine import ProjectionEngine
from actuarypoc.projection.service import (
    build_projection_summary,
    store_projection,
    store_json_metadata,
    build_audit_from_summary,
    build_input_snapshot_from_summary,
)
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
    engine = ProjectionEngine(formula)
    result = engine.project(record, horizon=years)
    typer.echo(result)


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

    summary = build_projection_summary(
        pas_prefix=pas_prefix,
        actuarial_prefix=actuarial_prefix,
        rate_prefix=rate_prefix,
        crm_prefix=crm_prefix,
        term23_actuarial_prefix=term23_actuarial_prefix,
    )
    key = store_projection(summary, object_name=object_name or None)
    # Optionally emit separate audit + input snapshot artefacts. These are
    # derived from the summary and are intentionally metadata-only.
    if audit_object_name:
        audit_doc = build_audit_from_summary(summary)
        store_json_metadata(audit_doc, audit_object_name)
    if input_snapshot_object_name:
        snapshot_doc = build_input_snapshot_from_summary(summary)
        store_json_metadata(snapshot_doc, input_snapshot_object_name)
    typer.echo(key)


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
