import React from "react";

// Phase 2 (the chassis): the product-input panel. Each mechanic the UL
// chassis needs is a slot — COI schedule, surrender schedule, policy and
// admin fees, NAR factor, corridor, crediting — showing its status, the
// values currently in force, and where they came from. Slots are edited
// in place (paste or upload a replacement table, change a fee, set the
// NAR factor); the server validates with the same validators ingestion
// uses and rejects invalid input whole. Every edit is recorded in the
// change history below and marks the saved projection stale until the
// analysis is re-run.

interface SlotView {
  id: string;
  mechanic?: string | null;
  label: string;
  kind: "table" | "scalar" | "display";
  status: string;
  statusLabel: string;
  editable: boolean;
  rowCount?: number;
  rows?: Array<Record<string, any>>;
  value?: any;
  provenance?: Array<{
    filename?: string | null;
    page?: number | null;
    tableHeading?: string | null;
    sourceType?: string | null;
    reviewStatus?: string | null;
  }>;
  pendingCandidateCount?: number;
  pendingCandidates?: Array<{
    id?: string;
    filename?: string | null;
    page?: number | null;
    tableHeading?: string | null;
    rowCount?: number | null;
    valueBasis?: string | null;
  }>;
  editedInWorkspace?: boolean;
  lastEdit?: { at?: string | null; who?: string | null } | null;
}

interface ChangeRecord {
  id: string;
  slot: string;
  kind: string;
  who?: string;
  at?: string;
  summary: string;
}

interface PanelPayload {
  workspaceId: string;
  slots: SlotView[];
  changeLog: ChangeRecord[];
  projectionStale: boolean;
  projectionStaleSince?: string | null;
  projectionStaleSlots: string[];
}

const ROW_COLUMNS = [
  "component",
  "duration",
  "attained_age",
  "issue_age",
  "sex",
  "risk_class",
  "tobacco_status",
  "premium_mode",
  "rate",
  "rate_unit",
  "charge",
  "charge_unit",
  "amount",
  "fee_unit",
  "factor",
  "percentage",
];

const statusClass = (status: string): string => {
  switch (status) {
    case "filed_accepted":
      return "basis-tag basis-tag--filed";
    case "synthetic":
      return "basis-tag basis-tag--synthetic";
    case "missing":
      return "basis-tag basis-tag--placeholder";
    default:
      return "basis-tag";
  }
};

const provenanceText = (slot: SlotView): string => {
  const parts: string[] = [];
  for (const source of slot.provenance ?? []) {
    if (source.sourceType === "workspace_edit") {
      parts.push("Workspace edit");
    } else if (source.filename) {
      parts.push(
        source.page != null ? `${source.filename} (p. ${source.page})` : source.filename,
      );
    } else if (source.sourceType) {
      parts.push(source.sourceType);
    }
  }
  return parts.length > 0 ? parts.join("; ") : "—";
};

