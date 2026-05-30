# ADR: Operator-Driven AuditRecord E2E Validation (p12trf-e2e-operator-3)

## Context

We needed to prove that the end-to-end path from an `IllustrationProject` CRD through the illustration operator, projection runner, storage, API, and UI correctly produces and surfaces an `AuditRecord` enriched with ProductDefinition and Filing metadata for the POC product **P12TRF**.

This ADR documents what was validated by the **`p12trf-e2e-operator-3`** run and what remains as known gaps.

---

## IllustrationProject Lifecycle

**What was validated**

- An `IllustrationProject` in namespace `illustrations-poc` is the user-facing unit of work for an illustration run.
- Key fields:
  - `spec.productId`: product identity (e.g. `p12trf`, lower-case)
  - `spec.horizonYears`, `spec.mode`, `spec.notes`
- Lifecycle (happy path):
  1. `IllustrationProject` is created with `productId = p12trf`.
  2. Operator resolves product config (from `CONFIG_PATH=/config/products.yaml`) and writes `status.resolved` fields (e.g. `dslFile`, `filingsPrefix`, `docPrefix`).
  3. Assumptions are prepped and approved (`status.assumptionApproved = true`, `status.assumptionSetId = p12trf-llm-v1`).
  4. Operator creates a one-shot Job (`illustration-p12trf-e2e-operator-3`) with environment wiring for the runner.
  5. On Job completion, operator updates `status`:
     - `status.phase = Succeeded`
     - `status.lastRunId` to the run identifier
     - `status.projectionObject` to the projection object key
     - `status.auditObject` / `status.inputSnapshotObject` to their object keys
     - `status.runnerImage` to the runner image used

**Evidence**

- `IllustrationProject` `p12trf-e2e-operator-3` in `illustrations-poc` with:
  - `status.phase = Succeeded`
  - `status.projectionObject = projections/p12trf/61bd4ca2-5eb1-46d8-ac29-4a950c1e9422/projection.json`
  - `status.auditObject = audit/p12trf/61bd4ca2-5eb1-46d8-ac29-4a950c1e9422/audit.json`
  - `status.runnerImage = ghcr.io/billyridgway/actuarypoc:main`

---

## Operator Responsibilities

**What was validated**

- Watches `IllustrationProject` resources and reconciles them into Jobs.
- For P12TRF projects:
  - Injects environment into the Job:
    - `PRODUCT_ID = p12trf`
    - `PROJECT_NAME = <project-name>`
    - `RUN_ID = <IllustrationProject.metadata.uid>` (for p12trf-e2e-operator-3: `61bd4ca2-...`)
    - `FILINGS_PREFIX = filings/p12trf/`
    - `POLICIES_PREFIX = p12trf/`
    - `PROJECTIONS_PREFIX = projections/p12trf/`
    - `PROJECTION_OBJECT_NAME = projections/p12trf/<RUN_ID>/projection.json`
    - `AUDIT_OBJECT_NAME = audit/p12trf/<RUN_ID>/audit.json`
    - `INPUT_SNAPSHOT_OBJECT_NAME = audit/p12trf/<RUN_ID>/inputs.json`
  - Selects the projection runner image via env:
    - `ILLUSTRATION_RUNNER_IMAGE = ghcr.io/billyridgway/actuarypoc:main`
- Ensures Job pod runs the runner command:

  ```sh
  /bin/sh -c "set -euo pipefail; ...; cd /opt/dagster/app; python -m actuarypoc.cli.main project-minio"
  ```

**Scope**

- Operator does **not** load ProductDefinition directly; it delegates all product- and filing-level semantics to the runner code via the `PRODUCT_ID` and object prefixes.

---

## Projection Runner Responsibilities

**What was validated**

- Image: `ghcr.io/billyridgway/actuarypoc:main` (digest `sha256:2c8614a6...` for p12trf-e2e-operator-3).
- Entrypoint (`project-minio`) inside the container is responsible for:
  - Reading PAS and other actuarial inputs from MinIO using the `<PREFIX>` environment variables.
  - Building a projection summary that includes:
    - `inputs.product_code`
    - `inputs.run_id` (from `RUN_ID` env)
    - various input object keys (`pas_object`, `actuarial_object`, etc.).
  - Writing the **projection object** into MinIO under `PROJECTIONS_PREFIX` with a generated key.
  - Computing an `AuditRecord` via `build_audit_record_from_summary`.
  - Writing:
    - `audit/<PRODUCT_CODE>/<RUN_ID>/audit_record.json`
    - `audit/<product_code_lower>/<RUN_ID>/audit.json` (legacy audit payload)
    - `audit/<product_code_lower>/<RUN_ID>/inputs.json` (input snapshot)

**Proven behavior**

