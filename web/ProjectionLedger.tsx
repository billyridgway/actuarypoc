import React from "react";

// Local copy of the workspace currency formatter so this module does not
// import from ProductWorkspacePage (which imports this component).
const formatCurrency = (value: any): string => {
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

// Phase 1 (show the math): the projection's primary view is the auditable
// roll-forward ledger. Every row expands to the derivation of each
// component — plain-language formula plus the actual values the engine
// used — and the full rate tables in force are displayed alongside.
// Data comes from `illustration.ledger` / `illustration.rateTables` in
// the snapshot; older snapshots without a ledger fall back to the raw
// projection rows (amounts only, no derivations).

interface ProjectionLedgerProps {
  ledger?: any;
  rateTables?: any;
  fallbackRows?: any[];
}

const formatRate = (value: any): string => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value ?? "—");
  return `${(numeric * 100).toFixed(2)}%`;
};

const formatDerivationValue = (input: any): string => {
  if (input?.value === null || input?.value === undefined) return "—";
  if (input.unit === "USD") return formatCurrency(input.value);
  if (input.unit === "rate" || input.unit === "percent_nar_annual") return formatRate(input.value);
  if (typeof input.unit === "string" && input.unit.startsWith("per_1000")) {
    return `${input.value} per $1,000`;
  }
  return String(input.value);
};

const basisClass = (basis?: string): string => {
  switch (basis) {
    case "filed":
      return "basis-tag basis-tag--filed";
    case "synthetic":
      return "basis-tag basis-tag--synthetic";
    case "placeholder":
      return "basis-tag basis-tag--placeholder";
    case "corrected":
      return "basis-tag basis-tag--corrected";
    default:
      return "basis-tag";
  }
};

const DerivationList: React.FC<{ components: any[] }> = ({ components }) => (
  <div className="ledger-derivations">
    {components.map((component) => (
      <article key={component.id} className="ledger-derivation">
        <header>
          <strong>{component.label}</strong>
          <span className="ledger-derivation__amount">
            {typeof component.amount === "number" ? formatCurrency(component.amount) : ""}
          </span>
          {component.basisLabel && <span className={basisClass(component.basis)}>{component.basisLabel}</span>}
        </header>
        <p>{component.formula}</p>
        {Array.isArray(component.inputs) && component.inputs.length > 0 && (
          <dl>
            {component.inputs.map((input: any, index: number) => (
              <div key={`${component.id}-input-${index}`}>
                <dt>{input.label}</dt>
                <dd>{formatDerivationValue(input)}</dd>
              </div>
            ))}
          </dl>
        )}
        {component.source?.filename && (
          <p className="muted ledger-derivation__source">
            Source: {component.source.filename}
            {component.source.page ? ` · page ${component.source.page}` : ""}
            {component.source.tableHeading ? ` · ${component.source.tableHeading}` : ""}
          </p>
        )}
      </article>
    ))}
  </div>
);

