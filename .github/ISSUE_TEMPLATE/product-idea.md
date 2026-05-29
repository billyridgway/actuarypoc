---
name: "Product idea"
about: "Capture a new product, rider, or product variation idea"
labels: ["product-idea"]
---

## Problem statement

Describe the product idea in terms of value:

- What kind of product/rider is this (term, WL, UL, rider, etc.)?
- Which customers / channels / filings does it relate to?
- Why does it matter for the illustration platform?

## Acceptance criteria

What does it mean for this product idea to be "captured" in the platform?
Examples:

- [ ] High-level ProductDefinition drafted (even if placeholders)
- [ ] Key assumptions and riders listed
- [ ] Filing and SERFF implications noted
- [ ] Next concrete steps (e.g. POC DSL, test product) identified

## Technical notes

- Any known product codes, form numbers, or existing filings?
- How similar is this to existing DSL/product definitions (e.g. P12TRF)?
- Any special requirements for MinIO layout, assumptions, or rates?

## Test plan

For a product idea, the "test" is usually conceptual at first:

- What example scenarios should a future POC cover?
- Are there obvious edge cases (issue ages, riders, underwriting classes)?
- How would we know a POC ProductDefinition/DSL is "good enough" to test
  with actuaries?

## Audit considerations

- Are there regulatory/filing complexities that we should track from day 1?
- Does this product require special handling in FilingRecords or
  ProductDefinitions (e.g. multiple carriers, multi-state complexity)?
- Any early thoughts on how to make future projections explainable
  (e.g. key assumption levers)?
