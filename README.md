# Actuary POC

Initial scaffolding for the insurance illustration platform discussed with Billy. The repo currently demonstrates three pillars:

1. **Connector + pipeline layer** – sample CSV ingestion into MinIO (S3-compatible) storage.
2. **Policy DSL** – YAML-based structure for storing reusable formulas.
3. **Projection engine stub** – simple deterministic projection over the ingested policy data.

## Layout

```
src/actuarypoc
├── cli/                # Typer CLI entrypoints
├── config/             # Environment templates
├── connectors/         # Data connector contracts
├── dsl/                # Policy DSL definitions + examples
├── pipeline/           # Ingestion pipeline(s)
├── projection/         # Projection engine stub
├── sample_data/        # Synthetic CSV for early tests
└── storage/            # MinIO helpers
```

## Quickstart

1. **Install dependencies**
   ```bash
   cd actuarypoc
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment**
   ```bash
   cp src/actuarypoc/config/example.env .env
   # edit if your endpoint/keys differ
   export $(cat .env | xargs)
   ```

3. **Ingest sample data**
   ```bash
   python -m actuarypoc.pipeline.ingest
   ```
   or via CLI:
   ```bash
   python -m actuarypoc.cli.main load-sample src/actuarypoc/sample_data/policies.csv
   ```

4. **Run projection stub**
   ```bash
   python -m actuarypoc.cli.main project \
     '{"premium": 2500, "face_amount": 500000, "interest_rate": 0.045}' \
     src/actuarypoc/dsl/examples/whole_life.yaml
   ```

## Next Steps
- Flesh out additional connectors (PAS APIs, SFTP loaders, etc.).
- Implement schema registry / mapping templates.
- Expand DSL compiler + interpreter (LLM-assisted extraction).
- Replace projection stub with actuarial-grade simulation engine.
- Add Dagster/Prefect orchestration definitions for repeatable runs.
