# Actuary AI Definition of Done

> **Status:** Mandatory completion standard  
> **Last updated:** 2026-07-22  
> **Rule:** The applicable checklist must pass before work is described as complete

## 1. Core Definition

A change is done only when:

1. The requested outcome and acceptance criteria were written before implementation.
2. The existing behavior was inspected.
3. The implementation stays within approved scope.
4. Appropriate tests pass.
5. Independent review passes.
6. Required running-system validation passes.
7. Evidence is preserved.
8. Documentation is updated.
9. Known limitations are disclosed.
10. Deployment identity is confirmed when deployment occurred.

## 2. Universal Checklist

Applies to every nontrivial change.

- [ ] A task contract exists.
- [ ] Goal, scope, exclusions, constraints, and acceptance criteria are explicit.
- [ ] Relevant architecture and product principles were read.
- [ ] Existing code and tests were inspected before editing.
- [ ] The implementation does not silently broaden scope.
- [ ] Product-specific references were scanned and justified.
- [ ] Placeholders, fallbacks, defaults, and fixtures are labeled honestly.
- [ ] Focused tests pass.
- [ ] Relevant regression tests pass.
- [ ] Exact commands and outputs are recorded.
- [ ] An implementation report exists.
- [ ] An independent review report exists.
- [ ] Blocking review findings are resolved.
- [ ] `PROJECT_STATE.md` is updated when implementation state changed.
- [ ] Remaining limitations are stated.

## 3. Documentation-Only Change

- [ ] Claims are supported by repository, live-system, or cited design evidence.
- [ ] Target architecture is not described as current implementation.
- [ ] Dates and status labels are updated.
- [ ] Cross-document links remain correct.
- [ ] The document does not create a new product requirement accidentally.
- [ ] Independent review checks internal consistency.

## 4. Backend or Domain Change

- [ ] Domain semantics are represented in canonical objects.
- [ ] Shared logic remains product-agnostic.
- [ ] Product-line-specific behavior is scoped appropriately.
- [ ] Schema changes are backward-compatible or migration is documented.
- [ ] Positive tests exist.
- [ ] Negative tests exist.
- [ ] Regression tests cover adjacent products or flows.
- [ ] Errors and unresolved states are explicit.
- [ ] API contracts are updated where applicable.
- [ ] Persistence behavior is tested where applicable.

## 5. AI or Extraction Change

- [ ] The model prompt, extraction logic, or processing path is identified.
- [ ] At least two materially different document sets or products are tested.
- [ ] Output changes appropriately when source facts change.
- [ ] Unrelated output remains stable where expected.
- [ ] Provenance distinguishes AI extraction, inference, configuration, cache, fallback, and placeholder.
- [ ] Static fixture values are not presented as AI output.
- [ ] Cache behavior is tested or explicitly bypassed.
- [ ] Invalid or insufficient documents produce honest unresolved states.
- [ ] Cross-product contamination tests pass.
- [ ] Model-call or processing evidence is captured where available without exposing secrets.

## 6. Requirement or Readiness Change

- [ ] Applicability is determined before missingness.
- [ ] Requirement ID is stable.
- [ ] Product-model dependencies are explicit.
- [ ] Input-state and implementation-state behavior are tested.
- [ ] Blocking-gap logic is tested.
- [ ] Not-applicable behavior is tested.
- [ ] The UI reason explains why the requirement applies.
- [ ] Trust-level effects are tested.

## 7. Projection Change

- [ ] Numeric behavior is deterministic.
- [ ] Inputs and assumptions are versioned or identifiable.
- [ ] Boundary cases are tested.
- [ ] Expected calculation examples are independently checked.
- [ ] Unsupported mechanics fail or downgrade trust explicitly.
- [ ] Projection configuration can be traced to product-model fields.
- [ ] Trust-level assignment follows rules.
- [ ] Results are reproducible from recorded inputs and code identity.

## 8. UI Change

- [ ] The rendered UI is reviewed, not only the component source.
- [ ] Every section answers a distinct reviewer question.
- [ ] Redundant facts or warnings are removed or justified.
- [ ] Required, optional, unresolved, unavailable, and not-applicable states are visually distinct.
- [ ] Provenance is accessible.
- [ ] Placeholder and fallback values are unmistakable.
- [ ] Loading, empty, error, and partial states are tested.
- [ ] The relevant browser workflow is exercised.
- [ ] Screenshots or equivalent evidence are captured.
- [ ] The UI is tested with materially different products.

## 9. Deployment Change

- [ ] Change is approved for deployment.
- [ ] Protected-branch and merge requirements pass.
- [ ] Build succeeds.
- [ ] Container image is published.
- [ ] Commit and image digest are recorded.
- [ ] Kubernetes rollout completes.
- [ ] Running workload uses the expected image digest.
- [ ] Health checks pass.
- [ ] Relevant API smoke tests pass.
- [ ] Relevant UI workflow passes.
- [ ] Persistence and migration checks pass where applicable.
- [ ] Rollback steps are documented.
- [ ] Deployment report exists.

## 10. Review Dispositions

### APPROVED

All blocking criteria pass. Any remaining follow-up is explicitly non-blocking.

### APPROVED WITH FOLLOW-UP

The change may proceed, but non-blocking actions are recorded with owners and rationale.

### REJECTED

One or more blocking defects remain, including:

- Contract violation
- Architecture violation
- Product-specific hardcoding
- False AI provenance
- Missing required tests
- Failed regression
- Failed live validation
- Undisclosed placeholder or fallback
- Unsafe deployment condition

## 11. Required Evidence Bundle

A completed change should have:

```text
task-contract.md
implementation-report.md
changes.diff
test-results.txt
product-agnosticity-report.md
review-report.md
behavior-validation-report.md      # when applicable
deployment-report.md               # when applicable
screenshots/                       # when applicable
```

## 12. Completion Language

Allowed:

- Implemented locally; review pending
- Unit tests passed; live validation not run
- Review approved; deployment pending
- Deployed and smoke-tested
- Partially verified
- Blocked by unavailable dependency

Not allowed unless fully supported:

- Done
- Complete
- Fixed
- Verified
- Production-ready
- Filed-rate ready

## 13. Exception Process

An exception requires:

1. Explicit description of the skipped criterion
2. Reason
3. Risk
4. Compensating control
5. Owner approval
6. Follow-up action
7. Expiration or review date

The implementer may not approve its own exception.
