import React from "react";
import { MechanicsPanel } from "./MechanicsPanel";
import { ValidationPanel } from "./ValidationPanel";
import { EquationsPanel } from "./EquationsPanel";
import { ActivityPanel } from "./ActivityPanel";
import {
  useProjectionWorkspace,
  ProjectionResultsSection,
  ProjectionGraphSection,
} from "./ProjectionLogicPage";

// The actuary workbench: one bench per product, organized as tabs —
// not one forever-long page. The header (identity, trust state,
// scenario + Run) stays global above the tabs; each tab is a full
// working surface with one job. Tabs stay MOUNTED when inactive
// (hidden with CSS, never unmounted), so switching loses nothing: no
// refetch, no lost scroll, no lost in-progress edits. The ledger is
// the home tab; the calculation graph survives only as a collapsed
// debugging detail inside it — it is not the interface actuaries
// work in.

const trustLevelLabel = (value?: string | null): string => {
  switch ((value || "").toLowerCase()) {
    case "exploration_only":
      return "Exploration only — placeholder values still in use";
    case "draft_illustration":
      return "Draft illustration";
    case "review_ready":
      return "Review ready";
    case "filed_rate_ready":
      return "Filed-rate ready";
    default:
      return "Not yet classified";
  }
};

const humanize = (value?: string | null): string =>
  (value || "")
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

export type BenchTab = "ledger" | "inputs" | "validation" | "filing" | "activity";

const BENCH_TABS: Array<{ id: BenchTab; label: string }> = [
  { id: "ledger", label: "Ledger" },
  { id: "inputs", label: "Inputs & Equations" },
  { id: "validation", label: "Validation" },
  { id: "filing", label: "Filing" },
  { id: "activity", label: "Activity" },
];

interface WorkbenchPageProps {
  snapshot: any;
  workspaceId: string;
  /** Deep links to the old graph page (view=map / view=logic) land on
   *  the Ledger tab with the calculation-map detail already expanded. */
  expandMap?: boolean;
  /** Deep link view=details lands on the Filing tab. */
  initialTab?: BenchTab;
}