- For run `61bd4ca2-5eb1-46d8-ac29-4a950c1e9422`:
  - Projection object `projections/p12trf/projection-1780167342.json` exists and contains:
    - `inputs.run_id = "61bd4ca2-5eb1-46d8-ac29-4a950c1e9422"`
    - `inputs.product_code = "P12TRF"`.
  - AuditRecord `audit/P12TRF/61bd4ca2-5eb1-46d8-ac29-4a950c1e9422/audit_record.json` exists and is enriched as described below.

---

## AuditRecord Contract

**What was validated**

- `AuditRecord` is a metadata-only JSON document containing:
  - `audit_version`: currently `"1.0"`.
  - `run_id`: logical run identifier (here equal to the `IllustrationProject` UID).
  - `product`:
    - `product_code`: e.g. `"P12TRF"`.
    - `product_definition_id`: best-effort linkage to ProductDefinition (see below).
  - `assumptions`: list containing `assumption_set_id` when present.
  - `engine`:
    - `engine_version` (nullable).
    - `runner_image` (nullable; not currently populated in-cluster).
  - `inputs`:
    - `pas_export`, `actuarial_tables`, `term23_actuarial`, `rate_curves`, `crm_accounts`, `premium_table` – all object keys only.
  - `outputs`:
    - `projection_object`: projection object key.
    - `audit_object`: legacy audit object key (from `AUDIT_OBJECT_NAME`).
    - `input_snapshot_object`: input snapshot object key.
  - `dsl.file`: DSL file path used for the run.
  - `filings`: list of filing metadata (see below).
  - `environment`: environment label (nullable).
  - `created_at`: ISO timestamp (aligned with projection `generated_at`).

**Naming convention validated**

- **AuditRecord key**:

  ```text
  audit/<PRODUCT_CODE>/<RUN_ID>/audit_record.json
  ```

  For P12TRF operator run 3:

  - `audit/P12TRF/61bd4ca2-5eb1-46d8-ac29-4a950c1e9422/audit_record.json`

---

## ProductDefinition Linkage

**What was validated**

- The runner uses a best-effort helper to load a local ProductDefinition JSON for the product code in the projection summary.
- Implementation details for P12TRF:
  - ProductDefinition file shipped in the repo:

    ```text
    examples/product-definitions/p12trf-product-definition.json
    ```

  - Key fields in that file:

    ```json
    {
      "product_definition_id": "P12TRF-def-v1-poc",
      "product_code": "P12TRF",
      ...
      "filing_refs": [ ... ]
    }
    ```

- For run `61bd4ca2-…`, the runner:
  - Detects `product_code = "P12TRF"` from the summary inputs.
  - Loads the POC ProductDefinition JSON.
  - Mutates the `AuditRecord` with:

    ```json
    "product": {
      "product_code": "P12TRF",
      "product_definition_id": "P12TRF-def-v1-poc"
    }
    ```

**Scope**

- Linkage is **metadata-only**: no SERFF payloads, PDFs, or PAS details are embedded in the `AuditRecord`.

---

## FilingRecord Linkage

**What was validated**

- The runner extracts `filing_refs` from the ProductDefinition and projects them into the AuditRecord as a list of small metadata dictionaries:

  ```json
  "filings": [
    {
      "filing_id": "P12TRF-2020-01 (placeholder)",
      "serff_tracking_id": "SERFF-PLACEHOLDER"
    }
  ]
  ```

- For run `61bd4ca2-…`, `audit/P12TRF/61bd4ca2-5eb1-46d8-ac29-4a950c1e9422/audit_record.json` contains exactly this list.

**Scope**

- No full FilingRecord schema or SERFF integration yet; filing IDs and tracking IDs are POC placeholders.

---

## RunDetail Contract

**What was validated**

- HTTP API:

  ```text
  GET /api/run-detail?key=<projection-object-key>
  ```

- For `p12trf-e2e-operator-3`, using:

  ```text
  key = projections/p12trf/projection-1780167342.json
  ```

  the response includes:

  - `run`: high-level run metadata (run_id, status, created_at, product_code, etc.).
  - `policy_input`: PAS-derived core fields.
  - `assumptions`: assumption set id and approval status.
  - `audit_sources.objects`:
    - `projection_object`: same key as the request `key`.
    - `audit_object`: `audit/P12TRF/61bd4ca2-5eb1-46d8-ac29-4a950c1e9422/audit_record.json`.
  - `projection_summary`: summarized projection arrays and a `links.projection_object` field.
  - `audit_summary`:

    ```json
    {
      "run_id": "61bd4ca2-5eb1-46d8-ac29-4a950c1e9422",
      "audit_record_object": "audit/P12TRF/61bd4ca2-5eb1-46d8-ac29-4a950c1e9422/audit_record.json",
      "product_code": "P12TRF",
      "assumption_set_ids": ["term-risk-class-mapping-v1"],
      "dsl_file": "/opt/dagster/app/src/actuarypoc/dsl/examples/term_risk_class_mapping.yaml",
      "engine_version": null,
      "runner_image": null,
      "created_at": "2026-05-30T18:55:42.233469"
    }
    ```

