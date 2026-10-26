import React from "react";

// Phase 5 (the validation harness): test-case packs for the workspace's
// product. A pack is a set of named cases whose expectations — a field
// at a duration, the expected value, its source (filing page,
// illustration, admin-system export) and a tolerance — are checked
// against the projection ledger in one run. The diff view shows
// expected vs actual per case / duration / field with signed deltas;
// mismatches carry the engine's own explanation (including when the
// actual rests on a placeholder). Every run is stored: the report
// (JSON or plain text) is the audit artifact, and the run history is
// the regression record — re-running after a slot edit, a correction,
// or a rule-bank change shows what moved.

interface PackSummary {
  id: string;
  name: string;
  version: string;
  productCode?: string | null;
  description?: string | null;
  caseCount: number;
  createdBy?: string | null;
  createdAt?: string | null;
  lastRun?: {
    id: string;
    ranAt?: string | null;
    ranBy?: string | null;
    summary?: RunSummaryCounts | null;
  } | null;
}

interface RunSummaryCounts {
  status: string;
  cases: number;
  passedCases: number;
  failedCases: number;
  expectations: number;
  passed: number;
  failed: number;
  missing: number;
  basisCounts?: Record<string, number>;
}

interface RunResult {
  duration: number;
  field: string;
  fieldLabel: string;
  expected: number;
  actual?: number | null;
  delta?: number | null;
  tolerance: { absolute: number; relative: number; band: number };
  status: "pass" | "fail" | "missing";
  basis?: string | null;
  basisLabel?: string | null;
  source?: { description?: string; document?: string | null; page?: number | null };
  explanation?: string;
}

interface RunCase {
  caseId: string;
  name: string;
  status: string;
  inputs: Record<string, any>;
  mechanicsMode: string;
  mechanicsFingerprint: string;
  switchesUsed: string[];
  appliedEquations?: Array<{
    equationId: string;
    mechanic: string;
    version?: number;
    approvedBy?: string;
  }>;
  results: RunResult[];
}

interface RunChange {
  previousRunId?: string;
  previousRanAt?: string;
  newlyFailing: string[];
  newlyPassing: string[];
  mechanicsChangedCases: string[];
}

interface RunReport {
  id: string;
  packId: string;
  packName: string;
  packVersion: string;
  workspaceId: string;
  productCode?: string | null;
  ranBy: string;
  ranAt: string;
  engine: { ledgerVersion?: number | null; switchesUsed: string[]; appliedEquations?: Array<{ equationId: string; mechanic: string; version?: number; approvedBy?: string }> };
  summary: RunSummaryCounts;
  standInLines: Array<{ caseId: string; duration: number; field: string; basis: string }>;
  cases: RunCase[];
  changeVsPreviousRun?: RunChange | null;
}

interface RunHistoryEntry {
  id: string;
  ranAt?: string | null;
  ranBy?: string | null;
  summary?: RunSummaryCounts | null;
  changeVsPreviousRun?: RunChange | null;
}

const EXAMPLE_CASES = [
  {
    id: "base-case",
    name: "Base case from the carrier illustration",
    inputs: { issueAge: 45, faceAmount: 100000, premiumMode: "ANNUAL", modalPremium: 3600 },
    expectations: [
      {
        duration: 1,
        field: "accountValue",
        value: 0,
        source: { description: "Carrier illustration, year 1 account value", page: 12 },
        tolerance: { absolute: 1.0 },
      },
      {
        duration: 1,
        field: "surrenderValue",
        value: 0,
        source: { description: "Carrier illustration, year 1 surrender value", page: 12 },
        tolerance: { absolute: 1.0 },
      },
    ],
  },
];

