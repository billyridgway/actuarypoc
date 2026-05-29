# Definition of Done – Insurance Illustration Platform (ActuaryPOC)

> Status: **Applies to current work going forward**. Some existing code
> predates this definition and may not yet satisfy every point.

This document defines when a change related to the Insurance Illustration
Platform is considered **done** in the `actuarypoc` repo. It is intentionally
strict because the ultimate goal is regulatory‑grade, explainable
illustrations.

The checklist below applies to features, significant refactors, and
cross‑cutting changes that touch the projection engine, assumptions,
operator integration, or UI.

---

## 1. Definition of Done Checklist

A feature is **not complete** unless all of the following are satisfied or
explicitly waived (with rationale) in the PR/commit message.

### 1.1 Tests

1. **Unit tests pass**
   - Relevant Python tests under `src/actuarypoc/tests/` have been added or
     updated.
   - `python -m pytest src/actuarypoc/tests` passes locally and in CI.

2. **Golden tests pass (where applicable)**
   - For products with golden cases (e.g. P12TRF under
     `src/actuarypoc/tests/golden/`), golden inputs/outputs are updated
     intentionally.
   - Any changes to golden data are justified in the commit message and, if
     material, in docs.

### 1.2 API & Schema

3. **API schema updated**
   - If the Run Detail JSON shape changes or new fields are added, update:
     - `src/actuarypoc/ui/server.py` (RunDetail builder).
     - `web/run-detail.types.ts` (TypeScript types for the React UI).
   - Any external API contracts (if introduced in future) must have their
     schema/docs updated as well.

### 1.3 UI / UX

4. **UI updated (when relevant)**
   - If a change affects what an actuary or product user needs to see,
     update:
     - React components in `web/` (e.g. `RunDetailPage.tsx`).
     - Styles as needed (`web/styles.css`).
   - New fields that matter for trust or understanding must be visible in the
     UI or justified as intentionally internal‑only.

### 1.4 Audit & Assumptions

5. **Audit trail updated**
   - If a change introduces new inputs, assumptions, or output artefacts,
     ensure they are:
     - referenced in projection summaries and/or audit snapshot objects, and
     - discoverable via Run Detail.

6. **Assumptions documented**
   - New or changed assumptions include:
     - A clear description (e.g. in DSL `meta`, assumption set metadata, or
       docs under `docs/knowledge/`).
     - When applicable, a pointer to source material (SERFF filing, actuarial
       memo, internal spec) using MinIO object paths or references.

7. **Warnings implemented for missing / degraded assumptions**
   - If required inputs or assumptions are unavailable or incomplete,
     projection code should:
     - emit warnings (e.g. recorded on the projection summary or Run Detail
       warnings list), and
     - avoid silently substituting unrealistic default values.

### 1.5 Deployment & Validation

8. **Deployment validated on k3s (when change impacts runtime)**
   - For changes that affect Jobs, the UI, or MinIO wiring:
     - The `actuarypoc` image for the relevant branch (`main` in most cases)
       has been built and pushed by GitHub Actions.
     - The `projection-ui` Deployment in the `illustrations-poc` namespace
       has been updated (if necessary) and restarted.
     - At least one projection run has been executed on the dev cluster to
       exercise the change.

9. **Results summarized**
   - A short summary is recorded in one or more of:
     - the PR description
     - a commit message
     - a small note in `docs/` (for major architectural or actuarial changes).
   - Summary should include:
     - what changed
     - how it was validated (tests + specific projection run)
     - any new risks or follow‑ups.

---

## 2. Scope & Exceptions

- **Small refactors / docs‑only changes**
  - May not need k3s validation, but should still keep tests passing.
- **Experimental branches**
  - Can temporarily skip parts of this DoD, but must clearly label the branch
     and avoid merging to `main` until the checklist is met.
- **Legacy code**
  - Some existing modules predate this doc. Future work on those modules
    should bring them up to this standard incrementally.

Any time a checklist item is consciously skipped (e.g. no golden case exists
yet), that must be called out explicitly so future agents and humans are
aware of the gap.
