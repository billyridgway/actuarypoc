# Product Review Onboarding – P12TRF (MVP Demo Flow)

> Status: **Implemented MVP.** This walkthrough describes how to use the
> in-cluster projection UI to go from product documents + scenarios to the
> existing Product Model Review Trust Surface, without writing code.

This flow is intentionally narrow and demo-focused:

- single product: **P12TRF**
- no authentication or permissions
- no generic document management
- no multi-reviewer workflow

It is designed to show the *shape* of a customer onboarding experience, not
end-state production UX.

---

## 1. Prerequisites

- Pi k3s cluster is running with the `projection-ui` Deployment healthy.
- MinIO and Postgres are reachable from the `projection-ui` pod (see
  `k8s/postgres.yaml` and `k8s/projection-ui.yaml`).
- The `actuarypoc` image tagged `:main` has been built and pushed from the
  GitHub Actions workflow.
- Local port-forward from your laptop/workstation:

  ```bash
  # from the actuarypoc repo root on your machine
  export KUBECONFIG=$HOME/.kube/pi-k3s.yaml
  kubectl -n illustrations-poc port-forward svc/projection-ui 30301:8080
  ```

- Browser pointed at the forwarded UI:

  ```text
  http://localhost:30301/web?view=create-review
  ```

---

## 2. Step 1 – Product Setup

1. Open `http://localhost:30301/web?view=create-review`.
2. In **Product Setup**:
   - Carrier name – e.g. `Demo Carrier`.
   - Product name – e.g. `ICC12 P12TRF Term (demo)`.
   - Product code – `P12TRF` (MVP flow is hard-wired to this code).
   - Product type – e.g. `Level term`.
3. Click **Save draft & continue to documents**.

What happens:

- The UI calls `POST /api/product-review/draft`.
- Backend stores a row in the existing `products` table with
  `product_id = "P12TRF"` and a `metadata` JSONB block containing:
  - `name`, `type`, and a `review.status = "draft"` marker.

---

## 3. Step 2 – Document Upload

1. In **Document Upload**:
   - Drag and drop one or more files (PDF, DOCX, XLSX, CSV), or
   - Click the dropzone to open a file picker.
2. The table below the dropzone lists uploaded documents.

What happens:

- For each upload, the UI calls:

  ```http
  POST /api/product-review/P12TRF/documents
  ```

- The FastAPI handler:
  - Validates extension (`.pdf`, `.docx`, `.xlsx`, `.csv`).
  - Writes the file to MinIO under:

    ```text
    docs/P12TRF/<timestamp>-<original-filename>
    ```

  - Records a row in the `documents` table with:
    - `product_id = "P12TRF"`
    - `kind = "filing"` (MVP default)
    - `description` (from the form or filename)
    - `object_path` pointing at the MinIO key.
  - Returns the updated Product Review payload from
    `GET /api/product-review/P12TRF` so the UI can refresh the list.

This is deliberately a thin index over MinIO objects, *not* a generic
document management system.

---

## 4. Step 3 – Scenario Configuration

1. Scroll to **Scenario Configuration**.
2. The table is pre-populated from the bundled
   `examples/p12trf_scenarios.json` fixture if no scenarios have been saved
   yet.
   - S1 – Typical mid-age non-smoker.
   - S2 – Young short-term coverage.
   - S3 – Edge older age smoker.
3. Edit fields as needed:
   - Age
   - Sex
   - Smoker class
   - Risk class
   - Face amount
   - Level period
   - Premium mode
   - Modal premium
4. Optionally click **Add scenario** to append a new row (still treated as a
   P12TRF test-case for the MVP).
5. Click **Save scenarios & review**.

What happens:

- The UI sends the current table as JSON to:

  ```http
  PUT /api/product-review/P12TRF/scenarios
  ```

- The FastAPI handler:
  - Converts UI rows into the internal structure used by
    `examples/p12trf_scenarios.json`:

    ```jsonc
    {
      "id": "S1",
      "name": "Typical mid-age non-smoker",
      "policy": {
        "policy_number": "P12TRF-S1",
        "product_type": "p12trf_term",
        "issue_age": 35,
        "gender": "M",
        "smoker_class": "NS",
        "risk_class": "SUPER_PREFERRED_NON_TOBACCO",
        "level_period": 20,
        "face_amount": 450000,
        "modal_premium": 450.0,
        "premium_mode": "ANNUAL"
      }
    }
    ```

  - Stores the resulting list under `products.metadata.review.scenarios` for
    `product_id = "P12TRF"`.
  - Returns `GET /api/product-review/P12TRF` so the UI can refresh.

At this point, **scenario configuration lives in Postgres**, aligned with the
scenario generator wiring but editable via forms instead of raw JSON.

---

## 5. Step 4 – Generate Product Review

1. In **Generate Product Review**:
   - Confirm the summary (product, carrier, document count, scenario count).
   - Click **Generate Product Review & open Trust Surface**.

What happens:

- The UI calls:

  ```http
  POST /api/product-review/P12TRF/generate
  ```