function money(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function signedMoney(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const text = money(Math.abs(value));
  return value > 0 ? `+${text}` : value < 0 ? `-${text}` : text;
}

function basisClass(basis?: string | null): string {
  switch (basis) {
    case "filed":
      return "basis-tag basis-tag--filed";
    case "synthetic":
      return "basis-tag basis-tag--synthetic";
    case "corrected":
      return "basis-tag basis-tag--corrected";
    case "placeholder":
      return "basis-tag basis-tag--placeholder";
    default:
      return "basis-tag";
  }
}

export function ValidationPanel({ workspaceId }: { workspaceId: string }) {
  const [packs, setPacks] = React.useState<PackSummary[]>([]);
  const [report, setReport] = React.useState<RunReport | null>(null);
  const [history, setHistory] = React.useState<RunHistoryEntry[]>([]);
  const [historyPackId, setHistoryPackId] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [runningPackId, setRunningPackId] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [problems, setProblems] = React.useState<string[]>([]);
  const [message, setMessage] = React.useState<string | null>(null);
  const [newName, setNewName] = React.useState("");
  const [newVersion, setNewVersion] = React.useState("1.0");
  const [newCases, setNewCases] = React.useState("");

  const base = `/api/workspaces/${encodeURIComponent(workspaceId)}`;

  const loadPacks = React.useCallback(async () => {
    try {
      setLoading(true);
      const resp = await fetch(`${base}/validation-packs`);
      if (!resp.ok) throw new Error(`Failed to load validation packs (HTTP ${resp.status})`);
      const body = await resp.json();
      setPacks(body.packs || []);
    } catch (err: any) {
      setError(err?.message || "Failed to load validation packs.");
    } finally {
      setLoading(false);
    }
  }, [base]);

  React.useEffect(() => {
    void loadPacks();
  }, [loadPacks]);

  const loadHistory = React.useCallback(
    async (packId: string) => {
      const resp = await fetch(`${base}/validation-packs/${encodeURIComponent(packId)}/runs`);
      if (!resp.ok) throw new Error(`Failed to load run history (HTTP ${resp.status})`);
      const body = await resp.json();
      setHistory(body.runs || []);
      setHistoryPackId(packId);
    },
    [base],
  );

  const viewRun = React.useCallback(
    async (runId: string) => {
      setError(null);
      const resp = await fetch(`${base}/validation-runs/${encodeURIComponent(runId)}`);
      if (!resp.ok) throw new Error(`Failed to load run report (HTTP ${resp.status})`);
      const body = await resp.json();
      setReport(body.report);
    },
    [base],
  );

  const runPack = async (pack: PackSummary) => {
    setRunningPackId(pack.id);
    setError(null);
    setMessage(null);
    try {
      const resp = await fetch(`${base}/validation-packs/${encodeURIComponent(pack.id)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Run failed (HTTP ${resp.status})`);
      }
      const body = await resp.json();
      setReport(body.report);
      setMessage(
        `Ran ${pack.name}: ${body.report.summary.passedCases}/${body.report.summary.cases} cases passed.`,
      );
      await loadPacks();
      await loadHistory(pack.id);
    } catch (err: any) {
      setError(err?.message || "Run failed.");
    } finally {
      setRunningPackId(null);
    }
  };

  const createPack = async () => {
    setError(null);
    setProblems([]);
    setMessage(null);
    let cases: any;
    try {
      cases = JSON.parse(newCases);
    } catch (err: any) {
      setError(`The cases are not valid JSON: ${err?.message || err}`);
      return;
    }
    try {
      const resp = await fetch(`${base}/validation-packs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName, version: newVersion, cases }),
      });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const detail = (body as any)?.detail;
        if (detail && Array.isArray(detail.problems)) {
          setProblems(detail.problems);
          throw new Error("The pack was rejected — fix the problems listed below.");
        }
        throw new Error(
          (typeof detail === "string" && detail) || `Create failed (HTTP ${resp.status})`,
        );
      }
      setMessage(`Created pack ${body.pack.name} (version ${body.pack.version}).`);
      setNewName("");
      setNewCases("");
      await loadPacks();
    } catch (err: any) {
      setError(err?.message || "Create failed.");
    }
  };

  const deletePack = async (pack: PackSummary) => {
    setError(null);
    try {
      const resp = await fetch(`${base}/validation-packs/${encodeURIComponent(pack.id)}`, {
        method: "DELETE",
      });
      if (!resp.ok) throw new Error(`Delete failed (HTTP ${resp.status})`);
      if (report && report.packId === pack.id) setReport(null);
      await loadPacks();
    } catch (err: any) {
      setError(err?.message || "Delete failed.");
    }
  };

  return (
    <section className="card home-card" id="validation-panel">
      <h2>Validation packs</h2>
      <p className="muted">
        Test cases with expected results — from the filing, the carrier's illustration, or the
        admin system — checked against the projection in one run. Every expectation states its
        source and a tolerance; every actual carries its ledger basis, so a mismatch on a
        placeholder line explains itself. Runs are stored with the workspace as the audit
        record: re-run after a slot edit or a correction to see exactly what moved.
      </p>
      {loading && <p className="muted">Loading validation packs…</p>}
      {error && <p className="error">{error}</p>}
      {problems.length > 0 && (
        <ul className="error">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
      {message && <p className="muted">{message}</p>}

      {packs.map((pack) => (
        <div key={pack.id} className="slot-card">
          <h3>
            {pack.name}{" "}
            <span className="basis-tag">version {pack.version}</span>{" "}
            {pack.lastRun?.summary && (
              <span className={basisClass(pack.lastRun.summary.status === "pass" ? "filed" : "placeholder")}>
                last run {pack.lastRun.summary.status.toUpperCase()} —{" "}
                {pack.lastRun.summary.passed}/{pack.lastRun.summary.expectations} expectations
              </span>
            )}
          </h3>
          <p className="muted">
            {pack.caseCount} case{pack.caseCount === 1 ? "" : "s"}
            {pack.productCode ? ` · ${pack.productCode}` : ""}
            {pack.description ? ` · ${pack.description}` : ""}
            {pack.lastRun ? ` · last run ${pack.lastRun.ranAt} by ${pack.lastRun.ranBy}` : " · never run"}
          </p>
          <p>
            <button
              type="button"
              className="button"
              disabled={runningPackId === pack.id}
              onClick={() => void runPack(pack)}
            >
              {runningPackId === pack.id ? "Running…" : "Run pack"}
            </button>{" "}
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void loadHistory(pack.id)}
            >
              Run history
            </button>{" "}
            {pack.lastRun && (
              <button
                type="button"
                className="button button-secondary"
                onClick={() => void viewRun(pack.lastRun!.id)}
              >
                Latest report
              </button>
            )}{" "}
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void deletePack(pack)}
            >
              Delete pack
            </button>
          </p>
          {historyPackId === pack.id && history.length > 0 && (
            <table className="kv-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>When</th>
                  <th>By</th>
                  <th>Result</th>
                  <th>What moved</th>
                  <th>Report</th>
                </tr>
              </thead>
              <tbody>
                {history.map((run) => (
                  <tr key={run.id}>
                    <td>{run.id}</td>
                    <td>{run.ranAt}</td>
                    <td>{run.ranBy}</td>
                    <td>
                      {run.summary
                        ? `${run.summary.status.toUpperCase()} — ${run.summary.passed}/${run.summary.expectations}`
                        : "—"}
                    </td>
                    <td>
                      {run.changeVsPreviousRun
                        ? `${run.changeVsPreviousRun.newlyFailing.length} newly failing, ` +
                          `${run.changeVsPreviousRun.newlyPassing.length} newly passing` +
                          (run.changeVsPreviousRun.mechanicsChangedCases.length > 0
                            ? `, mechanics changed in ${run.changeVsPreviousRun.mechanicsChangedCases.join(", ")}`
                            : "")
                        : "first run"}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => void viewRun(run.id)}
                      >
                        View
                      </button>{" "}
                      <a href={`${base}/validation-runs/${encodeURIComponent(run.id)}/report.txt`} download>
                        Text
                      </a>{" "}
                      <a href={`${base}/validation-runs/${encodeURIComponent(run.id)}`} download>
                        JSON
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}

      <div className="slot-card">
        <h3>New pack</h3>
        <p className="muted">
          Name the pack and paste its cases as JSON. Each expectation needs a duration, a
          field (accountValue, surrenderValue, deathBenefit, coiCharge, surrenderCharge,
          policyFee, premiumLoad, premium, interestCredited, netAmountAtRisk, beginningValue,
          cumulativePremium), the expected value, its source, and optionally a tolerance.
        </p>
        <p>
          <label>
            Pack name{" "}
            <input value={newName} onChange={(e) => setNewName(e.target.value)} size={40} />
          </label>{" "}
          <label>
            Version{" "}
            <input value={newVersion} onChange={(e) => setNewVersion(e.target.value)} size={8} />
          </label>
        </p>
        <p>
          <textarea
            value={newCases}
            onChange={(e) => setNewCases(e.target.value)}
            rows={12}
            cols={100}
            placeholder="Cases JSON — use the template button, then fill in the expected values from your source"
          />
        </p>
        <p>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => setNewCases(JSON.stringify(EXAMPLE_CASES, null, 2))}
          >
            Insert example case template
          </button>{" "}
          <button type="button" className="button" onClick={() => void createPack()}>
            Create pack
          </button>
        </p>
      </div>

      {report && <ReportView report={report} base={base} />}
    </section>
  );
}

function ReportView({ report, base }: { report: RunReport; base: string }) {
  const summary = report.summary;
  return (
    <div className="slot-card" id="validation-report">
      <h3>
        {report.packName} — run {report.id}{" "}
        <span className={basisClass(summary.status === "pass" ? "filed" : "placeholder")}>
          {summary.status.toUpperCase()}
        </span>
      </h3>
      <p className="muted">
        Pack version {report.packVersion} · ran {report.ranAt} by {report.ranBy} ·{" "}
        {summary.passedCases}/{summary.cases} cases passed · {summary.passed}/
        {summary.expectations} expectations within tolerance ({summary.failed} failed,{" "}
        {summary.missing} missing)
        {summary.basisCounts && (
          <>
            {" "}· basis of actuals:{" "}
            {Object.entries(summary.basisCounts)
              .map(([basis, count]) => `${basis} ${count}`)
              .join(", ")}
          </>
        )}
      </p>
      <p className="muted">
        {report.engine.appliedEquations && report.engine.appliedEquations.length > 0 ? (
          <>
            Approved equations applied:{" "}
            {report.engine.appliedEquations
              .map((e) => `${e.mechanic} (v${e.version ?? "?"}, approved by ${e.approvedBy ?? "—"})`)
              .join(", ")}
            .{" "}
          </>
        ) : (
          <>
            Rule-bank switches used: {report.engine.switchesUsed.join(", ") || "none recorded"}.{" "}
          </>
        )}
        <a href={`${base}/validation-runs/${encodeURIComponent(report.id)}/report.txt`} download>
          Download text report
        </a>{" "}
        ·{" "}
        <a href={`${base}/validation-runs/${encodeURIComponent(report.id)}`} download>
          Download JSON report
        </a>
      </p>
      {report.changeVsPreviousRun && (
        <p className="muted">
          Versus the previous run ({report.changeVsPreviousRun.previousRanAt}):{" "}
          {report.changeVsPreviousRun.newlyFailing.length} newly failing,{" "}
          {report.changeVsPreviousRun.newlyPassing.length} newly passing
          {report.changeVsPreviousRun.mechanicsChangedCases.length > 0 &&
            `; mechanics changed in ${report.changeVsPreviousRun.mechanicsChangedCases.join(", ")}`}
          .
        </p>
      )}
      {report.standInLines.length > 0 && (
        <p className="muted">
          Lines resting on stand-ins (placeholder or synthetic basis — not filed values):{" "}
          {report.standInLines
            .map((line) => `${line.caseId} year ${line.duration} ${line.field} (${line.basis})`)
            .join("; ")}
        </p>
      )}
      {report.cases.map((runCase) => {
        const mismatches = runCase.results.filter((r) => r.status !== "pass");
        return (
          <div key={runCase.caseId}>
            <h4>
              {runCase.name} — {runCase.status.toUpperCase()}{" "}
              <span className="basis-tag">
                mechanics: {runCase.mechanicsMode} · fingerprint{" "}
                {runCase.mechanicsFingerprint.slice(0, 12)}…
              </span>
            </h4>
            <div className="slot-table-wrap">
              <table className="kv-table slot-table">
                <thead>
                  <tr>
                    <th>Year</th>
                    <th>Field</th>
                    <th>Expected</th>
                    <th>Actual</th>
                    <th>Delta</th>
                    <th>Result</th>
                    <th>Basis</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {runCase.results.map((result) => (
                    <tr
                      key={`${result.duration}-${result.field}`}
                      className={
                        result.status === "fail"
                          ? "validation-row validation-row--fail"
                          : result.status === "missing"
                            ? "validation-row validation-row--missing"
                            : "validation-row"
                      }
                    >
                      <td>{result.duration}</td>
                      <td>{result.fieldLabel}</td>
                      <td>{money(result.expected)}</td>
                      <td>{money(result.actual)}</td>
                      <td>{signedMoney(result.delta)}</td>
                      <td>{result.status.toUpperCase()}</td>
                      <td>
                        <span className={basisClass(result.basis)}>
                          {result.basisLabel || result.basis || "—"}
                        </span>
                      </td>
                      <td>
                        {result.source?.document ? `${result.source.document}: ` : ""}
                        {result.source?.description || ""}
                        {result.source?.page ? ` (p.${result.source.page})` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {mismatches.length > 0 && (
              <>
                <p>
                  <strong>Mismatches:</strong>
                </p>
                <ul>
                  {mismatches.map((result) => (
                    <li key={`${result.duration}-${result.field}`}>
                      Year {result.duration} {result.fieldLabel}: {result.explanation}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
