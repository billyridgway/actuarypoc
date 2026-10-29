// Contract test for web/EquationMath.tsx against the math-tree
// vocabulary the server actually ships (render_math_tree in
// src/actuarypoc/domain/equations.py), and — since Oct 28, 2026 —
// for the approval-card surfaces in web/MechanicsPanel.tsx
// (StructureOptionCard / ProposalCard) and the option-card layout
// rules in web/styles.css.  The panel itself fetches its payload,
// so the fold assertions there are source-structure checks; the
// cards are pure components and render to string like the rest.
//
// Why this exists: on Oct 27, 2026 the renderer and the server
// builder drifted apart — the renderer read cmp operands from
// left/right (server ships a/b), unary children from `of` (server
// ships x), treated the binary sub {a, b} as an items list, and had
// no cases for text/min.  Pressing "Approve all" put equation
// records carrying those nodes in force, the component threw during
// render, and with no error boundary the whole UI went white.
//
// This test renders EquationDisplay to a string over:
//   - fixtures/live-math-trees.json — the 7 real math trees from
//     Billy's live workspace ws-4fa227ca (fetched from the running
//     app the day of the crash), and
//   - fixtures/vocabulary-math-trees.json — synthetic trees for the
//     rest of the server's emitted vocabulary (min, neg, not, and,
//     or, bands-style cases, lookup without default, str, text),
//     legacy spellings the renderer tolerates, and malformed nodes
//     that must degrade, never throw.
// and asserts: no throw, and the substantive tokens survive.
//
// Run (from web/): npm run test:unit
// (esbuild + react-dom come from the app's own node_modules.)

import { buildSync } from "esbuild";
import { createRequire } from "node:module";
import { readFileSync, rmSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToString } from "react-dom/server";

const here = dirname(fileURLToPath(import.meta.url));
const webDir = join(here, "..");
const buildDir = join(here, ".build");
mkdirSync(buildDir, { recursive: true });
const bundlePath = join(buildDir, "EquationMath.cjs");
buildSync({
  entryPoints: [join(webDir, "EquationMath.tsx")],
  bundle: true,
  platform: "node",
  format: "cjs",
  external: ["react", "react-dom", "react-dom/server"],
  outfile: bundlePath,
  logLevel: "silent",
});
const require = createRequire(join(webDir, "package.json"));
const { EquationDisplay } = require(bundlePath);

const panelBundlePath = join(buildDir, "MechanicsPanel.cjs");
buildSync({
  entryPoints: [join(webDir, "MechanicsPanel.tsx")],
  bundle: true,
  platform: "node",
  format: "cjs",
  external: ["react", "react-dom", "react-dom/server"],
  outfile: panelBundlePath,
  logLevel: "silent",
});
const { StructureOptionCard, ProposalCard } = require(panelBundlePath);
const panelSource = readFileSync(join(webDir, "MechanicsPanel.tsx"), "utf8");
const stylesSource = readFileSync(join(webDir, "styles.css"), "utf8");

const live = JSON.parse(
  readFileSync(join(here, "fixtures", "live-math-trees.json"), "utf8"),
);
const vocab = JSON.parse(
  readFileSync(join(here, "fixtures", "vocabulary-math-trees.json"), "utf8"),
);

let failures = 0;
const check = (name, fn) => {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (err) {
    failures += 1;
    console.log(`FAIL ${name}: ${err.message}`);
  }
};
const expectTokens = (rawHtml, tokens) => {
  // React SSR interleaves <!-- --> comment markers between text
  // runs; strip them so token checks see the rendered text.
  const html = rawHtml.replace(/<!--[\s\S]*?-->/g, "");
  for (const token of tokens) {
    if (!html.includes(token)) {
      throw new Error(`missing token ${JSON.stringify(token)} in: ${html.slice(0, 220)}`);
    }
  }
};
const expectAbsent = (rawHtml, tokens) => {
  const html = rawHtml.replace(/<!--[\s\S]*?-->/g, "");
  for (const token of tokens) {
    if (html.includes(token)) {
      throw new Error(`unexpected token ${JSON.stringify(token)} in: ${html.slice(0, 220)}`);
    }
  }
};
const renderDisplay = (math, extra = {}) =>
  renderToString(
    React.createElement(EquationDisplay, {
      math,
      rendering: extra.rendering ?? "prose rendering",
      timingNote: extra.timingNote ?? null,
      defaultWordsOpen: extra.defaultWordsOpen ?? false,
    }),
  );

