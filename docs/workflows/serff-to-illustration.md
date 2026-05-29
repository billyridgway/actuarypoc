# SERFF-to-Illustration Workflow (Design)

> Status: **Design only.** This document describes how SERFF filings should
> flow through the platform, using FilingRecords and ProductDefinitions as
> first-class concepts.
>
> Many steps here are **planned or partial**; only the parts explicitly noted
> as implemented exist in the current codebase.

Target hierarchy:

```text
SERFF Filing
→ FilingRecord
→ ProductDefinition
→ AssumptionSets (and other product components)
→ Illustration Runs (and AuditRecords)
```

---

## 1. Roles and Ownership

- **Ingestion layer (future)**
  - Accepts SERFF filings (zips/PDFs) from humans or upstream systems.
  - Stores raw artefacts in MinIO under standardized prefixes.

- **ActuaryPOC backend (this repo)**
  - Text/PDF extraction and AI triage of documents (partial today).
  - Construction of `FilingRecord` objects (planned).
  - Maintenance of `ProductDefinition` and `AssumptionSet` metadata (planned,
    building on existing DSL and assumptions registry).
  - Projection engine (`project-minio`) and RunDetail API (implemented).

- **Illustration Operator (separate repo)**
  - Turns `IllustrationProject` CRDs into Jobs that run projections using
    the `actuarypoc` image (implemented).
  - Exposes projection object keys and wiring details on CRD status
    (implemented).

- **UI / Tools**
  - Projection viewer (React UI served from this repo) (implemented).
  - Future filing review UI for filing/assumption review (planned).

---

## 2. MinIO Layout and Object Model (Proposed)

The following layout builds on existing prefixes and adds SERFF‑specific
areas. Only prefixes marked **implemented** exist today.

### 2.1 Existing Prefixes (Implemented)

- `pas_export/` – PAS exports (JSON) used as policy inputs.
- `actuarial_tables/` – primary actuarial tables.
- `actuarial_tables_term23/` – Term23 mortality slice.
- `crm_accounts/` – CRM accounts.
- `rate_curves/` – yield curves.
- `p12trf/` – P12TRF‑specific policy data.
- `projections/` – projection summaries written by `project-minio`.
- `audit/` – audit and input snapshot objects (when `project-minio` is
  configured to write them).

### 2.2 SERFF and Filing Layout (Planned)

New, SERFF‑oriented prefixes (design only):

```text
filings/<product_code>/raw/<filing_id>/<filename>
filings/<product_code>/text/<filing_id>/<basename>.txt
filings/<product_code>/meta/<filing_id>/<basename>.json
filings/<product_code>/classified/<filing_id>.json
filings/<product_code>/records/<filing_id>.json   # FilingRecord

premium_tables/<product_code>/<filing_id>/<table>.csv
```

- `raw/` – original SERFF bundles (zip/PDF/Word).
- `text/` – extracted text for each document.
- `meta/` – per‑document metadata (page counts, hashes, etc.).
- `classified/` – AI triage results mapping docs to roles (memo, tables, etc.).
- `records/` – canonical `FilingRecord` JSONs.
- `premium_tables/` – tables derived from SERFF or internal rate sheets.

These prefixes are **not yet created or enforced** by the code; they are
proposed targets.

---

## 3. Workflow Steps

### Step 1 – SERFF Upload (Planned)

**Goal:** Ingest a SERFF filing into the platform in a reproducible way.

- Input:
  - SERFF zip and/or individual PDFs.
  - Metadata: `product_code`, jurisdictions, optional SERFF tracking ID.
- Component: future `actuarypoc` CLI/API (e.g. `serff-upload`).
- Actions:
  1. Assign a `filing_id` (could be SERFF ID or an internal ID).
  2. Store raw files in:

     ```text
     filings/<product_code>/raw/<filing_id>/<filename>
     ```

- Implementation status: **Planned.** Today, SERFF‑like docs must be
  manually copied into MinIO if used at all.

### Step 2 – Text Extraction (Partial)

**Goal:** Convert raw documents into text suitable for LLM analysis and
assumption extraction.