- The FastAPI handler:
  - Reads scenarios from `products.metadata.review.scenarios` for P12TRF.
    - If none are present, falls back to the bundled
      `examples/p12trf_scenarios.json`.
  - Uses the same DSL and Term23 wiring as the
    `project-p12trf-scenarios-minio` CLI to:
    - project each scenario policy
    - write projection summaries to MinIO under:

      ```text
      projections/p12trf/scenarios/S1.json
      projections/p12trf/scenarios/S2.json
      projections/p12trf/scenarios/S3.json
      ```

  - Marks the Product Review status as `generated` in
    `products.metadata.review.status`.
  - Returns a small JSON payload:

    ```jsonc
    {
      "ok": true,
      "written": [
        "projections/p12trf/scenarios/S1.json",
        "projections/p12trf/scenarios/S2.json",
        "projections/p12trf/scenarios/S3.json"
      ],
      "redirectUrl": "/web?view=product-model"
    }
    ```

- The React onboarding page reads `redirectUrl` and performs:

  ```text
  window.location.href = "/web?view=product-model"
  ```

This lands the user in the existing **Product Model Review Trust Surface**,
which now reads scenario evidence from the freshly generated
scenario artefacts.

### 5.1 Generation-Scoped Layout

To avoid silently overwriting scenario projections, each Generate action now
creates a **generation_id** and writes artefacts under a generation-scoped
prefix while still maintaining compatibility with the original PMR layout.

- **Generation identifier**
  - Created in `POST /api/product-review/{product_code}/generate`.
  - Format: UTC timestamp like `20260603T120000Z`.
  - Stored in Postgres under `products.metadata.review.current_generation`.

- **Generation-scoped scenario projections (MinIO)**

  ```text
  projections/{product_code_lower}/reviews/{generation_id}/scenarios/{scenario_id}.json
  ```

  Example for P12TRF:

  ```text
  projections/p12trf/reviews/20260603T120000Z/scenarios/S1.json
  ```

- **Backwards-compatible PMR aliases (MinIO)**

  For the existing Product Model Review wiring, the UI server also writes
  alias objects for each scenario under:

  ```text
  projections/p12trf/scenarios/{scenario_id}.json
  ```

  This keeps `/api/product-model-review/p12trf` and the current Trust Surface
  working without change, while preserving per-generation history under the
  `reviews/{generation_id}` prefix.

- **Projection metadata**
  - Each generation-scoped scenario projection JSON includes:

    ```jsonc
    {
      "product_code": "P12TRF",
      "generation_id": "20260603T120000Z",
      "scenario_id": "S1",
      "scenario_label": "Typical mid-age non-smoker",
      "generated_at": "2026-06-03T12:00:00Z",
      "inputs": { ... },
      "metadata": {
        "environment": "...", // when available
        "product_code": "P12TRF",
        "generation_id": "20260603T120000Z",
        "scenario_id": "S1",
        "scenario_label": "Typical mid-age non-smoker"
      },
      "projection": { ... }
    }
    ```

- **Product Review state (Postgres)**
  - `products.metadata.review` now additionally carries:

    ```jsonc
    {
      "status": "generated",
      "current_generation": "20260603T120000Z",
      "generated_at": "2026-06-03T12:00:00Z",
      "written_keys": [
        "projections/p12trf/reviews/20260603T120000Z/scenarios/S1.json",
        "projections/p12trf/reviews/20260603T120000Z/scenarios/S2.json",
        "projections/p12trf/reviews/20260603T120000Z/scenarios/S3.json"
      ],
      "scenarios": [ ... ]
    }
    ```

- **Product Review API payload**
  - `GET /api/product-review/P12TRF` exposes these as:

    ```jsonc
    "review": {
      "status": "generated",
      "currentGeneration": "20260603T120000Z",
      "generatedAt": "2026-06-03T12:00:00Z",
      "writtenKeys": [ ... ]
    }
    ```

- **Trust Surface review summary**
  - `/api/product-model-review/p12trf` now returns a `reviewMeta` block:

    ```jsonc
    "reviewMeta": {
      "currentGeneration": "20260603T120000Z",
      "generatedAt": "2026-06-03T12:00:00Z",
      "documentCount": 3,
      "scenarioCount": 3
    }
    ```

  - The React PMR page surfaces this in the **Review Summary (POC)** card so
    actuaries can see which generation and document set the current Trust
    Surface is based on.

---

## 6. Definition of Done Checklist

This MVP flow is considered complete when:

- [x] A user can start from `/web?view=create-review` with no local code
      changes.
- [x] Product metadata can be entered and persisted as a Product Review
      draft.
- [x] Documents can be uploaded via the UI, stored in MinIO, and indexed in
      Postgres.
- [x] Scenarios can be configured via forms instead of JSON and saved as
      review configuration.
- [x] Clicking **Generate Product Review** projects the configured scenarios
      for P12TRF and writes generation-scoped artefacts under
      `projections/{product_code_lower}/reviews/{generation_id}/scenarios/*.json`,
      while also maintaining alias objects at `projections/p12trf/scenarios/*.json`.
- [x] The flow redirects into the existing Trust Surface
      (`/web?view=product-model`).
- [x] Runtime is verified in the Pi k3s cluster (Deployment rolled out,
      `/health` OK, onboarding and PMR flows accessible via port-forward) and
      generation-scoped artefacts are visible in the Product Review API and
      Trust Surface review summary.

This document should be kept in sync with future iterations of the onboarding
flow (additional products, richer metadata, or more advanced workflow), but
those should remain clearly scoped beyond this MVP slice.
