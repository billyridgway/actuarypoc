import React from "react";
import type { RunDetail } from "./run-detail.types";

interface RunDetailPageProps {
  runDetail: RunDetail;
}

export const RunDetailPage: React.FC<RunDetailPageProps> = ({ runDetail }) => {
  const {
    run,
    trust_status,
    policy_input,
    premium_comparison,
    warnings,
    assumptions,
    projection_summary,
    audit_sources,
  } = runDetail;

  return (
    <div className="run-detail-page">
      <TrustStatusBanner trustStatus={trust_status} />

      <section className="card">
        <h2>Assumptions</h2>
        <AssumptionsSection assumptions={assumptions} />
      </section>

      <section className="card">
        <h2>Policy Input</h2>
        <PolicyInputSection policyInput={policy_input} />
      </section>

      <section className="card">
        <h2>Premium Comparison</h2>
        <PremiumComparisonSection premiumComparison={premium_comparison} />
      </section>

      <section className="card">
        <h2>Warnings</h2>
        <WarningsSection warnings={warnings} />
      </section>

      <section className="card">
        <h2>Projection Summary</h2>
        <ProjectionSummarySection summary={projection_summary} />
      </section>

      <section className="card">
        <h2>Projection Graphs</h2>
        <ProjectionGraphs summary={projection_summary} />
      </section>

      <section className="card">
        <h2>Audit &amp; Sources</h2>
        <AuditSourcesSection auditSources={audit_sources} run={run} />
      </section>
    </div>
  );
};

const AssumptionsSection: React.FC<{ assumptions: RunDetail["assumptions"] }> = ({ assumptions }) => {
  const { assumption_set_id, status, approved_by, approved_at } = assumptions || {};

  if (!assumption_set_id && !status && !approved_by && !approved_at) {
    return <div className="assumptions-empty">No assumption set linked to this run.</div>;
  }

  return (
    <table className="kv-table">
      <tbody>
        <tr>
          <th>Assumption set ID</th>
          <td>{assumption_set_id || <span className="muted">(none)</span>}</td>
        </tr>
        <tr>
          <th>Status</th>
          <td>{status || <span className="muted">(unknown)</span>}</td>
        </tr>
        <tr>
          <th>Approved by</th>
          <td>{approved_by || <span className="muted">(unknown)</span>}</td>
        </tr>
        <tr>
          <th>Approved at</th>
          <td>{approved_at || <span className="muted">(unknown)</span>}</td>
        </tr>
      </tbody>
    </table>
  );
};

const TrustStatusBanner: React.FC<{ trustStatus: RunDetail["trust_status"] }> = ({ trustStatus }) => {
  const { status, headline, reasons } = trustStatus;

  let className = "trust-banner";
  if (status === "clean") className += " trust-banner--clean";
  else if (status === "warnings_found") className += " trust-banner--warning";
  else if (status === "missing_premium_table") className += " trust-banner--missing";

  return (
    <div className={className}>
      <div className="trust-banner__headline">{headline}</div>
      {reasons && reasons.length > 0 && (
        <div className="trust-banner__reasons">Reasons: {reasons.join(", ")}</div>
      )}
    </div>
  );
};

const PolicyInputSection: React.FC<{ policyInput: RunDetail["policy_input"] }> = ({ policyInput }) => {
  const { identifiers, core_fields, pas_premium, raw_record } = policyInput;

  return (
    <div className="policy-input">
      <div className="policy-input__row">
        <div>
          <div>
            <strong>Policy number</strong>: {identifiers.policy_number}
          </div>
          <div>
            <strong>Product</strong>: {identifiers.product_code} ({identifiers.product_type})
          </div>
        </div>
        <div>
          <div>
            <strong>Issue age</strong>: {core_fields.issue_age}
          </div>
          <div>
            <strong>Gender</strong>: {core_fields.gender}
          </div>
          <div>
            <strong>Smoker class</strong>: {core_fields.smoker_class}
          </div>
          <div>
            <strong>Risk class</strong>: {core_fields.risk_class}
          </div>
          <div>
            <strong>Face amount</strong>: {core_fields.face_amount}
          </div>
          <div>
            <strong>Level period</strong>: {core_fields.level_period}
          </div>
          <div>
            <strong>Premium mode</strong>: {core_fields.premium_mode}
          </div>
        </div>
      </div>

      <div className="policy-input__row">
        <strong>PAS modal premium</strong>: {pas_premium.modal_premium.toFixed(2)} {pas_premium.currency} (
        {core_fields.premium_mode})
      </div>

      {raw_record && (
        <details className="policy-input__raw-record">
          <summary>Show raw PAS record</summary>
          <pre>{JSON.stringify(raw_record, null, 2)}</pre>
        </details>
      )}
    </div>
  );
};

