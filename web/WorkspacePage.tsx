import React from "react";
import { ProductWorkspacePage } from "./ProductWorkspacePage";
import { WorkbenchPage } from "./WorkbenchPage";
import {
  analysisPhaseLabel,
  startWorkspaceAnalysis,
  type AnalysisJobState,
} from "./analyzeJob";

interface WorkspaceMeta {
  id: string;
  status: string;
  documentCount: number;
  createdAt?: string;
  updatedAt?: string;
  analysisJob?: AnalysisJobState | null;
}

interface WorkspaceDocument {
  id?: number | string;
  kind?: string;
  description?: string | null;
  objectPath?: string | null;
  createdAt?: string | null;
  filingId?: string | null;
}

interface WorkspaceResponse {
  workspace: WorkspaceMeta & {
    inferredProductName?: string | null;
    inferredProductType?: string | null;
    inferredCarrier?: string | null;
  };
  documents: WorkspaceDocument[];
  snapshot: any | null;
}

const formatWorkspaceStatus = (value?: string | null): string => {
  const v = (value || "").toLowerCase();
  switch (v) {
    case "waiting_for_documents":
      return "Waiting For Documents";
    case "ready_for_analysis":
      return "Ready For Analysis";
    case "analyzing":
      return "Analyzing";
    case "analyzed":
      return "Analyzed";
    case "analysis_failed":
      return "Analysis Failed";
    default:
      return "Unknown";
  }
};

