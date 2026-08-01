import React from "react";
import { formatCurrency, ProjectionChart, ProjectionGraphDefinition, ProjectionLogicGraph, WorkspaceRow } from "./ProductWorkspacePage";

interface ProjectionLogicPageProps {
  snapshot: any;
  workspaceId: string;
}

const initialGraphInputs = (snapshot: any) => {
  const request = snapshot?.illustration?.request || {};
  const firstRow = snapshot?.illustration?.rows?.[0] || {};
  const inputs = Array.isArray(snapshot?.illustration?.inputs) ? snapshot.illustration.inputs : [];
  const policyFee = inputs.find((input: any) => input?.id === "policy_fee");
  const values: Record<string, string | number> = {
    issue_age: Number(request.age ?? 45),
    face_amount: Number(request.faceAmount ?? 100000),
    premium: Number(firstRow.modalPremium ?? firstRow.annualPremium ?? 3000),
    premium_mode: String(request.premiumMode ?? "ANNUAL"),
    sex: String(request.sex ?? ""),
    risk_class: String(request.riskClass ?? ""),
    tobacco_status: String(request.tobaccoStatus ?? ""),
  };
  if (["missing", "not_available", "scenario_assumption"].includes(String(policyFee?.status || "").toLowerCase())) {
    values.policy_fee = request.policyFeeAnnual ?? (policyFee?.status === "scenario_assumption" ? policyFee?.value : "");
  }
  return values;
};

