# Actuary AI Product Vision

> **Status:** Authoritative product-direction document  
> **Audience:** Product owner, actuaries, architects, implementers, reviewers, and validation agents  
> **Last updated:** 2026-07-22  
> **Related documents:** `ARCHITECTURE.md`, `PRODUCT_PRINCIPLES.md`, `PROJECT_STATE.md`, `DEFINITION_OF_DONE.md`

## 1. Vision

Actuary AI helps an actuary understand whether an insurance product has been modeled correctly from its filings and supporting specifications.

The product should ingest the available source documents, build a structured understanding of the insurance product, identify what is known and unknown, assess whether the projection engine supports the detected mechanics, and produce a traceable projection only at the level of trust justified by the evidence.

The long-term goal is a product-agnostic system that can support many life insurance products without embedding one-off logic for a single product code, carrier, filing, filename, or demonstration case.

## 2. Problem

Creating or reviewing an insurance illustration model requires an actuary to reconcile information scattered across filings, actuarial memoranda, rate tables, specifications, and implementation artifacts.

The difficult questions are not limited to “can the system calculate a projection?” They include:

- What product mechanics were detected?
- Which source supports each important fact?
- Which assumptions were extracted, inferred, configured, or supplied as placeholders?
- What information is still missing?
- Is the missing information actually required for this product?
- Does the projection engine support the detected mechanics?
- Where does the implementation differ from the filing?
- What level of trust can a reviewer place in the result?

Actuary AI should make those questions easier to answer without hiding uncertainty.

## 3. Primary User

The primary user is an actuary or actuarial reviewer evaluating whether a product model correctly represents its source documents and is suitable for projection or further implementation work.

Secondary users may include:

- Product owners deciding what functionality to build next
- Engineers implementing projection mechanics
- Reviewers validating evidence, assumptions, and calculations
- Compliance or governance stakeholders inspecting traceability
- Automation agents creating bounded implementation and review tasks

## 4. Product Promise

For an uploaded product-document workspace, Actuary AI should provide:

1. **Product identity and scope**  
   A structured understanding of product type, coverage scope, issue ages, risk classes, premium pattern, riders, and other relevant attributes.

2. **Evidence-backed mechanics**  
   Important product facts and mechanics tied to source documents, pages, snippets, confidence, and provenance.

3. **Honest readiness**  
   A classification of required, optional, unresolved, unavailable, placeholder, and not-applicable information.

4. **Capability assessment**  
   A comparison between the mechanics required by the product and the mechanics supported by the available projection engine.

5. **Actionable gaps**  
   Clear explanations of blocking inputs, unsupported features, and recommended next actions.

6. **Traceable projections**  
   Projection results only when justified, with a trust level that reflects the quality of the evidence, inputs, and engine support.

7. **Review workflow**  
   A way for a human reviewer to inspect, approve, reject, or request changes with a durable audit trail.

## 5. Product Outcomes

A successful workspace should let an actuary answer:

- What product is this?
- What are its important mechanics?
- Where did each material fact come from?
- What is missing?
- Which missing items are truly required?
- Which features are unsupported by the engine?
- Can a projection be produced safely?
- What trust level applies?
- What should engineering or actuarial review do next?

## 6. MVP Direction

The MVP should prove the end-to-end workflow for a limited number of product lines while preserving an architecture that can expand.

The MVP should prioritize:

- Reliable document ingestion
- Structured product understanding
- Field-level evidence and provenance
- Requirement and readiness classification
- Capability assessment
- A bounded projection path
- Human review and decision persistence
- Clear separation between verified facts, inferences, placeholders, and missing data
- A product-agnostic shared architecture

The MVP may initially support only selected product types or mechanics. Unsupported capabilities must be shown honestly rather than emulated with silent assumptions.

## 7. Non-Goals

The current product is not intended to:

- Automatically certify regulatory compliance
- Replace actuarial judgment
- Guarantee filed-rate accuracy without sufficient source data and validation
- Support every insurance product or rider immediately
- Hide unsupported mechanics behind generic approximations
- Generate authoritative projections from placeholders
- Treat an LLM response as proof
- Optimize for a visually dense dashboard at the expense of reviewer clarity
- Encode demonstration products as permanent architecture

## 8. Role of AI

AI should be used where interpretation is valuable:

- Identifying product type and scope
- Extracting facts and mechanics from documents
- Mapping source language into structured product concepts
- Summarizing evidence
- Suggesting requirement applicability
- Identifying potentially unsupported mechanics
- Helping reviewers navigate source material

AI should not be the sole authority for:

- Numeric projection calculations
- Deterministic requirement-state transitions
- Trust-level assignment without rule checks
- Approval decisions
- Claiming a product is complete or compliant
- Replacing missing filed inputs with invented values

AI output must remain distinguishable from rule-derived, configured, reviewer-approved, and placeholder data.

## 9. Success Measures

The product is progressing when:

- A materially different product can be added without modifying shared logic for its product code.
- Important facts have usable provenance.
- False “missing information” warnings decrease.
- Unsupported mechanics are identified rather than silently approximated.
- Reviewers can understand why a projection has its assigned trust level.
- Changes to source documents produce explainable changes in extracted results.
- Cross-product contamination tests pass.
- The live workflow is validated after meaningful updates.
- An actuary spends less time locating facts and more time evaluating them.

## 10. Decision Rights

Billy is the product owner for consequential scope and architecture decisions.

The Actuary Architect agent may:

- Clarify a request into a task contract
- Apply existing principles
- Delegate bounded implementation and review work
- Reject work that violates approved architecture
- Recommend product and technical decisions

The Actuary Architect must escalate decisions that:

- Change the product vision
- Introduce a new product-line architecture
- Alter trust-level semantics
- Allow approximations for missing material inputs
- Expand deployment authority
- Remove or weaken review controls
- Make a product-specific exception in shared code