// --- The 7 live trees: no throw, substantive content -------------
const liveExpectations = {
  coi_charge: ["net amount at risk", "COI rate", "1000", "duration, attained age"],
  surrender_charge: ["face amount", "surrender charge", "1000"],
  premium_load: ["premium due this month", "fee amount", "fee unit = percent_premium"],
  policy_fees: ["Σ", "fee schedule", "=", "row unit", "annual_fixed", "otherwise"],
  crediting: ["account value", "guaranteed annual rate", "−", "("],
  nar_definition: ["max(", "−", "death benefit", "account value", "NAR factor"],
  death_benefit: ["max(", "face amount", "corridor percentage", "account value"],
};
for (const [mechanic, tokens] of Object.entries(liveExpectations)) {
  check(`live tree ${mechanic} renders with content`, () => {
    const rec = live[mechanic];
    const html = renderDisplay(rec.math, {
      rendering: rec.rendering,
      timingNote: rec.timingNote,
    });
    expectTokens(html, tokens);
  });
}
check("live coi_charge timing note renders as its own line", () => {
  const rec = live.coi_charge;
  const html = renderDisplay(rec.math, {
    rendering: rec.rendering,
    timingNote: rec.timingNote,
  });
  expectTokens(html, ["Timing:", "beginning of each month"]);
});

// --- The rest of the server vocabulary ---------------------------
const vocabExpectations = {
  min_node: ["min(", "account value", "5000"],
  neg_node: ["−", "surrender charge"],
  not_node: ["not (", "duration", "≥"],
  and_or_node: [" and ", " or ", "attained age", "is male", "is smoker"],
  bands_cases: ["duration in years 1–5", "otherwise", "0.055"],
  lookup_no_default: ["COI rate", "risk class = standard"],
  str_node: ["annual_fixed"],
  text_node: ["per the filed schedule"],
  legacy_cmp: ["duration", "≤", "30"],
  legacy_paren_and_sub_items: ["(", "10", "−", "3"],
};
for (const [name, tokens] of Object.entries(vocabExpectations)) {
  check(`vocabulary ${name} renders with content`, () => {
    expectTokens(renderDisplay(vocab[name]), tokens);
  });
}

// --- Degradation, never a throw ----------------------------------
check("unknown node renders no math and does not throw", () => {
  // The math block is empty; the prose survives behind the
  // collapsed "In words" toggle (Oct 28, 2026) rather than inline.
  const html = renderDisplay(vocab.unknown_node);
  expectTokens(html, ["equation-words-toggle"]);
  expectAbsent(html, ["prose rendering"]);
});
check("null child inside mul does not throw", () => {
  const html = renderDisplay(vocab.null_child_mul);
  expectTokens(html, ["premium"]);
});
check("null math node degrades to prose", () => {
  const html = renderToString(
    React.createElement(EquationDisplay, { math: null, rendering: "just prose" }),
  );
  expectTokens(html, ["just prose"]);
});

// --- Proposal-shaped payloads (equations consolidation) ----------
// Since the consolidation, an equation proposal in the mechanics
// panel renders through this same component, fed with exactly the
// fields the proposal payload carries (math + rendering +
// timingNote, built server-side from the candidate body).  A
// suggestion must be approved in the same typeset form it will run
// in; a proposal whose body has no typeset form (math null) must
// degrade to its prose — never a throw, never blank.
const renderProposal = (proposal) =>
  renderToString(
    React.createElement(EquationDisplay, {
      math: proposal.math,
      rendering: proposal.rendering,
      timingNote: proposal.timingNote ?? null,
    }),
  );
