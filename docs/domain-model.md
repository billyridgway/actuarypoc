# Domain Model – Insurance Illustration Platform

> Status: **Design document.** This describes canonical business entities and
> their relationships for the platform. Some entities already exist in code
> (e.g. `IllustrationProject`, AssumptionSets), others are conceptual or
> planned (e.g. `ProductDefinition` as a first-class resource).

The goal of this model is to give us a stable mental map of **what** the
platform manages – carriers, filings, products, assumptions, illustration
requests, runs, and audits – and how those concepts map to storage and
runtime representations (Kubernetes, MinIO, databases, derived views).

The core entities considered here are:

- Carrier
- FilingRecord
- ProductDefinition
- AssumptionSet
- IllustrationProject
- IllustrationRun
- AuditRecord

---

## 1. Carrier

### Purpose

Represents a legal entity (insurance company) that owns products and files
SERFF submissions. In a multi‑carrier platform, Carrier would be important
for tenancy and branding. In the current POC, the carrier is implicit
("Pacific Life" style references sprinkled in docs) rather than modeled.

### Ownership

- **Business owner:** platform/business operations; not product‑specific.
- **Technical owner:** would likely live at the platform layer, outside of
  `actuarypoc` and `illustration-operator`.

### Lifecycle

- Created when a new carrier is onboarded.
- Updated rarely (name changes, mergers).
- Referenced by:
  - FilingRecords
  - ProductDefinitions
  - potentially runtime tenancy config.

### Identifiers

- `carrier_id` (stable platform ID, e.g. `pacific-life`, `carrier-123`).
- Optional: legal entity IDs, NAIC number, etc.

### Storage / Representation

- **Eventually:**
  - A database record in a central platform DB.
  - Cached or referenced in configuration for per‑cluster deployments.
- **Not needed as a Kubernetes resource for now.**
  - Carrier rarely changes and is more of a config/tenancy concern.
- **MinIO:** may appear as a top-level namespace/prefix if multi‑carrier
  support is added (e.g. `carrier/<carrier_id>/filings/...`).

### Relationships

- **Carrier 1–N FilingRecord** – a carrier files many filings.
- **Carrier 1–N ProductDefinition** – carrier offers many products.


---

## 2. FilingRecord (Primary SERFF-Derived Artefact)

### Purpose

FilingRecord is the normalized representation of a regulator filing:

- connects SERFF tracking details to concrete MinIO documents
- summarizes which documents are important (memos, rate tables, SOV, etc.)
- provides the provenance backbone for ProductDefinitions and AssumptionSets.

It is **the primary artefact derived from SERFF**, not AssumptionSets.

### Ownership

- **Business:** actuarial + regulatory filings team.
- **Technical:** ActuaryPOC backend (ingestion + classification pipeline).

### Lifecycle

- Created once per SERFF filing (or filing amendment).
- Updated if classification or metadata improves (e.g. better doc triage),
  but versioned via `record_version` or new `filing_id` when materially
  changed.
- Archived when superseded by later filings; historical records must remain
  for audit.

### Identifiers

- `filing_id` – platform‑level ID (could embed SERFF tracking ID and date).
- `serff_tracking_id` – optional, when available.
- `(carrier_id, product_code)` – connect to Carrier + product.

### Storage / Representation

- **Primary storage:** MinIO object

  ```text
  filings/<product_code>/records/<filing_id>.json
  ```

- **Derived views:**
  - DB index or search service could index FilingRecords for querying.

- **Kubernetes:** **not** needed as a CRD initially; filings are
  relatively static metadata and do not require reconciliation.

### Relationships

- **FilingRecord 1–N ProductDefinition** (over time):
  - A single filing might define or amend multiple products and riders.
- **FilingRecord 1–N AssumptionSet**:
  - Many AssumptionSets may be extracted from one filing (e.g. base
    assumptions vs. variations).
- Referenced by:
  - ProductDefinition (`filing_refs` list).
  - AssumptionSets (`source_filing_id`).
  - AuditRecord (`filings` section).


