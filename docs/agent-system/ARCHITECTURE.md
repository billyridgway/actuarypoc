# Actuary AI Architecture

> **Status:** Target architecture with explicit current-state notes  
> **Audience:** Architects, implementers, reviewers, validators, and product owners  
> **Last updated:** 2026-07-22  
> **Source lineage:** Consolidated from the prior `ActuaryPOC Architecture` design  
> **Related documents:** `PRODUCT_VISION.md`, `PRODUCT_PRINCIPLES.md`, `PROJECT_STATE.md`

## 1. Purpose

This document describes the target architecture for supporting multiple life insurance product lines—such as term, whole life, universal life, and indexed universal life—through a consistent workflow.

The architecture must support:

- Ingesting filings and specifications for any supported product
- Using AI and deterministic rules to build a structured product model
- Identifying what additional information is required
- Distinguishing missing inputs from unsupported engine behavior
- Emitting feature requests for unsupported mechanics
- Producing projections with explicit trust levels
- Preserving evidence, provenance, and review history
- Avoiding one-off behavior for demonstration products

## 2. Architectural Goals

1. **Product-line extensibility**  
   Add product lines through models, extractors, requirement catalogs, capability mappings, and projection adapters—not product-code branches in shared code.

2. **Shared semantics**  
   All product lines use common concepts for evidence, applicability, readiness, implementation state, capability support, trust, and review.

3. **Evidence-first behavior**  
   Material facts must retain source references and provenance.

4. **AI-assisted, rule-governed processing**  
   AI interprets source language. Deterministic rules enforce state transitions, safety constraints, and trust-level eligibility.

5. **Honest incompleteness**  
   The system must represent unresolved, unavailable, placeholder, optional, and not-applicable states explicitly.

6. **Observable validation**  
   Architecture correctness must be demonstrated in running behavior, not inferred from code structure alone.

## 3. High-Level Flow

```text
Upload filings and specifications
              ↓
Document ingestion and workspace inventory
              ↓
Document parsing and evidence indexing
              ↓
AI-assisted extraction into a product-line model
              ↓
Requirement applicability and readiness classification
              ↓
Engine capability assessment
              ↓
Unsupported-feature request emission
              ↓
Projection configuration build
              ↓
Projection execution or ProjectionNotPossible
              ↓
Workspace UI, evidence review, decision, and audit trail
```

## 4. Logical Layers

### 4.1 Document Layer

Responsibilities:

- Store uploaded source documents
- Track workspace membership and document identity
- Extract text and page references
- Preserve document-level metadata
- Expose evidence locations to downstream processing

The document layer must not decide actuarial meaning by itself.

### 4.2 Product Understanding Layer

Responsibilities:

- Identify product line and product identity
- Extract structured product facts and mechanics
- Attach field-level status and evidence
- Separate direct extraction from inference and configuration
- Produce a canonical product model

The output should be a product-line model, not a UI-specific payload.

### 4.3 Requirement Classification Layer

Responsibilities:

- Determine whether a requirement applies
- Determine whether engine behavior exists
- Determine whether required input data is ready
- Determine whether a gap is blocking
- Provide consistent status semantics across product lines

This layer should be product-agnostic. Product-line catalogs supply the requirements and field mappings.

### 4.4 Capability Assessment Layer

Responsibilities:

- Compare detected product mechanics with supported engine capabilities
- Classify support as supported, partial, unsupported, or unknown
- Explain why the classification was assigned
- Link capability findings to product requirements and evidence

### 4.5 Projection Layer

Responsibilities:

- Convert a ready product model into engine-specific configuration
- Refuse unsafe projections when blocking requirements exist
- Run deterministic projection logic
- Assign a trust level from verified readiness and support state
- Return projection results or an explicit failure object

### 4.6 Workspace and Review Layer

Responsibilities:

- Present identity, evidence, mechanics, readiness, capabilities, gaps, and projections
- Avoid duplicating the same fact without adding reviewer value
- Support reviewer decisions
- Preserve review comments and exclusions
- Expose traceability from UI state back to canonical objects

## 5. Canonical Domain Model

### 5.1 Base Product Model

All life products share a common core.

```python
@dataclass
class BaseLifeProductModel:
    product_code: str
    product_name: str | None
    carrier: str | None
    jurisdiction: str | None
    product_type: str

    issue_age_min: int | None
    issue_age_max: int | None
    risk_classes: list[str]

    premium_pattern: str | None
    premium_guarantee_description: str | None

    riders: list[str]
    metadata_sources: list["EvidenceRef"]
```

### 5.2 Evidence Reference

```python
@dataclass
class EvidenceRef:
    document: str | None
    page: str | None
    snippet: str | None
    confidence: float | None
```

Evidence references identify where a claim came from. They do not by themselves prove the claim is complete or correct.

### 5.3 Field Evidence

