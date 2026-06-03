# Insurance Illustration Platform – Architecture (ActuaryPOC + Operator Overview)

> Status: **Draft**, grounded in current code (2026‑05‑29). Future / planned
> components are explicitly labeled as such.

This document describes the current architecture of the Insurance
Illustration Platform as implemented by the **ActuaryPOC** backend and the
**Illustration Operator** on the Raspberry Pi k3s cluster, with MinIO as the
backing object store.

It is intentionally POC‑level and describes what exists today, plus a small
number of clearly labeled future components.

---

## 1. High‑Level Architecture

At a high level, the platform consists of:

- **k3s cluster (Raspberry Pi)** – runs the operator, Jobs, UI, Postgres,
  and MinIO.
- **MinIO** – S3‑compatible object storage (`illuminet` bucket) for:
  - PAS exports
  - actuarial tables (including Term23 slice)
  - CRM account data
  - rate curves
  - assumption sets registry
  - projection outputs and audit snapshots
- **ActuaryPOC** (this repo) – Python backend that provides:
  - data ingestion helpers
  - policy DSL and projection engine
  - LLM‑assisted assumption extraction and registry
  - projection summary builder (`project-minio`)
  - a Run Detail API and UI (FastAPI + React)
- **Illustration Operator** (separate repo) – Kubernetes operator that:
  - defines the `IllustrationProject` CRD
  - resolves product wiring from a product registry
  - creates Kubernetes Jobs to run assumptions extraction and projections
  - records projection artefact locations on CRD status

**Future / planned (not fully implemented yet):**

- SERFF Filing ingestion as a first‑class workflow:
  - upload endpoints
  - structured provenance records
  - mapping between SERFF artefacts and assumption sets.

---

## 2. Major Components (Implemented)

### 2.1 MinIO Object Model

The `actuarypoc` code expects a MinIO bucket (e.g. `illuminet`) with objects
under conventional prefixes:

- `pas_export/` – PAS policy export snapshots (ingested from CSV).
- `actuarial_tables/` – core actuarial tables.
- `actuarial_tables_term23/` – Term23 mortality slice used by the P12TRF POC.
- `crm_accounts/` – CRM account data.
- `rate_curves/` – yield curves / discount rates.
- `p12trf/` – P12TRF term policy data.
- `projections/` – projection summaries written by `project-minio`.
- `docs/...` – **(planned)** SERFF / filing documents and extracted text.
- `product-definitions/{product_code}/{filing_id}/product-definition.json` –
  ProductDefinition v1 artefacts for a specific product + filing context
  (used by the P12TRF Product Model Review Trust Surface).

These prefixes are typically populated by:

- `python -m actuarypoc.pipeline.ingest` (for sample data), or
- the `load-sample` CLI command in `src/actuarypoc/cli/main.py`.

### 2.2 ActuaryPOC Backend

**Modules:**

- `src/actuarypoc/pipeline/ingest.py`
  - Reads CSVs and writes JSON objects into MinIO under the prefixes above.
- `src/actuarypoc/dsl/`
  - Policy DSL definitions and examples (e.g. `p12trf_term.yaml`).
  - DSL loader (`load_formula`) that turns YAML into an executable formula
    graph.
- `src/actuarypoc/projection/`
  - `engine.py` – projection engine over the DSL graph.
  - `mortality.py` – mortality surface builders, including a Term23 slice.
  - `premium.py` – premium lookup table handling and band selection.
  - `service.py` – projection summary builder + helpers to write results to
    MinIO and Postgres.
- `src/actuarypoc/config/assumptions.py`
  - Assumption Set schema and MinIO‑backed registry helpers.
- `src/actuarypoc/extract/assumptions_extractor.py`
  - LLM‑assisted extraction of assumption sets from text.
- `src/actuarypoc/storage/`
  - `minio_client.py` – MinIO access
  - `postgres_client.py` – optional run history in Postgres.
