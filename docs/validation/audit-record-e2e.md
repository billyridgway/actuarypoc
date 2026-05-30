# AuditRecord End-to-End Validation – Cluster Run

> Status: **Operator path exercised; ProductDefinition wiring not yet
> present in the in-cluster AuditRecord.** Validation was performed
> using `kubectl` against the Raspberry Pi k3s cluster and direct
> MinIO access as described below.

## 1. Preconditions

Run from this workspace on Billy's MacBook Air, where:

- `kubectl` is installed and can reach the k3s cluster via
  `KUBECONFIG=../.kube/pi-k3s.yaml`.
- MinIO access/env for local CLI use was supplied via:

  ```bash
  export MINIO_ENDPOINT=192.168.50.101:32619
  export MINIO_ACCESS_KEY=admin
  export MINIO_SECRET_KEY=password
  export MINIO_BUCKET=illuminet
  export MINIO_SECURE=false
  ```

- The `actuarypoc` and `illustration-operator` repos are up to date on
  the branch used by the cluster (feature/projection-trigger).

## 2. Health Check (Before)

From the workspace root on that machine:

```bash
cd actuarypoc
source .venv/bin/activate

python -m actuarypoc.tools.health_check \
  --kubeconfig ../.kube/pi-k3s.yaml \
  --namespace illustrations-poc \
  --minio-namespace minio-system \
  --ui-url http://192.168.50.251:30301/health
```

Record (this run):

- Overall status: `UNKNOWN`
- Checks:
  - `kubectl_available`: OK
  - `pods_illustrations-poc`: OK – all Running pods Ready (completed
    Job pods ignored)
  - `pods_minio-system`: OK
  - `illustration_operator_deploy`: OK
  - `illustrationproject_crd`: OK
  - `illustrationproject_phases`: `{'Succeeded': 1, 'AwaitingApproval': 1}`
  - `jobs_failed`: OK – no failed Jobs
  - `projection_ui_health`: OK (HTTP 200)
  - `minio_health`: inconclusive from this host (local
    `MINIO_ENDPOINT` not set for the health CLI), but Jobs have MinIO
    env wired and have succeeded.

## 3. Create a Fresh IllustrationProject

From the `illustration-operator` repo on the same machine:

1. Pick or create a sample `IllustrationProject` YAML that targets the
   POC product/code you want to validate (e.g. `P12TRF`):

   ```bash
   cd illustration-operator
   KUBECONFIG=../.kube/pi-k3s.yaml kubectl apply -f config/samples/p12trf-serff-demo.yaml
   ```

2. Record:

   - **IllustrationProject name:** `p12trf-serff-demo`

3. Watch reconciliation:

   ```bash
   KUBECONFIG=../.kube/pi-k3s.yaml \
   kubectl get illustrationprojects.illustrations.poc -n illustrations-poc -o wide
   ```

   - Confirm `.status.phase` is `Succeeded` for `p12trf-serff-demo` and
     `AwaitingApproval` for `p12trf-term-10-15-20-30-serff`.
   - Note any warnings or failure phases.

## 4. Verify Operator Job Execution

1. List Jobs related to the new IllustrationProject:

   ```bash
   KUBECONFIG=../.kube/pi-k3s.yaml \
   kubectl get jobs -n illustrations-poc
   ```

2. Identify the Job that ran `project-minio` for this project (often
   includes the project name in the Job name).

3. Record:

   - **Job name:** `illustration-p12trf-serff-demo` (existing completed
     Job owned by `p12trf-serff-demo`).

4. Optionally inspect Job logs (for debugging only; do not paste secrets
   into this doc).

## 5. Verify Projection Object Creation

From the same machine, use either `kubectl` or MinIO tooling to confirm
that a projection object was written under `projections/`.

Typically you can:

```bash
# If the CRD status records the projection object key
echo "Projection object:" \
  $(KUBECONFIG=../.kube/pi-k3s.yaml \
    kubectl get illustrationprojects.illustrations.poc <project-name> -n illustrations-poc -o jsonpath='{.status.projectionObject}')
```

Record:

- **Projection object key (from CRD status):**
  `projections/p12trf/run-1779282542.json` (historical run)
- **Projection object key (E2E validation run, local CLI):**
  `projections/p12trf/p12trf-e2e-2.json`

## 6. Verify AuditRecord Creation

Given `product_code` and `RUN_ID` used by the Job (often recorded in
CRD status or Job env), the AuditRecord should now live at:

```text
audit/<product_code>/<run_id>/audit_record.json
```

Steps:

1. Derive `run_id` and `product_code` from either:
   - IllustrationProject status fields, or
   - the `IllustrationRun` record (if Postgres is wired), or
   - the Job env used by `project-minio`.

2. Using MinIO tooling (CLI/UI) or a small helper script that uses
   `get_minio_client()`, confirm the object exists.

3. Record:

- **AuditRecord object key (E2E validation run):**
  `audit/P12TRF/p12trf-e2e-2/audit_record.json`

4. For the operator-driven run `p12trf-e2e-operator-1`, the
   AuditRecord object exists at:

   - `audit/P12TRF/37027f0c-148b-4cb5-b55f-6e2c86f1a426/audit_record.json`

   As of the `ghcr.io/billyridgway/actuarypoc:main` runner image used in
   this cluster, that record contains:

   - `product.product_code = "P12TRF"`
   - `product.product_definition_id = null`
   - `filings = []`

   Local CLI runs from this workspace (using the same codebase and the
   POC ProductDefinition JSON under
   `examples/product-definitions/p12trf-product-definition.json`) do
   populate `product_definition_id = "P12TRF-def-v1-poc"` and the
   expected filing refs. The discrepancy indicates the cluster runner
   image has not yet been rebuilt/pushed with the latest
   ProductDefinition-enrichment logic and/or assets.