const SlotRowsTable: React.FC<{ rows: Array<Record<string, any>> }> = ({ rows }) => {
  const present = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (key !== "provenance") present.add(key);
    }
  }
  const columns = ROW_COLUMNS.filter((c) => present.has(c));
  for (const key of present) {
    if (!columns.includes(key)) columns.push(key);
  }
  if (columns.length === 0) return null;
  return (
    <div className="slot-table-wrap">
      <table className="kv-table slot-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx}>
              {columns.map((c) => (
                <td key={c}>{row[c] == null ? "" : String(row[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export const MechanicsPanel: React.FC<{
  workspaceId: string;
  onSnapshotReload?: () => void;
}> = ({ workspaceId, onSnapshotReload }) => {
  const [panel, setPanel] = React.useState<PanelPayload | null>(null);
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);
  const [busySlot, setBusySlot] = React.useState<string | null>(null);
  const [rerunning, setRerunning] = React.useState<boolean>(false);
  const [pasteText, setPasteText] = React.useState<Record<string, string>>({});
  const [feeForm, setFeeForm] = React.useState({ component: "policy_fee", amount: "", feeUnit: "annual_fixed" });
  const [narFactor, setNarFactor] = React.useState<string>("");

  const loadPanel = React.useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/mechanics-panel`);
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Failed to load product inputs (HTTP ${resp.status})`);
      }
      const body: PanelPayload = await resp.json();
      setPanel(body);
      const nar = body.slots.find((s) => s.id === "nar");
      if (nar && nar.value != null) setNarFactor(String(nar.value));
    } catch (err: any) {
      setError(err?.message || "Failed to load product inputs.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  React.useEffect(() => {
    void loadPanel();
  }, [loadPanel]);

  const runEdit = async (slotId: string, payload: Record<string, any>) => {
    setBusySlot(slotId);
    setMessage(null);
    setError(null);
    try {
      const resp = await fetch(
        `/api/workspaces/${encodeURIComponent(workspaceId)}/mechanics-panel/${encodeURIComponent(slotId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      if (!resp.ok) {
        const text = await resp.text();
        let detail = text;
        try {
          detail = JSON.parse(text)?.detail || text;
        } catch {
          /* keep raw text */
        }
        throw new Error(detail || `Edit failed (HTTP ${resp.status})`);
      }
      const body = await resp.json();
      setMessage(body.change?.summary || "Saved.");
      await loadPanel();
    } catch (err: any) {
      setError(err?.message || "Edit failed.");
    } finally {
      setBusySlot(null);
    }
  };

  const handleUpload = (slotId: string): React.ChangeEventHandler<HTMLInputElement> => async (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    setBusySlot(slotId);
    setMessage(null);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const resp = await fetch(
        `/api/workspaces/${encodeURIComponent(workspaceId)}/mechanics-panel/${encodeURIComponent(slotId)}/table-file`,
        { method: "POST", body: form },
      );
      if (!resp.ok) {
        const text = await resp.text();
        let detail = text;
        try {
          detail = JSON.parse(text)?.detail || text;
        } catch {
          /* keep raw text */
        }
        throw new Error(detail || `Upload failed (HTTP ${resp.status})`);
      }
      const body = await resp.json();
      setMessage(body.change?.summary || "Table replaced.");
      await loadPanel();
    } catch (err: any) {
      setError(err?.message || "Upload failed.");
    } finally {
      setBusySlot(null);
      event.target.value = "";
    }
  };

  const handleAcceptCandidate = async (slot: SlotView, candidateId?: string) => {
    if (!slot.mechanic) return;
    setBusySlot(slot.id);
    setMessage(null);
    setError(null);
    try {
      const resp = await fetch(
        `/api/workspaces/${encodeURIComponent(workspaceId)}/filed-mechanics/accept`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mechanic: slot.mechanic, candidateId: candidateId ?? null }),
        },
      );
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Accept failed (HTTP ${resp.status})`);
      }
      setMessage(`Filed ${slot.label.toLowerCase()} accepted and in force.`);
      await loadPanel();
      if (onSnapshotReload) onSnapshotReload();
    } catch (err: any) {
      setError(err?.message || "Accept failed.");
    } finally {
      setBusySlot(null);
    }
  };

  const handleRerun = async () => {
    setRerunning(true);
    setMessage(null);
    setError(null);
    try {
      const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/analyze`, {
        method: "POST",
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Re-run failed (HTTP ${resp.status})`);
      }
      setMessage("Analysis re-run with the edited inputs.");
      await loadPanel();
      if (onSnapshotReload) onSnapshotReload();
    } catch (err: any) {
      setError(err?.message || "Re-run failed.");
    } finally {
      setRerunning(false);
    }
  };

  const slotLabel = (slotId: string): string =>
    panel?.slots.find((s) => s.id === slotId)?.label || slotId;

  return (
    <section className="card home-card" id="mechanics-panel">
      <h2>Product inputs</h2>
      <p className="muted">
        The chassis asks for each input below. Fill a slot from a filing, accept a filed table, or edit it
        here — changes are validated, recorded in the change history, and take effect on the next re-run.
        No document re-upload and no code required.
      </p>
      {loading && <p className="muted">Loading product inputs…</p>}
      {error && <p className="error">{error}</p>}
      {message && <p className="muted">{message}</p>}
      {panel?.projectionStale && (
        <div className="slot-stale-banner">
          <strong>Inputs changed since the last analysis.</strong>{" "}
          The saved projection may be stale (changed: {panel.projectionStaleSlots.map(slotLabel).join(", ")}).{" "}
          <button type="button" className="button" disabled={rerunning} onClick={handleRerun}>
            {rerunning ? "Re-running…" : "Re-run analysis"}
          </button>
        </div>
      )}
      {panel?.slots.map((slot) => (
        <div key={slot.id} id={`slot-${slot.id}`} className="slot-card">
          <h3>
            {slot.label}{" "}
            <span className={statusClass(slot.status)}>{slot.statusLabel}</span>
            {slot.editedInWorkspace && <span className="basis-tag">Edited in workspace</span>}
          </h3>
          <p className="muted">
            <strong>Source:</strong> {provenanceText(slot)}
            {slot.lastEdit?.at && (
              <>
                {" "}· <strong>Last edit:</strong> {slot.lastEdit.at}
                {slot.lastEdit.who ? ` by ${slot.lastEdit.who}` : ""}
              </>
            )}
          </p>
          {slot.kind === "table" && slot.rows && slot.rows.length > 0 && (
            <SlotRowsTable rows={slot.rows} />
          )}
          {slot.kind === "table" && (!slot.rows || slot.rows.length === 0) && (
            <p className="muted">No table in force for this slot.</p>
          )}
          {slot.kind === "scalar" && (
            <p className="muted">
              <strong>Current factor:</strong> {slot.value != null ? String(slot.value) : "not set (1.0 used)"}
            </p>
          )}
          {slot.kind === "display" && (
            <p className="muted">
              <strong>Guaranteed credited rate:</strong>{" "}
              {slot.value != null ? `${(Number(slot.value) * 100).toFixed(2)}%` : "not configured"}
              {" "}— set by the product's assumptions, shown here for completeness.
            </p>
          )}
          {(slot.pendingCandidates ?? []).map((candidate) => (
            <div key={candidate.id || `${candidate.filename}-${candidate.page}`} className="slot-candidate">
              <p className="muted">
                Filed table awaiting review: {candidate.tableHeading || "table"}
                {candidate.filename ? ` — ${candidate.filename}` : ""}
                {candidate.page != null ? ` (p. ${candidate.page})` : ""}
                {candidate.rowCount != null ? `, ${candidate.rowCount} rows` : ""}. Accepting puts the
                filed values in force.
              </p>
              <button
                type="button"
                className="button button-secondary"
                disabled={busySlot === slot.id}
                onClick={() => void handleAcceptCandidate(slot, candidate.id)}
              >
                Accept filed table
              </button>
            </div>
          ))}
          {slot.editable && slot.kind === "table" && (
            <div className="slot-edit">
              <label className="button button-secondary">
                {busySlot === slot.id ? "Working…" : "Upload replacement table (CSV/TSV)"}
                <input
                  type="file"
                  accept=".csv,.tsv"
                  style={{ display: "none" }}
                  disabled={busySlot === slot.id}
                  onChange={handleUpload(slot.id)}
                />
              </label>
              <textarea
                className="slot-paste"
                rows={4}
                placeholder={"Paste CSV here — e.g. duration,rate,rate_unit — then apply. Invalid tables are rejected with the reason."}
                value={pasteText[slot.id] ?? ""}
                onChange={(e) => setPasteText((prev) => ({ ...prev, [slot.id]: e.target.value }))}
              />
              <button
                type="button"
                className="button"
                disabled={busySlot === slot.id || !(pasteText[slot.id] ?? "").trim()}
                onClick={() => void runEdit(slot.id, { csvText: pasteText[slot.id] })}
              >
                Apply pasted table
              </button>
              {slot.id === "fees" && (
                <div className="slot-fee-form">
                  <input
                    type="text"
                    value={feeForm.component}
                    onChange={(e) => setFeeForm((f) => ({ ...f, component: e.target.value }))}
                    placeholder="Component (e.g. policy_fee)"
                  />
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={feeForm.amount}
                    onChange={(e) => setFeeForm((f) => ({ ...f, amount: e.target.value }))}
                    placeholder="Amount"
                  />
                  <select
                    value={feeForm.feeUnit}
                    onChange={(e) => setFeeForm((f) => ({ ...f, feeUnit: e.target.value }))}
                  >
                    <option value="annual_fixed">per year (fixed)</option>
                    <option value="monthly_fixed">per month (fixed)</option>
                    <option value="modal_fixed">per premium payment (fixed)</option>
                    <option value="per_1000_face_annual">per $1,000 of face, per year</option>
                    <option value="percent_premium">fraction of premium</option>
                  </select>
                  <button
                    type="button"
                    className="button"
                    disabled={busySlot === slot.id || feeForm.amount === ""}
                    onClick={() =>
                      void runEdit("fees", {
                        rows: [
                          {
                            component: feeForm.component || "policy_fee",
                            amount: Number(feeForm.amount),
                            fee_unit: feeForm.feeUnit,
                          },
                        ],
                      })
                    }
                  >
                    Set fee
                  </button>
                </div>
              )}
            </div>
          )}
          {slot.editable && slot.kind === "scalar" && (
            <div className="slot-edit">
              <input
                type="number"
                min="0"
                max="2"
                step="0.01"
                value={narFactor}
                onChange={(e) => setNarFactor(e.target.value)}
                placeholder="e.g. 1.05"
              />
              <button
                type="button"
                className="button"
                disabled={busySlot === slot.id || narFactor === ""}
                onClick={() => void runEdit("nar", { factor: Number(narFactor) })}
              >
                Set NAR factor
              </button>
            </div>
          )}
        </div>
      ))}
      {panel && panel.changeLog.length > 0 && (
        <div className="slot-history">
          <h3>Change history</h3>
          <ul className="muted">
            {panel.changeLog.map((change) => (
              <li key={change.id}>
                <strong>{change.at || ""}</strong> — {change.summary}
                {change.who ? ` (${change.who})` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
};