check("proposal-shaped payload renders typeset with In words collapsed", () => {
  // Since Oct 28, 2026 the prose rendering sits behind the "In
  // words" toggle, collapsed by default: the toggle is present and
  // the prose-only fragment of the rendering is NOT in the output.
  const rec = live.premium_load;
  const html = renderProposal({
    kind: "equation",
    math: rec.math,
    rendering: rec.rendering,
    timingNote: rec.timingNote,
  });
  expectTokens(html, ["equation-math", "premium due this month", "equation-words-toggle"]);
  expectAbsent(html, ["(or 0 if no row applies)"]);
});
check("In words toggle expands to the prose rendering", () => {
  const rec = live.premium_load;
  const html = renderDisplay(rec.math, {
    rendering: rec.rendering,
    defaultWordsOpen: true,
  });
  expectTokens(html, ["In words:", "(or 0 if no row applies)", 'aria-expanded="true"']);
});
check("proposal-shaped payload renders its Timing line", () => {
  const rec = live.coi_charge;
  const html = renderProposal({
    kind: "equation",
    math: rec.math,
    rendering: rec.rendering,
    timingNote: rec.timingNote,
  });
  expectTokens(html, ["equation-math", "Timing:", "beginning of each month"]);
});
check("proposal with null math degrades to prose only", () => {
  const html = renderProposal({
    kind: "equation",
    math: null,
    rendering: "the stated charge, not yet structured",
    timingNote: null,
  });
  expectTokens(html, ["the stated charge, not yet structured"]);
});

// --- Structure option cards (Oct 28, 2026) ------------------------
// Billy's radio rule: a step with exactly ONE reading option shows
// its confirm button directly — no radio to press first.  Several
// readings keep select-then-confirm.
const noop = () => {};
const narOption = (overrides = {}) => ({
  key: "nar-1",
  mechanic: "nar_definition",
  recordId: "rec-1",
  origin: "harvest",
  state: "pending",
  rendering: live.nar_definition.rendering,
  math: live.nar_definition.math,
  timingNote: null,
  evidence: {
    filename: "ICC18 P18PRUL.pdf",
    page: 4,
    snippet: "Net Amount at Risk is the difference",
  },
  provenanceClass: "filed_definition",
  provenanceLabel: "Filed definition",
  ...overrides,
});
const renderOptionCard = (props) =>
  renderToString(
    React.createElement(StructureOptionCard, {
      equationLabel: "Net amount at risk definition",
      radioName: "structure-option-nar",
      stepHasInEffect: false,
      busy: false,
      confirming: false,
      onSelect: noop,
      onConfirm: noop,
      onCancel: noop,
      onDismissProposal: noop,
      ...props,
    }),
  );
check("single-option card: direct confirm, no radio, no cancel", () => {
  const html = renderOptionCard({ option: narOption(), singleOption: true });
  expectTokens(html, ["Confirm — put this reading in effect", "Filed definition"]);
  expectAbsent(html, ['type="radio"', "Cancel"]);
});
check("multi-option card unselected: radio present, no confirm yet", () => {
  const html = renderOptionCard({ option: narOption(), singleOption: false });
  expectTokens(html, ['type="radio"']);
  expectAbsent(html, ["Confirm — put this reading in effect", "Confirm — use this reading instead"]);
});
check("multi-option card confirming: confirm and cancel appear", () => {
  const html = renderOptionCard({
    option: narOption(),
    singleOption: false,
    confirming: true,
  });
  expectTokens(html, ['type="radio"', "Confirm — put this reading in effect", "Cancel"]);
});
check("single-option card with an incumbent: use-instead wording, no radio", () => {
  const html = renderOptionCard({
    option: narOption(),
    singleOption: true,
    stepHasInEffect: true,
  });
  expectTokens(html, ["Confirm — use this reading instead"]);
  expectAbsent(html, ['type="radio"']);
});
check("in-effect option card: no radio to press, no confirm", () => {
  const html = renderOptionCard({
    option: narOption({ state: "in_effect" }),
    singleOption: true,
  });
  expectTokens(html, ["In effect"]);
  expectAbsent(html, ['type="radio"', "Confirm —"]);
});

