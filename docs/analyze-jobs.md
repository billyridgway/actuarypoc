# Analyze jobs: analysis as a server-side background job

## Why

On Oct 26, 2026 a 13-document workspace (ws-0e4bd9b4) could not be
analyzed at all: the analysis ran *inside* the `POST /analyze` HTTP
request, the pipeline takes many minutes at that size, and when the
browser gave up, the analysis died with the request — unrecorded. The
workspace sat in `ready_for_analysis` limbo with no error anywhere,
and the partial artifacts the run had written (document records, the
mechanics file) were orphaned. A second, older wart compounded it: the
commit step's existence check once discarded a completed 215-second
analysis on a single transient S3 `NoSuchKey`.

Analysis is therefore a **background job owned by the server**, not a
long request.

## The contract

`POST /api/workspaces/{id}/analyze`:

- validates synchronously (404 unknown workspace, 400 no documents),
- starts the job (or reports the one already running — see dedupe),
- returns **202** immediately with
  `{workspace, analysisJob, started}`.

The analysis itself runs on a daemon thread in the app process,
detached from any request. Progress and the outcome are read from the
workspace record: `GET /api/workspaces/{id}` → `workspace.analysisJob`
(also present in the start response). There is no separate job store
and no job id to track beyond the workspace.

## State: where it lives and its shape

The job record lives on the workspace record itself —
`workspaces/{id}/workspace.json` → `analysis_job` — in the object
store, like all workspace state. Its shape is fixed:

```json
{
  "state": "running" | "succeeded" | "failed",
  "phase": "starting" | "reading_documents" | "extracting_mechanics"
         | "building_snapshot" | "extracting_slices" | "finalizing" | null,
  "startedAt": "<iso8601>",
  "finishedAt": "<iso8601>" | null,
  "error": "<plain-language failure>" | null,
  "runId": "<12 hex>"
}
```

Writes go through `update_workspace_analysis_job`
(`storage/workspace_store.py`), a read-modify-write of the workspace
record with bounded retries on transient store errors. Phase writes
are best-effort and carry the run's `runId`, so a stale thread can
never overwrite a newer run's state; the terminal write (succeeded /
failed, with `finishedAt`) is the one that matters.

The workspace `status` moves with the job for a workspace that has
never completed an analysis: `analyzing` while running,
`analysis_failed` on failure, `analyzed` on success. A failed
*re*-analysis of an already-analyzed workspace leaves `status` at
`analyzed` (the good snapshot survives); the failure is on the job
record, where the UI shows it.

## Disconnect semantics

Starting a job is the last thing the client must do. After the 202:

- Browser timeout, disconnect, refresh, or the user navigating away
  have **no effect** on the job. (Uvicorn cancelling the request
  handler cannot reach the detached thread.)
- A page loaded mid-run reads `analysisJob.state == "running"` from
  the workspace record and resumes showing live progress — the state
  is the server's, not the page's.

## Dedupe and orphaned jobs

A second `POST` while a job is running starts nothing and reports the
running job (`started: false`, same `runId`). Two guards cooperate:

1. the in-process registry of live job threads, and
2. the durable record: a `running` record younger than **45 minutes**
   is believed (it may belong to another process after a rolling
   restart).

A `running` record older than that is an orphan — its process died
mid-analysis. The next `POST` closes it out (`failed`, "the previous
analysis was interrupted…") and starts a fresh job, so a pod restart
can never wedge a workspace in `analyzing` forever. The 45-minute
bound is deliberately far beyond observed analysis durations
(minutes, even for the 13-document set).

## Failure recording

Any exception in the pipeline ends the job as `failed` with the error
recorded on the workspace (`TypeError: …` / the HTTP detail), plus
`analysis_failed` status for never-analyzed workspaces. The failure
is therefore visible in every later read of the workspace — the
silent-limbo outcome that motivated this change is structurally
impossible: a started job always ends with a recorded terminal state.

## Commit resilience

The analyze pipeline's commits — both `store_workspace_executable_mechanics`
writes and the final `update_workspace_analysis` — go through a
bounded retry (4 attempts, exponential backoff from 0.25s) that
absorbs transient object-store errors: S3 codes such as `NoSuchKey`,
`SlowDown`, 5xx, and connection/timeout errors, plus the existence
check's `ValueError("workspace does not exist")` surfacing a transient
missing read. Non-transient errors propagate immediately; exhausted
retries preserve the previous semantics (the final commit returning
`None` still surfaces as the caller's 503). The retry is scoped to
the analyze pipeline's commit points; the store layer itself is
unchanged (its only addition is the job-state writer above).

## UI

- The workspace page's Analyze Product card starts the job, then
  polls the workspace record every ~3s while a job runs, showing the
  phase and elapsed time and noting that leaving the page is safe.
  On success the page reloads into the analyzed workbench; on failure
  the card shows the recorded error in plain language and offers a
  re-run. Helpers live in `web/analyzeJob.ts`.
- The product page's re-run actions use the same start + poll helper.

## Tests

`tests/test_analyze_jobs.py`: prompt return + commit after the client
leaves, duplicate-start dedupe, failure recording (fresh and
re-analysis), orphan restart, fresh-record dedupe, commit retries
(transient `NoSuchKey`, the existence-check `ValueError`, a transient
missing final read, and no-retry on real errors), and the store-level
job-state round-trip. The pre-existing route test in
`tests/test_workspace_sources.py` polls the job like the browser does
and asserts the same committed end state as before.
