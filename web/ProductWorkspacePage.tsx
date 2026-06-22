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
  gaps?: {
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

export const ProductWorkspacePage: React.FC = () => {
  const [data, setData] = React.useState<WorkspacePayload | null>(null);
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        // Slice 3 is Promise‑UL‑first: ICC18 P18PR UL is the canonical
        // workspace product code, with ICC18P18PRUL supported server‑side
        // as an alias.
        const code = encodeURIComponent("ICC18 P18PR UL");
        const resp = await fetch(`/api/product-workspace/${code}`);
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text || `HTTP ${resp.status}`);
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
  const gaps = data?.gaps;
  const illustration = data?.illustration;
  const mechanicsExplanation = data?.mechanicsExplanation;
  const pmr = data?.pmrReadiness;

  return (
    <div className="home-page">
      <header className="card">
        <h1>Product Understanding Workspace</h1>
        <p className="muted">
          High-level, read-only view of the current Promise UL understanding. Use this as the default workspace; switch
          to Expert / Debug mode when you need full control over each pipeline stage.
        </p>
        <p>
          <a href="/web?view=expert" className="button">
            Open Expert / Debug Mode
          </a>
        </p>
        {loading && <p className="muted">Loading Promise UL workspace…</p>}
        {error && !loading && <p className="error">{error}</p>}
      </header>

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
        {gaps && (gaps.warnings?.length || gaps.notes?.length) ? (
          <>
            {gaps.warnings && gaps.warnings.length > 0 && (
              <>
                <h3>Warnings</h3>
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
              <table className="kv-table">
                <tbody>
                  {Object.entries(illustration.metrics).map(([k, v]) => (
                    <tr key={k}>
                      <th>{k}</th>
                      <td>{typeof v === "number" ? formatCurrency(v) : String(v ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
                  <td>{pmr.status || "unknown"}</td>
                </tr>
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
    </div>
  );
};
