# Actuary POC

Actuarial/illustration sandbox that wires together:

1. **Connector + pipeline layer** – sample CSV ingestion into MinIO
   (S3‑compatible) storage.
2. **Policy DSL** – YAML‑based structure for reusable product formulas.
3. **Projection + assumptions engine** – deterministic projection over
   ingested data, plus LLM‑assisted assumption extraction and approval.

The goal is to have a small but realistic playground for how a future
illustration platform could hang together: PAS exports, filings, actuarial
inputs, and CRM data flowing into MinIO, then through a DSL‑driven projection
engine and orchestration layer (Dagster / Kubernetes Jobs).

---

## Scope

This repo is intentionally **POC‑level** and opinionated around a single
"illustrations‑poc" environment:

- **What it covers**
  - Sample connectors for PAS export, actuarial tables, CRM, and rate curves
    (CSV → MinIO).
  - A simple, readable **policy DSL** that can express term/whole‑life style
    products (including the P12TRF term example).
  - A projection engine that can:
    - run a projection for a single policy against a DSL file, and
    - build a portfolio‑level projection summary from MinIO inputs.
  - An **assumptions pipeline** that uses OpenAI to extract an
    `AssumptionSet` from a filing / doc and stores it in a MinIO‑backed
    registry, with an explicit approval step.
  - A minimal **Dagster** repo that exercises the above pieces as jobs,
    schedules, and sensors.
- **What it assumes exists**
  - MinIO or S3‑compatible storage reachable with credentials in `.env`.
  - (For LLM workflows) an OpenAI API key and model permissions compatible
    with the extraction helpers.
  - For cluster use: a Kubernetes environment that can run the Dagster
    deployment in `k8s/dagster-dev.yaml` and mount this repo.
- **Out of scope (for now)**
  - Production‑grade data governance, lineage tracking, and auditability.
  - Rich UI / quoting front‑end – this is backend plumbing.
  - Full actuarial‑grade stochastic modeling – the engine is deliberately
    simplified to keep the POC readable.

---

## What this repo does (function and flow)

At a high level, the POC demonstrates the following flows.

### 1. Data ingestion → MinIO

Using either direct Python modules or the Typer CLI, you can load synthetic
CSV data under conventional prefixes:

- `pas_export/` – PAS policy export snapshot.
- `actuarial_tables/` and `actuarial_tables_term23/` – mortality and related
  tables.
- `crm_accounts/` – CRM account metadata.
- `rate_curves/` – yield curves / discount rates.
- `p12trf/` – P12TRF term policy data.

The CLI helper `load-sample` (see `src/actuarypoc/cli/main.py`) maps known
filenames to these prefixes and writes JSON objects into MinIO.

### 2. DSL‑driven projection

The **policy DSL** (YAML) lives under `src/actuarypoc/dsl/`. Example files:

- `examples/whole_life.yaml`
- `examples/p12trf_term.yaml`

The projection engine:

- Loads a DSL file and turns it into a formula graph.
- Applies that formula to a policy record over a given horizon.
- Can be invoked directly for ad‑hoc policies (`project` CLI) or via the
  portfolio service (`project-minio`, which reads from MinIO prefixes and
  writes a projection summary object back to MinIO).

### 3. LLM‑assisted assumptions

Under `src/actuarypoc/extract` and `src/actuarypoc/config/assumptions.py` the
POC adds an "assumption registry" pattern:

- `extract-assumptions` reads a local doc (PDF/text), calls the OpenAI API,
  validates the resulting `AssumptionSet`, and writes/prints JSON.
- `extract-assumptions-minio` finds the latest doc under a MinIO prefix,
  runs the same extraction, and upserts the set into the MinIO‑backed
  registry.
- `import-assumption` and `approve-assumption` manage the registry contents
  and designate an approved, current set per product.

This is what the illustration operator uses when you enable LLM extraction
for a product.

### 4. Orchestration with Dagster

The `dagster/` repo wires the above into jobs/schedules:

- `sample_ingestion_job` – wraps the basic policy CSV ingest helper.
- `p12trf_policies_job` – ingests the P12TRF term sample policies under the
  `p12trf/` prefix.
- `pas_export_job`, `actuarial_table_job`, `crm_data_job`, `rate_curve_job` –
  keep the PAS/actuarial/CRM/rate prefixes fresh.
- `projection_job` – reads the most recent PAS/actuarial/rate/CRM snapshots
  and writes a projection summary JSON to the `projections/` prefix.

A `pas_projection_sensor` watches for new PAS snapshots and triggers
`projection_job` so that each export gets a projection summary.

The `k8s/dagster-dev.yaml` manifest runs Dagster in‑cluster in the
`illustrations-poc` namespace.

---

## Layout

```
src/actuarypoc
├── cli/                # Typer CLI entrypoints (load-sample, project, assumptions helpers, ...)
├── config/             # Environment templates + assumption schema/registry code
├── connectors/         # Data connector contracts (e.g. CSV → MinIO)
├── dsl/                # Policy DSL definitions + examples
├── extract/            # LLM-assisted assumption extraction helpers
├── pipeline/           # Ingestion and PDF extraction pipelines
├── projection/         # Projection engine + service layer
├── sample_data/        # Synthetic CSVs for PAS/actuarial/CRM/rate mocks
└── storage/            # MinIO helpers
```

Dagster lives under `dagster/`, and k8s manifests under `k8s/`.

---

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

4. **Run a single‑policy projection**
   ```bash
   python -m actuarypoc.cli.main project \
     '{"premium": 2500, "face_amount": 500000, "interest_rate": 0.045}' \
     src/actuarypoc/dsl/examples/whole_life.yaml
   ```

5. **Run the bundled P12TRF term example**
   ```bash
   # Project the first synthetic P12TRF policy using the p12trf_term DSL
   python -m actuarypoc.cli.main project-p12trf-sample
   ```

---

## Dagster orchestration scaffold

A minimal Dagster repository lives under `dagster/`. Run any job locally with:

```bash
pip install -r requirements.txt
export $(cat .env | xargs)
dagster job execute -f dagster/repository.py -j sample_ingestion_job
```

You can also launch the Dagster UI with:

```bash
dagster dev -f dagster/repository.py
```

The sample schedules (`hourly_sample_ingest_schedule`,
`daily_pas_export_schedule`, etc.) are registered but default to `STOPPED`
so they won't burn storage—enable/disable with the standard Dagster CLI, e.g.:

```bash
dagster schedule start -f dagster/repository.py -n hourly_sample_ingest_schedule
```

A `pas_projection_sensor` watches for new PAS snapshots in MinIO and
automatically kicks off `projection_job`, ensuring each fresh export gets a
projection summary stored under `projections/`.

### Cluster deployment

`k8s/dagster-dev.yaml` runs Dagster inside the `illustrations-poc` namespace
(NodePort `dagster-dev`, port `30300`). It clones this repo, installs deps,
points at in-cluster MinIO, and exposes the Dagster UI/daemon for
orchestration. To redeploy:

```bash
kubectl --kubeconfig ~/.openclaw/workspace/.kube/pi-k3s.yaml apply -f k8s/dagster-dev.yaml
```

---

## Next Steps

- Flesh out additional connectors (PAS APIs, SFTP loaders, etc.).
- Implement schema registry / mapping templates.
- Expand DSL compiler + interpreter (LLM-assisted extraction).
- Replace projection stub with actuarial-grade simulation engine.
- Extend Dagster repository with additional assets/jobs + k8s deployment
  manifests.
