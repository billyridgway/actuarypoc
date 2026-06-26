import React from "react";
import { ProductWorkspacePage } from "./ProductWorkspacePage";

interface WorkspaceMeta {
  id: string;
  status: string;
  documentCount: number;
  createdAt?: string;
  updatedAt?: string;
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

export const WorkspacePage: React.FC<{ workspaceId: string }> = ({ workspaceId }) => {
  const [data, setData] = React.useState<WorkspaceResponse | null>(null);
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);
  const [uploading, setUploading] = React.useState<boolean>(false);
  const [uploadMessage, setUploadMessage] = React.useState<string | null>(null);
  const [analyzing, setAnalyzing] = React.useState<boolean>(false);
  const [deleting, setDeleting] = React.useState<boolean>(false);

  const loadWorkspace = React.useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `HTTP ${resp.status}`);
      }
      const body: WorkspaceResponse = await resp.json();
      setData(body);
    } catch (err: any) {
      setError(err?.message || "Failed to load workspace.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  React.useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  const workspace = data?.workspace;
  const documents = data?.documents ?? [];
  const snapshot = data?.snapshot;
  const hasSnapshot = !!snapshot;

  if (hasSnapshot && snapshot) {
    // Once analysis has populated the snapshot, reuse the existing
    // Product Understanding Workspace view directly from the snapshot.
    return <ProductWorkspacePage snapshot={snapshot} workspaceId={workspaceId} />;
  }

  const statusLabel = formatWorkspaceStatus(workspace?.status);
  const docCount = workspace?.documentCount ?? 0;
  const analyzeDisabled = docCount <= 0 || !!loading || !!analyzing;

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
      const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/analyze`, {
        method: "POST",
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Analyze failed with status ${resp.status}`);
      }
      const body = await resp.json();
      // Refresh workspace so that the snapshot and inferred fields are up to date.
      setData({
        workspace: body.workspace,
        documents,
        snapshot: body.snapshot,
      });
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
        <button type="button" className="button" disabled={analyzeDisabled} onClick={handleAnalyzeClick}>
          {analyzing ? "Analyzing…" : "Analyze Product"}
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
