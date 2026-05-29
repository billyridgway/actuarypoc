# Canonical Audit Model – Insurance Illustration Platform

> Status: **Spec only**. This document defines the intended canonical audit
> model. Not all components implement it today. Implemented vs. planned
> elements are called out explicitly.

The goal of this model is to make every illustration run **explainable and
reproducible** by tying together:

- SERFF filings
- filing‑level metadata
- product definitions
- assumption sets
- input data snapshots
- engine and image versions
- projection outputs

The hierarchy is:

```text
SERFF Filing
→ FilingRecord
→ ProductDefinition
→ AssumptionSets (and other product components)
→ Illustration Runs (and their AuditRecords)
```

Today, only parts of this hierarchy exist in code:

- Assumption sets are implemented and stored in a MinIO‑backed registry.
- Product knowledge is partly embedded in DSL files and the operator’s
  `products.yaml`.
- Projection summaries and basic audit snapshots exist in MinIO.
- CRD status and the RunDetail API expose some wiring information.

`FilingRecord`, `ProductDefinition` as a first‑class concept, and a single
canonical `AuditRecord` are defined here as **design targets**.

---

## 1. Core Entities

### 1.1 SERFF Filing (Conceptual Only)

A SERFF filing is the regulator‑facing package that contains forms, rates,
actuarial memoranda, statements of variability, and supporting material. The
platform does **not** currently ingest SERFF natively; this is modeled here so
future ingestion can attach to the rest of the audit surface.

Key conceptual attributes:

- `serff_tracking_id`
- `company_name`
- `product_marketing_name`
- `jurisdictions` (e.g. list of states)
- `submitted_at`, `approved_at`

In the POC, SERFF artefacts are represented only indirectly (file names,
notes); there is no `SERFF` type in code.

### 1.2 FilingRecord (Primary SERFF‑Derived Artefact)

**FilingRecord** is the primary object the platform derives from SERFF
filings. It normalizes the core metadata and points at the actual docs stored
in MinIO.

> **Implementation status:** Planned. Some pieces (PDF/text extraction,
> AI triage, assumption extraction) exist, but there is no single
> `FilingRecord` object or storage location yet.

Proposed JSON shape (stored in MinIO):

```jsonc
{
  "record_version": "1.0",
  "filing_id": "P12TRF-2020-01",          // platform-level ID or SERFF ID
  "serff_tracking_id": "SERFF-...",      // optional
  "product_code": "P12TRF",
  "product_marketing_name": "Pacific Life ICC12 P12TRF Term",
  "company_name": "...",
  "jurisdictions": ["CA", "TX"],
  "submitted_at": "2020-01-17T00:00:00Z",
  "approved_at": "2020-03-01T00:00:00Z",
  "raw_docs": [
    "filings/P12TRF/raw/P12TRF-2020-01/filing.zip"
  ],
  "text_docs": [
    "filings/P12TRF/text/P12TRF-2020-01/actuarial_memo.txt"
  ],
  "classified_docs": {
    "actuarial_memo": ["filings/P12TRF/text/P12TRF-2020-01/actuarial_memo.txt"],
    "premium_tables": ["filings/P12TRF/text/P12TRF-2020-01/rates.txt"],
    "risk_mapping": ["filings/P12TRF/text/P12TRF-2020-01/risk_mapping.txt"],
    "sov": ["filings/P12TRF/text/P12TRF-2020-01/sov.txt"]
  }
}
```

Proposed MinIO location:

```text
filings/<product_code>/records/<filing_id>.json
```

### 1.3 ProductDefinition (Canonical Product View)

**ProductDefinition** is the canonical representation of an insurance product
in the platform. It aggregates:

- core identification
- form and jurisdiction scope
- DSL and config
- premium tables
- assumption sets
- riders and underwriting classes
- filing references.

> **Implementation status:** Partially implemented in two places:
>
> - DSL YAML under `src/actuarypoc/dsl/` (e.g. `p12trf_term.yaml`).
> - Product registry in the operator repo (`config/products.yaml`).
>
> There is no single `ProductDefinition` type yet; this section defines the
> desired shape.

Proposed logical fields:

