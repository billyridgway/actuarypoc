import React from "react";
import { CapabilityAlignmentItem, GraphInputConfig, MechanicsStep, ProjectionInput, ProjectionLogicGraph } from "./ProductWorkspacePage";

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

const uniqueOptions = (values: unknown[]): string[] => {
  const seen = new Set<string>();
  for (const value of values) {
    const label = String(value ?? "").trim();
    if (label) seen.add(label);
  }
  return [...seen];
};

const graphInputConfigs = (snapshot: any, values: Record<string, string | number>): Record<string, GraphInputConfig> => {
  const configuredRiskClasses = Array.isArray(snapshot?.productUnderstanding?.riskClasses)
    ? snapshot.productUnderstanding.riskClasses
    : [];
  const riskClasses = configuredRiskClasses.length
    ? uniqueOptions(configuredRiskClasses)
    : uniqueOptions([values.risk_class]);
  const sexValues = ["F", "M"];
  const tobaccoValues = ["Non-Tobacco", "Tobacco"];

  return {
    issue_age: { kind: "number", min: 0, max: 120, step: 1, help: "Whole number from 0 to 120" },
    face_amount: { kind: "number", min: 1, step: 1000, help: "Must be greater than $0" },
    premium: { kind: "number", min: 1, step: 100, help: "Must be greater than $0" },
    policy_fee: {
      kind: "number",
      min: 0,
      step: 0.01,
      enteredStatus: "provisional",
      placeholder: "Enter annual fee",
      help: "Scenario assumption; $0 must be entered explicitly",
    },
    premium_mode: {
      kind: "select",
      options: [
        { value: "ANNUAL", label: "Annual" },
        { value: "SEMIANNUAL", label: "Semiannual" },
        { value: "QUARTERLY", label: "Quarterly" },
        { value: "MONTHLY", label: "Monthly" },
      ],
    },
    sex: {
      kind: "select",
      placeholder: "Select sex",
      options: sexValues.map((value) => ({ value, label: value === "F" ? "Female (F)" : value === "M" ? "Male (M)" : value })),
    },
    risk_class: {
      kind: "select",
      placeholder: riskClasses.length ? "Select risk class" : "No risk classes available",
      options: riskClasses.map((value) => ({ value, label: value })),
      help: riskClasses.length ? "From this product's configured risk classes" : "Upload evidence defining valid risk classes",
    },
    tobacco_status: {
      kind: "select",
      placeholder: "Select tobacco status",
      options: tobaccoValues.map((value) => ({ value, label: value })),
    },
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
  const inputConfigs = React.useMemo(() => graphInputConfigs(snapshot, values), [snapshot, values]);
  const capabilities = (snapshot?.capabilityAssessment?.items ?? []) as CapabilityAlignmentItem[];
  const missingCount = inputs.filter((input) => ["missing", "not_available"].includes(String(input.status || "").toLowerCase())).length;
  const provisionalCount = inputs.filter((input) => ["placeholder", "derived_placeholder", "default", "diagnostic", "not_supplied", "scenario_assumption"].includes(String(input.status || "").toLowerCase())).length;

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
        <ProjectionLogicGraph
          inputs={inputs}
          steps={steps}
          editableValues={values}
          onInputChange={updateInput}
          inputConfigs={inputConfigs}
          capabilities={capabilities}
        />
      ) : (
        <section className="card"><p className="muted">No projection mechanics are available for this workspace yet.</p></section>
      )}
    </div>
  );
};