// --- The silent Confirm (Oct 28, 2026) ----------------------------
// Billy's death-benefit card: a single harvested reading, NO saved
// record (recordId null) — its only approval path is the pending
// proposal the server attaches.  When the proposal exists the card
// offers its direct confirm as usual; when the server says the
// reading cannot be confirmed (confirmBlockedReason), the card must
// show the reason INSTEAD of a button that does nothing, and a
// failed confirm must render its error inside the card.
const deathBenefitOption = (overrides = {}) => ({
  key: "death_benefit-harvest",
  mechanic: "death_benefit",
  recordId: null,
  origin: "harvest",
  state: "pending",
  rendering: live.death_benefit.rendering,
  math: live.death_benefit.math,
  timingNote: null,
  evidence: {
    filename: "ICC18 P18PRUL.pdf",
    page: 4,
    snippet: "Death Benefit is the greater of",
  },
  provenanceClass: "from_filing",
  provenanceLabel: "From the filing",
  ...overrides,
});
check("death-benefit single-option card (harvest, no record): direct confirm renders", () => {
  const html = renderOptionCard({
    option: deathBenefitOption(),
    singleOption: true,
  });
  expectTokens(html, ["Confirm — put this reading in effect", "From the filing"]);
  expectAbsent(html, ['type="radio"']);
});
check("blocked single-option card: the reason shows, no dead confirm button", () => {
  const html = renderOptionCard({
    option: deathBenefitOption({
      confirmBlockedReason:
        "The holistic review reconciled this reading against the reading that stands; it stays in the record but is not offered for approval.",
    }),
    singleOption: true,
  });
  expectTokens(html, ["reconciled this reading against the reading that stands"]);
  expectAbsent(html, ["Confirm — put this reading in effect", "Confirm — use this reading instead"]);
});
// The NAR coupling (Oct 29, 2026): the filed NAR definition arrived
// as a harvest candidate with NO saved record — the exact shape the
// factor-table coupling used to block with a note claiming the
// table set the definition.  The server no longer stamps that
// reason (the definition has its own equation proposal), so the
// card renders its working direct Confirm and the note is absent.
check("filed NAR definition card (harvest, no record): working confirm, no table-coupling note", () => {
  const html = renderOptionCard({
    option: narOption({ recordId: null }),
    singleOption: true,
  });
  expectTokens(html, ["Confirm — put this reading in effect", "Filed definition"]);
  expectAbsent(html, [
    "set by the NAR factor table",
    "Change the net amount at risk definition",
    'type="radio"',
  ]);
});
check("option card with a failed confirm: the error renders inside the card", () => {
  const html = renderOptionCard({
    option: deathBenefitOption(),
    singleOption: true,
    error: "This reading has no saved record to approve yet — nothing was applied.",
  });
  expectTokens(html, [
    "This reading has no saved record to approve yet — nothing was applied.",
    'class="error"',
  ]);
});

// --- Proposal cards in the steps (Oct 28, 2026) -------------------
// The radio rule covers the proposals too: a one-slice table
// proposal shows its summary with Confirm and apply / Dismiss and
// no radio; a genuine conflict gives each version its own confirm
// path (independent alternatives, never an exclusive radio group).
const sliceOption = (overrides = {}) => ({
  candidateId: "cand-1",
  filename: "ICC18 S18PRUL.pdf",
  page: 6,
  sources: [{ filename: "ICC18 S18PRUL.pdf", page: 6 }],
  rowCount: 121,
  valueBasis: "guaranteed_maximum",
  coverageText: "121 rows across durations 1–121",
  selectors: { tobacco_status: ["Non-Tobacco"] },
  inForce: false,
  confirmBack:
    "COI schedule: was nothing in force; now the filed table of 121 rows from ICC18 S18PRUL.pdf, p. 6, accepted on your confirmation. It adds its coverage to the table in force — versions already accepted stay in force.",
  evidence: { filename: "ICC18 S18PRUL.pdf", page: 6, snippet: "Monthly COI rates" },
  ...overrides,
});
const renderProposalCard = (proposal) =>
  renderToString(
    React.createElement(ProposalCard, {
      proposal,
      busy: false,
      onConfirm: noop,
      onDismiss: noop,
    }),
  );