---

## 3. ProductDefinition (Canonical Product View)

### Purpose

ProductDefinition is the canonical description of an insurance product as the
platform understands it. It answers: “What is this product?”

It aggregates:

- identification (code, names, forms, jurisdictions)
- actuarial configuration (DSL, assumptions, premium tables)
- operational config (allowed horizons, modes, PAS integration hints)
- regulatory provenance (which Filings it comes from).

### Ownership

- **Business:** product management + actuarial pricing.
- **Technical:** shared between ActuaryPOC (DSL, assumptions) and the
  operator (product registry for CRD wiring).

### Lifecycle

- Created when a new product is introduced.
- Updated when:
  - new filings modify assumptions or forms
  - new riders or underwriting classes are added
  - technical changes occur (e.g. new DSL file versions).
- Versioned – ProductDefinition itself should carry a `product_definition_id`
  and `version` so we can tell which version governed a historical run.

### Identifiers

- `product_definition_id` – stable ID (e.g. `P12TRF-def-v1`).
- `product_code` – e.g. `P12TRF` (may span multiple definitions over time).
- `(carrier_id, product_code, version)` – full composite identity in a
  multi‑carrier platform.

### Storage / Representation

**Option A – MinIO + code (initial)**

- Store ProductDefinition JSON in MinIO:

  ```text
  products/<product_code>/definitions/<product_definition_id>.json
  ```

- Keep DSL files as now (`src/actuarypoc/dsl/...`), referenced by path.
- Keep the operator product registry (`config/products.yaml`) either:
  - generated from ProductDefinitions, or
  - treated as a low‑level runtime view.

**Option B – First-class Kubernetes Resource (future)**

- Define a `ProductDefinition` CRD:

  ```yaml
  apiVersion: products.illustrations.poc/v1alpha1
  kind: ProductDefinition
  metadata:
    name: p12trf-def-v1
  spec:
    productCode: P12TRF
    dslFile: p12trf_term.yaml
    premiumTables:
      - kind: level_term
        object: premium_tables/P12TRF/P12TRF-2020-01/level_term.csv
    assumptionSetIds:
      - P12TRF-2020-01-assumptions-v1
    filingRefs:
      - filingId: P12TRF-2020-01
  ```

- Pros:
  - Watchable, declarative API; UIs and other controllers can observe
    product changes natively.
  - Well‑aligned with the existing operator pattern.
- Cons:
  - Raises the bar for multi‑cluster / multi‑carrier setups.
  - May mix long‑lived domain data with cluster‑local operational config.

**Recommendation:**

- Short term: treat ProductDefinition as a **MinIO JSON + code‑level
  concept**, and only later promote it to a CRD if the complexity justifies
  it.
- If promoted:
  - keep the YAML spec minimal and continue to store heavy artefacts
    (premium tables, filings) in MinIO.

### Relationships

- **ProductDefinition 1–N AssumptionSet** – many assumption sets per product
  (e.g. base, variations, vintages).
- **ProductDefinition 1–N FilingRecord** via `filing_refs` – but over time,
  also many‑to‑many (a filing can affect multiple products and vice versa).
- **ProductDefinition 1–N IllustrationProject** – multiple illustration
  requests per product.
- **ProductDefinition 1–N IllustrationRun** – runs use a specific product
  definition version.


### Example: P12TRF ProductDefinition (POC)

As a concrete example, the repo includes a **POC-only** ProductDefinition
JSON for the P12TRF term product at:

- `examples/product-definitions/p12trf-product-definition.json`

This file:

- Follows the logical shape described above (`product_definition_version`,
  `product_definition_id`, `product_code`, `dsl`, `premium_tables`,
  `assumption_sets`, `filing_refs`, `illustration_config`).
- Uses **placeholder** or **approximate** values for fields we do not yet
  have from real SERFF filings (carrier ID, form numbers, jurisdictions,
  filing IDs, premium table locations).
