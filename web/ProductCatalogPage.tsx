import React from "react";

interface CatalogWorkspace {
  id: string;
  status: string;
  documentCount: number;
  inferredProductName?: string | null;
  inferredProductType?: string | null;
  inferredCarrier?: string | null;
  complianceStatus?: string | null;
  complianceImplemented?: number | null;
  compliancePartial?: number | null;
  complianceMissing?: number | null;
  projectionTrustLevel?: string | null;
}

interface WorkspacesResponse {
  workspaces?: any[];
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

const normaliseComplianceLabel = (value?: string | null): string => {
  const v = (value || "").toLowerCase();
  if (!v) return "Unknown";
  if (v === "green") return "Green";
  if (v === "yellow") return "Yellow";
  if (v === "red") return "Red";
  return "Unknown";
};

export const ProductCatalogPage: React.FC = () => {
  const [workspaces, setWorkspaces] = React.useState<CatalogWorkspace[]>([]);
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = React.useState<{
    total: number;
    uploaded: number;
  } | null>(null);

  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await fetch("/api/workspaces");
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text || `HTTP ${resp.status}`);
        }
        const body: WorkspacesResponse = await resp.json();
        const raw = body.workspaces || [];
        if (!Array.isArray(raw)) {
          if (!cancelled) setWorkspaces([]);
          return;
        }

        const mapped: CatalogWorkspace[] = raw.map((w: any) => {
          return {
            id: String(w.id || "").toLowerCase(),
            status: String(w.status || "unknown"),
            documentCount:
              typeof w.documentCount === "number" ? w.documentCount : Number(w.documentCount || 0),
            inferredProductName: w.inferredProductName ?? null,
            inferredProductType: w.inferredProductType ?? null,
            inferredCarrier: w.inferredCarrier ?? null,
            complianceStatus: w.complianceStatus ?? null,
            complianceImplemented:
              typeof w.complianceImplemented === "number" ? w.complianceImplemented : null,
            compliancePartial:
              typeof w.compliancePartial === "number" ? w.compliancePartial : null,
            complianceMissing:
              typeof w.complianceMissing === "number" ? w.complianceMissing : null,
            projectionTrustLevel: w.projectionTrustLevel ?? null,
          };
        });

        if (!cancelled) setWorkspaces(mapped);
      } catch (err: any) {
        if (!cancelled) setError(err?.message || "Failed to load products.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const hasWorkspaces = workspaces.length > 0;

  const handleDeleteWorkspace = async (id: string) => {
    const confirmed = window.confirm(
      "This will permanently delete the workspace and uploaded documents from object storage. This cannot be undone.",
    );
    if (!confirmed) return;

    try {
      const resp = await fetch(`/api/workspaces/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Delete failed with status ${resp.status}`);
      }

      // Optimistically remove from local state; a refresh will also
      // reflect the deletion.
      setWorkspaces((prev) => prev.filter((w) => w.id !== id));
    } catch (err: any) {
      setError(err?.message || "Failed to delete workspace.");
    }
  };

  const handleNewProductReviewFiles: React.ChangeEventHandler<HTMLInputElement> = async (event) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    const fileArray = Array.from(files);
    setCreating(true);
    setUploadProgress({ total: fileArray.length, uploaded: 0 });
    setError(null);

    try {
      // Step 1: create a new workspace to host these filings.
      const respWorkspace = await fetch("/api/workspaces", { method: "POST" });
      if (!respWorkspace.ok) {
        const text = await respWorkspace.text();
        throw new Error(text || `Failed to create workspace (HTTP ${respWorkspace.status})`);
      }
      const bodyWs: any = await respWorkspace.json();
      const ws = bodyWs.workspace;
      const workspaceId: string | undefined = ws && ws.id ? String(ws.id) : undefined;
      if (!workspaceId) {
        throw new Error("Workspace ID was not returned from create endpoint.");
      }

      // Step 2: upload each selected filing document into the new workspace.
      let uploaded = 0;
      for (const file of fileArray) {
        const form = new FormData();
        form.append("file", file);
        const respUpload = await fetch(
          `/api/workspaces/${encodeURIComponent(workspaceId)}/documents`,
          {
            method: "POST",
            body: form,
          },
        );
        if (!respUpload.ok) {
          const text = await respUpload.text();
          throw new Error(text || `Upload failed with status ${respUpload.status}`);
        }
        uploaded += 1;
        setUploadProgress({ total: fileArray.length, uploaded });
      }

      // Step 3: open the workspace so the user can immediately click Analyze Product.
      window.location.href = `/web?workspace=${encodeURIComponent(workspaceId)}`;
    } catch (err: any) {
      setError(err?.message || "Failed to create product review workspace.");
    } finally {
      setCreating(false);
      setUploadProgress(null);
      if (event.target) {
        event.target.value = "";
      }
    }
  };

  return (
    <div className="home-page">
      <section className="card home-card">
        <h2>Workspace Catalog</h2>
        <p className="muted">
          Start a new product review by uploading one or more filing documents. The system will create a workspace for
          you and attach those documents automatically. Use Expert / Debug mode for detailed pipeline control.
        </p>
        <p>
          <button
            type="button"
            className="button"
            disabled={creating}
            onClick={() => {
              setError(null);
              if (fileInputRef.current) {
                fileInputRef.current.click();
              }
            }}
          >
            New Product Review
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            style={{ display: "none" }}
            onChange={handleNewProductReviewFiles}
          />
        </p>
        {uploadProgress && (
          <p className="muted">
            Uploading filings… {uploadProgress.uploaded} of {uploadProgress.total}
          </p>
        )}
        {loading && <p className="muted">Loading products…</p>}
        {error && !loading && <p className="error">{error}</p>}
        {!loading && !error && !hasWorkspaces && (
          <p className="muted">
            No workspaces exist yet. Click New Product Review and upload filings to get started.
          </p>
        )}

        {hasWorkspaces && (
          <div className="catalog-grid">
            {workspaces.map((w) => {
              const statusLabel = formatWorkspaceStatus(w.status);
              const docCountLabel = String(w.documentCount ?? 0);
              const complianceLabel = normaliseComplianceLabel(w.complianceStatus);
              const projectionLabel = w.projectionTrustLevel
                ? normaliseComplianceLabel(w.projectionTrustLevel)
                : "Unknown";
              const name = w.inferredProductName || "New Product Review";
              const type = w.inferredProductType || "(unknown)";
              const carrier = w.inferredCarrier || "(unknown)";

              const href = `/web?workspace=${encodeURIComponent(w.id)}`;

              return (
                <div key={w.id} className="card home-card">
                  <h3>{name}</h3>
                  <p className="muted">
                    <strong>Workspace:</strong> {w.id}
                    <br />
                    <strong>Type:</strong> {type}
                    <br />
                    <strong>Carrier:</strong> {carrier}
                  </p>
                  <table className="kv-table">
                    <tbody>
                      <tr>
                        <th>Status</th>
                        <td>{statusLabel}</td>
                      </tr>
                      <tr>
                        <th>Documents</th>
                        <td>{docCountLabel}</td>
                      </tr>
                      <tr>
                        <th>Projection</th>
                        <td>{projectionLabel}</td>
                      </tr>
                      <tr>
                        <th>Compliance</th>
                        <td>
                          {complianceLabel}
                          {w.complianceImplemented != null && (
                            <span className="muted">{` - Impl: ${w.complianceImplemented}, Part: ${
                              w.compliancePartial ?? 0
                            }, Miss: ${w.complianceMissing ?? 0}`}</span>
                          )}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <p>
                    <a href={href} className="button">
                      Open workspace
                    </a>
                  </p>
                  <p>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => handleDeleteWorkspace(w.id)}
                    >
                      Delete workspace
                    </button>
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="card home-card">
        <h2>Add Workspace (coming soon)</h2>
        <p className="muted">
          This is a placeholder for future workspace templates and cloning. For now, use Create Workspace above and
          upload filing documents directly.
        </p>
        <div className="add-product-form" />
      </section>
    </div>
  );
};
