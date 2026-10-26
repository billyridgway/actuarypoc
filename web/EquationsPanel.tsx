import React from "react";

// Phase 7 (equation doctrine): the equations pane is where stated
// calculations from the filing are approved and where the equations in
// force for each mechanic are shown with their provenance. Built
// against the Phase 7 API contract:
//   GET    /api/workspaces/{id}/equations
//     -> { equations: [{ mechanic, state, verbatim, documentName, page,
//          rendering, provenance: {...}, conflict? }], missingMechanics: [...] }
//   POST   /api/workspaces/{id}/equations/{mechanic}/approve { equationId, confirmed: true }
//   POST   /api/workspaces/{id}/equations/{mechanic}/reject  { equationId }
//   PUT    /api/workspaces/{id}/equations/{mechanic} { equation }
//   POST   /api/workspaces/{id}/equations/harvest
// If the list endpoint is absent (Phase 7 not yet live for this
// workspace), the pane says so plainly and offers the harvest action —
// it never fabricates equation state.

interface EquationView {
  id?: string;
  equationId?: string;
  mechanic: string;
  state?: string;
  verbatim?: string | null;
  documentName?: string | null;
  page?: number | string | null;
  rendering?: string | null;
  provenance?: Record<string, any> | null;
  conflict?: any;
}

interface EquationsPayload {
  equations: EquationView[];
  missingMechanics: string[];
}

const MECHANIC_LABELS: Record<string, string> = {
  coi: "Cost of insurance (COI)",
  surrender: "Surrender charge",
  fees: "Policy and admin fees",
  policy_fee: "Policy and admin fees",
  nar: "Net amount at risk",
  nar_factors: "Net amount at risk",
  net_amount_at_risk: "Net amount at risk",
  crediting: "Interest crediting",
  premium: "Premium",
  death_benefit: "Death benefit",
  corridor: "Minimum death-benefit corridor",
};

export const mechanicLabel = (mechanic: string): string =>
  MECHANIC_LABELS[mechanic] ||
  mechanic
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

const PENDING_STATES = new Set(["pending", "pending_approval", "pending_review", "proposed", "awaiting_approval", "review", "needs_review", "harvested"]);

const isPending = (eq: EquationView): boolean => PENDING_STATES.has(String(eq.state || "").toLowerCase());

const equationIdOf = (eq: EquationView): string | undefined =>
  eq.id ?? eq.equationId ?? eq.provenance?.id ?? eq.provenance?.equationId;

const conflictText = (conflict: any): string | null => {
  if (!conflict) return null;
  if (typeof conflict === "string") return conflict;
  return conflict.message || conflict.description || conflict.detail || "This statement disagrees with the mechanics currently in force.";
};

const provenanceLine = (eq: EquationView): string => {
  const parts: string[] = [];
  if (eq.documentName) parts.push(eq.documentName);
  if (eq.page != null && eq.page !== "") parts.push(`p. ${eq.page}`);
  const prov = eq.provenance || {};
  if (prov.approvedBy) parts.push(`approved by ${prov.approvedBy}`);
  if (prov.approvedAt) parts.push(String(prov.approvedAt));
  if (prov.authoredBy) parts.push(`written by ${prov.authoredBy}`);
  if (prov.source) parts.push(String(prov.source));
  return parts.join(" · ");
};