check("one-slice table proposal: summary and direct confirm, no radio", () => {
  const option = sliceOption();
  const html = renderProposalCard({
    id: "prop-1",
    kind: "filed_table_choice",
    slot: "coi",
    mechanic: "coi",
    label: "Accept the filed COI schedule table from ICC18 S18PRUL.pdf (p. 6)",
    confirmBack: option.confirmBack,
    candidateId: "cand-1",
    options: [option],
    optionDiffs: [],
    evidence: option.evidence,
  });
  expectTokens(html, [
    "Accept the filed COI schedule table",
    "Confirm and apply",
    "Dismiss",
    "adds its coverage to the table in force",
  ]);
  expectAbsent(html, ['type="radio"']);
});
// --- The unified table+equation act (Oct 29, 2026) ----------------
// A transcription mechanic's slice card shows the equation the
// acceptance carries — typeset, BEFORE confirmation — and the one
// button names both halves of the act.  A later slice shows the
// equation as already in effect and its button goes back to plain
// coverage wording.  A table that carries no equation (the NAR
// factor table) shows no equation block and no unified wording.
const coiPreview = (state) => ({
  mechanic: "coi_charge",
  label: "COI charge",
  state,
  rendering: live.coi_charge.rendering,
  math: live.coi_charge.math,
  timingNote: "The COI charge is deducted at the beginning of each month, before interest is credited.",
});
check("coi slice card: typeset equation preview + unified confirm, pre-acceptance", () => {
  const option = sliceOption({
    confirmBack:
      "COI schedule: nothing was in force before; now the filed table of 121 rows from ICC18 S18PRUL.pdf, p. 6, accepted on your confirmation. It adds its coverage to the table in force — versions already accepted stay in force. Confirming also puts the COI charge equation in effect — the equation this table carries, shown on this card.",
    equationPreviews: [coiPreview("will_put_in_effect")],
  });
  const html = renderProposalCard({
    id: "prop-4",
    kind: "filed_table_choice",
    slot: "coi",
    mechanic: "coi",
    label: "Accept the filed COI schedule table from ICC18 S18PRUL.pdf (p. 6)",
    confirmBack: option.confirmBack,
    candidateId: "cand-1",
    options: [option],
    optionDiffs: [],
    evidence: option.evidence,
  });
  expectTokens(html, [
    "Accept this table and its equation",
    "the equation this table carries; confirming puts it in effect",
    "equation-math",
    "puts the COI charge equation in effect",
  ]);
  expectAbsent(html, ["Confirm and apply", 'type="radio"']);
});
check("later coi slice card: equation shown as already in effect, plain confirm", () => {
  const option = sliceOption({
    candidateId: "cand-2",
    filename: "ICC18 S18PRUL Nicotine.pdf",
    equationPreviews: [coiPreview("already_in_effect")],
  });
  const html = renderProposalCard({
    id: "prop-5",
    kind: "filed_table_choice",
    slot: "coi",
    mechanic: "coi",
    label: "Accept the filed COI schedule table from ICC18 S18PRUL Nicotine.pdf (p. 4)",
    confirmBack: option.confirmBack,
    candidateId: "cand-2",
    options: [option],
    optionDiffs: [],
    evidence: option.evidence,
  });
  expectTokens(html, [
    "the equation this table carries, already in effect",
    "Confirm and apply",
  ]);
  expectAbsent(html, ["Accept this table and its equation"]);
});
check("nar factor slice card: no equation block, no unified wording", () => {
  const option = sliceOption({
    candidateId: "cand-3",
    filename: "ICC18 S18PRUL Nicotine.pdf",
    page: 2,
    rowCount: 1,
    coverageText: "1 row",
    selectors: {},
    confirmBack:
      "Net amount at risk (NAR) factor: nothing was in force before; now the filed table of 1 rows from ICC18 S18PRUL Nicotine.pdf, p. 2, accepted on your confirmation. It adds its coverage to the table in force — versions already accepted stay in force.",
    evidence: { filename: "ICC18 S18PRUL Nicotine.pdf", page: 2, snippet: "Net Amount at Risk Factor" },
  });
  const html = renderProposalCard({
    id: "prop-6",
    kind: "filed_table_choice",
    slot: "nar",
    mechanic: "nar_factors",
    label: "Accept the filed net amount at risk (nar) factor table from ICC18 S18PRUL Nicotine.pdf (p. 2)",
    confirmBack: option.confirmBack,
    candidateId: "cand-3",
    options: [option],
    optionDiffs: [],
    evidence: option.evidence,
  });
  expectTokens(html, ["Confirm and apply", "Dismiss"]);
  expectAbsent(html, [
    "equation-math",
    "Accept this table and its equation",
    "the equation this table carries",
  ]);
});
check("conflict proposal: each version has its own confirm, no radio", () => {
  const incumbent = sliceOption({
    candidateId: "cand-0",
    inForce: true,
    confirmBack:
      "COI schedule: keep the filed table from ICC18 S18PRUL.pdf as the version that governs the 21 row(s) where the two filings disagree.",
  });
  const challenger = sliceOption({
    candidateId: "cand-2",
    filename: "ICC18 S18PRUL Nicotine.pdf",
    confirmBack:
      "COI schedule: accept the filed table of 121 rows from ICC18 S18PRUL Nicotine.pdf; where its rows disagree with the table in force (21 row(s)), this version's rows govern.",
  });
  const html = renderProposalCard({
    id: "prop-2",
    kind: "filed_table_choice",
    slot: "coi",
    mechanic: "coi",
    label: "Conflicting filed COI schedule tables — choose which governs the 21 row(s) where they disagree",
    confirmBack: "COI schedule: two filed versions disagree on 21 row(s).",
    candidateId: null,
    options: [incumbent, challenger],
    optionDiffs: [
      {
        candidateId: "cand-2",
        comparedTo: "cand-0",
        identicalRows: 100,
        differingRows: 21,
        onlyInFirst: 0,
        onlyInOption: 0,
      },
    ],
    conflict: {
      candidateId: "cand-2",
      incumbentCandidateIds: ["cand-0"],
      differingRows: 21,
    },
    evidence: challenger.evidence,
  });
  expectTokens(html, [
    "Confirm — keep this version in force",
    "Confirm and apply",
    "rows differ in value",
    "currently in force",
  ]);
  expectAbsent(html, ['type="radio"']);
});
check("plain filed-table proposal: confirm and dismiss, no radio", () => {
  const html = renderProposalCard({
    id: "prop-3",
    kind: "filed_table",
    slot: "fees",
    mechanic: "policy_fees",
    label: "Accept the filed policy fees table from ICC18 P18PRUL.pdf (p. 2)",
    confirmBack: "Policy fees: was nothing in force; now the filed table, accepted on your confirmation.",
    candidateId: "cand-9",
    evidence: { filename: "ICC18 P18PRUL.pdf", page: 2, snippet: "Administrative Charge" },
  });
  expectTokens(html, ["Confirm and apply", "Dismiss", "Policy fees: was nothing in force"]);
  expectAbsent(html, ['type="radio"']);
});
check("equation proposal card: typeset with confirm, no radio", () => {
  const rec = live.premium_load;
  const html = renderProposalCard({
    id: "prop-4",
    kind: "equation",
    slot: "fees",
    mechanic: "premium_load",
    equationMechanic: "premium_load",
    label: "Approve the premium load equation from the filing",
    confirmBack: "Premium load: was nothing in force; now the harvested reading, approved on your confirmation.",
    rendering: rec.rendering,
    math: rec.math,
    timingNote: rec.timingNote,
    evidence: { filename: "ICC18 P18PRUL Promise UL Actuarial Memo V3.pdf", page: 2, snippet: "premium expense" },
  });
  expectTokens(html, ["equation-math", "Confirm and apply", "Dismiss"]);
  expectAbsent(html, ['type="radio"']);
});

