# AGENTS.md – ActuaryPOC Repo Operator Rules

This file defines how the local OpenClaw agent should behave when working in
this repo. Treat it as the repo’s operating manual, not just a note.

## 0. Role of this repo

`actuarypoc` is the **projection + assumptions backend**:

- Policy DSL + projection engine
- Assumption set extraction/registry
- MinIO connectors (PAS, actuarial tables, CRM, rates)
- Run-detail API and projection UI (React + FastAPI)

The Raspberry Pi k3s cluster with MinIO is the **default dev environment**.

---

## 1. Repo → Cluster development loop

When changing code in this repo, prefer the full loop instead of ad‑hoc steps:

1. **Edit + format + unit tests (local)**
   - Modify Python / TS files.
   - Run focused tests:
     - `python -m pytest src/actuarypoc/tests/test_*.py` (or narrower).
   - For UI only: `cd web && npm test` (when tests exist).
2. **Build container via GitHub Actions**
   - Commit & push to `main` (or an agreed feature branch).
   - Let `.github/workflows/build-and-push.yml` build
     `ghcr.io/<owner>/actuarypoc:<branch>` (not from inside the cluster).
3. **Deploy to k3s**
   - Update k8s manifests in this repo **only** (no in‑cluster hacking):
     - `k8s/projection-ui.yaml` for the UI
     - Jobs/Deployments that run `actuarypoc` CLIs.
   - Apply from workspace root (or repo root) using the provided kubeconfig.
4. **Validate against MinIO**
   - Confirm projection objects exist under `projections/` in MinIO.
   - Hit the run‑detail API and/or UI for at least one run.
5. **Summarize results**
   - Capture:
     - What changed
     - Which projection object key was validated
     - Any warnings or trust concerns raised by the run‑detail API
   - Write a short note to the chat + (optionally) to a repo doc / ADR.

When time/CPU is tight, you can temporarily skip a step, but you should say so
explicitly in the chat and in commit messages.

---

## 2. Actuarial calculation safety rules

**Never change actuarial calculation logic without all of these:**

1. **Unit tests**
   - Add or update tests under `src/actuarypoc/tests/` that exercise the
     changed path (e.g. premium lookup, mortality surfaces, reserve formulas).
2. **Golden test case**
   - For term products like P12TRF, keep a golden JSON under
     `src/actuarypoc/tests/golden/<product>/` and assert on it from tests.
   - When behavior changes intentionally, update golden files and document why.
3. **Source / audit note**
   - Document the source of the change: SERFF filing, actuarial memo, grid
     extract, etc.
   - Put a short note in either:
     - a relevant doc under `docs/`, or
     - a comment in the DSL / config pointing to the doc/object key.
4. **Warning behavior when assumptions are missing**
   - If an assumption set, table, or doc is missing, **never silently fall
     back** to a flat or arbitrary default.
   - Emit a structured warning via the projection summary so the run‑detail
     API + UI can surface it.

If you cannot satisfy one of the four (e.g. no golden data available yet), you
must:

- call it out in the PR / commit message, and
- add a **TODO with owner + date** near the missing piece.

---

## 3. Kubernetes / operator integration rules

When changes in this repo affect Kubernetes behavior (Jobs, UI Deployment,
operator runner image, etc.):

1. **Update CRD types (if applicable)**
   - If a change impacts `IllustrationProject` or related CRDs, update
     Go types in the **illustration-operator** repo, not here.
   - This repo’s responsibility is: CLI flags, env vars, and paths that the
     operator expects.
2. **Keep image contract stable or versioned**
   - When you change CLIs used by the operator (e.g. `project-minio`,
     `extract-assumptions-minio`), either:
     - preserve existing flags/env semantics, or
     - bump a clearly named alternative and coordinate with the operator.
3. **Add / update sample YAML**
   - If you add a new CLI or change behavior that affects Kubernetes Jobs,
     update the relevant samples under `k8s/` or add new ones.
4. **Use `k8s/projection-ui.yaml` as the truth for the UI Deployment**
   - The cluster’s `projection-ui` deployment should match this file.
   - Never hand‑edit the Deployment in‑cluster without back‑propagating
     changes to `k8s/projection-ui.yaml`.

---

## 4. Projection UI & API rules

- React UI (`web/`) and FastAPI server (`src/actuarypoc/ui/server.py`) are
  treated as **one unit**:
  - Any breaking change in run‑detail JSON shape must update:
    - `run-detail.types.ts`
    - `RunDetailPage.tsx`
    - Tests under `src/actuarypoc/tests/test_run_detail_api.py`.
- The UI should always:
  - show which assumption set + docs were used,
  - surface any trust warnings,
  - provide at least a minimal projection graph (cash value + death benefit).

---

## 5. Trust / audit loop responsibilities

When working in this repo, the agent should:

- Prefer changes that **improve explainability and reproducibility**:
  - clearer DSL metadata (`source_documents`, `premium_table` config),
  - better audit objects (MinIO keys, counts, timestamps),
  - richer run‑detail output for the UI.
- When in doubt, ask: “Can this projection be explained and reproduced?” and
  adjust code/docs accordingly.

---

## 6. Product‑management support

- Treat Telegram / OpenClaw messages as a lightweight backlog:
  - When asked, draft GitHub issues for this repo with:
    - problem statement
    - acceptance criteria
    - minimal test plan.
- Keep issue titles concrete (e.g. “Wire P12TRF premium grid into run-detail
  API and UI”).