export const WorkbenchPage: React.FC<WorkbenchPageProps> = ({
  snapshot,
  workspaceId,
  expandMap,
  initialTab,
}) => {
  const [data, setData] = React.useState<any>(snapshot ?? null);
  const [meta, setMeta] = React.useState<any>(null);
  const [documents, setDocuments] = React.useState<any[]>([]);
  const [sources, setSources] = React.useState<any[]>([]);
  const [activeTab, setActiveTab] = React.useState<BenchTab>(initialTab ?? "ledger");
  // Unification revamp: one invalidation signal for every panel on
  // the bench. Any mutation — from the mechanics panel, the
  // equations panel, or a snapshot reload — bumps the epoch, and
  // both panels refetch the same artifact store. No section can
  // hold a stale generation of the approval truth again.
  const [inputsEpoch, setInputsEpoch] = React.useState(0);
  const bumpInputsEpoch = React.useCallback(() => setInputsEpoch((n) => n + 1), []);

  const reload = React.useCallback(async () => {
    try {
      const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
      if (!resp.ok) return;
      const body = await resp.json();
      if (body?.snapshot) setData(body.snapshot);
      setMeta(body?.workspace ?? null);
      setDocuments(Array.isArray(body?.documents) ? body.documents : []);
      setSources(Array.isArray(body?.sources) ? body.sources : []);
      bumpInputsEpoch();
    } catch {
      /* keep the current bench state if a refresh fails */
    }
  }, [workspaceId, bumpInputsEpoch]);

  // A saved projection clears the stale flag on the server; reloading
  // through the same path as every other bench refresh makes the
  // header's stale banner/chip clear the moment a run completes.
  const ws = useProjectionWorkspace(data, workspaceId, { onProjectionSaved: reload });

  React.useEffect(() => {
    void reload();
  }, [reload]);

  // While an analysis runs on the server, poll the workspace: the
  // reload that observes its completion bumps the inputs epoch, so
  // both panels refetch the post-analysis artifact — an open page
  // can never sit on pre-analysis panel state beside the new saved
  // projection (Oct 27, 2026).
  const analysisState = meta?.analysisJob?.state;
  React.useEffect(() => {
    if (analysisState !== "running") return;
    const timer = window.setInterval(() => {
      void reload();
    }, 4000);
    return () => window.clearInterval(timer);
  }, [analysisState, reload]);

  // Filing-tab gap links point at a slot card on the Inputs tab:
  // switch tabs (the panel stays mounted, so this only reveals it),
  // then scroll the slot into view once it is visible.
  const openSlot = React.useCallback((slotId: string) => {
    setActiveTab("inputs");
    window.setTimeout(() => {
      document.getElementById(`slot-${slotId}`)?.scrollIntoView({ block: "start" });
    }, 60);
  }, []);

  const product = data?.product ?? {};
  const understanding = data?.productUnderstanding ?? {};
  const productName =
    product.name || understanding.productName || meta?.inferredProductName || "Product workspace";
  const productCode = product.code || understanding.productCode || meta?.inferredProductCode || "";
  const carrier = product.carrier || meta?.inferredCarrier || "";
  const productType = product.type || understanding.productType || meta?.inferredProductType || "";
  const readiness = data?.readinessDashboard ?? {};
  const compliance = readiness.complianceSummary ?? data?.complianceMatrix?.summary ?? {};
  const trust = trustLevelLabel(readiness.projectionTrustLevel ?? data?.projectionTrustLevel);
  const gapItems: any[] = Array.isArray(data?.gaps?.items) ? data.gaps.items : [];
  const inputsStale = Boolean(meta?.projectionStale);
  // Live reconciliation of the frozen counts below: what has come
  // into force since that analysis ran (computed server-side on
  // every read; null when nothing has changed since the analysis).
  const reconciliationText = meta?.filingReviewReconciliation?.text ?? null;
  const analysisRunning = analysisState === "running";
  // The counts are labeled with the last COMPLETED analysis — never
  // the workspace's updatedAt, which any later edit would move.
  const analysisTime = meta?.analysisJob?.finishedAt || null;
  // Sub-progress within the running analysis (e.g. "Mechanics — unit
  // 3 of 12"), recorded on the job by the slice-extraction stage.
  const analysisDetail = analysisRunning ? meta?.analysisJob?.phaseDetail || null : null;

  const scenarioOptions = (inputId: string): Array<{ value: string; label: string }> | null => {
    const node = (ws.projectionGraph?.nodes ?? []).find((n: any) => n.inputId === inputId);
    const options = node?.inputConfig?.options;
    return Array.isArray(options) && options.length > 0 ? options : null;
  };

  const scenarioField = (
    inputId: string,
    label: string,
    kind: "number" | "text" | "select" = "text",
  ) => {
    const options = kind === "select" ? scenarioOptions(inputId) : null;
    return (
      <label className="workbench__scenario-field">
        <span>{label}</span>
        {options ? (
          <select value={String(ws.values[inputId] ?? "")} onChange={(e) => ws.updateInput(inputId, e.target.value)}>
            <option value="">Select…</option>
            {options.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        ) : (
          <input
            type={kind === "number" ? "number" : "text"}
            value={String(ws.values[inputId] ?? "")}
            onChange={(e) => ws.updateInput(inputId, e.target.value)}
          />
        )}
      </label>
    );
  };

  const tabPanel = (id: BenchTab, children: React.ReactNode) => (
    <div
      key={id}
      role="tabpanel"
      id={`bench-panel-${id}`}
      aria-labelledby={`bench-tab-${id}`}
      className="workbench__tabpanel"
      hidden={activeTab !== id}
    >
      {children}
    </div>
  );

  return (
    <div className="workbench">
      <header className="card workbench__header">
        <div className="workbench__identity">
          <a className="logic-workspace__back" href="/web">← All workspaces</a>
          <h1>{productName}</h1>
          <p className="muted workbench__identity-line">
            {[productCode, productType, carrier].filter(Boolean).join(" · ") || "Product identity still being established"}
          </p>
          <p className="workbench__state">
            <span className="basis-tag">{trust}</span>{" "}
            <span className="muted">
              {/* These counts are the last analysis's assessment of
                  the filing's requirements (the snapshot's compliance
                  matrix: implemented / partial / missing), frozen at
                  that analysis run. Approvals made since do NOT move
                  them — approval state lives on the Inputs & Equations
                  tab and takes effect on the next projection run. The
                  label says what the counts measure. */}
              {analysisRunning
                ? `Filing review — what the last completed analysis extracted from the documents${
                    analysisTime ? ` (finished ${analysisTime})` : ""
                  }; a new analysis is running and this page will refresh when it finishes${
                    analysisDetail ? ` — now: ${analysisDetail}` : ""
                  }: `
                : `Filing review — what the last analysis extracted from the documents${
                    analysisTime ? ` (finished ${analysisTime})` : ""
                  }: `}
              {compliance.implemented ?? 0} implemented · {compliance.partial ?? 0} partial ·{" "}
              {compliance.missing ?? 0} missing
              {gapItems.length > 0 ? ` · ${gapItems.length} open gap${gapItems.length === 1 ? "" : "s"}` : ""}
              {reconciliationText ? ` — ${reconciliationText}` : ""}
            </span>
          </p>
          {meta?.holisticReview?.status === "absent" && (
            <p className="muted">
              {meta.holisticReview.statement ||
                `Holistic review did not run: ${meta.holisticReview.reason ?? "not recorded"}.`}
            </p>
          )}
          {inputsStale && (
            <div className="workbench__stale" role="status">
              <span>
                Inputs changed since the saved projection was computed. Run the
                projection below to update it — approvals take effect on the next
                projection run; no new analysis is needed.{" "}
                {analysisRunning
                  ? "An analysis is running; this page refreshes when it finishes."
                  : ""}
              </span>
            </div>
          )}
          {!inputsStale && ws.dirty && (
            <p className="workbench__stale" role="status">
              Scenario inputs changed — re-run the projection to update the ledger.
            </p>
          )}
        </div>

        <form
          className="workbench__scenario"
          onSubmit={(event) => {
            event.preventDefault();
            void ws.runProjection(false);
          }}
        >
          <div className="workbench__scenario-fields">
            {scenarioField("issue_age", "Issue age", "number")}
            {scenarioField("face_amount", "Face amount", "number")}
            {scenarioField("premium", "Premium", "number")}
            {scenarioField("premium_mode", "Premium mode", "select")}
            {scenarioField("sex", "Sex", "select")}
            {scenarioField("risk_class", "Risk class", "select")}
            {scenarioField("tobacco_status", "Tobacco status", "select")}
            {"policy_fee" in ws.values && scenarioField("policy_fee", "Policy fee (annual)", "number")}
          </div>
          <div className="workbench__scenario-actions">
            <span className={`logic-workspace__run-state${ws.dirty || !ws.selectorReady || inputsStale ? " is-dirty" : ""}`}>
              {!ws.selectorReady
                ? `Projection needs ${ws.missingSelectors.join(", ")}`
                : inputsStale
                  ? "Saved projection is stale"
                  : ws.dirty
                    ? "Inputs changed"
                    : "Projection current"}
            </span>
            <button type="submit" className="button" disabled={ws.running || !ws.selectorReady}>
              {ws.running ? "Running projection…" : "Run projection"}
            </button>
            <a className="button button-secondary" href={`/web?workspace=${encodeURIComponent(workspaceId)}&view=analysis`}>
              Full filing analysis
            </a>
          </div>
          <p className="muted workbench__scenario-help">
            Run projection recomputes the ledger from the approved equations and
            tables, for the scenario above.
          </p>
        </form>

        {ws.error && <p className="error">{ws.error}</p>}
        {ws.selectorFallbackIssues.length > 0 && (
          <div className="logic-workspace__selector-fallback" role="alert">
            <strong>No exact filed-table match</strong>
            {ws.selectorFallbackIssues.map((issue: any) => (
              <span key={issue.mechanic}>{issue.message} Affected policy years: {issue.years?.join(", ")}.</span>
            ))}
            <button type="button" className="button button-secondary" disabled={ws.running} onClick={() => ws.runProjection(true)}>
              Run with disclosed fallback
            </button>
          </div>
        )}
        {ws.runMessage && <p className="logic-workspace__success" role="status">{ws.runMessage}</p>}
      </header>

      <div className="workbench__tabs" role="tablist" aria-label="Workbench sections">
        {BENCH_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`bench-tab-${tab.id}`}
            aria-selected={activeTab === tab.id}
            aria-controls={`bench-panel-${tab.id}`}
            className={`workbench__tab${activeTab === tab.id ? " is-active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {tabPanel("ledger", (
        <>
          <ProjectionResultsSection ws={ws} />
          <details className="card workbench__map" open={expandMap || undefined}>
            <summary>Details — calculation map (debugging)</summary>
            <p className="muted">
              The dependency graph behind the projection, for tracing how an input reaches a
              result. It is a debugging aid — the bench is where the product is worked.
            </p>
            <ProjectionGraphSection ws={ws} />
          </details>
        </>
      ))}

      {tabPanel("inputs", (
        <div className="workbench__grid">
          <div className="workbench__main">
            <MechanicsPanel
              workspaceId={workspaceId}
              onSnapshotReload={reload}
              refreshKey={inputsEpoch}
              hideStaleBanner
            />
          </div>
          <aside className="workbench__side">
            <EquationsPanel
              workspaceId={workspaceId}
              refreshKey={inputsEpoch}
              onMutated={bumpInputsEpoch}
            />
          </aside>
        </div>
      ))}

      {tabPanel("validation", <ValidationPanel workspaceId={workspaceId} />)}

      {tabPanel("filing", (
        <section className="card home-card workbench__filing" id="filing">
          <h2>Filing</h2>
          <p>
            {productName}
            {productType ? ` — a ${productType} product` : ""}
            {understanding.confidence ? ` · understanding confidence: ${humanize(understanding.confidence).toLowerCase()}` : ""}
            {understanding.documentsReviewed != null ? ` · ${understanding.documentsReviewed} document(s) reviewed` : ""}
          </p>
          <details>
            <summary>Review detail</summary>
            {readiness.overallExplanation && <p className="muted">{readiness.overallExplanation}</p>}
            {gapItems.length > 0 && (
              <>
                <h3>Open gaps</h3>
                <ul className="muted">
                  {gapItems.slice(0, 12).map((gap: any, index: number) => (
                    <li key={gap.id ?? index}>
                      <strong>{gap.title || gap.name || "Gap"}</strong>
                      {gap.description ? ` — ${gap.description}` : ""}
                      {gap.slotId ? (
                        <>
                          {" "}
                          <a
                            href={`#slot-${gap.slotId}`}
                            onClick={(event) => {
                              event.preventDefault();
                              openSlot(String(gap.slotId));
                            }}
                          >
                            Open in product inputs
                          </a>
                        </>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <h3>Documents</h3>
            {documents.length > 0 ? (
              <ul className="muted">
                {documents.map((doc: any) => (
                  <li key={doc.id ?? doc.objectPath ?? doc.createdAt}>
                    {doc.description || doc.objectPath || "Document"}
                    {doc.kind ? ` · ${doc.kind}` : ""}
                    {doc.createdAt ? ` · ${doc.createdAt}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No documents listed for this workspace.</p>
            )}
            {sources.length > 0 && (
              <>
                <h3>Sources in the object store</h3>
                <p className="muted">
                  These documents are referenced in place — the workspace holds no copy. The
                  version analyzed is the one cited by the analysis and its equations.
                </p>
                <ul className="muted">
                  {sources.map((source: any) => (
                    <li key={source.documentId ?? `${source.bucket}/${source.key}`}>
                      <strong>{source.filename || source.key}</strong>
                      <br />
                      {source.bucket}/{source.key}
                      {source.analyzedEtag
                        ? ` · analyzed version ${String(source.analyzedEtag).slice(0, 8)}…`
                        : " · not yet analyzed"}
                      {source.missing ? (
                        <>
                          {" "}
                          <span className="basis-tag">Not found in the store</span>
                        </>
                      ) : source.changedSinceAnalyzed ? (
                        <>
                          {" "}
                          <span className="basis-tag">
                            Changed since analyzed — re-run analysis to use the current version
                          </span>
                        </>
                      ) : null}
                      {source.changedAtAnalyze ? (
                        <>
                          <br />
                          The source changed between selection and the last analyze; the analyze
                          read the current version and updated the pin to it.
                        </>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <p className="muted">
              Re-running the analysis re-reads the filing documents and re-extracts
              tables and equations. It is only needed when the documents change —
              your approvals are kept.
            </p>
            <p>
              <a href={`/web?workspace=${encodeURIComponent(workspaceId)}&view=analysis`}>
                Open the full filing analysis →
              </a>
            </p>
          </details>
        </section>
      ))}

      {tabPanel("activity", <ActivityPanel workspaceId={workspaceId} />)}
    </div>
  );
};

export default WorkbenchPage;