// --- The feed is folded into the steps (Oct 28, 2026) -------------
// Source-structure checks (the panel fetches its payload, so its
// composition cannot render to string): no "Suggested from the
// filing" surface remains; the bulk block and the holistic-review
// preamble render in the structure header, before the steps; the
// proposal cards render inside the step containers and the
// also-found group.
check("no Suggested from the filing feed remains", () => {
  expectAbsent(panelSource, ['id="extraction-proposals"', "<h3>Suggested from the filing</h3>"]);
});
check("bulk block and review preamble render in the structure header", () => {
  const headerAt = panelSource.indexOf("<h3>Product structure</h3>");
  const preambleAt = panelSource.indexOf(
    "Holistic review ran before these were offered",
    headerAt,
  );
  const bulkAt = panelSource.indexOf("Approve all uncontested", headerAt);
  const stepsAt = panelSource.indexOf("panel.structure.steps.map", headerAt);
  if (!(headerAt >= 0 && preambleAt > headerAt && bulkAt > headerAt && stepsAt > bulkAt)) {
    throw new Error("bulk block / review preamble are not in the structure header before the steps");
  }
});
check("proposal cards render inside steps and the also-found group", () => {
  expectTokens(panelSource, [
    "tableProposalsForStep(step).map",
    "leftoverEquationProposals(step).map",
    'groupedProposals.get("__also_found")',
  ]);
  const cardUses = panelSource.split("<ProposalCard").length - 1;
  if (cardUses < 3) {
    throw new Error(`expected ProposalCard in steps and also-found, found ${cardUses}`);
  }
});

