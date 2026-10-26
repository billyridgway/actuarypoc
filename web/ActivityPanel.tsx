import React from "react";

// The bench's activity record: one chronological list of everything that
// changed the product — slot edits, candidate acceptances, corrections
// (applied and recorded-as-notes). Sourced from the same mechanics-panel
// payload the product-inputs tooling writes to, so the record here can
// never disagree with the record there.

interface ChangeRecord {
  id: string;
  slot: string;
  kind: string;
  who?: string;
  at?: string;
  summary: string;
}

interface CorrectionRequest {
  id: string;
  title: string;
  description: string;
  status: string;
  createdAt?: string | null;
}

export const ActivityPanel: React.FC<{ workspaceId: string }> = ({ workspaceId }) => {
  const [changes, setChanges] = React.useState<ChangeRecord[] | null>(null);
  const [notes, setNotes] = React.useState<CorrectionRequest[]>([]);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/mechanics-panel`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const body = await resp.json();
      setChanges(Array.isArray(body?.changeLog) ? body.changeLog : []);
      setNotes(Array.isArray(body?.correctionRequests) ? body.correctionRequests : []);
    } catch (err: any) {
      setError(err?.message || "Activity could not be loaded.");
      setChanges([]);
    }
  }, [workspaceId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="card home-card activity-panel" id="activity-panel">
      <h2>Activity</h2>
      <details>
        <summary>What this records</summary>
        <p className="muted">
          Every change to this product's inputs, in order: tables accepted from the filing,
          values edited in the product inputs, corrections applied or recorded as notes.
          Equation approvals join this record as equations are approved in the Equations pane.
        </p>
      </details>
      {error && <p className="error">{error}</p>}
      {changes === null && <p className="muted">Loading activity…</p>}
      {changes !== null && changes.length === 0 && notes.length === 0 && (
        <p className="muted">Nothing has changed yet. Edits, corrections, and approvals will appear here.</p>
      )}
      {changes !== null && changes.length > 0 && (
        <ul className="activity-list">
          {changes.map((change) => (
            <li key={change.id}>
              <strong>{change.at || ""}</strong> — {change.summary}
              {change.who ? <span className="muted"> ({change.who})</span> : null}
            </li>
          ))}
        </ul>
      )}
      {notes.length > 0 && (
        <>
          <h3>Corrections recorded as notes</h3>
          <ul className="activity-list">
            {notes.map((note) => (
              <li key={note.id}>
                <strong>{note.title}</strong> — {note.status}
                {note.createdAt ? <span className="muted"> · {note.createdAt}</span> : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
};

export default ActivityPanel;
