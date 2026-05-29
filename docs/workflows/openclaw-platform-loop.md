# OpenClaw Platform Loop – Standard Runbook

> Status: **Active runbook.** This document describes how an OpenClaw agent or
> developer should use the project health check as the **first step** before
> doing any platform work that touches the live dev cluster.

The goal is to make platform changes in a disciplined loop:

```text
health check
→ summarize status
→ inspect failed/degraded components only
→ propose a fix
→ make the smallest change
→ run tests
→ rerun health check
→ summarize before/after
```

This applies to changes that touch:

- k3s manifests (e.g. `k8s/*.yaml`, operator `config/` in the other repo)
- operator wiring (env vars, Job specs, product wiring)
- MinIO prefixes (ingestion paths, projection outputs)
- projection Jobs (how `project-minio` is executed)
- UI/API deployment (projection UI Deployment/Service)
- health check code itself (`actuarypoc.tools.health_check`)

For purely local refactors or doc-only changes you can skip the k3s parts,
but any cluster/MinIO/Job/Deployment work should follow this loop.

---

## 1. Step 1 – Health Check (Before Changes)

From the repo root, with the virtualenv set up (see `docs/dev-setup.md`):

```bash
cd actuarypoc
source .venv/bin/activate

python -m actuarypoc.tools.health_check \
  --kubeconfig ../.kube/pi-k3s.yaml \
  --namespace illustrations-poc \
  --minio-namespace minio-system \
  --ui-url http://192.168.50.251:30301/health
```

Or JSON output for agents/tools:

```bash
python -m actuarypoc.tools.health_check \
  --kubeconfig ../.kube/pi-k3s.yaml \
  --namespace illustrations-poc \
  --minio-namespace minio-system \
  --ui-url http://192.168.50.251:30301/health \
  --json
```

**OpenClaw rule:**

> Before *any* change that touches k3s manifests, operator wiring, MinIO
> prefixes, projection Jobs, UI/API deployment, or health check code,
> OpenClaw should run the health check and capture a short summary.

---

## 2. Step 2 – Summarize Status

Based on the health check output, summarize at a high level:

- Overall status: `HEALTHY` / `DEGRADED` / `FAILED` / `UNKNOWN`.
- Any **critical** failures (kubectl, pods, operator deployment, CRD).
- Any **non-critical** degradations (failed Jobs, UI health, MinIO issues).

OpenClaw should write a concise summary in chat. When status is
`UNKNOWN`, it must **not** describe the platform as failed. Instead it
should say something like:

> Platform status is unknown from this environment because required
> local tooling or configuration is missing.

Then it should list the missing items based on check details, such as:

- `kubectl` not found
- kubeconfig path missing/invalid
- MinIO env vars (e.g. `MINIO_ENDPOINT`) missing

For non-UNKNOWN runs, a typical summary looks like:

```text
Overall: DEGRADED
- kubectl_available: OK
- pods_illustrations-poc: OK
- pods_minio-system: OK
- illustration_operator_deploy: OK
- illustrationproject_crd: OK
- illustrationproject_phases: FAIL (non-critical) – 1 Failed project
- jobs_failed: FAIL (non-critical) – 2 failed Jobs
- projection_ui_health: OK
- minio_health: OK
```

This becomes the "before" snapshot for any work.

---

## 3. Step 3 – Inspect Failed/Degraded Components Only

Do **not** inspect every component on every run. Focus on what the health
check flagged:

- If `illustration_operator_deploy` is failing:
  - inspect that Deployment and its pods/logs.
- If `jobs_failed` is failing:
  - inspect those specific Jobs and determine if they are:
    - old/expected (can be ignored or cleaned), or
    - current regressions.
- If `projection_ui_health` is failing:
  - inspect the `projection-ui` Deployment and logs.
- If `pods_...` checks are failing:
  - focus on which pods are not Ready.

OpenClaw should avoid diving into unrelated services unless explicitly
requested.

---

## 4. Step 4 – Propose a Fix

After inspecting the degraded components, propose a **minimal** fix:

- Describe the intended change:
  - e.g. "Update `k8s/projection-ui.yaml` image tag to the latest
    `actuarypoc:main` image."
- Call out any risks:
  - e.g. "This will restart the projection UI but should not affect Jobs."
- Tie it back to the health findings:
  - e.g. "Fix addresses `projection_ui_health` failing with HTTP 500."