- Input: raw docs in `filings/<product>/raw/<filing_id>/`.
- Component: PDF/text extraction utilities (partially implemented in prior
  POC code under `pipeline/pdf_extract.py` and earlier UI servers).
- Actions:
  1. For each supported file type (PDF, DOCX, TXT):
     - Extract text.
     - Store as:

       ```text
       filings/<product_code>/text/<filing_id>/<basename>.txt
       filings/<product_code>/meta/<filing_id>/<basename>.json
       ```

- Implementation status: **Partial.** The extraction code exists, but there
  is no unified CLI or workflow that runs this systematically against
  `filings/` prefixes.

### Step 3 – Document Classification (Partial)

**Goal:** Identify which extracted docs are relevant to assumptions and
product configuration.

- Input: text docs + per‑file metadata.
- Component: LLM triage logic used in the earlier AI‑assisted upload flow
  (previous `ui_server.py` implementation) – currently not exposed as a clean
  module.
- Actions:
  1. For each text doc:
     - Ask the LLM to classify it as one or more of:
       - `actuarial_memo`
       - `premium_tables`
       - `risk_mapping`
       - `sov`
       - `other`.
  2. Write summary JSON:

     ```jsonc
     {
       "filing_id": "P12TRF-2020-01",
       "product_code": "P12TRF",
       "docs": [
         {
           "key": "filings/P12TRF/text/P12TRF-2020-01/actuarial_memo.txt",
           "role": ["actuarial_memo"],
           "keep_recommended": true
         },
         ...
       ]
     }
     ```

     Stored at:

     ```text
     filings/<product_code>/classified/<filing_id>.json
     ```

- Implementation status: **Partial/legacy**. The concept and code exist, but
  need to be pulled into a dedicated module and wired to the filings/
  prefixes.

### Step 4 – FilingRecord Construction (Planned)

**Goal:** Create a canonical FilingRecord from classified docs and metadata.

- Input:
  - Upload metadata (product code, jurisdictions, etc.).
  - Classification results (`classified/<filing_id>.json`).
- Component: new `FilingRecord` builder in `actuarypoc`.
- Actions:
  1. Aggregate:
     - product code and marketing name
     - jurisdictions
     - SERFF tracking ID (if available)
     - lists of doc keys grouped by role.
  2. Write a `FilingRecord` JSON as defined in `docs/audit-model.md` to:

     ```text
     filings/<product_code>/records/<filing_id>.json
     ```

- Implementation status: **Planned.** No single builder exists yet; this
  document defines the target behavior.

### Step 5 – ProductDefinition Update (Planned/Partial)

**Goal:** Keep a canonical ProductDefinition in sync with filings and
assumptions.

- Input:
  - FilingRecord(s) for a product.
  - Existing DSL file(s) under `src/actuarypoc/dsl/`.
  - Premium tables derived from SERFF (future) or synthetic tables (current).
  - AssumptionSets (current registry).
- Component: future ProductDefinition builder / updater.
- Actions:
  1. For each product code:
     - Initialize or update a ProductDefinition that includes:
       - product code, marketing name, forms, jurisdictions.
       - DSL reference (file path and optional hash).
       - premium table references and their source filings.
       - AssumptionSets and their roles.
       - filing references (`filing_refs`).
  2. Store this representation either as:
     - a JSON definition in MinIO (design target), and/or
     - synthesized from DSL and operator config at runtime.

- Implementation status:
  - **Partial:** DSL files and operator `products.yaml` already encode pieces
    of this.
  - **Planned:** a unified ProductDefinition representation as described in
    `docs/audit-model.md`.

### Step 6 – AssumptionSet Extraction and Approval (Implemented/Planned Links)

**Goal:** Extract and approve AssumptionSets derived from filings.

- Input:
  - Classified doc keys (e.g. actuarial memos, risk mapping docs).
  - FilingRecord and ProductDefinition context.
- Component:
  - `extract-assumptions-minio` CLI (implemented).
  - AssumptionSet registry (implemented).
