# Independent Review Report Template

> The Actuary Auditor completes this report independently.  
> The reviewer must not modify the implementation under review.

---

## 1. Metadata

- **Task ID:**
- **Task title:**
- **Reviewer:** Actuary Auditor
- **Review date:**
- **Repository:**
- **Branch/worktree:**
- **Commit or diff reviewed:**
- **Task-contract version:**
- **Review-bundle location:**

## 2. Disposition

Choose exactly one:

- [ ] **APPROVED**
- [ ] **APPROVED WITH FOLLOW-UP**
- [ ] **REJECTED**

### Disposition rationale

Provide a concise explanation grounded in evidence.

## 3. Materials Reviewed

- [ ] Task contract
- [ ] Product vision
- [ ] Architecture
- [ ] Product principles
- [ ] Project state
- [ ] Definition of done
- [ ] Implementation report
- [ ] Diff
- [ ] Changed-file snapshots
- [ ] Test output
- [ ] Product-agnosticity report
- [ ] Behavior-validation report
- [ ] Deployment report
- [ ] Screenshots
- [ ] Other:

Missing materials:

- 

## 4. Contract Compliance

### Goal achieved

- **Result:** `pass | partial | fail | not verifiable`
- **Evidence:**

### Scope respected

- **Result:** `pass | partial | fail`
- **Evidence:**

### Out-of-scope changes

- **Result:** `none | present`
- **Evidence:**

### Acceptance criteria

| Criterion | Result | Evidence | Notes |
|---|---|---|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |

## 5. Architecture Review

| Area | Result | Evidence |
|---|---|---|
| Canonical domain model | | |
| Product-line boundaries | | |
| Product-agnostic shared logic | | |
| Evidence and provenance | | |
| Requirement applicability | | |
| Capability assessment | | |
| Projection determinism | | |
| Trust semantics | | |
| Persistence | | |
| UI/domain separation | | |

## 6. Product-Agnosticity Review

### Product-specific references found

| Reference | Location | Type | Justified? | Rationale |
|---|---|---|---|---|
| | | product code / filename / fixture / label / policy ID | | |

### Cross-product contamination risk

- **Result:** `low | medium | high | blocking`
- **Evidence:**

### Required correction

- 

## 7. AI Integrity and Provenance

| Check | Result | Evidence |
|---|---|---|
| AI output distinguishable from rules/configuration | | |
| Placeholder distinguishable from extracted fact | | |
| Fallback distinguishable from source truth | | |
| Cache behavior understood | | |
| Materially different inputs tested | | |
| Output responds appropriately to input changes | | |
| Model or processing evidence captured where applicable | | |

## 8. Requirement and Readiness Semantics

| Check | Result | Evidence |
|---|---|---|
| Applicability precedes missingness | | |
| Not-applicable behavior works | | |
| Input state is correct | | |
| Implementation state is correct | | |
| Blocking-gap logic is correct | | |
| Trust impact is correct | | |

## 9. Test Review

### Tests added or changed

- 

### Commands reviewed

```text
Paste exact commands.
```

### Results

```text
Paste or reference exact results.
```

### Test-quality assessment

- **Positive coverage:**
- **Negative coverage:**
- **Regression coverage:**
- **Cross-product coverage:**
- **Failure-path coverage:**
- **Missing coverage:**

## 10. UI Review

Complete when applicable.

| Check | Result | Evidence |
|---|---|---|
| Rendered UI reviewed | | |
| Section purposes are distinct | | |
| Redundant facts removed or justified | | |
| Missing/not-applicable states are clear | | |
| Provenance is accessible | | |
| Placeholder/fallback is clear | | |
| Empty/error/partial states work | | |
| Multiple products were tested | | |

## 11. Live Behavior Review

- **Required by contract:** `yes | no`
- **Performed:** `yes | no`
- **Environment:**
- **Commit/image identity:**
- **Workflow exercised:**
- **Observed result:**
- **Evidence:**
- **Unverified behavior:**

## 12. Findings

Use one entry per finding.

### Finding R-001

- **Severity:** `blocking | high | medium | low | informational`
- **Category:** `contract | architecture | product-agnosticity | provenance | AI integrity | test | UI | deployment | security`
- **Location:**
- **Observed behavior:**
- **Evidence:**
- **Rule or criterion affected:**
- **Risk:**
- **Required correction:**
- **Retest required:**

Duplicate this section for additional findings.

## 13. Follow-Up Items

Only include non-blocking work when disposition is approved or approved with follow-up.

| Item | Owner | Priority | Reason |
|---|---|---|---|
| | | | |

## 14. Final Reviewer Statement

State:

1. Whether the implementation satisfies the task contract
2. Whether it follows the architecture and product principles
3. Whether test evidence is sufficient
4. Whether live behavior was verified where required
5. Whether the change may proceed
