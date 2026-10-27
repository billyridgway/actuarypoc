# Approve all uncontested + typeset equations — 2026-10-27

Billy approved both features in one breath ("Build both," Oct 27,
11:28 CT): a bulk approval for a workspace's pending suggestions, and
a real typeset display for equations. Both are built under the
equation doctrine, not around it.

## Feature 1 — "Approve all uncontested"

Entry point: the proposals card ("Suggested from the filing") in
Inputs & Equations — an "Approve all uncontested" button above the
individual suggestions.

- **Endpoint** `POST /api/workspaces/{id}/mechanics-panel/approve-all`
  with the same two-step confirm-back discipline as single proposals.
  Unconfirmed → HTTP 400 with
  `{code: "confirmation_required", confirmBack, summary}` and **no
  changes**. Confirmed → applies.
- **Planning** (`plan_bulk_approval` /
  `apply_bulk_approval` in `extract/workspace_mechanics_proposals.py`)
  works from the same proposal list the panel shows:
  - *Eligible*: a filed-table candidate whose rows create no value
    conflict with rows already in force (the existing conflict
    machinery decides); an equation when its mechanic has exactly one
    pending reading and no different in-force equation to replace.
  - *Excluded, named with a reason*: competing pending readings for
    one mechanic (the standing example: a model's wrong policy-fees
    reading beside the correct deterministic one — bulk approval
    never swallows a rival); a pending equation that would replace a
    different in-force equation; a candidate in genuine conflict with
    rows in force; anything the proposal layer itself shapes as a
    choice or conflict.
- **Application** goes through the existing `apply_proposal` path per
  item — no forked apply logic. Each item is re-planned against the
  artifact as earlier items land, so an item that became contested
  mid-batch (its rows now disagree with a table approved seconds
  earlier in the same batch) is skipped and reported, never forced.
  Every applied item is recorded individually in the change history
  with its evidence, stamped with the batch's `batchId` and
  `bulkApproval: true`. Projection staleness is marked once, from the
  applied items' slots.
- The UI shows the summary before confirming: counts by kind, the
  eligible items listed, and the exclusions listed with their reasons.

## Feature 2 — Typeset equation rendering

- **Renderer** `render_math_tree` in `domain/equations.py`: a
  deterministic walk of the same structured formula body the
  evaluator runs, producing a JSON math tree — division as a fraction
  node, multiplication as ×, lookups in function form
  ("COI rate(duration, attained age)") with their `where` conditions
  and filed-defaults, powers, `max`, condition chains as cases,
  comparisons/logic, and the fee `rows_sum` as a summation over the
  fee schedule with the percent-premium exclusion and unit conditions
  as notes/cases branches. Quantities carry display labels ("net
  amount at risk", "account value") so the typeset form reads like
  the prose. **An unknown node shape yields no tree at all** — never a
  blank or a guessed formula.
- **Payloads**: `record_view` (Equations section + panel) and the
  ledger's rate-table citations now carry `math` and `timingNote`
  alongside `rendering`.
- **Display** (`web/EquationMath.tsx`, hand-rolled HTML/CSS — no
  external typesetting dependency, works offline): the equation
  stands alone as its own block; timing is a separate labeled line
  ("Timing: deducted at the beginning of each month, before interest
  is credited"); the prose rendering stays beneath as an
  "In words: …" caption — plain-English fidelity is Eddy's
  requirement, kept deliberately. Fallback: no `math` → the prose
  stands alone, exactly as before.
- **Surfaces**: Equations-in-force cards (panel), the Equations
  section records (pending and in-force), and the ledger's
  "Equation in force" blocks beside the COI and surrender schedules.
  **Decisions**: confirm-back texts stay prose (they are change
  statements, not equation displays); the "Earlier equations" history
  one-liners stay prose (a collapsed audit list, not a display
  surface); pending equation *proposals* in the panel stay prose —
  once approved they render typeset in force, and the Equations
  section's pending records (where the approval decision is made) do
  show the typeset block.

## Tests

`src/actuarypoc/tests/test_bulk_approval_and_math.py` (18 tests):
renderer structure for all seven canonical Promise UL bodies
(fraction/lookup for COI, summation-of-cases for the fee chain,
power-with-fraction-exponent for crediting, max/lookup for NAR and
death benefit), unknown-node fallback, record-view/citation payloads;
the bulk eligibility matrix (clean slices eligible; rival readings
excluded and named; replace-in-force excluded; conflict candidate
excluded); summary-before-apply changes nothing (endpoint-level);
batch-tagged per-item history; a mid-batch conflict proven skipped,
not swallowed; a planted contested set left pending by the confirmed
call. Suite: 350 passed / the same 5 inherited failures; tsc error
set identical to baseline; vite build clean.
