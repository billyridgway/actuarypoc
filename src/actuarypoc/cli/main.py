from __future__ import annotations

import json
from pathlib import Path

import typer

from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.pipeline.ingest import ingest_csv
from actuarypoc.projection.engine import ProjectionEngine

app = typer.Typer(help="Actuary POC helpers")


@app.command()
def load_sample(path: str = typer.Argument(..., help="Path to CSV")):
    """Ingest a CSV file into MinIO using the canonical schema."""
    obj_name = ingest_csv(path)
    typer.echo(f"Uploaded: {obj_name}")


@app.command()
def project(policy_json: str, formula_path: str, years: int = 20):
    """Run a projection for a single policy record (JSON string)."""
    record = json.loads(policy_json)
    formula = load_formula(formula_path)
    engine = ProjectionEngine(formula)
    result = engine.project(record, horizon=years)
    typer.echo(result)


if __name__ == "__main__":
    app()
