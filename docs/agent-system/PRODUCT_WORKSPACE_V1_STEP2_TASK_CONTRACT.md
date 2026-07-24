# Product Workspace v1 Step 2 Task Contract

## 1. Metadata

- **Task ID:** `ACT-20260723-PW1-STEP2`
- **Title:** Canonical UL readiness and classification contract
- **Requested by:** Billy, through the Actuary Architect
- **Contract owner:** Actuary Architect
- **Created:** 2026-07-23
- **Target repository:** `actuarypoc`
- **Target branch or worktree:** Builder worktree at baseline `55d27367d8d8ca9a4343368c79d0bbed5a2173a2`
- **Priority:** high
- **Change type:** backend / extraction / requirements

## 2. Request

### Original request

Adapt the existing UL workspace analyzer to emit the canonical readiness and
classification contract while preserving practical legacy response
compatibility. This is Product Workspace v1 Step 2 only.

### Problem to solve

Step 1 provides exact workspace-document isolation and honest product identity
and provenance. The analyzer partitions readiness, but its
`requirementsClassification.all` items lack the architecture's canonical
fields and use presentation applicability values. Input readiness, engine
implementation, and applicability are not independently represented, and an
exclusive partition can erase one independently true gap.

### Desired outcome

Every existing UL requirement has stable canonical applicability,
implementation, input, materiality, and blocking fields. Applicability is
resolved before missingness; missing inputs and capability gaps remain
independent; unknown capability is never treated as support; and Step 1's
identity, provenance, document boundary, and unavailable-analysis behavior are
preserved.

## 3. Current Evidence

- **Current behavior:** `workspace_ul_analyzer.py` emits legacy requirement
  items and exclusive readiness buckets. Only the level policy/admin fee has a
  scoped supported-capability declaration. Other capability declarations are
  unresolved.
- **Repository evidence:** Step 1 analyzer and boundary tests pass at baseline
  `55d27367d8d8ca9a4343368c79d0bbed5a2173a2`; shared classification enums and
  deterministic blocking rules already exist in
  `domain/requirements_classification.py`.
- **Live-system evidence:** none; deployment is prohibited for this task.
- **Relevant project-state entries:** Step 1 is approved with follow-up;
  Product Workspace v1 Step 2 is planned.
- **Unknowns:** no complete general engine capability registry exists, and this
  task must not create one.

## 4. Scope

### In scope

- Emit `requirementId`, catalog impact/materiality, canonical applicability,
  implementation state, input state, and deterministic `isBlockingGap` for all
  existing UL requirements.
- Resolve applicability before missingness and derive non-exclusive missing,
  unsupported, unresolved-capability, unresolved-applicability, satisfied, and
  not-applicable views.
- Add only the narrow requirement-to-existing-UL-engine declarations necessary
  to distinguish supported, explicitly unsupported, and unknown capability.
- Use canonical provenance vocabulary while retaining clearly named legacy
  aliases required by existing consumers.
- Preserve the Step 1 endpoint boundary, identity, unavailable behavior, and
  top-level legacy response keys.
- Add focused and regression tests, review evidence, and a truthful project
  state update.

### Out of scope

- UI redesign or legacy-panel hiding.
- Projection eligibility or trust enforcement beyond readiness data emitted for
  later work.
- New product engines, product lines, or generic plugin/capability frameworks.
- Changes to approved deterministic classifier blocking semantics.
- Broad Python 3.9 compatibility cleanup, merge, push, deployment, or cluster
  changes.

### Files or components likely involved

- `src/actuarypoc/extract/workspace_ul_analyzer.py`
- `src/actuarypoc/domain/requirements_classification.py`
- Focused analyzer, classifier, and endpoint-boundary tests
- `docs/agent-system/PROJECT_STATE.md` and Step 2 review evidence

## 5. Architecture Constraints

- [x] Shared logic must remain product-agnostic.
- [x] No product-code or filename branches in shared behavior.
- [x] Canonical domain semantics remain the source of truth.
- [x] Applicability is determined before missingness.
- [x] AI/document provenance remains distinct from deterministic rules,
  configuration, fallback, default, and placeholder.
- [x] Blocking state remains deterministic under the existing classifier rule.
- [x] No risky migration and no deployment are permitted.

## 6. Product and Data Constraints