```python
@dataclass
class FieldEvidence:
    id: str
    status: str
    value_summary: str | None
    sources: list[EvidenceRef]
    impact: str
    provenance_kind: str | None
```

Recommended status values:

- `extracted`
- `inferred`
- `configured`
- `reviewer_supplied`
- `placeholder`
- `missing`
- `unresolved`
- `not_applicable`

Recommended provenance values:

- `product_document`
- `ai_extraction`
- `deterministic_rule`
- `engine_configuration`
- `reviewer_decision`
- `fixture`
- `fallback`
- `unresolved`

### 5.4 Product-Line Models

#### Term Life

```python
@dataclass
class TermLifeModel(BaseLifeProductModel):
    term_period_years: int | None
    renewable: bool | None
    convertible: bool | None
    conversion_rules: str | None
    premium_rate_tables: list["RateTable"]
    reentry_rules: str | None
    field_evidence: dict[str, FieldEvidence]
```

#### Whole Life

```python
@dataclass
class WholeLifeModel(BaseLifeProductModel):
    participating: bool | None
    guarantee_basis: str | None
    guaranteed_cash_value_table: "TableWithStatus" | None
    dividend_rules: str | None
    paid_up_options: str | None
    field_evidence: dict[str, FieldEvidence]
```

#### Universal Life

```python
@dataclass
class UniversalLifeModel(BaseLifeProductModel):
    death_benefit_options: list[str]

    guaranteed_rate: float | None
    current_rate: float | None
    crediting_rules: str | None

    coi_basis: str | None
    coi_tables: list["TableWithStatus"]
    policy_fees: list["FeeSchedule"]
    premium_loads: list["FeeSchedule"]

    surrender_schedule: "TableWithStatus" | None
    mva_rules: str | None

    loan_rules: str | None
    withdrawal_rules: str | None

    field_evidence: dict[str, FieldEvidence]
```

Indexed UL and future lines may extend an existing line model where the inheritance is semantically valid, or define a new line model when mechanics materially differ.

## 6. Requirements and Readiness

### 6.1 Shared Classification Types

The architecture uses common classification semantics:

```python
@dataclass
class RequirementClassification:
    requirement_id: str
    impact: str
    applicability: str
    implementation_state: str
    input_state: str
    is_blocking_gap: bool
```

Recommended applicability values:

- `confirmed_applicable`
- `needs_review`
- `confirmed_not_applicable`

Recommended implementation-state values:

- `implemented`
- `partial`
- `not_implemented`
- `unknown`

Recommended input-state values:

- `ready`
- `placeholder`
- `missing`
- `not_required`
- `unknown`

### 6.2 Product-Line Requirement Catalogs

Each product line defines requirements that map to fields and evidence in its canonical model.

Examples:

**Cross-line**

- `LIFE_DEATH_BENEFIT_DEFINITION`
- `LIFE_ISSUE_AGE_AND_RISK_CLASSES`
- `LIFE_PREMIUM_PATTERN_AND_GUARANTEES`

**Term**

- `TERM_LEVEL_PREMIUM_TABLE`
- `TERM_CONVERSION_OPTIONS`
- `TERM_RENEWAL_RULES`

**Whole Life**

- `WL_GUARANTEED_CASH_VALUES`
- `WL_DIVIDEND_FORMULA`
- `WL_PAID_UP_OPTIONS`

**Universal Life**

- `UL_COI_TABLE`
- `UL_SURRENDER_SCHEDULE`
- `UL_POLICY_FEES`
- `UL_CREDITING_RULES`
- `UL_LOAN_MECHANICS`

A catalog entry must define:

- Stable requirement ID
- Human-readable description
- Product-model dependencies
- Evidence mapping
- Default impact
- Applicability logic
- Blocking-gap rules

### 6.3 Meaning of “Additional Information Needed”

A missing-information item should appear only when:

1. The requirement is confirmed or reasonably believed to be applicable.
2. The required input is not ready.
3. The missing input affects the requested level of projection or review.
4. The system can explain why the information is required.

The UI must not show a generic missing field merely because a shared schema contains it.

## 7. Engine Capabilities

### 7.1 Capability Catalog

```python
@dataclass
class EngineCapability:
    capability_id: str
    product_type: str
    description: str
```

Example capabilities:

- `TERM_CAP_LEVEL_PREMIUM_RATE_TABLE`
- `TERM_CAP_CONVERSION_SIMPLE`
- `WL_CAP_GUARANTEED_CASH_VALUE_TABLE`
- `WL_CAP_DIVIDEND_TABLE`
- `UL_CAP_COI_TABLE_AGE_GENDER_CLASS`
- `UL_CAP_SURRENDER_FIXED_SCHEDULE`
- `UL_CAP_LEVEL_POLICY_FEE`
- `UL_CAP_INDEXED_CREDITING_SIMPLE`

### 7.2 Capability Assessment

