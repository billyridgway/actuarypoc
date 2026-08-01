import React from "react";

interface WorkspaceAssumption {
  name?: string;
  value?: any;
  source?: string;
}

export interface WorkspaceRow {
  year?: number;
  attainedAge?: number;
  premiumMode?: string;
  modalPremium?: number;
  annualPremium?: number;
  cumulativePremium?: number;
  openingPolicyValue?: number;
  premiumLoad?: number;
  guaranteedInterest?: number;
  coiCharge?: number;
  policyFee?: number;
  policyValue?: number;
  endingPolicyValue?: number;
  cashValue?: number;
  surrenderCharge?: number;
  surrenderValue?: number;
  deathBenefit?: number;
  netAmountAtRisk?: number;
  status?: string | null;
}

export interface ProjectionInput {
  id?: string;
  label?: string;
  value?: any;
  unit?: string;
  status?: string;
  source?: string;
}

export interface MechanicsStep {
  id?: string;
  order?: number;
  title?: string;
  formulaText?: string;
  inputs?: Array<{ label?: string; value?: any; unit?: string; source?: string }>;
  result?: { label?: string; value?: any; unit?: string; source?: string };
}

export interface GraphInputConfig {
  kind: "number" | "select" | "text";
  enteredStatus?: "ready" | "provisional";
  min?: number;
  max?: number;
  step?: number;
  help?: string;
  placeholder?: string;
  options?: Array<{ value: string; label: string }>;
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
    formClassifications?: {
      primary?: string[];
      riders?: string[];
      supplements?: string[];
      referenced?: string[];
    };
    issueAgeRange?: string | null;
    issueAgeSource?: string | null;
    riskClasses?: string[] | null;
    riskClassesSource?: string | null;
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
    inputs?: ProjectionInput[];
    metrics?: Record<string, any>;
    rows?: WorkspaceRow[];
    sampleRows?: WorkspaceRow[];
    modelStatus?: string;
  } | null;
  mechanicsExplanation?: {
    title?: string;
    steps?: MechanicsStep[];
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
    pageCount?: number | null;
    textLength?: number | null;
  }>;
  extractedFacts?: Array<{
    label: string;
    value?: any;
    source?: string | null;
    confidence?: number | null;
    status?: string;
    provenanceKind?: string;
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
  capabilityAssessment?: {
    summary?: {
      supported?: number;
      partial?: number;
      unsupported?: number;
    };
    items?: Array<{
      capabilityId: string;
      name?: string;
      status?: string;
      impact?: string;
      reason?: string;
      productCode?: string | null;
      sourceRequirementId?: string | null;
      sourceRequirementText?: string | null;
      sourceDocument?: string | null;
      sourceReference?: string | null;
      recommendedAction?: string | null;
    }>;
  };
}