- Points at the current DSL file
  (`src/actuarypoc/dsl/examples/p12trf_term.yaml`) and the synthetic premium
  table (`p12trf_premiums.synthetic.csv`) as POC-only wiring.

It is intended as a reference shape for future, more accurate
ProductDefinitions, not as a source of production configuration.


---

## 4. AssumptionSet (Component of ProductDefinition)

### Purpose

Captures a coherent set of actuarial assumptions for a product (or product
variant): mortality, lapse, expenses, risk class mapping, etc.

In the POC, AssumptionSets already drive certain projection behaviors (e.g.
term risk class mapping for P12TRF).

### Ownership

- **Business:** actuarial pricing + valuation.
- **Technical:** ActuaryPOC backend (assumptions registry and extraction).

### Lifecycle

- Created by:
  - direct authoring, or
  - extraction from FilingRecords using LLM and human review.
- Approved by a human and marked as `current` for a product.
- Superseded when a later assumption set (possibly tied to a new filing) is
  approved.

### Identifiers

- `assumption_set_id` – unique ID (e.g.
  `P12TRF-2020-01-assumptions-v1`).
- `product_code` – product this set applies to.

### Storage / Representation

- **Primary:** MinIO‑backed registry (JSON)
  - Implementation already exists.
- **Database index (optional):**
  - For search / reporting.
- **Not a Kubernetes resource:**
  - AssumptionSets change on a slower cadence and are best treated as data,
    not cluster configuration.

### Relationships

- **AssumptionSet N–1 ProductDefinition** – many assumption sets link to one
  product definition version (or product code), though we may allow sets that
  span products in rare cases.
- **AssumptionSet N–1 FilingRecord** – assumption sets derived from a filing
  should reference that FilingRecord.
- Used by:
  - IllustrationProject/operator wiring (which `assumption_set_id` to use).
  - IllustrationRun/AuditRecord (what was actually used for a run).


---

## 5. IllustrationProject (Kubernetes CRD)

### Purpose

Represents a **request to run** an illustration. It captures a desired
scenario:

- product to illustrate
- horizon
- PAS input source
- run policy hints.

### Ownership

- **Business:** front‑end / workflow components that create projects.
- **Technical:** `illustration-operator` repo (CRD definition and controller).

### Lifecycle

- Created per run or per project (depending on usage pattern).
- Reconciled by the operator into one or more Jobs.
- Status updated as runs succeed or fail.
- May be retained for history or cleaned up after use.

### Identifiers

- `metadata.name` / namespace pair – Kubernetes identity.
- Logical fields in `spec` – `productId`, `horizonYears`, etc.

### Storage / Representation

- **Kubernetes CRD (implemented):**
  - `kind: IllustrationProject` in API group `illustrations.poc/v1alpha1`.
- **Not stored in MinIO or DB directly**; instead, it points into MinIO via
  status fields.

### Relationships

- **IllustrationProject N–1 ProductDefinition** – each project targets one
  product, but may not pinpoint a specific version unless versioning is added
  to the spec.
- **IllustrationProject 1–N IllustrationRun** – multiple runs per project
  (retries, different input sets) are possible.
- CRD status references:
  - `projectionObject`, `auditObject`, `inputSnapshotObject` (outputs).
  - `assumptionSetId` (assumptions).


---

## 6. IllustrationRun

### Purpose

Represents a **single execution** of an illustration request. Unlike an
IllustrationProject (which describes intent and desired state), an
IllustrationRun captures what actually happened at a point in time.

In the current POC, IllustrationRuns are implicit:

- each projection JSON + audit snapshot + CRD status update effectively
  describes a run.
- `record_illustration_run` in `postgres_client.py` stores some metadata.

### Ownership

- **Business:** anyone reviewing past runs (ops, actuaries, product owners).
- **Technical:** shared between ActuaryPOC (projection engine, DB writes) and
  operator (Job lifecycle and status mapping).

### Lifecycle