## 7. Verify RunDetail `audit_summary`

From a machine that can reach the projection UI NodePort
(`http://192.168.50.251:30301`):

```bash
curl -sS "http://192.168.50.251:30301/api/run-detail?key=<projection-object-key>" | jq
```

Confirm the JSON includes an `audit_summary` block with metadata only, e.g.:

```jsonc
{
  "audit_summary": {
    "run_id": "run-123",
    "audit_record_object": "audit/P12TRF/run-123/audit_record.json",
    "product_code": "P12TRF",
    "assumption_set_ids": ["term-risk-class-mapping-v1"],
    "dsl_file": "src/actuarypoc/dsl/examples/p12trf_term.yaml",
    "engine_version": "...",
    "runner_image": "...",
    "created_at": "..."
  },
  ...
}
```

For the E2E runs we triggered:

- Local CLI run (`p12trf-e2e-2`) verified that:
  - `projections/p12trf/p12trf-e2e-2.json` exists and contains
    `inputs.run_id = "p12trf-e2e-2"` and
    `inputs.product_code = "P12TRF"`.
  - `audit/P12TRF/p12trf-e2e-2/audit_record.json` exists and contains
    the expected metadata-only fields (`audit_version`, `run_id`,
    `product.product_code`, `engine`, `inputs`, `outputs`, `dsl.file`,
    `created_at`, etc.).

- Operator-driven run (`p12trf-e2e-operator-1`) verified that:
  - The illustration Job uses
    `ghcr.io/billyridgway/actuarypoc:main` as the runner image.
  - `projections/p12trf/projection-1780109539.json` exists and is the
    projection object for `run_id = 37027f0c-148b-4cb5-b55f-6e2c86f1a426`.
  - `audit/P12TRF/37027f0c-148b-4cb5-b55f-6e2c86f1a426/audit_record.json`
    exists and contains a metadata-only AuditRecord.
  - `/api/run-detail?key=projections/p12trf/projection-1780109539.json`
    returns a populated `audit_summary`:

    ```jsonc
    {
      "run_id": "37027f0c-148b-4cb5-b55f-6e2c86f1a426",
      "audit_record_object": "audit/P12TRF/37027f0c-148b-4cb5-b55f-6e2c86f1a426/audit_record.json",
      "product_code": "P12TRF",
      "assumption_set_ids": ["term-risk-class-mapping-v1"],
      "dsl_file": "/opt/dagster/app/src/actuarypoc/dsl/examples/term_risk_class_mapping.yaml",
      "engine_version": null,
      "runner_image": null,
      "created_at": "2026-05-30T02:52:19.343116"
    }
    ```

## 8. Verify React UI – Audit Information Card

1. In a browser that can reach the cluster, open:

   ```text
   http://192.168.50.251:30301/web?key=<projection-object-key>
   ```

2. On the Run Detail page, confirm the **Audit Information** card shows:

   - Run ID
   - Product Code
   - Assumption Set IDs
   - DSL File
   - Engine Version
   - Runner Image
   - Audit Record Object Key
   - Audit Created At

3. Capture a screenshot (redacting any sensitive policy identifiers if
   present) and attach it to the repo or an issue.

Record:

- **Screenshot path or link:** *(manual step; with the updated
  projection-ui image, the Audit Information card now renders the
  AuditRecord metadata for
  `projections/p12trf/projection-1780109539.json`.)*

## 9. Result and Defects

- **Overall result:** `PARTIAL` – operator-driven path, RunDetail
  `audit_summary`, and UI Audit Information card are working, but the
  in-cluster AuditRecord for `p12trf-e2e-operator-1` does **not** yet
  include `product_definition_id` or filing refs.
- **Date/time of run:** 2026-05-30
- **IllustrationProject name:**
  - historical: `p12trf-serff-demo`
  - e2e operator: `p12trf-e2e-operator-1`
- **Job name:** `illustration-p12trf-e2e-operator-1`
- **Projection object key (operator run):**
  `projections/p12trf/projection-1780109539.json`
- **AuditRecord object key (operator run):**
  `audit/P12TRF/37027f0c-148b-4cb5-b55f-6e2c86f1a426/audit_record.json`

Defects / gaps as of this run:

- Existing in-cluster projections (e.g.
  `projections/p12trf/projection-1779282554.json`) were generated before
  `inputs.run_id` and the AuditRecord writer were in place; they cannot
  be linked to AuditRecords without a migration or deliberate re-run
  under the new code. These are historical artefacts and expected.
- The current runner image `ghcr.io/billyridgway/actuarypoc:main` used
  by the operator Jobs does **not** yet emit ProductDefinition metadata
  into the AuditRecord for `P12TRF` (fields
  `product.product_definition_id` and `filings` are empty in-cluster but
  present when running the same code locally). To fully satisfy the
  updated acceptance criteria for operator-driven AuditRecord e2e, the
  actuarypoc image must be rebuilt from the latest code and the
  operator's `ILLUSTRATION_RUNNER_IMAGE` updated/redeployed, followed by
  another fresh IllustrationProject/Job run.
