# Equations consolidation (Oct 27, 2026)

Billy, working a fresh Promise UL workspace end to end, found the
Inputs & Equations tab presenting the same equations three ways —
and two outright defects. This change consolidates the presentation
and fixes the defects; no server semantics changed.

## What was wrong

1. **Suggested equations rendered as prose.** An equation proposal
   in "Suggested from the filing" showed only its prose rendering,
   while the same equation in force rendered typeset. A person was
   asked to approve math they could not see in the form it would
   run in.
2. **The same in-force equation appeared twice.** "Product inputs"
   carried a compact "Equations in force" block re-rendering the
   approved math, and the "Equations" section below rendered the
   same records again as full cards (typeset + timing + "In words"
   + provenance + Reads + Edit).
3. **The stale chip never cleared on screen.** The server clears
   `projectionStale` when a projection saves, but the Ledger page's
   run handler never refreshed the workspace meta the chip reads —
   "Saved projection is stale" sat beside the green "Projection
   complete" banner until a reload.
4. **Changelog grammar.** Confirm-backs read "was nothing is in
   force; now …" for an empty before-state.

## The consolidation

- **Proposals are typeset.** Equation proposals now carry `math`
  (the same `render_math_tree` output the in-force record views
  use, built server-side from the candidate body) and `timingNote`,
  and the proposal card renders them through `EquationDisplay` —
  math, timing line, "In words" caption — exactly like an in-force
  card, with Confirm and apply / Dismiss on the card. Table
  proposals keep their card form.
- **One presentation.** The compact "Equations in force" block in
  Product inputs no longer re-renders math: it is a one-line status
  per mechanic (approved / not calculated, plus a conflict note).
  In-force equations render only as the Equations section's full
  cards.
- **Stale clears on run.** `useProjectionWorkspace` accepts an
  `onProjectionSaved` callback; the workbench passes its existing
  `reload()` (the same refresh path as every other bench mutation),
  so the header banner and run-state chip clear the moment a
  projection run completes.
- **Plain before-clauses.** The empty-before case in proposal and
  correction confirm-backs now reads "nothing was in force before"
  (corrections: "no surrender schedule was in force before — no
  surrender charge was calculated"). The was/now information is
  unchanged.

## Filing-review reconciliation (same evening, Billy's addition)

The header's filing-review counts are the last analysis's frozen
snapshot — by design — but read as current status: requirements the
analysis counted missing can come into force minutes later. The
snapshot does not change; instead, `GET /api/workspaces/{id}` now
carries `workspace.filingReviewReconciliation`, computed live
against the current artifact by
`workspace_mechanics_panel.filing_review_reconciliation`:

- requirements the analysis counted missing/partial whose slot is
  now in force (filed table usable **and** its equation approved),
  named — e.g. "3 missing at analysis — now in force: COI rate
  table, Surrender charge schedule, Policy / admin fees";
- snapshot gaps whose subject is now resolved by the same test
  (the `missing_coi_equation` gap needs the COI equation approved
  and its table in force).

The header appends the clause when — and only when — something has
actually come into force since the analysis.

## Tests

- `src/actuarypoc/tests/test_equations_consolidation.py` — proposal
  math/timing presence (pending-record and harvest paths), plain
  before-clause wording (table + equation proposals), and the
  reconciliation (all resolved / nothing changed / partial progress
  / table-without-equation does not reconcile / payload wiring).
- `web/tests/equation-math.render.test.mjs` — proposal-shaped
  payloads render typeset with the "In words" caption and Timing
  line; a null-math proposal degrades to prose.
