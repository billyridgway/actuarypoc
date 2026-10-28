import React from "react";

import { EquationDisplay } from "./EquationMath";

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
  /** The run record's stamp of the chosen option per product-structure
   *  step (Oct 28, 2026): the definitions this run used, named. */
  definitionsLine?: string | null;
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

// Scenario flagging (Oct 27, 2026): in "Rates in force", the rows
// that match the run's classification are highlighted, with a count
// line per selector-bearing table. Matching is by SELECTOR ONLY —
// never by value (in this filing both specimen slices carry identical
// rates, so value-matching would flag everything and lie). The
// semantics mirror the evaluator's own (server `_selector_match_issues`
// / `select_rows`): a row-side null / "ANY" / "All" selector is a
// wildcard; otherwise the scenario's value must equal it
// (case-insensitive). Tables whose rows carry no class selectors
// (surrender, corridor — duration-keyed only) get no flagging at all.
const CLASS_SELECTOR_FIELDS: Array<{ row: string; scenario: string }> = [
  { row: "sex", scenario: "sex" },
  { row: "risk_class", scenario: "riskClass" },
  { row: "tobacco_status", scenario: "tobaccoStatus" },
];

const isWildcardSelector = (value: any): boolean =>
  value === null || value === undefined || value === "" || value === "ANY" || value === "All";

const rowMatchesScenario = (row: any, classification: any): boolean =>
  CLASS_SELECTOR_FIELDS.every(({ row: rowField, scenario: scenarioField }) => {
    const expected = row?.[rowField];
    if (isWildcardSelector(expected)) return true;
    const actual = classification?.[scenarioField];
    if (actual === null || actual === undefined || actual === "") return false;
    return String(expected).trim().toLowerCase() === String(actual).trim().toLowerCase();
  });

const tableHasClassSelectors = (rows: any[]): boolean =>
  (rows ?? []).some((row) =>
    CLASS_SELECTOR_FIELDS.some(({ row: rowField }) => !isWildcardSelector(row?.[rowField])),
  );

const classificationLabel = (classification: any): string =>
  CLASS_SELECTOR_FIELDS.map(({ scenario }) => classification?.[scenario])
    .filter((value) => value !== null && value !== undefined && value !== "")
    .join(" · ");

const RateTablesInForce: React.FC<{ rateTables?: any; classification?: any }> = ({
  rateTables,
  classification,
}) => {
  if (!rateTables) return null;
  const coi = rateTables.coi;
  const surrender = rateTables.surrender;
  // Flagging applies only where the table's rows carry class
  // selectors and the run actually classified its scenario.
  const coiFlagged =
    coi && !coi.missingTable && classification && tableHasClassSelectors(coi.rows ?? [])
      ? (coi.rows ?? []).map((row: any) => rowMatchesScenario(row, classification))
      : null;
  const coiMatchCount = coiFlagged ? coiFlagged.filter(Boolean).length : 0;
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
        The full tables this projection charges from, beside the approved equation that
        applies each one. If a table is missing, the absence is stated plainly — nothing
        is substituted for it.
      </p>
      {coi && (
        <section className="rate-table">
          <h4>
            Cost of insurance (COI){" "}
            <span className={basisClass(coi.status)}>
              {coi.status === "missing" ? "Missing" : `${coi.rowCount} rows`}
            </span>
          </h4>
          {coi.missingTable ? (
            <p className="rate-table__placeholder">{coi.missingTable.description}</p>
          ) : (
            <>
              {coiFlagged && (
                <p className="muted rate-table__match-count">
                  {coiMatchCount} of {coi.rows.length} rows match this scenario
                  {classificationLabel(classification)
                    ? ` (${classificationLabel(classification)})`
                    : ""}{" "}
                  — those rows are highlighted.
                </p>
              )}
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
                    <tr
                      key={`coi-${index}`}
                      className={coiFlagged?.[index] ? "rate-row--scenario" : undefined}
                    >
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
            </>
          )}
          {coi.equation ? (
            <>
              <p className="muted"><strong>Equation in force:</strong></p>
              <EquationDisplay
                math={coi.equation.math}
                rendering={coi.equation.rendering}
                timingNote={coi.equation.timingNote}
                approvalBy={coi.equation.approvedBy ?? null}
              />
            </>
          ) : null}
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
              {surrender.status === "missing" ? "Missing" : `${surrender.rowCount} rows`}
            </span>
          </h4>
          {surrender.missingTable ? (
            <p className="rate-table__placeholder">{surrender.missingTable.description}</p>
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
          {surrender.equation ? (
            <>
              <p className="muted"><strong>Equation in force:</strong></p>
              <EquationDisplay
                math={surrender.equation.math}
                rendering={surrender.equation.rendering}
                timingNote={surrender.equation.timingNote}
                approvalBy={surrender.equation.approvedBy ?? null}
              />
            </>
          ) : null}
        </section>
      )}
    </div>
  );
};

export const ProjectionLedger: React.FC<ProjectionLedgerProps> = ({ ledger, rateTables, fallbackRows, definitionsLine }) => {
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
  // The run's own classification, carried on its projection rows,
  // drives the Rates-in-force scenario flagging. A run whose scenario
  // specified no classification (e.g. the analysis-time illustration)
  // has nothing to flag against.
  const rawClassification = (fallbackRows ?? []).find(
    (row: any) => row?.appliedClassification,
  )?.appliedClassification;
  const classification =
    rawClassification &&
    [rawClassification.sex, rawClassification.riskClass, rawClassification.tobaccoStatus].some(
      (value) => value !== null && value !== undefined && value !== "",
    )
      ? rawClassification
      : null;
  if (rows.length === 0) return null;

  return (
    <div className="projection-ledger-view">
      {definitionsLine ? (
        <p className="muted projection-definitions">{definitionsLine}</p>
      ) : null}
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
      <RateTablesInForce rateTables={rateTables} classification={classification} />
    </div>
  );
};

export default ProjectionLedger;