```jsonc
{
  "product_definition_version": "1.0",
  "product_code": "P12TRF",
  "marketing_name": "Pacific Life ICC12 P12TRF Term",
  "form_numbers": ["ICC12 P12TRF"],
  "jurisdictions": ["CA", "TX"],
  "issue_age_min": 18,
  "issue_age_max": 75,
  "riders": ["waiver_of_premium", "child_term"],
  "underwriting_classes": ["Preferred NT", "Standard NT", "Smoker"],

  "dsl": {
    "file": "p12trf_term.yaml",             // maps to src/actuarypoc/dsl/examples/
    "hash": "sha256-...",                  // optional
    "meta": {
      "premium_table_prefix": "premium_tables/P12TRF/",
      "source_filing_ids": ["P12TRF-2020-01"]
    }
  },

  "premium_tables": [
    {
      "kind": "level_term_premium",
      "object": "premium_tables/P12TRF/P12TRF-2020-01/level_term.csv",
      "source_filing_id": "P12TRF-2020-01"
    }
  ],

  "assumption_sets": [
    {
      "id": "P12TRF-2020-01-assumptions-v1",
      "source_filing_id": "P12TRF-2020-01",
      "role": "base_mortality_and_lapse"
    }
  ],

  "filing_refs": [
    {
      "filing_id": "P12TRF-2020-01",
      "serff_tracking_id": "SERFF-..."
    }
  ],

  "illustration_config": {
    "default_horizon_years": 40,
    "allowed_modes": ["adhoc"],
    "supports_pas_configmap": true
  }
}
```

ProductDefinitions may be **derived** from one or more FilingRecords, but they
are conceptually separate: FilingRecords describe *what was filed*, while
ProductDefinitions describe *how the platform understands the product*.

### 1.4 AssumptionSets (Component of ProductDefinition)

AssumptionSets capture specific actuarial assumptions (mortality, lapse,
expenses, mapping rules). In the POC, they already exist as concrete objects
stored in the MinIO‑backed registry (`config-assumption_sets.json` in the
workspace is an example export).

> **Implementation status:** Implemented, but not yet fully wired to
> FilingRecords and ProductDefinitions.

Key fields (current POC):

- `id` – logical identifier (e.g. `term-risk-class-mapping-v1`).
- `product_code` – e.g. `P12TRF`.
- `description` – human‑readable.
- `status` – draft/approved.
- `is_current` – whether this is the current set for the product.

Cross‑linking to the new concepts (planned fields in future schema/doc):

- `source_filing_id` – link back to FilingRecord.
- `source_doc_keys` – SERFF docs used to derive the set.
- `product_definition_id` – link into a ProductDefinition.

### 1.5 AuditRecord (Run-Level Canonical Artefact)

**AuditRecord** describes a single illustration run (or batch run) and ties
it to:

- the ProductDefinition that governed it
- the specific AssumptionSets and premium tables used
- the FilingRecords that underlie those assumptions
- the concrete MinIO objects for inputs and outputs.

> **Implementation status:** Not implemented as a named object yet.
> Projection JSONs, audit snapshots, CRD status, and RunDetail JSON contain
> the necessary **pieces**, but not yet in a unified record.

Proposed shape (focused on the POC context, extensible later). The initial
implementation in `project-minio` populates only a **safe subset** of these
fields (see below):

```jsonc
{
  "audit_version": "1.0",

  "run_id": "run-1779282542",               // e.g. UID or Job-based ID
  "project_name": "p12trf-serff-demo",
  "environment": "dev-k3s",

  "product": {
    "product_code": "P12TRF",
    "product_definition_id": "P12TRF-def-v1"    // optional/logical ID
  },

  "filings": [
    {
      "filing_id": "P12TRF-2020-01",
      "serff_tracking_id": "SERFF-..."
    }
  ],

  "assumptions": [
    {
      "assumption_set_id": "P12TRF-2020-01-assumptions-v1",
      "role": "base_mortality_and_lapse",
      "status": "approved"
    }
  ],

  "engine": {
    "engine_version": "0.1.0",               // from env or code
    "runner_image": "ghcr.io/.../actuarypoc:main"
  },

  "inputs": {
    "pas_export": "pas_export/p12trf-...json",
    "actuarial_tables": "actuarial_tables/actuarial_tables-...json",
    "term23_actuarial": "actuarial_tables_term23/...json",
    "rate_curves": "rate_curves/rate_curves-...json",
    "crm_accounts": "crm_accounts/crm_accounts-...json",
    "premium_table": "premium_tables/P12TRF/P12TRF-2020-01/level_term.csv"
  },

  "outputs": {
    "projection_object": "projections/P12TRF/run-1779282542.json",
    "audit_object": "audit/P12TRF/run-1779282542/audit.json",
    "input_snapshot_object": "audit/P12TRF/run-1779282542/inputs.json"
  },

  "created_at": "2026-05-29T09:39:49Z",
  "notes": "optional human/debug notes"
}
```

Proposed MinIO location (when/if materialized):

```text
audit/<product_code>/<run_id>/audit_record.json
```

In the near term, `AuditRecord` may remain a **logical view** constructed on
request by combining:

- projection JSON
- audit/input snapshot JSONs
- CRD status
- ProductDefinition lookup
- FilingRecord lookup
- AssumptionSet metadata.

