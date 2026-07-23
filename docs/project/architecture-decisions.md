# Architecture decisions

Only decisions supported by current manifests, source, or explicit project
documentation are listed as accepted. Plans and unresolved items are separate.

## Accepted

- **A-001 — Split runtime ownership.** `actuarypoc` owns extraction,
  definitions/assumptions, projections, API, and UI. `illustration-operator`
  owns Kubernetes reconciliation and Job/status orchestration.
- **A-002 — Kubernetes Jobs are the execution unit.** The operator creates Jobs
  for extraction/projection work; Dagster is historical for this path. Source:
  operator README/history and controller implementation.
- **A-003 — MinIO is the primary artifact store.** Projection, audit, document,
  and review artifacts use the `illuminet` bucket and structured object keys.
  Postgres supports mutable review/workspace state.
- **A-004 — Product variation belongs outside shared logic.** Product registry,
  product definitions, DSL/configuration, and scoped adapters are the intended
  variation points. This is a governing constraint; current compatibility code
  still requires review.
- **A-005 — API and React UI form one behavior surface.** Contract changes must
  be validated across backend response, frontend rendering, and live workflow.
- **A-006 — Provenance and reproducibility are first-class.** Missing inputs
  must surface warnings/unresolved state; arbitrary silent actuarial fallbacks
  are not acceptable.
- **A-007 — GitHub Actions builds images; Pi k3s is the MVP runtime.** Mutable
  tags use `imagePullPolicy: Always`; closeout records the pulled digest and,
  when available, embedded Git identity.

## Historical, superseded, or limited

- Dagster deployments and documents remain in the workspace, but the operator
  architecture standardized projection execution on Kubernetes Jobs.
- P12TRF-specific routes, fixtures, and golden tests are valid scoped assets,
  not an architecture decision to specialize the shared platform.

## Unresolved

- Canonical authentication/authorization and multi-tenant boundaries.
- Production storage, availability, backup, and disaster-recovery topology.
- A complete versioned public API contract and migration policy.
- The authoritative mapping from container digest to source commit is not
  consistently available from current deployment evidence.
