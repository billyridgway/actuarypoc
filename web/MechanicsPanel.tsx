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
  /** Every filed candidate, each approved independently (selector
   * slices of one table since Oct 27, 2026). */
  candidates?: CandidateView[];
  coverageText?: string;
  usedByLabels?: string[];
  unusedByEquations?: boolean;
  /** Crediting only: the value is a runtime-config assumption. */
  sourceKind?: string;
  sourceLabel?: string;
  editedInWorkspace?: boolean;
  lastEdit?: { at?: string | null; who?: string | null } | null;
  correction?: CorrectionView | null;
  correctionVariants?: CorrectionVariant[];
}

interface CandidateDiff {
  identicalRows: number;
  differingRows: number;
  onlyInA: number;
  onlyInB: number;
  examples?: Array<Record<string, any>>;
}

interface CandidateView {
  id?: string;
  filename?: string | null;
  page?: number | null;
  tableHeading?: string | null;
  rowCount?: number | null;
  valueBasis?: string | null;
  reviewStatus?: string | null;
  inForce?: boolean;
  coverageText?: string;
  selectors?: Record<string, any[]>;
  overriddenRowCount?: number;
  overriddenBy?: string | null;
  diffVsReference?: CandidateDiff | null;
  referenceCandidateId?: string;
  referenceInForce?: boolean;
}

interface ChangeRecord {
  id: string;
  slot: string;
  kind: string;
  who?: string;
  at?: string;
  summary: string;
}

interface CorrectionView {
  id: string;
  slot?: string;
  mechanic?: string;
  variant: string;
  params?: Record<string, any>;
  who?: string;
  at?: string;
  text?: string | null;
  confirmBack: string;
  replacedStatus?: string | null;
  replacedDescription?: string | null;
  replacedWasFiled?: boolean;
}

interface CorrectionVariant {
  id: string;
  label: string;
  /** Names of the parameters the variant takes (the form is per-variant). */
  params: string[];
  /** Phase 7: the equation mechanic this variant puts in force. */
  equationMechanic?: string;
}

interface ProposalOption {
  candidateId: string;
  filename?: string | null;
  page?: number | null;
  tableHeading?: string | null;
  rowCount?: number | null;
  valueBasis?: string | null;
  coverageText?: string;
  selectors?: Record<string, any[]>;
  inForce?: boolean;
  confirmBack: string;
  evidence?: {
    filename?: string | null;
    page?: number | null;
    heading?: string | null;
    snippet?: string | null;
  } | null;
}

interface ProposalView {
  id: string;
  kind: "filed_table" | "filed_table_choice" | "equation";
  slot: string;
  label: string;
  confirmBack: string;
  candidateId?: string | null;
  options?: ProposalOption[];
  conflict?: {
    candidateId: string;
    incumbentCandidateIds: string[];
    differingRows: number;
    examples?: Array<Record<string, any>>;
  } | null;
  optionDiffs?: Array<{
    candidateId: string;
    comparedTo: string;
    identicalRows: number;
    differingRows: number;
    onlyInFirst: number;
    onlyInOption: number;
    examples?: Array<Record<string, any>>;
  }>;
  equationMechanic?: string | null;
  rendering?: string | null;
  evidence?: {
    filename?: string | null;
    page?: number | null;
    heading?: string | null;
    snippet?: string | null;
  } | null;
}

interface EquationRecordView {
  id: string;
  mechanic: string;
  version?: number;
  state: string;
  rendering?: string | null;
  timing?: string | null;
  conflict?: boolean;
  source?: Record<string, any>;
  approval?: { by?: string; at?: string } | null;
}

interface EquationsView {
  mechanics: Record<
    string,
    {
      label: string;
      inForce?: EquationRecordView | null;
      records: EquationRecordView[];
      missing: boolean;
      resolution?: string;
    }
  >;
  conflicts: Array<Record<string, any>>;
}

interface PanelPayload {
  workspaceId: string;
  slots: SlotView[];
  changeLog: ChangeRecord[];
  corrections: CorrectionView[];
  correctionRequests: Array<{
    id: string;
    title: string;
    description: string;
    status: string;
    createdAt?: string | null;
  }>;
  projectionStale: boolean;
  projectionStaleSince?: string | null;
  projectionStaleSlots: string[];
  /** Pending extraction proposals + the Phase 7 equation state. */
  proposals?: ProposalView[];
  equations?: EquationsView;
}

/** One editable row of a banded (piecewise) schedule correction. */
interface BandRow {
  fromYear: string;
  toYear: string; // "" = open-ended (the final band)
  unit: string;
  value: string;
  gradeTo: string; // "" = constant across the band
}

