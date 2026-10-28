// Background analysis jobs (docs/analyze-jobs.md).
//
// POST /api/workspaces/{id}/analyze starts the analysis on the server
// and returns promptly; the job's state lives on the workspace record
// (analysisJob) and is read back with the normal workspace GET. These
// helpers are the one place the web app talks to that contract.

export interface AnalysisJobProgress {
  stage?: string | null;
  documentsDone?: number | null;
  documentsTotal?: number | null;
  pass?: string | null;
  unitsDone?: number | null;
  unitsTotal?: number | null;
}

export interface AnalysisJobState {
  state?: string | null; // "running" | "succeeded" | "failed"
  phase?: string | null;
  // Sub-progress within a phase (slice extraction): a human-readable
  // detail line plus the counters behind it. Absent outside the
  // phases that report it, and cleared when the job finishes.
  phaseDetail?: string | null;
  phaseProgress?: AnalysisJobProgress | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  error?: string | null;
  runId?: string | null;
}

export const ANALYSIS_PHASE_LABELS: Record<string, string> = {
  starting: "Starting",
  reading_documents: "Reading documents",
  extracting_mechanics: "Extracting mechanics",
  building_snapshot: "Building the product snapshot",
  extracting_slices: "Extracting document slices",
  holistic_review: "Holistic review — self-checking the suggestions",
  finalizing: "Finalizing the analysis",
};

export const analysisPhaseLabel = (phase?: string | null): string =>
  (phase && ANALYSIS_PHASE_LABELS[phase]) || "Working";

export interface AnalyzeStartResponse {
  workspace: any;
  analysisJob: AnalysisJobState | null;
  started: boolean;
}

export async function startWorkspaceAnalysis(
  workspaceId: string,
): Promise<AnalyzeStartResponse> {
  const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/analyze`, {
    method: "POST",
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || `Analyze failed with status ${resp.status}`);
  }
  return (await resp.json()) as AnalyzeStartResponse;
}

export interface WorkspaceViewBody {
  workspace: any;
  documents?: any[];
  sources?: any[];
  snapshot: any | null;
}

/**
 * Poll the workspace record until the background analysis finishes.
 * Resolves with the final workspace GET body on success; rejects with
 * the recorded error when the job failed, or with a "still running"
 * note when the (generous) wait budget runs out — the job itself keeps
 * running on the server either way.
 */
export async function waitForWorkspaceAnalysis(
  workspaceId: string,
  options: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<WorkspaceViewBody> {
  const intervalMs = options.intervalMs ?? 2500;
  const timeoutMs = options.timeoutMs ?? 30 * 60 * 1000;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(text || `Failed to load workspace (HTTP ${resp.status})`);
    }
    const body = (await resp.json()) as WorkspaceViewBody;
    const job: AnalysisJobState | null = body.workspace?.analysisJob ?? null;
    if (job?.state === "failed") {
      throw new Error(job.error || "Analysis failed.");
    }
    if (job?.state === "succeeded" || (!job && body.workspace?.status === "analyzed")) {
      return body;
    }
    if (Date.now() > deadline) {
      throw new Error(
        "Analysis is still running on the server. It will finish on its own — reload this page in a while to see the result.",
      );
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
