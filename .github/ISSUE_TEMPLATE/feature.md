---
name: "Feature"
about: "Propose a new feature or enhancement for the illustration backend/engine/UI"
labels: ["feature"]
---

## Problem statement

Describe the user or business problem this feature should solve. Avoid jumping
straight to implementation. Include relevant context (products, filings,
users, environments).

## Acceptance criteria

List concrete, verifiable outcomes. For example:

- [ ] New capability is visible via CLI / API / UI as described
- [ ] Behavior is well-defined for errors and edge cases
- [ ] Relevant products (e.g. P12TRF) are covered, or explicitly excluded

## Technical notes

Capture initial design thoughts and constraints:

- Affected modules (e.g. `projection/engine.py`, `dsl/`, `ui/server.py`)
- Data flows (MinIO prefixes, CRDs, RunDetail fields)
- Any interactions with `illustration-operator` or k3s Jobs

Do **not** put secrets, tokens, or raw PAS data here.

## Test plan

How will we verify the feature works?

- Unit tests (Python / JS): which test files and scenarios?
- Golden tests: any existing or new golden cases to update?
- k3s validation: which `IllustrationProject` or projection key will be
  used as a smoke test?

## Audit considerations

How does this feature affect trust and auditability?

- Does it change which inputs/assumptions are used?
- Does it require updates to `AuditRecord`, FilingRecord, or ProductDefinition
  design/docs?
- Do we need new warnings when assumptions or inputs are missing?  
- What should show up in the RunDetail UI to explain this feature?
