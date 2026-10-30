# Phase 7 — The Equation Doctrine

Phase 7 of the Eddy improvement plan. It supersedes the Phase 4
rule-bank framing (`docs/rule-bank.md`) and re-founds the projection
engine on one rule, stated by Billy (Oct 25, 2026) and treated here as
doctrine, not preference:

> The rule bank disappears. I don't want there to be any question
> whether our software is running the way we think or if it is some
> safety net.

## The doctrine

1. **The only equations that execute are (a) document-derived and
   human-approved in the product, or actuary-authored in the product,
   and (b) equations in code only where they are always used and
   assumed to be used in the documents.** The test for any code
   candidate: *could a document state this differently?* If yes, it is
   not code — it belongs to the document pipeline (harvest → approve →
   execute). Net-amount-at-risk definitions are the archetype of "not
   code": filings state them factor-adjusted and unadjusted.
2. **A mechanic with no approved equation does not calculate.** The
   product states the absence plainly (a missing state naming the
   mechanic and the resolution path). There are no placeholder
   calculations, no automatic fallbacks, no safety-net math. The flat
   placeholder COI, the simplified surrender pattern, and the
   configured-fee fallback are **deleted**, not relabelled.
3. **Every executed equation has a source and an approver.** The
   ledger derivation for a charge *is* the approved equation that
   produced it — its canonical rendering, its source page, its
   approver. Nothing engages automatically.
4. **Synthetic schedules remain data**: explicit, human-invoked,
   accepted, labelled. They never engage automatically, so they are
   not a safety net. An equation may read a synthetic table exactly as
   it reads a filed one; the table's provenance travels with it.

## The formula language

Equations are stored as structured JSON (an AST). There is **no
`eval`, no expression strings, no generated code** — a model or an
actuary proposes a tree of the nodes below, the validator rejects
anything outside the grammar, and the evaluator is a small
deterministic interpreter (`src/actuarypoc/domain/equations.py`).

### Nodes

| Node | Shape | Meaning |
| --- | --- | --- |
| constant | `{"const": 12}` | a number |
| string | `{"str": "annual_fixed"}` | a string (row-unit comparisons only) |
| quantity | `{"qty": "account_value"}` | a chassis quantity (below) |
| arithmetic | `{"add": [a, b, …]}`, `{"sub": [a, b]}`, `{"mul": […]}`, `{"div": [a, b]}`, `{"neg": a}`, `{"pow": [a, b]}` | numeric |
| bounds | `{"min": […]}`, `{"max": […]}` | numeric |
| conditional | `{"if": {"cond": c, "then": a, "else": b}}` | |
| condition | `{"cmp": ["<=", a, b]}`, `{"and": […]}`, `{"or": […]}`, `{"not": c}` | comparisons over numbers (and `==`/`!=` over strings) |
| bands | `{"bands": [{"from": 1, "to": 10, "value": e}, …]}` | piecewise by policy duration; `to: null` = open-ended; bands must be sorted and non-overlapping |
| table lookup | `{"lookup": {"table": "coi", "field": "rate", "where": {...}, "default": e}}` | the value of `field` from the row of the workspace's accepted table selected for the current context; `where` adds equality filters on row fields (e.g. a fee component); `default` is evaluated when no row matches — without it, a miss makes the mechanic unevaluable for that period |
| row sum | `{"rows_sum": {"table": "fees", "where": {...}, "exclude_where": {...}, "expr": e}}` | sum of `expr` over every selected row of the table; inside `expr`, `row_amount` is the row's value field and `row_unit` its unit string |

Tables a lookup may name, and their value fields: `coi` → `rate`,
`surrender` → `charge`, `fees` → `amount`, `nar_factors` → `factor`,
`corridor` → `percentage`. Row selection is the engine's existing
contract (most specific matching row on duration / attained age /
sex / risk class / tobacco / issue age / premium mode) — addressing
data, stated once here, rendered into every lookup's plain-language
form ("the COI table rate for this duration and attained age").

### Quantities

