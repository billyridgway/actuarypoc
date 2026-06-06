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
      evidence?: {
        id?: number | string;
        documentPath?: string | null;
        pageReference?: string | null;
        sourceSnippet?: string | null;
        aiInterpretation?: string | null;
        confidence?: string | null;
      }[];
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
    purpose?: string;
    dimensionsExercised?: string[];
    source?: string;
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
  reviewMeta?: {
    filingId?: string | null;
    currentGeneration?: string | null;
    generatedAt?: string | null;
    documentCount?: number;
    scenarioCount?: number;
    traceableRuleCount?: number;
    unattributedRuleCount?: number;
    coverageCoveredCount?: number;
    coveragePartialCount?: number;
    coverageGapCount?: number;
    coverageNotApplicableCount?: number;
  };
  reviewFreshness?: {
    status: "fresh" | "stale" | "warning" | string;
    messages: string[];
    latestDocumentUploadedAt?: string | null;
    currentGeneration?: string | null;
    generatedAt?: string | null;
    productDefinitionGeneratedAt?: string | null;
    latestDecisionCreatedAt?: string | null;
  };
  productDefinition?: {
    productCode?: string;
    filingId?: string;
    coverages?: {
      id: string;
      name: string;
      kind: string;
      term_periods?: number[];
      notes?: string | null;
    }[];
    issueAges?: { min?: number | null; max?: number | null };
    termPeriods?: number[];
    underwritingClasses?: string[];
    riskClasses?: string[];
    smokerClasses?: string[];
    premiumModes?: string[];
    faceAmounts?: { min?: number | null; max?: number | null };
    sourceDocumentCount?: number;
    evidenceRefCount?: number;
  } | null;
  coverageMatrix?: {
    feature: string;
    productDefinitionValue?: string;
    modelSupport?: string;
    evidence?: string;
    status: "covered" | "partial" | "gap" | "not_applicable" | string;
  }[];
  productDefinitionBuild?: {
    generatedAt?: string | null;
    generatorVersion?: string | null;
    documentCount?: number;
    evidenceCount?: number;
    scenarioCount?: number;
    warningCount?: number;
    warnings?: string[];
  } | null;
  productDefinitionValidation?: {
    status: "pass" | "warning" | "fail" | string;
    checks: {
      id: string;
      label: string;
      status: "pass" | "warning" | "fail" | string;
      message: string;
    }[];
    summary: { pass: number; warning: number; fail: number };
  } | null;
  scenarioValidation?: {
    status: "pass" | "warning" | "fail" | string;
    summary: { pass: number; warning: number; fail: number };
    checks: {
      id: string;
      scenarioId: string;
      label: string;
      status: "pass" | "warning" | "fail" | string;
      message: string;
    }[];
  } | null;
  decisionTimeline?: {
    points: {
      id?: number | string;
      createdAt?: string | null;
      decision?: string | null;
      reviewer?: string | null;
      riskStatus?: string | null;
      scenarioValidationStatus?: string | null;
      productDefinitionValidationStatus?: string | null;
      coverageGapCount?: number | null;
      bundlePresent?: boolean;
      comments?: string | null;
    }[];
    summary?: {
      latestRiskStatus?: string | null;
      decisionCount?: number | null;
      cleanCount?: number | null;
      warningCount?: number | null;
      failCount?: number | null;
      incompleteCount?: number | null;
    } | null;
    transitions?: {
      fromDecisionId?: number | string | null;
      toDecisionId?: number | string | null;
      change?: string | null;
      reason?: string | null;
    }[];
  } | null;
}

interface ProductModelReviewPageProps {
  review: ProductModelReview & {
    documents?: {
      id: number | string;
      kind?: string | null;
      description?: string | null;
      objectPath?: string | null;
      createdAt?: string | null;
      filingId?: string | null;
    }[];
    lastDecision?: {
      id?: number | string;
      product_code?: string;
      reviewer?: string | null;
      decision?: string | null;
      exclusions?: string | null;
      comments?: string | null;
      created_at?: string | null;
      filing_id?: string | null;
      generation_id?: string | null;
      pd_generated_at?: string | null;
      pd_generator_version?: string | null;
      pd_warning_count?: number | null;
      coverage_covered_count?: number | null;
      coverage_partial_count?: number | null;
      coverage_gap_count?: number | null;
      coverage_not_applicable_count?: number | null;
      validation_status?: string | null;
      validation_pass_count?: number | null;
      validation_warning_count?: number | null;
      validation_fail_count?: number | null;
      scenario_validation_status?: string | null;
      scenario_validation_pass_count?: number | null;
      scenario_validation_warning_count?: number | null;
      scenario_validation_fail_count?: number | null;
      decisionRisk?: {
        status?: string;
        reasons?: string[];
      } | null;
      product_definition_path?: string | null;
      product_definition_hash?: string | null;
      build_report_path?: string | null;
      build_report_hash?: string | null;
      coverage_matrix_path?: string | null;
      coverage_matrix_hash?: string | null;
      validation_report_path?: string | null;
      validation_snapshot_hash?: string | null;
      bundle_path?: string | null;
      bundle_hash?: string | null;
    } | null;
    decisionHistory?: {
      id?: number | string;
      product_code?: string | null;
      reviewer?: string | null;
      decision?: string | null;
      exclusions?: string | null;
      comments?: string | null;
      created_at?: string | null;
      filing_id?: string | null;
      generation_id?: string | null;
      pd_generated_at?: string | null;
      pd_generator_version?: string | null;
      pd_warning_count?: number | null;
      coverage_covered_count?: number | null;
      coverage_partial_count?: number | null;
      coverage_gap_count?: number | null;
      coverage_not_applicable_count?: number | null;
      validation_status?: string | null;
      validation_pass_count?: number | null;
      validation_warning_count?: number | null;
      validation_fail_count?: number | null;
      scenario_validation_status?: string | null;
      scenario_validation_pass_count?: number | null;
      scenario_validation_warning_count?: number | null;
      scenario_validation_fail_count?: number | null;
      decisionRisk?: {
        status?: string;
        reasons?: string[];
      } | null;
      product_definition_path?: string | null;
      product_definition_hash?: string | null;
      build_report_path?: string | null;
      build_report_hash?: string | null;
      coverage_matrix_path?: string | null;
      coverage_matrix_hash?: string | null;
      validation_report_path?: string | null;
      validation_snapshot_hash?: string | null;
      bundle_path?: string | null;
      bundle_hash?: string | null;
      bundle_created_at?: string | null;
    }[];
    reviewProgress?: {
      filingContextEstablished?: boolean;
      documentsUploaded?: boolean;
      scenariosConfigured?: boolean;
      reviewGenerated?: boolean;
      ruleEvidencePresent?: boolean;
      finalDecisionRecorded?: boolean;
      completedSteps?: number;
      totalSteps?: number;
    };
  };
}

