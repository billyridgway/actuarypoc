import React from "react";

// Minimal POC types for the P12TRF Product Model Review screen. These mirror
// the static payload returned by /api/product-model-review/p12trf and are
// intentionally simple and POC-only.

export interface ProductModelReview {
  product: {
    code: string;
    name: string;
    definitionId?: string | null;
  };
  scope: {
    filings: { id: string; name: string }[];
    featuresModeled: string[];
    featuresNotModeled: string[];
    confidence: "low" | "medium" | "high";
    pocLabel?: string;
  };
  traceability: {
    rules: {
      id: string;
      name: string;
      filingId: string;
      page?: number;
      section?: string;
      snippet: string;
      interpretation: string;
      confidence: "low" | "medium" | "high";
      reviewStatus: "not_reviewed" | "approved" | "needs_change";
    }[];
  };
  rates: {
    cellsChecked: number;
    cellsMatched: number;
    exceptions: any[];
    spotChecks: {
      age: number;
      termYears: number;
      riskClass: string;
      faceAmount: number;
      filedPremium: number;
      modelPremium: number;
      diff: number;
      status: string;
    }[];
  };
  scenarios: {
    id: string;
    name: string;
    inputs: {
      age: number | string;
      sex: string;
      smokerClass: string;
      termYears: number;
      faceAmount: number;
      premiumMode: string;
    };
    expectedBehavior: string[];
    modelBehaviorSummary: string;
    status: string;
    ruleIds: string[];
    runId?: string | null;
    projectionKey?: string | null;
    checks?: {
      noDeathBenefitAfterTerm?: boolean;
      deathBenefitApproxFaceDuringTerm?: boolean;
    };
    projection?: {
      years?: (number | string)[];
      deathBenefits?: (number | string)[];
    };
    projectionTable?: {
      year: number | string;
      attainedAge?: number | string | null;
      premium?: number | string | null;
      deathBenefit?: number | string | null;
      cashValue?: number | string | null;
      status?: string | null;
    }[];
  }[];
  assumptions: {
    filed: any[];
    aiProposed: {
      id: string;
      name: string;
      value: string;
      source: string;
      sensitivitySummary: string;
      humanApproval: string;
    }[];
  };
  gaps: {
    missingFeatures: {
      id: string;
      description: string;
      severity: string;
    }[];
    ambiguousLanguage: any[];
  };
}

interface ProductModelReviewPageProps {
  review: ProductModelReview;
}