export const EquationsPanel: React.FC<{ workspaceId: string }> = ({ workspaceId }) => {
  const [payload, setPayload] = React.useState<EquationsPayload | null>(null);
  const [loadState, setLoadState] = React.useState<"loading" | "ready" | "unavailable">("loading");
  const [error, setError] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);
  const [busyKey, setBusyKey] = React.useState<string | null>(null);
  const [confirmingId, setConfirmingId] = React.useState<string | null>(null);
  const [editingMechanic, setEditingMechanic] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState<string>("");

  const base = `/api/workspaces/${encodeURIComponent(workspaceId)}/equations`;

  const load = React.useCallback(async () => {
    try {
      const resp = await fetch(base);
      if (!resp.ok) {
        setLoadState("unavailable");
        setPayload(null);
        return;
      }
      const body = await resp.json();
      setPayload({
        equations: Array.isArray(body?.equations) ? body.equations : [],
        missingMechanics: Array.isArray(body?.missingMechanics) ? body.missingMechanics : [],
      });
      setLoadState("ready");
    } catch {
      setLoadState("unavailable");
      setPayload(null);
    }
  }, [base]);

  React.useEffect(() => {
    setLoadState("loading");
    void load();
  }, [load]);

  const act = async (key: string, run: () => Promise<void>, done: string) => {
    setBusyKey(key);
    setError(null);
    try {
      await run();
      setMessage(done);
      setConfirmingId(null);
      setEditingMechanic(null);
      await load();
    } catch (err: any) {
      setError(err?.message || "The equation action failed.");
    } finally {
      setBusyKey(null);
    }
  };

  const post = async (url: string, body?: any) => {
    const resp = await fetch(url, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!resp.ok) throw new Error((await resp.text()) || `Request failed (HTTP ${resp.status})`);
    return resp.json().catch(() => ({}));
  };

  const handleApprove = (eq: EquationView) => {
    const id = equationIdOf(eq);
    const key = `approve-${eq.mechanic}-${id ?? ""}`;
    if (confirmingId !== key) {
      setConfirmingId(key);
      return;
    }
    void act(key, async () => {
      await post(`${base}/${encodeURIComponent(eq.mechanic)}/approve`, { equationId: id, confirmed: true });
    }, `${mechanicLabel(eq.mechanic)} equation approved and in force.`);
  };

  const handleReject = (eq: EquationView) => {
    const id = equationIdOf(eq);
    void act(`reject-${eq.mechanic}-${id ?? ""}`, async () => {
      await post(`${base}/${encodeURIComponent(eq.mechanic)}/reject`, { equationId: id });
    }, `${mechanicLabel(eq.mechanic)} statement rejected. It will not be used.`);
  };

  const handleHarvest = () => {
    void act("harvest", async () => {
      await post(`${base}/harvest`);
    }, "Looked through the documents for stated calculations. Anything found is listed below for approval.");
  };

  const startEdit = (mechanic: string, current?: string) => {
    setEditingMechanic(mechanic);
    setDraft(current || "");
    setError(null);
  };

  const handleSaveEdit = (mechanic: string, existing?: EquationView) => {
    const text = draft.trim();
    if (!text) {
      setError("Write the equation first — an empty equation cannot be saved.");
      return;
    }
    void act(`save-${mechanic}`, async () => {
      const equation = existing ? { ...existing, rendering: text } : { mechanic, rendering: text };
      const resp = await fetch(`${base}/${encodeURIComponent(mechanic)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ equation }),
      });
      if (!resp.ok) throw new Error((await resp.text()) || `Save failed (HTTP ${resp.status})`);
    }, `${mechanicLabel(mechanic)} equation saved.`);
  };

  const editor = (mechanic: string, existing?: EquationView) => (
    <div className="equation-editor">
      <label>
        Equation for {mechanicLabel(mechanic)}, in actuarial language
        <textarea
          value={draft}
          rows={3}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="e.g. Monthly COI charge = COI table rate × net amount at risk ÷ 1,000, deducted at the start of the month."
        />
      </label>
      <div className="equation-actions">
        <button type="button" className="button" disabled={busyKey === `save-${mechanic}`} onClick={() => handleSaveEdit(mechanic, existing)}>
          {busyKey === `save-${mechanic}` ? "Saving…" : "Save equation"}
        </button>
        <button type="button" className="button button-secondary" onClick={() => setEditingMechanic(null)}>Cancel</button>
      </div>
    </div>
  );

  const pending = (payload?.equations ?? []).filter(isPending);
  const inForce = (payload?.equations ?? []).filter((eq) => !isPending(eq));
  const missing = payload?.missingMechanics ?? [];

  return (
    <section className="card home-card equations-panel" id="equations-panel">
      <h2>Equations</h2>
      <p className="muted">
        The calculations this product runs are the ones stated in its documents and approved
        here — nothing calculates from an unstated default. Approvals are recorded with who
        approved them and where the statement came from.
      </p>
      {error && <p className="error">{error}</p>}
      {message && <p className="muted">{message}</p>}

      {loadState === "loading" && <p className="muted">Loading equations…</p>}

      {loadState === "unavailable" && (
        <div className="equation-unavailable">
          <p>
            <strong>Equations aren't available for this workspace yet.</strong>{" "}
            Equation harvesting hasn't been switched on here, so there are no stated
            calculations to approve and none are in force through this pane.
          </p>
          <div className="equation-actions">
            <button type="button" className="button" disabled={busyKey === "harvest"} onClick={handleHarvest}>
              {busyKey === "harvest" ? "Looking…" : "Look for equations in the documents"}
            </button>
            <button type="button" className="button button-secondary" onClick={() => void load()}>Check again</button>
          </div>
        </div>
      )}

      {loadState === "ready" && payload && (
        <>
          <div className="equation-actions">
            <button type="button" className="button button-secondary" disabled={busyKey === "harvest"} onClick={handleHarvest}>
              {busyKey === "harvest" ? "Looking…" : "Look for equations in the documents"}
            </button>
          </div>

          {pending.length > 0 && (
            <div className="equation-group">
              <h3>Waiting for approval ({pending.length})</h3>
              {pending.map((eq, index) => {
                const id = equationIdOf(eq);
                const key = `approve-${eq.mechanic}-${id ?? index}`;
                const conflict = conflictText(eq.conflict);
                return (
                  <article key={`${eq.mechanic}-${id ?? index}`} className="slot-card equation-card">
                    <h4>{mechanicLabel(eq.mechanic)} <span className="basis-tag basis-tag--placeholder">Approval needed</span></h4>
                    {eq.verbatim && (
                      <blockquote className="equation-verbatim">
                        “{eq.verbatim}”
                        <cite>{provenanceLine(eq) || "the filing"}</cite>
                      </blockquote>
                    )}
                    {eq.rendering && (
                      <p><strong>As an equation:</strong> {eq.rendering}</p>
                    )}
                    {conflict && <p className="equation-conflict"><strong>Disagrees with what's in force:</strong> {conflict}</p>}
                    {editingMechanic === eq.mechanic ? editor(eq.mechanic, eq) : (
                      <div className="equation-actions">
                        <button type="button" className="button" disabled={busyKey === key} onClick={() => handleApprove(eq)}>
                          {busyKey === key ? "Approving…" : confirmingId === key ? "Confirm approval — use this equation" : "Approve"}
                        </button>
                        <button type="button" className="button button-secondary" onClick={() => startEdit(eq.mechanic, eq.rendering || "")}>Edit</button>
                        <button
                          type="button"
                          className="button button-secondary"
                          disabled={busyKey === `reject-${eq.mechanic}-${id ?? ""}`}
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

          {inForce.length > 0 && (
            <div className="equation-group">
              <h3>In force</h3>
              {inForce.map((eq, index) => {
                const id = equationIdOf(eq);
                return (
                  <article key={`${eq.mechanic}-${id ?? index}`} className="slot-card equation-card">
                    <h4>{mechanicLabel(eq.mechanic)} <span className="basis-tag basis-tag--filed">Approved equation</span></h4>
                    {eq.rendering && <p>{eq.rendering}</p>}
                    {eq.verbatim && (
                      <details>
                        <summary>As stated in the document</summary>
                        <blockquote className="equation-verbatim">“{eq.verbatim}”</blockquote>
                      </details>
                    )}
                    <p className="muted">{provenanceLine(eq) || "Provenance recorded with the equation."}</p>
                    {editingMechanic === eq.mechanic ? editor(eq.mechanic, eq) : (
                      <div className="equation-actions">
                        <button type="button" className="button button-secondary" onClick={() => startEdit(eq.mechanic, eq.rendering || "")}>Edit equation</button>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}

          {missing.length > 0 && (
            <div className="equation-group">
              <h3>Equation missing</h3>
              {missing.map((mechanic) => (
                <article key={mechanic} className="slot-card equation-card equation-card--missing">
                  <h4>{mechanicLabel(mechanic)} <span className="basis-tag basis-tag--placeholder">Equation missing</span></h4>
                  <p className="muted">
                    No approved equation is in force for this mechanic, so it does not
                    calculate. Find the statement in the documents, or write the equation.
                  </p>
                  {editingMechanic === mechanic ? editor(mechanic) : (
                    <div className="equation-actions">
                      <button type="button" className="button button-secondary" disabled={busyKey === "harvest"} onClick={handleHarvest}>Look in the documents</button>
                      <button type="button" className="button button-secondary" onClick={() => startEdit(mechanic)}>Write the equation</button>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}

          {pending.length === 0 && inForce.length === 0 && missing.length === 0 && (
            <p className="muted">No equations recorded yet. Use “Look for equations in the documents” to harvest the calculations the filing states.</p>
          )}
        </>
      )}
    </section>
  );
};

export default EquationsPanel;
