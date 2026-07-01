# ActuaryPOC Architecture

> **Purpose**
>
> This document describes the target architecture for supporting many life products (term, whole, UL, indexed UL, etc.) in a consistent way:
>
> * ingest filings / specs for **any** product
> * use AI + rules to build a **product model**
> * declare what’s **missing** for a filed‑rate‑quality illustration
> * detect **unsupported features** and emit feature requests
> * run a **projection** with clear trust levels and traceability

The goal is to avoid one‑off, Promise‑UL‑specific flows and instead have a single, extensible architecture that works across product lines.

---

## 1. High‑Level Flow

```text
Upload filings/specs
        ↓
Document ingestion + workspace
        ↓
LLM-driven extraction into product-line model
        ↓
Requirements classification (readiness)
        ↓
Capability assessment (engine vs product)
        ↓
Feature request emission (object store)
        ↓
Projection build (term / whole / UL engine)
        ↓
Workspace UI (identity, gaps, readiness, projection, traceability)
```

Key properties:

- **Product‑line first**: term, whole, UL, and others each have a dedicated product model and extractor.
- **Shared semantics**: requirements, capabilities, readiness, and feature requests use common types across lines.
- **AI assist, rule guardrails**: LLMs extract and summarize; rules enforce safety/consistency.

---

## 2. Domain Model

### 2.1 Base product model

All life products share a small, common core.

```python
@dataclass
class BaseLifeProductModel:
    product_code: str
    product_name: str | None
    carrier: str | None
    jurisdiction: str | None
    product_type: str  # e.g. "term", "whole", "ul", "indexed_ul"

    # Core coverage scope
    issue_age_min: int | None
    issue_age_max: int | None
    risk_classes: list[str]  # e.g. ["Preferred Non-Tobacco", "Standard Tobacco"]

    # High-level premium pattern and guarantees
    premium_pattern: str | None  # "level", "single", "flexible", ...
    premium_guarantee_description: str | None

    # Riders / options present (term riders, chronic illness, etc.)
    riders: list[str]

    # Raw evidence references (per-field evidence hangs off line-specific models)
    metadata_sources: list[EvidenceRef]
```

Where `EvidenceRef` is a small, generic reference into filings/specs:

```python
@dataclass
class EvidenceRef:
    document: str | None
    page: str | None
    snippet: str | None
    confidence: float | None
```

Every line‑specific model extends `BaseLifeProductModel`.

### 2.2 Term life model

```python
@dataclass
class TermLifeModel(BaseLifeProductModel):
    # Coverage structure
    term_period_years: int | None
    renewable: bool | None
    convertible: bool | None
    conversion_rules: str | None

    # Premium mechanics
    premium_rate_tables: list[RateTable]  # age/sex/smoker/term/face
    reentry_rules: str | None

    # Field-level evidence & status per important table/parameter
    field_evidence: dict[str, FieldEvidence]
```

### 2.3 Whole life model

```python
@dataclass
class WholeLifeModel(BaseLifeProductModel):
    participating: bool | None
    guarantee_basis: str | None  # e.g. "2001 CSO", "net level reserve"

    guaranteed_cash_value_table: TableWithStatus | None
    dividend_rules: str | None
    paid_up_options: str | None

    field_evidence: dict[str, FieldEvidence]
```

### 2.4 Universal life model

```python
@dataclass
class UniversalLifeModel(BaseLifeProductModel):
    # Death benefit / face mechanics
    death_benefit_options: list[str]  # e.g. ["Option A", "Option B"]

    # Crediting mechanics
    guaranteed_rate: float | None
    current_rate: float | None
    crediting_rules: str | None  # including banding, indices, etc.

    # Charges
    coi_basis: str | None  # e.g. "NAR", "face"
    coi_tables: list[TableWithStatus]
    policy_fees: list[FeeSchedule]
    premium_loads: list[FeeSchedule]

    # Surrender mechanics
    surrender_schedule: TableWithStatus | None
    mva_rules: str | None

    # Loans / withdrawals
    loan_rules: str | None
    withdrawal_rules: str | None

    field_evidence: dict[str, FieldEvidence]
```

### 2.5 Field evidence and status

All lines share a common notion of field‑level status and provenance.

```python
@dataclass
class FieldEvidence:
    id: str  # stable key, e.g. "ul_coi_table_main", "term_level_prem_20"
    status: str  # "extracted" | "inferred" | "placeholder" | "missing"
    value_summary: str | None  # short human-readable description
    sources: list[EvidenceRef]
    impact: str  # "high" | "medium" | "low"
```

`TableWithStatus` and `FeeSchedule` use `FieldEvidence` internally to track provenance.

---

## 3. Requirements & Readiness

### 3.1 Generic classification engine

We already have a product‑agnostic classification core in
`src/actuarypoc/domain/requirements_classification.py`:

- `EvidenceKind` – product document vs AI vs engine vs reviewer decision.
- `Applicability` – `confirmed_applicable | needs_review | confirmed_not_applicable`.
- `ImplementationState` – `implemented | partial | not_implemented | unknown`.
- `InputState` – `ready | placeholder | missing | not_required | unknown`.
- `RequirementClassification` – wraps all of the above plus an `impact` and `is_blocking_gap` flag.

```python
@dataclass
class RequirementClassification:
    requirement_id: str
    impact: Impact
    applicability: Applicability
    implementation_state: ImplementationState
    input_state: InputState
    is_blocking_gap: bool
```

This engine is deliberately **product‑agnostic**: it doesn’t know about Promise UL or P12TRF.

### 3.2 Requirement catalogs per product line

Each product line defines a small catalog of requirements, mapping to
fields in its product model.

Examples:

- **Cross‑line (all life products)**
  - `LIFE_DEATH_BENEFIT_DEFINITION`
  - `LIFE_ISSUE_AGE_AND_RISK_CLASSES`
  - `LIFE_PREMIUM_PATTERN_AND_GUARANTEES`

- **Term‑specific**
  - `TERM_LEVEL_PREMIUM_TABLE`
  - `TERM_CONVERSION_OPTIONS`
  - `TERM_RENEWAL_RULES`

- **Whole‑life‑specific**
  - `WL_GUARANTEED_CASH_VALUES`
  - `WL_DIVIDEND_FORMULA`
  - `WL_PAID_UP_OPTIONS`

- **UL‑specific**
  - `UL_COI_TABLE`
  - `UL_SURRENDER_SCHEDULE`
  - `UL_POLICY_FEES`
  - `UL_CREDITING_RULES`
  - `UL_LOAN_MECHANICS`

Each requirement definition knows:

- Which product‑model fields and `FieldEvidence` it depends on.
- How to convert those into `Evidence` objects for the classifier.

### 3.3 What "additional information is needed" means

For any product, after classification we can ask:

- **Blocking gaps** – `is_blocking_gap == True` and
  `applicability == confirmed_applicable`.
- For each such requirement, inspect `implementation_state` and
  `input_state` to see whether we lack:
  - behaviour in the engine, or
  - structured inputs/tables.

This directly answers:

> *“Declare what additional information is needed to fully generate an illustration projection.”*

The workspace’s “Missing information / Gaps” section is just a
presentation of these blocking requirements.

---

## 4. Capability Assessment & Feature Requests

### 4.1 Engine capability catalogs

For each engine (term, whole, UL), we define a catalogue of capabilities
it supports.

```python
@dataclass
class EngineCapability:
    capability_id: str  # e.g. "UL_CAP_COI_TABLE_AGE_GENDER"
    product_type: str   # "term" | "whole" | "ul" | ...
    description: str
    # Possible future: min/max dimensionality, supported bases, etc.
```

Example capabilities:

- Term:
  - `TERM_CAP_LEVEL_PREMIUM_RATE_TABLE`
  - `TERM_CAP_CONVERSION_SIMPLE`
- Whole Life:
  - `WL_CAP_GUARANTEED_CASH_VALUE_TABLE`
  - `WL_CAP_DIVIDEND_TABLE`
- UL:
  - `UL_CAP_COI_TABLE_AGE_GENDER_CLASS`
  - `UL_CAP_SURRENDER_FIXED_SCHEDULE`
  - `UL_CAP_LEVEL_POLICY_FEE`
  - `UL_CAP_INDEXED_CREDITING_SIMPLE`

### 4.2 Capability mapping

A line‑specific mapper compares the **product model** with the
**engine capabilities**:

```python
@dataclass
class CapabilityAssessmentItem:
    capability_id: str
    name: str
    status: str  # "supported" | "partial" | "unsupported"
    impact: str  # from linked requirements
    reason: str
    product_code: str
    source_requirement_ids: list[str]
    source_requirement_text: str | None
    source_document: str | None
    source_reference: str | None
```

For example, for a UL product with a complex indexed crediting rule but
an engine that only supports simple annual point‑to‑point, we’d produce
an `unsupported` or `partial` assessment.

### 4.3 Feature requests in object storage

For every `partial` / `unsupported` capability, we emit a feature
request JSON object to object storage (MinIO/S3):

```python
@dataclass
class FeatureRequest:
    product_code: str
    product_type: str
    capability_id: str
    title: str
    description: str
    impact: str
    status: str  # "proposed" | "approved" | ...
    source_requirement_ids: list[str]
    source_requirement_text: str | None
    source_document: str | None
    source_reference: str | None
    created_at: str
```

Suggested object key layout:

```text
feature-requests/{product_type}/{product_code}/{capability_id}.json
```

OpenClaw (or any other automation) can then:

- List all feature requests across products.
- Group by `capability_id` to see where engine work has the most impact.
- Create tickets, prioritize, and implement.

This directly supports:

> *“Declare if there are features in this product that are currently not supported and … create a feature request and store [it] in the object store.”*

---

## 5. Projection Engines & Trust Levels

### 5.1 Engines per product line, unified interface

We keep separate engines per line, but expose a single projection
interface.

