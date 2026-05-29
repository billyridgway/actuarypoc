# Project Health Workflow (Design) – Insurance Illustration Platform

> Status: Initial CLI implemented as `python -m actuarypoc.tools.health_check`
> plus manual checks. This document describes how an OpenClaw agent or
> developer can answer: "Is the insurance illustration platform healthy right
> now?" using the CLI and (optionally) lower-level tools (GitHub, kubectl,
> curl, etc.).

The goal is a repeatable checklist that surfaces:

- whether code is building and images are being published
- whether cluster components are up
- whether dependencies (MinIO, Postgres) are reachable
- whether operator + CRDs are behaving
- whether the UI/API can serve at least one known projection
- whether there are recent failures that need attention.

The workflow is designed for:

- humans running commands from the workspace
- OpenClaw agents that can invoke
  `python -m actuarypoc.tools.health_check`, `kubectl`, `curl`, and
  GitHub APIs.

---

## 1. Overall Health Status Levels

The final report should classify platform health into one of:

- **HEALTHY** – all configured critical checks pass; no recent blocking
  failures.
- **DEGRADED** – all configured critical checks pass, but one or more
  non-critical checks fail (e.g. recent Job failures, a flaky dependency).
- **FAILED** – one or more configured critical platform checks fail
  (e.g. pods not Ready, operator unavailable, CRD missing, MinIO
  unreachable when configured).
- **UNKNOWN** – the CLI cannot determine platform health because required
  local tooling or configuration is missing (e.g. `kubectl` not found,
  kubeconfig path invalid, MinIO env vars missing for a MinIO check).

The workflow below defines which checks contribute to each level. The
implemented CLI (`python -m actuarypoc.tools.health_check`) follows these
semantics when computing the overall status.

---

## 2. GitHub Actions Status (Both Repos)

**Repos:**

- `actuarypoc`
- `illustration-operator`

**Checks:**

1. Latest workflow runs on `main` for both repos succeed.
2. No recent repeated failures on `main` (e.g. 3+ consecutive failures).

**Example commands:**

- Using `gh` CLI (if available):

  ```sh
  gh run list --repo <owner>/actuarypoc --branch main --limit 5
  gh run list --repo <owner>/illustration-operator --branch main --limit 5
  ```

- Or via GitHub web UI (manually) when `gh` is not available.

**Health impact:**

- If latest `main` build for either repo is failing → **Degraded**.
- If builds have been red for several runs and no fix is in progress → push
  toward **Failed** for development readiness.

The health report should include:

- The status of the latest build for each repo (success/failure + timestamp).
- A note if recent history suggests instability.

It should **not** include:

- full logs
- secrets or internal URLs from CI.

---

## 3. k3s Workloads

**Namespace:** `illustrations-poc` (primary), plus `minio-system` for MinIO.

**Checks:**

1. All critical Deployments have at least 1 Ready pod:
   - `illustration-operator`
   - `projection-ui`
   - Postgres (if used)
2. No critical pods in `CrashLoopBackOff` or `Error`.

**Example commands:**

```sh
KUBECONFIG=.kube/pi-k3s.yaml kubectl get pods -n illustrations-poc
KUBECONFIG=.kube/pi-k3s.yaml kubectl get pods -n minio-system
```

Or via the health CLI (which internally shells out to `kubectl`):

```sh
python -m actuarypoc.tools.health_check \
  --kubeconfig .kube/pi-k3s.yaml \
  --namespace illustrations-poc \
  --minio-namespace minio-system \
  --ui-url http://192.168.50.251:30301/health
```

**Health impact:**

- If `illustration-operator` or `projection-ui` pods are not Ready → at least
  **Degraded**, and **Failed** if they remain down.
- If Postgres is down (when actively used for runs) → **Degraded**.

The report should list:

- pod names, Ready status, and high-level reason if not Ready.

It should **not** include:

- full pod logs
- any sensitive env var values.

---

## 4. Illustration Operator Health & CRDs

**Checks:**

1. CRD `illustrationprojects.illustrations.poc` is present and Established.

   ```sh
   KUBECONFIG=.kube/pi-k3s.yaml kubectl get crd illustrationprojects.illustrations.poc
   ```

2. `illustration-operator` Deployment is Ready.

   ```sh
   KUBECONFIG=.kube/pi-k3s.yaml kubectl get deploy illustration-operator -n illustrations-poc
   ```

3. No obvious operator errors in recent logs (brief sample only):

   ```sh
   KUBECONFIG=.kube/pi-k3s.yaml kubectl logs -n illustrations-poc deploy/illustration-operator --tail=50
   ```

4. `IllustrationProject` resources are in reasonable states:
   - No projects stuck in `Pending`/`Running` for an unusually long time.
   - No large number of `Failed` projects without investigation.

   ```sh
   KUBECONFIG=.kube/pi-k3s.yaml kubectl get illustrationprojects.illustrations.poc -n illustrations-poc
   ```

**Health impact:**

- Missing CRD or non-Ready operator → **Failed**.
- Repeated or unexplained failures in `IllustrationProject.status.phase` →
  **Degraded**.

The report should summarize:

- Operator Ready status
- Count of `IllustrationProject`s by phase (Pending/Running/Succeeded/Failed).

It should **not** list:

- the full contents of CRDs beyond phase and key MinIO object refs.

---