- `src/actuarypoc/cli/main.py`
  - CLI entrypoints:
    - `load-sample` – CSV → MinIO
    - `project` – single‑policy projection from JSON string + DSL file
    - `project_p12trf_sample` – bundles a P12TRF sample dataset
    - `project-minio` – build a projection summary from MinIO inputs and
      write back to MinIO
    - `extract-assumptions-minio` – run LLM extraction against a MinIO doc
      prefix and store/update an assumption set
    - `approve-assumption` – mark an assumption set approved/current.
- `src/actuarypoc/ui/server.py` + `web/`
  - FastAPI app with:
    - `/health` – simple health check
    - `/projections` / `/projections/{key}` – raw projection JSON
    - `/api/run-detail` – structured Run Detail JSON for one projection
    - `/ui` – redirector into the React UI
    - `/ui/list` – simple HTML list of projection objects (debugging)
    - `/web` – static React SPA (projection viewer)
  - React app (Vite‑built) that renders:
    - trust banner
    - assumptions summary
    - policy input and premium comparison
    - year‑by‑year projection summary
    - simple SVG graphs for cash value & death benefit
    - audit sources (MinIO object names, referenced docs).

### 2.3 Illustration Operator (Summary)

**Note:** The operator is defined in a separate repo (`illustration-operator`)
but is a critical part of the deployed system.

- CRD: `IllustrationProject` (`illustrations.poc/v1alpha1`)
  - `spec` fields:
    - `productId`, `horizonYears`, `mode`, `pasConfigMap`, `runPolicy`, `notes`.
  - `status` fields (subset):
    - `phase`, `lastRunId`, `lastRunTime`, `lastError`.
    - `projectionObject`, `auditObject`, `inputSnapshotObject`.
    - `assumptionSetId`, `assumptionApproved`.
    - `engineVersion`, `runnerImage`.
    - `resolved` – wiring summary (product, PAS ConfigMap/key, DSL file,
      MinIO prefixes, doc prefixes, assumption ID).

- Controller (`controllers/illustrationproject_controller.go`):
  - Resolves product config from `/config/products.yaml` (ConfigMap mount).
  - Derives MinIO prefixes and DSL file path by convention.
  - Optionally creates a one‑shot LLM assumptions Job using `actuarypoc`
    CLI (`extract-assumptions-minio`).
  - Gates projection on explicit assumption approval (`assumptionApproved`).
  - Creates an illustration Job using the `actuarypoc` image to run
    `python -m actuarypoc.cli.main project-minio` with appropriate env vars.
  - Updates CRD status with:
    - planned/written MinIO object keys
    - last Job outcome and timestamps.

---

## 3. Data Flows

### 3.1 Projection Flow (Implemented)

This is the primary flow that exists today and is exercised by the
`p12trf-serff-demo` example.

1. **Data ingestion → MinIO**
   - Sample CSVs in `src/actuarypoc/sample_data/` are ingested into MinIO using
     `actuarypoc.pipeline.ingest` or the `load-sample` CLI.
   - Objects are written under standard prefixes like `pas_export/`,
     `actuarial_tables/`, `actuarial_tables_term23/`, `crm_accounts/`,
     `rate_curves/`, and `p12trf/`.