// --- Option cards stack at phone widths ---------------------------
// The SSR harness cannot evaluate media queries, so this pins the
// stylesheet rule itself: inside the narrow-width block, the
// structure option card becomes a single column.
check("styles stack structure option cards at narrow widths", () => {
  const blocks = [...stylesSource.matchAll(/@media \(max-width: 640px\)/g)].map(
    (m) => stylesSource.slice(m.index, m.index + 900),
  );
  const stacked = blocks.some(
    (block) => block.includes(".structure-option") && block.includes("flex-direction: column"),
  );
  if (!stacked) {
    throw new Error("no narrow-width media block stacks .structure-option into a column");
  }
});

// --- The Ledger definitions summary (declutter, Oct 28, 2026) ----
// Billy, after accepting everything and running a projection: the
// Ledger still carried "some duplication and potentially unnecessary
// extra information" — all seven in-effect definitions rendered as
// one run-on prose paragraph (the policy-fees entry alone ~80 words
// of nested conditionals), plus a "Filed classification matched" box
// restating the scenario inputs directly above it.  The summary is
// now one compact row per settled step — step, the reading's short
// name, its provenance class — fed by the run record's
// definitionsUsed stamp; the stamp's entries still CARRY the prose
// rendering (record data), and the Ledger must never render it.
// Rates in force keeps its typeset "Equation in force" blocks: that
// is the audit view, not duplication.
const ledgerBundlePath = join(buildDir, "ProjectionLedger.cjs");
buildSync({
  entryPoints: [join(webDir, "ProjectionLedger.tsx")],
  bundle: true,
  platform: "node",
  format: "cjs",
  external: ["react", "react-dom", "react-dom/server"],
  outfile: ledgerBundlePath,
  logLevel: "silent",
});
const { ProjectionLedger } = require(ledgerBundlePath);
const logicBundlePath = join(buildDir, "ProjectionLogicPage.cjs");
buildSync({
  entryPoints: [join(webDir, "ProjectionLogicPage.tsx")],
  bundle: true,
  platform: "node",
  format: "cjs",
  external: ["react", "react-dom", "react-dom/server"],
  outfile: logicBundlePath,
  logLevel: "silent",
});
const { ProjectionResultsSection } = require(logicBundlePath);
const logicSource = readFileSync(join(webDir, "ProjectionLogicPage.tsx"), "utf8");
const ledgerSource = readFileSync(join(webDir, "ProjectionLedger.tsx"), "utf8");
const workspacePageSource = readFileSync(
  join(webDir, "ProductWorkspacePage.tsx"),
  "utf8",
);

// The settled state of the canonical Promise UL run with the FILED
// NAR definition chosen — the shape the live gate reproduces.  Each
// entry carries its full prose `rendering` from the live fixture,
// exactly as the run record ships it.
const definitionsFixture = [
  { stepId: "premium", stepLabel: "Premium & loads", mechanic: "premium_load", equationLabel: "Premium load", provenanceClass: "from_filing", provenanceLabel: "From the filing" },
  { stepId: "fees", stepLabel: "Policy fees", mechanic: "policy_fees", equationLabel: "Policy and admin fees", provenanceClass: "from_filing", provenanceLabel: "From the filing" },
  { stepId: "crediting", stepLabel: "Interest crediting", mechanic: "crediting", equationLabel: "Interest crediting", provenanceClass: "from_filing", provenanceLabel: "From the filing" },
  { stepId: "death_benefit", stepLabel: "Death benefit & corridor", mechanic: "death_benefit", equationLabel: "Death benefit", provenanceClass: "derived", provenanceLabel: "Derived" },
  { stepId: "nar", stepLabel: "Net amount at risk", mechanic: "nar_definition", equationLabel: "Net amount at risk definition", provenanceClass: "filed_definition", provenanceLabel: "Filed definition" },
  { stepId: "coi", stepLabel: "COI charges", mechanic: "coi_charge", equationLabel: "COI charge", provenanceClass: "derived", provenanceLabel: "Derived" },
  { stepId: "surrender", stepLabel: "Surrender & exit", mechanic: "surrender_charge", equationLabel: "Surrender charge", provenanceClass: "derived", provenanceLabel: "Derived" },
].map((entry) => ({ ...entry, rendering: live[entry.mechanic].rendering }));

