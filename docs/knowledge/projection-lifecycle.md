# Projection Lifecycle (Current POC)

> Status: Describes the **implemented** projection lifecycle as of the current
> POC. Planned SERFF and ingestion workflows are called out explicitly as
> future work.

This document explains how a projection flows through the system today,
starting from sample data and ending with a projection UI view.

---

## 1. Inputs and Ingestion

### 1.1 Sample Data

Sample CSV files under `src/actuarypoc/sample_data/` include:

- `pas_export.csv` – PAS policy export sample
- `actuarial_tables.csv` – primary actuarial tables
- `actuarial_tables_term23.csv` – Term23 mortality slice
- `crm_accounts.csv` – CRM accounts
- `rate_curves.csv` – rate curves
- `policies_p12trf.csv` – P12TRF term policies
- `p12trf_premiums.synthetic.csv` – synthetic premium grid for P12TRF

These are synthetic and anonymized – they are not production data.

### 1.2 Ingesting Data into MinIO

Data is ingested into MinIO via:

- `python -m actuarypoc.pipeline.ingest`
- or the `load-sample` CLI (`python -m actuarypoc.cli.main load-sample ...`).

Each file is mapped to a logical MinIO prefix, for example:

- `pas_export/`
- `actuarial_tables/`
- `actuarial_tables_term23/`
- `crm_accounts/`
- `rate_curves/`
- `p12trf/`

Objects are stored as JSON, usually with a `records` array.

---

## 2. Product Configuration and DSL

### 2.1 Policy DSL

The policy DSL lives under `src/actuarypoc/dsl/` and describes products as
formula graphs. Example:

- `examples/p12trf_term.yaml` – DSL for the P12TRF term product.
- `examples/whole_life.yaml` – DSL stub for a whole life product.

The DSL is loaded by `load_formula()` and used by the projection engine.

### 2.2 Product Registry (Operator Side)

The **illustration operator** repo defines `config/products.yaml` which maps
product IDs (e.g. `p12trf`) to:

- display name
- DSL file name
- MinIO prefix base for inputs and projections
- mortality hints (e.g. Term23 tables)
- optional LLM config (doc prefix, assumption ID).

The operator uses this registry to:

- resolve product wiring for `IllustrationProject.spec.productId`.
- derive MinIO prefixes and DSL file path.

---

## 3. IllustrationProject and Operator

### 3.1 Creating a Project

A user (or tooling) creates an `IllustrationProject` CR, e.g.:

```yaml
apiVersion: illustrations.poc/v1alpha1
kind: IllustrationProject
metadata:
  name: p12trf-serff-demo
  namespace: illustrations-poc
spec:
  productId: p12trf
  horizonYears: 40
  mode: adhoc
  pasConfigMap: p12trf-pas
  notes: "Demo project for P12TRF"
```

### 3.2 Operator Reconciliation

The illustration operator:

1. Loads the `IllustrationProject`.
2. Looks up the product in `/config/products.yaml`.
3. Derives:
   - PAS source (ConfigMap vs MinIO)
   - DSL file
   - MinIO prefixes for filings/docs, policies, and projections
   - LLM doc prefix and assumption ID (if configured).
4. Writes a summary to `status.resolved` and sets `status.assumptionSetId`.

If LLM extraction is configured, the operator:

- creates a one‑shot Job `assumptions-<productId>` to run the `actuarypoc`
  CLI `extract-assumptions-minio`.
- waits for the Job to complete.
- requires `status.assumptionApproved=true` before proceeding to projection.

---

## 4. Projection Execution (project-minio)

### 4.1 Illustration Job

Once assumptions are ready/approved (or not needed for the product), the
operator ensures a Job `illustration-<projectName>` exists. This Job:

- uses the `actuarypoc` container image
- sets env vars for:
  - MinIO connection
  - PAS / actuarial / rates / CRM prefixes
  - Term23 prefix
  - output object keys (`PROJECTION_OBJECT_NAME`, `AUDIT_OBJECT_NAME`,
    `INPUT_SNAPSHOT_OBJECT_NAME`)
  - metadata (`RUN_ID`, `PRODUCT_ID`, `PROJECT_NAME`).
- runs:

  ```sh
  python -m actuarypoc.cli.main project-minio
  ```

### 4.2 Projection Summary

`project-minio`:

1. Calls `build_projection_summary(...)` using the provided prefixes.
2. Writes a JSON object to MinIO containing:
   - `generated_at` timestamp
   - `inputs` block (object keys, product code, assumption set ID, etc.)
   - `metadata` block (record counts, engine metadata when available)
   - `projection` block (arrays for years, cash values, death benefits,
     survival probabilities, etc.).
3. Optionally writes:
   - an audit object (metadata‑only summary)
   - an input snapshot object.
4. Optionally records a row in Postgres via `record_illustration_run`.

### 4.3 CRD Status

The operator inspects the Job and updates `IllustrationProject.status`:

- `phase`: `Running` → `Succeeded` / `Failed`
- `lastRunId`, `lastRunTime`, `lastError`
- `projectionObject`, `auditObject`, `inputSnapshotObject`
- `engineVersion`, `runnerImage` (when provided via env)
- `assumptionSetId`, `assumptionApproved`

This ties the Kubernetes resource to the MinIO artefacts without embedding
raw projection values.

---

## 5. Run Detail and UI

### 5.1 Run Detail API

The `projection-ui` Deployment exposes the FastAPI app from this repo. A key
endpoint is:

```http
GET /api/run-detail?key=projections/...json
```

This endpoint:

1. Loads the projection JSON from MinIO.
2. Optionally loads PAS record(s) based on `pas_object` and `policy_id`.
3. Loads the DSL formula to read `meta` and premium table configuration.
4. Optionally loads premium table data from MinIO.
5. Builds a `RunDetail` JSON object including:
   - run metadata
   - policy input summary
   - premium comparison (PAS vs table)
   - warnings and trust status
   - assumptions summary
   - audit sources (MinIO object names)
   - simplified projection arrays.

### 5.2 React UI

The React app in `web/`:

- Reads the projection key from `?key=...` in the browser URL.
- Fetches `/api/run-detail?key=...`.
- Renders:
  - a trust banner (clean / warnings / missing premium table)
  - assumptions section (assumption set ID, status, approval info)
  - policy input and PAS premium
  - premium comparison section
  - projection summary (key years)
  - projection graphs (cash values and death benefits over time)
  - audit sources section (MinIO object keys and document references).

`/ui` is wired to redirect into `/web?key=...` for a recent projection,
making the React UI the primary projection viewer.

---

## 6. What Is Not Yet Part of the Lifecycle

The current lifecycle **does not yet include** a fully wired SERFF ingestion
pipeline. Specifically missing pieces include:

- User‑facing upload endpoints for SERFF zips/PDFs.
- A stable convention for storing SERFF raw and processed artefacts in MinIO.
- A first‑class "filing record" concept that ties docs to products and
  assumption sets.

Parts of this exist as experimental code or helpers, but they are not yet
assembled into a single workflow.