```python
@dataclass
class CapabilityAssessmentItem:
    capability_id: str
    name: str
    status: str
    impact: str
    reason: str
    product_code: str
    source_requirement_ids: list[str]
    source_requirement_text: str | None
    source_document: str | None
    source_reference: str | None
```

Recommended status values:

- `supported`
- `partial`
- `unsupported`
- `unknown`

Capability assessment must be based on the product model and engine catalog, not a product-code lookup.

## 8. Feature Requests

For partial or unsupported capabilities, the system may emit a feature request:

```python
@dataclass
class FeatureRequest:
    product_code: str
    product_type: str
    capability_id: str
    title: str
    description: str
    impact: str
    status: str
    source_requirement_ids: list[str]
    source_requirement_text: str | None
    source_document: str | None
    source_reference: str | None
    created_at: str
```

Suggested object key:

```text
feature-requests/{product_type}/{product_code}/{capability_id}.json
```

Feature requests are proposals, not automatic implementation approvals.

## 9. Projection Interface and Trust

### 9.1 Unified Result Types

```python
@dataclass
class ProjectionResult:
    product_code: str
    product_type: str
    trust_level: str
    metrics: dict[str, Any]
    sample_rows: list[dict[str, Any]]
    notes: list[str]

@dataclass
class ProjectionNotPossible:
    reason: str
    blocking_requirements: list[RequirementClassification]
    unsupported_capabilities: list[CapabilityAssessmentItem]
```

### 9.2 Dispatch

```python
def build_projection(
    model: BaseLifeProductModel
) -> ProjectionResult | ProjectionNotPossible:
    if isinstance(model, TermLifeModel):
        return run_term_projection(build_term_engine_config(model))
    if isinstance(model, WholeLifeModel):
        return run_whole_life_projection(build_whole_life_engine_config(model))
    if isinstance(model, UniversalLifeModel):
        return run_ul_projection(build_ul_engine_config(model))
    return ProjectionNotPossible(
        reason="Unsupported product type",
        blocking_requirements=[],
        unsupported_capabilities=[],
    )
```

### 9.3 Trust Levels

Suggested trust levels:

- `exploration_only`
- `draft_illustration`
- `review_ready`
- `filed_rate_ready`

Trust must be rule-derived from:

- Requirement applicability
- Input readiness
- Engine implementation state
- Capability support
- Evidence quality
- Reviewer decisions
- Validation evidence

An LLM may explain a trust level. It may not assign one independently.

## 10. Workspace Payload

The workspace may expose:

- `product`
- `productUnderstanding`
- `documentInventory`
- `extractedFacts`
- `mechanics`
- `assumptions`
- `readinessDashboard`
- `requirementsClassification`
- `complianceMatrix`
- `capabilityAssessment`
- `featureRequests`
- `gaps`
- `illustration`
- `reviewDecision`

These are views over canonical domain objects. UI payloads must not become an alternative source of truth.

## 11. AI and Deterministic Boundaries

### AI responsibilities

- Interpret document language
- Identify likely product type
- Extract candidate facts and mechanics
- Map text to canonical concepts
- Summarize evidence
- Suggest applicability for review
- Identify novel or unsupported mechanics

### Deterministic responsibilities

- Validate schema
- Normalize status values
- Enforce provenance requirements
- Calculate readiness
- Determine blocking gaps
- Compare capabilities
- Build engine configuration
- Run projections
- Assign eligible trust levels
- Persist reviewer decisions
- Enforce deployment and review gates

## 12. Product-Agnostic Extension Pattern

To add a product line:

1. Define or extend a canonical model.
2. Implement extraction into that model.
3. Define the requirement catalog.
4. Define capability needs and mappings.
5. Implement the engine adapter or projection engine.
6. Add representative fixtures.
7. Add cross-product contamination tests.
8. Render through shared workspace sections.
9. Validate with a materially different product.

To add a product within an existing line:

1. Add source documents and product definition/configuration as needed.
2. Do not add a shared-code branch for the product code.
3. Add fixtures and expected evidence.
4. Validate requirement applicability and capability assessment.
5. Confirm the product does not alter another product’s output.

## 13. Agent Delivery Architecture

The engineering-agent workflow is:

```text
Billy
  ↓
Actuary Architect
  ├── task contract
  ├── Actuary Builder
  │     └── implementation report + diff + tests
  └── Actuary Auditor
        └── independent disposition and findings
```

The master agent owns scope and architecture. The implementer owns bounded changes. The reviewer is independent and read-only. Deployment remains separately approved.

## 14. Current-State Note

The prior architecture document reported that:

- A generic requirement classifier existed and was wired into the Promise UL workspace path.
- The current UL runtime configuration and workspace builder remained substantially Promise-UL-shaped.
- Placeholder assumptions were used in some paths.
- Term and whole-life models and engines were not yet wired into the unified architecture.

These statements must be reverified against the repository and live deployment before being treated as current. `PROJECT_STATE.md` is the place to record the latest verified state.