2. **IllustrationProject created** (in the cluster)
   - A resource like `config/samples/p12trf-serff-demo.yaml` is applied:

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
       notes: "Demo project for P12TRF SERFF filings"
     ```

3. **Operator resolves wiring**
   - Reads product config from `/config/products.yaml` for `productId=p12trf`.
   - Computes:
     - filings/doc prefixes
     - PAS source (ConfigMap vs MinIO)
     - DSL file path
     - MinIO prefixes for projections.
   - Writes a summary into `status.resolved`.

4. **(Optional) LLM assumptions Job**
   - If product LLM config is present, the operator:
     - Ensures a Job to run `extract-assumptions-minio` exists.
     - Waits for the Job to complete.
     - Updates `status.assumptionSetId`.
     - Waits for `status.assumptionApproved=true` before proceeding.

5. **Illustration Job**
   - Operator creates a Job `illustration-<projectName>` that runs the
     `actuarypoc` image with env vars like:
     - `PAS_PREFIX`, `ACTUARIAL_PREFIX`, `RATE_PREFIX`, `CRM_PREFIX`,
       `TERM23_ACTUARIAL_PREFIX`.
     - `PROJECTION_OBJECT_NAME`, `AUDIT_OBJECT_NAME`,
       `INPUT_SNAPSHOT_OBJECT_NAME`.
     - `RUN_ID`, `PRODUCT_ID`, `PROJECT_NAME`, MinIO connection vars.
   - The Job container executes:

     ```sh
     python -m actuarypoc.cli.main project-minio
     ```

6. **Projection summary written to MinIO**
   - `project-minio` uses the prefixes + MinIO client to:
     - load latest inputs for PAS, actuarial tables, Term23 slice, rates,
       and CRM accounts.
     - build a portfolio‑level projection summary.
     - write JSON to the requested `PROJECTION_OBJECT_NAME` (e.g.
       `projections/p12trf/run-<uid>.json`).
     - optionally write audit and input snapshot objects.

7. **CRD status updated**
   - Operator tracks Job completion and sets:
     - `status.phase` (`Running` → `Succeeded` / `Failed`).
     - `status.lastRunId`, `status.lastRunTime`, `status.lastError`.
     - `status.projectionObject`, `status.auditObject`,
       `status.inputSnapshotObject`.

8. **UI / API consumption**
   - The `projection-ui` Deployment exposes the FastAPI app from this repo.
   - `/api/run-detail?key=projections/...json` returns a structured JSON view
     that includes:
     - policy identifiers and core fields
     - premium comparison (PAS vs table, when available)
     - assumption set ID and approval info
     - MinIO object keys for inputs
     - projection arrays (years, cash values, death benefits, etc.).
   - `/web?key=...` loads the React UI to render that Run Detail as a
     human‑friendly page.

### 3.2 SERFF / Filing Flow (Planned / Partial)

There is **partial support** for SERFF‑style document ingestion and AI triage
in earlier POC code (e.g. PDF extraction utilities and AI‑assisted file
classification in older `projection-ui` code), but:

- There is **no single, fully implemented, end‑to‑end SERFF ingestion
  workflow** yet.
- The following pieces exist today:
  - PDF/text extraction helpers under `src/actuarypoc/pipeline/pdf_extract.py`
    and the inlined FastAPI code from the older UI deployment (now superseded).
  - LLM classifiers that recommend which SERFF files to keep as sources for
    assumptions.
  - CLI and helpers to extract assumption sets from text and write them into
    the MinIO‑backed registry.

What is **not** yet implemented as a coherent pipeline:

- A stable API/CLI to:
  - accept SERFF uploads,
  - store raw and derived text under well‑defined MinIO prefixes,
  - create structured “filing records” with provenance,
  - attach those records to products and assumption sets.

This future SERFF pipeline is described in concept in other planning docs and
in code comments, but should still be considered **planned**.

### 3.3 Product Review Onboarding (Implemented MVP)

In addition to the projection and SERFF design flows above, the platform now
includes a lightweight, demo-focused **Product Review onboarding flow** for
P12TRF that runs entirely inside the `projection-ui` Deployment:

- **Product Setup (UI)**
  - Route: `/web?view=create-review` (React SPA)
  - Captures carrier name, product name, product code, product type, and an
    optional `filing_id` (e.g. `P12TRF-ICC12-2026-DEMO`).
  - Persists a minimal Product Review draft into Postgres via
    `/api/product-review/draft`, reusing the existing `products` table
    (`metadata` JSONB stores review state under a `review` block).

- **Document Upload (UI + API)**
  - Drag-and-drop upload UI accepts `PDF`, `DOCX`, `XLSX`, and `CSV`.
  - Backend endpoint: `POST /api/product-review/{product_code}/documents`.
  - Files are written into MinIO using the current Product Review's
    `filing_id` when present:

    ```text
    docs/{product_code}/{filing_id}/{timestamp}-{filename}
    ```

    and into an `unassigned` bucket otherwise:

    ```text
    docs/{product_code}/unassigned/{timestamp}-{filename}
    ```

  - Each upload is indexed in the `documents` Postgres table with
    `product_id = product_code` and `serff_id = filing_id` (or `NULL` for
    unassigned documents).
  - The UI lists uploaded documents from `/api/product-review/{product_code}`;
    by default this is filtered to the current filing context:
    - when `filing_id` is set → `serff_id = filing_id`
    - when no `filing_id` → `serff_id IS NULL`.

- **Scenario Configuration (UI + API)**
  - UI shows an editable table of scenarios (age, sex, smoker class, risk
    class, face amount, level period, premium mode, modal premium).
  - Backend endpoint: `PUT /api/product-review/{product_code}/scenarios`.
  - Scenario rows are stored as JSON inside the product `metadata.review`
    block, mirroring the structure of `examples/p12trf_scenarios.json` so
    they can be passed directly to the existing
    `project-p12trf-scenarios-minio` logic.
  - When no scenarios are stored yet, `/api/product-review/P12TRF` exposes
    a UI-friendly view derived from the bundled `p12trf_scenarios.json`
    fixture.

- **Generate Product Review (API + Trust Surface)**
  - Backend endpoint: `POST /api/product-review/{product_code}/generate`.
  - MVP restriction: implemented only for `P12TRF`, where it:
    - reads configured scenarios from Postgres (falling back to the
      bundled fixture when needed),
    - computes a `generation_id` (e.g. `20260603T120000Z`) for this
      Product Review run,
    - projects each scenario using the existing P12TRF DSL + Term23 wiring,
    - writes generation-scoped projection summaries to MinIO under

      ```text
      projections/{product_code_lower}/reviews/{generation_id}/scenarios/{scenario_id}.json
      ```

      and, for backward compatibility with the existing Trust Surface,
      also writes alias objects under:

      ```text
      projections/p12trf/scenarios/{scenario_id}.json
      ```

    - marks the Product Review status as `generated` in Postgres and
      persists `current_generation`, `generated_at`, and the list of
      written projection keys under `products.metadata.review`, and
    - returns a small JSON payload including `generation_id`, the
      `written` keys, and `redirectUrl: "/web?view=product-model"`.
  - The React onboarding flow uses this redirect to land the user in the
    existing Product Model Review Trust Surface (`ProductModelReviewPage`)
    without introducing new workflow engines, authentication, or
    multi-reviewer coordination.

This MVP onboarding path is intentionally not a generic document management
system and is scoped for demoability: it wires documents, scenarios, and
projections together just enough to show how a customer might go from
product artefacts to a live Trust Surface review.

### 3.4 End-to-End Diagram (Conceptual)

The following diagram shows the intended high-level flow from SERFF filing to
illustration and UI.

- Document ingestion and extraction are **planned/partial**.
- Projection execution, RunDetail UI/API, and basic audit references/
  snapshots are **implemented today**.
- A canonical audit record model and SERFF-to-assumption provenance model are
  **still planned** and not yet implemented.

```mermaid
flowchart LR
    A[SERFF Filing\n(forms, rates, memos)]
    B[Document Ingestion\n(Planned MinIO prefixes under filings/)]
    C[Text / Metadata Extraction\n(PDF/text extract + LLM triage\nPartially implemented)]
    D[Actuarial DSL & Assumption Sets\n(DSL YAML + AssumptionSet registry)]
    E[Projection Engine & Jobs\n(project-minio via Jobs in k3s)]
    F[Audit Layer\n(projection JSON + audit/input snapshots\n+ CRD status)]
    G[UI / API\nRunDetail endpoint + React UI]

    A --> B --> C --> D --> E --> F --> G
