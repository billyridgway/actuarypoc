# Product vision and MVP boundaries

## Accepted direction

Actuary AI is a product-understanding and trust system for turning insurance
filings and related evidence into reviewable product definitions, assumptions,
mechanics, projection behavior, and audit evidence. It should help an actuary
understand and review decisions, not merely display generated summaries.

Shared platform capabilities must be product-agnostic. Product-specific facts
belong in source evidence, product definitions, configuration, DSL/data, or an
explicitly scoped adapter. A successful demonstration for one product is not
proof of cross-product support.

AI-dependent behavior must be inspectable and honest about provenance. Model
output, mechanical derivation, configuration, cache, fallback, placeholder,
and unresolved values are distinct states.

## Current MVP boundary

- In scope: document/workspace onboarding; evidence-backed product
  understanding; review of requirements, definitions, assumptions, mechanics,
  scenarios, and projections; reproducible audit evidence; operator-driven
  execution on Pi k3s; user-visible trust and provenance.
- Reference products may be used to prove the platform, including P12TRF and
  Promise UL material already present in source/tests. Reference-product logic
  must not silently become shared-platform policy.
- Human review and explicit unresolved states remain part of the MVP. The
  system does not autonomously approve actuarial correctness.
- UI quality is functional: every displayed item should help an actuary make or
  review a decision, with correct required/optional/not-applicable and
  provenance states.

## Not claimed or not decided

- Full production readiness, regulatory approval, or coverage of all insurance
  product families is not established.
- The repository does not establish a final commercial packaging, tenancy,
  authorization, or production-scale architecture decision.
- No authoritative decision found defines which additional product must follow
  the current reference products or the exact exit criteria for a public MVP.
