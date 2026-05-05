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
├── sample_data/        # Synthetic CSV for early tests (PAS/actuarial/CRM/rate mocks; see docs)
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

## Dagster orchestration scaffold

A minimal Dagster repository lives under `dagster/`. Current jobs:
- `sample_ingestion_job` – wraps the basic policy CSV ingest helper.
- `pas_export_job` – prototypes the PAS export connector (uses `sample_data/pas_export.csv`).
- `actuarial_table_job` – ingests actuarial tables (uses `sample_data/actuarial_tables.csv`).
- `crm_data_job` – ingests CRM account data (`sample_data/crm_accounts.csv`).
- `rate_curve_job` – ingests rate curve snapshots (`sample_data/rate_curves.csv`).

Run any job locally with:

```bash
pip install -r requirements.txt
export $(cat .env | xargs)
dagster job execute -f dagster/repository.py -j sample_ingestion_job
```

You can also launch the Dagster UI with `dagster dev -f dagster/repository.py` to trigger runs interactively; the jobs use the same MinIO env vars. Included schedules (`hourly_sample_ingest_schedule`, `daily_pas_export_schedule`) are registered but default to `STOPPED` so they won't burn storage—enable/disable with the standard Dagster CLI, e.g.:
```
dagster schedule start -f dagster/repository.py -n hourly_sample_ingest_schedule
```

### Cluster deployment
`k8s/dagster-dev.yaml` runs Dagster inside the `illustrations-poc` namespace (NodePort `dagster-dev`, port `30300`). It clones this repo, installs deps, points at in-cluster MinIO, and exposes the Dagster UI/daemon for orchestration (the old Kubernetes CronJob has been removed in favor of this). To redeploy:
```
kubectl --kubeconfig ~/.openclaw/workspace/.kube/pi-k3s.yaml apply -f k8s/dagster-dev.yaml
```

## Next Steps
- Flesh out additional connectors (PAS APIs, SFTP loaders, etc.).
- Implement schema registry / mapping templates.
- Expand DSL compiler + interpreter (LLM-assisted extraction).
- Replace projection stub with actuarial-grade simulation engine.
- Extend Dagster repository with additional assets/jobs + k8s deployment manifests.