- Actions:
  1. For a given product/filing:
     - Run `extract-assumptions-minio` with:
       - `LLM_DOC_PREFIX` pointing to the chosen docs.
       - `LLM_PRODUCT_CODE` set to the product code.
       - `LLM_ASSUMPTION_ID` including the filing ID (e.g.
         `P12TRF-2020-01-assumptions-v1`).
  2. Upsert the resulting AssumptionSet into the registry.
  3. Manually review and then mark the AssumptionSet as approved and current
     using `approve-assumption`.

- Implementation status:
  - **Implemented:** extraction and approval CLIs, storage in MinIO registry.
  - **Planned:** stronger metadata linking AssumptionSets to FilingRecords and
    ProductDefinitions.

### Step 7 – Illustration Runs (Implemented)

**Goal:** Run projections that are wired to ProductDefinitions and
AssumptionSets.

- Input:
  - ProductDefinition/AssumptionSets for a product.
  - Config in the operator’s `products.yaml` to identify DSL, prefixes, and
    assumption IDs.
  - PAS/actuarial/rate/CRM data in MinIO.
- Component:
  - `IllustrationProject` CRDs and illustration operator (implemented).
  - `project-minio` CLI in `actuarypoc` (implemented).
- Actions:
  1. Create an `IllustrationProject` referring to the product.
  2. Operator resolves product wiring, ensures assumptions Jobs (if used),
     and creates illustration Job.
  3. Job runs `project-minio`, writing a projection JSON and optional
     audit/input snapshots.
  4. Operator sets CRD status with projection/audit object keys and
     assumption set ID.

- Implementation status: **Implemented** for the P12TRF POC and similar
  scenarios.

### Step 8 – Audit and Review (Partially Implemented)

**Goal:** Allow actuaries and engineers to review how a projection was
produced and which filings/assumptions it depended on.

- Input:
  - Projection object key (e.g. from CRD status or UI).
  - AssumptionSet registry.
  - (Future) ProductDefinition and FilingRecord.
- Component:
  - RunDetail API + React UI (implemented).
  - Canonical `AuditRecord` model (defined in `docs/audit-model.md`).
- Actions:
  1. RunDetail API loads projection JSON and related inputs.
  2. UI displays trust status, assumptions, premiums, projection arrays, and
     audit sources.
  3. In the future, an AuditRecord view would:
     - pull FilingRecord, ProductDefinition, AssumptionSets, and object keys
       into a single representation.

- Implementation status:
  - **Implemented:** RunDetail API and UI, basic audit sources via MinIO keys.
  - **Planned:** FilingRecord/ProductDefinition integration and canonical
    AuditRecord materialization.

---

## 4. Acceptance Criteria for This Design Phase

For this Phase 2 design work (docs only), we consider SERFF-to-illustration
workflow design **done** when:

1. `docs/workflows/serff-to-illustration.md`:
   - Defines each step from SERFF upload to projection review.
   - Assigns ownership to components (ingestion, ActuaryPOC, operator, UI).
   - Distinguishes clearly between implemented, partial, and planned steps.
   - Specifies MinIO prefixes and object layouts for filings and premium
     tables.
   - Explains how FilingRecords, ProductDefinitions, AssumptionSets, and
     AuditRecords relate.

2. `docs/audit-model.md`:
   - Defines FilingRecord, ProductDefinition, AssumptionSet links, and
     AuditRecord shape with enough detail to guide future code changes.

No code changes will have been made yet as part of this phase; these docs are
specs that Phase 3/4 code changes will implement.

---

## 5. Risks and Open Questions

- **SERFF complexity and variability**
  - Filings can cover multiple products, riders, and jurisdictions; the
    FilingRecord model may need to support many-to-many relationships.

- **Versioning and superseded filings**
  - How to handle multiple filings for the same product over time
    (e.g. new forms replacing old ones) without confusing historical
    projections.

- **Human vs. AI responsibilities**
  - Which classification and extraction steps are safe to fully automate, and
    which should require explicit human approval in a UI.

- **Where to store ProductDefinitions**
  - As MinIO objects, in code (DSL + config), in CRDs, or a combination.

- **Performance and cost**
  - LLM-based classification and extraction could be expensive; we may need
    caching and batching strategies that are beyond the scope of this initial
    design.