const PremiumComparisonSection: React.FC<{
  premiumComparison: RunDetail["premium_comparison"];
}> = ({ premiumComparison }) => {
  const { table_premium, pas_premium, used_for_projection, mismatch } = premiumComparison;

  return (
    <div className="premium-comparison">
      <table className="kv-table">
        <tbody>
          {table_premium && (
            <>
              <tr>
                <th>Table per $1,000</th>
                <td>{table_premium.per_1000}</td>
              </tr>
              <tr>
                <th>Table basis</th>
                <td>{table_premium.basis}</td>
              </tr>
              <tr>
                <th>Table annual premium</th>
                <td>
                  {table_premium.annual_premium.toFixed(2)} {table_premium.currency}
                </td>
              </tr>
              <tr>
                <th>Expected modal premium</th>
                <td>
                  {table_premium.expected_modal_premium.toFixed(6)} {table_premium.currency}
                </td>
              </tr>
              <tr>
                <th>Modalization rule</th>
                <td>
                  {table_premium.modalization_rule} ({table_premium.mode})
                </td>
              </tr>
              <tr>
                <th>Premium table</th>
                <td>
                  {table_premium.source.object}
                  {table_premium.premium_table_is_synthetic && table_premium.premium_table_label && (
                    <div className="label label--warning">{table_premium.premium_table_label}</div>
                  )}
                </td>
              </tr>
            </>
          )}
          <tr>
            <th>PAS modal premium</th>
            <td>
              {pas_premium.modal_premium.toFixed(2)} {pas_premium.currency} {" "}
              {pas_premium.mode && `(${pas_premium.mode})`}
            </td>
          </tr>
          <tr>
            <th>Used for projection</th>
            <td>{used_for_projection}</td>
          </tr>
        </tbody>
      </table>

      {mismatch?.material && (
        <div className="premium-comparison__mismatch">
          Premium mismatch: expected {mismatch.expected_modal.toFixed(6)}, PAS {mismatch.pas_modal.toFixed(2)}
          {" "}
          (threshold {mismatch.threshold.toFixed(6)}, source {mismatch.source})
        </div>
      )}
    </div>
  );
};

const WarningsSection: React.FC<{ warnings: string[] }> = ({ warnings }) => {
  if (!warnings || warnings.length === 0) {
    return <div>No warnings.</div>;
  }
  return (
    <ul className="warnings-list">
      {warnings.map((w, idx) => (
        <li key={idx}>{w}</li>
      ))}
    </ul>
  );
};

const ProjectionSummarySection: React.FC<{ summary: RunDetail["projection_summary"] }> = ({ summary }) => {
  const { years, cash_values, death_benefits, mortality_rates, survival_probabilities, net_level_premium } =
    summary;

  const pickIndex = (year: number) => years.indexOf(year);
  const importantYears = [1, 5, 10];

  const rows = importantYears
    .map((y) => {
      const idx = pickIndex(y);
      return idx >= 0 ? { label: `Year ${y}`, idx } : null;
    })
    .filter((r): r is { label: string; idx: number } => r !== null);

  return (
    <div className="projection-summary">
      <table className="kv-table">
        <thead>
          <tr>
            <th>Year</th>
            <th>Cash value</th>
            <th>Death benefit</th>
            {mortality_rates && <th>qₓ</th>}
            {survival_probabilities && <th>Survival prob</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, idx }) => (
            <tr key={label}>
              <td>{label}</td>
              <td>{cash_values[idx]?.toFixed(2)}</td>
              <td>{death_benefits[idx]?.toFixed(2)}</td>
              {mortality_rates && <td>{mortality_rates[idx]?.toFixed(6)}</td>}
              {survival_probabilities && <td>{survival_probabilities[idx]?.toFixed(6)}</td>}
            </tr>
          ))}
        </tbody>
      </table>

      {typeof net_level_premium === "number" && (
        <div className="projection-summary__nlp">
          Net level premium (per policy issued): {net_level_premium.toFixed(2)}
        </div>
      )}
    </div>
  );
};

