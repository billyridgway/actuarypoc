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

## Deploying the sample ingestion CronJob (k3s)

A simple CronJob manifest lives in `k8s/ingestion-cronjob.yaml`. It clones the repo each hour inside a `python:3.11-slim` container and runs the sample ingestion pipeline against the MinIO bucket. By default it talks to the in-cluster MinIO service exposed at `minio.minio-system.svc.cluster.local:9000`.

Apply it to the provided namespace:

```bash
kubectl --kubeconfig ~/.openclaw/workspace/.kube/pi-k3s.yaml apply -f k8s/ingestion-cronjob.yaml
kubectl -n illustrations-poc get cronjob actuarypoc-sample-ingest
```

To grab the logs from the latest run:

```bash
kubectl -n illustrations-poc get jobs --sort-by=.metadata.creationTimestamp
kubectl -n illustrations-poc logs job/<latest-job-name>
```

## Next Steps
- Flesh out additional connectors (PAS APIs, SFTP loaders, etc.).
- Implement schema registry / mapping templates.
- Expand DSL compiler + interpreter (LLM-assisted extraction).
- Replace projection stub with actuarial-grade simulation engine.
- Add Dagster/Prefect orchestration definitions for repeatable runs.
