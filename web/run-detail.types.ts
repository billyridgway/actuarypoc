export interface RunDetail {
  run: RunInfo;
  trust_status: TrustStatus;
  policy_input: PolicyInput;
  premium_comparison: PremiumComparison;
  warnings: string[];
  assumptions: Assumptions;
  audit_sources: AuditSources;
  projection_summary: ProjectionSummary;
}

export interface RunInfo {
  run_id: string;
  status: "succeeded" | "failed" | "pending" | string;
  created_at: string;
  engine_version: string;
  product_code: string;
  product_type: string;
  policy_id: string;
  environment: string;
  triggered_by: string;
}

export interface TrustStatus {
  status: "clean" | "warnings_found" | "missing_premium_table" | string;
  headline: string;
  reasons: string[];
}

export interface PolicyInput {
  identifiers: {
    policy_number: string;
    product_code: string;
    product_type: string;
  };
  core_fields: {
    issue_age: number;
    gender: string;
    smoker_class: string;
    risk_class: string;
    face_amount: number;
    level_period: number;
    premium_mode: string;
  };
  pas_premium: {
    modal_premium: number;
    currency: string;
  };
  raw_record?: Record<string, unknown> | null;
}

export interface PremiumComparison {
  table_premium?: TablePremium;
  pas_premium: {
    modal_premium: number;
    mode?: string;
    currency: string;
  };
  used_for_projection: "table_annual_premium" | "pas_premium" | string;
  mismatch?: PremiumMismatch;
}

export interface TablePremium {
  per_1000: number;
  basis: string;
  annual_premium: number;
  expected_modal_premium: number;
  modalization_rule: string;
  mode: string;
  currency: string;
  premium_table_is_synthetic?: boolean;
  premium_table_label?: string;
  source: {
    type: string;
    object: string;
    prefix: string;
    value_column: string;
    keys: string[];
  };
}

export interface PremiumMismatch {
  code: string;
  expected_modal: number;
  pas_modal: number;
  threshold: number;
  material: boolean;
  source: string;
}

export interface AuditSources {
  objects: {
    pas_object?: string;
    actuarial_object?: string;
    term23_actuarial_object?: string;
    rate_object?: string;
    crm_object?: string;
    premium_table_object?: string;
    projection_object?: string;
    audit_object?: string;
  };
  documents: {
    actuarial_memo?: string;
    risk_mapping?: string;
    premiums?: string;
  };
}

export interface Assumptions {
  assumption_set_id?: string | null;
  status?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
}

export interface ProjectionSummary {
  years: number[];
  cash_values: number[];
  death_benefits: number[];
  mortality_rates?: number[];
  survival_probabilities?: number[];
  net_level_premium?: number;
  links?: {
    projection_object?: string;
  };
}