Every context carries: `duration` (policy year), `month_in_year`,
`attained_age`, `issue_age`, `face_amount`, `premium_due` (this
month's gross premium; 0 in months no premium is due), `payment_due`
(1/0), `guaranteed_rate` (the scenario/product input — an assumption
value, never a formula).

Per mechanic, additionally:

- `coi_charge` (monthly): `account_value` (value at the evaluation
  point fixed by the skeleton and the equation's timing attribute),
  `death_benefit` (the approved death-benefit equation evaluated at
  that value), `nar` (the approved NAR equation evaluated there).
- `nar_definition`: `death_benefit`, `account_value` → returns NAR.
- `death_benefit`: `face_amount`, `account_value` → returns the death
  benefit.
- `crediting` (monthly): `account_value` = the interest base at the
  crediting point; the equation returns the interest **amount** (e.g.
  `account_value × ((1 + guaranteed_rate)^(1/12) − 1)` — the
  annual→monthly conversion is stated by the equation, never hidden).
- `premium_load` (monthly): `premium_due` (so a load expressed as a
  percentage of premium is naturally 0 in non-payment months).
- `policy_fees` (monthly): `account_value`, plus row context inside
  `rows_sum`.
- `surrender_charge` (annual, at year end): `account_value` = ending
  account value, `face_amount`, `duration`, `attained_age`.

### Timing attribute

`coi_charge` records carry a `timing` attribute —
`beginning | middle | end` — because filings state *when* the COI is
deducted as part of the COI calculation itself. The attribute selects
the skeleton's within-month arrangement (see Universal equations);
it is part of the approved artifact, shown at approval, and cited by
the ledger. No approved COI equation → no COI at all, timing included.

### Validation (at approval/authoring time, never first at run time)

An equation is rejected, with a specific message, when: a node is
outside the grammar; a quantity is unknown *for that mechanic's
context*; a lookup names an unknown table/field or a field the table
does not carry; arithmetic is applied to a string; bands overlap or
are unsorted; a `rows_sum` references row quantities outside its
`expr`. Division by zero and lookup misses *at run time* make the
mechanic unevaluable for that period: it contributes nothing, and the
run is flagged incomplete naming the mechanic and the reason.

### Canonical rendering

Every equation has exactly one plain-language rendering, derived
deterministically from the AST (`render_equation`). This rendering —
not the JSON — is what the approval screen shows beside the filing's
verbatim words, and what the ledger cites. Example:
`max(death_benefit / lookup(nar_factors.factor, default 1) − account_value, 0)`
renders as "the greater of (the death benefit / the NAR factor table
factor for this duration (1 if no factor applies) − the account
value) and 0".

## Equation artifacts

Stored on the workspace's mechanics artifact under `equations` (a list
of records), so every existing consumer of the artifact sees them.

```json
{
  "id": "eq-…", "mechanic": "coi_charge", "version": 1,
  "state": "pending | approved | rejected | superseded | unmapped",
  "timing": "beginning | middle | end | null",
  "body": { "…AST…" },
  "rendering": "canonical plain-language form, derived from body",
  "source": {
    "kind": "document | actuary | correction | proposal | specimen | pre_doctrine_migration",
    "statement": "verbatim filing text (document kind)",
    "filename": "…", "page": 12,
    "harvesterModel": "…", "harvestedAt": "…"
  },
  "approval": {"by": "…", "at": "…"},
  "conflict": {"withEquationId": "…", "note": "…"} ,
  "createdAt": "…", "updatedAt": "…"
}
```

Rules:

- At most one `approved` record per mechanic — the one in force.
  Approving a record supersedes the previous in-force record (kept,
  state `superseded`, never deleted: the audit trail is the product).
- `unmapped` records carry a verbatim statement and **no body**: a
  stated calculation the harvester could not structure confidently.
  It is surfaced as a conflict, never dropped, never auto-approved;
  an actuary resolves it by authoring the equation (PUT) or rejecting
  the record.
- A harvested record whose rendering differs from the in-force
  record for the same mechanic is flagged `conflict` against it.
  Neither silently wins; the in-force equation keeps executing until
  a human approves the challenger.

## Harvesting

`POST /api/workspaces/{id}/equations/harvest` runs harvesting over the
workspace's Phase 0 document slices:

1. **Deterministic assists first** — the conservative prose patterns
   the Phase 4 proposals already proved (COI timing phrases, NAR
   "death benefit minus account value" phrasing, graded surrender
   percentages with *both* numbers present in the text). A pattern
   that cannot see every number it needs does not fire.
