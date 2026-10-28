// Contract test for web/EquationMath.tsx against the math-tree
// vocabulary the server actually ships (render_math_tree in
// src/actuarypoc/domain/equations.py).
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
const renderDisplay = (math, extra = {}) =>
  renderToString(
    React.createElement(EquationDisplay, {
      math,
      rendering: extra.rendering ?? "prose rendering",
      timingNote: extra.timingNote ?? null,
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
  const html = renderDisplay(vocab.unknown_node);
  expectTokens(html, ["prose rendering"]);
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
check("proposal-shaped payload renders typeset with In words caption", () => {
  const rec = live.premium_load;
  const html = renderProposal({
    kind: "equation",
    math: rec.math,
    rendering: rec.rendering,
    timingNote: rec.timingNote,
  });
  expectTokens(html, ["equation-math", "premium due this month", "In words:"]);
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

rmSync(buildDir, { recursive: true, force: true });
if (failures > 0) {
  console.log(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log("\nAll EquationMath contract checks passed");
