import React from "react";

// Phase 7 (the equation doctrine): the equations pane is where the
// calculations stated in a workspace's documents are approved, and
// where the equation in force for each mechanic is shown with its
// provenance. It speaks to Phase 7's real API (see
// docs/phase-7-equations.md):
//   GET  /api/workspaces/{id}/equations
//     -> { workspaceId, mechanics: { <mechanic>: { mechanic, label,
//          inForce: <record|null>, records: [<record>], missing,
//          resolution } }, conflicts: [...] }
//     A record is { id, mechanic, version, state, timing, body,
//     rendering, source: { kind, filename, page, statement },
//     sourceKindLabel, approval: { by, at }, conflict } with state in
//     pending | approved | rejected | superseded | unmapped.
//   POST /api/workspaces/{id}/equations/{mechanic}/approve
//     { equationId, confirmed: true } — unconfirmed is a 400 whose
//     detail carries the rendering as the confirm-back.
//   POST /api/workspaces/{id}/equations/{mechanic}/reject { equationId }
//   PUT  /api/workspaces/{id}/equations/{mechanic}
//     { body, timing?, statement?, confirmed } — unconfirmed returns
//     { preview: true, rendering } and writes nothing; an invalid
//     body is a 400 with detail.errors naming each problem.
//   POST /api/workspaces/{id}/equations/harvest
//     -> the full list view plus harvest: { createdCount, ... }.
// The pane never fabricates equation state: what it renders is what
// the API returned, and a mechanic with no approved equation is shown
// as missing — it does not calculate.

interface EquationSource {
  kind?: string | null;
  filename?: string | null;
  page?: number | string | null;
  statement?: string | null;
  [key: string]: any;
}