export const ProjectionLogicPage: React.FC<ProjectionLogicPageProps> = ({ snapshot, workspaceId }) => {
  const [illustration, setIllustration] = React.useState(snapshot?.illustration ?? null);
  const [projectionGraph, setProjectionGraph] = React.useState<ProjectionGraphDefinition | null>(snapshot?.projectionGraph ?? null);
  const [values, setValues] = React.useState<Record<string, string | number>>(() => initialGraphInputs(snapshot));
  const [dirty, setDirty] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [runMessage, setRunMessage] = React.useState<string | null>(null);
  const [syntheticPreview, setSyntheticPreview] = React.useState<any>(null);
  const [generatingSynthetic, setGeneratingSynthetic] = React.useState(false);
  const [acceptingSynthetic, setAcceptingSynthetic] = React.useState(false);
  const [removingSynthetic, setRemovingSynthetic] = React.useState(false);

  const graphNodes = projectionGraph?.nodes ?? [];
  const inputNodes = graphNodes.filter((node) => node.kind === "input" || (node.kind === "unmodeled" && Boolean(node.inputId)));
  const ruleNodes = graphNodes.filter((node) => node.kind === "rule" || (node.kind === "unmodeled" && !node.inputId));
  const rows = (illustration?.rows ?? []) as WorkspaceRow[];
  const metrics = illustration?.metrics ?? {};
  const missingCount = graphNodes.filter((node) => node.status === "missing").length;
  const provisionalCount = graphNodes.filter((node) => node.status === "provisional").length;

  const updateInput = (inputId: string, value: string) => {
    setValues((current) => ({ ...current, [inputId]: value }));
    setDirty(true);
  };

  const runProjection = async () => {
    const issueAge = Number(values.issue_age);
    const faceAmount = Number(values.face_amount);
    const modalPremium = Number(values.premium);
    const policyFeeText = String(values.policy_fee ?? "").trim();
    const policyFeeAnnual = policyFeeText === "" ? undefined : Number(policyFeeText);
    if (!Number.isInteger(issueAge) || issueAge < 0 || issueAge > 120) {
      setError("Issue age must be a whole number from 0 to 120.");
      return;
    }
    if (!Number.isFinite(faceAmount) || faceAmount <= 0) {
      setError("Face amount must be greater than $0.");
      return;
    }
    if (!Number.isFinite(modalPremium) || modalPremium <= 0) {
      setError("Modal premium must be greater than $0.");
      return;
    }
    if (policyFeeAnnual !== undefined && (!Number.isFinite(policyFeeAnnual) || policyFeeAnnual < 0)) {
      setError("Annual policy/admin fee must be $0 or greater.");
      return;
    }
    setRunning(true);
    setError(null);
    setRunMessage(null);
    try {
      const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/projection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          issueAge,
          faceAmount,
          modalPremium,
          premiumMode: String(values.premium_mode),
          sex: String(values.sex || ""),
          riskClass: String(values.risk_class || ""),
          tobaccoStatus: String(values.tobacco_status || ""),
          policyFeeAnnual,
        }),
      });
      if (!response.ok) throw new Error((await response.text()) || `Projection failed (HTTP ${response.status})`);
      const body = await response.json();
      setIllustration(body.illustration ?? null);
      setProjectionGraph(body.projectionGraph ?? null);
      setDirty(false);
      setRunMessage("Projection complete. Results updated below.");
      window.setTimeout(() => document.getElementById("projection-results")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    } catch (err: any) {
      setError(err?.message || "Projection failed.");
    } finally {
      setRunning(false);
    }
  };

  const generateSyntheticCoi = async () => {
    setGeneratingSynthetic(true);
    setError(null);
    try {
      const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/synthetic-coi/preview`, { method: "POST" });
      if (!response.ok) throw new Error((await response.text()) || `Generation failed (HTTP ${response.status})`);
      const body = await response.json();
      setSyntheticPreview(body.preview ?? null);
      window.setTimeout(() => document.getElementById("synthetic-coi-review")?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
    } catch (err: any) {
      setError(err?.message || "Synthetic COI generation failed.");
    } finally {
      setGeneratingSynthetic(false);
    }
  };

  const acceptSyntheticCoi = async () => {
    if (!syntheticPreview) return;
    setAcceptingSynthetic(true);
    setError(null);
    try {
      const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/synthetic-coi/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          parameters: syntheticPreview.parameters,
          model: syntheticPreview.model,
          generatedAt: syntheticPreview.generatedAt,
        }),
      });
      if (!response.ok) throw new Error((await response.text()) || `Acceptance failed (HTTP ${response.status})`);
      setSyntheticPreview(null);
      await runProjection();
      setRunMessage("Synthetic COI table accepted and applied to the projection.");
    } catch (err: any) {
      setError(err?.message || "Synthetic COI table could not be accepted.");
    } finally {
      setAcceptingSynthetic(false);
    }
  };

  const removeSyntheticCoi = async () => {
    setRemovingSynthetic(true);
    setError(null);
    try {
      const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/synthetic-coi`, { method: "DELETE" });
      if (!response.ok) throw new Error((await response.text()) || `Removal failed (HTTP ${response.status})`);
      await runProjection();
      setRunMessage("Synthetic COI table removed. The flat fallback is active again.");
    } catch (err: any) {
      setError(err?.message || "Synthetic COI table could not be removed.");
    } finally {
      setRemovingSynthetic(false);
    }
  };

  const downloadSyntheticCoiCsv = () => {
    const syntheticRows = syntheticPreview?.rows ?? [];
    if (!syntheticRows.length) return;
    const fields = ["attained_age", "sex", "risk_class", "tobacco_status", "rate", "rate_unit"];
    const csv = [fields.join(","), ...syntheticRows.map((row: any) => fields.map((field) => `"${String(row[field] ?? "").replace(/"/g, '""')}"`).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "synthetic-coi-table.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const downloadProjectionCsv = () => {
    if (!rows.length) return;
    const columns: Array<[keyof WorkspaceRow, string]> = [
      ["year", "Year"], ["attainedAge", "Age"], ["openingPolicyValue", "Opening value"],
      ["annualPremium", "Annual premium"], ["cumulativePremium", "Cumulative premium"],
      ["coiCharge", "COI charge"], ["policyFee", "Policy fee"], ["guaranteedInterest", "Interest"],
      ["endingPolicyValue", "Ending value"], ["surrenderCharge", "Surrender charge"],
      ["surrenderValue", "Surrender value"], ["deathBenefit", "Death benefit"],
      ["netAmountAtRisk", "Net amount at risk"],
    ];
    const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
    const csv = [columns.map(([, label]) => escape(label)).join(","), ...rows.map((row) => columns.map(([key]) => escape(row[key])).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "diagnostic-projection.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="logic-workspace">
      <header className="logic-workspace__header">
        <div>
          <a className="logic-workspace__back" href="/web">← All workspaces</a>
          <p className="logic-workspace__eyebrow">Projection model</p>
          <h1>Projection logic</h1>
          <p className="muted">Edit scenario inputs directly in the graph, trace dependencies, and inspect where model data is missing or provisional.</p>
        </div>
        <div className="logic-workspace__actions">
          <a className="button button-secondary" href={`/web?workspace=${encodeURIComponent(workspaceId)}&view=details`}>More details</a>
          <span className={`logic-workspace__run-state${dirty ? " is-dirty" : ""}`}>{dirty ? "Inputs changed" : "Projection current"}</span>
          <button type="button" className="button" disabled={running} onClick={runProjection}>
            {running ? "Running projection…" : "Run projection"}
          </button>
        </div>
      </header>

      <div className="logic-workspace__summary" aria-label="Projection logic status">
        <span><strong>{inputNodes.length}</strong> inputs</span>
        <span><strong>{ruleNodes.length}</strong> rules</span>
        <span className={provisionalCount ? "is-warning" : ""}><strong>{provisionalCount}</strong> provisional</span>
        <span className={missingCount ? "is-danger" : ""}><strong>{missingCount}</strong> missing</span>
      </div>

      {error && <p className="error">{error}</p>}
      {runMessage && <p className="logic-workspace__success" role="status">{runMessage}</p>}
      {projectionGraph?.nodes?.length ? (
        <ProjectionLogicGraph
          definition={projectionGraph}
          editableValues={values}
          onInputChange={updateInput}
          onGenerateSyntheticCoi={generateSyntheticCoi}
          generatingSyntheticCoi={generatingSynthetic}
          onRemoveSyntheticCoi={removeSyntheticCoi}
          removingSyntheticCoi={removingSynthetic}
        />
      ) : (
        <section className="card"><p className="muted">No projection mechanics are available for this workspace yet.</p></section>
      )}

      {syntheticPreview && (
        <section id="synthetic-coi-review" className="card synthetic-coi-review">
          <div className="synthetic-coi-review__header">
            <div>
              <p className="logic-workspace__eyebrow">AI agent proposal</p>
              <h2>Review synthetic COI table</h2>
              <p className="synthetic-coi-review__warning">{syntheticPreview.disclaimer}</p>
            </div>
            <button type="button" className="button button-secondary" onClick={() => setSyntheticPreview(null)}>Discard</button>
          </div>
          <div className="synthetic-coi-review__metrics">
            <article><span>Rows</span><strong>{syntheticPreview.rowCount}</strong></article>
            <article><span>Minimum rate</span><strong>{syntheticPreview.minimumRate} / $1,000</strong></article>
            <article><span>Maximum rate</span><strong>{syntheticPreview.maximumRate} / $1,000</strong></article>
            <article><span>Model</span><strong>{syntheticPreview.model || "Not recorded"}</strong></article>
          </div>
          <details open>
            <summary>Agent assumptions</summary>
            <pre className="synthetic-coi-review__parameters">{JSON.stringify(syntheticPreview.parameters, null, 2)}</pre>
          </details>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Attained age</th><th>Sex</th><th>Risk class</th><th>Tobacco</th><th>Annual rate / $1,000</th></tr></thead>
              <tbody>{(syntheticPreview.sampleRows ?? []).map((row: any, index: number) => (
                <tr key={`${row.attained_age}-${row.sex}-${row.risk_class}-${index}`}>
                  <td>{row.attained_age}</td><td>{row.sex}</td><td>{row.risk_class}</td><td>{row.tobacco_status}</td><td>{row.rate}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="synthetic-coi-review__actions">
            <button type="button" className="button" disabled={acceptingSynthetic} onClick={acceptSyntheticCoi}>
              {acceptingSynthetic ? "Accepting…" : "Accept synthetic table"}
            </button>
            <button type="button" className="button button-secondary" onClick={downloadSyntheticCoiCsv}>Download CSV</button>
            <span className="muted">Acceptance records synthetic provenance; it never becomes filed evidence.</span>
          </div>
        </section>
      )}

      <section id="projection-results" className="card logic-results">
        <div className="logic-results__header">
          <div>
            <p className="logic-workspace__eyebrow">Projection output</p>
            <h2>Projection results</h2>
            <p className="muted">These diagnostic values use the inputs and assumptions shown in the graph above.</p>
          </div>
          {rows.length > 0 && <button type="button" className="button button-secondary" onClick={downloadProjectionCsv}>Download ledger CSV</button>}
        </div>
        {rows.length > 0 ? (
          <>
            <div className="logic-results__metrics">
              <article><span>Projection horizon</span><strong>{metrics.maximumYear ?? rows.length} years</strong></article>
              <article><span>Final cash value</span><strong>{formatCurrency(metrics.finalCashValue ?? rows[rows.length - 1]?.cashValue)}</strong></article>
              <article><span>Final surrender value</span><strong>{formatCurrency(metrics.finalSurrenderValue ?? rows[rows.length - 1]?.surrenderValue)}</strong></article>
              <article><span>Final net amount at risk</span><strong>{formatCurrency(metrics.finalNetAmountAtRisk ?? rows[rows.length - 1]?.netAmountAtRisk)}</strong></article>
            </div>
            <ProjectionChart rows={rows} />
            <details className="logic-results__ledger">
              <summary>{rows.length}-year annual projection ledger</summary>
              <div className="table-scroll projection-ledger">
                <table className="kv-table">
                  <thead><tr><th>Year</th><th>Age</th><th>Opening value</th><th>Premium</th><th>COI</th><th>Policy fee</th><th>Interest</th><th>Ending value</th><th>Surrender charge</th><th>Surrender value</th><th>Death benefit</th><th>Net amount at risk</th></tr></thead>
                  <tbody>{rows.map((row, index) => <tr key={row.year ?? index}><td>{row.year}</td><td>{row.attainedAge}</td><td>{formatCurrency(row.openingPolicyValue)}</td><td>{formatCurrency(row.annualPremium)}</td><td>{formatCurrency(row.coiCharge)}</td><td>{formatCurrency(row.policyFee)}</td><td>{formatCurrency(row.guaranteedInterest)}</td><td>{formatCurrency(row.endingPolicyValue ?? row.policyValue)}</td><td>{formatCurrency(row.surrenderCharge)}</td><td>{formatCurrency(row.surrenderValue)}</td><td>{formatCurrency(row.deathBenefit)}</td><td>{formatCurrency(row.netAmountAtRisk)}</td></tr>)}</tbody>
                </table>
              </div>
            </details>
          </>
        ) : <p className="muted">Run the projection to generate results.</p>}
      </section>
    </div>
  );
};
