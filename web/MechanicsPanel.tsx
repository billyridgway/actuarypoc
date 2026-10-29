import React from "react";

import { EquationDisplay, type MathNode } from "./EquationMath";

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
    sources?: SourceView[];
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

/** One document a filed table was extracted from. */
interface SourceView {
  filename?: string | null;
  page?: number | null;
  tableHeading?: string | null;
}

/** The name shown for a source: the document, or the plain fact
 *  that no source was recorded — never a vague placeholder. */
const sourceName = (filename?: string | null): string =>
  filename || "source not recorded";

/** Note for a table filed identically in several documents (one
 *  merged candidate): why a single document name is shown. */
const filedIdenticallyNote = (sources?: SourceView[] | null): string =>
  sources && sources.length > 1
    ? ` · filed identically in ${sources.length} documents`
    : "";

interface CandidateView {
  id?: string;
  filename?: string | null;
  page?: number | null;
  tableHeading?: string | null;
  sources?: SourceView[];
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

interface EquationPreview {
  mechanic: string;
  label: string;
  /** will_put_in_effect: confirming this slice installs this
   *  transcription; already_in_effect: an earlier slice's acceptance
   *  already installed it — this act adds coverage only. */
  state: "will_put_in_effect" | "already_in_effect";
  rendering?: string | null;
  math?: MathNode | null;
  timingNote?: string | null;
}

interface ProposalOption {
  candidateId: string;
  filename?: string | null;
  page?: number | null;
  tableHeading?: string | null;
  sources?: SourceView[];
  rowCount?: number | null;
  valueBasis?: string | null;
  coverageText?: string;
  selectors?: Record<string, any[]>;
  inForce?: boolean;
  confirmBack: string;
  /** The unified table+equation act (Oct 29, 2026): for a
   *  transcription mechanic, the equation(s) this slice's acceptance
   *  carries — previewed before confirmation, typeset, exactly the
   *  body acceptance installs.  Absent for tables that carry no
   *  equation (NAR factor, corridor) and for conflict choices. */
  equationPreviews?: EquationPreview[] | null;
  /** Plain statement when one of this table's equations is decided
   *  by its own reading instead — the card never promises a
   *  substitution acceptance will not perform. */
  equationNote?: string | null;
  evidence?: {
    filename?: string | null;
    page?: number | null;
    heading?: string | null;
    snippet?: string | null;
    sources?: SourceView[];
  } | null;
  /** Holistic review outcome for this suggestion (Oct 27, 2026):
   *  verification evidence from the independent re-read, or the
   *  reconciliation note when the review's ladder settled a
   *  divergence in this reading's favour. */
  review?: {
    status?: string | null;
    evidence?: string | null;
    note?: string | null;
  } | null;
  /** An UNRESOLVED holistic review flag: the review could not
   *  reconcile this suggestion, so it is excluded from bulk
   *  approval and decided individually, with the evidence quoted. */
  reviewFlag?: {
    id?: string | null;
    kind?: string | null;
    reason?: string | null;
    evidence?: Array<{
      filename?: string | null;
      page?: number | null;
      snippet?: string | null;
      rendering?: string | null;
    }>;
  } | null;
}

interface ProposalView {
  id: string;
  kind: "filed_table" | "filed_table_choice" | "equation";
  slot: string;
  /** The table mechanic (filed-table proposals; the payload
   *  carries it alongside the slot). */
  mechanic?: string | null;
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
  /** Typeset form of the proposed equation's body (same math tree
   *  the in-force record views carry); null when the body has no
   *  typeset form — the prose rendering then stands alone. */
  math?: MathNode | null;
  timingNote?: string | null;
  evidence?: {
    filename?: string | null;
    page?: number | null;
    heading?: string | null;
    snippet?: string | null;
    sources?: SourceView[];
  } | null;
  /** Holistic review outcome for this suggestion (Oct 27, 2026). */
  review?: {
    status?: string | null;
    evidence?: string | null;
    note?: string | null;
  } | null;
  /** An UNRESOLVED holistic review flag (excluded from bulk). */
  reviewFlag?: {
    id?: string | null;
    kind?: string | null;
    reason?: string | null;
    evidence?: Array<{
      filename?: string | null;
      page?: number | null;
      snippet?: string | null;
      rendering?: string | null;
    }>;
  } | null;
}

interface EquationRecordView {
  id: string;
  mechanic: string;
  version?: number;
  state: string;
  rendering?: string | null;
  math?: MathNode | null;
  timingNote?: string | null;
  timing?: string | null;
  conflict?: boolean;
  source?: Record<string, any>;
  approval?: { by?: string; at?: string } | null;
}

interface BulkItemView {
  proposalId: string;
  kind: "filed_table" | "equation";
  slot: string;
  mechanic?: string | null;
  candidateId?: string | null;
  label: string;
  reason?: string;
  /** One-line holistic-review reconciliation note (eligible items). */
  reviewNote?: string | null;
  reviewFlagId?: string | null;
  /** The reading's provenance class (equation items, Oct 28, 2026) —
   *  a carried-over reading is labeled as one, never passed off as
   *  a filed one. */
  provenanceClass?: string | null;
  provenanceLabel?: string | null;
}

interface BulkSummaryView {
  eligibleCount: number;
  tableCount: number;
  equationCount: number;
  eligible: BulkItemView[];
  excluded: BulkItemView[];
  reviewNotes?: BulkItemView[];
  carriedOver?: BulkItemView[];
  confirmBack: string;
}

/** One reading of a step's equation (product structure, Oct 28, 2026):
 *  an explicit option with its evidence and provenance class. */
interface StructureReadingView {
  key: string;
  mechanic: string;
  recordId?: string | null;
  origin: string;
  state: "in_effect" | "pending";
  rendering?: string | null;
  math?: MathNode | null;
  timingNote?: string | null;
  evidence?: {
    filename?: string | null;
    page?: number | null;
    snippet?: string | null;
  } | null;
  provenanceClass: string;
  provenanceLabel: string;
  /** Set by the server when this reading cannot be confirmed (no
   *  proposal, no saved record): the card shows this reason where
   *  the Confirm button would be, instead of offering a press that
   *  silently does nothing. */
  confirmBlockedReason?: string | null;
}

interface StructureStepView {
  id: string;
  label: string;
  blurb: string;
  equationMechanic: string;
  equationLabel: string;
  tableMechanics: string[];
  slots: SlotView[];
  state: string;
  stateLabel: string;
  options: StructureReadingView[];
  inEffect?: StructureReadingView | null;
  coverage: { state?: string | null; filename?: string | null; page?: number | null };
}

interface StructureView {
  steps: StructureStepView[];
  alsoFound: Array<{ mechanic: string; kind: string }>;
  decisions: Array<{
    stepId: string;
    stepLabel: string;
    kind: string;
    mechanic: string;
    text: string;
  }>;
  progress: {
    settled: number;
    total: number;
    choicesAwaiting: number;
    decisionsAwaiting: number;
    headerText: string;
  };
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
  /** The product structure (Oct 28, 2026): the declared anatomy with
   *  each step's state, readings, and choices — composed once,
   *  server-side; this panel and the decisions checklist both render
   *  from it. */
  structure?: StructureView;
  /** The holistic review record from the last analysis (Oct 27,
   *  2026): status "ran" with its counts, or "absent" with the plain
   *  reason it did not run. */
  holisticReview?: {
    status?: string | null;
    reason?: string | null;
    statement?: string | null;
    counts?: Record<string, number>;
    flags?: Array<Record<string, any>>;
  } | null;
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

/** Product-structure step states -> tag styling (Oct 28, 2026). */
const stepStatusClass = (state: string): string => {
  switch (state) {
    case "settled":
      return "basis-tag basis-tag--filed";
    case "choice":
    case "carried":
      return "basis-tag basis-tag--synthetic";
    case "not_in_documents":
    case "stated_not_extracted":
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

/** One reading of a step's equation, presented as an explicit
 *  option (product structure, Oct 28, 2026).  Choosing an option IS
 *  the approval act: with several readings, the radio selects and
 *  the inline confirm applies; with exactly ONE reading there is no
 *  radio to press first — the confirm button stands on the card
 *  (Billy, Oct 28, 2026).  When the reading travels as a pending
 *  proposal, the proposal's review lines and was/now restatement
 *  ride on this card and Dismiss acts on that proposal — proposals
 *  render inside their step now, not in a separate feed. */
export const StructureOptionCard: React.FC<{
  equationLabel: string;
  radioName: string;
  stepHasInEffect: boolean;
  option: StructureReadingView;
  proposal?: ProposalView | null;
  singleOption: boolean;
  confirming: boolean;
  busy: boolean;
  /** A failed confirm for THIS card, rendered inside it. */
  error?: string | null;
  onSelect: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  onDismissProposal: () => void;
}> = ({
  equationLabel,
  radioName,
  stepHasInEffect,
  option,
  proposal,
  singleOption,
  confirming,
  busy,
  error,
  onSelect,
  onConfirm,
  onCancel,
  onDismissProposal,
}) => {
  const isCurrent = option.state === "in_effect";
  const headerContent = (
    <>
      <strong>{equationLabel}</strong>{" "}
      <span className="basis-tag">{option.provenanceLabel}</span>{" "}
      {isCurrent ? (
        <span className="basis-tag basis-tag--filed">In effect</span>
      ) : (
        <span className="muted">Not in effect</span>
      )}
    </>
  );
  return (
    <div className="choice-option structure-option">
      {singleOption ? (
        <div>{headerContent}</div>
      ) : (
        <label>
          <input
            type="radio"
            name={radioName}
            checked={isCurrent}
            disabled={isCurrent || busy}
            onChange={onSelect}
          />{" "}
          {headerContent}
        </label>
      )}
      {proposal?.reviewFlag && (
        <p className="error">
          Holistic review flag — this suggestion needs your individual review (it
          is excluded from Approve all uncontested): {proposal.reviewFlag.reason}
          {(proposal.reviewFlag.evidence ?? []).map((item, index) => (
            <span key={index}>
              {" "}
              [{sourceName(item.filename)}
              {item.page != null ? `, p. ${item.page}` : ""}
              {item.snippet ? <> — “{item.snippet}”</> : null}]
            </span>
          ))}
        </p>
      )}
      {!proposal?.reviewFlag && proposal?.review?.evidence && (
        <p className="muted">Review: {proposal.review.evidence}.</p>
      )}
      {!proposal?.reviewFlag && proposal?.review?.note && (
        <p className="muted">Review: {proposal.review.note}</p>
      )}
      <EquationDisplay
        math={option.math}
        rendering={option.rendering}
        timingNote={option.timingNote}
      />
      {option.evidence?.filename ? (
        <p className="muted">
          Evidence: {sourceName(option.evidence.filename)}
          {option.evidence.page != null ? `, p. ${option.evidence.page}` : ""}
          {option.evidence.snippet ? <> — “{option.evidence.snippet}”</> : null}
        </p>
      ) : option.provenanceClass === "carried_over" ? (
        <p className="muted">
          Evidence: none — this reading was carried over from the workspace's
          earlier state; no filed statement stands behind it.
        </p>
      ) : null}
      {proposal && !isCurrent ? (
        <p className="muted">{proposal.confirmBack}</p>
      ) : null}
      {error && !isCurrent ? <p className="error">{error}</p> : null}
      {!isCurrent && option.confirmBlockedReason ? (
        <p className="muted">{option.confirmBlockedReason}</p>
      ) : null}
      {!isCurrent && !option.confirmBlockedReason && (singleOption || confirming) && (
        <p>
          <button
            type="button"
            className="button"
            disabled={busy}
            onClick={onConfirm}
          >
            {stepHasInEffect
              ? "Confirm — use this reading instead"
              : "Confirm — put this reading in effect"}
          </button>{" "}
          {proposal ? (
            <>
              <button
                type="button"
                className="button button-secondary"
                disabled={busy}
                onClick={onDismissProposal}
              >
                Dismiss
              </button>{" "}
            </>
          ) : null}
          {!singleOption && (
            <button
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={onCancel}
            >
              Cancel
            </button>
          )}
        </p>
      )}
    </div>
  );
};

/** One pending extraction proposal — a filed-table acceptance, a
 *  genuine table conflict, or an equation reading that matches no
 *  structure option — rendered inside its mechanic's step (the
 *  "Suggested from the filing" feed is retired, Oct 28, 2026).
 *  Confirm/dismiss semantics are the proposal endpoints', unchanged.
 *
 *  Radio rule (Billy, Oct 28, 2026): no radio anywhere on these
 *  cards.  A table proposal with exactly one slice shows the slice
 *  summary with Confirm and apply / Dismiss directly — the slice
 *  adds its coverage to the table in force (union semantics).  A
 *  genuine conflict shows each version as its own block with its
 *  own confirm path: the versions are explicit alternatives, and
 *  choosing one is a decision, not a radio form. */
export const ProposalCard: React.FC<{
  proposal: ProposalView;
  busy: boolean;
  onConfirm: (candidateId?: string) => void;
  onDismiss: () => void;
}> = ({ proposal, busy, onConfirm, onDismiss }) => {
  const isChoice = proposal.kind === "filed_table_choice";
  const options = proposal.options ?? [];
  const optionSummary = (option: ProposalOption) => (
    <span>
      <strong>{sourceName(option.filename)}</strong>
      {option.page != null ? ` (p. ${option.page})` : ""}
      {filedIdenticallyNote(option.sources)}
      {option.coverageText ? ` — ${option.coverageText}` : ""}
      {selectorSummaryText(option.selectors)
        ? ` · ${selectorSummaryText(option.selectors)}`
        : ""}{" "}
      {option.inForce ? <span className="basis-tag">currently in force</span> : null}
    </span>
  );
  return (
    <div className="slot-candidate">
      <p>
        <strong>{proposal.label}</strong>
        {proposal.kind === "equation" ? (
          <span className="basis-tag">equation</span>
        ) : null}
      </p>
      {proposal.conflict && (
        <p className="error">
          These two filed tables disagree on {proposal.conflict.differingRows}{" "}
          row{proposal.conflict.differingRows === 1 ? "" : "s"} where their coverage
          overlaps — choose which one governs those rows. Nothing is merged
          silently.
        </p>
      )}
      {proposal.reviewFlag && (
        <p className="error">
          Holistic review flag — this suggestion needs your individual review (it
          is excluded from Approve all uncontested): {proposal.reviewFlag.reason}
          {(proposal.reviewFlag.evidence ?? []).map((item, index) => (
            <span key={index}>
              {" "}
              [{sourceName(item.filename)}
              {item.page != null ? `, p. ${item.page}` : ""}
              {item.snippet ? <> — “{item.snippet}”</> : null}]
            </span>
          ))}
        </p>
      )}
      {!proposal.reviewFlag && proposal.review?.evidence && (
        <p className="muted">Review: {proposal.review.evidence}.</p>
      )}
      {!proposal.reviewFlag && proposal.review?.note && (
        <p className="muted">Review: {proposal.review.note}</p>
      )}
      {proposal.kind === "equation" && proposal.rendering ? (
        <div className="proposal-equation">
          <EquationDisplay
            math={proposal.math}
            rendering={proposal.rendering}
            timingNote={proposal.timingNote}
          />
        </div>
      ) : null}
      {!isChoice && proposal.evidence && (
        <p className="muted">
          Evidence: {sourceName(proposal.evidence.filename)}
          {proposal.evidence.page != null ? `, p. ${proposal.evidence.page}` : ""}
          {filedIdenticallyNote(proposal.evidence.sources)}
          {proposal.evidence.snippet ? <> — “{proposal.evidence.snippet}”</> : null}
        </p>
      )}
      {isChoice &&
        options.map((option) => {
          const diff = (proposal.optionDiffs ?? []).find(
            (d) => d.candidateId === option.candidateId,
          );
          return (
            <div key={option.candidateId} className="proposal-option">
              {optionSummary(option)}
              {diff && (
                <p className="muted">
                  Compared with the first version: {diff.identicalRows} rows
                  identical, {diff.differingRows} rows differ in value,{" "}
                  {diff.onlyInFirst} rows only in the first, {diff.onlyInOption}{" "}
                  rows only in this one.
                </p>
              )}
              {option.confirmBack ? (
                <p className="muted">{option.confirmBack}</p>
              ) : null}
              {(option.equationPreviews ?? []).map((preview) => (
                <div key={preview.mechanic} className="proposal-equation">
                  <p className="muted">
                    {preview.state === "will_put_in_effect"
                      ? `${preview.label} — the equation this table carries; confirming puts it in effect:`
                      : `${preview.label} — the equation this table carries, already in effect:`}
                  </p>
                  <EquationDisplay
                    math={preview.math}
                    rendering={preview.rendering}
                    timingNote={preview.timingNote}
                  />
                </div>
              ))}
              {option.equationNote ? (
                <p className="muted">{option.equationNote}</p>
              ) : null}
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => onConfirm(option.candidateId ?? undefined)}
              >
                {options.length > 1 && option.inForce
                  ? "Confirm — keep this version in force"
                  : (option.equationPreviews ?? []).some(
                        (p) => p.state === "will_put_in_effect",
                      )
                    ? "Accept this table and its equation"
                    : "Confirm and apply"}
              </button>
            </div>
          );
        })}
      {!isChoice ? <p className="muted">{proposal.confirmBack}</p> : null}
      {!isChoice && (
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={() => onConfirm(undefined)}
        >
          Confirm and apply
        </button>
      )}{" "}
      <button
        type="button"
        className="button button-secondary"
        disabled={busy}
        onClick={onDismiss}
      >
        Dismiss
      </button>
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
  /** Product structure: the option key whose inline confirmation is
   *  open ("Use this reading?") — choosing is the approval act, so it
   *  keeps the confirm-back discipline. */
  const [confirmingOption, setConfirmingOption] = React.useState<string | null>(null);
  /** A failed confirm for one structure option, shown ON that
   *  option's card.  The panel banner alone is not enough: it sits
   *  at the top of a long panel, and a press that only lit it read
   *  as "nothing happened" (Oct 28, 2026). */
  const [optionError, setOptionError] = React.useState<{
    key: string;
    message: string;
  } | null>(null);
  // Bulk approval ("Approve all uncontested", Oct 27, 2026): the
  // summary the server returned for review, before anything applied.
  const [bulkSummary, setBulkSummary] = React.useState<BulkSummaryView | null>(null);
  const [bulkBusy, setBulkBusy] = React.useState<boolean>(false);
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
  // Resolves to the failure message, or null on success.  Callers
  // acting for a specific card pass reportOnCard so the failure is
  // shown on that card (where the person's eyes are) rather than
  // only in the panel banner at the top of a long page.
  const postProposal = async (
    proposalId: string,
    action: "confirm" | "dismiss",
    candidateId?: string,
    reportOnCard?: boolean,
  ): Promise<string | null> => {
    setBusyProposal(proposalId);
    setMessage(null);
    if (!reportOnCard) setError(null);
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
      return null;
    } catch (err: any) {
      const failure = err?.message || "Proposal action failed.";
      if (!reportOnCard) setError(failure);
      return failure;
    } finally {
      setBusyProposal(null);
    }
  };

  // Product structure: choosing an option IS the approval act.  The
  // reading usually travels as a pending proposal — confirming it is
  // the same act as confirming the suggestion — otherwise the pending
  // record is approved through the equations route.  Either way the
  // server records the choice in the change history under the
  // option's own identity, and switching later is the same act.
  const chooseOption = async (step: StructureStepView, option: StructureReadingView) => {
    if (option.state === "in_effect") return;
    const proposal = (panel?.proposals ?? []).find(
      (p) =>
        p.kind === "equation" &&
        p.equationMechanic === step.equationMechanic &&
        p.rendering === option.rendering,
    );
    setOptionError(null);
    if (proposal) {
      setConfirmingOption(null);
      const failure = await postProposal(proposal.id, "confirm", undefined, true);
      if (failure) setOptionError({ key: option.key, message: failure });
      return;
    }
    if (!option.recordId) {
      // No approval path exists for this reading.  Say so on the
      // card itself, with the server's reason when it gave one —
      // a press that only lit the panel banner read as "nothing
      // happened" (Oct 28, 2026).
      setOptionError({
        key: option.key,
        message:
          option.confirmBlockedReason ||
          "This reading has no saved record to approve yet — nothing was applied.",
      });
      return;
    }
    setBusyProposal(option.recordId);
    setMessage(null);
    setError(null);
    try {
      const resp = await fetch(
        `/api/workspaces/${encodeURIComponent(workspaceId)}/equations/${encodeURIComponent(step.equationMechanic)}/approve`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ equationId: option.recordId, confirmed: true }),
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
      setMessage(`Now in effect: ${option.rendering}`);
      setConfirmingOption(null);
      await loadPanel();
      if (onSnapshotReload) onSnapshotReload();
    } catch (err: any) {
      setOptionError({
        key: option.key,
        message: err?.message || "Choosing the reading failed — nothing was applied.",
      });
    } finally {
      setBusyProposal(null);
    }
  };

  // Bulk approval, step 1: ask the server what WOULD be approved.
  // The unconfirmed call applies nothing — it answers 400 with the
  // summary as its detail, the same confirm-back discipline as a
  // single proposal.
  const requestBulkSummary = async () => {
    setBulkBusy(true);
    setMessage(null);
    setError(null);
    try {
      const resp = await fetch(
        `/api/workspaces/${encodeURIComponent(workspaceId)}/mechanics-panel/approve-all`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        },
      );
      const body = await resp.json().catch(() => null);
      const detail = body?.detail;
      if (resp.status === 400 && detail?.code === "confirmation_required" && detail.summary) {
        setBulkSummary(detail.summary as BulkSummaryView);
        return;
      }
      throw new Error(detail?.message || `Request failed (HTTP ${resp.status})`);
    } catch (err: any) {
      setError(err?.message || "Could not prepare the bulk approval summary.");
    } finally {
      setBulkBusy(false);
    }
  };