interface EquationRecord {
  id: string;
  mechanic: string;
  version?: number;
  state: string;
  timing?: string | null;
  body?: any;
  rendering?: string | null;
  source?: EquationSource | null;
  sourceKindLabel?: string | null;
  approval?: { by?: string | null; at?: string | null } | null;
  rejectedBy?: string | null;
  conflict?: { note?: string | null; withEquationId?: string | null } | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

interface MechanicView {
  mechanic: string;
  label: string;
  inForce: EquationRecord | null;
  records: EquationRecord[];
  missing: boolean;
  resolution?: string | null;
}

interface EquationsPayload {
  workspaceId?: string;
  mechanics: Record<string, MechanicView>;
  conflicts: Array<Record<string, any>>;
}

const MECHANIC_ORDER = [
  "coi_charge",
  "surrender_charge",
  "premium_load",
  "policy_fees",
  "crediting",
  "nar_definition",
  "death_benefit",
];

const humanizeMechanic = (mechanic: string): string =>
  mechanic
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

// Starting points for the authoring editor: the standard
// transcriptions of the shapes filings state (the same bodies the
// backend's transcription builders produce), so an actuary edits a
// working equation instead of writing the formula language from a
// blank page. Saving still goes through the API's validation and
// preview/confirm discipline — a template is a draft, never in force
// until confirmed here.
const BODY_TEMPLATES: Record<string, any> = {
  coi_charge: {
    mul: [
      { div: [{ qty: "nar" }, { const: 1000 }] },
      { lookup: { table: "coi", field: "rate" } },
    ],
  },
  surrender_charge: {
    mul: [
      { lookup: { table: "surrender", field: "charge", default: { const: 0 } } },
      { qty: "account_value" },
    ],
  },
  premium_load: {
    mul: [
      { qty: "premium_due" },
      {
        lookup: {
          table: "fees",
          field: "amount",
          where: { fee_unit: "percent_premium" },
          default: { const: 0 },
        },
      },
    ],
  },
  policy_fees: {
    rows_sum: {
      table: "fees",
      exclude_where: { fee_unit: "percent_premium" },
      expr: {
        if: {
          cond: { cmp: ["==", { qty: "row_unit" }, { str: "annual_fixed" }] },
          then: { div: [{ qty: "row_amount" }, { const: 12 }] },
          else: {
            if: {
              cond: { cmp: ["==", { qty: "row_unit" }, { str: "per_1000_face_annual" }] },
              then: {
                div: [
                  { mul: [{ div: [{ qty: "face_amount" }, { const: 1000 }] }, { qty: "row_amount" }] },
                  { const: 12 },
                ],
              },
              else: {
                if: {
                  cond: { cmp: ["==", { qty: "row_unit" }, { str: "modal_fixed" }] },
                  then: { mul: [{ qty: "row_amount" }, { qty: "payment_due" }] },
                  else: { qty: "row_amount" },
                },
              },
            },
          },
        },
      },
    },
  },
  crediting: {
    mul: [
      { qty: "account_value" },
      {
        sub: [
          { pow: [{ add: [{ const: 1 }, { qty: "guaranteed_rate" }] }, { div: [{ const: 1 }, { const: 12 }] }] },
          { const: 1 },
        ],
      },
    ],
  },
  nar_definition: {
    max: [{ sub: [{ qty: "death_benefit" }, { qty: "account_value" }] }, { const: 0 }],
  },
  death_benefit: {
    max: [
      { qty: "face_amount" },
      { mul: [{ lookup: { table: "corridor", field: "percentage", default: { const: 1 } } }, { qty: "account_value" }] },
    ],
  },
};

const COI_TIMINGS = ["beginning", "middle", "end"];

const statementOf = (eq: EquationRecord): string | null =>
  (eq.source?.statement && String(eq.source.statement)) || null;

const provenanceLine = (eq: EquationRecord): string => {
  const parts: string[] = [];
  if (eq.sourceKindLabel) parts.push(eq.sourceKindLabel);
  if (eq.source?.filename) parts.push(String(eq.source.filename));
  if (eq.source?.page != null && eq.source?.page !== "") parts.push(`p. ${eq.source.page}`);
  if (eq.approval?.by) parts.push(`approved by ${eq.approval.by}`);
  if (eq.approval?.at) parts.push(String(eq.approval.at));
  if (eq.version) parts.push(`version ${eq.version}`);
  return parts.join(" · ");
};

const detailMessage = (data: any, status: number): string => {
  const detail = data?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string" && detail.message) return detail.message;
    if (Array.isArray(detail)) {
      return detail.map((d: any) => d?.msg || JSON.stringify(d)).join("; ");
    }
  }
  if (typeof data?.message === "string" && data.message) return data.message;
  return `Request failed (HTTP ${status})`;
};