- **Product lines affected:** existing bounded universal-life workspace analyzer.
- **Representative products:** Promise UL fixture and a materially distinct UL
  identity; unresolved/other product types.
- **Required document sets or fixtures:** deterministic in-memory text document
  fixtures used by existing Step 1 tests.
- **Sensitive data considerations:** none; tests use synthetic data.
- **Backward compatibility requirements:** retain top-level analysis,
  identity/provenance, readiness/readiness-dashboard, requirements, and legacy
  requirement aliases where practical.
- **Migration requirements:** none.
- **Cache considerations:** none; the analyzer consumes exact current workspace
  membership on every endpoint run.
- **Provenance requirements:** new canonical fields use `product_document`,
  `deterministic_rule`, and `engine_configuration`; placeholders/defaults/
  fallbacks must never be represented as document- or AI-extracted values.

## 7. Acceptance Criteria

1. Supported UL analysis emits the complete canonical shape, with explicit
   engine-configuration provenance, while retaining practical legacy fields.
2. A second UL identity remains distinct and contains no Promise UL or P12TRF
   identity or mechanics; other/unresolved product types remain
   `analysis_unavailable`.
3. Confirmed-applicable missing input appears in `missingInformation`
   independently of supported, unsupported, or unknown capability state.
4. Explicit unsupported capability appears in `unsupportedCapabilities`
   independently of missing information; absent declarations appear only as
   unresolved capability and never default supported.
5. `needs_review` applicability is nonblocking and is not labeled missing;
   `confirmed_not_applicable` has `inputState=not_required`, is nonblocking, and
   appears in no missing-information or document-request view.
6. Placeholder/default/fallback inputs are not ready and are not labeled
   document-extracted.
7. Step 1 exact-document isolation and membership-validation regressions pass,
   including endpoint serialization/persistence behavior.

## 8. Validation Plan

### Focused tests

- Run analyzer canonical-shape and partition tests separately.
- Run generic requirement-classifier tests separately.

### Regression and cross-product tests

- Run Step 1 analyzer and exact-membership endpoint boundary tests separately
  and combined.
- Run relevant capability and endpoint regression tests.
- Confirm materially distinct UL and unavailable product fixtures.

### AI-integrity tests

- Confirm placeholder/default/fallback provenance is explicit and never
  `product_document` or `ai_extraction`.

### Live and deployment validation

- **Live required:** no; this is a bounded local backend contract change and
  deployment is prohibited.
- **Deployment permitted:** no.
- **Approval required from:** Billy for any later merge or deployment.

## 9. Required Handoff

The Builder must return the implementation summary, exact files and commit
identity, architecture choices, tests, exact commands/results, product-specific
reference scan, limitations, diff summary, and review-evidence location.

## 10. Reviewer Instructions

The independent Auditor must evaluate contract compliance, scope,
product-agnosticity, provenance/AI integrity, applicability-before-missingness,
independent gap partitions, test quality, regression risk, and compatibility.
Required disposition: `APPROVED`, `APPROVED WITH FOLLOW-UP`, or `REJECTED`.

## 11. Decision Log

| Date | Decision | Owner | Reason | Contract impact |
|---|---|---|---|---|
| 2026-07-23 | Use a narrow UL analyzer capability map, not a registry | Actuary Architect | Existing engine declarations are scoped and a general framework is out of scope | Keeps Step 2 bounded |
| 2026-07-23 | Preserve legacy fields as explicit aliases | Actuary Architect | Avoid a risky consumer migration | Adds canonical fields without removing old keys |

## 12. Contract Revision History

| Version | Date | Changed by | Summary |
|---|---|---|---|
| 1 | 2026-07-23 | Actuary Architect | Initial bounded Step 2 contract |

## 13. Final Closeout

- **Implementation status:** implemented locally; focused tests passed
- **Review disposition:** pending independent Auditor review
- **Behavior-validation status:** 19 focused/regression tests passed; known
  Python 3.9 classifier-test collection limitation recorded in review evidence
- **Deployment status:** not permitted
- **Acceptance criteria met:** Builder evidence recorded; Auditor confirmation pending
- **Open follow-ups:** preserve Step 1 follow-ups; independent review required
- **Project state updated:** yes; implemented/tested, review pending
- **Product-owner decision:** pending review; no merge/deployment authority