**Projection object naming validated**

- Projection objects live under a product-specific prefix:

  ```text
  projections/<productId-lower>/...
  ```

- For the operator runs we validated:
  - CLI-focused run: `projections/p12trf/p12trf-e2e-2.json`
  - Operator run 1: `projections/p12trf/projection-1780109539.json`
  - Operator run 3: `projections/p12trf/projection-1780167342.json`

  The exact filename pattern (`projection-<timestamp>.json` vs `p12trf-e2e-<n>.json`) is an implementation detail; the **contract** is that:
  - The CRD status and UI/API both refer to the **full object key**.
  - That key resolves in MinIO and includes `inputs.run_id` and `inputs.product_code`.

---

## UI Audit Surface

**What was validated**

- Web UI is served at:

  ```text
  /web?key=<projection-object-key>
  ```

- For `key=projections/p12trf/projection-1780167342.json`, the Run Detail page renders an **Audit Information** card fed by `audit_summary` and `audit_sources` from the RunDetail API.
- The Audit Information card surfaces at least:
  - Run ID
  - Product Code
  - Assumption Set IDs
  - DSL File
  - Engine Version
  - Runner Image
  - Audit Record Object Key
  - Audit Created At

**Result**

- With the refreshed image, the UI now indirectly reflects the ProductDefinition-enriched AuditRecord for P12TRF via the RunDetail `audit_summary` and `audit_sources` data.

---

## Object Naming Conventions Validated

**Projection objects**

- Prefix: `projections/<productId-lower>/`
- Examples validated:
  - `projections/p12trf/p12trf-e2e-2.json`
  - `projections/p12trf/projection-1780109539.json`
  - `projections/p12trf/projection-1780167342.json`

**AuditRecord objects**

- Canonical key for the AuditRecord JSON:

  ```text
  audit/<PRODUCT_CODE>/<RUN_ID>/audit_record.json
  ```

- Example validated:

  ```text
  audit/P12TRF/61bd4ca2-5eb1-46d8-ac29-4a950c1e9422/audit_record.json
  ```

**Other audit-related objects**

- Legacy audit payload:

  ```text
  audit/<productId-lower>/<RUN_ID>/audit.json
  ```

- Input snapshot payload:

  ```text
  audit/<productId-lower>/<RUN_ID>/inputs.json
  ```

These additional objects are not part of the public API contract yet but are produced by the same runner invocation.

---

## Known Gaps and Limitations

The following are **not** solved by the p12trf-e2e-operator-3 validation and remain explicit gaps:

1. **Historical projections without AuditRecords**
   - Older projection objects (e.g. `projections/p12trf/projection-1779282554.json`) pre-date `inputs.run_id` and the AuditRecord writer. They cannot be retro-linked to AuditRecords without a migration or re-run.

2. **CRD `projectionObject` vs. actual projection key**
   - `IllustrationProject.status.projectionObject` currently uses a `.../<RUN_ID>/projection.json` path, while the actual projection key is a flat `projection-<timestamp>.json` under the product prefix.
   - RunDetail and the UI use the actual key; the CRD status link is best-effort and may not always resolve.

3. **Engine version and runner image in AuditRecord**
   - In-cluster `AuditRecord` and `audit_summary` continue to show `engine_version = null` and `runner_image = null`.
   - The underlying data (image digest, etc.) exists at the Kubernetes level but is not yet wired through into the AuditRecord and RunDetail.

4. **Single-product ProductDefinition**
   - Only P12TRF has a wired ProductDefinition JSON and filing refs.
   - There is no multi-product registry, versioning strategy, or clear precedence rules for future products.

5. **Placeholder Filing metadata**
   - Filing IDs and SERFF tracking IDs are POC placeholders; there is no integration with a real filing system, SERFF, or regulatory document store.

6. **Operational observability**
   - No dedicated metrics/alerts for:
     - Failed AuditRecord writes.
     - Mismatches between projection objects and AuditRecords.
     - Stale or missing ProductDefinition assets.

7. **Security / PII considerations**
   - While the current AuditRecord is metadata-only, there is no formal policy or validation guard to prevent accidental inclusion of PHI/PII or raw PAS data in future changes.

8. **Assumption approval flow**
   - In this validation, `assumptionApproved` was toggled via a direct status patch. A full operator+UI-driven approval workflow (with audit history) is not yet implemented.

These gaps should inform the next set of platform milestones.
