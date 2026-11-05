import React from "react";

// The bench's Ask tab: a grounded chat scoped to this workspace and
// its presented projection. The server routes each question (filing
// fact / model fact / ledger explanation / scenario change / out of
// scope), assembles ONLY the grounded context for that intent from
// the workspace's own data, and answers from it with citations. The
// chat never computes numbers — scenario changes come back as a
// proposal this panel applies to the scenario form, and the
// projection engine produces the new ledger. Conversation lives
// client-side per workspace session; nothing is persisted.

interface ChatCitation {
  kind: string;
  label: string;
  document?: string;
  page?: number;
  mechanic?: string;
  table?: string;
  years?: number[];
}

interface ScenarioChange {
  field: string;
  label: string;
  currentValue?: any;
  newValue: any;
}

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  intentLabel?: string;
  citations?: ChatCitation[];
  scenarioChanges?: ScenarioChange[];
  applied?: boolean;
  groundingNote?: string;
}

interface ChatPanelProps {
  workspaceId: string;
  /** The run currently presented on the Ledger tab (the client holds
   *  diagnostic runs), sent with each question so answers ground on
   *  the presented ledger, not a stale saved one. */
  presentedRun: any;
  hasFilings: boolean;
  /** Apply a scenario proposal to the bench's scenario form. */
  onApplyScenario: (changes: ScenarioChange[]) => void;
}

const formatValue = (value: any): string => {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  return String(value);
};

export const ChatPanel: React.FC<ChatPanelProps> = ({
  workspaceId,
  presentedRun,
  hasFilings,
  onApplyScenario,
}) => {
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [draft, setDraft] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const listRef = React.useRef<HTMLDivElement | null>(null);

  // A new workspace starts a new conversation.
  React.useEffect(() => {
    setMessages([]);
    setDraft("");
    setError(null);
  }, [workspaceId]);

  React.useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, busy]);

  const hasRun = Boolean(presentedRun && Array.isArray(presentedRun.rows) && presentedRun.rows.length > 0);

  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    const history = messages.slice(-6).map((m) => ({
      role: m.role,
      content: m.text,
    }));
    setMessages((current) => [...current, { role: "user", text }]);
    setDraft("");
    setBusy(true);
    setError(null);
    try {
      const resp = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history,
          presentedRun: hasRun
            ? {
                request: presentedRun.request ?? null,
                rows: presentedRun.rows,
                metrics: presentedRun.metrics ?? null,
              }
            : undefined,
        }),
      });
      if (!resp.ok) throw new Error(`Chat failed (HTTP ${resp.status})`);
      const body = await resp.json();
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: body.answer ?? "",
          intentLabel: body.intentLabel ?? undefined,
          citations: Array.isArray(body.citations) ? body.citations : [],
          scenarioChanges: body.scenario_proposal?.changes ?? undefined,
          groundingNote: body.groundingNote ?? undefined,
        },
      ]);
    } catch (err: any) {
      setError(err?.message || "The question could not be answered.");
    } finally {
      setBusy(false);
    }
  };

  const applyProposal = (index: number, changes: ScenarioChange[]) => {
    onApplyScenario(changes);
    setMessages((current) =>
      current.map((m, i) => (i === index ? { ...m, applied: true } : m)),
    );
  };

  return (
    <section className="card home-card chat-panel" id="chat-panel">
      <h2>Ask</h2>
      <p className="muted">
        Questions about this product and the presented projection, answered from the
        filing documents, the equations and tables in force, and the ledger — every
        figure quoted from its source, never computed here. Ask for a different
        scenario and you'll get a proposal to apply to the scenario form; the
        projection engine does the arithmetic.
      </p>
      {!hasRun && (
        <p className="muted" role="status">
          {hasFilings
            ? "No projection has been presented yet — I can answer filing and model questions now, and ledger questions once you run a projection."
            : "No projection has been presented yet and no filing documents have been analyzed — answers need one of those sources first."}
        </p>
      )}

      <div className="chat-panel__log" ref={listRef}>
        {messages.length === 0 && (
          <p className="muted">
            Try: “What does the filing say about the surrender charge?” · “How is the
            net amount at risk defined?” · “Why does the cash value change in year 9?”
            · “What if the premium were $5,000 a year?”
          </p>
        )}
        {messages.map((message, index) => (
          <div
            key={index}
            className={`chat-panel__message chat-panel__message--${message.role}`}
          >
            {message.role === "assistant" && message.intentLabel && (
              <span className="basis-tag">{message.intentLabel}</span>
            )}
            <p className="chat-panel__text">{message.text}</p>
            {message.groundingNote && (
              <p className="muted chat-panel__note">{message.groundingNote}</p>
            )}
            {message.citations && message.citations.length > 0 && (
              <div className="chat-panel__citations">
                {message.citations.map((citation, cIndex) => (
                  <span key={cIndex} className="basis-tag basis-tag--filed">
                    {citation.label}
                  </span>
                ))}
              </div>
            )}
            {message.scenarioChanges && message.scenarioChanges.length > 0 && (
              <div className="chat-panel__proposal">
                <ul>
                  {message.scenarioChanges.map((change) => (
                    <li key={change.field}>
                      <strong>{change.label}</strong>: {formatValue(change.currentValue)}
                      {" → "}
                      {formatValue(change.newValue)}
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={message.applied}
                  onClick={() => applyProposal(index, message.scenarioChanges!)}
                >
                  {message.applied
                    ? "Applied — press Run projection above"
                    : "Apply to scenario form"}
                </button>
              </div>
            )}
          </div>
        ))}
        {busy && <p className="muted">Answering from the sources…</p>}
      </div>

      {error && <p className="error">{error}</p>}
      <form
        className="chat-panel__composer"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask about the product or the presented projection…"
          aria-label="Ask a question"
        />
        <button type="submit" className="button" disabled={busy || !draft.trim()}>
          Ask
        </button>
      </form>
    </section>
  );
};

export default ChatPanel;