```

---

## 4. Trust Boundaries

### 4.1 MinIO as System of Record

MinIO holds the canonical artefacts for:

- input datasets (PAS, tables, rates, CRM)
- extracted filing documents (planned)
- assumption sets
- projection summaries
- audit snapshots.

The system is designed so that projections and audit trails can be
reconstructed from MinIO without relying on in‑memory state in the operator
or backend.

### 4.2 CRD / Kubernetes API

The `IllustrationProject` CRD status is intentionally **metadata‑only**:

- It holds:
  - MinIO object keys
  - logical IDs (product ID, assumption set ID)
  - engine / runner image versions
  - coarse lifecycle info.
- It does **not** hold:
  - PAS policy details
  - per‑policy cash flows or reserves
  - SERFF filing text.

This keeps the Kubernetes API surface lean and avoids leaking sensitive data.

### 4.3 RunDetail API and UI

The RunDetail API exposed by `actuarypoc` is internal to the platform and may
include:

- per‑policy input fields (policy number, face amount, risk class)
- projections at a per‑policy level
- assumption set and premium table references.

Any future client‑facing or multi‑tenant UI should **not** directly expose
this API without an additional authorization and redaction layer.

---

## 5. Audit Model

The current audit model is spread across several artefacts:

- **Assumption Sets**
  - Stored in MinIO as JSON documents via the assumption registry.
  - Identified by `AssumptionSet.id` and referenced in projection inputs.
  - Approval status recorded and surfaced via CLI and RunDetail.

- **Projection Summaries**
  - Each projection JSON contains:
    - `inputs` – object keys, product code, assumption set ID, etc.
    - `metadata` – counts of records used, timestamps, engine metadata
      (partial).
    - `projection` – year‑by‑year values.

- **Audit & Input Snapshot Objects**
  - When configured, `project-minio` writes:
    - an audit JSON summarizing the run (metadata‑only), and
    - an input snapshot JSON listing which input objects were used.

- **CRD Status** (operator)
  - Holds the object keys and logical IDs that tie a run to its artefacts.

- **RunDetail API / UI**
  - Aggregates:
    - assumption set ID + approval info
    - PAS / tables / rates / CRM object keys
    - product DSL path
    - projection values and simple premiums analysis.

**Gaps / planned improvements:**

- A **single, versioned audit record schema** that ties together:
  - SERFF filing IDs
  - assumption sets
  - DSL file versions
  - MinIO object keys for inputs and outputs.
- More explicit `engine_version` and `environment` fields in projection
  summaries and status.

---

## 6. Deployment Model

### 6.1 Images and CI

- `actuarypoc` image is built by `.github/workflows/build-and-push.yml` and
  pushed to GHCR as:
  - `ghcr.io/<owner>/actuarypoc:latest`
  - `ghcr.io/<owner>/actuarypoc:<branch>`, including `:main`.

- `illustration-operator` image is built similarly in its repo and pushed to
  GHCR as:
  - `ghcr.io/<owner>/illustration-operator:latest`
  - `ghcr.io/<owner>/illustration-operator:main`.

### 6.2 k3s Resources (key pieces)

- Namespace: `illustrations-poc`.
- MinIO: deployed in `minio-system` namespace with service
  `minio.minio-system.svc.cluster.local:9000` and the `illuminet` bucket.
- `projection-ui` Deployment (
  defined in `actuarypoc/k8s/projection-ui.yaml`):
  - Uses `ghcr.io/<owner>/actuarypoc:main`.
  - Runs `uvicorn actuarypoc.ui.server:app` on port 8080.
  - Exposed via a NodePort service on `:30301`.
- `illustration-operator` Deployment (in its repo/manifests):
  - Uses `ghcr.io/<owner>/illustration-operator:main`.
  - Mounts a ConfigMap for `/config/products.yaml`.
  - Watches `IllustrationProject` CRDs and Jobs.
- Postgres Deployment / Service:
  - Used by `actuarypoc` to optionally record run history.

---

## 7. Summary

The current architecture already has the main ingredients for a
Kubernetes‑native insurance illustration platform:

- CRD as the run request interface
- Jobs as the execution primitive
- MinIO as the central object store
- A Python backend with DSL, projection engine, assumptions, and UI.

SERFF ingestion and richer audit/provenance records are partially implemented
and planned to become first‑class workflows, but today remain **incomplete
and experimental**. Future work should focus on formalizing those flows and
strengthening the trust/audit model across MinIO, CRDs, and the UI.