export const ProductModelReviewPage: React.FC<ProductModelReviewPageProps> = ({ review }) => {
  const {
    product,
    scope,
    traceability,
    rates,
    scenarios,
    assumptions,
    gaps,
    reviewMeta,
    documents,
    lastDecision,
    decisionHistory,
    reviewProgress,
    productDefinition,
    coverageMatrix,
    productDefinitionBuild,
    productDefinitionValidation,
    reviewFreshness,
    scenarioValidation,
    decisionTimeline,
  } = review;

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

  const shortenHash = (hash?: string | null, length = 8): string | null => {
    if (!hash) return null;
    return hash.length > length ? hash.slice(0, length) : hash;
  };

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

  // Bundle inspection state for Decision History rows.
  const [inspectedDecisionId, setInspectedDecisionId] = React.useState<number | string | null>(null);
  const [bundleManifest, setBundleManifest] = React.useState<any | null>(null);
  const [bundleManifestLoading, setBundleManifestLoading] = React.useState(false);
  const [bundleManifestError, setBundleManifestError] = React.useState<string | null>(null);

  // Filing requirements (P12TRF-only for now).
  const [requirements, setRequirements] = React.useState<any[] | null>(null);
  const [requirementsSummary, setRequirementsSummary] = React.useState<any | null>(null);
  const [requirementsLoading, setRequirementsLoading] = React.useState<boolean>(false);
  const [requirementsError, setRequirementsError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const loadRequirements = async () => {
      setRequirementsLoading(true);
      setRequirementsError(null);
      try {
        const res = await fetch(`/api/products/${encodeURIComponent(product.code)}/requirements`);
        if (!res.ok) {
          // For non-P12TRF or unimplemented products this may legitimately
          // return 404/501; treat that as "no requirements surface".
          if (res.status === 404 || res.status === 501) {
            setRequirements([]);
            setRequirementsSummary(null);
            return;
          }
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setRequirements(Array.isArray(data?.requirements) ? data.requirements : []);
        setRequirementsSummary(data?.summary ?? null);
      } catch (err: any) {
        setRequirementsError(err?.message || "Failed to load filing requirements.");
      } finally {
        setRequirementsLoading(false);
      }
    };

    if (product && product.code) {
      void loadRequirements();
    }
  }, [product.code]);

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

  const onInspectBundle = async (decisionId: number | string) => {
    setInspectedDecisionId(decisionId);
    setBundleManifest(null);
    setBundleManifestError(null);
    setBundleManifestLoading(true);
    try {
      const res = await fetch(
        `/api/product-model-review/${encodeURIComponent(product.code)}/decisions/${encodeURIComponent(String(decisionId))}/bundle/manifest`,
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setBundleManifest(data);
    } catch (err: any) {
      setBundleManifestError(err?.message || "Failed to load bundle manifest.");
    } finally {
      setBundleManifestLoading(false);
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
        <p className="muted">
          Need to adjust metadata, documents, or scenarios?{" "}
          <a href="/web?view=create-review">Edit Product Review inputs</a> (this will let you regenerate the review).
        </p>
      </header>

      <section className="card">
        <h2>Review Summary (POC)</h2>
        <p className="muted">
          This summary is derived from the current Product Model Review data for P12TRF.
          Use it as your navigation: confirm scope, scenarios, and evidence below, then capture your decision.
        </p>
        {reviewFreshness && reviewFreshness.status !== "fresh" && (
          <div className={`alert alert--${reviewFreshness.status}`}>
            <p>
              <strong>This review may be {reviewFreshness.status}.</strong>{" "}
              Inputs changed after the current generated evidence set. Regenerate before recording a new decision.
            </p>
            {Array.isArray(reviewFreshness.messages) && reviewFreshness.messages.length > 0 && (
              <ul>
                {reviewFreshness.messages.map((m, idx) => (
                  <li key={idx}>{m}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        <table className="kv-table">
          <tbody>
            <tr>
              <th>Review completion</th>
              <td>
                {(() => {
                  const done = reviewProgress?.completedSteps ?? 0;
                  const total = reviewProgress?.totalSteps ?? 6;
                  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
                  return (
                    <>
                      {done}/{total} steps ({pct}%)
                    </>
                  );
                })()}
              </td>
            </tr>
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
            <tr>
              <th>Filing ID</th>
              <td>{reviewMeta?.filingId || "(not set)"}</td>
            </tr>
            <tr>
              <th>Product Review generation</th>
              <td>
                {reviewMeta?.currentGeneration || "(not generated via onboarding yet)"}
                {reviewMeta?.generatedAt && (
                  <span className="muted">{` (generated at ${reviewMeta.generatedAt})`}</span>
                )}
              </td>
            </tr>
            <tr>
              <th>Onboarding artefacts</th>
              <td>
                {reviewMeta?.documentCount ?? 0} document(s), {reviewMeta?.scenarioCount ?? scenarios.length} scenario(s)
              </td>
            </tr>
            <tr>
              <th>Rule traceability</th>
              <td>
                {(reviewMeta?.traceableRuleCount ?? 0)} traceable, {(reviewMeta?.unattributedRuleCount ?? 0)} without document attribution
              </td>
            </tr>
            <tr>
              <th>Coverage matrix status</th>
              <td>
                {(reviewMeta?.coverageCoveredCount ?? 0)} covered, {(reviewMeta?.coveragePartialCount ?? 0)} partial, {(reviewMeta?.coverageGapCount ?? 0)} gap
              </td>
            </tr>
            {lastDecision && (
              <tr>
                <th>Evidence Snapshot</th>
                <td className="muted">
                  <div>
                    ProductDefinition: {lastDecision.product_definition_path || "(path not recorded)"}
                    {lastDecision.product_definition_hash && (
                      <>
                        {" "}
                        <span>(hash {shortenHash(lastDecision.product_definition_hash)})</span>
                      </>
                    )}
                  </div>
                  <div>
                    Build report: {lastDecision.build_report_path || "(path not recorded)"}
                    {lastDecision.build_report_hash && (
                      <>
                        {" "}
                        <span>(hash {shortenHash(lastDecision.build_report_hash)})</span>
                      </>
                    )}
                  </div>
                  <div>
                    Coverage matrix: {lastDecision.coverage_matrix_path || "(path not recorded)"}
                    {lastDecision.coverage_matrix_hash && (
                      <>
                        {" "}
                        <span>(hash {shortenHash(lastDecision.coverage_matrix_hash)})</span>
                      </>
                    )}
                  </div>
                  <div>
                    Validation report: {lastDecision.validation_report_path || "(path not recorded)"}
                    {lastDecision.validation_snapshot_hash && (
                      <>
                        {" "}
                        <span>(hash {shortenHash(lastDecision.validation_snapshot_hash)})</span>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            )}
            {lastDecision && (
              <tr>
                <th>Evidence Bundle</th>
                <td className="muted">
                  <div>Decision ID: {lastDecision.id ?? "(unknown)"}</div>
                  <div>Bundle path: {lastDecision.bundle_path || "(not recorded)"}</div>
                  <div>
                    Bundle hash: {lastDecision.bundle_hash ? shortenHash(lastDecision.bundle_hash) : "(n/a)"}
                  </div>
                </td>
              </tr>
            )}
            <tr>
              <th>Decision status</th>
              <td>
                {lastDecision && lastDecision.decision
                  ? `${lastDecision.decision} by ${lastDecision.reviewer || "(unknown)"} at ${lastDecision.created_at || "(time unknown)"}`
                  : "No decision recorded yet"}
              </td>
            </tr>
            {lastDecision && lastDecision.decision && (
              <tr>
                <th>Decision context</th>
                <td className="muted">
                  Filing: {lastDecision.filing_id || reviewMeta?.filingId || "(unknown)"}; Generation: {lastDecision.generation_id || reviewMeta?.currentGeneration || "(unknown)"};
                  {" "}ProductDefinition build: {lastDecision.pd_generated_at || "(n/a)"}
                  {lastDecision.pd_generator_version && ` (generator ${lastDecision.pd_generator_version})`};
                  {" "}Warnings: {lastDecision.pd_warning_count ?? productDefinitionBuild?.warningCount ?? 0};
                  {" "}Validation: {lastDecision.validation_status || productDefinitionValidation?.status || "(n/a)"}
                  {lastDecision.validation_pass_count != null
                    ? ` [pass=${lastDecision.validation_pass_count}, warning=${lastDecision.validation_warning_count ?? 0}, fail=${lastDecision.validation_fail_count ?? 0}]`
                    : productDefinitionValidation && productDefinitionValidation.summary
                      ? ` [pass=${productDefinitionValidation.summary.pass}, warning=${productDefinitionValidation.summary.warning}, fail=${productDefinitionValidation.summary.fail}]`
                      : ""}
                  {" "}Scenario validation: {lastDecision.scenario_validation_status || scenarioValidation?.status || "(n/a)"}
                  {lastDecision.scenario_validation_pass_count != null
                    ? ` [pass=${lastDecision.scenario_validation_pass_count}, warning=${lastDecision.scenario_validation_warning_count ?? 0}, fail=${lastDecision.scenario_validation_fail_count ?? 0}]`
                    : scenarioValidation && scenarioValidation.summary
                      ? ` [pass=${scenarioValidation.summary.pass ?? 0}, warning=${scenarioValidation.summary.warning ?? 0}, fail=${scenarioValidation.summary.fail ?? 0}]`
                      : ""}
                </td>
              </tr>
            )}
            {lastDecision && lastDecision.decisionRisk && (
              <tr>
                <th>Decision risk</th>
                <td>
                  <span
                    className={`tag tag--decision-risk-${(lastDecision.decisionRisk.status || "unknown").toLowerCase()}`}
                  >
                    {String(lastDecision.decisionRisk.status || "unknown").toUpperCase()}
                  </span>
                  {Array.isArray(lastDecision.decisionRisk.reasons)
                    && lastDecision.decisionRisk.reasons.length > 0 && (
                      <ul className="muted">
                        {lastDecision.decisionRisk.reasons.map((r, idx) => (
                          <li key={idx}>{r}</li>
                        ))}
                      </ul>
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section id="filing-requirements" className="card">
        <h2>Filing Requirements</h2>
        <p className="muted">
          Curated view of key filing requirements for P12TRF and where they
          are represented in the current ProductDefinition and coverage
          matrix.
        </p>
        {requirementsError && (
          <p className="error">Error loading filing requirements: {requirementsError}</p>
        )}
        {!requirementsError && requirementsLoading && !requirements && (
          <p className="muted">Loading filing requirements…</p>
        )}
        {!requirementsError && Array.isArray(requirements) && requirements.length === 0 && !requirementsLoading && (
          <p className="muted">No filing requirements surface is available for this product yet.</p>
        )}
        {requirementsSummary && (
          <table className="kv-table">
            <tbody>
              <tr>
                <th>Total requirements</th>
                <td>{requirementsSummary.total ?? 0}</td>
              </tr>
              <tr>
                <th>Status counts</th>
                <td>
                  implemented={requirementsSummary.implemented ?? 0}, partial={requirementsSummary.partial ?? 0},
                  missing={requirementsSummary.missing ?? 0}
                </td>
              </tr>
            </tbody>
          </table>
        )}
        {Array.isArray(requirements) && requirements.length > 0 && (
          <>
            <h3>Requirements</h3>
            <table className="kv-table">
              <thead>
                <tr>
                  <th>Requirement ID</th>
                  <th>Requirement</th>
                  <th>Source</th>
                  <th>ProductDefinition mapping</th>
                  <th>Status</th>
                  <th>Evidence / notes</th>
                </tr>
              </thead>
              <tbody>
                {requirements.map((r) => {
                  const statusRaw = (r && r.status) || "unknown";
                  const status = String(statusRaw).toLowerCase();
                  return (
                    <tr key={r.requirementId || r.requirementText}>
                      <td>{r.requirementId || "(n/a)"}</td>
                      <td>{r.requirementText || "(n/a)"}</td>
                      <td>{r.source || r.filingLocation || "(unknown)"}</td>
                      <td>{r.productDefinitionMapping || "(not mapped)"}</td>
                      <td>
                        <span className={`tag tag--req-status-${status}`}>
                          {String(statusRaw).toUpperCase()}
                        </span>
                      </td>
                      <td className="muted">
                        {r.evidenceRuleId && (
                          <span>
                            Rule: {r.evidenceRuleId}.{" "}
                          </span>
                        )}
                        {r.notes || ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}
      </section>

      {decisionTimeline && Array.isArray(decisionTimeline.points) && decisionTimeline.points.length > 0 && (
        <section className="card">
          <h2>Decision Timeline</h2>
          <p className="muted">
            Chronological view of Product Model Review decisions and their risk levels
            (oldest first). Uses decisionRisk.status with severity ordering
            clean &lt; warning &lt; incomplete &lt; fail.
          </p>

          {decisionTimeline.summary && (
            <table className="kv-table">
              <tbody>
                <tr>
                  <th>Latest risk status</th>
                  <td>
                    {decisionTimeline.summary.latestRiskStatus ? (
                      <span
                        className={`tag tag--decision-risk-${String(
                          decisionTimeline.summary.latestRiskStatus || "unknown",
                        ).toLowerCase()}`}
                      >
                        {String(decisionTimeline.summary.latestRiskStatus || "unknown").toUpperCase()}
                      </span>
                    ) : (
                      <span className="muted">(unknown)</span>
                    )}
                  </td>
                </tr>
                <tr>
                  <th>Decision counts</th>
                  <td>
                    total={decisionTimeline.summary.decisionCount ?? 0},
                    {" "}clean={decisionTimeline.summary.cleanCount ?? 0},
                    {" "}warning={decisionTimeline.summary.warningCount ?? 0},
                    {" "}incomplete={decisionTimeline.summary.incompleteCount ?? 0},
                    {" "}fail={decisionTimeline.summary.failCount ?? 0}
                  </td>
                </tr>
              </tbody>
            </table>
          )}

          <h3>Timeline points</h3>
          <table className="kv-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Created at</th>
                <th>Decision / reviewer</th>
                <th>Risk status</th>
                <th>Scenario validation</th>
                <th>Bundle</th>
              </tr>
            </thead>
            <tbody>
              {decisionTimeline.points.map((p) => {
                const riskStatus = (p.riskStatus || "unknown").toString().toLowerCase();
                const scenStatus = (p.scenarioValidationStatus || "(n/a)").toString();
                const bundleLabel = p.bundlePresent ? "yes" : "no";
                return (
                  <tr key={p.id ?? String(p.createdAt ?? Math.random())}>
                    <td>#{p.id}</td>
                    <td>{p.createdAt || "(unknown)"}</td>
                    <td>
                      {p.decision || "(no decision)"}
                      {" "}
                      <span className="muted">by {p.reviewer || "(unknown)"}</span>
                    </td>
                    <td>
                      <span className={`tag tag--decision-risk-${riskStatus}`}>
                        {riskStatus.toUpperCase()}
                      </span>
                    </td>
                    <td>
                      {scenStatus !== "(n/a)" ? (
                        <span className={`tag tag--scenario-validation-${scenStatus}`}>
                          {scenStatus.toUpperCase()}
                        </span>
                      ) : (
                        <span className="muted">(n/a)</span>
                      )}
                    </td>
                    <td>{bundleLabel}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {Array.isArray(decisionTimeline.transitions) && decisionTimeline.transitions.length > 0 && (
            <>
              <h3>Transitions</h3>
              <ul className="muted">
                {decisionTimeline.transitions.map((t, idx) => (
                  <li key={idx}>
                    Decision {t.fromDecisionId} → {t.toDecisionId}: {t.change || "(unknown)"}
                    {t.reason ? ` — ${t.reason}` : ""}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {Array.isArray(decisionHistory) && decisionHistory.length > 0 && (
        <section className="card">
          <h2>Decision History</h2>
          <p className="muted">
            Each decision row shows the immutable snapshot that was approved at that point in time. New decisions
            append to this history and write a new evidence bundle; existing rows and bundles are never mutated.
          </p>
          <table className="kv-table">
            <thead>
              <tr>
                <th>Decision ID</th>
                <th>Decision</th>
                <th>Reviewer</th>
                <th>Created at</th>
                <th>Filing</th>
                <th>Generation</th>
                <th>Validation</th>
                <th>Scenario validation</th>
                <th>Decision risk</th>
                <th>Coverage (C/P/G/N)</th>
                <th>Bundle path</th>
                <th>Bundle hash</th>
                <th>Comments / exclusions</th>
              </tr>
            </thead>
            <tbody>
              {decisionHistory.map((d) => {
                const latestId = lastDecision && lastDecision.id != null ? String(lastDecision.id) : null;
                const isLatest = latestId !== null && d.id != null && String(d.id) === latestId;
                const validationLabel = d.validation_status || "(n/a)";
                const vPass = d.validation_pass_count ?? 0;
                const vWarn = d.validation_warning_count ?? 0;
                const vFail = d.validation_fail_count ?? 0;
                const sStatus = d.scenario_validation_status || "(n/a)";
                const sPass = d.scenario_validation_pass_count ?? 0;
                const sWarn = d.scenario_validation_warning_count ?? 0;
                const sFail = d.scenario_validation_fail_count ?? 0;
                const cCov = d.coverage_covered_count ?? 0;
                const cPart = d.coverage_partial_count ?? 0;
                const cGap = d.coverage_gap_count ?? 0;
                const cNA = d.coverage_not_applicable_count ?? 0;

                const riskStatusRaw = (d.decisionRisk && d.decisionRisk.status) || "";
                const riskStatus = typeof riskStatusRaw === "string" ? riskStatusRaw.toLowerCase() : "";
                const riskReasons = Array.isArray(d.decisionRisk?.reasons) ? d.decisionRisk?.reasons : [];
                const shortRiskReasons = riskReasons.slice(0, 2).join(" | ");

                const scenarioNonPass =
                  typeof d.scenario_validation_status === "string"
                  && d.scenario_validation_status.toLowerCase() !== "pass";

                const riskRowHighlight = riskStatus === "fail" || riskStatus === "incomplete";

                const rowClassNames = [
                  "decision-row",
                  isLatest ? "decision-row--latest" : "",
                  scenarioNonPass ? "decision-row--scenario-nonpass" : "",
                  riskRowHighlight ? "decision-row--risk" : "",
                ]
                  .filter(Boolean)
                  .join(" ");

                return (
                  <tr key={d.id ?? Math.random()} className={rowClassNames}>
                    <td>
                      {d.id}
                      {isLatest && <span className="tag">latest</span>}
                    </td>
                    <td>{d.decision || "(unknown)"}</td>
                    <td>{d.reviewer || "(unknown)"}</td>
                    <td>{d.created_at || "(n/a)"}</td>
                    <td>{d.filing_id || reviewMeta?.filingId || "(n/a)"}</td>
                    <td>{d.generation_id || reviewMeta?.currentGeneration || "(n/a)"}</td>
                    <td>
                      {validationLabel}
                      {" "}
                      <span className="muted">[pass={vPass}, warn={vWarn}, fail={vFail}]</span>
                    </td>
                    <td>
                      {sStatus}
                      {" "}
                      <span className="muted">[pass={sPass}, warn={sWarn}, fail={sFail}]</span>
                    </td>
                    <td>
                      <span
                        className={`tag tag--decision-risk-${riskStatus || "unknown"}`}
                      >
                        {(riskStatus || "unknown").toUpperCase()}
                      </span>
                      {shortRiskReasons && (
                        <span className="muted"> — {shortRiskReasons}</span>
                      )}
                    </td>
                    <td>
                      {cCov}/{cPart}/{cGap}/{cNA}
                    </td>
                    <td>
                      {d.bundle_path || "(none)"}
                      {d.bundle_path && d.id != null && (
                        <>
                          <br />
                          <a
                            href={`/api/product-model-review/${encodeURIComponent(
                              product.code,
                            )}/decisions/${encodeURIComponent(String(d.id))}/bundle`}
                          >
                            Download bundle
                          </a>
                          {" "}
                          <button
                            type="button"
                            className="link-button"
                            onClick={() => onInspectBundle(d.id as number | string)}
                          >
                            Inspect bundle
                          </button>
                        </>
                      )}
                    </td>
                    <td>{d.bundle_hash ? shortenHash(d.bundle_hash) : "(n/a)"}</td>
                    <td className="muted">
                      {d.comments || "(no comments)"}
                      {d.exclusions && (
                        <>
                          <br />
                          <strong>Exclusions:</strong> {d.exclusions}
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {inspectedDecisionId != null && (
            <div className="bundle-inspection">
              <h3>
                Bundle inspection – decision {inspectedDecisionId}
              </h3>
              <p className="muted">
                This view is read-only and reflects the exact artefacts that were approved at the time of the
                decision. Bundles are immutable and append-only; new decisions create new bundles rather than
                mutating prior ones.
              </p>
              {bundleManifestLoading && <p className="muted">Loading bundle manifest…</p>}
              {bundleManifestError && <p className="error">{bundleManifestError}</p>}
              {bundleManifest && !bundleManifestLoading && !bundleManifestError && (
                <>
                  <p>
                    <strong>Bundle path:</strong> {bundleManifest.bundle_path || "(unknown)"}
                  </p>
                  {Array.isArray(bundleManifest.entries) && bundleManifest.entries.length > 0 && (
                    <>
                      <h4>ZIP entries</h4>
                      <ul>
                        {bundleManifest.entries.map((name: string) => (
                          <li key={name}>{name}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {bundleManifest.manifest && (
                    <>
                      <h4>Bundle manifest</h4>
                      <table className="kv-table">
                        <tbody>
                          <tr>
                            <th>bundleVersion</th>
                            <td>{bundleManifest.manifest.bundleVersion || "(n/a)"}</td>
                          </tr>
                          <tr>
                            <th>productCode</th>
                            <td>{bundleManifest.manifest.productCode || "(n/a)"}</td>
                          </tr>
                          <tr>
                            <th>filingId</th>
                            <td>{bundleManifest.manifest.filingId || "(n/a)"}</td>
                          </tr>
                          <tr>
                            <th>decisionId</th>
                            <td>{bundleManifest.manifest.decisionId ?? "(n/a)"}</td>
                          </tr>
                          <tr>
                            <th>createdAt</th>
                            <td>{bundleManifest.manifest.createdAt || "(n/a)"}</td>
                          </tr>
                          <tr>
                            <th>generationId</th>
                            <td>{bundleManifest.manifest.generationId || "(n/a)"}</td>
                          </tr>
                        </tbody>
                      </table>
                    </>
                  )}
                  {bundleManifest.hashes && (
                    <>
                      <h4>File hashes (hashes.json)</h4>
                      <table className="kv-table">
                        <thead>
                          <tr>
                            <th>File</th>
                            <th>Short hash</th>
                            <th>Full hash</th>
                          </tr>
                        </thead>
                          <tbody>
                          {[
                            "product-definition.json",
                            "build-report.json",
                            "coverage-matrix.json",
                            "validation-report.json",
                            "decision.json",
                            "manifest.json",
                            "scenario-validation.json",
                            "hashes.json",
                          ].map((name) => {
                            const full = bundleManifest.hashes[name];
                            return (
                              <tr key={name}>
                                <td>{name}</td>
                                <td>{full ? shortenHash(full, 12) : "(n/a)"}</td>
                                <td>
                                  {full ? <code>{full}</code> : <span className="muted">(no hash recorded)</span>}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </>
                  )}
                </>
              )}
            </div>
          )}
        </section>
      )}

      <section className="card">
        <h2>Step 1 – Confirm Product Scope</h2>
        <p className="muted">Check that the product scope and gaps match your understanding of the filed product.</p>
        <h3>Product Scope Summary</h3>
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
        {productDefinition && (
          <>
            <h3>Product Definition (v1 snapshot)</h3>
            <p className="muted">
              Derived from the ProductDefinition artefact for this product and filing. Later slices will enrich this
              with more detailed coverage and evidence.
            </p>
            <table className="kv-table">
              <tbody>
                <tr>
                  <th>Issue ages</th>
                  <td>
                    {productDefinition.issueAges?.min ?? "?"}–{productDefinition.issueAges?.max ?? "?"}
                  </td>
                </tr>
                <tr>
                  <th>Term periods</th>
                  <td>
                    {productDefinition.termPeriods && productDefinition.termPeriods.length > 0
                      ? productDefinition.termPeriods.join(", ")
                      : "(not specified yet)"}
                  </td>
                </tr>
                <tr>
                  <th>Underwriting classes</th>
                  <td>
                    {productDefinition.underwritingClasses && productDefinition.underwritingClasses.length > 0
                      ? productDefinition.underwritingClasses.join(", ")
                      : "(none recorded)"}
                  </td>
                </tr>
                <tr>
                  <th>Smoker classes</th>
                  <td>
                    {productDefinition.smokerClasses && productDefinition.smokerClasses.length > 0
                      ? productDefinition.smokerClasses.join(", ")
                      : "(none recorded)"}
                  </td>
                </tr>
                <tr>
                  <th>Premium modes</th>
                  <td>
                    {productDefinition.premiumModes && productDefinition.premiumModes.length > 0
                      ? productDefinition.premiumModes.join(", ")
                      : "(none recorded)"}
                  </td>
                </tr>
                <tr>
                  <th>Face amounts</th>
                  <td>
                    {productDefinition.faceAmounts
                    && (productDefinition.faceAmounts.min != null || productDefinition.faceAmounts.max != null)
                      ? `${productDefinition.faceAmounts.min ?? "?"}–${productDefinition.faceAmounts.max ?? "?"}`
                      : "(not inferred yet)"}
                  </td>
                </tr>
                <tr>
                  <th>Coverages</th>
                  <td>
                    {productDefinition.coverages && productDefinition.coverages.length > 0
                      ? productDefinition.coverages.map((c) => `${c.name} (${c.kind})`).join(", ")
                      : "(none recorded)"}
                  </td>
                </tr>
                <tr>
                  <th>Supporting artefacts</th>
                  <td>
                    {(productDefinition.sourceDocumentCount ?? 0)} document(s), {productDefinition.evidenceRefCount ?? 0} evidence link(s)
                  </td>
                </tr>
              </tbody>
            </table>
          </>
        )}
        {coverageMatrix && coverageMatrix.length > 0 && (
          <>
            <h3>ProductDefinition Coverage Matrix (v1)</h3>
            <p className="muted">
              Shows how key ProductDefinition dimensions are represented in the P12TRF model and where documentary
              evidence is wired. Dimensions without direct filing evidence are marked as partial.
            </p>
            <table className="kv-table">
              <thead>
                <tr>
                  <th>Feature</th>
                  <th>Product definition</th>
                  <th>Model support</th>
                  <th>Evidence</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {coverageMatrix.map((row, idx) => (
                  <tr key={idx}>
                    <td>{row.feature}</td>
                    <td>{row.productDefinitionValue || "(none)"}</td>
                    <td className="muted">{row.modelSupport || "(not recorded)"}</td>
                    <td className="muted">{row.evidence || "(none)"}</td>
                    <td>{row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {productDefinitionBuild && (
          <>
            <h3>ProductDefinition Build (v1)</h3>
            <table className="kv-table">
              <tbody>
                <tr>
                  <th>Generated</th>
                  <td>{productDefinitionBuild.generatedAt || "(builder not run yet)"}</td>
                </tr>
                <tr>
                  <th>Generator</th>
                  <td>{productDefinitionBuild.generatorVersion || "(n/a)"}</td>
                </tr>
                <tr>
                  <th>Sources</th>
                  <td>
                    {(productDefinitionBuild.documentCount ?? 0)} document(s),{" "}
                    {(productDefinitionBuild.evidenceCount ?? 0)} evidence link(s),{" "}
                    {(productDefinitionBuild.scenarioCount ?? 0)} scenario(s)
                  </td>
                </tr>
                <tr>
                  <th>Warnings</th>
                  <td>
                    {productDefinitionBuild.warningCount
                      ? `${productDefinitionBuild.warningCount} warning(s)`
                      : "None"}
                  </td>
                </tr>
              </tbody>
            </table>
            {productDefinitionBuild.warnings && productDefinitionBuild.warnings.length > 0 && (
              <ul className="muted">
                {productDefinitionBuild.warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            )}
          </>
        )}
        {productDefinitionValidation && (
          <>
            <h3>ProductDefinition Validation (v1)</h3>
            <p className="muted">
              Deterministic checks comparing ProductDefinition, scenarios, coverage matrix, and evidence. This is
              MVP-only and does not infer missing information.
            </p>
            <table className="kv-table">
              <tbody>
                <tr>
                  <th>Overall status</th>
                  <td>{productDefinitionValidation.status}</td>
                </tr>
                <tr>
                  <th>Checks</th>
                  <td>
                    {productDefinitionValidation.summary.pass} pass, {productDefinitionValidation.summary.warning} warning,
                    {" "}
                    {productDefinitionValidation.summary.fail} fail
                  </td>
                </tr>
              </tbody>
            </table>
            {productDefinitionValidation.checks && productDefinitionValidation.checks.length > 0 && (
              <table className="kv-table">
                <thead>
                  <tr>
                    <th>Check</th>
                    <th>Status</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {productDefinitionValidation.checks.map((c) => (
                    <tr key={c.id}>
                      <td>{c.label}</td>
                      <td>{c.status}</td>
                      <td className="muted">{c.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
        {scenarioValidation && (
          <>
            <h3>Scenario Validation</h3>
            <p className="muted">
              Deterministic checks on P12TRF scenarios to highlight model-behavior issues such as non-zero death
              benefit after term, negative values, and structural gaps.
            </p>
            <table className="kv-table">
              <tbody>
                <tr>
                  <th>Overall status</th>
                  <td>
                    <span className={`tag tag--scenario-validation-${scenarioValidation.status}`}>
                      {String(scenarioValidation.status).toUpperCase()}
                    </span>
                  </td>
                </tr>
                <tr>
                  <th>Checks</th>
                  <td>
                    {scenarioValidation.summary.pass} pass, {scenarioValidation.summary.warning} warning, {" "}
                    {scenarioValidation.summary.fail} fail
                  </td>
                </tr>
              </tbody>
            </table>
            {Array.isArray(scenarioValidation.checks) && scenarioValidation.checks.length > 0 && (
              <table className="kv-table">
                <thead>
                  <tr>
                    <th>Scenario</th>
                    <th>Check</th>
                    <th>Status</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {scenarioValidation.checks.map((c) => (
                    <tr key={c.id}>
                      <td>{c.scenarioId}</td>
                      <td>{c.label}</td>
                      <td>{c.status}</td>
                      <td className="muted">{c.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {scenarioValidation.status && scenarioValidation.status.toLowerCase() !== "pass" && (
              <p className="warning">Review scenario validation issues before recording a new decision.</p>
            )}
          </>
        )}
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
                  <th>Scenario purpose</th>
                  <td>{selectedScenario.purpose || "(not recorded)"}</td>
                </tr>
                <tr>
                  <th>Dimensions exercised</th>
                  <td>
                    {Array.isArray(selectedScenario.dimensionsExercised)
                      ? selectedScenario.dimensionsExercised.join(", ")
                      : "(not recorded)"}
                  </td>
                </tr>
                <tr>
                  <th>Scenario source</th>
                  <td>{selectedScenario.source || "unknown"}</td>
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
        <h2>Step 3 – Check Filing Rule Evidence</h2>
        <p className="muted">
          Review key filing rules and confirm that each rule is backed by an appropriate source document and snippet.
        </p>
        <h3>Filing Traceability – Key Rules (POC)</h3>
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
                <td className="muted">
                  {r.snippet}
                  {Array.isArray(r.evidence) && r.evidence.length > 0 && (
                    <div className="muted" style={{ marginTop: "0.5rem" }}>
                      <strong>Evidence:</strong>
                      <ul>
                        {r.evidence.map((e, idx) => (
                          <li key={e.id ?? idx}>
                            <div>
                              <span>
                                Doc: {(() => {
                                  const match = documents?.find((d) => d.objectPath === e.documentPath);
                                  if (match?.description) return match.description;
                                  if (e.documentPath) {
                                    const parts = e.documentPath.split("/");
                                    return parts[parts.length - 1] || e.documentPath;
                                  }
                                  return "(unknown document)";
                                })()}
                              </span>
                              {" "}
                              {e.documentPath && (
                                <span className="muted">({e.documentPath})</span>
                              )}
                            </div>
                            <div>
                              Page: {e.pageReference || "page unknown"}
                            </div>
                            <div>
                              Snippet: {e.sourceSnippet || "(no snippet recorded)"}
                            </div>
                            <div>
                              Interpretation: {e.aiInterpretation || "(no interpretation recorded)"}
                            </div>
                            <div>
                              Confidence: {e.confidence || r.confidence}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </td>
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
        <h2>Step 2 – Review Scenario Evidence (POC)</h2>
        <p className="muted">
          Review how the model behaves under a small set of test scenarios. Confirm that the inputs and projected
          behavior match your expectations for this filing.
        </p>
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
                  <strong>Purpose:</strong> {s.purpose || "(not recorded)"}
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
        <h2>Uploaded Documents (current filing context)</h2>
        <p className="muted">
          Uploaded documents are stored and associated with this filing context. Automatic parsing/extraction is not yet
          implemented in this MVP.
        </p>
        {documents && documents.length > 0 ? (
          <table className="kv-table">
            <thead>
              <tr>
                <th>Description</th>
                <th>Kind</th>
                <th>Filing ID</th>
                <th>Object path</th>
                <th>Uploaded at</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((d) => (
                <tr key={d.id}>
                  <td>{d.description || "(none)"}</td>
                  <td>{d.kind || "(n/a)"}</td>
                  <td>{d.filingId || reviewMeta?.filingId || "(not set)"}</td>
                  <td>{d.objectPath}</td>
                  <td>{d.createdAt ? String(d.createdAt) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No uploaded documents for this filing context.</p>
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
        <h2>Step 4 – Record Final Actuary Decision (POC)</h2>
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
