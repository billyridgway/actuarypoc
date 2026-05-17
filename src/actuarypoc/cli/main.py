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
from actuarypoc.projection.service import build_projection_summary, store_projection

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
    typer.echo(key)


if __name__ == "__main__":
    app()