const ProjectionGraphs: React.FC<{ summary: RunDetail["projection_summary"] }> = ({ summary }) => {
  const { years, cash_values, death_benefits } = summary;

  if (!years || years.length === 0 || cash_values.length === 0 || death_benefits.length === 0) {
    return <div className="projection-graphs__empty">No projection rows available for charting.</div>;
  }

  const width = 640;
  const height = 260;
  const padding = 40;

  const maxYear = years[years.length - 1];
  const minYear = years[0];

  const allValues = [...cash_values, ...death_benefits].filter((v) => typeof v === "number" && !Number.isNaN(v));
  const maxValue = allValues.length > 0 ? Math.max(...allValues) : 0;

  if (!maxValue) {
    return <div className="projection-graphs__empty">Projection values are all zero.</div>;
  }

  const xScale = (year: number) =>
    padding + ((year - minYear) / (maxYear - minYear || 1)) * (width - padding * 2);

  const yScale = (value: number) =>
    height - padding - (value / maxValue) * (height - padding * 2);

  const toPoints = (values: number[]) =>
    years
      .map((year, idx) => {
        const v = values[idx];
        if (typeof v !== "number" || Number.isNaN(v)) return null;
        return `${xScale(year)},${yScale(v)}`;
      })
      .filter(Boolean)
      .join(" ");

  const cashPath = toPoints(cash_values);
  const deathPath = toPoints(death_benefits);

  return (
    <div className="projection-graphs">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="projection-graphs__svg"
        aria-label="Projection graph"
      >
        {/* Axes */}
        <line
          x1={padding}
          y1={height - padding}
          x2={width - padding}
          y2={height - padding}
          stroke="#e5e7eb"
          strokeWidth={1}
        />
        <line
          x1={padding}
          y1={padding}
          x2={padding}
          y2={height - padding}
          stroke="#e5e7eb"
          strokeWidth={1}
        />

        {/* Cash value line */}
        {cashPath && (
          <polyline
            points={cashPath}
            fill="none"
            stroke="#2563eb"
            strokeWidth={2}
          />
        )}

        {/* Death benefit line */}
        {deathPath && (
          <polyline
            points={deathPath}
            fill="none"
            stroke="#10b981"
            strokeWidth={2}
          />
        )}

        {/* Simple labels */}
        <text x={padding} y={padding - 10} fontSize={10} fill="#6b7280">
          Values
        </text>
        <text
          x={width - padding}
          y={height - padding + 14}
          fontSize={10}
          fill="#6b7280"
          textAnchor="end"
        >
          Policy year
        </text>
      </svg>

      <div className="projection-graphs__legend">
        <span className="legend-item">
          <span className="legend-swatch legend-swatch--cash" /> Cash value
        </span>
        <span className="legend-item">
          <span className="legend-swatch legend-swatch--death" /> Death benefit
        </span>
      </div>
    </div>
  );
};

const AuditSourcesSection: React.FC<{
  auditSources: RunDetail["audit_sources"];
  run: RunDetail["run"];
}> = ({ auditSources }) => {
  const { objects, documents } = auditSources;

  return (
    <div className="audit-sources">
      <h3>Run Inputs</h3>
      <table className="kv-table">
        <tbody>
          {objects.pas_object && (
            <tr>
              <th>PAS object</th>
              <td>{objects.pas_object}</td>
            </tr>
          )}
          {objects.actuarial_object && (
            <tr>
              <th>Actuarial tables</th>
              <td>{objects.actuarial_object}</td>
            </tr>
          )}
          {objects.term23_actuarial_object && (
            <tr>
              <th>Term23 actuarial</th>
              <td>{objects.term23_actuarial_object}</td>
            </tr>
          )}
          {objects.rate_object && (
            <tr>
              <th>Rate curves</th>
              <td>{objects.rate_object}</td>
            </tr>
          )}
          {objects.crm_object && (
            <tr>
              <th>CRM accounts</th>
              <td>{objects.crm_object}</td>
            </tr>
          )}
          {objects.premium_table_object && (
            <tr>
              <th>Premium table</th>
              <td>{objects.premium_table_object}</td>
            </tr>
          )}
          {objects.projection_object && (
            <tr>
              <th>Projection object</th>
              <td>{objects.projection_object}</td>
            </tr>
          )}
          {objects.audit_object && (
            <tr>
              <th>Audit object</th>
              <td>{objects.audit_object}</td>
            </tr>
          )}
        </tbody>
      </table>

      <h3>Source Documents</h3>
      <table className="kv-table">
        <tbody>
          {documents.actuarial_memo && (
            <tr>
              <th>Actuarial memo</th>
              <td>{documents.actuarial_memo}</td>
            </tr>
          )}
          {documents.risk_mapping && (
            <tr>
              <th>Risk mapping</th>
              <td>{documents.risk_mapping}</td>
            </tr>
          )}
          {documents.premiums && (
            <tr>
              <th>Premiums / rate grids</th>
              <td>{documents.premiums}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};