- Created when a projection Job is launched.
- Moves through phases (`Pending`, `Running`, `Succeeded`/`Failed`).
- Immutable after completion (for audit purposes).

### Identifiers

- `run_id` – stable ID, may map to:
  - Job UID
  - CRD UID
  - or a separate UUID.
- `project_name` – name of the `IllustrationProject`.

### Storage / Representation

- **Today:**
  - Projection JSON in MinIO.
  - Optional audit/input snapshot JSON in MinIO.
  - Optional row in Postgres (`illustration_runs` table).
  - CRD status fields pointing to these objects.

- **Future:**
  - Could be formalized as:
    - a DB row keyed by `run_id`, and/or
    - a first‑class object in MinIO.

- **Not a Kubernetes resource** – runs are ephemeral/append‑only and better
  suited to data stores than the control plane.

### Relationships

- **IllustrationRun N–1 IllustrationProject** – many runs per project.
- **IllustrationRun N–1 ProductDefinition** – each run is tied to one
  product definition version.
- **IllustrationRun 1–1 AuditRecord** – each run should have exactly one
  canonical AuditRecord describing it.


---

## 7. AuditRecord (Run-Level Canonical Artefact)

### Purpose

Provides a **single, authoritative view** of how an IllustrationRun was
produced:

- which ProductDefinition and AssumptionSets were used
- which FilingRecords those were based on
- which inputs (PAS, tables, premiums) were read from MinIO
- which engine/image version created the output
- where the outputs live in MinIO.

### Ownership

- **Business:** audit, compliance, and actuaries performing back‑testing.
- **Technical:** shared between ActuaryPOC (builder) and potentially
  operator (linking runs to CRDs).

### Lifecycle

- Created when a run completes successfully (or with failure state when
  appropriate).
- Immutable after creation.
- Queryable via APIs and UI.

### Identifiers

- `audit_version` – schema version.
- `run_id` – ties directly to the IllustrationRun.
- `(product_code, run_id)` – convenient namespacing in MinIO.

### Storage / Representation

- **Design target:**
  - Materialized as JSON in MinIO:

    ```text
    audit/<product_code>/<run_id>/audit_record.json
    ```

  - Potentially indexed in a DB for fast querying.

- **Today:**
  - Not materialized as a single object; instead, view must be assembled from
    projection JSON, audit snapshots, CRD status, and registry lookups.

- **Kubernetes:**
  - Not a good fit for a CRD – too many records, append‑only, data‑oriented.

### Relationships

- **AuditRecord 1–1 IllustrationRun** – each run has one record.
- **AuditRecord N–1 ProductDefinition** – run references the specific product
  definition used.
- **AuditRecord N–1 FilingRecord** – may reference multiple filings (e.g. for
  cross‑product assumptions), but typically one.
- **AuditRecord N–1 AssumptionSet** – references the assumption sets that
  were active for the run.


---

## 8. Summary of Resource / Storage Choices

- **Carrier**
  - DB record (platform‑level), optional MinIO prefixes per carrier.
  - Not a K8s resource.

- **FilingRecord**
  - MinIO JSON (`filings/.../records/...`), possibly indexed in DB.
  - Not a K8s resource.

- **ProductDefinition**
  - Short term: MinIO JSON (`products/...`), plus code/DSL/operator config.
  - Long term: **may** become a K8s CRD if we benefit from a declarative,
    watchable API for products.

- **AssumptionSet**
  - MinIO‑backed registry.
  - Optional DB index.
  - Not a K8s resource.

- **IllustrationProject**
  - K8s CRD (implemented) as the run request interface.

- **IllustrationRun**
  - Projection+audit JSON in MinIO, optional DB row.
  - Not a K8s resource.

- **AuditRecord**
  - Design target: MinIO JSON (+ DB index), possibly also reconstructable on
    the fly.
  - Not a K8s resource.

This domain model is the conceptual backbone for future work: any new
features, workflows, or storage choices should be evaluated against this map
for consistency and auditability.