const SURRENDER_BAND_UNITS = [
  { value: "percent_account_value", label: "% of account value" },
  { value: "percent_face", label: "% of face amount" },
  { value: "per_1000_face", label: "$ per $1,000 of face" },
  { value: "fixed", label: "Flat $" },
];

const COI_BAND_UNITS = [
  { value: "per_1000_monthly", label: "per $1,000 of NAR, monthly" },
  { value: "per_1000_annual", label: "per $1,000 of NAR, annual" },
  { value: "percent_nar_annual", label: "% of NAR, annual" },
];

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
    case "corrected":
      return "basis-tag basis-tag--corrected";
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
    } else if (source.sourceType === "correction") {
      parts.push("Workspace correction");
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

const SELECTOR_LABELS: Record<string, string> = {
  sex: "sex",
  risk_class: "risk class",
  tobacco_status: "tobacco",
  issue_age: "issue age",
  premium_mode: "premium mode",
  component: "component",
};

/** "tobacco Tobacco · risk class Standard" — what distinguishes a
 *  filed candidate on a choice card without opening the table. */
const selectorSummaryText = (selectors?: Record<string, any[]>): string => {
  if (!selectors) return "";
  const parts: string[] = [];
  for (const [field, values] of Object.entries(selectors)) {
    if (Array.isArray(values) && values.length > 0) {
      parts.push(`${SELECTOR_LABELS[field] ?? field} ${values.join("/")}`);
    }
  }
  return parts.join(" · ");
};

const candidateDiffText = (diff?: CandidateDiff | null): string => {
  if (!diff) return "";
  return (
    `${diff.identicalRows} rows identical, ${diff.differingRows} rows differ in value, ` +
    `${diff.onlyInA} rows only in the table in force, ${diff.onlyInB} rows only in this one`
  );
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
  /** Unification revamp: bumped by the workbench whenever ANY panel
   *  mutates workspace state, so every panel refetches the same
   *  store and no two sections can hold different generations of
   *  the truth. */
  refreshKey?: number;
  /** The workbench header carries the one stale-inputs banner; the
   *  panel's own copy is suppressed there (it remains for the
   *  standalone product page). */
  hideStaleBanner?: boolean;
}> = ({ workspaceId, onSnapshotReload, refreshKey, hideStaleBanner }) => {
  const [panel, setPanel] = React.useState<PanelPayload | null>(null);
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);
  const [busySlot, setBusySlot] = React.useState<string | null>(null);
  const [pasteText, setPasteText] = React.useState<Record<string, string>>({});
  const [feeForm, setFeeForm] = React.useState({ component: "policy_fee", amount: "", feeUnit: "annual_fixed" });
  const [narFactor, setNarFactor] = React.useState<string>("");
  // Phase 3 ("This should be…"): per-slot correction form state. A
  // correction is previewed first — the server restates it in actuarial
  // language — and only applied when the user confirms that statement.
  const [corrVariant, setCorrVariant] = React.useState<Record<string, string>>({});
  const [corrParams, setCorrParams] = React.useState<Record<string, Record<string, string>>>({});
  const [corrText, setCorrText] = React.useState<Record<string, string>>({});
  const [corrPreview, setCorrPreview] = React.useState<Record<string, any>>({});
  // Phase 4: banded-schedule editor state (per slot) and the busy flag
  // for proposal confirm/dismiss actions.
  const [corrBands, setCorrBands] = React.useState<Record<string, BandRow[]>>({});
  const [busyProposal, setBusyProposal] = React.useState<string | null>(null);
  // Unification revamp: the chosen option of a filed-table choice
  // proposal. Slot-card candidates are approved independently since
  // the selector-slice model (Oct 27, 2026) — no radio choice there.
  const [choiceSelection, setChoiceSelection] = React.useState<Record<string, string>>({});
  // A refused accept that named a genuine conflict, keyed
  // `${slotId}:${candidateId}` — the card then offers the explicit
  // override decision instead of a bare error.
  const [conflictFor, setConflictFor] = React.useState<Record<string, string>>({});

  const bandsFor = (slot: SlotView): BandRow[] => {
    const existing = corrBands[slot.id];
    if (existing && existing.length > 0) return existing;
    const unit = slot.id === "coi" ? "per_1000_monthly" : "percent_account_value";
    return [
      { fromYear: "1", toYear: "10", unit, value: "", gradeTo: "" },
      { fromYear: "11", toYear: "", unit, value: "", gradeTo: "" },
    ];
  };

  const updateBands = (slot: SlotView, rows: BandRow[]) => {
    setCorrBands((prev) => ({ ...prev, [slot.id]: rows }));
  };

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

  // Refetch when the workbench signals that another panel changed
  // the workspace (the mount-time load above is not skipped: the
  // first refreshKey value is the one we mounted with).
  const mountedRefreshKey = React.useRef(refreshKey);
  React.useEffect(() => {
    if (mountedRefreshKey.current === refreshKey) return;
    mountedRefreshKey.current = refreshKey;
    void loadPanel();
  }, [refreshKey, loadPanel]);

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

  const handleAcceptCandidate = async (
    slot: SlotView,
    candidateId?: string,
    resolveConflict = false,
  ) => {
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
          body: JSON.stringify({
            mechanic: slot.mechanic,
            candidateId: candidateId ?? null,
            resolveConflict,
          }),
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
        // A genuine conflict is a decision to offer, not an error:
        // the row disagrees with a version in force, and only the
        // user can say which governs. Nothing was written.
        if (
          resp.status === 409 &&
          typeof detail === "string" &&
          detail.includes("conflicts with the accepted table")
        ) {
          setConflictFor((prev) => ({
            ...prev,
            [`${slot.id}:${candidateId ?? ""}`]: detail,
          }));
          return;
        }
        throw new Error(detail || `Accept failed (HTTP ${resp.status})`);
      }
      setConflictFor((prev) => {
        const next = { ...prev };
        delete next[`${slot.id}:${candidateId ?? ""}`];
        return next;
      });
      setMessage(`Filed ${slot.label.toLowerCase()} accepted and in force.`);
      await loadPanel();
      if (onSnapshotReload) onSnapshotReload();
    } catch (err: any) {
      setError(err?.message || "Accept failed.");
    } finally {
      setBusySlot(null);
    }
  };

  const slotLabel = (slotId: string): string =>
    panel?.slots.find((s) => s.id === slotId)?.label || slotId;

  const postCorrection = async (
    slotId: string,
    suffix: string,
    payload: Record<string, any>,
  ): Promise<any> => {
    const resp = await fetch(
      `/api/workspaces/${encodeURIComponent(workspaceId)}/mechanics-panel/${encodeURIComponent(slotId)}/corrections${suffix}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    const text = await resp.text();
    let body: any = null;
    try {
      body = JSON.parse(text);
    } catch {
      /* keep raw text */
    }
    if (!resp.ok) {
      const detail = body?.detail;
      const message =
        (typeof detail === "string" ? detail : detail?.message) ||
        text ||
        `Request failed (HTTP ${resp.status})`;
      throw new Error(message);
    }
    return body;
  };

  const correctionPayload = (slot: SlotView): Record<string, any> => {
    const variantId = corrVariant[slot.id] ?? "";
    const raw = corrParams[slot.id] ?? {};
    const params: Record<string, any> = {};
    if (variantId === "surrender_basis") {
      params.basis = raw.basis || "percent_account_value";
      // The percentage field is entered as a percentage ("8" for 8%).
      if (params.basis === "flat_amount") {
        if (raw.amount) params.amount = Number(raw.amount);
      } else if (raw.percent) {
        params.percent = Number(raw.percent) / 100;
      }
      if (raw.gradingYears) params.gradingYears = Number(raw.gradingYears);
    } else if (variantId === "coi_timing") {
      params.timing = raw.timing || "end";
    } else if (variantId === "nar_definition") {
      params.definition = raw.definition || "unadjusted";
    } else if (variantId === "surrender_banded" || variantId === "coi_banded") {
      // Percentage-based band values are entered as percentages
      // ("8" for 8%) and converted to fractions, like the basis form.
      const convert = (unit: string, rawValue: string): number => {
        const n = Number(rawValue);
        return unit.startsWith("percent") ? n / 100 : n;
      };
      params.bands = bandsFor(slot).map((band) => {
        const out: Record<string, any> = {
          fromYear: Number(band.fromYear),
          toYear: band.toYear.trim() === "" ? null : Number(band.toYear),
          unit: band.unit,
          value: convert(band.unit, band.value),
        };
        if (band.gradeTo.trim() !== "") out.gradeTo = convert(band.unit, band.gradeTo);
        return out;
      });
    }
    return {
      variant: variantId || null,
      params,
      text: (corrText[slot.id] ?? "").trim() || null,
    };
  };

  const handlePreviewCorrection = async (slot: SlotView) => {
    setBusySlot(slot.id);
    setMessage(null);
    setError(null);
    try {
      const body = await postCorrection(slot.id, "/preview", correctionPayload(slot));
      setCorrPreview((prev) => ({ ...prev, [slot.id]: body }));
    } catch (err: any) {
      setError(err?.message || "Could not preview the correction.");
    } finally {
      setBusySlot(null);
    }
  };

  const handleApplyCorrection = async (slot: SlotView) => {
    const preview = corrPreview[slot.id];
    setBusySlot(slot.id);
    setMessage(null);
    setError(null);
    try {
      const payload = preview?.suggested
        ? {
            variant: preview.suggestion.variant,
            params: preview.suggestion.params,
            text: (corrText[slot.id] ?? "").trim() || null,
            confirmed: true,
          }
        : { ...correctionPayload(slot), confirmed: true };
      const body = await postCorrection(slot.id, "", payload);
      setMessage(body.correction?.confirmBack || "Correction applied.");
      setCorrPreview((prev) => ({ ...prev, [slot.id]: null }));
      await loadPanel();
    } catch (err: any) {
      setError(err?.message || "Could not apply the correction.");
    } finally {
      setBusySlot(null);
    }
  };

  // Phase 4: extraction proposals. Confirming sends confirmed: true —
  // the server refuses anything less and returns the restated change;
  // dismissing persists so the proposal does not come back.
  const postProposal = async (
    proposalId: string,
    action: "confirm" | "dismiss",
    candidateId?: string,
  ) => {
    setBusyProposal(proposalId);
    setMessage(null);
    setError(null);
    try {
      const resp = await fetch(
        `/api/workspaces/${encodeURIComponent(workspaceId)}/mechanics-panel/proposals/${encodeURIComponent(proposalId)}/${action}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            action === "confirm"
              ? { confirmed: true, ...(candidateId ? { candidateId } : {}) }
              : {},
          ),
        },
      );
      const text = await resp.text();
      let body: any = null;
      try {
        body = JSON.parse(text);
      } catch {
        /* keep raw text */
      }
      if (!resp.ok) {
        const detail = body?.detail;
        throw new Error(
          (typeof detail === "string" ? detail : detail?.message) || text || `Request failed (HTTP ${resp.status})`,
        );
      }
      setMessage(
        action === "confirm"
          ? body.proposal?.confirmBack || "Proposal applied."
          : "Proposal dismissed — it will not be suggested again.",
      );
      await loadPanel();
      if (action === "confirm" && onSnapshotReload) onSnapshotReload();
    } catch (err: any) {
      setError(err?.message || "Proposal action failed.");
    } finally {
      setBusyProposal(null);
    }
  };

  const handleRecordCorrectionNote = async (slot: SlotView) => {
    setBusySlot(slot.id);
    setMessage(null);
    setError(null);
    try {
      const body = await postCorrection(slot.id, "", {
        variant: null,
        params: {},
        text: (corrText[slot.id] ?? "").trim() || null,
      });
      setMessage(
        body.featureRequest
          ? "Recorded as a product note / feature request — the projection is unchanged."
          : "Recorded.",
      );
      setCorrPreview((prev) => ({ ...prev, [slot.id]: null }));
      await loadPanel();
    } catch (err: any) {
      setError(err?.message || "Could not record the correction.");
    } finally {
      setBusySlot(null);
    }
  };

  return (
    <section className="card home-card" id="mechanics-panel">
      <h2>Product inputs</h2>
      <p className="muted">
        The chassis asks for each input below. Fill a slot from a filing, accept a filed table, or edit it
        here — changes are validated, recorded in the change history, and take effect on the next projection run.
        No document re-upload and no code required.
      </p>
      {loading && <p className="muted">Loading product inputs…</p>}
      {error && <p className="error">{error}</p>}
      {message && <p className="muted">{message}</p>}
      {panel?.projectionStale && !hideStaleBanner && (
        <div className="slot-stale-banner">
          <strong>Inputs changed since the saved projection was computed.</strong>{" "}
          The saved projection may be stale (changed: {panel.projectionStaleSlots.map(slotLabel).join(", ")}).{" "}
          Re-run the projection to update it — approvals take effect on the next
          projection run; no new analysis is needed.
        </div>
      )}
      {panel && (panel.proposals ?? []).length > 0 && (
        <div className="slot-card" id="extraction-proposals">
          <h3>Suggested from the filing</h3>
          <p className="muted">
            These were read from the filing's tables and text, with the page each came from.
            Nothing is applied until you confirm it — confirming restates the change below
            exactly as it will take effect.
          </p>
          {(panel.proposals ?? []).map((proposal) => {
            const isChoice = proposal.kind === "filed_table_choice";
            const options = proposal.options ?? [];
            const selectedId =
              choiceSelection[proposal.id] ??
              (options.length === 1 ? options[0].candidateId : undefined);
            const selected = options.find((o) => o.candidateId === selectedId);
            const selectedDiff = (proposal.optionDiffs ?? []).find(
              (d) => d.candidateId === selectedId,
            );
            return (
            <div key={proposal.id} className="slot-candidate">
              <p>
                <strong>{proposal.label}</strong>
                {proposal.kind === "equation" ? (
                  <span className="basis-tag">equation</span>
                ) : null}
              </p>
              {proposal.conflict && (
                <p className="error">
                  These two filed tables disagree on {proposal.conflict.differingRows}{" "}
                  row{proposal.conflict.differingRows === 1 ? "" : "s"} where their
                  coverage overlaps — choose which one governs those rows. Nothing is
                  merged silently.
                </p>
              )}
              {proposal.kind === "equation" && proposal.rendering ? (
                <p className="muted">Equation: {proposal.rendering}</p>
              ) : null}
              {!isChoice && proposal.evidence && (
                <p className="muted">
                  Evidence: {proposal.evidence.filename || "the filing"}
                  {proposal.evidence.page != null ? `, p. ${proposal.evidence.page}` : ""}
                  {proposal.evidence.snippet ? <> — “{proposal.evidence.snippet}”</> : null}
                </p>
              )}
              {isChoice && (
                <div className="choice-options" role="radiogroup" aria-label={proposal.label}>
                  {options.map((option) => (
                    <label key={option.candidateId} className="choice-option">
                      <input
                        type="radio"
                        name={`choice-${proposal.id}`}
                        checked={selectedId === option.candidateId}
                        onChange={() =>
                          setChoiceSelection((prev) => ({
                            ...prev,
                            [proposal.id]: option.candidateId,
                          }))
                        }
                      />
                      <span>
                        <strong>{option.filename || "the filing"}</strong>
                        {option.page != null ? ` (p. ${option.page})` : ""}
                        {option.coverageText ? ` — ${option.coverageText}` : ""}
                        {selectorSummaryText(option.selectors)
                          ? ` · ${selectorSummaryText(option.selectors)}`
                          : ""}{" "}
                        {option.inForce ? (
                          <span className="basis-tag">currently in force</span>
                        ) : null}
                      </span>
                    </label>
                  ))}
                  {selectedDiff && (
                    <p className="muted">
                      Compared with the first version: {selectedDiff.identicalRows} rows
                      identical, {selectedDiff.differingRows} rows differ in value,{" "}
                      {selectedDiff.onlyInFirst} rows only in the first,{" "}
                      {selectedDiff.onlyInOption} rows only in this one.
                    </p>
                  )}
                </div>
              )}
              <p className="muted">{selected ? selected.confirmBack : proposal.confirmBack}</p>
              <button
                type="button"
                className="button"
                disabled={busyProposal === proposal.id || (isChoice && !selectedId)}
                onClick={() => void postProposal(proposal.id, "confirm", selectedId)}
              >
                Confirm and apply
              </button>{" "}
              <button
                type="button"
                className="button button-secondary"
                disabled={busyProposal === proposal.id}
                onClick={() => void postProposal(proposal.id, "dismiss")}
              >
                Dismiss
              </button>
            </div>
            );
          })}
        </div>
      )}
      {panel?.equations && (
        <div className="slot-card" id="equations-in-force">
          <h3>Equations in force</h3>
          <p className="muted">
            Only approved equations calculate. A mechanic with no approved equation is
            not calculated — the projection states the absence instead of substituting
            a fallback.
          </p>
          {Object.entries(panel.equations.mechanics).map(([mechanic, view]) => (
            <div key={mechanic} className="slot-candidate">
              <p>
                <strong>{view.label}</strong>{" "}
                {view.inForce ? (
                  <span className="basis-tag">approved</span>
                ) : (
                  <span className="basis-tag">not calculated</span>
                )}
                {view.records.some((r) => r.conflict) ? (
                  <span className="basis-tag">conflict</span>
                ) : null}
              </p>
              {view.inForce ? (
                <p className="muted">
                  {view.inForce.rendering}
                  {view.inForce.approval?.by ? (
                    <> — approved by {view.inForce.approval.by}</>
                  ) : null}
                </p>
              ) : (
                <p className="muted">{view.resolution}</p>
              )}
              {view.records
                .filter((r) => r.state === "pending")
                .map((r) => (
                  <p key={r.id} className="muted">
                    Pending approval: {r.rendering ?? "(stated, not yet structured)"}
                  </p>
                ))}
            </div>
          ))}
          {panel.equations.conflicts.length > 0 && (
            <p className="muted">
              {panel.equations.conflicts.length} stated calculation(s) conflict with an
              equation in force or could not be structured — see the equation records;
              nothing was silently dropped or auto-approved.
            </p>
          )}
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
            {slot.kind === "table" && slot.coverageText && (
              <>
                {" "}· <strong>In force:</strong> {slot.coverageText}
              </>
            )}
            {slot.lastEdit?.at && (
              <>
                {" "}· <strong>Last edit:</strong> {slot.lastEdit.at}
                {slot.lastEdit.who ? ` by ${slot.lastEdit.who}` : ""}
              </>
            )}
          </p>
          {slot.kind !== "display" && (slot.rows?.length ?? 0) > 0 && (
            <p className="muted">
              {slot.unusedByEquations ? (
                <span className="basis-tag">Not used by any approved equation</span>
              ) : (slot.usedByLabels ?? []).length > 0 ? (
                <>Read by: {(slot.usedByLabels ?? []).join(", ")}</>
              ) : (
                <>No approved equation reads this table yet.</>
              )}
            </p>
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
              {slot.sourceKind === "assumption" ? (
                <>
                  {" "}<span className="assumption-tag">Assumption</span>{" "}
                  {slot.sourceLabel ??
                    "Set in the product's runtime configuration; not read from the filing."}
                </>
              ) : (
                <> — set by the product's assumptions, shown here for completeness.</>
              )}
            </p>
          )}
          {(slot.candidates ?? []).length > 0 && (
            <div className="slot-candidate">
              <p className="muted">
                <strong>Filed versions of this table</strong> — each version covers
                part of the table's selectors; accept each one that should be in
                force. The table in force is the union of the accepted versions.
              </p>
              <div className="choice-options">
                {(slot.candidates ?? []).map((candidate) => {
                  const conflictKey = `${slot.id}:${candidate.id ?? ""}`;
                  return (
                    <div
                      key={candidate.id || `${candidate.filename}-${candidate.page}`}
                      className="choice-option"
                    >
                      <span>
                        <strong>{candidate.filename || "the filing"}</strong>
                        {candidate.page != null ? ` (p. ${candidate.page})` : ""}
                        {candidate.coverageText ? ` — ${candidate.coverageText}` : ""}
                        {selectorSummaryText(candidate.selectors)
                          ? ` · Covers: ${selectorSummaryText(candidate.selectors)}`
                          : ""}{" "}
                        {candidate.inForce ? (
                          candidate.overriddenRowCount ? (
                            <span className="basis-tag">
                              In force — {candidate.overriddenRowCount} row
                              {candidate.overriddenRowCount === 1 ? "" : "s"} overridden
                              by a later acceptance
                            </span>
                          ) : (
                            <span className="basis-tag">In force — part of the table</span>
                          )
                        ) : candidate.reviewStatus === "superseded" ? (
                          <span className="basis-tag">Superseded</span>
                        ) : (
                          <span className="basis-tag">Awaiting review</span>
                        )}
                      </span>
                      {candidate.diffVsReference && !candidate.inForce && (
                        <p className="muted">
                          Compared with the version in force:{" "}
                          {candidateDiffText(candidate.diffVsReference)}.
                        </p>
                      )}
                      {!candidate.inForce && (
                        <p>
                          <button
                            type="button"
                            className="button button-secondary"
                            disabled={busySlot === slot.id}
                            onClick={() => void handleAcceptCandidate(slot, candidate.id)}
                          >
                            {candidate.reviewStatus === "superseded"
                              ? "Put this version back in force"
                              : "Accept this version"}
                          </button>
                        </p>
                      )}
                      {conflictFor[conflictKey] && (
                        <p className="error">
                          {conflictFor[conflictKey]}{" "}
                          <button
                            type="button"
                            className="button"
                            disabled={busySlot === slot.id}
                            onClick={() =>
                              void handleAcceptCandidate(slot, candidate.id, true)
                            }
                          >
                            Accept and override the conflicting rows
                          </button>
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          <details className="slot-details">
            <summary>Details — rows, replace, correct</summary>
          {slot.kind === "table" && slot.rows && slot.rows.length > 0 && (
            <SlotRowsTable rows={slot.rows} />
          )}
          {slot.kind === "table" && (!slot.rows || slot.rows.length === 0) && (
            <p className="muted">No table in force for this slot.</p>
          )}
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
          <div className="slot-correction">
            <h4>This should be…</h4>
            {slot.correction && (
              <p className="slot-correction-active">
                <strong>Correction in force:</strong> {slot.correction.confirmBack}
                {slot.correction.replacedWasFiled
                  ? " It overrides the filed values; the filed values are preserved in the correction record and the change history."
                  : ""}
              </p>
            )}
            <p className="muted">
              If this calculation is wrong, say what it should be. You will see the change
              restated in actuarial language and nothing is applied until you confirm it.
            </p>
            {(slot.correctionVariants ?? []).length > 0 && (
              <select
                value={corrVariant[slot.id] ?? ""}
                onChange={(e) => {
                  setCorrVariant((prev) => ({ ...prev, [slot.id]: e.target.value }));
                  setCorrPreview((prev) => ({ ...prev, [slot.id]: null }));
                }}
              >
                <option value="">Choose what should change…</option>
                {(slot.correctionVariants ?? []).map((variant) => (
                  <option key={variant.id} value={variant.id}>
                    {variant.label}
                  </option>
                ))}
              </select>
            )}
            {(corrVariant[slot.id] ?? "") === "surrender_basis" && (
              <div className="slot-correction-params">
                <label className="slot-correction-param">
                  Charge basis
                  <select
                    value={(corrParams[slot.id] ?? {}).basis ?? "percent_account_value"}
                    onChange={(e) =>
                      setCorrParams((prev) => ({
                        ...prev,
                        [slot.id]: { ...(prev[slot.id] ?? {}), basis: e.target.value },
                      }))
                    }
                  >
                    <option value="percent_account_value">% of account value</option>
                    <option value="percent_face">% of face amount</option>
                    <option value="flat_amount">Flat amount</option>
                  </select>
                </label>
                {((corrParams[slot.id] ?? {}).basis ?? "percent_account_value") === "flat_amount" ? (
                  <label className="slot-correction-param">
                    Amount in year 1 ($)
                    <input
                      type="number"
                      min="0"
                      step="any"
                      value={(corrParams[slot.id] ?? {}).amount ?? ""}
                      onChange={(e) =>
                        setCorrParams((prev) => ({
                          ...prev,
                          [slot.id]: { ...(prev[slot.id] ?? {}), amount: e.target.value },
                        }))
                      }
                    />
                  </label>
                ) : (
                  <label className="slot-correction-param">
                    Percentage in year 1 (%)
                    <input
                      type="number"
                      min="0"
                      step="any"
                      value={(corrParams[slot.id] ?? {}).percent ?? ""}
                      onChange={(e) =>
                        setCorrParams((prev) => ({
                          ...prev,
                          [slot.id]: { ...(prev[slot.id] ?? {}), percent: e.target.value },
                        }))
                      }
                    />
                  </label>
                )}
                <label className="slot-correction-param">
                  Grading years (to 0)
                  <input
                    type="number"
                    min="1"
                    max="40"
                    step="1"
                    value={(corrParams[slot.id] ?? {}).gradingYears ?? ""}
                    onChange={(e) =>
                      setCorrParams((prev) => ({
                        ...prev,
                        [slot.id]: { ...(prev[slot.id] ?? {}), gradingYears: e.target.value },
                      }))
                    }
                  />
                </label>
              </div>
            )}
            {(corrVariant[slot.id] ?? "") === "coi_timing" && (
              <label className="slot-correction-param">
                Deduct the COI charge
                <select
                  value={(corrParams[slot.id] ?? {}).timing ?? "end"}
                  onChange={(e) =>
                    setCorrParams((prev) => ({
                      ...prev,
                      [slot.id]: { ...(prev[slot.id] ?? {}), timing: e.target.value },
                    }))
                  }
                >
                  <option value="beginning">At the beginning of the month, before interest</option>
                  <option value="middle">In the middle of the month, half before and half after interest</option>
                  <option value="end">At the end of the month, after interest</option>
                </select>
              </label>
            )}
            {(corrVariant[slot.id] ?? "") === "nar_definition" && (
              <label className="slot-correction-param">
                Net amount at risk is
                <select
                  value={(corrParams[slot.id] ?? {}).definition ?? "unadjusted"}
                  onChange={(e) =>
                    setCorrParams((prev) => ({
                      ...prev,
                      [slot.id]: { ...(prev[slot.id] ?? {}), definition: e.target.value },
                    }))
                  }
                >
                  <option value="unadjusted">Death benefit − account value (no NAR factor)</option>
                  <option value="factor_adjusted">Death benefit ÷ NAR factor − account value</option>
                </select>
              </label>
            )}
            {((corrVariant[slot.id] ?? "") === "surrender_banded" ||
              (corrVariant[slot.id] ?? "") === "coi_banded") && (
              <div className="slot-correction-params">
                <p className="muted">
                  Bands must start at year 1 and join up with no gaps or overlaps; only the
                  last band may be open-ended. Percentage values are entered as percentages
                  (8 means 8%). “Grading to” is optional — leave it blank for a constant band.
                </p>
                {bandsFor(slot).map((band, index) => {
                  const units = slot.id === "coi" ? COI_BAND_UNITS : SURRENDER_BAND_UNITS;
                  const rows = bandsFor(slot);
                  return (
                    <div key={index} className="slot-band-row">
                      <label className="slot-correction-param">
                        From year
                        <input
                          type="number"
                          min="1"
                          step="1"
                          value={band.fromYear}
                          onChange={(e) =>
                            updateBands(slot, rows.map((r, i) => (i === index ? { ...r, fromYear: e.target.value } : r)))
                          }
                        />
                      </label>
                      <label className="slot-correction-param">
                        To year (blank = onward)
                        <input
                          type="number"
                          min="1"
                          step="1"
                          value={band.toYear}
                          onChange={(e) =>
                            updateBands(slot, rows.map((r, i) => (i === index ? { ...r, toYear: e.target.value } : r)))
                          }
                        />
                      </label>
                      <label className="slot-correction-param">
                        Basis
                        <select
                          value={band.unit}
                          onChange={(e) =>
                            updateBands(slot, rows.map((r, i) => (i === index ? { ...r, unit: e.target.value } : r)))
                          }
                        >
                          {units.map((unit) => (
                            <option key={unit.value} value={unit.value}>
                              {unit.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="slot-correction-param">
                        Value{band.unit.startsWith("percent") ? " (%)" : ""}
                        <input
                          type="number"
                          min="0"
                          step="any"
                          value={band.value}
                          onChange={(e) =>
                            updateBands(slot, rows.map((r, i) => (i === index ? { ...r, value: e.target.value } : r)))
                          }
                        />
                      </label>
                      <label className="slot-correction-param">
                        Grading to (optional)
                        <input
                          type="number"
                          min="0"
                          step="any"
                          value={band.gradeTo}
                          onChange={(e) =>
                            updateBands(slot, rows.map((r, i) => (i === index ? { ...r, gradeTo: e.target.value } : r)))
                          }
                        />
                      </label>
                      <button
                        type="button"
                        className="button button-secondary"
                        disabled={rows.length <= 1}
                        onClick={() => updateBands(slot, rows.filter((_, i) => i !== index))}
                      >
                        Remove band
                      </button>
                    </div>
                  );
                })}
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => {
                    const rows = bandsFor(slot);
                    const last = rows[rows.length - 1];
                    const unit = slot.id === "coi" ? "per_1000_monthly" : "percent_account_value";
                    updateBands(slot, [
                      ...rows,
                      {
                        fromYear: last && last.toYear ? String(Number(last.toYear) + 1) : "",
                        toYear: "",
                        unit: last?.unit || unit,
                        value: "",
                        gradeTo: "",
                      },
                    ]);
                  }}
                >
                  Add band
                </button>
              </div>
            )}
            {(() => {
              const variant = (slot.correctionVariants ?? []).find(
                (v) => v.id === (corrVariant[slot.id] ?? ""),
              );
              return variant?.equationMechanic ? (
                <p className="muted">
                  Puts an approved {variant.equationMechanic.replace(/_/g, " ")}{" "}
                  equation in force — the correction is the equation.
                </p>
              ) : null;
            })()}
            <textarea
              className="slot-paste"
              rows={2}
              placeholder="…or describe the correction in your own words. Your words are kept word-for-word; anything that does not match a known change is recorded as a product note, never dropped."
              value={corrText[slot.id] ?? ""}
              onChange={(e) => setCorrText((prev) => ({ ...prev, [slot.id]: e.target.value }))}
            />
            <div className="slot-correction-actions">
              <button
                type="button"
                className="button button-secondary"
                disabled={
                  busySlot === slot.id ||
                  (!((corrVariant[slot.id] ?? "") !== "") && !(corrText[slot.id] ?? "").trim())
                }
                onClick={() => void handlePreviewCorrection(slot)}
              >
                Preview correction
              </button>
            </div>
            {corrPreview[slot.id] && (
              <div className="slot-correction-confirm">
                <p>
                  <strong>Please confirm:</strong> {corrPreview[slot.id].confirmBack}
                </p>
                {corrPreview[slot.id].mapped && (
                  <button
                    type="button"
                    className="button"
                    disabled={busySlot === slot.id}
                    onClick={() => void handleApplyCorrection(slot)}
                  >
                    Confirm and apply
                  </button>
                )}
                {corrPreview[slot.id].suggested && (
                  <button
                    type="button"
                    className="button"
                    disabled={busySlot === slot.id}
                    onClick={() => void handleApplyCorrection(slot)}
                  >
                    Yes — apply it that way
                  </button>
                )}
                {!corrPreview[slot.id].mapped && !corrPreview[slot.id].suggested && (
                  <button
                    type="button"
                    className="button"
                    disabled={busySlot === slot.id}
                    onClick={() => void handleRecordCorrectionNote(slot)}
                  >
                    Record as a note
                  </button>
                )}
              </div>
            )}
          </div>
          </details>
        </div>
      ))}
      {panel && panel.correctionRequests.length > 0 && (
        <div className="slot-history">
          <h3>Corrections recorded as notes</h3>
          <p className="muted">
            These corrections did not match a known calculation change, so they were
            captured word-for-word as product notes / feature requests. The projection is
            unchanged by them.
          </p>
          <ul className="muted">
            {panel.correctionRequests.map((request) => (
              <li key={request.id}>
                <strong>{request.title}</strong> — {request.status}
                {request.createdAt ? ` · ${request.createdAt}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
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