2. **The configured model** (`EQUATION_HARVEST_MODEL`, falling back to
   `MECHANICS_EXTRACT_MODEL` / `ASSUMPTION_EXTRACT_MODEL`) then reads
   the calculation-bearing slices and proposes structured readings in
   the AST grammar, each with the verbatim statement and page. The
   server validates every proposal against the grammar; an invalid or
   low-confidence reading becomes an `unmapped` conflict record with
   the verbatim statement preserved.
3. Harvesting **never approves**. New records land `pending` (or
   `unmapped`); re-harvesting refreshes pending records for the same
   statement and never touches approved/rejected ones.

## API contract

Mirrors the proposals/corrections shapes; the actuary workbench UI
consumes exactly this.

- `GET /api/workspaces/{id}/equations` — every record grouped by
  mechanic, with state, the in-force record per mechanic, and
  conflicts.
- `GET /api/workspaces/{id}/equations/{mechanic}` — one mechanic's
  records (in-force first, then history).
- `POST /api/workspaces/{id}/equations/{mechanic}/approve`
  `{equationId, confirmed: true}` — 400 `confirmation_required`
  (with the rendering as confirm-back) unless `confirmed` is true;
  validates the body first (400 with the specific defect); approving
  supersedes the in-force record.
- `POST /api/workspaces/{id}/equations/{mechanic}/reject`
  `{equationId}` — marks the record rejected; an in-force record
  cannot be rejected (supersede it instead) → 400.
- `PUT /api/workspaces/{id}/equations/{mechanic}`
  `{body, timing?, confirmed: true, statement?}` — actuary-authored
  or edited equation. Since Oct 29, 2026 the registry's authoring
  door saves a **pending draft** with actuary provenance — it never
  puts anything in force; the draft appears as a reading option in
  the mechanic's product-structure step, and only confirming it
  there (the approve route, driven by the step) puts it in force.
  Without `confirmed: true` it returns the rendering as a
  confirm-back preview and writes nothing. (Corrections and
  confirmed proposals still author straight into force through the
  domain `author_equation` — their door is the structure surface.)
- `POST /api/workspaces/{id}/equations/harvest` — run/refresh
  harvesting; returns the records created/refreshed.

Every mutation appends a mechanics change record. Mutations that
change what executes (approvals, rejections, corrections) also mark
the projection stale; saving a draft does not — nothing that runs
has changed.

## Execution

The monthly loop evaluates approved equations; it contains no
per-unit formula branches and no bank dispatch.

- Each mechanic computes **only** from its in-force equation. Missing
  or unevaluable → contributes nothing, and the projection carries
  `incomplete: true` with `missingMechanics: [{mechanic, reason}]`
  (also stored on the snapshot). A lookup that misses in some years
  flags those years on the row's applied-mechanics record.
- `appliedMechanics` per row cites the equation that ran:
  `{equationId, mechanic, version, rendering, sourcePage,
  sourceFilename, approvedBy, approvedAt, sourceKind}` per mechanic.
- The ledger builds derivations from those citations: the formula
  printed is the approved equation's rendering; the basis derives
  from the equation's source kind (`document` → filed, `correction` →
  corrected, `actuary`/`specimen`/`pre_doctrine_migration` →
  approved-equation labels). A missing mechanic's ledger component
  states the absence and the resolution path.
- Validation packs record `appliedEquations`
  (`{id, mechanic, version, approvedBy}`) per run and per case,
  replacing the switch fingerprint; the mechanics fingerprint now
  covers the equations in force. Runs written before Phase 7 keep
  their `switchesUsed` and remain readable; the text report prints
  applied equations when present, else the legacy switch line.

## Universal equations (in code) — each justified under the test

*Could a document state this differently? If yes, it is not here.*

1. **The roll-forward identity** — ending value = beginning value +
   premium − premium load − policy fees − COI + interest credited.
   Definitional: an account value *is* this accumulation. Filings
   state the charges and credits; none states a different arithmetic
   for what a balance means.
2. **The within-month sequencing skeleton** — premiums land on their
   scheduled dates (scenario structure); deductions and crediting
   apply in the order the approved COI equation's timing attribute
   states; the balance is floored at zero after deductions (charges
   cannot make a balance negative — definitional, and filings state
   charges, never balance flooring).
