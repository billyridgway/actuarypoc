# Definition of done

Freeze acceptance criteria before implementation. Select gates by affected
surface; do not weaken them after seeing results.

A nontrivial change is done only when:

1. Authoritative context and existing implementation were inspected.
2. Acceptance criteria, affected products/surfaces, and provenance expectations
   were written before editing.
3. Formatting/build checks and focused tests pass.
4. Relevant regression tests pass.
5. Shared-surface changes pass product-agnosticity review.
6. AI-dependent changes pass differential AI-integrity validation and label
   model/configured/derived/cached/fallback/placeholder/unresolved states.
7. Source-aware review has no accepted actionable findings.
8. Source-blind behavior validation satisfies the prewritten contract.
9. UI changes are exercised in the rendered live UI with screenshots and a
   real workflow, including empty/error/state semantics and provenance.
10. Deployed changes have successful CI, rollout, image digest and source
    identity where available, health/API checks, and actual workflow evidence
    from Pi k3s.
11. Documentation/state/decision records are updated and exact commands,
    outputs, evidence, limitations, and blockers are reported.

A required blocked or failed gate means **not complete**. Documentation-only
changes do not require a product deployment, but executable verification
scripts and configuration still require no-op/safe invocation tests.
