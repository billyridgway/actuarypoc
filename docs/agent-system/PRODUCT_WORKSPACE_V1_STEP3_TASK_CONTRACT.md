# Product Workspace v1 Step 3 Task Contract

> Contract for bounded Step 3 implementation only. This document records the approved scope, constraints, and validation plan for the simplified single-page Product Workspace normal-user experience.

---

## 1. Metadata

- **Task ID:** `PRODUCT-WORKSPACE-V1-STEP3`
- **Title:** Simplify the normal Product Workspace into one coherent page
- **Requested by:** Billy
- **Contract owner:** Actuary Architect
- **Created:** 2026-07-23
- **Target repository:** `actuarypoc`
- **Target branch or worktree:** `agent/actuary-pilot-20260722-222609`
- **Related issue or feature request:** Step 3 of the Product Workspace v1 plan
- **Priority:** `high`
- **Change type:** `UI`

## 2. Request

### Original request

Deliver the simplified single-page Product Workspace normal-user experience using the canonical workspace analysis/readiness model established in Steps 1-2.

### Problem to solve

The normal workspace experience still exposes multiple legacy panels and workflow fragments. A reviewer should be able to upload, analyze, inspect readiness, see evidence/provenance, and identify next actions on one clear page without losing honest unresolved or unsupported states.

### Desired outcome

A normal user reaches one primary Product Workspace page that coherently presents upload/analyze/readiness/review content, while redundant legacy panels and routes are hidden from the normal workflow and navigation.

## 3. Current Evidence

- **Current behavior:** The `ProductWorkspacePage` renders many stacked sections, including document inventory, extracted facts, compliance matrix, candidate requirements, unsupported features, feature requests, mechanics, assumptions, draft illustration, mechanics explanation, PMR/readiness, and uploaded documents. Advanced debug is currently shown via a toggle, but the page is still visually broad.
- **Repository evidence:** `web/ProductWorkspacePage.tsx`, `web/App.tsx`, `src/actuarypoc/tests/test_workspace_analysis_boundary.py`, `src/actuarypoc/tests/test_workspace_ul_analyzer.py`.
- **Live-system evidence:** None in this task.
- **Screenshots or API examples:** Not yet captured.
- **Relevant project-state entries:** `docs/agent-system/PROJECT_STATE.md` records Step 1 and Step 2 as repository-verified and notes that Step 3 work was not yet authorized.
- **Unknowns:** Whether an automated browser harness is available in this workspace; whether the UI can be exercised end-to-end without starting a local server.

## 4. Scope

### In scope

- Compose the normal Product Workspace around one primary guided page.
- Surface decision-relevant status, evidence/provenance, gaps, and required actions together.
- Hide legacy panels and nonessential workflow fragments from normal navigation while preserving the underlying capabilities behind explicit advanced access.
- Preserve truthful unresolved, unavailable, unsupported, placeholder, and not-applicable states.
- Add focused tests for page composition and legacy suppression.

### Out of scope

- Server-side projection eligibility/trust enforcement and projection output/blockers.
- Removing the legacy implementation or deleting supported capabilities.
- Deployment, main merge, or unrelated redesign.

### Files or components likely involved

- `web/ProductWorkspacePage.tsx`
- `web/App.tsx`
- `src/actuarypoc/tests/test_workspace_analysis_boundary.py`
- `src/actuarypoc/tests/test_workspace_ul_analyzer.py`
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
- [ ] Other: preserve legacy workflow content behind an explicit advanced/debug surface rather than deleting it.

## 6. Product and Data Constraints

- **Product lines affected:** Universal Life workspace review flow, with no new product-line branching.
- **Representative products:** Promise UL, other UL workspace snapshots used in existing tests.
- **Required document sets or fixtures:** Existing workspace snapshots and UL analyzer fixtures.
- **Sensitive data considerations:** Do not expose new secrets or hidden evidence in the simplified page.
- **Backward compatibility requirements:** Preserve API contracts and deterministic analysis outputs.
- **Migration requirements:** None.
- **Cache considerations:** Do not alter cache semantics.
- **Provenance requirements:** Maintain displayed evidence/provenance labels and honest fallback labeling.

## 7. Acceptance Criteria

1. Given a normal Product Workspace user, when the page loads, then one primary Product Workspace page is shown with upload/analyze/readiness/review content grouped coherently, and the evidence must show the current workspace status rather than legacy review chrome.
2. Given a workspace with evidence, gaps, and readiness data, when rendered in normal mode, then truthful state distinctions and provenance remain visible, including unresolved/unavailable/unsupported/placeholder/not-applicable distinctions.
3. Given the normal workflow, when the page renders, then redundant legacy panels are absent from normal navigation and hidden from the main flow, while still remaining available behind explicit advanced/debug access if needed.
4. Given existing supported analysis flows, when the UI is simplified, then API contracts and deterministic calculations remain unchanged and the existing backend tests still pass.

Each criterion should be evidenced by focused tests that would fail if the new page composition or suppression behavior regressed.

## 8. Validation Plan

### Focused tests

- UI rendering / composition test for the primary Product Workspace page.
- Legacy suppression test for normal navigation and workflow.

### Regression tests

- `src/actuarypoc/tests/test_workspace_analysis_boundary.py`
- `src/actuarypoc/tests/test_workspace_ul_analyzer.py`

### Cross-product tests

- Existing UL analyzer regression coverage to ensure the simplified page does not disturb canonical state shaping.

### AI-integrity tests

- Confirm placeholders/defaults/fallbacks remain labeled as such in the UI.

### UI or API behavior tests

- Rendered page smoke test with a representative workspace snapshot.

### Live validation

- **Required:** `no`
- **Environment:** Local repo workspace
- **Workflow:** Build and focused tests only
- **Expected evidence:** Command output, optionally screenshots if a browser harness is used

### Deployment validation

- **Deployment permitted:** `no`
- **Approval required from:** Billy
- **Expected commit/image identity:** Bounded Step 3 commit on `agent/actuary-pilot-20260722-222609`
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
| 2026-07-23 | Created | Actuary Architect | Bounded Step 3 UI composition task | Defines implementation scope |

## 12. Contract Revision History

| Version | Date | Changed by | Summary |
|---|---|---|---|
| 1 | 2026-07-23 | Actuary Architect | Initial Step 3 contract |

## 13. Final Closeout

- **Implementation status:** Pending
- **Review disposition:** Pending
- **Behavior-validation status:** Pending
- **Deployment status:** Not permitted
- **Acceptance criteria met:** Pending
- **Open follow-ups:** None yet
- **Project state updated:** Pending
- **Product-owner decision:** Pending
