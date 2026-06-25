import React from "react";

interface WorkspaceAssumption {
  name?: string;
  value?: any;
  source?: string;
}

interface WorkspaceRow {
  year?: number;
  attainedAge?: number;
  premiumMode?: string;
  modalPremium?: number;
  annualPremium?: number;
  cumulativePremium?: number;
  guaranteedInterest?: number;
  coiCharge?: number;
  policyValue?: number;
  cashValue?: number;
  surrenderCharge?: number;
  surrenderValue?: number;
  deathBenefit?: number;
  netAmountAtRisk?: number;
  status?: string | null;
}

interface WorkspacePayload {
  product?: {
    code?: string;
    name?: string;
    type?: string;
    carrier?: string | null;
    filingId?: string | null;
    understandingStatus?: string;
  };
  productUnderstanding?: {
    productName?: string | null;
    productCode?: string | null;
    productType?: string | null;
    formNumbers?: string[] | null;
    issueAgeRange?: string | null;
    riskClasses?: string[] | null;
    documentsReviewed?: number;
    requirementsIdentified?: number;
    confidence?: string | null;
  };
  documents?: Array<{
    id?: number | string;
    kind?: string;
    description?: string | null;
    objectPath?: string | null;
    createdAt?: string | null;
    filingId?: string | null;
  }>;
  mechanics?: {
    summary?: {
      deathBenefitOption?: string;
      coiApproach?: string;
      interestCrediting?: string;
      surrenderMechanics?: string;
      mechanicsCount?: number;
    };
  };
  assumptions?: {
    provenance?: WorkspaceAssumption[];
  };
  readinessDashboard?: {
    overallStatus?: string;
    overallExplanation?: string;
    complianceSummary?: {
      implemented?: number;
      partial?: number;
      missing?: number;
      overallStatus?: string;
    };
    projectionTrustLevel?: string;
    criticalIssues?: Array<{
      id: string;
      name?: string;
      status?: string;
      impact?: string;
    }>;
    recommendedNextAction?: string | null;
  };
  complianceMatrix?: {
    summary?: {
      implemented?: number;
      partial?: number;
      missing?: number;
      overallStatus?: string;
    };
    requirements?: Array<{
      id: string;
      name: string;
      category?: string;
      filedRequirement?: string;
      currentImplementation?: string;
      status?: string;
      impact?: string;
      evidence?: any[];
      notes?: string;
    }>;
  };
  evidence?: {
    items?: Array<{
      id: string;
      label: string;
      category?: string;
      status?: string;
      value?: any;
      confidence?: number;
      impact?: string;
      notes?: string;
      sources?: Array<{
        document?: string | null;
        page?: string | null;
        snippet?: string | null;
        confidence?: number;
        origin?: string;
      }>;
    }>;
  };
  gaps?: {
    items?: Array<{
      id: string;
      title: string;
      severity?: string;
      status?: string;
      whyItMatters?: string;
      suggestedUploads?: string[];
      source?: string;
    }>;
    warnings?: string[];
    notes?: string[];
  };
  illustration?: {
    request?: Record<string, any>;
    metrics?: Record<string, any>;
    sampleRows?: WorkspaceRow[];
  } | null;
  mechanicsExplanation?: {
    title?: string;
    steps?: Array<{
      id?: string;
      order?: number;
      title?: string;
      formulaText?: string;
      inputs?: Array<{ label?: string; value?: any; source?: string }>;
      result?: { label?: string; value?: any; source?: string };
    }>;
  } | null;
  pmrReadiness?: {
    status?: string;
    messages?: string[];
  };
  documentInventory?: Array<{
    id?: number | string;
    description?: string | null;
    kind?: string | null;
    objectPath?: string | null;
    createdAt?: string | null;
    processingStatus?: string | null;
  }>;
  extractedFacts?: Array<{
    label: string;
    value?: any;
    source?: string | null;
    confidence?: number | null;
    status?: string;
  }>;
  requirementsCandidates?: Array<{
    id?: string;
    text: string;
    sourceDocument?: string | null;
    sourceReference?: string | null;
    confidence?: number | null;
    status: string;
    aiGenerated: boolean;
  }>;
}