const ledgerRowFixture = {
  year: 1, attainedAge: 45, beginningValue: 0, premium: 3000,
  premiumLoad: 300, policyFee: 90, coiCharge: 120, interestCredited: 45,
  endingValue: 2535, surrenderCharge: 0, surrenderValue: 2535,
  deathBenefit: 100000, netAmountAtRisk: 97465, components: null,
};
const rateTablesFixture = {
  coi: {
    status: "filed", rowCount: 1,
    rows: [{ duration: 1, attained_age: 45, sex: "M", risk_class: "Standard", tobacco_status: "Tobacco", rate: 0.1468, rate_unit: "per_1000_monthly" }],
    equation: { math: live.coi_charge.math, rendering: live.coi_charge.rendering, timingNote: live.coi_charge.timingNote, approvedBy: "workspace_user" },
  },
  surrender: {
    status: "filed", rowCount: 1,
    rows: [{ duration: 1, charge: 17.9413, charge_unit: "per_1000_face" }],
    equation: { math: live.surrender_charge.math, rendering: live.surrender_charge.rendering, timingNote: null, approvedBy: "workspace_user" },
  },
};
const renderLedger = () =>
  renderToString(
    React.createElement(ProjectionLedger, {
      ledger: { rows: [ledgerRowFixture] },
      rateTables: rateTablesFixture,
      fallbackRows: [],
      definitionsUsed: definitionsFixture,
    }),
  );

check("ledger definitions summary: one compact row per settled step", () => {
  const html = renderLedger();
  const rows = html.split("projection-definitions-summary__row").length - 1;
  if (rows !== 7) {
    throw new Error(`expected 7 summary rows, found ${rows}`);
  }
  expectTokens(html, [
    "Definitions in effect",
    "Premium &amp; loads", "Policy fees", "Interest crediting",
    "Death benefit &amp; corridor", "Net amount at risk",
    "Net amount at risk definition", "Filed definition",
    "From the filing", "Derived", "Surrender &amp; exit",
  ]);
});
check("ledger definitions summary: the formula prose never renders", () => {
  const html = renderLedger();
  expectAbsent(html, [
    // The policy-fees prose wall (~80 words of nested conditionals).
    "the sum over the fee schedule rows in force of",
    "whether a premium is due this month",
    "excluding rows matching",
    // The other definitions' prose bodies.
    "the greater of (the death benefit / the NAR factor",
    "the corridor table percentage for this duration",
    "the fee schedule amount for this duration and attained age (fee unit: percent_premium)",
    // The old one-line wall's joined form.
    "Definitions in effect —",
  ]);
});
check("rates in force keeps its typeset Equation in force blocks", () => {
  const html = renderLedger();
  expectTokens(html, ["Rates in force", "Equation in force:", "equation-math"]);
});
check("results section: no Filed classification matched box", () => {
  const row = { year: 1, attainedAge: 45, cashValue: 100, surrenderValue: 90, openingPolicyValue: 0, annualPremium: 3000 };
  const ws = {
    illustration: {
      ledger: null, rateTables: null, definitionsUsed: definitionsFixture,
      selectorIntegrity: { passed: true, scenario: { sex: "M", riskClass: "Standard", tobaccoStatus: "Tobacco" } },
    },
    rows: [row],
    metrics: { maximumYear: 30, finalCashValue: 100, finalSurrenderValue: 90, finalNetAmountAtRisk: 50 },
    reconciliation: { passed: true, checkCount: 90, maxResidual: 0, failures: [], failedYears: [] },
    downloadProjectionCsv: () => {},
  };
  const html = renderToString(React.createElement(ProjectionResultsSection, { ws }));
  expectAbsent(html, ["Filed classification matched"]);
  // The decluttered summary is wired through this section too.
  expectTokens(html, ["Definitions in effect", "Filed definition"]);
});
check("results section: Projection ledger reconciled still renders", () => {
  expectTokens(logicSource, ["Projection ledger reconciled"]);
});
check("the frontend no longer consumes the definitions prose line", () => {
  expectAbsent(ledgerSource + logicSource + workspacePageSource, ["definitionsLine"]);
});

rmSync(buildDir, { recursive: true, force: true });
if (failures > 0) {
  console.log(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log("\nAll EquationMath contract checks passed");