export const ProductModelReviewPage: React.FC<ProductModelReviewPageProps> = ({ review }) => {
  const { product, scope, traceability, rates, scenarios, assumptions, gaps } = review;

  const totalScenarios = scenarios.length;
  const scenarioPassCount = scenarios.filter((s) => s.status.toLowerCase() === "pass").length;
  const scenarioNeedsReviewCount = scenarios.filter((s) => s.status.toLowerCase() !== "pass").length;

  const cellsChecked = rates.cellsChecked ?? 0;
  const cellsMatched = rates.cellsMatched ?? 0;
  const hasRateExceptions = (rates.exceptions && rates.exceptions.length > 0) || false;

  const assumptionsNeedingApproval = assumptions.aiProposed?.length ?? 0;
  const knownGaps = gaps.missingFeatures?.length ?? 0;

  const [selectedScenarioId, setSelectedScenarioId] = React.useState<string | null>(
    scenarios.length > 0 ? scenarios[0].id : null,
  );
  const selectedScenario =
    scenarios.find((s) => s.id === selectedScenarioId) || (scenarios.length > 0 ? scenarios[0] : null);

  const normaliseInputs = (inputs: any) => {
    const age = inputs && inputs.age !== undefined ? inputs.age : "unknown";
    const sex = inputs && typeof inputs.sex === "string" && inputs.sex ? inputs.sex : "unknown";
    const smokerClass =
      inputs && typeof inputs.smokerClass === "string" && inputs.smokerClass ? inputs.smokerClass : "unknown";
    const termYears =
      inputs && typeof inputs.termYears === "number" && !Number.isNaN(inputs.termYears) ? inputs.termYears : 0;
    const faceAmount =
      inputs && typeof inputs.faceAmount === "number" && !Number.isNaN(inputs.faceAmount) ? inputs.faceAmount : 0;
    const premiumMode =
      inputs && typeof inputs.premiumMode === "string" && inputs.premiumMode
        ? inputs.premiumMode.toUpperCase()
        : "UNKNOWN";

    return { age, sex, smokerClass, termYears, faceAmount, premiumMode };
  };

  const selectedInputs = selectedScenario ? normaliseInputs(selectedScenario.inputs || {}) : null;
  const selectedFaceDisplay =
    selectedInputs && typeof selectedInputs.faceAmount === "number"
      ? selectedInputs.faceAmount.toLocaleString()
      : selectedInputs
        ? String(selectedInputs.faceAmount)
        : null;

  // Simple, MVP-only Final Actuary Decision form state.
  const [reviewer, setReviewer] = React.useState("");
  const [decision, setDecision] = React.useState("");
  const [exclusions, setExclusions] = React.useState("");
  const [comments, setComments] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [saveMessage, setSaveMessage] = React.useState<string | null>(null);
  const [saveError, setSaveError] = React.useState<string | null>(null);

  const onSubmitDecision = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveMessage(null);
    setSaveError(null);

    const trimmedDecision = decision.trim();
    if (!trimmedDecision) {
      setSaveError("Please select a decision.");
      return;
    }

    setSaving(true);
    try {
      const payload = {
        reviewer: reviewer.trim() || undefined,
        decision: trimmedDecision,
        exclusions: exclusions.trim() || undefined,
        comments: comments.trim() || undefined,
      };

      const res = await fetch(`/api/product-model-review/${encodeURIComponent(product.code)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }

      const data = (await res.json()) as {
        id?: number;
        created_at?: string;
      };

      setSaveMessage(
        data && data.created_at
          ? `Decision saved at ${data.created_at}.`
          : "Decision saved (timestamp unavailable).",
      );
    } catch (err: any) {
      setSaveError(err?.message || "Failed to save decision.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="run-detail-page">
      <header className="card">
        <h1>Product Model Review – {product.name}</h1>
        <p>
          <strong>Product code:</strong> {product.code}
          {product.definitionId && (
            <>
              {" "}
              <span className="muted">(definition: {product.definitionId})</span>
            </>
          )}
        </p>
        <p>
          <strong>Filings (POC placeholders):</strong>{" "}
          {scope.filings.map((f) => f.id).join(", ")}
        </p>
        <p>
          <strong>Model confidence (POC):</strong> {scope.confidence}
        </p>
        {scope.pocLabel && <p className="muted">{scope.pocLabel}</p>}
      </header>

      <section className="card">
        <h2>Review Summary (POC)</h2>
        <p className="muted">
          This summary is derived from the current Product Model Review data for P12TRF.
        </p>
        <table className="kv-table">
          <tbody>
            <tr>
              <th>Product</th>
              <td>
                {product.name} ({product.code})
              </td>
            </tr>
            <tr>
              <th>Scenarios reviewed</th>
              <td>
                {totalScenarios} total &mdash; {scenarioPassCount} pass, {scenarioNeedsReviewCount} flagged
              </td>
            </tr>
            <tr>
              <th>Rate spot checks</th>
              <td>
                {cellsChecked} checked, {cellsMatched} matched
                {hasRateExceptions && <span className="warning"> (exceptions present)</span>}
              </td>
            </tr>
            <tr>
              <th>Assumptions requiring approval</th>
              <td>{assumptionsNeedingApproval}</td>
            </tr>
            <tr>
              <th>Known gaps</th>
              <td>{knownGaps} missing / unmodeled feature(s) recorded</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>Product Scope Summary</h2>
        <div className="two-column">
          <div>
            <h3>Features modeled</h3>
            <ul>
              {scope.featuresModeled.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3>Features NOT modeled (POC)</h3>
            <ul>
              {scope.featuresNotModeled.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </div>
        </div>
        {selectedScenario && selectedInputs && (
          <div className="scenario-detail">
            <h3>Scenario Detail – {selectedScenario.id}</h3>
            <table className="kv-table">
              <tbody>
                <tr>
                  <th>Label</th>
                  <td>{selectedScenario.name}</td>
                </tr>
                <tr>
                  <th>Status</th>
                  <td>{selectedScenario.status.toUpperCase()}</td>
                </tr>
                {selectedScenario.runId && (
                  <tr>
                    <th>Run ID</th>
                    <td>{selectedScenario.runId}</td>
                  </tr>
                )}
                {selectedScenario.projectionKey && (
                  <tr>
                    <th>Projection object</th>
                    <td>{selectedScenario.projectionKey}</td>
                  </tr>
                )}
                <tr>
                  <th>Policy inputs</th>
                  <td>
                    Age {selectedInputs.age}, {selectedInputs.sex}, {selectedInputs.smokerClass}, term {selectedInputs.termYears} years, face {selectedFaceDisplay} ({selectedInputs.premiumMode} premium)
                  </td>
                </tr>
                {(() => {
                  const scenario = selectedScenario as any;
                  const policyInputs = (scenario && (scenario as any).policyInputs) || null;
                  const modalPremium = policyInputs?.modal_premium;
                  const mode = policyInputs?.premium_mode || selectedInputs.premiumMode;
                  if (modalPremium === undefined || modalPremium === null) return null;
                  return (
                    <tr>
                      <th>Configured modal premium</th>
                      <td>
                        {typeof modalPremium === "number"
                          ? modalPremium.toLocaleString(undefined, { maximumFractionDigits: 2 })
                          : String(modalPremium)}
                        {mode ? ` (${mode} mode)` : ""}
                      </td>
                    </tr>
                  );
                })()}
                <tr>
                  <th>Rule IDs</th>
                  <td>{selectedScenario.ruleIds.join(", ")}</td>
                </tr>
                <tr>
                  <th>Objective checks</th>
                  <td>
                    <ul>
                      <li>
                        No death benefit after term: {String(selectedScenario.checks?.noDeathBenefitAfterTerm ?? false)}
                      </li>
                      <li>
                        Death benefit ≈ face amount during term: {String(selectedScenario.checks?.deathBenefitApproxFaceDuringTerm ?? false)}
                      </li>
                    </ul>
                  </td>
                </tr>
                <tr>
                  <th>Model behavior summary</th>
                  <td>{selectedScenario.modelBehaviorSummary}</td>
                </tr>
              </tbody>
            </table>
            {Array.isArray(selectedScenario.projectionTable) && selectedScenario.projectionTable.length > 0 && (
              <>
                <h4>Projection evidence (policy-year table)</h4>
                {(() => {
                  const rows = selectedScenario.projectionTable || [];
                  const limited = rows.slice(0, 20); // keep the table compact for MVP
                  const hasAttainedAge = limited.some((r) => r.attainedAge !== undefined && r.attainedAge !== null && r.attainedAge !== "");
                  const hasPremium = limited.some((r) => {
                    const p = r.premium;
                    if (p === undefined || p === null || p === "") return false;
                    if (typeof p === "number") return Math.abs(p) > 1e-9; // hide column when all premiums are 0.0
                    return true;
                  });
                  const hasStatus = limited.some((r) => r.status && r.status !== "");
                  const hasCash = limited.some((r) => r.cashValue !== undefined && r.cashValue !== null && r.cashValue !== "");

                  return (
                    <>
                      <p className="muted">
                        Configured modal premium is shown above. Projection table values are engine-produced projection outputs.
                      </p>
                      <table className="kv-table">
                        <thead>
                          <tr>
                            <th>Policy year</th>
                            {hasAttainedAge && <th>Attained age</th>}
                            {hasPremium && <th>Expected premium (engine)</th>}
                            <th>Death benefit</th>
                            {hasCash && <th>Cash value</th>}
                            {hasStatus && <th>Status</th>}
                          </tr>
                        </thead>
                        <tbody>
                          {limited.map((r, idx) => (
                            <tr key={idx}>
                              <td>{r.year}</td>
                              {hasAttainedAge && <td>{r.attainedAge ?? ""}</td>}
                              {hasPremium && (
                                <td>
                                  {typeof r.premium === "number"
                                    ? r.premium.toLocaleString(undefined, { maximumFractionDigits: 2 })
                                    : r.premium ?? ""}
                                </td>
                              )}
                              <td>
                                {typeof r.deathBenefit === "number"
                                  ? r.deathBenefit.toLocaleString()
                                  : r.deathBenefit ?? ""}
                              </td>
                              {hasCash && (
                                <td>
                                  {typeof r.cashValue === "number"
                                    ? r.cashValue.toLocaleString(undefined, { maximumFractionDigits: 2 })
                                    : r.cashValue ?? ""}
                                </td>
                              )}
                              {hasStatus && <td>{r.status ?? ""}</td>}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  );
                })()}
              </>
            )}
          </div>
        )}
      </section>

      <section className="card">
        <h2>Filing Traceability – Key Rules (POC)</h2>
        <table className="kv-table">
          <thead>
            <tr>
              <th>Rule</th>
              <th>Filing</th>
              <th>Snippet</th>
              <th>AI interpretation</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {traceability.rules.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td>
                  {r.filingId}
                  {r.page && <span className="muted"> (p.{r.page})</span>}
                </td>
                <td className="muted">{r.snippet}</td>
                <td>{r.interpretation}</td>
                <td>{r.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>Rate Reconciliation (POC sample)</h2>
        <p>
          <strong>Cells checked:</strong> {rates.cellsChecked} &nbsp;|&nbsp; <strong>Matched:</strong> {rates.cellsMatched}
        </p>
        {rates.exceptions && rates.exceptions.length > 0 && (
          <p className="warning">Exceptions present (not shown in POC).</p>
        )}
        <h3>Example spot checks</h3>
        <table className="kv-table">
          <thead>
            <tr>
              <th>Age</th>
              <th>Term</th>
              <th>Risk class</th>
              <th>Face</th>
              <th>Filed premium</th>
              <th>Model premium</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rates.spotChecks.map((s, idx) => (
              <tr key={idx}>
                <td>{s.age}</td>
                <td>{s.termYears}</td>
                <td>{s.riskClass}</td>
                <td>
                  {typeof s.faceAmount === "number"
                    ? s.faceAmount.toLocaleString()
                    : String(s.faceAmount ?? "")}
                </td>
                <td>{s.filedPremium.toFixed(2)}</td>
                <td>{s.modelPremium.toFixed(2)}</td>
                <td>{s.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>Scenario Evidence (POC)</h2>
        <div className="scenario-grid">
          {scenarios.map((s) => {
            const inp = normaliseInputs(s.inputs || {});
            const faceDisplay =
              typeof inp.faceAmount === "number" ? inp.faceAmount.toLocaleString() : String(inp.faceAmount);

            return (
              <div
                key={s.id}
                className={
                  "scenario-card" + (selectedScenario && selectedScenario.id === s.id ? " scenario-card--selected" : "")
                }
                onClick={() => setSelectedScenarioId(s.id)}
              >
                <h3>
                  {s.id} – {s.name}
                </h3>
                <p>
                  <strong>Inputs:</strong> Age {inp.age}, {inp.sex}, {inp.smokerClass}, term {inp.termYears} years, face {faceDisplay} ({inp.premiumMode} premium)
                </p>
                <p>
                  <strong>Expected behavior:</strong>
                </p>
                <ul>
                  {s.expectedBehavior.map((b, idx) => (
                    <li key={idx}>{b}</li>
                  ))}
                </ul>
                <p>
                  <strong>Model behavior (summary):</strong> {s.modelBehaviorSummary}
                </p>
                <p>
                  <strong>Result:</strong> {s.status.toUpperCase()}
                </p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="card">
        <h2>Assumptions Requiring Approval (POC)</h2>
        {assumptions.aiProposed.length === 0 ? (
          <p>No AI-proposed assumptions recorded.</p>
        ) : (
          <table className="kv-table">
            <thead>
              <tr>
                <th>Assumption</th>
                <th>Value</th>
                <th>Source</th>
                <th>Sensitivity / impact</th>
                <th>Approval (POC)</th>
              </tr>
            </thead>
            <tbody>
              {assumptions.aiProposed.map((a) => (
                <tr key={a.id}>
                  <td>{a.name}</td>
                  <td>{a.value}</td>
                  <td>{a.source}</td>
                  <td className="muted">{a.sensitivitySummary}</td>
                  <td>{a.humanApproval}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>Gap and Exception Report (POC)</h2>
        {gaps.missingFeatures.length === 0 && gaps.ambiguousLanguage.length === 0 ? (
          <p>No gaps recorded.</p>
        ) : (
          <>
            {gaps.missingFeatures.length > 0 && (
              <>
                <h3>Missing / unmodeled features</h3>
                <ul>
                  {gaps.missingFeatures.map((g) => (
                    <li key={g.id}>
                      {g.description} <span className="muted">(severity: {g.severity})</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </section>

      <section className="card">
        <h2>Final Actuary Decision (POC)</h2>
        <p className="muted">
          MVP-only decision capture for the P12TRF Product Model Review. This does not yet implement a full workflow or
          permissions model.
        </p>

        <form onSubmit={onSubmitDecision} className="form-grid">
          <div className="form-row">
            <label htmlFor="pmr-reviewer">Reviewer</label>
            <input
              id="pmr-reviewer"
              type="text"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
              placeholder="Your name"
            />
          </div>

          <div className="form-row">
            <label htmlFor="pmr-decision">Decision</label>
            <select
              id="pmr-decision"
              value={decision}
              onChange={(e) => setDecision(e.target.value)}
              required
            >
              <option value="">Select…</option>
              <option value="approve_for_poc">Approve for POC</option>
              <option value="approve_with_exclusions">Approve with exclusions</option>
              <option value="request_changes">Request changes</option>
              <option value="reject">Reject</option>
            </select>
          </div>

          <div className="form-row">
            <label htmlFor="pmr-exclusions">Exclusions (optional)</label>
            <textarea
              id="pmr-exclusions"
              value={exclusions}
              onChange={(e) => setExclusions(e.target.value)}
              rows={2}
              placeholder="List any exclusions or conditions for approval."
            />
          </div>

          <div className="form-row">
            <label htmlFor="pmr-comments">Comments (optional)</label>
            <textarea
              id="pmr-comments"
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              rows={3}
              placeholder="Additional notes or rationale for this decision."
            />
          </div>

          <div className="form-row">
            <button type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save decision"}
            </button>
          </div>

          {saveMessage && <p className="success">{saveMessage}</p>}
          {saveError && <p className="error">{saveError}</p>}
        </form>
      </section>
    </div>
  );
};