const formatCurrency = (value: any): string => {
  if (value == null || value === "") return "";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

const formatStatusLabel = (value?: string | null): string => {
  const raw = (value || "").trim();
  if (!raw) return "Unknown";
  const v = raw.toLowerCase();
  const map: Record<string, string> = {
    review_in_progress: "Review In Progress",
    implemented: "Implemented",
    partial: "Partial",
    missing: "Missing",
    extracted: "Extracted",
    inferred: "Inferred",
    placeholder: "Placeholder",
    assumption_discovery: "Assumption Discovery",
    cash_surrender_value: "Cash Surrender Value",
  };
  if (map[v]) return map[v];
  // Fallback: split on underscores and capitalise words.
  return v
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
};

const formatProjectionTrustLevel = (value?: string | null): string => {
  const v = (value || "").toLowerCase();
  switch (v) {
    case "exploration_only":
      return "Exploration Only";
    case "draft_illustration":
      return "Draft Illustration";
    case "review_ready":
      return "Review Ready";
    case "filed_rate_ready":
      return "Filed-Rate Ready";
    default:
      return "Unknown";
  }
};

export const ProductWorkspacePage: React.FC<{ productCode?: string; snapshot?: WorkspacePayload | null }> = ({
  productCode,
  snapshot,
}) => {
  const [data, setData] = React.useState<WorkspacePayload | null>(snapshot ?? null);
  const [loading, setLoading] = React.useState<boolean>(!snapshot);
  const [error, setError] = React.useState<string | null>(null);
  const [uploadingId, setUploadingId] = React.useState<string | null>(null);
  const [uploadMessage, setUploadMessage] = React.useState<string | null>(null);
  const [dashboardUploading, setDashboardUploading] = React.useState<boolean>(false);
  const [dashboardUploadMessage, setDashboardUploadMessage] = React.useState<string | null>(null);
  const [showEvidence, setShowEvidence] = React.useState<boolean>(false);
  const [showMechanics, setShowMechanics] = React.useState<boolean>(false);
  const [showAssumptions, setShowAssumptions] = React.useState<boolean>(false);
  const [showGapWarnings, setShowGapWarnings] = React.useState<boolean>(false);
  const [showDocuments, setShowDocuments] = React.useState<boolean>(false);

  React.useEffect(() => {
    if (snapshot) {
      // When a snapshot is provided (workspace-based view), we skip the
      // product-code fetch entirely.
      setData(snapshot);
      setLoading(false);
      return;
    }

    if (!productCode) {
      setError("Product code is required for this view.");
      setLoading(false);
      return;
    }

    let cancelled = false;

    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const code = encodeURIComponent(productCode || "");
        const resp = await fetch(`/api/product-workspace/${code}`);
        if (!resp.ok) {
          let message = `Failed to load workspace (HTTP ${resp.status})`;
          try {
            const contentType = resp.headers.get("content-type") || "";
            if (contentType.includes("application/json")) {
              const body = await resp.json();
              if (body && typeof body.detail === "string" && body.detail.trim()) {
                message = body.detail.trim();
              }
            } else {
              const text = await resp.text();
              if (text) message = text;
            }
          } catch {
            // Ignore parse errors and keep the default message.
          }

          if (resp.status === 501) {
            message =
              "Product Understanding Workspace is not yet implemented for this product type. Use Expert / Debug mode or the Trust Surface for detailed PMR status.";
          }

          throw new Error(message);
        }
        const payload: WorkspacePayload = await resp.json();
        if (!cancelled) {
          setData(payload);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || "Failed to load workspace snapshot.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [productCode, snapshot]);

  const product = data?.product;
  const productUnderstanding = data?.productUnderstanding;
  const mechanicsSummary = data?.mechanics?.summary;
  const assumptions = data?.assumptions?.provenance ?? [];
  const evidenceItems = data?.evidence?.items ?? [];
  const compliance = data?.complianceMatrix;
  const readiness = data?.readinessDashboard;
  const gaps = data?.gaps;
  const illustration = data?.illustration;
  const mechanicsExplanation = data?.mechanicsExplanation;
  const pmr = data?.pmrReadiness;
  const documentInventory = data?.documentInventory;
  const extractedFacts = data?.extractedFacts ?? [];
  const requirementsCandidates = data?.requirementsCandidates ?? [];

  const gapItems = gaps?.items ?? [];
  // Build a short, deterministic product description from existing
  // product and mechanics data. Detailed readiness, compliance, and
  // projection narratives live in the dedicated cards below.
  const overviewParts: string[] = [];
  if (product) {
    const name = product.name || product.code || "This product";
    const type = product.type || "universal life";
    overviewParts.push(`${name} appears to be a ${type} product.`);
  } else {
    overviewParts.push("This product appears to be a universal life insurance product.");
  }

  if (mechanicsSummary) {
    const mechBits: string[] = [];
    if (mechanicsSummary.deathBenefitOption) {
      mechBits.push(
        mechanicsSummary.deathBenefitOption.toLowerCase() === "level"
          ? "a level death benefit option"
          : `a ${mechanicsSummary.deathBenefitOption} death benefit option`,
      );
    }
    if (mechanicsSummary.interestCrediting) {
      mechBits.push(mechanicsSummary.interestCrediting.toLowerCase());
    }
    if (mechanicsSummary.coiApproach) {
      mechBits.push(mechanicsSummary.coiApproach.toLowerCase());
    }
    if (mechanicsSummary.surrenderMechanics) {
      mechBits.push(mechanicsSummary.surrenderMechanics.toLowerCase());
    }
    if (mechBits.length > 0) {
      overviewParts.push(`Key mechanics include ${mechBits.join(", ")}.`);
    }
  }

  const overviewText = overviewParts.join(" ");

  return (
    <div className="home-page">
      <header className="card">
        <h1>Product Understanding Workspace</h1>
        <p className="muted">
          High-level, read-only view of the current product understanding. Use this as the default workspace; switch to
          Expert / Debug mode when you need full control over each pipeline stage.
        </p>
        <p>
          <a href="/web?view=expert" className="button">
            Open Expert / Debug Mode
          </a>
        </p>
        {loading && <p className="muted">Loading product workspace…</p>}
        {error && !loading && <p className="error">{error}</p>}
      </header>

      <section className="card home-card">
        <h2>Product Readiness Dashboard</h2>
        <p className="muted">
          Quick view of how complete the current understanding is, whether you can trust the projection, and what
          should happen next.
        </p>
        {readiness ? (
          <>
            <h3>Overall Understanding Status</h3>
            <p>
              <strong>Status:</strong>{" "}
              <span
                className={`tag tag--understanding-${(readiness.overallStatus || "unknown").toLowerCase()}`}
              >
                {formatStatusLabel(readiness.overallStatus || "unknown")}
              </span>
            </p>
            {readiness.overallExplanation && <p className="muted">{readiness.overallExplanation}</p>}

            <h3>Compliance Summary</h3>
            <p>
              {readiness.complianceSummary
                ? `Implemented: ${readiness.complianceSummary.implemented ?? 0}, Partial: ${
                    readiness.complianceSummary.partial ?? 0
                  }, Missing: ${readiness.complianceSummary.missing ?? 0}`
                : "Compliance summary is not available yet for this product."}
            </p>

            <h3>Projection Trust Level</h3>
            <p>
              <strong>Level:</strong> {formatProjectionTrustLevel(readiness.projectionTrustLevel || "unknown")}
            </p>

            <h3>Critical Missing Requirements</h3>
            {readiness.criticalIssues && readiness.criticalIssues.length > 0 ? (
              <ul className="muted">
                {readiness.criticalIssues.map((ci) => (
                  <li key={ci.id}>
                    {(ci.name || ci.id) + " – " + formatStatusLabel(ci.status || "unknown") + " (" +
                      formatStatusLabel(ci.impact || "unknown") + " impact)"}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No critical missing or partial high-impact requirements identified.</p>
            )}

            <h3>Recommended Next Action</h3>
            <p className="muted">
              {readiness.recommendedNextAction ||
                "Review the compliance matrix and evidence to decide the next best action for this product."}
            </p>
            {readiness.recommendedNextAction === "Upload COI rate table." && (
              <div className="next-action">
                <label className="button">
                  {dashboardUploading ? "Uploading COI rate table…" : "Upload COI rate table"}
                  <input
                    type="file"
                    style={{ display: "none" }}
                    disabled={dashboardUploading}
                    onChange={async (event: React.ChangeEvent<HTMLInputElement>) => {
                      const file = event.target.files && event.target.files[0];
                      if (!file) return;
                      setDashboardUploading(true);
                      setDashboardUploadMessage(null);
                      try {
                        const form = new FormData();
                        form.append("file", file);
                        const dashProductCode = product?.code || productCode || "ICC18 P18PR UL";
                        const resp = await fetch(
                          `/api/product-assumptions/${encodeURIComponent(dashProductCode)}/support`,
                          {
                            method: "POST",
                            body: form,
                          },
                        );
                        if (!resp.ok) {
                          const text = await resp.text();
                          throw new Error(text || `Upload failed with status ${resp.status}`);
                        }
                        setDashboardUploadMessage(
                          "Uploaded. Use Expert / Debug mode to rerun the pipeline until workspace rerun is wired.",
                        );
                      } catch (e: any) {
                        setDashboardUploadMessage(e?.message || "Upload failed.");
                      } finally {
                        setDashboardUploading(false);
                        if (event.target) {
                          event.target.value = "";
                        }
                      }
                    }}
                  />
                </label>
                {dashboardUploadMessage && <p className="muted">{dashboardUploadMessage}</p>}
              </div>
            )}
          </>
        ) : (
          <p className="muted">
            {loading
              ? "Loading readiness dashboard…"
              : "Readiness dashboard is not available yet for this product. Use Expert / Debug mode for more detail."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Product Understanding (AI-generated draft)</h2>
        <p>
          <span className="tag">AI-generated draft</span>{" "}
          <span className="tag">Needs actuarial review</span>
        </p>
        <p className="muted">
          High-level summary of what the system currently believes about this product based on existing structured
          data. This does not change projection behaviour.
        </p>
        {productUnderstanding ? (
          <table className="kv-table">
            <tbody>
              <tr>
                <th>Product Name</th>
                <td>{productUnderstanding.productName || "Not available in current analysis"}</td>
              </tr>
              <tr>
                <th>Product Code</th>
                <td>{productUnderstanding.productCode || "Not available in current analysis"}</td>
              </tr>
              <tr>
                <th>Product Type</th>
                <td>{productUnderstanding.productType || "Not available in current analysis"}</td>
              </tr>
              <tr>
                <th>Form Numbers</th>
                <td>
                  {productUnderstanding.formNumbers && productUnderstanding.formNumbers.length > 0
                    ? productUnderstanding.formNumbers.join(", ")
                    : "Not available in current analysis"}
                </td>
              </tr>
              <tr>
                <th>Issue Age Range</th>
                <td>{productUnderstanding.issueAgeRange || "Not available in current analysis"}</td>
              </tr>
              <tr>
                <th>Risk Classes</th>
                <td>
                  {productUnderstanding.riskClasses && productUnderstanding.riskClasses.length > 0
                    ? productUnderstanding.riskClasses.join(", ")
                    : "Not available in current analysis"}
                </td>
              </tr>
              <tr>
                <th>Documents Reviewed</th>
                <td>{productUnderstanding.documentsReviewed ?? 0}</td>
              </tr>
              <tr>
                <th>Candidate Requirements</th>
                <td>{productUnderstanding.requirementsIdentified ?? 0}</td>
              </tr>
              <tr>
                <th>Understanding Confidence</th>
                <td>{formatStatusLabel(productUnderstanding.confidence || "partial")}</td>
              </tr>
            </tbody>
          </table>
        ) : (
          <p className="muted">
            {loading
              ? "Loading product understanding…"
              : "Product understanding summary is not yet available for this workspace."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Document Inventory</h2>
        <p className="muted">
          Workspace documents that the system has recorded for this analysis. This is a read-only, AI-assisted view and
          does not change projection behaviour.
        </p>
        {documentInventory && documentInventory.length > 0 ? (
          <table className="kv-table">
            <thead>
              <tr>
                <th>Description</th>
                <th>Kind</th>
                <th>Object path</th>
                <th>Uploaded at</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {documentInventory.map((d, idx) => (
                <tr key={d.id ?? d.objectPath ?? String(d.createdAt) ?? idx}>
                  <td>{d.description || "(no description)"}</td>
                  <td>{d.kind || "(unknown)"}</td>
                  <td>{d.objectPath || "(not set)"}</td>
                  <td>{d.createdAt || ""}</td>
                  <td>{formatStatusLabel(d.processingStatus || "uploaded")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">
            {loading
              ? "Loading document inventory…"
              : "No workspace-specific document inventory is available. This MVP does not yet link product snapshots to individual workspace documents."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Extracted Facts (AI-generated draft)</h2>
        <p>
          <span className="tag">AI-generated draft</span>{" "}
          <span className="tag">Needs actuarial review</span>
        </p>
        <p className="muted">
          Key product facts the system believes it has extracted from existing metadata and the current workspace
          snapshot. These are AI-generated drafts and need actuarial review.
        </p>
        {extractedFacts && extractedFacts.length > 0 ? (
          <table className="kv-table">
            <thead>
              <tr>
                <th>Fact</th>
                <th>Value</th>
                <th>Status</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {extractedFacts.map((f, idx) => (
                <tr key={idx}>
                 <td>{f.label}</td>
                  <td>
                    {f.value == null || f.value === ""
                      ? "Not available in current analysis"
                      : Array.isArray(f.value)
                        ? (f.value as any[]).join(", ")
                        : String(f.value)}
                  </td>
                  <td>{formatStatusLabel(f.status || "extracted")}</td>
                  <td>{f.source || "(not recorded)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">
            {loading
              ? "Loading extracted facts…"
              : "No extracted facts snapshot is available yet for this workspace."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Product summary</h2>
        {product ? (
          <table className="kv-table">
            <tbody>
              <tr>
                <th>Product code</th>
                <td>{product.code || "ICC18 P18PR UL"}</td>
              </tr>
              <tr>
                <th>Product name</th>
                <td>{product.name || "Promise UL"}</td>
              </tr>
              <tr>
                <th>Product type</th>
                <td>{product.type || "UL"}</td>
              </tr>
              <tr>
                <th>Carrier</th>
                <td>{product.carrier || "(not set)"}</td>
              </tr>
              <tr>
                <th>Filing context</th>
                <td>{product.filingId || "(none)"}</td>
              </tr>
              <tr>
                <th>Understanding status</th>
                <td>{product.understandingStatus || pmr?.status || "unknown"}</td>
              </tr>
            </tbody>
          </table>
        ) : (
          <p className="muted">{loading ? "Loading product summary…" : "No Product Review metadata found yet."}</p>
        )}
      </section>

      <section className="card home-card">
        <h2>Product Understanding Evidence</h2>
        <p className="muted">
          Traceability from filings and assumptions to the mechanics used in this workspace. This helps explain why the
          system believes the product behaves the way it does.
        </p>
        <p>
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setShowEvidence((v) => !v)}
          >
            {showEvidence ? "Hide evidence details" : "Show evidence details"}
          </button>
        </p>
        {showEvidence ? (
          evidenceItems.length > 0 ? (
            <div className="evidence-list">
              {evidenceItems.map((ev) => {
                const statusLabel = formatStatusLabel(ev.status || "unknown");
                const conf =
                  typeof ev.confidence === "number" ? `${(ev.confidence * 100).toFixed(0)}%` : "Unknown";
                const impactLabel = formatStatusLabel(ev.impact || "unknown");
                const src = (ev.sources && ev.sources[0]) || null;
                const valueText =
                  typeof ev.value === "number"
                    ? ev.label.toLowerCase().includes("rate")
                      ? `${(ev.value * 100).toFixed(2)}%`
                      : formatCurrency(ev.value)
                    : String(ev.value ?? "");

                return (
                  <div key={ev.id} className="evidence-item">
                    <h3>{ev.label}</h3>
                    <p className="muted">{ev.notes}</p>
                    <p>
                      <strong>Status:</strong> {statusLabel} | <strong>Impact:</strong> {impactLabel}
                    </p>
                    <p>
                      <strong>Value:</strong> {valueText || "(not set)"}
                    </p>
                    <p>
                      <strong>Confidence:</strong> {conf}
                    </p>
                    <div>
                      <strong>Source:</strong>
                      {src ? (
                        <div className="muted">
                          {src.document && <div>{src.document}</div>}
                          {src.page && <div>p. {src.page}</div>}
                          {src.snippet && <div>{src.snippet}</div>}
                          {src.origin && <div>Origin: {formatStatusLabel(src.origin)}</div>}
                        </div>
                      ) : (
                        <span className="muted"> (no direct filing source)</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="muted">
              {loading
                ? "Loading evidence…"
                : "No structured evidence snapshot is available yet for this product. Use Expert / Debug mode or the Trust Surface for more detail."}
            </p>
          )
        ) : null}
      </section>

      <section className="card home-card">
        <h2>Product Compliance Matrix</h2>
        <p className="muted">
          Comparison of key filed requirements against the current implementation, with a simple implemented/partial/
          missing status for each.
        </p>
        {compliance && compliance.requirements && compliance.requirements.length > 0 ? (
          <>
            {compliance.summary && (
              <div className="summary-status">
                <strong>Overall compliance status: </strong>
                <span
                  className={`tag tag--compliance-${(compliance.summary.overallStatus || "unknown").toLowerCase()}`}
                >
                  {formatStatusLabel(compliance.summary.overallStatus || "unknown")}
                </span>
                <span className="muted" style={{ marginLeft: "0.5rem" }}>
                  Implemented: {compliance.summary.implemented ?? 0}, Partial: {compliance.summary.partial ?? 0},
                  Missing: {compliance.summary.missing ?? 0}
                </span>
              </div>
            )}

            <div className="compliance-list">
              {compliance.requirements.map((req) => {
                const status = formatStatusLabel(req.status || "unknown");
                const impact = formatStatusLabel(req.impact || "unknown");
                const ev = (req.evidence && req.evidence[0]) || null;
                const src = ev && ev.sources && ev.sources[0];

                return (
                  <div key={req.id} className="compliance-item">
                    <h3>{req.name}</h3>
                    <p className="muted">{req.notes}</p>
                    <p>
                      <strong>Status:</strong> {status} | <strong>Impact:</strong> {impact}
                    </p>
                    <p>
                      <strong>Filed requirement:</strong> {req.filedRequirement || "(not documented)"}
                    </p>
                    <p>
                      <strong>Current implementation:</strong> {req.currentImplementation || "(not implemented)"}
                    </p>
                    <div>
                      <strong>Evidence:</strong>
                      {src ? (
                        <div className="muted">
                          {src.document && <div>{src.document}</div>}
                          {src.page && <div>p. {src.page}</div>}
                          {src.snippet && <div>{src.snippet}</div>}
                        </div>
                      ) : (
                        <span className="muted"> (no direct filing source)</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <p className="muted">
            {loading
              ? "Loading compliance matrix…"
              : "No compliance matrix is available yet for this product. Use Expert / Debug mode or the Trust Surface for more detail."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Candidate Requirements (AI-generated)</h2>
        <p>
          <span className="tag">AI-generated draft</span>{" "}
          <span className="tag">Needs actuarial review</span>
        </p>
        <p className="muted">
          Draft filing and implementation requirements inferred from the current compliance matrix and evidence. These
          are AI-generated candidates and must be reviewed and, if appropriate, translated into formal requirements.
        </p>
        {requirementsCandidates && requirementsCandidates.length > 0 ? (
          <table className="kv-table">
            <thead>
              <tr>
                <th>Requirement</th>
                <th>Source document</th>
                <th>Reference</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {requirementsCandidates.map((r) => (
                <tr key={r.id ?? r.text}>
                  <td>{r.text}</td>
                  <td>{r.sourceDocument || "(not recorded)"}</td>
                  <td>{r.sourceReference || "(not recorded)"}</td>
                  <td>
                    {typeof r.confidence === "number"
                      ? `${(r.confidence * 100).toFixed(0)}%`
                      : "Unknown"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">
            {loading
              ? "Loading candidate requirements…"
              : "No candidate requirements are available yet for this workspace."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Mechanics discovered</h2>
        <p>
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setShowMechanics((v) => !v)}
          >
            {showMechanics ? "Hide mechanics" : "Show mechanics"}
          </button>
        </p>
        {showMechanics ? (
          mechanicsSummary ? (
            <>
              <p className="muted">Draft mechanics currently inferred for Promise UL.</p>
              <table className="kv-table">
                <tbody>
                  <tr>
                    <th>Death benefit option</th>
                    <td>{mechanicsSummary.deathBenefitOption || "level"}</td>
                  </tr>
                  <tr>
                    <th>COI approach</th>
                    <td>{mechanicsSummary.coiApproach}</td>
                  </tr>
                  <tr>
                    <th>Interest crediting</th>
                    <td>{mechanicsSummary.interestCrediting}</td>
                  </tr>
                  <tr>
                    <th>Surrender mechanics</th>
                    <td>{mechanicsSummary.surrenderMechanics}</td>
                  </tr>
                  <tr>
                    <th>Mechanics discovered</th>
                    <td>{mechanicsSummary.mechanicsCount ?? 0}</td>
                  </tr>
                </tbody>
              </table>
            </>
          ) : (
            <p className="muted">{loading ? "Loading mechanics…" : "No mechanics registry found for Promise UL yet."}</p>
          )
        ) : null}
      </section>

      <section className="card home-card">
        <h2>Assumptions extracted</h2>
        <p>
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setShowAssumptions((v) => !v)}
          >
            {showAssumptions ? "Hide assumptions" : "Show assumptions"}
          </button>
        </p>
        {showAssumptions ? (
          assumptions.length > 0 ? (
            <table className="kv-table">
              <thead>
                <tr>
                  <th>Assumption</th>
                  <th>Value</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {assumptions.map((a, idx) => (
                  <tr key={idx}>
                    <td>{a.name || "(unnamed)"}</td>
                    <td>
                      {typeof a.value === "number"
                        ? a.name?.toLowerCase().includes("rate")
                          ? `${(a.value * 100).toFixed(2)}%`
                          : formatCurrency(a.value)
                        : String(a.value ?? "")}
                    </td>
                    <td>{a.source || "(unknown)"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">
              {loading
                ? "Loading assumptions…"
                : "No UL projection assumptions have been discovered for Promise UL yet."}
            </p>
          )
        ) : null}
      </section>

      <section className="card home-card">
        <h2>Missing information / gaps</h2>
        <p className="muted">
          Uploading additional support documents improves evidence for mechanics and assumptions, but does not
          automatically make this draft projection filed-rate compliant. Use Expert / Debug mode to rerun and review
          the full pipeline.
        </p>
        {uploadMessage && <p className="muted">{uploadMessage}</p>}
            {gaps && gaps.items && gaps.items.length > 0 ? (
          <>
            {gaps.items.map((item) => {
              const isUploading = uploadingId === item.id;
              const gapProductCode = product?.code || "ICC18 P18PR UL";

              const handleFileChange: React.ChangeEventHandler<HTMLInputElement> = async (event) => {
                const file = event.target.files && event.target.files[0];
                if (!file) return;
                setUploadingId(item.id);
                setUploadMessage(null);
                try {
                  const form = new FormData();
                  form.append("file", file);
                  const resp = await fetch(
                    `/api/product-assumptions/${encodeURIComponent(gapProductCode)}/support`,
                    {
                      method: "POST",
                      body: form,
                    },
                  );
                  if (!resp.ok) {
                    const text = await resp.text();
                    throw new Error(text || `Upload failed with status ${resp.status}`);
                  }
                  setUploadMessage(
                    `Uploaded '${file.name}' as additional assumption support for ${gapProductCode}. Rerun understanding via Expert / Debug mode to incorporate new evidence.`,
                  );
                } catch (e: any) {
                  setUploadMessage(e?.message || "Upload failed.");
                } finally {
                  setUploadingId(null);
                  event.target.value = "";
                }
              };

              const handleRerunClick = () => {
                setUploadMessage(
                  "Rerun understanding is not wired to orchestration yet. Use Expert / Debug mode to rerun the pipeline after uploading support.",
                );
              };

              return (
                <div key={item.id} className="gap-item">
                  <h3>{item.title}</h3>
                  <p className="muted">
                    <strong>Status:</strong> {formatStatusLabel(item.status || "unknown")}; <strong>Severity:</strong> {formatStatusLabel(item.severity || "n/a")}
                    {item.source && (
                      <>
                        {" "}- <strong>Source:</strong> {item.source}
                      </>
                    )}
                  </p>
                  {item.whyItMatters && <p className="muted">{item.whyItMatters}</p>}
                  {item.suggestedUploads && item.suggestedUploads.length > 0 && (
                    <p className="muted">
                      <strong>Suggested uploads:</strong> {item.suggestedUploads.join(", ")}
                    </p>
                  )}
                  <div className="gap-actions">
                    <label className="button button-secondary">
                      {isUploading ? "Uploading…" : "Upload supporting document"}
                      <input
                        type="file"
                        style={{ display: "none" }}
                        disabled={isUploading}
                        onChange={handleFileChange}
                      />
                    </label>
                    <button type="button" className="button button-ghost" onClick={handleRerunClick}>
                      Rerun understanding (coming soon)
                    </button>
                  </div>
                </div>
              );
            })}

            {/* Preserve raw warnings/notes for additional context. */}
            {(gaps.warnings && gaps.warnings.length > 0) || (gaps.notes && gaps.notes.length > 0) ? (
              <div className="gap-raw-summary">
                <p>
                  <button
                    type="button"
                    className="button button-ghost"
                    onClick={() => setShowGapWarnings((v) => !v)}
                  >
                    {showGapWarnings ? "Hide raw warnings / notes" : "Show raw warnings / notes"}
                  </button>
                </p>
                {showGapWarnings && (
                  <>
                    {gaps.warnings && gaps.warnings.length > 0 && (
                      <>
                        <h3>Raw warnings</h3>
                        <ul className="muted">
                          {gaps.warnings.map((w, idx) => (
                            <li key={idx}>{w}</li>
                          ))}
                        </ul>
                      </>
                    )}
                    {gaps.notes && gaps.notes.length > 0 && (
                      <>
                        <h3>Notes</h3>
                        <ul className="muted">
                          {gaps.notes.map((n, idx) => (
                            <li key={idx}>{n}</li>
                          ))}
                        </ul>
                      </>
                    )}
                  </>
                )}
              </div>
            ) : null}
          </>
        ) : (
          <p className="muted">
            {loading
              ? "Loading gaps…"
              : "No explicit gaps recorded yet. Placeholder UL assumptions may still hide missing COI tables, surrender schedules, or fees."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Draft illustration (product understanding only)</h2>
        {illustration ? (
          <>
            <p className="muted">
              Draft Promise UL projection for product understanding. This is not a filed-rate compliant carrier
              illustration.
            </p>
            {illustration.metrics && (
              <div className="projection-summary">
                {typeof illustration.metrics.maximumYear === "number" && (
                  <p>
                    <strong>Projection Horizon:</strong> {illustration.metrics.maximumYear} years
                  </p>
                )}
                {typeof illustration.metrics.breakEvenYearCash === "number" && (
                  <p>
                    <strong>Break-even Cash Value:</strong> Year {illustration.metrics.breakEvenYearCash}
                  </p>
                )}
                {typeof illustration.metrics.breakEvenYearSurrender === "number" && (
                  <p>
                    <strong>Break-even Surrender Value:</strong> Year {illustration.metrics.breakEvenYearSurrender}
                  </p>
                )}
              </div>
            )}
            {illustration.sampleRows && illustration.sampleRows.length > 0 && (
              <>
                <h3>Sample projection rows</h3>
                <table className="kv-table">
                  <thead>
                    <tr>
                      <th>Year</th>
                      <th>Attained age</th>
                      <th>Premium mode</th>
                      <th>Annual premium</th>
                      <th>Cash value</th>
                      <th>Surrender value</th>
                      <th>Death benefit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {illustration.sampleRows.map((row, idx) => (
                      <tr key={idx}>
                        <td>{row.year}</td>
                        <td>{row.attainedAge ?? ""}</td>
                        <td>{row.premiumMode ?? ""}</td>
                        <td>{formatCurrency(row.annualPremium ?? row.modalPremium)}</td>
                        <td>{formatCurrency(row.cashValue ?? row.policyValue)}</td>
                        <td>{formatCurrency(row.surrenderValue)}</td>
                        <td>{formatCurrency(row.deathBenefit)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        ) : (
          <p className="muted">
            {loading
              ? "Loading draft illustration…"
              : "No draft UL illustration is available yet for Promise UL."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Mechanics explanation / order of operations</h2>
        {mechanicsExplanation && mechanicsExplanation.steps && mechanicsExplanation.steps.length > 0 ? (
          <>
            <p className="muted">Year 1 order-of-operations trace for the current Promise UL projection.</p>
            <ol>
              {mechanicsExplanation.steps.map((step) => (
                <li key={step.id ?? step.order}>
                  <strong>{step.title || "Step"}</strong>
                  {step.formulaText && <p className="muted">{step.formulaText}</p>}
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p className="muted">
            {loading
              ? "Loading mechanics explanation…"
              : "No UL mechanics explanation is available yet for Promise UL."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>PMR / readiness recommendation</h2>
        {pmr ? (
          <>
            <table className="kv-table">
              <tbody>
                <tr>
                  <th>Status</th>
                  <td>{formatStatusLabel(pmr.status || "unknown")}</td>
                </tr>
                {compliance && compliance.summary && (
                  <tr>
                    <th>Compliance summary</th>
                    <td>
                      Implemented: {compliance.summary.implemented ?? 0}, Partial: {compliance.summary.partial ?? 0},
                      Missing: {compliance.summary.missing ?? 0} (Overall {formatStatusLabel(
                        compliance.summary.overallStatus || "unknown",
                      )})
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            {pmr.messages && pmr.messages.length > 0 && (
              <ul className="muted">
                {pmr.messages.map((m, idx) => (
                  <li key={idx}>{m}</li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <p className="muted">
            {loading
              ? "Loading readiness…"
              : "No Product Model Review readiness snapshot is available for Promise UL yet."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Uploaded documents</h2>
        <p>
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setShowDocuments((v) => !v)}
          >
            {showDocuments ? "Hide documents" : "Show documents"}
          </button>
        </p>
        {showDocuments ? (
          data?.documents && data.documents.length > 0 ? (
            <table className="kv-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Kind</th>
                  <th>Description</th>
                  <th>Object path</th>
                  <th>Filing</th>
                  <th>Uploaded at</th>
                </tr>
              </thead>
              <tbody>
                {data.documents.map((d) => (
                  <tr key={d.id ?? d.objectPath ?? String(d.createdAt)}>
                    <td>{d.id}</td>
                    <td>{d.kind || "filing"}</td>
                    <td>{d.description || "(none)"}</td>
                    <td>{d.objectPath}</td>
                    <td>{d.filingId || product?.filingId || "(n/a)"}</td>
                    <td>{d.createdAt || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">
              {loading
                ? "Loading documents…"
                : "No filings or support documents are registered for Promise UL yet."}
            </p>
          )
        ) : null}
      </section>
    </div>
  );
};
