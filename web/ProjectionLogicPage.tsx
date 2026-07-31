import React from "react";
import { MechanicsStep, ProjectionInput, ProjectionLogicGraph } from "./ProductWorkspacePage";

interface ProjectionLogicPageProps {
  snapshot: any;
  workspaceId: string;
}

const initialGraphInputs = (snapshot: any) => {
  const request = snapshot?.illustration?.request || {};
  const firstRow = snapshot?.illustration?.rows?.[0] || {};
  return {
    issue_age: Number(request.age ?? 45),
    face_amount: Number(request.faceAmount ?? 100000),
    premium: Number(firstRow.modalPremium ?? firstRow.annualPremium ?? 3000),
    premium_mode: String(request.premiumMode ?? "ANNUAL"),
    sex: String(request.sex ?? ""),
    risk_class: String(request.riskClass ?? ""),
    tobacco_status: String(request.tobaccoStatus ?? ""),
  };
};

export const ProjectionLogicPage: React.FC<ProjectionLogicPageProps> = ({ snapshot, workspaceId }) => {
  const [illustration, setIllustration] = React.useState(snapshot?.illustration ?? null);
  const [mechanics, setMechanics] = React.useState(snapshot?.mechanicsExplanation ?? null);
  const [values, setValues] = React.useState<Record<string, string | number>>(() => initialGraphInputs(snapshot));
  const [dirty, setDirty] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const inputs = (illustration?.inputs ?? []) as ProjectionInput[];
  const steps = (mechanics?.steps ?? []) as MechanicsStep[];
  const missingCount = inputs.filter((input) => ["missing", "not_available"].includes(String(input.status || "").toLowerCase())).length;
  const provisionalCount = inputs.filter((input) => ["placeholder", "derived_placeholder", "default", "diagnostic", "not_supplied"].includes(String(input.status || "").toLowerCase())).length;

  const updateInput = (inputId: string, value: string) => {
    setValues((current) => ({ ...current, [inputId]: value }));
    setDirty(true);
  };

  const runProjection = async () => {
    setRunning(true);
    setError(null);
    try {
      const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/projection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          issueAge: Number(values.issue_age),
          faceAmount: Number(values.face_amount),
          modalPremium: Number(values.premium),
          premiumMode: String(values.premium_mode),
          sex: String(values.sex || ""),
          riskClass: String(values.risk_class || ""),
          tobaccoStatus: String(values.tobacco_status || ""),
        }),
      });
      if (!response.ok) throw new Error((await response.text()) || `Projection failed (HTTP ${response.status})`);
      const body = await response.json();
      setIllustration(body.illustration ?? null);
      setMechanics(body.mechanicsExplanation ?? null);
      setDirty(false);
    } catch (err: any) {
      setError(err?.message || "Projection failed.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="logic-workspace">
      <header className="logic-workspace__header">
        <div>
          <a className="logic-workspace__back" href={`/web?workspace=${encodeURIComponent(workspaceId)}`}>← Product workspace</a>
          <p className="logic-workspace__eyebrow">Projection model</p>
          <h1>Projection logic</h1>
          <p className="muted">Edit scenario inputs directly in the graph, trace dependencies, and inspect where model data is missing or provisional.</p>
        </div>
        <div className="logic-workspace__actions">
          <span className={`logic-workspace__run-state${dirty ? " is-dirty" : ""}`}>{dirty ? "Inputs changed" : "Projection current"}</span>
          <button type="button" className="button" disabled={running} onClick={runProjection}>
            {running ? "Running projection…" : "Run projection"}
          </button>
        </div>
      </header>

      <div className="logic-workspace__summary" aria-label="Projection logic status">
        <span><strong>{inputs.length}</strong> inputs</span>
        <span><strong>{steps.length}</strong> rules</span>
        <span className={provisionalCount ? "is-warning" : ""}><strong>{provisionalCount}</strong> provisional</span>
        <span className={missingCount ? "is-danger" : ""}><strong>{missingCount}</strong> missing</span>
      </div>

      {error && <p className="error">{error}</p>}
      {steps.length ? (
        <ProjectionLogicGraph inputs={inputs} steps={steps} editableValues={values} onInputChange={updateInput} />
      ) : (
        <section className="card"><p className="muted">No projection mechanics are available for this workspace yet.</p></section>
      )}
    </div>
  );
};