export const EquationsPanel: React.FC<{ workspaceId: string }> = ({ workspaceId }) => {
  const [payload, setPayload] = React.useState<EquationsPayload | null>(null);
  const [loadState, setLoadState] = React.useState<"loading" | "ready" | "unavailable">("loading");
  const [error, setError] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);
  const [busyKey, setBusyKey] = React.useState<string | null>(null);
  const [confirmingId, setConfirmingId] = React.useState<string | null>(null);
  // The authoring editor: which mechanic, the structured body as
  // editable JSON, the COI timing, the statement it comes from, and
  // the preview confirm-back the API returned for the current draft.
  const [editorMechanic, setEditorMechanic] = React.useState<string | null>(null);
  const [draftBody, setDraftBody] = React.useState<string>("");
  const [draftTiming, setDraftTiming] = React.useState<string>("");
  const [draftStatement, setDraftStatement] = React.useState<string>("");
  const [previewRendering, setPreviewRendering] = React.useState<string | null>(null);
  const [previewErrors, setPreviewErrors] = React.useState<string[]>([]);

  const base = `/api/workspaces/${encodeURIComponent(workspaceId)}/equations`;

  const applyPayload = React.useCallback((body: any) => {
    setPayload({
      workspaceId: body?.workspaceId,
      mechanics: body?.mechanics && typeof body.mechanics === "object" ? body.mechanics : {},
      conflicts: Array.isArray(body?.conflicts) ? body.conflicts : [],
    });
    setLoadState("ready");
  }, []);

  const load = React.useCallback(async () => {
    try {
      const resp = await fetch(base);
      if (!resp.ok) {
        setLoadState("unavailable");
        setPayload(null);
        return;
      }
      applyPayload(await resp.json());
    } catch {
      setLoadState("unavailable");
      setPayload(null);
    }
  }, [base, applyPayload]);

  React.useEffect(() => {
    setLoadState("loading");
    void load();
  }, [load]);

  const requestJson = async (url: string, init?: RequestInit): Promise<any> => {
    const resp = await fetch(url, init);
    const data = await resp.json().catch(() => null);
    if (!resp.ok) throw new Error(detailMessage(data, resp.status));
    return data;
  };

  const act = async (key: string, run: () => Promise<void>, done: string) => {
    setBusyKey(key);
    setError(null);
    try {
      await run();
      setMessage(done);
      setConfirmingId(null);
      closeEditor();
      await load();
    } catch (err: any) {
      setError(err?.message || "The equation action failed.");
    } finally {
      setBusyKey(null);
    }
  };

  const handleApprove = (eq: EquationRecord) => {
    const key = `approve-${eq.mechanic}-${eq.id}`;
    if (confirmingId !== key) {
      setConfirmingId(key);
      setError(null);
      return;
    }
    void act(
      key,
      async () => {
        await requestJson(`${base}/${encodeURIComponent(eq.mechanic)}/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ equationId: eq.id, confirmed: true }),
        });
      },
      `${labelOf(eq.mechanic)} equation approved and in force. The projection now calculates from it.`
    );
  };

  const handleReject = (eq: EquationRecord) => {
    void act(
      `reject-${eq.mechanic}-${eq.id}`,
      async () => {
        await requestJson(`${base}/${encodeURIComponent(eq.mechanic)}/reject`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ equationId: eq.id }),
        });
      },
      `${labelOf(eq.mechanic)} statement rejected. It will not be used.`
    );
  };

  const handleHarvest = () => {
    setBusyKey("harvest");
    setError(null);
    void (async () => {
      try {
        const data = await requestJson(`${base}/harvest`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        const created = Number(data?.harvest?.createdCount ?? 0);
        if (data?.mechanics) applyPayload(data);
        else await load();
        setMessage(
          created > 0
            ? `Harvesting proposed ${created} new equation${created === 1 ? "" : "s"} from the documents — each is waiting below for approval. Nothing runs until it is approved.`
            : "Looked through the documents for stated calculations; no new ones were found."
        );
      } catch (err: any) {
        setError(err?.message || "Harvesting failed.");
      } finally {
        setBusyKey(null);
      }
    })();
  };

  const mechanicViews: MechanicView[] = React.useMemo(() => {
    const mechanics = payload?.mechanics ?? {};
    const ordered = MECHANIC_ORDER.filter((m) => mechanics[m]).map((m) => mechanics[m]);
    const extras = Object.values(mechanics).filter((v) => !MECHANIC_ORDER.includes(v.mechanic));
    return [...ordered, ...extras];
  }, [payload]);

  const labelOf = (mechanic: string): string =>
    mechanicViews.find((v) => v.mechanic === mechanic)?.label || humanizeMechanic(mechanic);

  const pendingRecords: EquationRecord[] = mechanicViews.flatMap((v) =>
    v.records.filter((r) => r.state === "pending")
  );
  const unmappedRecords: EquationRecord[] = mechanicViews.flatMap((v) =>
    v.records.filter((r) => r.state === "unmapped")
  );
  const inForceViews = mechanicViews.filter((v) => v.inForce);
  const actionable = new Set([
    ...pendingRecords.map((r) => r.mechanic),
    ...unmappedRecords.map((r) => r.mechanic),
  ]);
  const missingViews = mechanicViews.filter((v) => v.missing && !actionable.has(v.mechanic));
  const historyRecords: EquationRecord[] = mechanicViews.flatMap((v) =>
    v.records.filter((r) => r.state === "rejected" || r.state === "superseded")
  );

  const closeEditor = () => {
    setEditorMechanic(null);
    setPreviewRendering(null);
    setPreviewErrors([]);
  };

  const openEditor = (mechanic: string, from?: EquationRecord) => {
    setEditorMechanic(mechanic);
    setError(null);
    setPreviewRendering(null);
    setPreviewErrors([]);
    const body = from?.body ?? BODY_TEMPLATES[mechanic];
    setDraftBody(body ? JSON.stringify(body, null, 2) : "");
    setDraftTiming(from?.timing || "");
    setDraftStatement(from ? statementOf(from) || "" : "");
  };

  const putAuthor = async (
    confirmed: boolean
  ): Promise<{ data?: any; errors?: string[] }> => {
    let body: any;
    try {
      body = JSON.parse(draftBody);
    } catch {
      return { errors: ["The equation body is not valid JSON — check the brackets and commas."] };
    }
    const requestBody: Record<string, any> = { body, confirmed };
    const statement = draftStatement.trim();
    if (statement) requestBody.statement = statement;
    if (editorMechanic === "coi_charge" && draftTiming) requestBody.timing = draftTiming;
    const resp = await fetch(`${base}/${encodeURIComponent(editorMechanic || "")}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
    const data = await resp.json().catch(() => null);
    if (!resp.ok) {
      const detail = data?.detail;
      if (detail && Array.isArray(detail.errors)) return { errors: detail.errors as string[] };
      return { errors: [detailMessage(data, resp.status)] };
    }
    return { data };
  };

  const handlePreview = () => {
    if (!editorMechanic) return;
    setBusyKey(`preview-${editorMechanic}`);
    setPreviewErrors([]);
    void (async () => {
      try {
        const { data, errors } = await putAuthor(false);
        if (errors) {
          setPreviewErrors(errors);
          setPreviewRendering(null);
        } else {
          setPreviewRendering(String(data?.rendering || ""));
        }
      } catch (err: any) {
        setPreviewErrors([err?.message || "The preview failed."]);
      } finally {
        setBusyKey(null);
      }
    })();
  };

  const handleConfirmSave = () => {
    if (!editorMechanic) return;
    const mechanic = editorMechanic;
    void act(
      `save-${mechanic}`,
      async () => {
        const { errors } = await putAuthor(true);
        if (errors) throw new Error(errors.join("; "));
      },
      `${labelOf(mechanic)} equation saved and in force, with your authorship recorded.`
    );
  };

  const editor = (mechanic: string) => (
    <div className="equation-editor">
      <p className="muted">
        The equation is a structured formula — the form the projection executes. Edit the
        draft, preview it to see exactly how it reads, then confirm to put it in force with
        your authorship recorded. Nothing is saved before you confirm.
      </p>
      <label>
        Equation body (structured formula, JSON)
        <textarea
          className="equation-body-input"
          value={draftBody}
          rows={10}
          spellCheck={false}
          onChange={(event) => {
            setDraftBody(event.target.value);
            setPreviewRendering(null);
            setPreviewErrors([]);
          }}
        />
      </label>
      {mechanic === "coi_charge" && (
        <label>
          COI deduction timing
          <select
            value={draftTiming}
            onChange={(event) => {
              setDraftTiming(event.target.value);
              setPreviewRendering(null);
            }}
          >
            <option value="">Not specified</option>
            {COI_TIMINGS.map((timing) => (
              <option key={timing} value={timing}>
                {timing === "beginning"
                  ? "Beginning of the month"
                  : timing === "middle"
                    ? "Middle of the month"
                    : "End of the month"}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        The statement this equation comes from (optional)
        <textarea
          value={draftStatement}
          rows={2}
          onChange={(event) => setDraftStatement(event.target.value)}
          placeholder="e.g. The filing's own words, or your note on where this calculation comes from."
        />
      </label>
      {previewErrors.length > 0 && (
        <div className="equation-errors">
          <p><strong>The equation is not valid and was not saved:</strong></p>
          <ul>
            {previewErrors.map((text, index) => (
              <li key={index}>{text}</li>
            ))}
          </ul>
        </div>
      )}
      {previewRendering !== null && (
        <p className="equation-preview">
          <strong>As an equation:</strong> {previewRendering}
        </p>
      )}
      <div className="equation-actions">
        <button
          type="button"
          className="button"
          disabled={busyKey === `preview-${mechanic}`}
          onClick={handlePreview}
        >
          {busyKey === `preview-${mechanic}` ? "Checking…" : "Preview the equation"}
        </button>
        <button
          type="button"
          className="button"
          disabled={previewRendering === null || busyKey === `save-${mechanic}`}
          onClick={handleConfirmSave}
        >
          {busyKey === `save-${mechanic}` ? "Saving…" : "Confirm — put this equation in force"}
        </button>
        <button type="button" className="button button-secondary" onClick={closeEditor}>
          Cancel
        </button>
      </div>
    </div>
  );

  const statementBlock = (eq: EquationRecord) => {
    const statement = statementOf(eq);
    if (!statement) return null;
    const citeParts: string[] = [];
    if (eq.source?.filename) citeParts.push(String(eq.source.filename));
    if (eq.source?.page != null && eq.source?.page !== "") citeParts.push(`p. ${eq.source.page}`);
    return (
      <blockquote className="equation-verbatim">
        “{statement}”
        {citeParts.length > 0 && <cite>{citeParts.join(", ")}</cite>}
      </blockquote>
    );
  };

  return (
    <section className="card home-card equations-panel" id="equations-panel">
      <h2>Equations</h2>
      <p className="muted">
        The calculations this product runs are the ones stated in its documents and approved
        here, or written here by an actuary — nothing calculates from an unstated default.
        Approvals are recorded with who approved them and where the statement came from.
      </p>
      {error && <p className="error">{error}</p>}
      {message && <p className="muted">{message}</p>}

      {loadState === "loading" && <p className="muted">Loading equations…</p>}

      {loadState === "unavailable" && (
        <div className="equation-unavailable">
          <p>
            <strong>The equations for this workspace couldn't be loaded.</strong>{" "}
            Nothing about the product's calculations is shown rather than guess at them.
          </p>
          <div className="equation-actions">
            <button type="button" className="button" onClick={() => void load()}>
              Check again
            </button>
          </div>
        </div>
      )}

      {loadState === "ready" && payload && (
        <>
          <div className="equation-actions">
            <button
              type="button"
              className="button button-secondary"
              disabled={busyKey === "harvest"}
              onClick={handleHarvest}
            >
              {busyKey === "harvest" ? "Looking…" : "Look for equations in the documents"}
            </button>
          </div>

          {pendingRecords.length > 0 && (
            <div className="equation-group">
              <h3>Waiting for approval ({pendingRecords.length})</h3>
              {pendingRecords.map((eq) => {
                const key = `approve-${eq.mechanic}-${eq.id}`;
                return (
                  <article key={eq.id} className="slot-card equation-card">
                    <h4>
                      {labelOf(eq.mechanic)}{" "}
                      <span className="basis-tag basis-tag--placeholder">Approval needed</span>
                    </h4>
                    {statementBlock(eq)}
                    {eq.rendering && (
                      <p><strong>As an equation:</strong> {eq.rendering}</p>
                    )}
                    {eq.conflict?.note && (
                      <p className="equation-conflict">
                        <strong>Disagrees with what's in force:</strong> {eq.conflict.note}
                      </p>
                    )}
                    <p className="muted">{provenanceLine(eq)}</p>
                    {editorMechanic === eq.mechanic ? (
                      editor(eq.mechanic)
                    ) : (
                      <div className="equation-actions">
                        <button
                          type="button"
                          className="button"
                          disabled={busyKey === key}
                          onClick={() => handleApprove(eq)}
                        >
                          {busyKey === key
                            ? "Approving…"
                            : confirmingId === key
                              ? "Confirm approval — use this equation"
                              : "Approve"}
                        </button>
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => openEditor(eq.mechanic, eq)}
                        >
                          Edit first
                        </button>
                        <button
                          type="button"
                          className="button button-secondary"
                          disabled={busyKey === `reject-${eq.mechanic}-${eq.id}`}
                          onClick={() => handleReject(eq)}
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}

          {unmappedRecords.length > 0 && (
            <div className="equation-group">
              <h3>Stated, but not structured ({unmappedRecords.length})</h3>
              {unmappedRecords.map((eq) => (
                <article key={eq.id} className="slot-card equation-card">
                  <h4>
                    {labelOf(eq.mechanic)}{" "}
                    <span className="basis-tag basis-tag--placeholder">Needs an equation</span>
                  </h4>
                  {statementBlock(eq)}
                  <p className="muted">
                    The filing states this calculation, but it could not be structured into
                    an equation automatically. It is recorded here so it is never silently
                    dropped: write the equation from the statement, or reject the record.
                    Until then this mechanic does not calculate from it.
                  </p>
                  <p className="muted">{provenanceLine(eq)}</p>
                  {editorMechanic === eq.mechanic ? (
                    editor(eq.mechanic)
                  ) : (
                    <div className="equation-actions">
                      <button
                        type="button"
                        className="button"
                        onClick={() => openEditor(eq.mechanic, eq)}
                      >
                        Write the equation
                      </button>
                      <button
                        type="button"
                        className="button button-secondary"
                        disabled={busyKey === `reject-${eq.mechanic}-${eq.id}`}
                        onClick={() => handleReject(eq)}
                      >
                        Reject
                      </button>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}

          {inForceViews.length > 0 && (
            <div className="equation-group">
              <h3>In force</h3>
              {inForceViews.map((view) => {
                const eq = view.inForce as EquationRecord;
                return (
                  <article key={view.mechanic} className="slot-card equation-card">
                    <h4>
                      {view.label}{" "}
                      <span className="basis-tag basis-tag--filed">
                        {eq.sourceKindLabel || "Approved equation"}
                      </span>
                    </h4>
                    {eq.rendering && <p>{eq.rendering}</p>}
                    {statementOf(eq) && (
                      <details>
                        <summary>As stated</summary>
                        {statementBlock(eq)}
                      </details>
                    )}
                    <p className="muted">
                      {provenanceLine(eq) || "Provenance recorded with the equation."}
                    </p>
                    {editorMechanic === view.mechanic ? (
                      editor(view.mechanic)
                    ) : (
                      <div className="equation-actions">
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => openEditor(view.mechanic, eq)}
                        >
                          Edit equation
                        </button>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}

          {missingViews.length > 0 && (
            <div className="equation-group">
              <h3>Equation missing</h3>
              {missingViews.map((view) => (
                <article
                  key={view.mechanic}
                  className="slot-card equation-card equation-card--missing"
                >
                  <h4>
                    {view.label}{" "}
                    <span className="basis-tag basis-tag--placeholder">Equation missing</span>
                  </h4>
                  <p className="muted">
                    No approved equation is in force for this mechanic, so it does not
                    calculate.
                    {view.resolution ? ` ${view.resolution}` : ""}
                  </p>
                  {editorMechanic === view.mechanic ? (
                    editor(view.mechanic)
                  ) : (
                    <div className="equation-actions">
                      <button
                        type="button"
                        className="button button-secondary"
                        disabled={busyKey === "harvest"}
                        onClick={handleHarvest}
                      >
                        Look in the documents
                      </button>
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => openEditor(view.mechanic)}
                      >
                        Write the equation
                      </button>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}

          {historyRecords.length > 0 && (
            <details className="equation-group">
              <summary>Earlier equations ({historyRecords.length})</summary>
              {historyRecords.map((eq) => (
                <p key={eq.id} className="muted">
                  <strong>{labelOf(eq.mechanic)}</strong> — {eq.state}
                  {eq.rendering ? `: ${eq.rendering}` : ""}
                  {provenanceLine(eq) ? ` (${provenanceLine(eq)})` : ""}
                </p>
              ))}
            </details>
          )}

          {pendingRecords.length === 0 &&
            unmappedRecords.length === 0 &&
            inForceViews.length === 0 &&
            missingViews.length === 0 && (
              <p className="muted">
                No equations recorded yet. Use “Look for equations in the documents” to
                harvest the calculations the filing states.
              </p>
            )}
        </>
      )}
    </section>
  );
};

export default EquationsPanel;
