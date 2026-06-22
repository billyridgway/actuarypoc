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

export const ProductWorkspacePage: React.FC<{ productCode: string }> = ({ productCode }) => {
  const [data, setData] = React.useState<WorkspacePayload | null>(null);
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);
  const [uploadingId, setUploadingId] = React.useState<string | null>(null);
  const [uploadMessage, setUploadMessage] = React.useState<string | null>(null);

  React.useEffect(() => {
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
  }, []);

  const product = data?.product;
  const mechanicsSummary = data?.mechanics?.summary;
  const assumptions = data?.assumptions?.provenance ?? [];
  const evidenceItems = data?.evidence?.items ?? [];
  const compliance = data?.complianceMatrix;
  const gaps = data?.gaps;
  const illustration = data?.illustration;
  const mechanicsExplanation = data?.mechanicsExplanation;
  const pmr = data?.pmrReadiness;

  const gapItems = gaps?.items ?? [];

  // Derive a simple high-level understanding status from current
  // mechanics, illustration, and gap items. This is intentionally
  // conservative and uses only existing workspace data.
  const hasMaterialGaps = gapItems.some((g) => {
    const sev = (g.severity || "").toLowerCase();
    return sev === "high" || sev === "medium";
  });

  let understandingStatusLevel: "green" | "yellow" | "red" | "unknown" = "unknown";
  let understandingStatusLabel = "Understanding status is unknown.";

  if (illustration && mechanicsSummary) {
    if (hasMaterialGaps) {
      understandingStatusLevel = "yellow";
      understandingStatusLabel = "Draft understanding available with material gaps.";
    } else {
      understandingStatusLevel = "green";
      understandingStatusLabel = "Understanding appears substantially complete.";
    }
  } else {
    understandingStatusLevel = "red";
    understandingStatusLabel = "Major information is missing; understanding is incomplete.";
  }

  // Promise UL currently has an illustration plus known gaps, so this
  // resolves to yellow in practice.

  // Build a short, deterministic overview paragraph from existing
  // product and mechanics data.
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

  if (illustration) {
    overviewParts.push(
      "A draft illustration projection is available based on the currently discovered mechanics and assumptions.",
    );
  } else {
    overviewParts.push(
      "A draft illustration projection is not yet available; mechanics and assumptions are still being assembled.",
    );
  }

  const overviewText = overviewParts.join(" ");

  // Key mechanics bullets for quick scanning.
  const keyMechanics: string[] = [];
  if (mechanicsSummary?.deathBenefitOption) {
    keyMechanics.push(
      mechanicsSummary.deathBenefitOption.toLowerCase() === "level"
        ? "Level death benefit option"
        : `Death benefit option: ${mechanicsSummary.deathBenefitOption}`,
    );
  }
  if (mechanicsSummary?.interestCrediting) {
    keyMechanics.push(mechanicsSummary.interestCrediting);
  }
  if (mechanicsSummary?.coiApproach) {
    keyMechanics.push(mechanicsSummary.coiApproach);
  }
  if (mechanicsSummary?.surrenderMechanics) {
    keyMechanics.push(mechanicsSummary.surrenderMechanics);
  }

  // Highest-severity gaps for the summary view.
  const severityRank = (s?: string): number => {
    const v = (s || "").toLowerCase();
    if (v === "high") return 3;
    if (v === "medium") return 2;
    if (v === "low") return 1;
    return 0;
  };

  const majorGaps = [...gapItems].sort((a, b) => severityRank(b.severity) - severityRank(a.severity)).slice(0, 3);

  // Projection readiness narrative based on illustration presence and
  // known gaps.
  let projectionReadiness = "Projection readiness is unknown.";
  if (illustration) {
    const hasCoiGap = gapItems.some((g) => g.id === "missing_coi_table");
    const hasSurrGap = gapItems.some((g) => g.id === "surrender_schedule_placeholder");
    const hasFeeGap = gapItems.some((g) => g.id === "policy_admin_fee_missing");

    if (hasCoiGap || hasSurrGap || hasFeeGap) {
      projectionReadiness =
        "Draft projection available. Projection currently relies on placeholder COI rates, simplified surrender mechanics, and/or missing fee schedules and should not be considered filed-rate compliant.";
    } else {
      projectionReadiness =
        "Draft projection available. This surface is intended for product understanding and should not be treated as a filed-rate projection.";
    }
  } else {
    projectionReadiness =
      "No draft projection is currently available; projection readiness cannot yet be assessed from this workspace.";
  }

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
        <h2>Product Understanding Summary</h2>
        <p>{overviewText}</p>
        <div className="summary-status">
          <strong>Current understanding status: </strong>
          <span className={`tag tag--understanding-${understandingStatusLevel}`}>
            {understandingStatusLevel === "unknown" ? "UNKNOWN" : understandingStatusLevel.toUpperCase()}
          </span>
          <span className="muted" style={{ marginLeft: "0.5rem" }}>
            {understandingStatusLabel}
          </span>
        </div>

        {keyMechanics.length > 0 && (
          <>
            <h3>Key mechanics discovered</h3>
            <ul>
              {keyMechanics.map((m, idx) => (
                <li key={idx}>{m}</li>
              ))}
            </ul>
          </>
        )}

        {majorGaps.length > 0 && (
          <>
            <h3>Major gaps</h3>
            <ul>
              {majorGaps.map((g) => (
                <li key={g.id}>{g.title}</li>
              ))}
            </ul>
          </>
        )}

        <h3>Projection readiness</h3>
        <p className="muted">{projectionReadiness}</p>
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
        {evidenceItems.length > 0 ? (
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
        )}
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
        <h2>Mechanics discovered</h2>
        {mechanicsSummary ? (
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
        )}
      </section>

      <section className="card home-card">
        <h2>Assumptions extracted</h2>
        {assumptions.length > 0 ? (
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
        )}
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
        <h2>Draft illustration projection</h2>
        {illustration ? (
          <>
            <p className="muted">Draft Promise UL projection based on the current mechanics and assumptions.</p>
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
        {data?.documents && data.documents.length > 0 ? (
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
        )}
      </section>
    </div>
  );
};
