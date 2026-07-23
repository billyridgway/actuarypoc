# Actuary AI Product and Engineering Principles

> **Status:** Mandatory design and review rules  
> **Last updated:** 2026-07-22  
> **Applies to:** Product design, extraction, modeling, APIs, UI, projection engines, tests, automation, and agent-delivered changes

## 1. Product-Agnostic by Default

Shared code must not behave differently because of:

- Product code
- Carrier name
- Filing filename
- Document title
- Workspace ID
- Sample policy ID
- Demo fixture name

Product-specific behavior must be represented as:

- Source-derived data
- Product definitions
- Configuration
- Product-line requirement catalogs
- Capability mappings
- Explicitly scoped adapters or plugins

A scoped adapter must be visible, justified, and reviewed. It must not become a hidden exception in shared logic.

## 2. Product-Line Specific, Product-Code Agnostic

The system may have different models and engines for genuinely different product lines, such as term, whole life, and universal life.

It should not have permanent branches for individual demonstration products inside shared line behavior.

The preferred extension pattern is:

```text
shared semantics
    +
product-line model
    +
product-line requirements
    +
product-line capabilities
    +
product data/configuration
```

## 3. Evidence Before Assertion

A material product claim should have:

- A structured value
- A status
- A provenance kind
- Source references where available
- Confidence where meaningful
- Impact
- An explanation when unresolved

The system should prefer “unresolved” over an unsupported claim.

## 4. Honest State Semantics

These states must remain distinct:

- `extracted`
- `inferred`
- `configured`
- `reviewer_supplied`
- `placeholder`
- `missing`
- `unresolved`
- `unavailable`
- `not_required`
- `not_applicable`

A placeholder is not extracted evidence. A configured default is not source truth. An inference is not a quote. A missing item is not automatically a blocking gap.

## 5. Applicability Before Missingness

The system must determine whether a requirement applies before displaying it as missing.

A requirement should not become a gap solely because:

- A shared schema contains a field
- Another product uses the field
- A generic UI card expects it
- A previous demo required it

The system must be able to explain why the requirement applies to the current product.

## 6. AI Assists; Rules Govern

AI is appropriate for interpretation, extraction, mapping, summarization, and discovery.

Deterministic code must govern:

- Schema validation
- Status normalization
- Readiness classification
- Blocking-gap calculation
- Capability comparison
- Projection calculations
- Trust-level eligibility
- Persistence
- Review gates

An LLM explanation may accompany a rule-derived result. It may not replace the rule.

## 7. No Silent Fallbacks

Fallbacks must be:

- Explicit
- Labeled
- Traceable
- Included in trust calculations
- Visible to reviewers when material

A system must never show a fallback, fixture, default, or cached demonstration value as though it came from the uploaded documents.

## 8. Input Changes Must Produce Explainable Output Changes

For AI-assisted or document-derived behavior, validation must include materially different inputs.

The system should demonstrate:

- Different products produce appropriately different models.
- Changing a source fact changes the relevant downstream result.
- Unrelated outputs remain stable.
- Cached results do not conceal stale analysis.
- Cross-product contamination does not occur.

## 9. Deterministic Projection Core

Projection calculations should be deterministic, testable, and reproducible from:

- Canonical product model
- Approved configuration
- Policy inputs
- Versioned engine code
- Versioned assumption sets

AI may help build or explain inputs. It should not perform the authoritative numeric projection.

## 10. Canonical Domain Objects Before UI Payloads

The source of truth should be domain objects and persisted records.

The UI should consume derived views. It should not create independent business logic that:

- Redefines requirement states
- Invents missing fields
- Changes provenance
- Assigns trust
- Adds product-specific exceptions

## 11. Reviewer Signal Over UI Volume

The UI should prioritize:

- Material decisions
- Exceptions
- Blocking gaps
- Unsupported capabilities
- Evidence
- Provenance
- Trust
- Required actions

Repeated facts, internal implementation detail, and non-actionable warnings should not dominate the page.

Each section should answer a distinct reviewer question.

## 12. Unsupported Is Better Than Incorrect

When the engine cannot represent a mechanic, the system should:

1. Identify the unsupported capability.
2. Explain its impact.
3. Prevent or downgrade the projection as appropriate.
4. Emit a feature request if useful.
5. Avoid approximating silently.

## 13. Trust Must Be Earned

Trust levels must follow evidence and validation.

A higher trust level requires stronger proof, not more confident language.

At minimum, trust assignment should consider:

- Applicable requirements
- Input readiness
- Engine support
- Evidence quality
- Placeholder usage
- Reviewer decisions
- Test coverage
- Running-system validation

## 14. Human Review Remains Authoritative

The system assists the actuary. It does not replace actuarial judgment.

Human decisions should be:

- Explicit
- Attributed
- Timestamped
- Durable
- Reversible where appropriate
- Included in downstream trust and readiness

## 15. Small, Bounded Changes

Agent-delivered work must begin with a task contract.

A task should define:

- Goal
- Scope
- Exclusions
- Constraints
- Acceptance criteria
- Validation plan

Agents must not silently expand a request into a broad redesign.

## 16. Independent Review

The implementer may not approve its own work.

Independent review should examine:

- Contract compliance
- Architecture
- Product agnosticism
- Provenance
- AI integrity
- Tests
- Scope
- Failure handling
- UI clarity where relevant

## 17. Live Behavior Is the Final Product

Passing unit tests is necessary but not always sufficient.

For user-visible or deployed changes, validation should exercise:

- The running API
- The live UI
- Representative inputs
- Failure paths
- Deployment identity
- Health checks
- Relevant persistence

## 18. No Unsupported Completion Claims

Do not say “complete,” “working,” “verified,” or “done” when:

- Required tests were skipped
- Live validation was required but not run
- A dependency was unavailable
- Evidence is incomplete
- The change exists only locally
- The deployed version was not identified
- Material limitations remain undisclosed

Use precise language such as:

- Implemented locally
- Unit tests passed
- Deployment not performed
- Live validation blocked
- Review rejected
- Partially verified

## 19. Durable Learning

When Billy corrects a recurring behavior, update the appropriate durable source:

- Product principle
- Architecture decision
- Project state
- Definition of done
- Agent instruction
- Reusable skill
- Test

The same correction should not depend on chat memory alone.

## 20. Security and Least Privilege

Agents should receive only the tools and credentials required for their role.

- The architect plans and delegates.
- The builder edits only its worktree.
- The reviewer is read-only.
- Deployment authority is separate.
- Secrets should not be readable by general agent tools.
- Production changes require explicit approval.
