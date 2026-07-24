# Product Workspace v1 Step 4 Task Contract

> Contract for bounded Step 4 implementation only. This document records the approved scope, constraints, and validation plan for server-authoritative projection eligibility and exact blocker reporting.

---

## 1. Metadata

- **Task ID:** `PRODUCT-WORKSPACE-V1-STEP4`
- **Title:** Enforce projection eligibility and trust on the server
- **Requested by:** Billy
- **Contract owner:** Actuary Architect
- **Created:** 2026-07-23
- **Target repository:** `actuarypoc`
- **Target branch or worktree:** `agent/actuary-pilot-20260722-222609`
- **Related issue or feature request:** Step 4 of the Product Workspace v1 plan
- **Priority:** `high`
- **Change type:** `backend`

## 2. Request

### Original request

Enforce projection eligibility and trust server-side, returning and showing either a product-faithful deterministic projection or exact blockers.

### Problem to solve

The current projection path still relies on broader UI/state composition and does not make the server the final authority for eligibility, trust, or blocker reporting. A reviewer should never be able to bypass blocked canonical states with client-only logic, and eligible workspaces should return a deterministic projection with explicit basis and provenance.

### Desired outcome

The server returns one of two mutually exclusive outcomes for projection requests: either a deterministic product-faithful projection with explicit trust/basis/provenance, or an exact structured blocker set with blocker IDs, reasons, and evidence needs. The UI shows only the server-authorized outcome and cannot bypass eligibility rules.

## 3. Current Evidence

- **Current behavior:** The UL workspace analyzer already emits canonical readiness, blocker partitions, and rule-derived trust hints. The broader UI/projection code still computes trust and projection summaries in a larger flow, and client composition can surface projection-related state independently of a dedicated server eligibility gate.
- **Repository evidence:** `src/actuarypoc/extract/workspace_ul_analyzer.py`, `src/actuarypoc/ui/server.py`, `src/actuarypoc/projection/service.py`, `src/actuarypoc/projection/engine.py`, `web/ProductWorkspacePage.tsx`, `src/actuarypoc/tests/test_workspace_ul_analyzer.py`, `src/actuarypoc/tests/test_workspace_analysis_boundary.py`.
- **Live-system evidence:** None in this task.
- **Screenshots or API examples:** None yet.
- **Relevant project-state entries:** `docs/agent-system/PROJECT_STATE.md` records Step 1 and Step 2 as repository-verified and notes Step 3 as a UI simplification task only.
- **Unknowns:** The exact API shape for server-side projection blockers vs deterministic projection response has not yet been finalized in code; the implementation must preserve product-agnostic shared mechanics and avoid product-code branches.

## 4. Scope

### In scope

- Add a server-authoritative eligibility decision derived from readiness, applicability, capability, input, and provenance state.
- Derive trust rule-wise from canonical state rather than client flags.
- Return a deterministic projection only when eligible and supported.
- Return exact structured blockers otherwise, including blocker IDs, reasons, and evidence needs.
- Update API and Product Workspace rendering so the UI shows exactly one of projection or blockers.
- Add focused backend/API/UI composition tests and relevant regressions.

### Out of scope

- Step 5 milestone E2E work.
- Unrelated redesign or broader UI re-layout.
- Unsupported product approximation or silent fallback projection.
- Merge, deploy, or cluster changes.

### Files or components likely involved

- `src/actuarypoc/ui/server.py`
- `src/actuarypoc/projection/service.py`
- `src/actuarypoc/projection/engine.py`
- `src/actuarypoc/extract/workspace_ul_analyzer.py`
- `web/ProductWorkspacePage.tsx`
- `web/App.tsx`
- Focused tests under `src/actuarypoc/tests/`
- `docs/agent-system/PROJECT_STATE.md`

## 5. Architecture Constraints

- [x] Shared logic must remain product-agnostic.
- [x] No product-code branches in shared behavior.
- [x] No filename-driven behavior.
- [x] Canonical domain objects remain the source of truth.
- [x] Applicability is determined before missingness.
- [x] AI provenance remains distinct from rules, configuration, cache, fallback, and placeholder.
- [x] Projection logic remains deterministic.
- [x] Trust is rule-derived.
- [x] Reviewer decisions remain durable and attributed.
- [x] UI must reduce or avoid redundant information.
- [x] No deployment is permitted.
- [x] Other: server is authoritative; the UI may only render the server result and must not bypass eligibility.