Only after you’ve proposed the fix should you proceed to modify manifests or
config.

---

## 5. Step 5 – Make the Smallest Change

Apply the minimal change required to address the degraded component:

- For k3s manifests in this repo:
  - edit `k8s/*.yaml` (or the operator repo manifests), *not* in-cluster
    YAML directly.
  - then apply via `kubectl apply` from the workspace.
- For operator wiring:
  - update `config/products.yaml` in the operator repo or equivalent.
- For MinIO prefixes:
  - adjust ingestion/projection code or configuration, but **do not** rename
    large swaths of prefixes without a clear migration plan.
- For the health check code:
  - update `actuarypoc.tools.health_check` and re-run its unit tests.

Whatever the change, keep it small and well-described.

---

## 6. Step 6 – Run Tests

Before re-running the health check, run relevant tests locally:

- Full suite (when appropriate):

  ```bash
  cd actuarypoc
  source .venv/bin/activate
  pytest -q
  ```

- Or focused tests:

  ```bash
  pytest src/actuarypoc/tests/test_health_check.py -q
  ```

In the operator repo, use:

```bash
cd illustration-operator
# assuming Go tooling is installed
go test ./...
```

OpenClaw should try to prefer **targeted tests** that exercise the changed
area before running the full suite, unless the change is large.

---

## 7. Step 7 – Rerun Health Check (After Changes)

Repeat the health check with the same command as in Step 1:

```bash
cd actuarypoc
source .venv/bin/activate

python -m actuarypoc.tools.health_check \
  --kubeconfig ../.kube/pi-k3s.yaml \
  --namespace illustrations-poc \
  --minio-namespace minio-system \
  --ui-url http://192.168.50.251:30301/health
```

Compare the new summary to the previous one:

- Did the degraded/failed checks move to OK?
- Did any new failures appear?

OpenClaw should flag if:

- the targeted issue persists, or
- the change fixed one area but broke another.

---

## 8. Step 8 – Summarize Before/After

Finally, OpenClaw should provide a concise before/after summary in chat for
any platform-level work:

- Before:
  - Overall status, list of failing/degraded checks.
- Change:
  - One or two sentences about what was changed (files, manifests, wiring).
- After:
  - Overall status, list of remaining failing/degraded checks (if any).

Example:

```text
Before: DEGRADED
- jobs_failed: FAIL – 2 failed Jobs (import-assumption-...)

Change:
- Cleaned up old import-assumption Jobs and reran current Job via
  kubectl apply -f config/samples/import-assumption-....yaml.

After: HEALTHY
- jobs_failed: OK – no failed Jobs in illustrations-poc
```

This closes the loop and makes it easy to understand what was done and why.

---

## 9. When to Always Use This Loop

OpenClaw (or any agent) should run the **before/after** health check loop
whenever a task involves:

- **k3s manifests**
  - `actuarypoc/k8s/*.yaml`
  - operator manifests in the `illustration-operator` repo
- **operator wiring**
  - changes to `config/products.yaml`
  - new env vars / Job args for illustration or assumptions Jobs
- **MinIO prefixes**
  - changes to ingestion prefixes (`pas_export/`, `actuarial_tables/`, etc.)
  - changes to projection/audit object naming (`projections/`, `audit/`)
- **projection Jobs**
  - how `project-minio` is invoked from Jobs
  - Job templates that control projection behavior
- **UI/API deployment**
  - `projection-ui` Deployment and Service
  - image tags and startup commands for the projection UI/API
- **health check code**
  - modifications to `actuarypoc.tools.health_check`
  - changes to what checks are considered critical vs non-critical.

For tasks that are entirely local and do not touch cluster state (e.g. a small
pure-Python refactor with unit tests only), running the full k3s health loop
is optional.

When the health CLI returns an overall status of `UNKNOWN`, OpenClaw
should **not** treat the platform as failed. Instead it should:

- Say explicitly: "Platform status is unknown from this environment
  because required local tooling or configuration is missing."
- List which pieces appear to be missing (e.g. `kubectl` not found,
  kubeconfig missing, MinIO env vars missing) based on the individual
  check messages.

For cluster-level changes in this situation, OpenClaw should either:

- Ask you to run the health CLI from a workstation with kubectl/MinIO
  access and share the results, **or**
- Proceed only with local code/docs work and clearly state that cluster
  validation was not performed.