const RateTablesInForce: React.FC<{ rateTables?: any }> = ({ rateTables }) => {
  if (!rateTables) return null;
  const coi = rateTables.coi;
  const surrender = rateTables.surrender;
  const formatSurrenderCharge = (row: any): string => {
    if (row.charge_unit === "percent_account_value" || row.charge_unit === "percent_face") {
      return formatRate(row.charge);
    }
    if (row.charge_unit === "per_1000_face") return `${row.charge} per $1,000`;
    return formatCurrency(row.charge);
  };
  return (
    <div className="rate-tables">
      <h3>Rates in force</h3>
      <p className="muted">
        The full tables this projection charges from. If a table is missing, the placeholder
        being used instead is stated plainly.
      </p>
      {coi && (
        <section className="rate-table">
          <h4>
            Cost of insurance (COI){" "}
            <span className={basisClass(coi.status)}>
              {coi.status === "placeholder" ? "Placeholder" : `${coi.rowCount} rows`}
            </span>
          </h4>
          {coi.placeholder ? (
            <p className="rate-table__placeholder">{coi.placeholder.description}</p>
          ) : (
            <div className="table-scroll rate-table__scroll">
              <table className="kv-table">
                <thead>
                  <tr>
                    <th>Duration</th>
                    <th>Attained age</th>
                    <th>Sex</th>
                    <th>Risk class</th>
                    <th>Tobacco</th>
                    <th>Rate</th>
                    <th>Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {coi.rows.map((row: any, index: number) => (
                    <tr key={`coi-${index}`}>
                      <td>{row.duration ?? "—"}</td>
                      <td>{row.attained_age ?? "—"}</td>
                      <td>{row.sex ?? "—"}</td>
                      <td>{row.risk_class ?? "—"}</td>
                      <td>{row.tobacco_status ?? "—"}</td>
                      <td>{row.rate}</td>
                      <td>{row.rate_unit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {Array.isArray(coi.sources) && coi.sources.length > 0 && (
            <p className="muted">
              Source: {coi.sources.map((source: any) => `${source.filename ?? "table"}${source.page ? ` · page ${source.page}` : ""}`).join("; ")}
            </p>
          )}
        </section>
      )}
      {surrender && (
        <section className="rate-table">
          <h4>
            Surrender charge schedule{" "}
            <span className={basisClass(surrender.status)}>
              {surrender.status === "placeholder" ? "Placeholder" : `${surrender.rowCount} rows`}
            </span>
          </h4>
          {surrender.placeholder ? (
            <p className="rate-table__placeholder">{surrender.placeholder.description}</p>
          ) : (
            <div className="table-scroll rate-table__scroll">
              <table className="kv-table">
                <thead>
                  <tr>
                    <th>Duration</th>
                    <th>Charge</th>
                    <th>Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {surrender.rows.map((row: any, index: number) => (
                    <tr key={`surrender-${index}`}>
                      <td>{row.duration ?? "—"}</td>
                      <td>{formatSurrenderCharge(row)}</td>
                      <td>{row.charge_unit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
};

export const ProjectionLedger: React.FC<ProjectionLedgerProps> = ({ ledger, rateTables, fallbackRows }) => {
  const [expandedYear, setExpandedYear] = React.useState<number | null>(null);
  const ledgerRows: any[] = Array.isArray(ledger?.rows) ? ledger.rows : [];
  const hasLedger = ledgerRows.length > 0;
  const rows: any[] = hasLedger
    ? ledgerRows
    : (fallbackRows ?? []).map((row) => ({
        year: row.year,
        attainedAge: row.attainedAge,
        beginningValue: row.openingPolicyValue,
        premium: row.annualPremium,
        premiumLoad: row.premiumLoad,
        policyFee: row.policyFee,
        coiCharge: row.coiCharge,
        interestCredited: row.guaranteedInterest,
        endingValue: row.endingPolicyValue ?? row.policyValue,
        surrenderCharge: row.surrenderCharge,
        surrenderValue: row.surrenderValue,
        deathBenefit: row.deathBenefit,
        netAmountAtRisk: row.netAmountAtRisk,
        components: null,
      }));
  if (rows.length === 0) return null;

  return (
    <div className="projection-ledger-view">
      <div className="table-scroll projection-ledger">
        <table className="kv-table">
          <thead>
            <tr>
              <th aria-label="Expand row" />
              <th>Year</th>
              <th>Age</th>
              <th>Beginning value</th>
              <th>Premium</th>
              <th>Premium load</th>
              <th>Policy fee</th>
              <th>COI</th>
              <th>Interest</th>
              <th>Ending value</th>
              <th>Surrender charge</th>
              <th>Surrender value</th>
              <th>Death benefit</th>
              <th>Net amount at risk</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const expanded = expandedYear === row.year;
              return (
                <React.Fragment key={row.year ?? index}>
                  <tr className={expanded ? "is-expanded" : ""}>
                    <td>
                      {row.components ? (
                        <button
                          type="button"
                          className="ledger-expand"
                          aria-expanded={expanded}
                          aria-label={`${expanded ? "Hide" : "Show"} how year ${row.year} was calculated`}
                          onClick={() => setExpandedYear(expanded ? null : row.year)}
                        >
                          {expanded ? "▾" : "▸"}
                        </button>
                      ) : null}
                    </td>
                    <td>{row.year}</td>
                    <td>{row.attainedAge ?? ""}</td>
                    <td>{formatCurrency(row.beginningValue)}</td>
                    <td>{formatCurrency(row.premium)}</td>
                    <td>{formatCurrency(row.premiumLoad)}</td>
                    <td>{formatCurrency(row.policyFee)}</td>
                    <td>{formatCurrency(row.coiCharge)}</td>
                    <td>{formatCurrency(row.interestCredited)}</td>
                    <td>{formatCurrency(row.endingValue)}</td>
                    <td>{formatCurrency(row.surrenderCharge)}</td>
                    <td>{formatCurrency(row.surrenderValue)}</td>
                    <td>{formatCurrency(row.deathBenefit)}</td>
                    <td>{formatCurrency(row.netAmountAtRisk)}</td>
                  </tr>
                  {expanded && row.components && (
                    <tr className="ledger-detail-row">
                      <td colSpan={14}>
                        <p className="ledger-detail-row__title">
                          How year {row.year} was calculated — every component, with the values used:
                        </p>
                        <DerivationList components={row.components} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {!hasLedger && (
        <p className="muted">
          This snapshot predates the auditable ledger, so per-component derivations are not
          available. Re-run the projection to generate them.
        </p>
      )}
      <RateTablesInForce rateTables={rateTables} />
    </div>
  );
};

export default ProjectionLedger;