## 6. Product and Data Constraints

- **Product lines affected:** bounded UL workspace projection flow and existing projection API consumers.
- **Representative products:** Promise UL workspace snapshots and other UL fixtures already covered by regression tests.
- **Required document sets or fixtures:** Existing workspace analysis fixtures and projection snapshots used in current tests.
- **Sensitive data considerations:** Do not surface new secrets or hidden evidence in blocker payloads or projection summaries.
- **Backward compatibility requirements:** Preserve existing honest unavailable/unsupported semantics and do not break unrelated read-only UI routes.
- **Migration requirements:** None.
- **Cache considerations:** Do not change cache behavior unless a server-authoritative eligibility decision requires a clear, testable cache boundary.
- **Provenance requirements:** Preserve explicit provenance for extracted facts, deterministic rules, engine configuration, placeholder/default/fallback, and blocker evidence needs.

## 7. Acceptance Criteria

1. Given a blocking canonical state, when the server receives a projection request, then it denies projection and returns structured blockers with stable IDs, reasons, and evidence needs, and the response does not include a projection payload.
2. Given supported complete eligible inputs, when the server receives a projection request, then it returns a deterministic product-faithful projection with explicit basis, provenance, and rule-derived trust.
3. Given the Product Workspace UI, when it renders a projection outcome, then it shows exactly one of projection or blockers and does not use client-only eligibility to bypass the server.
4. Given tampered or client-only eligibility state, when the UI or API attempts to project, then the server still enforces canonical eligibility and returns the same denial or deterministic projection outcome.

Each criterion should be evidenced by focused tests that would fail if eligibility, trust derivation, blocker reporting, or mutually exclusive rendering regressed.

## 8. Validation Plan

### Focused tests

- Server eligibility and blocker response tests.
- Deterministic projection and trust derivation tests.

### Regression tests

- Existing UL analyzer readiness regressions.
- Existing workspace analysis boundary regressions.

### Cross-product tests

- Representative UL workspaces with materially different readiness states.

### AI-integrity tests

- Confirm placeholders/defaults/fallbacks never qualify as extracted facts or eligible inputs.

### UI or API behavior tests

- Product Workspace rendering test for mutually exclusive projection vs blocker output.

### Live validation

- **Required:** `no`
- **Environment:** Local repo workspace
- **Workflow:** Focused tests and build only
- **Expected evidence:** Command output and test results

### Deployment validation

- **Deployment permitted:** `no`
- **Approval required from:** Billy
- **Expected commit/image identity:** Bounded Step 4 commit on `agent/actuary-pilot-20260722-222609`
- **Rollback requirement:** None in this task because deployment is out of scope

## 9. Required Handoff

The implementer must return:

- [ ] Implementation summary
- [ ] Files changed
- [ ] Architectural choices
- [ ] Tests added or changed
- [ ] Exact commands
- [ ] Complete results
- [ ] Product-specific reference report
- [ ] Known limitations
- [ ] Diff or commit
- [ ] Review-bundle location

## 10. Reviewer Instructions

The reviewer must independently evaluate:

- [ ] Contract compliance
- [ ] Scope
- [ ] Product agnosticism
- [ ] Provenance
- [ ] AI integrity
- [ ] Requirement applicability
- [ ] Test quality
- [ ] Regression risk
- [ ] UI redundancy where applicable
- [ ] Deployment evidence where applicable

Required disposition:

- `APPROVED`
- `APPROVED WITH FOLLOW-UP`
- `REJECTED`

## 11. Decision Log

| Date | Decision | Owner | Reason | Contract impact |
|---|---|---|---|---|
| 2026-07-23 | Created | Actuary Architect | Bounded Step 4 server-authoritative projection task | Defines implementation scope |

## 12. Contract Revision History

| Version | Date | Changed by | Summary |
|---|---|---|---|
| 1 | 2026-07-23 | Actuary Architect | Initial Step 4 contract |

## 13. Final Closeout

- **Implementation status:** Pending
- **Review disposition:** Pending
- **Behavior-validation status:** Pending
- **Deployment status:** Not permitted
- **Acceptance criteria met:** Pending
- **Open follow-ups:** None yet
- **Project state updated:** Pending
- **Product-owner decision:** Pending
