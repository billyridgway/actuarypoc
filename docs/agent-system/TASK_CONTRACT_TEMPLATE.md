# Task Contract Template

> Copy this file for every nontrivial Actuary AI task.  
> The Actuary Architect owns the contract.  
> Implementation must not begin until the required fields are complete.

---

## 1. Metadata

- **Task ID:** `ACT-YYYYMMDD-NNN`
- **Title:**
- **Requested by:** Billy
- **Contract owner:** Actuary Architect
- **Created:**
- **Target repository:**
- **Target branch or worktree:**
- **Related issue or feature request:**
- **Priority:** `low | medium | high | urgent`
- **Change type:** `documentation | backend | extraction | requirements | projection | UI | infrastructure | validation`

## 2. Request

### Original request

> Paste or summarize the product-owner request without changing its meaning.

### Problem to solve

Describe the observed problem and why it matters to an actuary or reviewer.

### Desired outcome

Describe the observable result, not the implementation.

## 3. Current Evidence

Record what is known before implementation.

- **Current behavior:**
- **Repository evidence:**
- **Live-system evidence:**
- **Screenshots or API examples:**
- **Relevant project-state entries:**
- **Unknowns:**

Do not convert assumptions into facts.

## 4. Scope

### In scope

- 
- 
- 

### Out of scope

- 
- 
- 

### Files or components likely involved

- 
- 
- 

The implementer may inspect adjacent code but may not broaden the change without contract revision.

## 5. Architecture Constraints

Check all that apply and add task-specific constraints.

- [ ] Shared logic must remain product-agnostic.
- [ ] No product-code branches in shared behavior.
- [ ] No filename-driven behavior.
- [ ] Canonical domain objects remain the source of truth.
- [ ] Applicability is determined before missingness.
- [ ] AI provenance remains distinct from rules, configuration, cache, fallback, and placeholder.
- [ ] Projection logic remains deterministic.
- [ ] Trust is rule-derived.
- [ ] Reviewer decisions remain durable and attributed.
- [ ] UI must reduce or avoid redundant information.
- [ ] No deployment is permitted.
- [ ] Other:

## 6. Product and Data Constraints

- **Product lines affected:**
- **Representative products:**
- **Required document sets or fixtures:**
- **Sensitive data considerations:**
- **Backward compatibility requirements:**
- **Migration requirements:**
- **Cache considerations:**
- **Provenance requirements:**

## 7. Acceptance Criteria

Write testable, observable criteria.

1. 
2. 
3. 
4. 

Each criterion should state:

- Given
- When
- Then
- Required evidence

Example:

> Given a Promise UL workspace and a term-life workspace, when requirements are classified, then each product displays only applicable missing information, with a reason and provenance, and no product code appears in shared classification logic.

## 8. Validation Plan

### Focused tests

- 
- 

### Regression tests

- 
- 

### Cross-product tests

- 
- 

### AI-integrity tests

- 
- 

### UI or API behavior tests

- 
- 

### Live validation

- **Required:** `yes | no`
- **Environment:**
- **Workflow:**
- **Expected evidence:**

### Deployment validation

- **Deployment permitted:** `yes | no`
- **Approval required from:**
- **Expected commit/image identity:**
- **Rollback requirement:**

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
| | | | | |

## 12. Contract Revision History

| Version | Date | Changed by | Summary |
|---|---|---|---|
| 1 | | Actuary Architect | Initial contract |

## 13. Final Closeout

- **Implementation status:**
- **Review disposition:**
- **Behavior-validation status:**
- **Deployment status:**
- **Acceptance criteria met:**
- **Open follow-ups:**
- **Project state updated:**
- **Product-owner decision:**