**Current implementation subset:**

The `project-minio` CLI now writes an `AuditRecord` JSON under
`audit/<product_code>/<run_id>/audit_record.json` when both `RUN_ID` and a
non-empty product code are available. This initial version includes only:

- `audit_version`
- `run_id` (from `RUN_ID` env, when set)
- `product.product_code`
- `engine.engine_version` (from `ENGINE_VERSION`/`ILLUSTRATION_ENGINE_VERSION` env, when set)
- `engine.runner_image` (from `RUNNER_IMAGE` env, when set)
- `environment` (from `ILLUSTRATION_ENVIRONMENT`/`ENVIRONMENT`, when set)
- `assumptions[*].assumption_set_id` (from the projection summary inputs)
- `dsl.file` (from the projection summary `formula_path`)
- `inputs.*` object keys (PAS export, actuarial tables, Term23 slice,
  rate curves, CRM, premium table)
- `outputs.projection_object`, `outputs.audit_object`,
  `outputs.input_snapshot_object`
- `created_at` / `generated_at`

All other fields remain empty or placeholder values (e.g. `filings` is an
empty list, `product_definition_id` is `null`) until FilingRecord and
ProductDefinition become first-class runtime objects.

In addition, the RunDetail API (`/api/run-detail`) now:

- Attempts to load the corresponding `AuditRecord` for a run using the
  `product_code` and `run_id` recorded in the projection summary.
- Exposes a small, metadata-only `audit_summary` block that includes:
  - `run_id`
  - `audit_record_object` (MinIO key)
  - `product_code`
  - `assumption_set_ids`
  - `dsl_file`
  - `engine_version`
  - `runner_image`
  - `created_at`
- Leaves `audit_summary` as `null` when no `AuditRecord` exists or when
  MinIO access fails, without failing the RunDetail API itself.

---

## 2. Mapping from Current Artefacts to the Canonical Model

This section summarizes how today’s data structures map into the audit model.

### 2.1 Projection JSON → AuditRecord

The projection JSON (written by `project-minio`) already contains:

- `inputs.product_code` → `AuditRecord.product.product_code`
- `inputs.assumption_set_id` → `AuditRecord.assumptions[*].assumption_set_id`
- `projection` arrays → _referenced indirectly_ via `projection_object` in
  `AuditRecord.outputs`.

`AuditRecord.run_id` can be:

- derived from the Job’s `RUN_ID` env var (when set), or
- a function of the projection object key (e.g. `run-<uid>`).

### 2.2 CRD Status → AuditRecord

`IllustrationProject.status` contributes:

- `projectionObject` → `AuditRecord.outputs.projection_object`
- `auditObject` → `AuditRecord.outputs.audit_object`
- `inputSnapshotObject` → `AuditRecord.outputs.input_snapshot_object`
- `assumptionSetId` → `AuditRecord.assumptions[*].assumption_set_id`
- `assumptionApproved` → `AuditRecord.assumptions[*].status`
- `engineVersion` → `AuditRecord.engine.engine_version`
- `runnerImage` → `AuditRecord.engine.runner_image`

These mappings can be documented in `docs/audit-model.md` without needing
code changes.

### 2.3 AssumptionSet Registry → AuditRecord

The AssumptionSet registry adds:

- description, status, and `is_current` flags for the assumption sets.

In the future, when AssumptionSets are extended with `source_filing_id` and
`source_doc_keys`, those fields will link `AuditRecord.assumptions` back to
FilingRecords.

### 2.4 FilingRecord & ProductDefinition → AuditRecord

Once FilingRecords and ProductDefinitions exist:

- `AuditRecord.filings[*].filing_id` will be drawn from the ProductDefinition
  or AssumptionSets (depending on configuration).
- `AuditRecord.product.product_definition_id` will allow a direct jump from
  a run to the canonical ProductDefinition.

Today, these links are **not implemented** and should be treated as future
work guided by this document.

---

## 3. Implemented vs. Planned – Summary

**Implemented today:**

- AssumptionSet registry (MinIO‑backed).
- Projection JSONs written by `project-minio`.
- Optional audit and input snapshot JSONs.
- CRD status fields pointing to MinIO objects and assumption IDs.
- RunDetail API + UI that aggregate much of this information for humans.

**Planned / not yet implemented:**

- `FilingRecord` objects stored under `filings/<product>/records/<filing_id>.json`.
- `ProductDefinition` as a single canonical product view.
- `AuditRecord` as either a persisted object or a first‑class logical view.
- Strong, explicit links from AssumptionSets and ProductDefinitions back to
  FilingRecords.

This document is the design target that future code changes in `actuarypoc`
and `illustration-operator` should converge toward.