interface FeatureRequest {
  id: number;
  workspaceId?: string;
  productCode?: string | null;
  capabilityId: string;
  title: string;
  description?: string | null;
  impact?: string | null;
  priority?: string | null;
  status: string;
  sourceRequirementId?: string | null;
  sourceRequirementText?: string | null;
  sourceDocument?: string | null;
  sourceReference?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export const formatCurrency = (value: any): string => {
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

const formatProjectionInputValue = (value: any, unit?: string): string => {
  if (value == null || value === "") return "Not modeled";
  if (unit === "USD") return formatCurrency(value);
  if (unit === "rate" && Number.isFinite(Number(value))) return `${(Number(value) * 100).toFixed(2)}%`;
  return `${String(value)}${unit && unit !== "years" ? ` ${unit}` : unit === "years" ? " years" : ""}`;
};

type LogicNodeStatus = "ready" | "provisional" | "missing";

interface LogicGraphNode {
  id: string;
  inputId?: string;
  kind: "input" | "rule";
  label: string;
  status: LogicNodeStatus;
  detail?: string;
  value?: any;
  unit?: string;
  source?: string;
  formula?: string;
  capability?: CapabilityAlignmentItem;
  dependencies: string[];
  level: number;
}

export interface CapabilityAlignmentItem {
  capabilityId: string;
  name?: string;
  status?: string;
  impact?: string;
  reason?: string;
  sourceRequirementId?: string | null;
  sourceRequirementText?: string | null;
  sourceDocument?: string | null;
  sourceReference?: string | null;
  recommendedAction?: string | null;
}

const normaliseLogicLabel = (value?: string): string =>
  String(value || "")
    .toLowerCase()
    .replace(/annual|flat|deducted|added|closing|ending/g, "")
    .replace(/[^a-z0-9]/g, "");

const inputStatus = (status?: string): LogicNodeStatus => {
  const value = String(status || "").toLowerCase();
  if (["missing", "not_available"].includes(value)) return "missing";
  if (["placeholder", "derived_placeholder", "default", "diagnostic", "not_supplied", "scenario_assumption"].includes(value)) return "provisional";
  return "ready";
};

export const ProjectionLogicGraph: React.FC<{
  inputs: ProjectionInput[];
  steps: MechanicsStep[];
  editableValues?: Record<string, string | number>;
  onInputChange?: (inputId: string, value: string) => void;
  inputConfigs?: Record<string, GraphInputConfig>;
  capabilities?: CapabilityAlignmentItem[];
}> = ({ inputs, steps, editableValues, onInputChange, inputConfigs, capabilities = [] }) => {
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [problemsOnly, setProblemsOnly] = React.useState(false);

  const graph = React.useMemo(() => {
    const capabilityByRequirement = new Map(
      capabilities.map((capability) => [String(capability.sourceRequirementId || ""), capability]),
    );
    const inputCapabilityRequirements: Record<string, string> = {
      coi_rate: "coi_table",
      policy_fee: "policy_admin_fees",
      surrender_schedule: "surrender_schedule",
    };
    const ruleCapabilityRequirements: Record<string, string> = {
      coi_charge_deducted: "coi_table",
      policy_admin_fee_deducted: "policy_admin_fees",
      surrender_charge: "surrender_schedule",
    };
    const nodes: LogicGraphNode[] = inputs.map((input, index) => ({
      id: `input:${input.id || index}`,
      inputId: input.id || String(index),
      kind: "input",
      label: input.label || input.id || "Input",
      status: editableValues && input.id && String(editableValues[input.id] ?? "").trim()
        ? (inputConfigs?.[input.id]?.enteredStatus || "ready")
        : inputStatus(input.status),
      detail: input.status,
      value: input.value,
      unit: input.unit,
      source: input.source,
      capability: capabilityByRequirement.get(inputCapabilityRequirements[input.id || ""]),
      dependencies: [],
      level: 0,
    }));
    const inputNodes = [...nodes];
    const ruleNodes: LogicGraphNode[] = [];

    const explicitInputIds: Record<string, string[]> = {
      premium_added: ["premium", "premium_mode"],
      coi_charge_deducted: ["face_amount", "coi_rate"],
      policy_admin_fee_deducted: ["policy_fee"],
      interest_credited: ["guaranteed_rate", "premium"],
      surrender_charge: ["face_amount", "surrender_schedule"],
      death_benefit: ["face_amount", "death_benefit_option"],
    };

    [...steps]
      .sort((a, b) => Number(a.order || 0) - Number(b.order || 0))
      .forEach((step, index) => {
        const stepId = step.id || `step-${index}`;
        const requestedLabels = (step.inputs || []).map((input) => normaliseLogicLabel(input.label));
        const dependencies = new Set<string>();

        for (const prior of ruleNodes) {
          const resultLabel = normaliseLogicLabel(
            steps.find((candidate) => `rule:${candidate.id || `step-${steps.indexOf(candidate)}`}` === prior.id)?.result?.label,
          );
          if (resultLabel && requestedLabels.some((label) => label === resultLabel || label.includes(resultLabel))) {
            dependencies.add(prior.id);
          }
        }
        for (const input of inputNodes) {
          const inputId = input.id.replace("input:", "");
          const label = normaliseLogicLabel(input.label);
          if (
            (explicitInputIds[stepId] || []).includes(inputId) ||
            (label && requestedLabels.some((requested) => requested === label || requested.includes(label)))
          ) {
            dependencies.add(input.id);
          }
        }

        const dependencyNodes = [...dependencies]
          .map((id) => [...inputNodes, ...ruleNodes].find((node) => node.id === id))
          .filter((node): node is LogicGraphNode => Boolean(node));
        const hasMissing = dependencyNodes.some((node) => node.status === "missing");
        const hasProvisional = dependencyNodes.some((node) => node.status === "provisional");
        const level = Math.max(1, ...dependencyNodes.map((node) => node.level + 1));
        ruleNodes.push({
          id: `rule:${stepId}`,
          kind: "rule",
          label: step.title || step.result?.label || `Step ${index + 1}`,
          status: hasMissing || hasProvisional ? "provisional" : "ready",
          detail: hasMissing ? "Uses a fallback because required data is missing" : hasProvisional ? "Uses a placeholder or default" : "Ready",
          value: step.result?.value,
          unit: step.result?.unit,
          source: step.result?.source,
          formula: step.formulaText,
          capability: capabilityByRequirement.get(ruleCapabilityRequirements[stepId]),
          dependencies: [...dependencies],
          level,
        });
      });

    return [...inputNodes, ...ruleNodes];
  }, [capabilities, editableValues, inputConfigs, inputs, steps]);

  const visibleIds = React.useMemo(() => {
    if (!problemsOnly) return new Set(graph.map((node) => node.id));
    const ids = new Set(graph.filter((node) => node.status !== "ready" || ["partial", "unsupported"].includes(String(node.capability?.status || "").toLowerCase())).map((node) => node.id));
    let changed = true;
    while (changed) {
      changed = false;
      for (const node of graph) {
        if (ids.has(node.id)) {
          for (const dependency of node.dependencies) {
            if (!ids.has(dependency)) {
              ids.add(dependency);
              changed = true;
            }
          }
        }
      }
    }
    return ids;
  }, [graph, problemsOnly]);

  const visibleNodes = graph.filter((node) => visibleIds.has(node.id));
  const levels = [...new Set(visibleNodes.map((node) => node.level))].sort((a, b) => a - b);
  const columnWidth = 250;
  const rowHeight = 124;
  const nodeWidth = 190;
  const nodeHeight = 90;
  const padding = 34;
  const maxRows = Math.max(1, ...levels.map((level) => visibleNodes.filter((node) => node.level === level).length));
  const width = Math.max(720, levels.length * columnWidth + padding * 2);
  const height = Math.max(360, maxRows * rowHeight + padding * 2);
  const positions = new Map<string, { x: number; y: number }>();
  levels.forEach((level, columnIndex) => {
    const column = visibleNodes.filter((node) => node.level === level);
    const offset = (height - column.length * rowHeight) / 2;
    column.forEach((node, rowIndex) => positions.set(node.id, { x: padding + columnIndex * columnWidth, y: offset + rowIndex * rowHeight }));
  });

  const selected = graph.find((node) => node.id === selectedId) || null;
  const problemCount = graph.filter((node) => node.status !== "ready" || ["partial", "unsupported"].includes(String(node.capability?.status || "").toLowerCase())).length;
  const unsupportedCapabilities = capabilities.filter((item) => String(item.status || "").toLowerCase() === "unsupported").length;
  const partialCapabilities = capabilities.filter((item) => String(item.status || "").toLowerCase() === "partial").length;

  return (
    <div className="logic-graph">
      <div className="logic-graph__toolbar">
        <div className="logic-graph__legend" aria-label="Graph status legend">
          <span><i className="logic-graph__dot logic-graph__dot--ready" />Ready</span>
          <span><i className="logic-graph__dot logic-graph__dot--provisional" />Placeholder / default</span>
          <span><i className="logic-graph__dot logic-graph__dot--missing" />Missing input</span>
          {(unsupportedCapabilities > 0 || partialCapabilities > 0) && (
            <span className="logic-graph__platform-summary">Platform gaps: {unsupportedCapabilities} unsupported · {partialCapabilities} partial</span>
          )}
        </div>
        <button type="button" className="button button-ghost" onClick={() => setProblemsOnly((value) => !value)}>
          {problemsOnly ? "Show all logic" : `Show problems only (${problemCount})`}
        </button>
      </div>
      <div className="logic-graph__viewport">
        <svg width={width} height={height} role="img" aria-label="Directed graph of projection inputs and calculation rules">
          <defs>
            <marker id="logic-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8 Z" className="logic-graph__arrowhead" />
            </marker>
          </defs>
          {visibleNodes.flatMap((node) => {
            const end = positions.get(node.id);
            if (!end) return [];
            return node.dependencies.map((dependency) => {
              const start = positions.get(dependency);
              if (!start || !visibleIds.has(dependency)) return null;
              const sourceNode = graph.find((candidate) => candidate.id === dependency);
              const affected = sourceNode?.status === "missing" || node.status === "missing";
              const x1 = start.x + nodeWidth;
              const y1 = start.y + nodeHeight / 2;
              const x2 = end.x;
              const y2 = end.y + nodeHeight / 2;
              const bend = Math.max(28, (x2 - x1) / 2);
              return <path key={`${dependency}-${node.id}`} d={`M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`} className={`logic-graph__edge${affected ? " logic-graph__edge--missing" : ""}`} markerEnd="url(#logic-arrow)" />;
            });
          })}
          {visibleNodes.map((node) => {
            const position = positions.get(node.id)!;
            const canEdit = node.kind === "input" && node.inputId && editableValues && node.inputId in editableValues;
            const config = node.inputId ? inputConfigs?.[node.inputId] : undefined;
            return (
              <g key={node.id} className={`logic-graph__node logic-graph__node--${node.status}${selectedId === node.id ? " is-selected" : ""}`} onClick={() => setSelectedId(node.id)} role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedId(node.id); }}>
                <rect x={position.x} y={position.y} width={nodeWidth} height={nodeHeight} rx="10" />
                {canEdit ? (
                  <foreignObject x={position.x + 10} y={position.y + 6} width={nodeWidth - 20} height={nodeHeight - (node.capability ? 24 : 10)}>
                    <label className="logic-graph__input" onClick={(event) => event.stopPropagation()}>
                      <span>{node.label === "Annual premium" ? "Modal premium" : node.label}</span>
                      {config?.kind === "select" ? (
                        <select
                          value={String(editableValues[node.inputId] ?? "")}
                          onChange={(event) => onInputChange?.(node.inputId!, event.target.value)}
                        >
                          {config.placeholder && <option value="">{config.placeholder}</option>}
                          {(config.options ?? []).map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type={config?.kind === "number" ? "number" : "text"}
                          min={config?.min}
                          max={config?.max}
                          step={config?.step}
                          value={editableValues[node.inputId] ?? ""}
                          placeholder={config?.placeholder}
                          onChange={(event) => onInputChange?.(node.inputId!, event.target.value)}
                        />
                      )}
                      {config?.help && <small>{config.help}</small>}
                    </label>
                  </foreignObject>
                ) : (
                  <>
                    <text x={position.x + 14} y={position.y + 20} className="logic-graph__kind">{node.kind === "input" ? "INPUT" : "RULE"}</text>
                    <text x={position.x + 14} y={position.y + 43} className="logic-graph__label">{node.label.length > 24 ? `${node.label.slice(0, 24)}…` : node.label}</text>
                    <text x={position.x + 14} y={position.y + 64} className="logic-graph__status">{node.detail || node.status}</text>
                  </>
                )}
                {node.capability && ["partial", "unsupported"].includes(String(node.capability.status || "").toLowerCase()) && (
                  <text x={position.x + 12} y={position.y + 82} className={`logic-graph__capability logic-graph__capability--${String(node.capability.status).toLowerCase()}`}>
                    PLATFORM: {String(node.capability.status).toUpperCase()}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      {selected && (
        <aside className={`logic-graph__detail logic-graph__detail--${selected.status}`}>
          <div>
            <span className="logic-graph__eyebrow">{selected.kind === "input" ? "Projection input" : "Calculation rule"}</span>
            <h3>{selected.label}</h3>
            <p className="muted">{selected.detail}</p>
          </div>
          <div>
            {selected.kind === "input" && selected.inputId && editableValues && selected.inputId in editableValues ? (
              <p><strong>Current value:</strong> {String(editableValues[selected.inputId] ?? "").trim()
                ? formatProjectionInputValue(editableValues[selected.inputId], selected.unit)
                : "No value or assumption supplied"}</p>
            ) : selected.value !== undefined && <p><strong>Current value:</strong> {formatProjectionInputValue(selected.value, selected.unit)}</p>}
            {selected.formula && <p><strong>Logic:</strong> {selected.formula}</p>}
            {selected.source && <p><strong>Source:</strong> {selected.source}</p>}
            {selected.capability && (
              <div className={`logic-graph__capability-detail logic-graph__capability-detail--${String(selected.capability.status || "unknown").toLowerCase()}`}>
                <p><strong>Platform capability:</strong> {selected.capability.name || selected.capability.capabilityId}</p>
                <p><strong>Status:</strong> {selected.capability.status || "Unknown"} · <strong>Impact:</strong> {selected.capability.impact || "Unknown"}</p>
                {selected.capability.reason && <p>{selected.capability.reason}</p>}
                {selected.capability.sourceRequirementText && <p><strong>Product requirement:</strong> {selected.capability.sourceRequirementText}</p>}
                {(selected.capability.sourceDocument || selected.capability.sourceReference) && (
                  <p><strong>Evidence:</strong> {selected.capability.sourceDocument || "Source document not recorded"}{selected.capability.sourceReference ? ` · Reference ${selected.capability.sourceReference}` : ""}</p>
                )}
                {selected.capability.recommendedAction && <p><strong>Next action:</strong> {selected.capability.recommendedAction}</p>}
              </div>
            )}
          </div>
        </aside>
      )}
    </div>
  );
};

export const ProjectionChart: React.FC<{ rows: WorkspaceRow[] }> = ({ rows }) => {
  const width = 720;
  const height = 280;
  const left = 58;
  const right = 16;
  const top = 18;
  const bottom = 42;
  const series = [
    { key: "cumulativePremium", label: "Cumulative premium", color: "#7c3aed" },
    { key: "cashValue", label: "Cash value", color: "#2563eb" },
    { key: "surrenderValue", label: "Surrender value", color: "#059669" },
    { key: "deathBenefit", label: "Death benefit", color: "#dc2626" },
  ] as const;
  type SeriesKey = (typeof series)[number]["key"];
  const [visible, setVisible] = React.useState<Record<SeriesKey, boolean>>({
    cumulativePremium: true,
    cashValue: true,
    surrenderValue: true,
    deathBenefit: false,
  });
  const visibleSeries = series.filter((item) => visible[item.key]);
  const values = rows.flatMap((row) =>
    visibleSeries.map((item) => Number(row[item.key] ?? 0)).filter((value) => Number.isFinite(value)),
  );
  const maxValue = Math.max(...values, 1);
  const minYear = Number(rows[0]?.year ?? 1);
  const maxYear = Number(rows[rows.length - 1]?.year ?? minYear + 1);
  const x = (year: number) =>
    left + ((year - minYear) / Math.max(maxYear - minYear, 1)) * (width - left - right);
  const y = (value: number) => top + (1 - value / maxValue) * (height - top - bottom);
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className="projection-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Projection values by policy year">
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={left}
              x2={width - right}
              y1={y(maxValue * tick)}
              y2={y(maxValue * tick)}
              className="projection-chart__grid"
            />
            <text x={left - 8} y={y(maxValue * tick) + 4} textAnchor="end" className="projection-chart__label">
              ${(maxValue * tick / 1000).toFixed(0)}k
            </text>
          </g>
        ))}
        {visibleSeries.map((item) => {
          const points = rows
            .map((row) => `${x(Number(row.year ?? minYear))},${y(Number(row[item.key] ?? 0))}`)
            .join(" ");
          return <polyline key={item.key} points={points} fill="none" stroke={item.color} strokeWidth="3" />;
        })}
        <text x={left} y={height - 12} className="projection-chart__label">Year {minYear}</text>
        <text x={width - right} y={height - 12} textAnchor="end" className="projection-chart__label">
          Year {maxYear}
        </text>
      </svg>
      <div className="projection-chart__legend">
        {series.map((item) => (
          <button
            type="button"
            key={item.key}
            className={visible[item.key] ? "is-visible" : ""}
            aria-pressed={visible[item.key]}
            onClick={() => setVisible((current) => ({ ...current, [item.key]: !current[item.key] }))}
          >
            <i style={{ backgroundColor: item.color }} /> {item.label}
          </button>
        ))}
      </div>
    </div>
  );
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

const formatProvenance = (value?: string | null): string => {
  const v = (value || "").toLowerCase();
  switch (v) {
    case "workspace_snapshot":
      return "Workspace snapshot";
    case "product_definition":
      return "Structured ProductDefinition";
    case "user_entered":
      return "User-entered";
    case "system_default":
      return "System default";
    case "unresolved":
      return "Unresolved / missing";
    default:
      return v ? formatStatusLabel(v) : "Unknown";
  }
};

const FEATURE_REQUEST_STATUSES = [
  "proposed",
  "approved",
  "rejected",
  "in_progress",
  "complete",
  "deferred",
] as const;

export const ProductWorkspacePage: React.FC<{
  snapshot?: WorkspacePayload | null;
  workspaceId?: string;
}> = ({ snapshot, workspaceId }) => {
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
  const [featureRequests, setFeatureRequests] = React.useState<FeatureRequest[] | null>(null);
  const [featureRequestsLoading, setFeatureRequestsLoading] = React.useState<boolean>(false);
  const [featureRequestsError, setFeatureRequestsError] = React.useState<string | null>(null);
  const [creatingCapabilityId, setCreatingCapabilityId] = React.useState<string | null>(null);
  const [updatingFeatureRequestId, setUpdatingFeatureRequestId] = React.useState<number | null>(null);
  const [showAdvancedDebug, setShowAdvancedDebug] = React.useState<boolean>(false);
  const [scenarioIllustration, setScenarioIllustration] =
    React.useState<WorkspacePayload["illustration"]>(null);
  const [scenarioMechanics, setScenarioMechanics] =
    React.useState<WorkspacePayload["mechanicsExplanation"]>(null);
  const [projectionRunning, setProjectionRunning] = React.useState<boolean>(false);
  const [projectionError, setProjectionError] = React.useState<string | null>(null);
  const [scenarioDirty, setScenarioDirty] = React.useState<boolean>(false);
  const [projectionForm, setProjectionForm] = React.useState({
    issueAge: 45,
    faceAmount: 100000,
    premiumMode: "ANNUAL",
    modalPremium: 3000,
    sex: "",
    riskClass: "",
    tobaccoStatus: "",
  });

  React.useEffect(() => {
    if (snapshot) {
      // When a snapshot is provided (workspace-based view), we skip the
      // product-code fetch entirely.
      setData(snapshot);
      setLoading(false);
      return;
    }

    setError("Workspace analysis is not available.");
    setLoading(false);
  }, [snapshot]);

  React.useEffect(() => {
    const request = data?.illustration?.request;
    if (!request) return;
    const annualPremium = data?.illustration?.rows?.[0]?.annualPremium;
    setProjectionForm({
      issueAge: Number(request.age ?? 45),
      faceAmount: Number(request.faceAmount ?? 100000),
      premiumMode: String(request.premiumMode ?? "ANNUAL"),
      modalPremium: Number(annualPremium ?? 3000),
      sex: String(request.sex ?? ""),
      riskClass: String(request.riskClass ?? ""),
      tobaccoStatus: String(request.tobaccoStatus ?? ""),
    });
    setScenarioIllustration(null);
    setScenarioMechanics(null);
    setScenarioDirty(false);
  }, [data?.illustration]);

  // Load existing feature requests when viewing a workspace-backed snapshot.
  React.useEffect(() => {
    if (!workspaceId) {
      setFeatureRequests(null);
      setFeatureRequestsError(null);
      return;
    }

    let cancelled = false;

    const load = async () => {
      try {
        setFeatureRequestsLoading(true);
        setFeatureRequestsError(null);
        const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/feature-requests`);
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text || `Failed to load feature requests (HTTP ${resp.status})`);
        }
        const body = (await resp.json()) as { featureRequests?: FeatureRequest[] };
        if (!cancelled) {
          setFeatureRequests(body.featureRequests ?? []);
        }
      } catch (err: any) {
        if (!cancelled) {
          setFeatureRequestsError(err?.message || "Failed to load feature requests.");
          setFeatureRequests([]);
        }
      } finally {
        if (!cancelled) {
          setFeatureRequestsLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const product = data?.product;
  const productUnderstanding = data?.productUnderstanding;
  const mechanicsSummary = data?.mechanics?.summary;
  const assumptions = data?.assumptions?.provenance ?? [];
  const evidenceItems = data?.evidence?.items ?? [];
  const compliance = data?.complianceMatrix;
  const readiness = data?.readinessDashboard;
  const gaps = data?.gaps;
  const illustration = scenarioIllustration ?? data?.illustration;
  const keyProjectionYears = new Set([1, 2, 3, 4, 5, 10, 15, 20, 25, 30]);
  const keyProjectionRows = (illustration?.rows ?? []).filter((row) =>
    keyProjectionYears.has(Number(row.year)),
  );
  const mechanicsExplanation = scenarioMechanics ?? data?.mechanicsExplanation;
  const pmr = data?.pmrReadiness;
  const documentInventory = data?.documentInventory;
  const extractedFacts = data?.extractedFacts ?? [];
  const requirementsCandidates = data?.requirementsCandidates ?? [];
  const capabilityAssessment = data?.capabilityAssessment;

  const gapItems = gaps?.items ?? [];
  // Build a short product identity description from product metadata
  // only. Mechanics and other provisional assumptions are surfaced in
  // their own sections so they do not blur identity confidence with
  // projection behaviour.
  const overviewParts: string[] = [];
  if (product) {
    const name = product.name || product.code || "This product";
    const type = product.type || "universal life";
    overviewParts.push(`${name} appears to be a ${type} product.`);
  } else {
    overviewParts.push("This product appears to be a universal life insurance product.");
  }

  const overviewText = overviewParts.join(" ");

  const capabilityItems =
    capabilityAssessment && Array.isArray(capabilityAssessment.items) ? capabilityAssessment.items : [];

  const capabilityHasItems = capabilityItems.length > 0;

  const featureRequestForCapability = (capabilityId: string): FeatureRequest | undefined => {
    if (!featureRequests || !Array.isArray(featureRequests)) return undefined;
    const cid = (capabilityId || "").toString();
    return featureRequests.find((fr) => (fr.capabilityId || "") === cid);
  };

  const reloadFeatureRequests = async () => {
    if (!workspaceId) return;
    try {
      setFeatureRequestsLoading(true);
      setFeatureRequestsError(null);
      const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/feature-requests`);
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Failed to load feature requests (HTTP ${resp.status})`);
      }
      const body = (await resp.json()) as { featureRequests?: FeatureRequest[] };
      setFeatureRequests(body.featureRequests ?? []);
    } catch (err: any) {
      setFeatureRequestsError(err?.message || "Failed to load feature requests.");
    } finally {
      setFeatureRequestsLoading(false);
    }
  };

  const handleCreateFeatureRequest = async (item: any) => {
    if (!workspaceId) return;
    const cid = (item.capabilityId || "").toString();
    if (!cid) return;
    setCreatingCapabilityId(cid);
    try {
      const payload = {
        capabilityId: cid,
        name: item.name || undefined,
        impact: item.impact || undefined,
        reason: item.reason || undefined,
        sourceRequirementId: item.sourceRequirementId || undefined,
        sourceRequirementText: item.sourceRequirementText || undefined,
        sourceDocument: item.sourceDocument || undefined,
        sourceReference: item.sourceReference || undefined,
        productCode: item.productCode || product?.code || undefined,
        priority: undefined,
      };

      const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/feature-requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Failed to create feature request (HTTP ${resp.status})`);
      }
      const body = (await resp.json()) as { featureRequest?: FeatureRequest };
      if (body.featureRequest) {
        // Merge into local list without duplicating.
        setFeatureRequests((prev) => {
          const base = Array.isArray(prev) ? [...prev] : [];
          const existingIdx = base.findIndex((fr) => fr.id === body.featureRequest!.id);
          if (existingIdx >= 0) {
            base[existingIdx] = body.featureRequest!;
          } else {
            base.push(body.featureRequest!);
          }
          return base;
        });
      } else {
        // Fallback: reload from server if shape was unexpected.
        await reloadFeatureRequests();
      }
    } catch (err: any) {
      setFeatureRequestsError(err?.message || "Failed to create feature request.");
    } finally {
      setCreatingCapabilityId(null);
    }
  };

  const handleUpdateFeatureRequestStatus = async (featureRequest: FeatureRequest, status: string) => {
    if (!workspaceId || !featureRequest?.id) return;
    const next = (status || "").toLowerCase();
    if (!next) return;
    setUpdatingFeatureRequestId(featureRequest.id);
    try {
      const resp = await fetch(
        `/api/workspaces/${encodeURIComponent(workspaceId)}/feature-requests/${encodeURIComponent(String(featureRequest.id))}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: next }),
        },
      );
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Failed to update feature request (HTTP ${resp.status})`);
      }
      const body = (await resp.json()) as { featureRequest?: FeatureRequest };
      if (body.featureRequest) {
        setFeatureRequests((prev) => {
          const base = Array.isArray(prev) ? [...prev] : [];
          const idx = base.findIndex((fr) => fr.id === body.featureRequest!.id);
          if (idx >= 0) {
            base[idx] = body.featureRequest!;
          } else {
            base.push(body.featureRequest!);
          }
          return base;
        });
      } else {
        await reloadFeatureRequests();
      }
    } catch (err: any) {
      setFeatureRequestsError(err?.message || "Failed to update feature request status.");
    } finally {
      setUpdatingFeatureRequestId(null);
    }
  };

  const hasMaterialProjectionGaps = gapItems.some((g) => {
    const id = (g.id || "").toString().toLowerCase();
    return (
      id === "missing_coi_table" ||
      id === "surrender_schedule_placeholder" ||
      id === "policy_admin_fee_missing"
    );
  });

  const runProjectionScenario = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!workspaceId) {
      setProjectionError("Open this projection from a workspace to run scenarios.");
      return;
    }
    setProjectionRunning(true);
    setProjectionError(null);
    try {
      const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/projection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(projectionForm),
      });
      if (!response.ok) {
        throw new Error((await response.text()) || `Projection failed (HTTP ${response.status})`);
      }
      const body = (await response.json()) as {
        illustration?: WorkspacePayload["illustration"];
        mechanicsExplanation?: WorkspacePayload["mechanicsExplanation"];
      };
      setScenarioIllustration(body.illustration ?? null);
      setScenarioMechanics(body.mechanicsExplanation ?? null);
      setScenarioDirty(false);
    } catch (err: any) {
      setProjectionError(err?.message || "Projection failed.");
    } finally {
      setProjectionRunning(false);
    }
  };

  const uploadWorkspaceDocument: React.ChangeEventHandler<HTMLInputElement> = async (event) => {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) return;
    setDashboardUploading(true);
    setDashboardUploadMessage(null);
    try {
      if (!workspaceId) throw new Error("Workspace context is required.");
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/documents`, {
          method: "POST",
          body: form,
        });
        if (!response.ok) {
          throw new Error(
            `${file.name}: ${(await response.text()) || `upload failed (HTTP ${response.status})`}`,
          );
        }
      }
      setDashboardUploadMessage(
        `Uploaded ${files.length} document${files.length === 1 ? "" : "s"}. Rerun analysis to incorporate ${
          files.length === 1 ? "it" : "them"
        } into product understanding.`,
      );
    } catch (err: any) {
      setDashboardUploadMessage(err?.message || "Upload failed.");
    } finally {
      setDashboardUploading(false);
      event.target.value = "";
    }
  };

  const rerunWorkspaceUnderstanding = async () => {
    setDashboardUploadMessage("Rerunning analysis with all workspace documents…");
    try {
      if (!workspaceId) throw new Error("Workspace context is required.");
      const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/analyze`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error((await response.text()) || `Analysis failed (HTTP ${response.status})`);
      }
      const body = await response.json();
      setData(body.snapshot as WorkspacePayload);
      setDashboardUploadMessage("Product understanding updated from all workspace documents.");
    } catch (err: any) {
      setDashboardUploadMessage(err?.message || "Failed to rerun analysis.");
    }
  };

  const downloadProjectionCsv = () => {
    const rows = illustration?.rows ?? [];
    if (rows.length === 0) return;
    const columns: Array<[keyof WorkspaceRow, string]> = [
      ["year", "Policy Year"],
      ["attainedAge", "Attained Age"],
      ["openingPolicyValue", "Opening Policy Value"],
      ["annualPremium", "Annual Premium"],
      ["cumulativePremium", "Cumulative Premium"],
      ["premiumLoad", "Premium Load"],
      ["coiCharge", "COI Charge"],
      ["policyFee", "Policy/Admin Fee"],
      ["guaranteedInterest", "Interest Credited"],
      ["endingPolicyValue", "Ending Policy Value"],
      ["surrenderCharge", "Surrender Charge"],
      ["surrenderValue", "Cash Surrender Value"],
      ["deathBenefit", "Death Benefit"],
      ["netAmountAtRisk", "Net Amount at Risk"],
    ];
    const escape = (value: any) => `"${String(value ?? "").replace(/"/g, '""')}"`;
    const csv = [
      columns.map(([, label]) => escape(label)).join(","),
      ...rows.map((row) => columns.map(([key]) => escape(row[key])).join(",")),
    ].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${product?.code || "ul"}-diagnostic-projection.csv`.replace(/\s+/g, "-");
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="home-page">
      <header className="card">
        <h1>Product Understanding Workspace</h1>
        <p className="muted">
          Guided review surface for the current product understanding. Start at the top, work through each section,
          and record workspace actions for any unsupported capabilities.
        </p>
        <p>
          <a href={`/web?workspace=${encodeURIComponent(workspaceId || "")}`} className="button">
            Back to graph workspace
          </a>
        </p>
        {loading && <p className="muted">Loading product workspace…</p>}
        {error && !loading && <p className="error">{error}</p>}
        <p className="muted" style={{ marginTop: "0.5rem" }}>
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setShowAdvancedDebug((v) => !v)}
          >
            {showAdvancedDebug ? "Hide advanced debug sections" : "Show advanced debug sections"}
          </button>
        </p>
      </header>

      <section className="card home-card">
        <h2>Executive Review Summary</h2>
        <p className="muted">
          Quick view of what product this appears to be, how trustworthy the current analysis is, and what you should
          do next.
        </p>
        <table className="kv-table">
          <tbody>
            <tr>
              <th>Product identity</th>
              <td>{overviewText || "Not available in current analysis"}</td>
            </tr>
            <tr>
              <th>Product identity confidence</th>
              <td>{formatStatusLabel(productUnderstanding?.confidence || "partial")}</td>
            </tr>
            <tr>
              <th>Document coverage</th>
              <td>
                {Array.isArray(documentInventory) && documentInventory.length > 0
                  ? `${documentInventory.length} workspace document${
                      documentInventory.length === 1 ? "" : "s"
                    }`
                  : "No workspace documents recorded yet"}
              </td>
            </tr>
            <tr>
              <th>Requirements identified</th>
              <td>{productUnderstanding?.requirementsIdentified ?? 0}</td>
            </tr>
            <tr>
              <th>Implementation alignment</th>
              <td>
                {compliance && compliance.summary
                  ? `Implemented: ${compliance.summary.implemented ?? 0}, Partial: ${
                      compliance.summary.partial ?? 0
                    }, Missing: ${compliance.summary.missing ?? 0}`
                  : "Compliance summary is not available yet for this product."}
              </td>
            </tr>
            <tr>
              <th>Projection readiness</th>
              <td>
                {hasMaterialProjectionGaps
                  ? "Diagnostic only – key inputs are missing or provisional"
                  : formatProjectionTrustLevel(readiness?.projectionTrustLevel || "unknown")}
              </td>
            </tr>
            <tr>
              <th>Next suggested action</th>
              <td>
                {readiness?.recommendedNextAction ||
                  (Array.isArray(gapItems) && gapItems.length > 0
                    ? "Review gaps and upload supporting documents where suggested, then rerun understanding."
                    : "Review requirements & compliance, then decide whether additional evidence is needed.")}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section className="card home-card">
        <h2>Product Understanding (system-generated draft)</h2>
        <p>
          <span className="tag">Deterministic extraction</span>{" "}
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
                <th>Uploaded Forms</th>
                <td>
                  {productUnderstanding.formNumbers && productUnderstanding.formNumbers.length > 0
                    ? productUnderstanding.formNumbers.join(", ")
                    : "Not available in current analysis"}
                </td>
              </tr>
              <tr>
                <th>Primary Forms</th>
                <td>{productUnderstanding.formClassifications?.primary?.join(", ") || "Not identified"}</td>
              </tr>
              <tr>
                <th>Riders</th>
                <td>{productUnderstanding.formClassifications?.riders?.join(", ") || "Not identified"}</td>
              </tr>
              <tr>
                <th>Supplements / Endorsements</th>
                <td>{productUnderstanding.formClassifications?.supplements?.join(", ") || "Not identified"}</td>
              </tr>
              <tr>
                <th>Issue Age Range</th>
                <td>
                  {productUnderstanding.issueAgeRange || "Not available in current analysis"}
                  {productUnderstanding.issueAgeSource && (
                    <small className="fact-source">Source: {productUnderstanding.issueAgeSource}</small>
                  )}
                </td>
              </tr>
              <tr>
                <th>Risk Classes</th>
                <td>
                  {productUnderstanding.riskClasses && productUnderstanding.riskClasses.length > 0
                    ? productUnderstanding.riskClasses.join(", ")
                    : "Not available in current analysis"}
                  {productUnderstanding.riskClassesSource && (
                    <small className="fact-source">Source: {productUnderstanding.riskClassesSource}</small>
                  )}
                </td>
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
          Uploaded filing documents and whether their text was available to this analysis.
        </p>
        <div className="workspace-document-actions">
          <h3>Add documents and rerun analysis</h3>
          <p className="muted">
            Upload any additional filing, rate table, schedule, memorandum, or supporting document. Then rerun
            analysis to rebuild product understanding from the complete workspace document set.
          </p>
          <div className="gap-actions">
            <label className="button button-secondary">
              {dashboardUploading ? "Uploading…" : "Add documents"}
              <input
                type="file"
                multiple
                style={{ display: "none" }}
                disabled={dashboardUploading || !workspaceId}
                onChange={uploadWorkspaceDocument}
              />
            </label>
            <button
              type="button"
              className="button button-ghost"
              disabled={dashboardUploading || !workspaceId}
              onClick={() => void rerunWorkspaceUnderstanding()}
            >
              Rerun analysis
            </button>
          </div>
          {dashboardUploadMessage && <p className="muted" role="status">{dashboardUploadMessage}</p>}
        </div>
        {documentInventory && documentInventory.length > 0 ? (
          <details>
            <summary>
              {documentInventory.length} document{documentInventory.length === 1 ? "" : "s"} analyzed
            </summary>
            <div className="table-scroll">
              <table className="kv-table">
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Pages</th>
                    <th>Status</th>
                    {showAdvancedDebug && <th>Object path</th>}
                  </tr>
                </thead>
                <tbody>
                  {documentInventory.map((d, idx) => (
                    <tr key={d.id ?? d.objectPath ?? String(d.createdAt) ?? idx}>
                      <td>{d.description || "(no description)"}</td>
                      <td>{d.pageCount ?? "—"}</td>
                      <td>{formatStatusLabel(d.processingStatus || "uploaded")}</td>
                      {showAdvancedDebug && <td className="technical-path">{d.objectPath || "(not set)"}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        ) : (
          <p className="muted">
            {loading
              ? "Loading document inventory…"
              : "No workspace-specific document inventory is available. This MVP does not yet link product snapshots to individual workspace documents."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Extracted Facts</h2>
        <p>
          <span className="tag">Extracted or inferred</span>{" "}
          <span className="tag">Needs actuarial review</span>
        </p>
        <p className="muted">
          Deterministic facts from uploaded documents and the current workspace snapshot. Each row distinguishes
          extracted evidence from inference or unresolved data.
        </p>
        {extractedFacts && extractedFacts.length > 0 ? (
          <details>
            <summary>{extractedFacts.length} extracted, inferred, and unresolved facts</summary>
            <div className="table-scroll">
          <table className="kv-table">
            <thead>
              <tr>
                <th>Fact</th>
                <th>Value</th>
                <th>Status</th>
                <th>Provenance</th>
                <th>Source detail</th>
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
                  <td>{formatProvenance(f.provenanceKind || "")}</td>
                  <td>{f.source || "(not recorded)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
            </div>
          </details>
        ) : (
          <p className="muted">
            {loading
              ? "Loading extracted facts…"
              : "No extracted facts snapshot is available yet for this workspace."}
          </p>
        )}
      </section>

      {showAdvancedDebug && <section className="card home-card">
        <h2>Product summary</h2>
        {product ? (
          <table className="kv-table">
            <tbody>
              <tr>
                <th>Product code</th>
                <td>{product.code || "(unknown)"}</td>
              </tr>
              <tr>
                <th>Product name</th>
                <td>{product.name || "(unknown)"}</td>
              </tr>
              <tr>
                <th>Product type</th>
                <td>{product.type || "(unknown)"}</td>
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
      </section>}

      {showAdvancedDebug && (
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
      )}

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
        <h2>Candidate Requirements (rules-based)</h2>
        <p>
          <span className="tag">Deterministic candidate</span>{" "}
          <span className="tag">Needs actuarial review</span>
        </p>
        <p className="muted">
          Predefined implementation requirements checked against workspace evidence. These are confirmations and
          probable matches, not independently discovered filing requirements.
        </p>
        {requirementsCandidates && requirementsCandidates.length > 0 ? (
          <details>
            <summary>{requirementsCandidates.length} requirement candidates</summary>
            <div className="table-scroll">
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
                      ? `${(r.confidence * 100).toFixed(0)}%${
                          r.confidence < 0.99 ? " (probable match)" : ""
                        }`
                      : "Unknown"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
            </div>
          </details>
        ) : (
          <p className="muted">
            {loading
              ? "Loading candidate requirements…"
              : "No candidate requirements are available yet for this workspace."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Platform Capability Alignment</h2>
        <p className="muted">
          This section tracks only mechanics that need implementation attention. It is not a summary of every
          supported product requirement.
        </p>
        {capabilityHasItems ? (
          <>
            {capabilityAssessment?.summary && (
              <p className="muted">
                Tracked capability gaps: Unsupported {capabilityAssessment.summary?.unsupported ?? 0}, Partial{" "}
                {capabilityAssessment.summary?.partial ?? 0}, Supported {" "}
                {capabilityAssessment.summary?.supported ?? 0}
              </p>
            )}
            <div className="compliance-list">
              {capabilityItems.map((item) => {
                const fr = featureRequestForCapability(item.capabilityId);
                const statusLabel = formatStatusLabel(item.status || "unsupported");
                const impactLabel = formatStatusLabel(item.impact || "unknown");
                const frStatusLabel = fr ? formatStatusLabel(fr.status || "proposed") : null;
                const createDisabled = !workspaceId || !!fr || creatingCapabilityId === item.capabilityId;
                const buttonLabel =
                  creatingCapabilityId === item.capabilityId ? "Creating…" : "Create Feature Request";

                return (
                  <div key={item.capabilityId} className="compliance-item">
                    <h3>{item.name || item.capabilityId}</h3>
                    <p className="muted">
                      <strong>Status:</strong> {statusLabel} | <strong>Impact:</strong> {impactLabel}
                    </p>
                    {item.reason && <p className="muted">{item.reason}</p>}
                    {item.sourceRequirementText && (
                      <p className="muted">
                        <strong>Source requirement:</strong> {item.sourceRequirementText}
                      </p>
                    )}
                    {(item.sourceDocument || item.sourceReference) && (
                      <p className="muted">
                        <strong>Source document:</strong> {item.sourceDocument || "(not recorded)"};{" "}
                        <strong>Reference:</strong> {item.sourceReference || "(not recorded)"}
                      </p>
                    )}
                    {fr ? (
                      <p className="muted">
                        Feature Request:{" "}
                        <span className="tag">{frStatusLabel}</span>
                      </p>
                    ) : workspaceId ? (
                      <button
                        type="button"
                        className="button button-secondary"
                        disabled={createDisabled}
                        onClick={() => handleCreateFeatureRequest(item)}
                      >
                        {buttonLabel}
                      </button>
                    ) : (
                      <p className="muted">Open this product via a workspace to file feature requests.</p>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <p className="muted">
            {loading
              ? "Loading capability assessment…"
              : "No platform capability assessment is available for this workspace."}
          </p>
        )}
      </section>

      <section className="card home-card">
        <h2>Feature Requests</h2>
        <p className="muted">
          Local feature requests for this workspace. These stay within the product workspace and are not synced to
          Jira, Linear, or any external system.
        </p>
        {!workspaceId ? (
          <p className="muted">Feature requests are available only when viewing a specific workspace.</p>
        ) : featureRequestsLoading ? (
          <p className="muted">Loading feature requests…</p>
        ) : featureRequestsError ? (
          <p className="error">{featureRequestsError}</p>
        ) : featureRequests && featureRequests.length > 0 ? (
          <table className="kv-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Capability</th>
                <th>Priority</th>
                <th>Status</th>
                <th>Source requirement</th>
                <th>Created at</th>
              </tr>
            </thead>
            <tbody>
              {featureRequests.map((fr) => (
                <tr key={fr.id}>
                  <td>{fr.title}</td>
                  <td>{fr.capabilityId}</td>
                  <td>{fr.priority || "(unset)"}</td>
                  <td>
                    <select
                      value={fr.status}
                      onChange={(e) => handleUpdateFeatureRequestStatus(fr, e.target.value)}
                      disabled={updatingFeatureRequestId === fr.id}
                    >
                      {FEATURE_REQUEST_STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {formatStatusLabel(s)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>{fr.sourceRequirementText || fr.sourceRequirementId || "(not recorded)"}</td>
                  <td>{fr.createdAt || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No feature requests have been created for this workspace yet.</p>
        )}
      </section>

      {showAdvancedDebug && (
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
      )}

      {showAdvancedDebug && (
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
      )}

      <section className="card home-card">
        <h2>Missing information / gaps</h2>
        <p className="muted">
          Uploading additional support documents improves evidence for mechanics and assumptions, but does not
          automatically make this draft projection filed-rate compliant. Rerun the workspace analysis after adding
          evidence.
        </p>
        {uploadMessage && <p className="muted">{uploadMessage}</p>}
            {gaps && gaps.items && gaps.items.length > 0 ? (
          <>
            {gaps.items.map((item) => {
              const isUploading = uploadingId === item.id;

                const handleFileChange: React.ChangeEventHandler<HTMLInputElement> = async (event) => {
                  const file = event.target.files && event.target.files[0];
                  if (!file) return;
                  setUploadingId(item.id);
                  setUploadMessage(null);
                  try {
                    const form = new FormData();
                    form.append("file", file);
                    form.append("gap_id", item.id);
                    if (!workspaceId) {
                      throw new Error("Workspace context is required.");
                    }
                    const resp = await fetch(
                      `/api/workspaces/${encodeURIComponent(workspaceId)}/documents`,
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
                    `Uploaded '${file.name}' to this workspace. Rerun analysis to incorporate the new evidence.`,
                  );
                } catch (e: any) {
                  setUploadMessage(e?.message || "Upload failed.");
                } finally {
                  setUploadingId(null);
                  event.target.value = "";
                }
                  };

                  const handleRerunClick = () => {
                    const rerun = async () => {
                      try {
                        setUploadMessage("Rerunning understanding for this workspace…");
                        if (workspaceId) {
                          const resp = await fetch(
                            `/api/workspaces/${encodeURIComponent(workspaceId)}/analyze`,
                            { method: "POST" },
                          );
                          if (!resp.ok) {
                            const text = await resp.text();
                            throw new Error(text || `Analyze failed with status ${resp.status}`);
                          }
                          const body = await resp.json();
                          const snap = body.snapshot as WorkspacePayload;
                          setData(snap);
                          setUploadMessage("Workspace understanding updated from latest evidence.");
                        } else {
                          setUploadMessage(
                            "Unable to rerun understanding: no workspace context is available in this view.",
                          );
                        }
                      } catch (err: any) {
                        setUploadMessage(err?.message || "Failed to rerun understanding.");
                      }
                    };

                    void rerun();
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
                      Rerun understanding
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
              {hasMaterialProjectionGaps
                ? "Diagnostic projection only. Not suitable for product validation, filed-rate review, or customer illustration. Key inputs are missing or provisional."
                : "Draft projection for product understanding. This is not a filed-rate compliant carrier illustration."}
            </p>
            <form className="projection-scenario" onSubmit={runProjectionScenario}>
              <h3>Diagnostic scenario</h3>
              <p className="muted">
                <span className="tag">
                  {scenarioIllustration
                    ? scenarioDirty
                      ? "Edited — run to apply"
                      : "User-entered scenario applied"
                    : scenarioDirty
                      ? "Edited — run to apply"
                      : "Derived default scenario"}
                </span>{" "}
                Guaranteed/default basis; a current-scale scenario is not modeled.
              </p>
              <div className="projection-scenario__grid">
                <label>
                  Issue age
                  <input
                    type="number"
                    min="0"
                    max="120"
                    value={projectionForm.issueAge}
                    onChange={(event) => {
                      setScenarioDirty(true);
                      setProjectionForm((current) => ({ ...current, issueAge: Number(event.target.value) }));
                    }}
                  />
                </label>
                <label>
                  Face amount
                  <input
                    type="number"
                    min="1"
                    step="1000"
                    value={projectionForm.faceAmount}
                    onChange={(event) => {
                      setScenarioDirty(true);
                      setProjectionForm((current) => ({ ...current, faceAmount: Number(event.target.value) }));
                    }}
                  />
                </label>
                <label>
                  Premium mode
                  <select
                    value={projectionForm.premiumMode}
                    onChange={(event) => {
                      setScenarioDirty(true);
                      setProjectionForm((current) => ({ ...current, premiumMode: event.target.value }));
                    }}
                  >
                    <option value="ANNUAL">Annual</option>
                    <option value="SEMIANNUAL">Semiannual</option>
                    <option value="QUARTERLY">Quarterly</option>
                    <option value="MONTHLY">Monthly</option>
                  </select>
                </label>
                <label>
                  Modal premium
                  <input
                    type="number"
                    min="1"
                    step="100"
                    value={projectionForm.modalPremium}
                    onChange={(event) => {
                      setScenarioDirty(true);
                      setProjectionForm((current) => ({ ...current, modalPremium: Number(event.target.value) }));
                    }}
                  />
                </label>
                <label>
                  Sex (as filed)
                  <input
                    type="text"
                    value={projectionForm.sex}
                    placeholder="e.g. F"
                    onChange={(event) => {
                      setScenarioDirty(true);
                      setProjectionForm((current) => ({ ...current, sex: event.target.value }));
                    }}
                  />
                </label>
                <label>
                  Underwriting / risk class
                  <input
                    type="text"
                    value={projectionForm.riskClass}
                    placeholder="e.g. Standard"
                    onChange={(event) => {
                      setScenarioDirty(true);
                      setProjectionForm((current) => ({ ...current, riskClass: event.target.value }));
                    }}
                  />
                </label>
                <label>
                  Tobacco / nicotine status
                  <input
                    type="text"
                    value={projectionForm.tobaccoStatus}
                    placeholder="e.g. Non-Tobacco"
                    onChange={(event) => {
                      setScenarioDirty(true);
                      setProjectionForm((current) => ({ ...current, tobaccoStatus: event.target.value }));
                    }}
                  />
                </label>
              </div>
              <p>
                <button type="submit" className="button button-secondary" disabled={projectionRunning}>
                  {projectionRunning ? "Running…" : "Run diagnostic projection"}
                </button>
              </p>
              {projectionError && <p className="error">{projectionError}</p>}
            </form>
            {hasMaterialProjectionGaps && (
              <div className="projection-summary">
                <p className="muted">
                  <strong>Why diagnostic only?</strong>
                </p>
                <ul className="muted">
                  {gapItems.some((g) => (g.id || "") === "missing_coi_table") && (
                    <li>
                      COI rates are placeholder. Actual cost of insurance tables may materially change policy charges
                      and cash values.
                    </li>
                  )}
                  {gapItems.some((g) => (g.id || "") === "surrender_schedule_placeholder") && (
                    <li>
                      Surrender charges use a simplified schedule. Filed surrender patterns may change early duration
                      surrender values.
                    </li>
                  )}
                  {gapItems.some((g) => (g.id || "") === "policy_admin_fee_missing") && (
                    <li>
                      Policy/admin fees are missing. Actual fee schedules will reduce projected account and surrender
                      values.
                    </li>
                  )}
                </ul>
              </div>
            )}
            {illustration.inputs && illustration.inputs.length > 0 && (
              <>
                <h3>Projection inputs and provenance</h3>
                <div className="table-scroll projection-inputs--desktop">
                  <table className="kv-table">
                    <thead>
                      <tr>
                        <th>Input</th>
                        <th>Value</th>
                        <th>Status</th>
                        <th>Source / derivation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {illustration.inputs.map((input) => (
                        <tr key={input.id ?? input.label}>
                          <td>{input.label}</td>
                          <td>{formatProjectionInputValue(input.value, input.unit)}</td>
                          <td>{formatStatusLabel(input.status)}</td>
                          <td>{input.source || "(not recorded)"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="projection-input-cards">
                  {illustration.inputs.map((input) => (
                    <article className="projection-input-card" key={input.id ?? input.label}>
                      <h4>{input.label}</h4>
                      <p>{formatProjectionInputValue(input.value, input.unit)}</p>
                      <p><span className="tag">{formatStatusLabel(input.status)}</span></p>
                      <small>{input.source || "(source not recorded)"}</small>
                    </article>
                  ))}
                </div>
              </>
            )}
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
            {illustration.rows && illustration.rows.length > 0 && (
              <>
                <h3>Projected values</h3>
                <ProjectionChart rows={illustration.rows} />
                <p>
                  <button type="button" className="button button-secondary" onClick={downloadProjectionCsv}>
                    Download full ledger CSV
                  </button>
                </p>
                <h4>Key policy durations</h4>
                <div className="projection-key-durations">
                  {keyProjectionRows.map((row, idx) => (
                    <article className="projection-key-duration" key={row.year ?? idx}>
                      <h4>Year {row.year} · Age {row.attainedAge ?? "—"}</h4>
                      <dl>
                        <div><dt>Cumulative premium</dt><dd>{formatCurrency(row.cumulativePremium)}</dd></div>
                        <div><dt>Ending value</dt><dd>{formatCurrency(row.endingPolicyValue ?? row.policyValue)}</dd></div>
                        <div><dt>Cash surrender value</dt><dd>{formatCurrency(row.surrenderValue)}</dd></div>
                        <div><dt>Death benefit</dt><dd>{formatCurrency(row.deathBenefit)}</dd></div>
                      </dl>
                    </article>
                  ))}
                </div>
                <details>
                  <summary>{illustration.rows.length}-year annual projection ledger</summary>
                  <div className="table-scroll projection-ledger projection-ledger--desktop">
                    <table className="kv-table">
                      <thead>
                        <tr>
                          <th>Year</th>
                          <th>Age</th>
                          <th>Opening value</th>
                          <th>Premium</th>
                          <th>Cumulative premium</th>
                          <th>Premium load</th>
                          <th>COI</th>
                          <th>Policy fee</th>
                          <th>Interest</th>
                          <th>Ending value</th>
                          <th>Surrender charge</th>
                          <th>Cash surrender value</th>
                          <th>Death benefit</th>
                          <th>Net amount at risk</th>
                        </tr>
                      </thead>
                      <tbody>
                        {illustration.rows.map((row, idx) => (
                          <tr key={row.year ?? idx}>
                            <td>{row.year}</td>
                            <td>{row.attainedAge ?? ""}</td>
                            <td>{formatCurrency(row.openingPolicyValue)}</td>
                            <td>{formatCurrency(row.annualPremium)}</td>
                            <td>{formatCurrency(row.cumulativePremium)}</td>
                            <td>{formatCurrency(row.premiumLoad)}</td>
                            <td>{formatCurrency(row.coiCharge)}</td>
                            <td>{formatCurrency(row.policyFee)}</td>
                            <td>{formatCurrency(row.guaranteedInterest)}</td>
                            <td>{formatCurrency(row.endingPolicyValue ?? row.policyValue)}</td>
                            <td>{formatCurrency(row.surrenderCharge)}</td>
                            <td>{formatCurrency(row.surrenderValue)}</td>
                            <td>{formatCurrency(row.deathBenefit)}</td>
                            <td>{formatCurrency(row.netAmountAtRisk)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="projection-ledger-cards">
                    {illustration.rows.map((row, idx) => (
                      <article className="projection-ledger-card" key={row.year ?? idx}>
                        <h4>Year {row.year} · Age {row.attainedAge ?? "—"}</h4>
                        <dl>
                          <div><dt>Opening value</dt><dd>{formatCurrency(row.openingPolicyValue)}</dd></div>
                          <div><dt>Premium</dt><dd>{formatCurrency(row.annualPremium)}</dd></div>
                          <div><dt>Cumulative premium</dt><dd>{formatCurrency(row.cumulativePremium)}</dd></div>
                          <div><dt>Premium load</dt><dd>{formatCurrency(row.premiumLoad)}</dd></div>
                          <div><dt>COI</dt><dd>{formatCurrency(row.coiCharge)}</dd></div>
                          <div><dt>Policy fee</dt><dd>{formatCurrency(row.policyFee)}</dd></div>
                          <div><dt>Interest</dt><dd>{formatCurrency(row.guaranteedInterest)}</dd></div>
                          <div><dt>Ending value</dt><dd>{formatCurrency(row.endingPolicyValue ?? row.policyValue)}</dd></div>
                          <div><dt>Surrender charge</dt><dd>{formatCurrency(row.surrenderCharge)}</dd></div>
                          <div><dt>Cash surrender value</dt><dd>{formatCurrency(row.surrenderValue)}</dd></div>
                          <div><dt>Death benefit</dt><dd>{formatCurrency(row.deathBenefit)}</dd></div>
                          <div><dt>Net amount at risk</dt><dd>{formatCurrency(row.netAmountAtRisk)}</dd></div>
                        </dl>
                      </article>
                    ))}
                  </div>
                </details>
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
        <h2>Projection logic graph</h2>
        {mechanicsExplanation && mechanicsExplanation.steps && mechanicsExplanation.steps.length > 0 ? (
          <>
            <p className="muted">
              Follow projection inputs into the rules they drive. Missing inputs are red; calculations using defaults
              or placeholders are amber. Select a node to inspect its value, source, and logic.
            </p>
            <p>
              <a className="button" href={`/web?workspace=${encodeURIComponent(workspaceId || "")}`}>
                Back to graph workspace
              </a>
            </p>
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

      {showAdvancedDebug && <section className="card home-card">
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
      </section>}
    </div>
  );
};
