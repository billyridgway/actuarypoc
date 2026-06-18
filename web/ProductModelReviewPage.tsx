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
  productMechanics?: {
    id: string;
    product_code: string;
    name: string;
    type: string;
    description: string;
    confidence: number;
    filing_sources: {
      id: string;
      document_hint: string;
      page?: string | null;
      snippet?: string | null;
      confidence?: number | null;
    }[];
    dsl_refs: {
      id: string;
      file: string;
      path: string;
      description?: string | null;
      valuePreview?: any;
    }[];
    upstream_ids: string[];
    downstream_ids: string[];
  }[];
  mechanicsValidation?: {
    productCode: string;
    checks: {
      mechanicId: string;
      mechanicName: string;
      dslFile: string | null;
      dslPath: string | null;
      status: string;
      expectedValue?: any;
      actualValue?: any;
      message?: string;
    }[];
  } | null;
  mechanicsGeneratedDsl?: {
    productCode: string;
    fragments: {
      dslPath: string;
      sourceMechanicId: string | null;
      sourceMechanicName: string | null;
      generatedValue: any;
      currentDslValue: any;
      status: string;
      message?: string;
    }[];
  } | null;
  mechanicsDslPatchPreview?: {
    productCode: string;
    patches: {
      dslPath: string;
      sourceMechanicId: string | null;
      sourceMechanicName: string | null;
      operation: string | null;
      currentValue: any;
      proposedValue: any;
      status: string;
      message?: string;
    }[];
  } | null;
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

  const [patchComments, setPatchComments] = React.useState<{ [path: string]: string }>({});
  const [patchSubmitting, setPatchSubmitting] = React.useState<{ [path: string]: boolean }>({});
  const [patchError, setPatchError] = React.useState<string | null>(null);

  // Mechanics + scenario coverage mapping (lightweight heuristics for P12TRF).
  const mechanics = review.productMechanics || [];
  const mechanicsById: { [id: string]: (typeof mechanics)[number] } = {};
  mechanics.forEach((m) => {
    mechanicsById[m.id] = m;
  });

  const scenarioMechanics: { [id: string]: string[] } = {};
  const mechanicScenarios: { [id: string]: string[] } = {};

  scenarios.forEach((s) => {
    const ids: string[] = [];
    const inp = s.inputs || {};
    const add = (id: string) => {
      if (!mechanicsById[id]) return;
      if (!ids.includes(id)) ids.push(id);
    };

    if (inp.age !== undefined && inp.age !== null) add("p12trf_issue_age");
    if (inp.riskClass) add("p12trf_risk_class");
    if (inp.faceAmount && typeof inp.faceAmount === "number" && inp.faceAmount > 0) {
      add("p12trf_face_amount");
      add("p12trf_face_band");
    }
    if (inp.premiumMode) add("p12trf_premium_mode");
    if (inp.termYears && typeof inp.termYears === "number" && inp.termYears > 0) {
      add("p12trf_level_term_period");
    }

    // Core mechanics we consider exercised by any term scenario.
    ["p12trf_premium", "p12trf_death_benefit", "p12trf_maturity", "p12trf_policy_fee"].forEach(add);

    scenarioMechanics[s.id] = ids;
    ids.forEach((mid) => {
      if (!mechanicScenarios[mid]) mechanicScenarios[mid] = [];
      mechanicScenarios[mid].push(s.id);
    });
  });

  // Simple, P12TRF-specific narrative of what each mechanic affects.
  const mechanicEffects: { [id: string]: string[] } = {
    p12trf_issue_age: ["Eligibility for level term periods", "Premium rate selection"],
    p12trf_risk_class: ["Premium rate selection", "Mortality assumptions"],
    p12trf_face_amount: ["Magnitude of death benefit", "Interaction with face bands"],
    p12trf_face_band: ["Which premium/mortality band applies"],
    p12trf_premium_mode: ["Payment frequency and modalization of rates"],
    p12trf_level_term_period: ["Length of level premiums and death benefit coverage"],
    p12trf_premium: ["Total premium paid over the level term"],
    p12trf_policy_fee: ["Per-policy fee component of premium"],
    p12trf_death_benefit: ["Benefit paid on death during the level term"],
    p12trf_maturity: ["When coverage ultimately expires; no cash value"],
    p12trf_conversion_privilege: ["Right to convert to a permanent plan under certain conditions"],
  } as any;

  // Infrastructure summaries per mechanic (validation / generated DSL / patch).
  const validationByMechanic: { [id: string]: { ok: number; mismatch: number; total: number } } = {};
  (review.mechanicsValidation?.checks || []).forEach((c) => {
    const mid = c.mechanicId as string | undefined;
    if (!mid) return;
    const entry = (validationByMechanic[mid] = validationByMechanic[mid] || { ok: 0, mismatch: 0, total: 0 });
    entry.total += 1;
    if (c.status === "ok") entry.ok += 1;
    if (c.status === "mismatch") entry.mismatch += 1;
  });

  const generatedByMechanic: { [id: string]: string } = {};
  (review.mechanicsGeneratedDsl?.fragments || []).forEach((f) => {
    const mid = (f.sourceMechanicId || "") as string;
    if (!mid) return;
    generatedByMechanic[mid] = f.status;
  });

  const patchByMechanic: { [id: string]: { status: string; approvalStatus?: string } } = {};
  (review.mechanicsDslPatchPreview?.patches || []).forEach((p) => {
    const mid = (p.sourceMechanicId || "") as string;
    if (!mid) return;
    patchByMechanic[mid] = {
      status: p.status,
      approvalStatus: (p as any).approvalStatus,
    };
  });

  // ------------------------------------------------------------
  // Product Understanding Gaps v0.1 – derive lightweight Known
  // and Suspected gaps in product-language terms.
  // ------------------------------------------------------------

  type UnderstandingGap = {
    productConcept: string;
    whyItMatters: string;
    evidence: string[];
    currentRepresentation: string;
    suggestedNextStep: string;
    confidence: "High" | "Medium" | "Low";
    suggestedOwner: string;
  };

  const knownGaps: UnderstandingGap[] = [];
  const suspectedGaps: UnderstandingGap[] = [];

  // Known Gap: Conversion Privilege represented but not exercised in scenarios.
  if (mechanicsById["p12trf_conversion_privilege"]) {
    const scenIds = mechanicScenarios["p12trf_conversion_privilege"] || [];
    if (scenIds.length === 0) {
      knownGaps.push({
        productConcept: "Conversion Privilege",
        whyItMatters:
          "Conversion is a core policyholder option and often a regulatory focus; it affects how policyowners can transition to permanent coverage.",
        evidence: [
          "Policy form conversion provision (e.g. ICC12_P12TRF10_Policy_Form.pdf).",
          "Mechanic p12trf_conversion_privilege exists in the mechanics set.",
          "DSL flag flags.convertible is present in p12trf_term.yaml.",
        ],
        currentRepresentation:
          "Conversion is present in filings, represented as a mechanic, and flagged in DSL, but no scenarios explicitly exercise conversion behaviour.",
        suggestedNextStep:
          "Define at least one scenario that explicitly tests conversion eligibility/behaviour, and consider adding a simple validation around conversion conditions.",
        confidence: "High",
        suggestedOwner: "Scenario Design",
      });
    }
  }

  // Known Gap: Maturity / Expiry behaviour has thin explicit testing.
  if (mechanicsById["p12trf_maturity"]) {
    const scenIds = mechanicScenarios["p12trf_maturity"] || [];
    // Even when scenarios exist, we call this out as a gap because there
    // is no explicit "end-of-term" scenario or validation.
    knownGaps.push({
      productConcept: "Maturity / Expiry behaviour",
      whyItMatters:
        "Maturity and end-of-term behaviour control when coverage ends and confirm that no cash values are created under the nonforfeiture exception.",
      evidence: [
        "Actuarial memo sections describing maturity/expiry and nonforfeiture exception.",
        "Mechanic p12trf_maturity exists in the mechanics set.",
        "DSL meta.maturity_age and flags.has_cash_value=false in p12trf_term.yaml.",
      ],
      currentRepresentation:
        scenIds.length > 0
          ? "Maturity is represented in mechanics and DSL, and scenarios exist, but none are explicitly designed as end-of-term tests and there is no focused maturity validation."
          : "Maturity is represented in mechanics and DSL, but scenarios do not explicitly exercise end-of-term behaviour and there is no focused maturity validation.",
      suggestedNextStep:
        "Introduce a scenario and/or validation that explicitly exercises behaviour near maturity (e.g. last covered year, first uncovered year) and confirms no cash values.",
      confidence: "High",
      suggestedOwner: "Validation",
    });
  }

  // Known Gap: Underwriting eligibility is only partially represented.
  if (mechanicsById["p12trf_risk_class"]) {
    knownGaps.push({
      productConcept: "Underwriting eligibility boundaries",
      whyItMatters:
        "Underwriting restrictions determine who can buy the product and under what combinations; missing them can misrepresent real-world availability.",
      evidence: [
        "Underwriting sections in filings describing risk class availability and limits.",
        "Mechanic p12trf_risk_class and related mappings exist in mechanics.",
        "DSL meta.filed_risk_classes, meta.risk_class_mapping, and meta.mortality_risk_class_mapping.",
      ],
      currentRepresentation:
        "Risk classes are normalised and mapped for pricing/mortality, but there is no explicit mechanic or validation for underwriting eligibility or disallowed combinations.",
      suggestedNextStep:
        "Clarify which underwriting restrictions should be enforced in the model, and add at least one negative test (e.g. disallowed age/risk-class/term combination) plus a corresponding validation.",
      confidence: "High",
      suggestedOwner: "Product Understanding",
    });
  }

  // Suspected Gap: Riders (Waiver of Premium, Child Term, etc.).
  // We treat this as a hypothesis: filings reference riders, but there
  // are no dedicated rider mechanics or scenarios.
  suspectedGaps.push({
    productConcept: "Riders (Waiver of Premium, Child Term, etc.)",
    whyItMatters:
      "Optional riders can materially change benefits and charges; omitting them may misrepresent how the product behaves for many policyowners.",
    evidence: [
      "Rider endorsements and Statement of Variability sections referencing Waiver of Premium, Child Term, and other riders.",
    ],
    currentRepresentation:
      "Riders are referenced in filings but are not represented as dedicated mechanics, have no structured DSL meta, and are not exercised by any scenarios.",
    suggestedNextStep:
      "Decide which riders are in-scope for this model. For in-scope riders, add mechanics and at least one scenario per rider, or explicitly document them as out-of-scope.",
    confidence: "Medium",
    suggestedOwner: "Filing Review",
  });

  // Suspected Gap: Additional underwriting restrictions beyond those
  // captured by Risk Class mappings.
  suspectedGaps.push({
    productConcept: "Additional underwriting restrictions",
    whyItMatters:
      "Filings may include nuanced underwriting rules (e.g. certain classes not available at older ages or for high face amounts) that materially affect eligibility but are not yet explicit in the model.",
    evidence: [
      "Detailed underwriting narrative and tables in filings describing limits and exceptions.",
    ],
    currentRepresentation:
      "Risk class mappings exist, but additional underwriting limits (e.g. age/face/risk-class interactions) are not captured as mechanics or DSL constraints, and there are no negative test scenarios.",
    suggestedNextStep:
      "Review underwriting sections to identify specific restrictions worth modelling, then either add mechanics and negative tests, or document them as intentionally out-of-scope.",
    confidence: "Low",
    suggestedOwner: "Product Understanding",
  });

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

  // ProductDefinition evidence.
  const [pdEvidence, setPdEvidence] = React.useState<any | null>(null);
  const [pdEvidenceError, setPdEvidenceError] = React.useState<string | null>(null);
  const [pdEvidenceLoading, setPdEvidenceLoading] = React.useState<boolean>(false);

  // Projection logic evidence.
  const [projectionEvidence, setProjectionEvidence] = React.useState<any | null>(null);
  const [projectionEvidenceError, setProjectionEvidenceError] = React.useState<string | null>(null);
  const [projectionEvidenceLoading, setProjectionEvidenceLoading] = React.useState<boolean>(false);

  // Illustration comparison evidence.
  const [illustrationEvidence, setIllustrationEvidence] = React.useState<any | null>(null);
  const [illustrationEvidenceError, setIllustrationEvidenceError] = React.useState<string | null>(null);
  const [illustrationEvidenceLoading, setIllustrationEvidenceLoading] = React.useState<boolean>(false);

  // On-demand illustration API (generic, product-aware).
  const [illustrationForm, setIllustrationForm] = React.useState({
    age: "",
    termYears: "",
    riskClass: "",
    smokerClass: "",
    faceAmount: "",
    premiumMode: "ANNUAL",
  });
  const [illustrationResult, setIllustrationResult] = React.useState<any | null>(null);
  const [illustrationError, setIllustrationError] = React.useState<string | null>(null);
  const [illustrationLoading, setIllustrationLoading] = React.useState<boolean>(false);

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

  React.useEffect(() => {
    const loadProjectionEvidence = async () => {
      setProjectionEvidenceLoading(true);
      setProjectionEvidenceError(null);
      try {
        const res = await fetch(`/api/products/${encodeURIComponent(product.code)}/projection-logic-evidence`);
        if (!res.ok) {
          if (res.status === 404 || res.status === 501) {
            setProjectionEvidence(null);
            return;
          }
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setProjectionEvidence(data || null);
      } catch (err: any) {
        setProjectionEvidenceError(err?.message || "Failed to load projection logic evidence.");
      } finally {
        setProjectionEvidenceLoading(false);
      }
    };

    if (product && product.code) {
      void loadProjectionEvidence();
    }
  }, [product.code]);

  React.useEffect(() => {
    const loadPdEvidence = async () => {
      setPdEvidenceLoading(true);
      setPdEvidenceError(null);
      try {
        const res = await fetch(`/api/products/${encodeURIComponent(product.code)}/product-definition-evidence`);
        if (!res.ok) {
          if (res.status === 404 || res.status === 501) {
            setPdEvidence(null);
            return;
          }
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setPdEvidence(data || null);
      } catch (err: any) {
        setPdEvidenceError(err?.message || "Failed to load ProductDefinition evidence.");
      } finally {
        setPdEvidenceLoading(false);
      }
    };

    if (product && product.code) {
      void loadPdEvidence();
    }
  }, [product.code]);

  React.useEffect(() => {
    const loadIllustrationEvidence = async () => {
      setIllustrationEvidenceLoading(true);
      setIllustrationEvidenceError(null);
      try {
        const res = await fetch(`/api/products/${encodeURIComponent(product.code)}/illustration-evidence`);
        if (!res.ok) {
          if (res.status === 404 || res.status === 501) {
            setIllustrationEvidence(null);
            return;
          }
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setIllustrationEvidence(data || null);
      } catch (err: any) {
        setIllustrationEvidenceError(err?.message || "Failed to load illustration comparison evidence.");
      } finally {
        setIllustrationEvidenceLoading(false);
      }
    };

    if (product && product.code) {
      void loadIllustrationEvidence();
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

  const handlePatchApproval = async (dslPath: string, status: "approved" | "rejected") => {
    const code = (product?.code || "").trim().toUpperCase();
    if (!code) {
      setPatchError("Missing product code for patch approval.");
      return;
    }

    setPatchSubmitting((prev) => ({ ...prev, [dslPath]: true }));
    setPatchError(null);
    try {
      const body = {
        productCode: code,
        dslPath,
        patchStatus: status,
        reviewer: lastDecision?.reviewer || reviewer || undefined,
        comments: patchComments[dslPath] || undefined,
      };
      const res = await fetch("/api/product-mechanics/patch-approval", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      // Reload to pick up latest approval state in the patch preview.
      window.location.reload();
    } catch (e: any) {
      setPatchError(e?.message || "Failed to record patch approval.");
    } finally {
      setPatchSubmitting((prev) => ({ ...prev, [dslPath]: false }));
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

      <section className="card">
        <h2>Quick Illustration (POC)</h2>
        <p className="muted">
          Enter a simple case to generate a fresh illustration projection using
          the current product configuration. This endpoint is product-aware and
          supports any product with term-style projections.
        </p>
        <form
          className="form-grid"
          onSubmit={async (e) => {
            e.preventDefault();
            setIllustrationError(null);
            setIllustrationResult(null);
            setIllustrationLoading(true);
            try {
              const payload: any = {
                age: illustrationForm.age ? Number(illustrationForm.age) : undefined,
                termYears: illustrationForm.termYears ? Number(illustrationForm.termYears) : undefined,
                riskClass: illustrationForm.riskClass || undefined,
                smokerClass: illustrationForm.smokerClass || undefined,
                faceAmount: illustrationForm.faceAmount ? Number(illustrationForm.faceAmount) : undefined,
                premiumMode: illustrationForm.premiumMode || undefined,
              };
              const res = await fetch(`/api/illustrations/${encodeURIComponent(product.code)}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
              });
              if (!res.ok) {
                const text = await res.text();
                throw new Error(text || `HTTP ${res.status}`);
              }
              const data = await res.json();
              setIllustrationResult(data || null);
            } catch (err: any) {
              setIllustrationError(err?.message || "Failed to generate illustration.");
            } finally {
              setIllustrationLoading(false);
            }
          }}
        >
          <div className="form-row">
            <label htmlFor="illustration-age">Issue age</label>
            <input
              id="illustration-age"
              type="number"
              value={illustrationForm.age}
              onChange={(e) => setIllustrationForm({ ...illustrationForm, age: e.target.value })}
              placeholder="e.g. 45"
            />
          </div>
          <div className="form-row">
            <label htmlFor="illustration-term">Term years</label>
            <input
              id="illustration-term"
              type="number"
              value={illustrationForm.termYears}
              onChange={(e) => setIllustrationForm({ ...illustrationForm, termYears: e.target.value })}
              placeholder="e.g. 10 or 20"
            />
          </div>
          <div className="form-row">
            <label htmlFor="illustration-risk">Risk class</label>
            <input
              id="illustration-risk"
              type="text"
              value={illustrationForm.riskClass}
              onChange={(e) => setIllustrationForm({ ...illustrationForm, riskClass: e.target.value })}
              placeholder="e.g. STANDARD_NON_TOBACCO"
            />
          </div>
          <div className="form-row">
            <label htmlFor="illustration-smoker">Smoker class</label>
            <input
              id="illustration-smoker"
              type="text"
              value={illustrationForm.smokerClass}
              onChange={(e) => setIllustrationForm({ ...illustrationForm, smokerClass: e.target.value })}
              placeholder="e.g. NS or S"
            />
          </div>
          <div className="form-row">
            <label htmlFor="illustration-face">Face amount</label>
            <input
              id="illustration-face"
              type="number"
              value={illustrationForm.faceAmount}
              onChange={(e) => setIllustrationForm({ ...illustrationForm, faceAmount: e.target.value })}
              placeholder="e.g. 250000"
            />
          </div>
          <div className="form-row">
            <label htmlFor="illustration-mode">Premium mode</label>
            <input
              id="illustration-mode"
              type="text"
              value={illustrationForm.premiumMode}
              onChange={(e) => setIllustrationForm({ ...illustrationForm, premiumMode: e.target.value })}
              placeholder="e.g. ANNUAL"
            />
          </div>
          <div className="form-row">
            <button type="submit" disabled={illustrationLoading}>
              {illustrationLoading ? "Generating…" : "Generate illustration"}
            </button>
          </div>
        </form>
        {illustrationError && <p className="error">{illustrationError}</p>}
        {illustrationResult && (
          <>
            <h3>Illustration projection</h3>
            {illustrationResult.projection?.metrics && (
              <table className="kv-table">
                <tbody>
                  <tr>
                    <th>Break-even year</th>
                    <td>{illustrationResult.projection.metrics.breakEvenYear ?? "(none)"}</td>
                  </tr>
                  <tr>
                    <th>IRR (to year 10)</th>
                    <td>
                      {typeof illustrationResult.projection.metrics.irr?.toYear10 === "number"
                        ? `${(illustrationResult.projection.metrics.irr.toYear10 * 100).toFixed(2)}%`
                        : "(n/a)"}
                    </td>
                  </tr>
                  <tr>
                    <th>IRR (to year 20)</th>
                    <td>
                      {typeof illustrationResult.projection.metrics.irr?.toYear20 === "number"
                        ? `${(illustrationResult.projection.metrics.irr.toYear20 * 100).toFixed(2)}%`
                        : "(n/a)"}
                    </td>
                  </tr>
                  <tr>
                    <th>IRR (to final year)</th>
                    <td>
                      {typeof illustrationResult.projection.metrics.irr?.toFinalYear === "number"
                        ? `${(illustrationResult.projection.metrics.irr.toFinalYear * 100).toFixed(2)}%`
                        : "(n/a)"}
                    </td>
                  </tr>
                </tbody>
              </table>
            )}
            <table className="kv-table">
              <thead>
                <tr>
                  <th>Year</th>
                  <th>Attained age</th>
                  <th>Premium</th>
                  <th>Cumulative premium</th>
                  <th>Death benefit</th>
                  <th>Cash value</th>
                  <th>Surrender value</th>
                  <th>Net amount at risk</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {Array.isArray(illustrationResult.projection?.rows)
                  && illustrationResult.projection.rows.map((r: any, idx: number) => (
                    <tr key={idx}>
                      <td>{r.year}</td>
                      <td>{r.attainedAge ?? ""}</td>
                      <td>{r.premium ?? ""}</td>
                      <td>{r.cumulativePremium ?? ""}</td>
                      <td>{r.deathBenefit ?? ""}</td>
                      <td>{r.cashValue ?? ""}</td>
                      <td>{r.surrenderValue ?? ""}</td>
                      <td>{r.netAmountAtRisk ?? ""}</td>
                      <td>{r.status ?? ""}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <section className="card">
        <h2>Projection Logic Evidence</h2>
        <p className="muted">
          How the ProductDefinition and filing requirements are realised
          as projection behaviour for key product features.
        </p>
        {projectionEvidenceError && (
          <p className="error">Error loading projection logic evidence: {projectionEvidenceError}</p>
        )}
        {!projectionEvidenceError && projectionEvidenceLoading && !projectionEvidence && (
          <p className="muted">Loading projection logic evidence…</p>
        )}
        {!projectionEvidenceError && !projectionEvidence && !projectionEvidenceLoading && (
          <p className="muted">No projection logic evidence surface is available for this product yet.</p>
        )}
        {projectionEvidence && (
          <>
            {projectionEvidence.summary && (
              <table className="kv-table">
                <tbody>
                  <tr>
                    <th>Behaviours documented</th>
                    <td>{projectionEvidence.summary.behaviorCount ?? 0}</td>
                  </tr>
                </tbody>
              </table>
            )}
            {Array.isArray(projectionEvidence.behaviors) && projectionEvidence.behaviors.length > 0 && (
              <>
                <h3>Key behaviours</h3>
                <table className="kv-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Label</th>
                      <th>Requirements</th>
                      <th>ProductDefinition paths</th>
                      <th>Logic</th>
                    </tr>
                  </thead>
                  <tbody>
                    {projectionEvidence.behaviors.map((b: any) => {
                      const reqIds = Array.isArray(b.requirementIds) ? b.requirementIds : [];
                      const pdPaths = Array.isArray(b.productDefinitionPaths) ? b.productDefinitionPaths : [];
                      const logic = b.projectionLogic || {};
                      return (
                        <tr key={b.id || b.label}>
                          <td>{b.id || "(n/a)"}</td>
                          <td>{b.label || "(n/a)"}</td>
                          <td>{reqIds.length > 0 ? reqIds.join(", ") : <span className="muted">(none)</span>}</td>
                          <td>{pdPaths.length > 0 ? pdPaths.join(", ") : <span className="muted">(none)</span>}</td>
                          <td>
                            {logic.description && <div>{logic.description}</div>}
                            {logic.pseudoCode && (
                              <pre className="inline-pre">{String(logic.pseudoCode)}</pre>
                            )}
                            {logic.notes && <div className="muted">{logic.notes}</div>}
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
      </section>

      <section className="card">
        <h2>Illustration Comparison</h2>
        <p className="muted">
          Comparison of modelled premiums against trusted illustration
          points for key age / term / risk / face combinations.
        </p>
        {illustrationEvidenceError && (
          <p className="error">Error loading illustration comparison evidence: {illustrationEvidenceError}</p>
        )}
        {!illustrationEvidenceError && illustrationEvidenceLoading && !illustrationEvidence && (
          <p className="muted">Loading illustration comparison evidence…</p>
        )}
        {!illustrationEvidenceError && !illustrationEvidence && !illustrationEvidenceLoading && (
          <p className="muted">No illustration comparison evidence surface is available for this product yet.</p>
        )}
        {illustrationEvidence && (
          <>
            {illustrationEvidence.summary && (
              <table className="kv-table">
                <tbody>
                  <tr>
                    <th>Comparison cases</th>
                    <td>{illustrationEvidence.summary.caseCount ?? 0}</td>
                  </tr>
                  <tr>
                    <th>Within tolerance</th>
                    <td>{illustrationEvidence.summary.withinTolerance ?? 0}</td>
                  </tr>
                  <tr>
                    <th>Mismatches</th>
                    <td>{illustrationEvidence.summary.mismatch ?? 0}</td>
                  </tr>
                </tbody>
              </table>
            )}
            {Array.isArray(illustrationEvidence.cases) && illustrationEvidence.cases.length > 0 && (
              <>
                <h3>Comparison cases</h3>
                <table className="kv-table">
                  <thead>
                    <tr>
                      <th>Case</th>
                      <th>Inputs</th>
                      <th>Filed premium</th>
                      <th>Model premium</th>
                      <th>Difference</th>
                      <th>Status</th>
                      <th>Linked requirements</th>
                    </tr>
                  </thead>
                  <tbody>
                    {illustrationEvidence.cases.map((c: any) => {
                      const inputs = c.inputs || {};
                      const trusted = c.trusted || {};
                      const model = c.model || {};
                      const diff = c.difference || {};
                      const linked = Array.isArray(c.linkedRequirementIds) ? c.linkedRequirementIds : [];
                      const status = String(c.status || "unknown");
                      return (
                        <tr key={c.id || c.label}>
                          <td>{c.label || c.id || "(n/a)"}</td>
                          <td>
                            <div className="muted">
                              age={inputs.age}, term={inputs.termYears}y, risk={inputs.riskClass}, face={inputs.faceAmount}
                            </div>
                          </td>
                          <td>{trusted.annualPremium != null ? trusted.annualPremium : <span className="muted">(n/a)</span>}</td>
                          <td>{model.annualPremium != null ? model.annualPremium : <span className="muted">(n/a)</span>}</td>
                          <td>
                            {diff.absolute != null && (
                              <div>
                                abs={diff.absolute}
                                {diff.percent != null && ` (${(diff.percent * 100).toFixed(2)}%)`}
                              </div>
                            )}
                            {diff.absolute == null && <span className="muted">(n/a)</span>}
                          </td>
                          <td>
                            <span className={`tag tag--illustration-${status.toLowerCase()}`}>
                              {status.toUpperCase()}
                            </span>
                          </td>
                          <td>
                            {linked.length > 0 ? linked.join(", ") : <span className="muted">(none)</span>}
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
                  const implStatusRaw =
                    (r && (r.implementationStatus ?? r.status)) || "unknown";
                  const status = String(implStatusRaw).toLowerCase();

                  // Source: handle the new generic {documentPath, filingLocation}
                  // shape as well as older string-based shapes.
                  let sourceText: string;
                  const src = r && r.source;
                  if (src && typeof src === "object") {
                    const loc = (src.filingLocation as string | undefined) ||
                      (src.documentPath as string | undefined);
                    sourceText = loc || "(unknown)";
                  } else {
                    sourceText = (src as string) || r.filingLocation || "(unknown)";
                  }

                  // ProductDefinition mappings: show mapped paths when present.
                  const mappings = Array.isArray(r.productDefinitionMappings)
                    ? r.productDefinitionMappings
                    : [];
                  const mappingText =
                    mappings.length > 0
                      ? mappings
                          .map((m: any) => (m && m.path ? String(m.path) : ""))
                          .filter(Boolean)
                          .join(", ") || "(mapped)"
                      : r.productDefinitionMapping || "(not mapped)";

                  const evidenceRuleIds = Array.isArray(r.evidenceRuleIds)
                    ? r.evidenceRuleIds
                    : r.evidenceRuleId
                      ? [r.evidenceRuleId]
                      : [];

                  return (
                    <tr key={r.requirementId || r.requirementText}>
                      <td>{r.requirementId || "(n/a)"}</td>
                      <td>{r.requirementText || "(n/a)"}</td>
                      <td>{sourceText}</td>
                      <td>{mappingText}</td>
                      <td>
                        <span className={`tag tag--req-status-${status}`}>
                          {String(implStatusRaw).toUpperCase()}
                        </span>
                      </td>
                      <td className="muted">
                        {evidenceRuleIds.length > 0 && (
                          <span>
                            Rules: {evidenceRuleIds.join(", ")}.{" "}
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

      <section className="card">
        <h2>ProductDefinition Evidence</h2>
        <p className="muted">
          Current ProductDefinition snapshot, build metadata, validation
          status, and how key fields link back to filing requirements.
        </p>
        {pdEvidenceError && (
          <p className="error">Error loading ProductDefinition evidence: {pdEvidenceError}</p>
        )}
        {!pdEvidenceError && pdEvidenceLoading && !pdEvidence && (
          <p className="muted">Loading ProductDefinition evidence…</p>
        )}
        {!pdEvidenceError && !pdEvidence && !pdEvidenceLoading && (
          <p className="muted">No ProductDefinition evidence surface is available for this product yet.</p>
        )}
        {pdEvidence && (
          <>
            {pdEvidence.summary && (
              <table className="kv-table">
                <tbody>
                  <tr>
                    <th>Validation status</th>
                    <td>{String(pdEvidence.summary.validationStatus || "unknown").toUpperCase()}</td>
                  </tr>
                  <tr>
                    <th>Fields linked to requirements</th>
                    <td>
                      {pdEvidence.summary.linkedFieldCount ?? 0} / {pdEvidence.summary.fieldCount ?? 0}
                    </td>
                  </tr>
                </tbody>
              </table>
            )}
            {Array.isArray(pdEvidence.fields) && pdEvidence.fields.length > 0 && (
              <>
                <h3>Key fields</h3>
                <table className="kv-table">
                  <thead>
                    <tr>
                      <th>Path</th>
                      <th>Label</th>
                      <th>Value</th>
                      <th>Linked requirements</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pdEvidence.fields.map((f: any, idx: number) => {
                      const linked = Array.isArray(f.linkedRequirementIds) ? f.linkedRequirementIds : [];
                      return (
                        <tr key={f.path || idx}>
                          <td><code>{f.path || "(n/a)"}</code></td>
                          <td>{f.label || "(n/a)"}</td>
                          <td>
                            <pre className="inline-pre">{JSON.stringify(f.value)}</pre>
                          </td>
                          <td>
                            {linked.length > 0 ? linked.join(", ") : <span className="muted">(none)</span>}
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

      {review.productMechanics && review.productMechanics.length > 0 && (
        <>
          <section className="card">
            <h2>How This Product Works</h2>
            <p className="muted">
              High-level narrative assembled from the Product Mechanics for this product. This is intentionally
              P12TRF-focused for v0.1 and is meant to give actuaries a fast mental model before diving into DSL
              or projections.
            </p>
            <ol>
              <li>A customer applies at an eligible <strong>Issue Age</strong>.</li>
              <li>The customer is assigned a <strong>Risk Class</strong>.</li>
              <li>The customer selects a <strong>Face Amount</strong>, which determines the applicable <strong>Face Band</strong>.</li>
              <li>The customer selects a <strong>Level Term Period</strong> (e.g. 10/15/20/30 years).</li>
              <li>
                <strong>Premiums</strong> are determined using Issue Age, Risk Class, Face Band, and Level Term Period, plus a
                <strong> Monthly Policy Fee</strong> when applicable.
              </li>
              <li>The policy provides a <strong>Death Benefit</strong> during the level term period.</li>
              <li>The policy may be <strong>Convertible</strong> to a permanent plan under certain conditions.</li>
              <li>
                Coverage ultimately expires at <strong>Maturity</strong> (term to age 95), and the product has <strong>no cash
                value</strong> under the nonforfeiture exception.
              </li>
            </ol>
          </section>

          <section className="card">
            <h2>Product Mechanics Review</h2>
            <p className="muted">
              Mechanics-first view of the product. Each mechanic captures a key product concept, its filing evidence,
              what it affects, which scenarios exercise it, and how it is implemented in DSL. Implementation details
              are intentionally secondary to product meaning.
            </p>
            <table className="kv-table">
              <thead>
                <tr>
                  <th>Mechanic</th>
                  <th>Behaviour & scenarios</th>
                  <th>Implementation details</th>
                </tr>
              </thead>
              <tbody>
                {review.productMechanics.map((m) => {
                  const effected = mechanicEffects[m.id] || [];
                  const scenIds = mechanicScenarios[m.id] || [];
                  const scenLabels = scenIds.length > 0 ? scenIds.join(", ") : "(none)";

                  const v = validationByMechanic[m.id];
                  let validationSummary = "No validation configured.";
                  if (v && v.total > 0) {
                    if (v.mismatch > 0) validationSummary = `Validation configured; ${v.mismatch} mismatch(es).`;
                    else if (v.ok > 0) validationSummary = "Validation configured; all checks OK.";
                    else validationSummary = "Validation checks present but inconclusive.";
                  }

                  const genStatus = generatedByMechanic[m.id];
                  let generatedSummary = "No generated DSL fragment.";
                  if (genStatus === "matches_current_dsl") generatedSummary = "Generated fragment matches current DSL.";
                  else if (genStatus === "differs_from_current_dsl") generatedSummary = "Generated fragment differs from current DSL.";

                  const patchInfo = patchByMechanic[m.id];
                  let patchSummary = "No mechanics-derived patch.";
                  if (patchInfo) {
                    const base = patchInfo.status === "no_change"
                      ? "Proposed patch would not change DSL."
                      : patchInfo.status === "would_update"
                        ? "Proposed patch would update DSL."
                        : `Patch status: ${patchInfo.status}.`;
                    if (patchInfo.approvalStatus) {
                      patchSummary = `${base} Approval: ${patchInfo.approvalStatus}.`;
                    } else {
                      patchSummary = base;
                    }
                  }

                  return (
                    <tr key={m.id}>
                      <td>
                        <strong>{m.name}</strong>
                        <br />
                        <span className="muted" style={{ fontSize: "0.85rem" }}>
                          {m.description}
                        </span>
                        <div style={{ marginTop: "0.5rem" }}>
                          <strong>Filing evidence:</strong>
                          {m.filing_sources && m.filing_sources.length > 0 ? (
                            <ul>
                              {m.filing_sources.map((fs) => (
                                <li key={fs.id}>
                                  <span>{fs.document_hint}</span>
                                  {fs.page && <span> ({fs.page})</span>}
                                  {fs.snippet && <span className="muted"> – {fs.snippet}</span>}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <span className="muted"> No filing evidence recorded.</span>
                          )}
                        </div>
                      </td>
                      <td>
                        <div>
                          <strong>What it affects:</strong>
                          {effected.length > 0 ? (
                            <ul>
                              {effected.map((txt) => (
                                <li key={txt}>{txt}</li>
                              ))}
                            </ul>
                          ) : (
                            <span className="muted"> (not documented yet)</span>
                          )}
                        </div>
                        <div style={{ marginTop: "0.5rem" }}>
                          <strong>Scenarios exercising this mechanic:</strong> {scenLabels}
                        </div>
                      </td>
                      <td>
                        <div>
                          <strong>DSL mappings:</strong>
                          {m.dsl_refs && m.dsl_refs.length > 0 ? (
                            <ul>
                              {m.dsl_refs.map((dr) => (
                                <li key={dr.id}>
                                  <code>{dr.file}</code>
                                  {": "}
                                  <code>{dr.path}</code>
                                  {dr.description && (
                                    <span className="muted"> – {dr.description}</span>
                                  )}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <span className="muted"> No DSL links recorded.</span>
                          )}
                        </div>
                        <div style={{ marginTop: "0.5rem" }}>
                          <strong>Validation:</strong> <span className="muted">{validationSummary}</span>
                        </div>
                        <div style={{ marginTop: "0.5rem" }}>
                          <strong>Generated DSL:</strong> <span className="muted">{generatedSummary}</span>
                        </div>
                        <div style={{ marginTop: "0.5rem" }}>
                          <strong>Patch / approval:</strong> <span className="muted">{patchSummary}</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        </>
      )}

      {review.mechanicsValidation && review.mechanicsValidation.checks && review.mechanicsValidation.checks.length > 0 && (
        <section className="card">
          <h2>Mechanics vs DSL Consistency</h2>
          <p className="muted">
            Comparison between Product Mechanics expectations and the current executable DSL fields. This is
            Mechanics Validation v0.1 and is advisory: mismatches are surfaced as review warnings, not blockers.
          </p>
          <table className="kv-table">
            <thead>
              <tr>
                <th>Mechanic</th>
                <th>DSL path</th>
                <th>Status</th>
                <th>Expected</th>
                <th>Actual</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {review.mechanicsValidation.checks.map((c) => (
                <tr key={`${c.mechanicId || ""}:${c.dslPath || ""}`}>
                  <td>{c.mechanicName || c.mechanicId}</td>
                  <td>
                    {c.dslFile && c.dslPath ? (
                      <>
                        <code>{c.dslFile}</code>
                        {": "}
                        <code>{c.dslPath}</code>
                      </>
                    ) : (
                      <span className="muted">(no DSL mapping)</span>
                    )}
                  </td>
                  <td>{c.status}</td>
                  <td>
                    {c.expectedValue !== undefined ? (
                      <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                        {JSON.stringify(c.expectedValue, null, 2)}
                      </pre>
                    ) : (
                      <span className="muted">(none)</span>
                    )}
                  </td>
                  <td>
                    {c.actualValue !== undefined ? (
                      <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                        {JSON.stringify(c.actualValue, null, 2)}
                      </pre>
                    ) : (
                      <span className="muted">(none)</span>
                    )}
                  </td>
                  <td className="muted">{c.message || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {review.mechanicsGeneratedDsl && review.mechanicsGeneratedDsl.fragments && review.mechanicsGeneratedDsl.fragments.length > 0 && (
        <section className="card">
          <h2>Mechanics-Generated DSL Preview</h2>
          <p className="muted">
            Preview of small DSL fragments generated directly from Product Mechanics expectations. For v0.1 this is
            limited to <code>meta.policy_fee</code>. This does not modify the DSL; it simply contrasts the generated
            value with the current executable DSL.
          </p>
          <table className="kv-table">
            <thead>
              <tr>
                <th>DSL path</th>
                <th>Source mechanic</th>
                <th>Status</th>
                <th>Generated value (from mechanics)</th>
                <th>Current DSL value</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {review.mechanicsGeneratedDsl.fragments.map((f) => (
                <tr key={f.dslPath}>
                  <td>
                    <code>{f.dslPath}</code>
                  </td>
                  <td>
                    {f.sourceMechanicName || f.sourceMechanicId || <span className="muted">(none)</span>}
                  </td>
                  <td>{f.status}</td>
                  <td>
                    {f.generatedValue !== undefined ? (
                      <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                        {JSON.stringify(f.generatedValue, null, 2)}
                      </pre>
                    ) : (
                      <span className="muted">(none)</span>
                    )}
                  </td>
                  <td>
                    {f.currentDslValue !== undefined ? (
                      <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                        {JSON.stringify(f.currentDslValue, null, 2)}
                      </pre>
                    ) : (
                      <span className="muted">(none)</span>
                    )}
                  </td>
                  <td className="muted">{f.message || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {(knownGaps.length > 0 || suspectedGaps.length > 0) && (
        <section className="card">
          <h2>Product Understanding Gaps</h2>
          <p className="muted">
            Product concepts that appear to be under-modelled, under-tested, or missing compared to the filings. This
            section is intentionally product-focused: it is meant to help actuaries decide what to investigate next,
            not to serve as a governance checklist.
          </p>

          {knownGaps.length > 0 && (
            <>
              <h3>Known Gaps (incompletely exercised modelled concepts)</h3>
              <table className="kv-table">
                <thead>
                  <tr>
                    <th>Product concept</th>
                    <th>Why it matters</th>
                    <th>Evidence</th>
                    <th>Current representation</th>
                    <th>Suggested next step</th>
                    <th>Confidence</th>
                    <th>Suggested owner</th>
                  </tr>
                </thead>
                <tbody>
                  {knownGaps.map((g, idx) => (
                    <tr key={g.productConcept + idx}>
                      <td>{g.productConcept}</td>
                      <td className="muted">{g.whyItMatters}</td>
                      <td>
                        <ul>
                          {g.evidence.map((e) => (
                            <li key={e}>{e}</li>
                          ))}
                        </ul>
                      </td>
                      <td className="muted">{g.currentRepresentation}</td>
                      <td className="muted">{g.suggestedNextStep}</td>
                      <td>{g.confidence}</td>
                      <td>{g.suggestedOwner}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {suspectedGaps.length > 0 && (
            <>
              <h3>Suspected Gaps (concepts that may not be modelled yet)</h3>
              <table className="kv-table">
                <thead>
                  <tr>
                    <th>Product concept</th>
                    <th>Why it matters</th>
                    <th>Evidence</th>
                    <th>Current representation</th>
                    <th>Suggested next step</th>
                    <th>Confidence</th>
                    <th>Suggested owner</th>
                  </tr>
                </thead>
                <tbody>
                  {suspectedGaps.map((g, idx) => (
                    <tr key={g.productConcept + idx}>
                      <td>{g.productConcept}</td>
                      <td className="muted">{g.whyItMatters}</td>
                      <td>
                        <ul>
                          {g.evidence.map((e) => (
                            <li key={e}>{e}</li>
                          ))}
                        </ul>
                      </td>
                      <td className="muted">{g.currentRepresentation}</td>
                      <td className="muted">{g.suggestedNextStep}</td>
                      <td>{g.confidence}</td>
                      <td>{g.suggestedOwner}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      )}

      {review.mechanicsDslPatchPreview && review.mechanicsDslPatchPreview.patches && review.mechanicsDslPatchPreview.patches.length > 0 && (
        <section className="card">
          <h2>Proposed DSL Patch Preview</h2>
          <p className="muted">
            Hypothetical patches to the executable DSL derived from Product Mechanics expectations. For v0.1 this is
            limited to a single <code>meta.policy_fee</code> "replace" patch. No changes are applied automatically;
            this view is for inspection only.
          </p>
          <table className="kv-table">
            <thead>
              <tr>
                <th>DSL path</th>
                <th>Source mechanic</th>
                <th>Operation</th>
                <th>Status</th>
                <th>Current DSL value</th>
                <th>Proposed DSL value</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {patchError && (
                <tr>
                  <td colSpan={7}>
                    <p className="error">{patchError}</p>
                  </td>
                </tr>
              )}
              {review.mechanicsDslPatchPreview.patches.map((p) => (
                <tr key={p.dslPath}>
                  <td>
                    <code>{p.dslPath}</code>
                  </td>
                  <td>{p.sourceMechanicName || p.sourceMechanicId || <span className="muted">(none)</span>}</td>
                  <td>{p.operation || <span className="muted">(n/a)</span>}</td>
                  <td>{p.status}</td>
                  <td>
                    {p.currentValue !== undefined ? (
                      <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                        {JSON.stringify(p.currentValue, null, 2)}
                      </pre>
                    ) : (
                      <span className="muted">(none)</span>
                    )}
                  </td>
                  <td>
                    {p.proposedValue !== undefined ? (
                      <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                        {JSON.stringify(p.proposedValue, null, 2)}
                      </pre>
                    ) : (
                      <span className="muted">(none)</span>
                    )}
                  </td>
                  <td>
                    <div className="muted" style={{ marginBottom: "0.5rem" }}>
                      {p.message || ""}
                    </div>
                    {p.approvalStatus && (
                      <div className="muted" style={{ fontSize: "0.85rem", marginBottom: "0.5rem" }}>
                        Approval: {p.approvalStatus} by {p.approvalReviewer || "(unknown)"} at {p.approvalReviewedAt || "(time unknown)"}
                        {p.approvalComments && <>
                          <br />Comment: {p.approvalComments}
                        </>}
                      </div>
                    )}
                    <div className="form-row" style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                      <textarea
                        rows={2}
                        placeholder="Optional approval comment"
                        value={patchComments[p.dslPath] || ""}
                        onChange={(e) =>
                          setPatchComments((prev) => ({
                            ...prev,
                            [p.dslPath]: e.target.value,
                          }))
                        }
                      />
                      <div>
                        <button
                          type="button"
                          onClick={() => handlePatchApproval(p.dslPath, "approved")}
                          disabled={patchSubmitting[p.dslPath] === true}
                          style={{ marginRight: "0.25rem" }}
                        >
                          {patchSubmitting[p.dslPath] ? "Approving…" : "Approve"}
                        </button>
                        <button
                          type="button"
                          onClick={() => handlePatchApproval(p.dslPath, "rejected")}
                          disabled={patchSubmitting[p.dslPath] === true}
                        >
                          {patchSubmitting[p.dslPath] ? "Rejecting…" : "Reject"}
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

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
        {(() => {
          const missing = Array.isArray(gaps?.missingFeatures) ? gaps.missingFeatures : [];
          const ambiguous = Array.isArray(gaps?.ambiguousLanguage) ? gaps.ambiguousLanguage : [];

          if (missing.length === 0 && ambiguous.length === 0) {
            return <p>No gaps recorded.</p>;
          }

          return (
            <>
              {missing.length > 0 && (
                <>
                  <h3>Missing / unmodeled features</h3>
                  <ul>
                    {missing.map((g: any) => (
                      <li key={g.id}>
                        {g.description} <span className="muted">(severity: {g.severity})</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {/* Ambiguous language bucket is kept for future use; for now we
                  only render missing/unmodeled features when present. */}
            </>
          );
        })()}
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