## 5. MinIO and Postgres Availability

### MinIO

**Checks:**

- MinIO service reachable from the cluster and from the workspace.
- Simple list operation on the configured bucket (`illuminet`) succeeds.

**Example commands:**

- Cluster-internal (via a pod):
  - Use an existing pod (e.g. `projection-ui`) to run a quick Python snippet
    that uses `get_minio_client()` to list objects under a small prefix.

- From the workspace (if networking allows):

  ```sh
  curl -v http://192.168.50.101:32619/minio/health/ready  # example NodePort/URL
  ```

**Health impact:**

- MinIO not reachable or failing health endpoint → **Failed** (platform
  cannot run projections reliably).

### Postgres (if used)

**Checks:**

- Postgres service in `illustrations-poc` namespace is Ready.
- Simple connection test from a pod using `POSTGRES_DSN` succeeds.

**Example commands:**

```sh
KUBECONFIG=.kube/pi-k3s.yaml kubectl get svc postgres -n illustrations-poc
```

For a deeper check, a small script/pod could attempt a trivial query, but the
workflow document will only require a basic readiness assessment.

**Health impact:**

- If Postgres is used for run history and is down → **Degraded**.
- If not actively used, may be noted but not considered critical.

The report should record:

- whether MinIO and Postgres appear reachable and Ready.

It should **not** expose:

- connection strings
- credentials
- query results with any business data.

---

## 6. Projection UI/API Health

**Checks:**

1. `projection-ui` health endpoint responds:

   ```sh
   curl -sS http://<node-ip>:30301/health  # adjust IP/port to environment
   ```

   Expect `{"status":"ok"}`.

2. UI and API respond at a basic level:

   - `/ui` should return a 200 or 307 redirect into `/web?key=...`.
   - `/web?key=...` should return a valid HTML shell (React app entry).

3. RunDetail API responds for a known projection object:

   ```sh
   curl -sS "http://<node-ip>:30301/api/run-detail?key=projections/...json"
   ```

   The response should be JSON with expected top-level fields
   (`run`, `trust_status`, `policy_input`, etc.).

**Health impact:**

- `/health` failing → **Failed**.
- `/api/run-detail` failing for a known, recent projection → **Degraded** or
  **Failed** depending on cause.

The report should note:

- basic status of `/health`, `/ui`, and `/api/run-detail`.

It should **not** include:

- full RunDetail payloads
- any raw policy input or projection arrays; only high-level success/failure
  and, at most, anonymized keys.

---

## 7. Recent Jobs and Smoke Test Projection

### Recent Job Failures

**Checks:**

- Inspect Jobs in `illustrations-poc` namespace for recent `Failed` states:

  ```sh
  KUBECONFIG=.kube/pi-k3s.yaml kubectl get jobs -n illustrations-poc
  ```

- For each failed Job, sample its events/logs briefly to understand whether
  failures are expected (e.g. old test jobs) or current regressions.

**Health impact:**

- Isolated historical failures → note, but may still be **Healthy**.
- Recent or repeated failures of key Jobs (assumptions or illustration Jobs)
  → **Degraded**.

### Smoke Test Projection

If a known, stable `IllustrationProject` and projection object exist
(e.g. `p12trf-serff-demo`):

1. Confirm the CR exists and is in `Succeeded` (or reasonable) phase.
2. Confirm its `status.projectionObject` points to a MinIO object.
3. Call RunDetail for that projection object as in §6.

**Health impact:**

- If the smoke test run cannot be reconciled, written to MinIO, and served
  via `/api/run-detail` → **Failed**.

The report should summarize:

- count and nature of recent failed Jobs
- status of the designated smoke test project (name, phase only).

---

## 8. Putting It All Together – Health Report Format

A final health report (for humans or OpenClaw agents) should look roughly
like. The `health_check` CLI emits a similar summary by default:

```text
Overall status: HEALTHY | DEGRADED | FAILED

GitHub:
  - actuarypoc: main build SUCCESS at 2026-05-29T...
  - illustration-operator: main build SUCCESS at 2026-05-29T...

Cluster (illustrations-poc):
  - illustration-operator: 1/1 Ready
  - projection-ui: 1/1 Ready
  - postgres: 1/1 Ready

CRDs & Projects:
  - illustrationprojects.illustrations.poc: Established
  - IllustrationProjects: 2 Succeeded, 0 Running, 0 Failed

MinIO & DB:
  - MinIO: reachable (health endpoint OK)
  - Postgres: reachable (service Ready)

UI/API:
  - /health: OK
  - /ui: 307 → /web, OK
  - /api/run-detail for smoke test: 200 OK

Jobs & Smoke Test:
  - Jobs: 0 Failed in last N minutes
  - Smoke test project p12trf-serff-demo: phase Succeeded
```

**Things to include:**

- Status and timestamps of key components
- Counts and phases (Succeeded/Running/Failed) for CRDs and Jobs
- Short notes on any degraded dependencies

**Things not to include:**

- Secrets (tokens, DSNs, passwords)
- Raw PAS exports or projection arrays
- Detailed error messages that might leak internal paths or data; instead,
  summarize them and, if needed, point to where logs can be found.

This design is intended to be a blueprint for a future `health_check` CLI or
OpenClaw workflow, not an implementation. Any code that arises from it should
be careful to follow the same constraints on what is collected and reported.