  // Bulk approval, step 2: the confirmed call applies the uncontested
  // set through the single-item paths; every item lands in the change
  // history individually, tagged with the one batch id.
  const confirmBulkApproval = async () => {
    setBulkBusy(true);
    setMessage(null);
    setError(null);
    try {
      const resp = await fetch(
        `/api/workspaces/${encodeURIComponent(workspaceId)}/mechanics-panel/approve-all`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmed: true }),
        },
      );
      const body = await resp.json().catch(() => null);
      if (!resp.ok) {
        const detail = body?.detail;
        throw new Error(
          (typeof detail === "string" ? detail : detail?.message) ||
            `Request failed (HTTP ${resp.status})`,
        );
      }
      const summary = body.summary ?? {};
      const skipped = (summary.skipped ?? []) as BulkItemView[];
      setMessage(
        `Approved ${summary.appliedCount ?? 0} item(s) in one batch (batch ${body.batchId}).` +
          (skipped.length > 0
            ? ` ${skipped.length} item(s) became contested during the batch and stayed pending: ${skipped
                .map((s) => s.label)
                .join("; ")}.`
            : ""),
      );
      setBulkSummary(null);
      await loadPanel();
      if (onSnapshotReload) onSnapshotReload();
    } catch (err: any) {
      setError(err?.message || "Bulk approval failed.");
    } finally {
      setBulkBusy(false);
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

  // Fold the proposals into the structure (Oct 28, 2026): every
  // pending proposal renders inside its product-structure step —
  // equation readings in the step's options area (matched onto the
  // step's own reading options where they are the same reading),
  // table acceptances in the step's tables area.  Proposals whose
  // mechanic belongs to no step render in the "Also found" group.
  // The grouping is presentation only: confirming and dismissing
  // still go through the proposal endpoints, unchanged.
  const groupedProposals = new Map<string, ProposalView[]>();
  for (const proposal of panel?.proposals ?? []) {
    const steps = panel?.structure?.steps ?? [];
    let stepId: string | null = null;
    if (proposal.kind === "equation") {
      stepId =
        steps.find((s) => s.equationMechanic === proposal.equationMechanic)?.id ??
        null;
    } else {
      stepId =
        steps.find(
          (s) =>
            s.slots.some((slot) => slot.id === proposal.slot) ||
            (proposal.mechanic != null &&
              s.tableMechanics.includes(proposal.mechanic)),
        )?.id ?? null;
    }
    const key = stepId ?? "__also_found";
    groupedProposals.set(key, [...(groupedProposals.get(key) ?? []), proposal]);
  }
  /** The pending proposal that IS this structure option's reading
   *  (same matching chooseOption uses), or null. */
  const equationProposalForOption = (
    step: StructureStepView,
    option: StructureReadingView,
  ): ProposalView | null => {
    if (option.state !== "pending") return null;
    return (
      (groupedProposals.get(step.id) ?? []).find(
        (p) => p.kind === "equation" && p.rendering === option.rendering,
      ) ?? null
    );
  };
  /** Equation proposals in a step that matched no reading option —
   *  rendered as their own cards so nothing is ever lost. */
  const leftoverEquationProposals = (step: StructureStepView): ProposalView[] => {
    const matched = new Set<string>();
    for (const option of step.options) {
      const match = equationProposalForOption(step, option);
      if (match) matched.add(match.id);
    }
    return (groupedProposals.get(step.id) ?? []).filter(
      (p) => p.kind === "equation" && !matched.has(p.id),
    );
  };
  const tableProposalsForStep = (step: StructureStepView): ProposalView[] =>
    (groupedProposals.get(step.id) ?? []).filter((p) => p.kind !== "equation");
  /** The structure step a bulk-summary item belongs to, labeled in
   *  the summary where the data allows. */
  const stepLabelForBulkItem = (item: BulkItemView): string | null => {
    for (const step of panel?.structure?.steps ?? []) {
      if (
        item.mechanic &&
        (step.equationMechanic === item.mechanic ||
          step.tableMechanics.includes(item.mechanic))
      ) {
        return step.label;
      }
      if (item.slot && step.slots.some((slot) => slot.id === item.slot)) {
        return step.label;
      }
    }
    return null;
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
      {panel?.structure && (
        <div className="structure-section">
          <h3>Product structure</h3>
          <p className="muted">
            <strong>{panel.structure.progress.headerText}</strong> — the product's
            anatomy, in the order money flows through it. Each step groups its
            equation and its tables; where the documents offer more than one
            reading, the choice is yours and is shown as one.
          </p>
          {(panel.proposals ?? []).length > 0 && (
            <>
              {panel.holisticReview?.status === "absent" && (
                <p className="muted">
                  {panel.holisticReview.statement ||
                    `Holistic review did not run: ${panel.holisticReview.reason ?? "not recorded"}.`}
                </p>
              )}
              {panel.holisticReview?.status === "ran" && (
                <p className="muted">
                  Holistic review ran before these were offered:{" "}
                  {panel.holisticReview.counts?.verified ?? 0} verified by an
                  independent re-read, {panel.holisticReview.counts?.resolved ?? 0}{" "}
                  divergence(s) reconciled, {panel.holisticReview.counts?.flags ?? 0}{" "}
                  flagged for individual review. The review approves nothing — each
                  suggestion still needs your confirmation.
                </p>
              )}
              <div className="bulk-approve">
                {!bulkSummary ? (
                  <>
                    <button
                      type="button"
                      className="button"
                      disabled={bulkBusy}
                      onClick={() => void requestBulkSummary()}
                    >
                      {bulkBusy ? "Checking…" : "Approve all uncontested"}
                    </button>{" "}
                    <span className="muted">
                      Approves every suggestion in the steps below that nothing
                      contests — after showing you the list. Anything with a rival
                      reading, a replacement, or a conflicting table stays pending
                      and is named.
                    </span>
                  </>
                ) : (
                  <>
                    <p>
                      <strong>{bulkSummary.confirmBack}</strong>
                    </p>
                    {bulkSummary.eligible.length > 0 && (
                      <ul>
                        {bulkSummary.eligible.map((item) => {
                          const stepLabel = stepLabelForBulkItem(item);
                          return (
                            <li key={item.proposalId}>
                              {stepLabel ? (
                                <span className="muted">{stepLabel} — </span>
                              ) : null}
                              {item.kind === "equation" ? "Equation: " : "Filed table: "}
                              {item.label}
                              {item.provenanceLabel ? (
                                <>
                                  {" "}
                                  <span className="basis-tag">{item.provenanceLabel}</span>
                                </>
                              ) : null}
                              {item.reviewNote ? (
                                <span className="muted"> — {item.reviewNote}</span>
                              ) : null}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                    {bulkSummary.excluded.length > 0 && (
                      <>
                        <p className="muted">
                          <strong>Not included — these stay pending:</strong>
                        </p>
                        <ul>
                          {bulkSummary.excluded.map((item) => {
                            const stepLabel = stepLabelForBulkItem(item);
                            return (
                              <li key={item.proposalId}>
                                {stepLabel ? `${stepLabel} — ` : ""}
                                {item.label} — {item.reason}
                              </li>
                            );
                          })}
                        </ul>
                      </>
                    )}
                    <button
                      type="button"
                      className="button"
                      disabled={bulkBusy || bulkSummary.eligibleCount === 0}
                      onClick={() => void confirmBulkApproval()}
                    >
                      {bulkBusy
                        ? "Approving…"
                        : `Confirm — approve ${bulkSummary.eligibleCount} item${bulkSummary.eligibleCount === 1 ? "" : "s"}`}
                    </button>{" "}
                    <button
                      type="button"
                      className="button button-secondary"
                      disabled={bulkBusy}
                      onClick={() => setBulkSummary(null)}
                    >
                      Cancel
                    </button>
                  </>
                )}
              </div>
            </>
          )}
          {panel.structure.decisions.length > 0 && (
            <div className="structure-decisions">
              <p>
                <strong>Decisions</strong>
              </p>
              <ul>
                {panel.structure.decisions.map((decision) => (
                  <li key={`${decision.stepId}-${decision.kind}`}>
                    <a href={`#structure-step-${decision.stepId}`}>{decision.text}</a>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {panel.structure.steps.map((step) => (
            <div key={step.id} className="slot-card structure-step" id={`structure-step-${step.id}`}>
              <h4>
                {step.label}{" "}
                <span className={stepStatusClass(step.state)}>{step.stateLabel}</span>
              </h4>
              <p className="muted">{step.blurb}</p>
              {step.state === "not_in_documents" && (
                <p className="muted">
                  The documents do not state this calculation — it does not
                  calculate. Nothing here is missing from anywhere else; the
                  filing simply does not cover it.
                </p>
              )}
              {step.state === "stated_not_extracted" && (
                <p className="muted">
                  The documents state this calculation, but extraction could not
                  structure it into an equation — that gap is ours, not the
                  filing's.
                </p>
              )}
              {step.options.length > 0 && (
                <div
                  className="choice-options"
                  {...(step.options.length > 1
                    ? {
                        role: "radiogroup",
                        "aria-label": `${step.label} readings`,
                      }
                    : {})}
                >
                  {step.options.map((option) => (
                    <StructureOptionCard
                      key={option.key}
                      equationLabel={step.equationLabel}
                      radioName={`structure-option-${step.id}`}
                      stepHasInEffect={Boolean(step.inEffect)}
                      option={option}
                      proposal={equationProposalForOption(step, option)}
                      singleOption={step.options.length === 1}
                      confirming={confirmingOption === option.key}
                      busy={busyProposal !== null}
                      error={
                        optionError?.key === option.key
                          ? optionError.message
                          : null
                      }
                      onSelect={() => setConfirmingOption(option.key)}
                      onConfirm={() => void chooseOption(step, option)}
                      onCancel={() => setConfirmingOption(null)}
                      onDismissProposal={() => {
                        const proposal = equationProposalForOption(step, option);
                        if (proposal) void postProposal(proposal.id, "dismiss");
                      }}
                    />
                  ))}
                </div>
              )}
              {leftoverEquationProposals(step).map((proposal) => (
                <ProposalCard
                  key={proposal.id}
                  proposal={proposal}
                  busy={busyProposal === proposal.id}
                  onConfirm={(candidateId) =>
                    void postProposal(proposal.id, "confirm", candidateId)
                  }
                  onDismiss={() => void postProposal(proposal.id, "dismiss")}
                />
              ))}
              {(step.slots.length > 0 || tableProposalsForStep(step).length > 0) && (
                <div className="structure-step-tables">
                  {step.slots.length > 0 && (
                    <p className="muted">
                      Tables in this step:{" "}
                      {step.slots.map((slot, index) => (
                        <span key={slot.id}>
                          {index > 0 ? " · " : ""}
                          <a href={`#slot-${slot.id}`}>{slot.label}</a> ({slot.statusLabel})
                        </span>
                      ))}
                    </p>
                  )}
                  {tableProposalsForStep(step).map((proposal) => (
                    <ProposalCard
                      key={proposal.id}
                      proposal={proposal}
                      busy={busyProposal === proposal.id}
                      onConfirm={(candidateId) =>
                        void postProposal(proposal.id, "confirm", candidateId)
                      }
                      onDismiss={() => void postProposal(proposal.id, "dismiss")}
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
          {(panel.structure.alsoFound.length > 0 ||
            (groupedProposals.get("__also_found") ?? []).length > 0) && (
            <div className="slot-card structure-step">
              <h4>Also found in the documents</h4>
              {panel.structure.alsoFound.length > 0 && (
                <p className="muted">
                  {panel.structure.alsoFound
                    .map((item) => `${item.mechanic} (${item.kind})`)
                    .join(" · ")}{" "}
                  — extracted from the documents, but not part of this product
                  type's normal structure. Nothing was forced into the steps above.
                </p>
              )}
              {(groupedProposals.get("__also_found") ?? []).map((proposal) => (
                <ProposalCard
                  key={proposal.id}
                  proposal={proposal}
                  busy={busyProposal === proposal.id}
                  onConfirm={(candidateId) =>
                    void postProposal(proposal.id, "confirm", candidateId)
                  }
                  onDismiss={() => void postProposal(proposal.id, "dismiss")}
                />
              ))}
            </div>
          )}
        </div>
      )}
      {panel?.equations && (
        <div className="slot-card" id="equations-in-force">
          <h3>Equations in force</h3>
          <p className="muted">
            One line per mechanic — the full equations, typeset with their
            provenance, live in the Equations section. Only approved
            equations calculate; a mechanic with none is not calculated.
          </p>
          <ul className="equation-status-list">
            {Object.entries(panel.equations.mechanics).map(([mechanic, view]) => (
              <li key={mechanic}>
                <strong>{view.label}</strong> —{" "}
                {view.inForce ? "approved" : "not calculated"}
                {view.records.some((r) => r.conflict) ? " · conflict" : ""}
              </li>
            ))}
          </ul>
          {panel.equations.conflicts.length > 0 && (
            <p className="muted">
              {panel.equations.conflicts.length} stated calculation(s) conflict with an
              equation in force or could not be structured — see the Equations
              section; nothing was silently dropped or auto-approved.
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
                        <strong>{sourceName(candidate.filename)}</strong>
                        {candidate.page != null ? ` (p. ${candidate.page})` : ""}
                        {filedIdenticallyNote(candidate.sources)}
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