export const WorkspacePage: React.FC<{ workspaceId: string; view?: string }> = ({ workspaceId, view }) => {
  const [data, setData] = React.useState<WorkspaceResponse | null>(null);
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);
  const [uploading, setUploading] = React.useState<boolean>(false);
  const [uploadMessage, setUploadMessage] = React.useState<string | null>(null);
  const [analyzing, setAnalyzing] = React.useState<boolean>(false);
  const [deleting, setDeleting] = React.useState<boolean>(false);

  // `quiet` polls refresh the workspace without flashing the page's
  // loading state or clearing a displayed error.
  const loadWorkspace = React.useCallback(
    async (quiet = false) => {
      try {
        if (!quiet) {
          setLoading(true);
          setError(null);
        }
        const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text || `HTTP ${resp.status}`);
        }
        const body: WorkspaceResponse = await resp.json();
        setData(body);
      } catch (err: any) {
        if (!quiet) setError(err?.message || "Failed to load workspace.");
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [workspaceId],
  );

  React.useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  const workspace = data?.workspace;
  const documents = data?.documents ?? [];
  const snapshot = data?.snapshot;
  const hasSnapshot = !!snapshot && workspace?.status === "analyzed";

  // Background analysis job state (recorded on the workspace itself):
  // while it runs, this page polls quietly — a refresh mid-run lands
  // right back on the live state, because the state is the server's,
  // not the page's.
  const job = workspace?.analysisJob ?? null;
  const jobRunning = job?.state === "running";
  const [nowMs, setNowMs] = React.useState(() => Date.now());

  React.useEffect(() => {
    if (!jobRunning) return;
    const timer = window.setInterval(() => {
      void loadWorkspace(true);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [jobRunning, loadWorkspace]);

  React.useEffect(() => {
    if (!jobRunning) return;
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [jobRunning]);

  const elapsedLabel = React.useMemo(() => {
    if (!job?.startedAt) return null;
    const started = Date.parse(job.startedAt);
    if (Number.isNaN(started)) return null;
    const secs = Math.max(0, Math.floor((nowMs - started) / 1000));
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return m > 0 ? `${m}:${String(s).padStart(2, "0")}` : `${s}s`;
  }, [job?.startedAt, nowMs]);

  if (hasSnapshot && snapshot) {
    // Once analysis has populated the snapshot and the workspace has
    // reached the analyzed state, the actuary workbench is the
    // workspace's main surface. The old deep links keep working:
    // view=details lands on the bench's Filing tab, view=map /
    // view=logic land on the Ledger tab with its calculation-map
    // debugging detail expanded — the graph is no longer a peer page.
    // The full filing analysis (the former details page) remains
    // reachable as its own view=analysis.
    return view === "analysis" ? (
      <ProductWorkspacePage snapshot={snapshot} workspaceId={workspaceId} />
    ) : (
      <WorkbenchPage
        snapshot={snapshot}
        workspaceId={workspaceId}
        expandMap={view === "map" || view === "logic"}
        initialTab={view === "details" ? "filing" : "ledger"}
      />
    );
  }

  const statusLabel = formatWorkspaceStatus(workspace?.status);
  const docCount = workspace?.documentCount ?? 0;
  const analyzeDisabled = docCount <= 0 || !!loading || !!analyzing || jobRunning;

  const handleFileChange: React.ChangeEventHandler<HTMLInputElement> = async (event) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    setUploading(true);
    setUploadMessage(null);
    try {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/documents`, {
          method: "POST",
          body: form,
        });
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text || `Upload failed with status ${resp.status}`);
        }
      }
      setUploadMessage("Uploaded. Analyze Product will use these documents in the next run.");
      await loadWorkspace();
    } catch (e: any) {
      setUploadMessage(e?.message || "Upload failed.");
    } finally {
      setUploading(false);
      if (event.target) event.target.value = "";
    }
  };

  const handleAnalyzeClick = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      // Starts the server-side job and returns promptly; the recorded
      // job state (picked up here, then by the poller) drives the card
      // until the analysis lands.
      const body = await startWorkspaceAnalysis(workspaceId);
      setData((prev) => (prev ? { ...prev, workspace: body.workspace } : prev));
      await loadWorkspace(true);
    } catch (e: any) {
      setError(e?.message || "Analysis failed.");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleDeleteWorkspace = async () => {
    if (!workspace) return;
    const confirmed = window.confirm(
      "This will permanently delete the workspace and uploaded documents from object storage. This cannot be undone.",
    );
    if (!confirmed) return;

    setDeleting(true);
    setError(null);
    try {
      const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`, {
        method: "DELETE",
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Delete failed with status ${resp.status}`);
      }

      // On success, return to the main catalog view.
      window.location.href = "/web";
    } catch (e: any) {
      setError(e?.message || "Failed to delete workspace.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="home-page">
      <section className="card home-card">
        <h2>Workspace</h2>
        {loading && <p className="muted">Loading workspace…</p>}
        {error && !loading && <p className="error">{error}</p>}
        {workspace && (
          <table className="kv-table">
            <tbody>
              <tr>
                <th>Workspace ID</th>
                <td>{workspace.id}</td>
              </tr>
              <tr>
                <th>Status</th>
                <td>{statusLabel}</td>
              </tr>
              <tr>
                <th>Documents</th>
                <td>{docCount}</td>
              </tr>
            </tbody>
          </table>
        )}
        {workspace && docCount === 0 && (
          <p className="muted">Upload one or more filing documents to begin.</p>
        )}
      </section>

      <section className="card home-card">
        <h2>Upload documents</h2>
        <p className="muted">
          Upload one or more filing documents for this workspace. The AI pipeline will infer product details from these
          documents when you analyze the product.
        </p>
        {uploadMessage && <p className="muted">{uploadMessage}</p>}
        <label className="button button-secondary">
          {uploading ? "Uploading…" : "Upload document"}
          <input
            type="file"
            multiple
            style={{ display: "none" }}
            disabled={uploading}
            onChange={handleFileChange}
          />
        </label>
      </section>

      <section className="card home-card">
        <h2>Uploaded documents</h2>
        {documents.length > 0 ? (
          <table className="kv-table">
            <thead>
              <tr>
                <th>Description</th>
                <th>Kind</th>
                <th>Object path</th>
                <th>Uploaded at</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((d) => (
                <tr key={d.id ?? d.objectPath ?? String(d.createdAt)}>
                  <td>{d.description || "(no description)"}</td>
                  <td>{d.kind || "(unknown)"}</td>
                  <td>{d.objectPath || "(not set)"}</td>
                  <td>{d.createdAt || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No documents have been uploaded yet.</p>
        )}
      </section>

      <section className="card home-card">
        <h2>Analyze Product</h2>
        <p className="muted">
          When you are ready, analyze the product using the uploaded documents. For this MVP, analysis uses the existing
          Promise UL understanding pipeline as a stand-in.
        </p>
        {jobRunning && (
          <p className="muted">
            Analysis is running on the server — you can leave or refresh this page; it finishes on its own.{" "}
            {analysisPhaseLabel(job?.phase)}
            {elapsedLabel ? ` · ${elapsedLabel} elapsed` : ""}
          </p>
        )}
        {job?.state === "failed" && (
          <p className="error">
            The last analysis failed — {job.error || "no detail was recorded."} You can run it again.
          </p>
        )}
        <button type="button" className="button" disabled={analyzeDisabled} onClick={handleAnalyzeClick}>
          {analyzing || jobRunning ? "Analyzing…" : "Analyze Product"}
        </button>
      </section>

      <section className="card home-card">
        <h2>Delete Workspace</h2>
        <p className="muted">
          This is a destructive action intended for testing and cleanup. It will remove the workspace and any uploaded
          documents stored under its workspace prefix.
        </p>
        <button
          type="button"
          className="button button-secondary"
          disabled={deleting}
          onClick={handleDeleteWorkspace}
        >
          {deleting ? "Deleting…" : "Delete Workspace"}
        </button>
      </section>
    </div>
  );
};