3. **Surrender value = max(account value − surrender charge, 0)** —
   definitional: the amount payable on surrender, floored at zero.
4. **Modal premium arithmetic** — annual premium = modal premium ×
   payments per year under the selected mode. Scenario-input
   arithmetic (the mode is the user's scenario choice), already
   disclosed as such on the logic graph.
5. **Bookkeeping identities** — cumulative premium is the sum of
   premiums paid; reported year values are the skeleton's own
   accumulations.
6. **Table row selection** — the lookup addressing contract above.
   It is how data is addressed, not an equation; it is stated in the
   language spec and rendered into every lookup's plain-language form.

Explicitly **not** universal (document pipeline, harvested/approved):
the NAR definition; COI timing; how a COI rate applies (per-$1,000 vs
% of NAR, annual→monthly division); the surrender basis and grading;
fee amount conversions (annual→monthly, per-$1,000); the crediting
conversion; the corridor/death-benefit shape. The guaranteed *rate*
is an input assumption; its conversion is an equation.

Judgment calls recorded: (a) COI timing is an attribute of the
`coi_charge` artifact rather than its own mechanic — filings state it
inside the COI calculation; (b) lookup row selection stays a language
contract (item 6) rather than per-equation data; (c) the scenario
`policyFeeAnnual` request value no longer feeds any calculation —
with the configured-fee fallback deleted, a fee enters only through
an approved `policy_fees` equation (the value remains visible as an
unapplied scenario input).

## Migration and retirement

- `domain/rule_bank.py` is **deleted**; `docs/rule-bank.md` is marked
  superseded by this document. The engine, ledger, graph, panel,
  corrections, proposals, and packs carry no bank references.
- Placeholder/fallback calculations are deleted: flat COI
  (`coi.placeholder.flat_face`, `coi_rate_flat`), the simplified
  surrender pattern (`surrender.placeholder.*`, `max_surrender_pct`,
  `surrender_period_years`), the configured-fee fallback
  (`fees.fallback.configured_annual`, config `policy_fee_annual`
  feeding math). UI/API fallback disclosures become missing-equation
  states pointing at harvest / approve / enter.
- **Phase 3 corrections** that selected rule variants are re-expressed:
  a rule-shaped correction now creates an equation record through the
  approval machinery (the correction keeps its audit record, its
  confirm-back, and the ledger's `corrected` basis, cited to the
  equation it created). Parameter-only corrections and table edits
  (values, fees) are data and work exactly as before.
- **Phase 4 proposals** that proposed switch settings are re-expressed
  as equation proposals (confirming one creates the equation record
  through the same approval machinery); filed-table proposals are
  unchanged.
- **Pre-doctrine workspaces** (including the canned Promise UL
  specimen, ws-92e574c9): a one-time, persisted, change-logged
  migration materializes equation artifacts from the mechanics state
  already in force — accepted tables (an equation per table unit),
  corrections in force, and the specimen's defaults — each with
  honest provenance ("product specimen — authored for the workspace,
  pre-doctrine" for the specimen; "pre-doctrine workspace state" in
  general) in an approved state, so nothing silently changes and
  nothing stays hidden in code. The migration runs once per artifact
  (at analysis and at first load under Phase 7); the runtime never
  derives anything — it executes artifacts or states their absence.
  Accepted synthetic schedules and filed tables are data and stay.

## Acceptance

- Evaluator correctness per construct (hand-computed) + rejection
  cases at approval time.
- Harvesting on a filing-style fixture that states its COI and
  surrender calculations in prose → pending records with the verbatim
  statement and page; an unstructurable statement → `unmapped`.
- Approval gating: unapproved never executes; unconfirmed approve →
  400; invalid body → 400 with the specific defect.
- Conflict: a stated equation disagreeing with an in-force authored
  one surfaces as a conflict; neither silently wins.
- **No-net proof**: a workspace with no approved COI equation projects
  with **no COI charge** and an explicit incompleteness flag; the old
  flat $1,000-of-face figure is unreachable (no code path emits it).
- End-to-end over HTTP (TestClient): fixture filing → harvest →
  approve COI + surrender → projection whose year-1 COI and surrender
  match a hand recursion of the *stated* equations and whose ledger
  cites them; an actuary edit (PUT) then changes the output
  predictably; reconciliation stays exact throughout.
