# Actuary AI Project State

> **Status:** Living, evidence-based project record  
> **Last updated:** 2026-07-22  
> **Owner:** Actuary Architect, with product-owner review  
> **Rule:** Repository and live-system evidence outrank chat summaries and file timestamps

## 1. Purpose

This document records the latest verified implementation state of Actuary AI.

It must distinguish:

- Verified current behavior
- Reported but not recently reverified behavior
- Target architecture
- Planned work
- Known risks
- Open questions

Agents must read this document before planning work and update it after meaningful verified changes.

## 2. Status Labels

Use these labels:

- **VERIFIED-REPO** — confirmed from the current repository and tests
- **VERIFIED-LIVE** — confirmed against the deployed environment
- **REPORTED** — described in prior work but not reverified during the latest review
- **TARGET** — desired architecture, not proof of implementation
- **PLANNED** — approved work not yet implemented
- **UNKNOWN** — insufficient evidence

## 3. Current Environment

### Reported platform

- **REPORTED:** The project uses the `actuarypoc` and `illustration-operator` repositories.
- **REPORTED:** The application is deployed on a Raspberry Pi k3s cluster.
- **REPORTED:** MinIO is used for object storage.
- **REPORTED:** PostgreSQL is used for durable application records.
- **REPORTED:** A web UI and API are available in the deployed environment.

These facts must be reverified and supplemented with exact repository paths, namespace, deployments, service names, container images, health endpoints, and kubeconfig locations before automated deployment work is enabled.

## 4. Architecture Implementation State

The prior architecture document reported:

- **REPORTED:** A generic requirement classifier exists in `src/actuarypoc/domain/requirements_classification.py`.
- **REPORTED:** The classifier is wired into the Promise UL workspace path.
- **REPORTED:** The UL runtime configuration and workspace builder remain substantially Promise-UL-shaped.
- **REPORTED:** Some paths use placeholder assumptions.
- **REPORTED:** Term and whole-life models and engines are not wired into the unified architecture.
- **TARGET:** Product-line models, requirement catalogs, capability assessment, feature requests, unified projection dispatch, and shared workspace semantics.

No agent may treat the target architecture as implemented without code and behavior evidence.

## 5. Reported Product Capabilities

Prior project work has reported the following capabilities. Each item requires re-verification before it is marked current:

- **REPORTED:** Product Model Review and Trust Surface UI
- **REPORTED:** Scenario evidence and scenario drill-down
- **REPORTED:** Review-decision persistence
- **REPORTED:** Multi-document workspace creation, upload, and analysis
- **REPORTED:** Product mechanics representation
- **REPORTED:** Mechanics validation and patch-preview workflows
- **REPORTED:** Approval and rejection persistence for mechanic patches
- **REPORTED:** Evidence items with source references and confidence
- **REPORTED:** Cross-product contamination guardrails
- **REPORTED:** Placeholder handling for unresolved COI inputs
- **REPORTED:** Product workspace views for at least P12TRF and Promise UL test paths

These items may be incomplete, product-specific, or partially implemented. Reverify both source and running behavior.

## 6. Known Architectural Risks

### 6.1 Product-Specific Shared Logic

Risk:

- Demonstration products become permanent branches in shared services.
- Product codes or filenames influence extraction, requirements, or UI behavior.

Required control:

- Product-agnosticity scan
- Cross-product tests
- Independent review
- Explicit adapter justification

### 6.2 Static Behavior Presented as AI

Risk:

- Fast, cached, configured, or hardcoded results are presented as model-derived extraction.

Required control:

- Trace model or extraction execution where possible
- Compare materially different inputs
- Verify downstream changes
- Label cache, fallback, fixture, and placeholder provenance

### 6.3 False Missing-Information Warnings

Risk:

- The UI declares fields missing before proving they apply to the product.

Required control:

- Applicability classification
- Requirement-to-model mapping
- Product-line catalogs
- Reviewer-facing reason

### 6.4 Redundant UI

Risk:

- Multiple sections repeat the same fact, provenance, or warning without helping a reviewer make a decision.

Required control:

- Rendered UI review
- Section-purpose test
- Signal-to-noise evaluation
- Removal or consolidation of duplicate displays

### 6.5 Source and Deployment Drift

Risk:

- Local code, built images, and the running cluster differ.

Required control:

- Commit identification
- Image digest verification
- Rollout verification
- Live smoke tests
- Deployment report

## 7. Immediate Verification Backlog

Before the first agent-implemented product change, the Actuary Architect should coordinate a read-only baseline review.

Required outputs:

1. Repository inventory
2. Current branch and commit
3. Test-command inventory
4. API endpoint inventory
5. UI route inventory
6. Deployment inventory
7. Current image digests
8. Document-ingestion flow
9. Product-understanding flow
10. Requirement-classification flow
11. Capability-assessment state
12. Projection-engine state
13. Review-decision persistence
14. Product-specific reference scan
15. Placeholder and fallback scan
16. Live workflow smoke test

## 8. Current Agent System

- **VERIFIED-LIVE:** `actuary-master` exists as Actuary Architect.
- **VERIFIED-LIVE:** `actuary-implementer` exists as Actuary Builder.
- **VERIFIED-LIVE:** `actuary-reviewer` exists as Actuary Auditor.
- **VERIFIED-LIVE:** Actuary Architect may explicitly delegate only to Actuary Builder and Actuary Auditor.
- **VERIFIED-LIVE:** Explicit agent IDs are required.
- **VERIFIED-LIVE:** Global active subagents are limited to two.
- **VERIFIED-LIVE:** A parent session may have at most two active children.
- **VERIFIED-LIVE:** Spawn depth is limited to one.
- **VERIFIED-LIVE:** OpenClaw configuration validates and Gateway health reports OK.

Still required:

- **PLANNED:** Restrict reviewer tools and workspace access to read-only.
- **PLANNED:** Create a dedicated builder Git worktree.
- **PLANNED:** Define review-bundle storage and handoff.
- **PLANNED:** Run a read-only delegation pilot.
- **PLANNED:** Install or create change-closeout and validation skills.
- **PLANNED:** Separate deployment authority from builder and architect.

## 9. Next Recommended Milestone

### Milestone: Read-Only Architecture Baseline

Goal:

Create a verified baseline without changing product behavior.

Acceptance criteria:

- Architect writes a task contract.
- Builder performs repository inspection without edits.
- Builder produces a structured review bundle.
- Auditor independently reviews the findings.
- Architect resolves disagreements.
- Project state is updated with verified facts.
- No merge or deployment occurs.

## 10. Update Procedure

After meaningful work:

1. Add the date.
2. Identify the task contract.
3. Change only statements supported by evidence.
4. Include repository commit or deployment identity.
5. Move items from `REPORTED` to `VERIFIED-REPO` or `VERIFIED-LIVE`.
6. Record newly discovered risks and limitations.
7. Do not erase historical context without preserving the reason.
8. Obtain product-owner review for major changes in direction.
