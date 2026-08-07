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

const REQUIRED_PROJECTION_SELECTORS = [
  ["sex", "sex"],
  ["risk_class", "risk class"],
  ["tobacco_status", "tobacco / nicotine status"],
] as const;

export const ProjectionLogicPage: React.FC<ProjectionLogicPageProps> = ({ snapshot, workspaceId }) => {
  const [illustration, setIllustration] = React.useState(snapshot?.illustration ?? null);
  const [projectionGraph, setProjectionGraph] = React.useState<ProjectionGraphDefinition | null>(snapshot?.projectionGraph ?? null);
  const [executableMechanics, setExecutableMechanics] = React.useState<any>(snapshot?.executableMechanics ?? null);
  const [values, setValues] = React.useState<Record<string, string | number>>(() => initialGraphInputs(snapshot));
  const [dirty, setDirty] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [runMessage, setRunMessage] = React.useState<string | null>(null);
  const [selectorFallbackIssues, setSelectorFallbackIssues] = React.useState<any[]>([]);
  const [syntheticPreview, setSyntheticPreview] = React.useState<any>(null);
  const [generatingSynthetic, setGeneratingSynthetic] = React.useState(false);
  const [acceptingSynthetic, setAcceptingSynthetic] = React.useState(false);
  const [removingSynthetic, setRemovingSynthetic] = React.useState(false);
  const [generatingSyntheticSurrender, setGeneratingSyntheticSurrender] = React.useState(false);
  const [removingSyntheticSurrender, setRemovingSyntheticSurrender] = React.useState(false);
  const [acceptingFiledMechanic, setAcceptingFiledMechanic] = React.useState<string | null>(null);

  const graphNodes = projectionGraph?.nodes ?? [];
  const inputNodes = graphNodes.filter((node) => node.kind === "input" || (node.kind === "unmodeled" && Boolean(node.inputId)));
  const ruleNodes = graphNodes.filter((node) => node.kind === "rule" || (node.kind === "unmodeled" && !node.inputId));
  const rows = (illustration?.rows ?? []) as WorkspaceRow[];
  const metrics = illustration?.metrics ?? {};
  const reconciliation = illustration?.reconciliation;
  const missingCount = graphNodes.filter((node) => node.status === "missing").length;
  const provisionalCount = graphNodes.filter((node) => node.status === "provisional").length;
  const filedCandidates = ["coi", "surrender", "fees", "nar_factors", "corridor"].flatMap((mechanic) => {
    const grouped = (executableMechanics?.candidates?.[mechanic] || []).filter(
      (candidate: any) => candidate.reviewStatus === "review_required" && candidate.rows?.length,
    );
    if (grouped.length) return grouped;
    const legacyRows = executableMechanics?.mechanics?.[mechanic] || [];
    return executableMechanics?.status?.[mechanic] === "filed_evidence_review_required" && legacyRows.length
      ? [{ id: mechanic, mechanic, rows: legacyRows, rowCount: legacyRows.length }]
      : [];
  });
  const missingSelectors = REQUIRED_PROJECTION_SELECTORS
    .filter(([key]) => !String(values[key] ?? "").trim())
    .map(([, label]) => label);
  const selectorReady = missingSelectors.length === 0;

  const updateInput = (inputId: string, value: string) => {
    setValues((current) => ({ ...current, [inputId]: value }));
    setDirty(true);
  };

  const runProjection = async (allowSelectorFallback = false) => {
    const issueAge = Number(values.issue_age);
    const faceAmount = Number(values.face_amount);
    const modalPremium = Number(values.premium);
    const policyFeeText = String(values.policy_fee ?? "").trim();
    const policyFeeAnnual = policyFeeText === "" ? undefined : Number(policyFeeText);
    if (!selectorReady) {
      setError(`Complete ${missingSelectors.join(", ")} before running the projection so the correct filed tables can be selected.`);
      return;
    }
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
    setSelectorFallbackIssues([]);
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
          allowSelectorFallback,
        }),
      });
      if (!response.ok) {
        const raw = await response.text();
        let detail: any = raw;
        try { detail = JSON.parse(raw)?.detail ?? raw; } catch { /* retain response text */ }
        if (response.status === 409 && detail?.code === "selector_table_mismatch") {
          setSelectorFallbackIssues(detail.issues || []);
          throw new Error(detail.message || "Accepted filed tables do not cover this underwriting scenario.");
        }
        throw new Error(typeof detail === "string" ? detail : detail?.message || `Projection failed (HTTP ${response.status})`);
      }
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
      window.setTimeout(() => document.getElementById("synthetic-schedule-review")?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
    } catch (err: any) {
      setError(err?.message || "Synthetic COI generation failed.");
    } finally {
      setGeneratingSynthetic(false);
    }
  };

  const acceptFiledMechanic = async (candidate: any) => {
    const mechanic = candidate.mechanic;
    setAcceptingFiledMechanic(candidate.id);
    setError(null);
    try {
      const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/filed-mechanics/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mechanic, candidateId: candidate.id === mechanic ? undefined : candidate.id }),
      });
      if (!response.ok) throw new Error((await response.text()) || `Acceptance failed (HTTP ${response.status})`);
      const body = await response.json();
      setExecutableMechanics((current: any) => ({
        ...(current || {}),
        status: { ...(current?.status || {}), [mechanic]: body.status },
        reviews: { ...(current?.reviews || {}), [mechanic]: body.review },
        candidates: {
          ...(current?.candidates || {}),
          [mechanic]: (current?.candidates?.[mechanic] || []).map((item: any) =>
            item.id === candidate.id ? { ...item, reviewStatus: "accepted" } : item),
        },
      }));
      await runProjection();
      const label = mechanic === "coi" ? "COI table" : mechanic === "surrender" ? "surrender schedule" : mechanic === "nar_factors" ? "NAR factor" : mechanic === "corridor" ? "minimum death-benefit corridor" : "fee schedule";
      const remaining = Number(body.remainingCandidateCount || 0);
      setRunMessage(`Filed ${label} accepted and applied (${body.activeRowCount} active rows).${remaining ? ` ${remaining} additional candidate${remaining === 1 ? "" : "s"} available for review.` : ""}`);
    } catch (err: any) {
      setError(err?.message || "The filed table could not be accepted.");
    } finally {
      setAcceptingFiledMechanic(null);
    }
  };

  const generateSyntheticSurrender = async () => {
    setGeneratingSyntheticSurrender(true);
    setError(null);
    try {
      const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/synthetic-surrender/preview`, { method: "POST" });
      if (!response.ok) throw new Error((await response.text()) || `Generation failed (HTTP ${response.status})`);
      const body = await response.json();
      setSyntheticPreview(body.preview ?? null);
      window.setTimeout(() => document.getElementById("synthetic-schedule-review")?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
    } catch (err: any) {
      setError(err?.message || "Synthetic surrender generation failed.");
    } finally {
      setGeneratingSyntheticSurrender(false);
    }
  };

  const acceptSyntheticCoi = async () => {
    if (!syntheticPreview) return;
    setAcceptingSynthetic(true);
    setError(null);
    try {
      const mechanicPath = syntheticPreview.mechanic === "surrender" ? "synthetic-surrender" : "synthetic-coi";
      const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/${mechanicPath}/accept`, {
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
      setRunMessage(`Synthetic ${syntheticPreview.mechanic === "surrender" ? "surrender schedule" : "COI table"} accepted and applied to the projection.`);
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

  const removeSyntheticSurrender = async () => {
    setRemovingSyntheticSurrender(true);
    setError(null);
    try {
      const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/synthetic-surrender`, { method: "DELETE" });
      if (!response.ok) throw new Error((await response.text()) || `Removal failed (HTTP ${response.status})`);
      await runProjection();
      setRunMessage("Synthetic surrender schedule removed. The simplified fallback is active again.");
    } catch (err: any) {
      setError(err?.message || "Synthetic surrender schedule could not be removed.");
    } finally {
      setRemovingSyntheticSurrender(false);
    }
  };

  const downloadSyntheticCoiCsv = () => {
    const syntheticRows = syntheticPreview?.rows ?? [];
    if (!syntheticRows.length) return;
    const fields = syntheticPreview?.mechanic === "surrender"
      ? ["duration", "charge", "charge_unit"]
      : ["attained_age", "sex", "risk_class", "tobacco_status", "rate", "rate_unit"];
    const csv = [fields.join(","), ...syntheticRows.map((row: any) => fields.map((field) => `"${String(row[field] ?? "").replace(/"/g, '""')}"`).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = syntheticPreview?.mechanic === "surrender" ? "synthetic-surrender-schedule.csv" : "synthetic-coi-table.csv";
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
          <span className={`logic-workspace__run-state${dirty || !selectorReady ? " is-dirty" : ""}`}>
            {!selectorReady ? `Projection needs ${missingSelectors.length} selector${missingSelectors.length === 1 ? "" : "s"}` : dirty ? "Inputs changed" : "Projection current"}
          </span>
          <button type="button" className="button" disabled={running || !selectorReady} onClick={() => runProjection(false)}>
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

      {!selectorReady && (
        <div className="logic-workspace__readiness" role="status">
          <strong>Complete the underwriting scenario</strong>
          <span>Select {missingSelectors.join(", ")} in the graph. These values determine which filed COI and expense rows apply.</span>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {selectorFallbackIssues.length > 0 && (
        <div className="logic-workspace__selector-fallback" role="alert">
          <strong>No exact filed-table match</strong>
          {selectorFallbackIssues.map((issue: any) => (
            <span key={issue.mechanic}>{issue.message} Affected policy years: {issue.years?.join(", ")}.</span>
          ))}
          <button type="button" className="button button-secondary" disabled={running} onClick={() => runProjection(true)}>
            Run with disclosed fallback
          </button>
        </div>
      )}
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
          onGenerateSyntheticSurrender={generateSyntheticSurrender}
          generatingSyntheticSurrender={generatingSyntheticSurrender}
          onRemoveSyntheticSurrender={removeSyntheticSurrender}
          removingSyntheticSurrender={removingSyntheticSurrender}
        />
      ) : (
        <section className="card"><p className="muted">No projection mechanics are available for this workspace yet.</p></section>
      )}

      {filedCandidates.length > 0 && (
        <section className="card filed-mechanics-review">
          <div>
            <p className="logic-workspace__eyebrow">Uploaded document evidence</p>
            <h2>Review filed PDF mechanics</h2>
            <p className="muted">These tables were read from uploaded filed-form PDFs. Review the source and values before allowing them to drive the projection.</p>
          </div>
          <div className="filed-mechanics-review__grid">
            {filedCandidates.map((candidate: any) => {
              const mechanic = candidate.mechanic;
              const candidateRows = candidate.rows || [];
              const first = candidateRows[0] || {};
              const last = candidateRows[candidateRows.length - 1] || {};
              const provenance = first.provenance || {};
              const value = (row: any) => mechanic === "coi" ? row.rate : mechanic === "surrender" ? row.charge : mechanic === "nar_factors" ? row.factor : mechanic === "corridor" ? row.percentage : row.amount;
              const feeComponents = (candidate.components || []).map((item: string) => item.replaceAll("_", " ")).join(", ");
              return (
                <article key={candidate.id} className="filed-mechanics-review__candidate">
                  <div>
                    <span className="filed-mechanics-review__badge">Review required</span>
                    <h3>{mechanic === "coi" ? "COI rate table" : mechanic === "surrender" ? "Surrender charge schedule" : mechanic === "nar_factors" ? "Net amount at risk factor" : mechanic === "corridor" ? "Minimum death benefit percentages" : "Policy fee schedule"}</h3>
                  </div>
                  <dl>
                    <div><dt>Rows</dt><dd>{candidate.rowCount || candidateRows.length}</dd></div>
                    <div><dt>Source{candidate.sources?.length > 1 ? "s" : ""}</dt><dd>
                      {candidate.sources?.length > 1
                        ? candidate.sources.map((source: any) => `${source.filename || "Uploaded PDF"}${source.page ? ` · page ${source.page}` : ""}`).join("; ")
                        : <>{candidate.filename || provenance.filename || "Uploaded PDF"}{candidate.page || provenance.page ? ` · page ${candidate.page || provenance.page}` : ""}</>}
                    </dd></div>
                    <div><dt>Table</dt><dd>{candidate.tableHeading || provenance.tableHeading || "Filed table"}</dd></div>
                    {mechanic === "fees" && feeComponents && <div><dt>Charge type</dt><dd>{feeComponents}</dd></div>}
                    <div><dt>Value basis</dt><dd>{String(candidate.valueBasis || provenance.valueBasis || "filed").replaceAll("_", " ")}</dd></div>
                    {candidate.selectors && Object.keys(candidate.selectors).length > 0 && (
                      <div><dt>Applies to</dt><dd>{Object.entries(candidate.selectors).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join(" · ")}</dd></div>
                    )}
                    <div><dt>Range</dt><dd>Duration {first.duration ?? "—"}: {value(first) ?? "—"} → duration {last.duration ?? "—"}: {value(last) ?? "—"}</dd></div>
                  </dl>
                  <button type="button" className="button" disabled={acceptingFiledMechanic !== null} onClick={() => acceptFiledMechanic(candidate)}>
                    {acceptingFiledMechanic === candidate.id ? "Accepting…" : "Accept and add to projection"}
                  </button>
                </article>
              );
            })}
          </div>
        </section>
      )}

      {syntheticPreview && (
        <section id="synthetic-schedule-review" className="card synthetic-coi-review">
          <div className="synthetic-coi-review__header">
            <div>
              <p className="logic-workspace__eyebrow">AI agent proposal</p>
              <h2>Review synthetic {syntheticPreview.mechanic === "surrender" ? "surrender schedule" : "COI table"}</h2>
              <p className="synthetic-coi-review__warning">{syntheticPreview.disclaimer}</p>
            </div>
            <button type="button" className="button button-secondary" onClick={() => setSyntheticPreview(null)}>Discard</button>
          </div>
          <div className="synthetic-coi-review__metrics">
            <article><span>Rows</span><strong>{syntheticPreview.rowCount}</strong></article>
            {syntheticPreview.mechanic === "surrender" ? (
              <><article><span>Minimum charge</span><strong>{(Number(syntheticPreview.minimumCharge) * 100).toFixed(2)}% of face</strong></article><article><span>Maximum charge</span><strong>{(Number(syntheticPreview.maximumCharge) * 100).toFixed(2)}% of face</strong></article></>
            ) : (
              <><article><span>Minimum rate</span><strong>{syntheticPreview.minimumRate} / $1,000</strong></article><article><span>Maximum rate</span><strong>{syntheticPreview.maximumRate} / $1,000</strong></article></>
            )}
            <article><span>Model</span><strong>{syntheticPreview.model || "Not recorded"}</strong></article>
          </div>
          <details open>
            <summary>Agent assumptions</summary>
            <pre className="synthetic-coi-review__parameters">{JSON.stringify(syntheticPreview.parameters, null, 2)}</pre>
          </details>
          <div className="table-scroll">
            <table>
              <thead>{syntheticPreview.mechanic === "surrender" ? <tr><th>Duration</th><th>Charge</th><th>Unit</th></tr> : <tr><th>Attained age</th><th>Sex</th><th>Risk class</th><th>Tobacco</th><th>Annual rate / $1,000</th></tr>}</thead>
              <tbody>{(syntheticPreview.sampleRows ?? []).map((row: any, index: number) => (
                syntheticPreview.mechanic === "surrender" ? <tr key={`${row.duration}-${index}`}><td>{row.duration}</td><td>{(Number(row.charge) * 100).toFixed(2)}%</td><td>{row.charge_unit}</td></tr> : <tr key={`${row.attained_age}-${row.sex}-${row.risk_class}-${index}`}><td>{row.attained_age}</td><td>{row.sex}</td><td>{row.risk_class}</td><td>{row.tobacco_status}</td><td>{row.rate}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <div className="synthetic-coi-review__actions">
            <button type="button" className="button" disabled={acceptingSynthetic} onClick={acceptSyntheticCoi}>
              {acceptingSynthetic ? "Accepting…" : `Accept synthetic ${syntheticPreview.mechanic === "surrender" ? "schedule" : "table"}`}
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
            {reconciliation && (
              <div className={`logic-results__reconciliation ${reconciliation.passed ? "is-passed" : "is-failed"}`} role="status">
                <strong>{reconciliation.passed ? "Projection ledger reconciled" : "Projection reconciliation failed"}</strong>
                <span>
                  {reconciliation.passed
                    ? `${reconciliation.checkCount} calculation checks passed across ${rows.length} policy years. Maximum residual ${formatCurrency(reconciliation.maxResidual)}.`
                    : `${reconciliation.failures?.length || 0} checks failed in policy years ${(reconciliation.failedYears || []).join(", ")}.`}
                </span>
              </div>
            )}
            {illustration?.selectorIntegrity && (
              <div className={`logic-results__selector-integrity ${illustration.selectorIntegrity.passed ? "is-passed" : "is-fallback"}`}>
                <strong>{illustration.selectorIntegrity.passed ? "Filed classification matched" : "Projection used authorized selector fallback"}</strong>
                <span>
                  Sex: {illustration.selectorIntegrity.scenario?.sex} · Risk class: {illustration.selectorIntegrity.scenario?.riskClass} · Tobacco status: {illustration.selectorIntegrity.scenario?.tobaccoStatus}
                </span>
                {!illustration.selectorIntegrity.passed && <span>{illustration.selectorIntegrity.issues?.map((issue: any) => issue.mechanic.replaceAll("_", " ")).join(", ")} did not have an exact match.</span>}
              </div>
            )}
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