```python
@dataclass
class ProjectionResult:
    product_code: str
    product_type: str
    trust_level: str  # "exploration_only" | "draft_illustration" | ...
    metrics: dict[str, Any]
    sample_rows: list[dict[str, Any]]
    notes: list[str]

@dataclass
class ProjectionNotPossible:
    reason: str
    blocking_requirements: list[RequirementClassification]
    unsupported_capabilities: list[CapabilityAssessmentItem]
```

Entry point:

```python
def build_projection(model: BaseLifeProductModel) -> ProjectionResult | ProjectionNotPossible:
    if isinstance(model, TermLifeModel):
        cfg = build_term_engine_config(model)
        return run_term_projection(cfg)
    elif isinstance(model, WholeLifeModel):
        cfg = build_whole_life_engine_config(model)
        return run_whole_life_projection(cfg)
    elif isinstance(model, UniversalLifeModel):
        cfg = build_ul_engine_config(model)
        return run_ul_projection(cfg)
    else:
        return ProjectionNotPossible("Unsupported product type")
```

### 5.2 Config builders check readiness & capabilities

Each `build_*_engine_config` uses:

- the **requirement classifications** for that product line, and
- the **capability assessment** for that engine,

to determine:

- whether we can safely produce an illustration at all, and
- what **trust level** to assign:

- `exploration_only` – missing or placeholder on high‑impact
  requirements or reliance on unsupported engine capabilities.
- `draft_illustration` – all high‑impact requirements implemented, but
  some medium‑impact ones still placeholder/missing.
- `review_ready` / `filed_rate_ready` – all high‑impact and
  medium‑impact confirmed requirements implemented + inputs ready, and
  no unresolved unsupported capabilities.

This satisfies:

> *“Generate an illustration projection based on the mechanisms detected.”*

The “mechanisms detected” are exactly the contents of the product
models and their `field_evidence` structures.

---

## 6. Workspace & UI Surfaces

The Product Understanding Workspace is a **read‑only view** built on top
of the canonical objects described above.

### 6.1 Snapshot payload shape (conceptual)

For any product (term, whole, UL, etc.), the workspace snapshot exposes:

- `product` – identity block (from `BaseLifeProductModel`).
- `productUnderstanding` – high‑level AI summary of identity and scope.
- `documentInventory` – documents in the workspace.
- `extractedFacts` – AI‑extracted facts (fact label, value, provenance).
- `mechanics` / `assumptions` – summarized from the product model.
- `readinessDashboard` – derived from requirement classifications.
- `complianceMatrix` – human‑oriented table over requirements.
- `requirementsClassification` – the canonical list of
  `RequirementClassification` objects.
- `capabilityAssessment` – list of `CapabilityAssessmentItem`s.
- `featureRequests` – optional, loaded from object store.
- `gaps` – blocking requirements presented as gap cards.
- `illustration` – projection result + sample rows + trust level.

### 6.2 Promise‑UL today vs target

Today, the workspace implementation is Promise‑UL‑first:

- UL runtime config is mostly Promise‑UL‑shaped placeholders.
- Requirements are coded around a small Promise‑UL list.
- Only UL‑style products with certain metadata routes succeed.

The architecture in this document generalizes that into:

- line‑specific models & extractors,
- shared requirement classification,
- shared capability assessment & feature requests,
- separate engines but a single projection interface,
- a product‑agnostic workspace surface.

---

## 7. Extensibility

### 7.1 Adding a new product line (e.g. Indexed UL)

1. Add a new model class `IndexedUniversalLifeModel` extending
   `UniversalLifeModel` or `BaseLifeProductModel`.
2. Implement an extractor that populates it from filings.
3. Define a requirement catalog for that line.
4. Add engine capabilities and a capability mapper.
5. Implement `build_indexed_ul_engine_config` and a projection runner.
6. Wire the workspace snapshot builder to recognise the new
   `product_type` and render the same sections.

### 7.2 Adding a new requirement

1. Add a requirement definition to the appropriate catalog.
2. Map it to the relevant product‑model fields.
3. Include its `FieldEvidence` in the evidence list.
4. Let the existing classifier compute applicability and gap status.
5. It will automatically appear in:
   - `requirementsClassification`,
   - the compliance matrix,
   - gaps (if `is_blocking_gap`),
   - and PMR/readiness.

### 7.3 Adding a new engine capability

1. Add an `EngineCapability` entry.
2. Update the line‑specific capability mapper to detect when the
   product needs that capability.
3. If unsupported, the mapper will produce an assessment item and the
   feature request emitter will write a JSON to object storage.

---

## 8. Implementation Status (2026‑06)

- The **generic requirement classifier** already exists and is wired
  into the Promise‑UL workspace path.
- The current UL runtime config and workspace builder are still mostly
  Promise‑UL‑specific and use placeholder assumptions for other
  products.
- Term and whole‑life models and engines are not yet wired into this
  unified architecture.

This document is the design target for evolving the codebase so that any
UL, term, whole, or other life product can be ingested and analysed
through the same architecture, with Promise‑UL treated as just one
instance rather than a special case.
