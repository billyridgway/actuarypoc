# Unification revamp — one approval reality

Diagnosis and record of the unification revamp (built overnight
Oct 26–27, 2026, on Billy's "Build the unification revamp"). The spec
was the run-detail assessment of ws-0e4bd9b4's printed run page
(`run-detail-assessment-2026-10-26.md`): one page stated three
different versions of the truth about the same seven mechanics.

## Diagnosis — why the printed page contradicted itself

The page (WorkbenchPage) renders three status systems side by side.
They do not read the same state:

**(a) "Equations in force" — CURRENT.** Rendered by MechanicsPanel
from the `equations` view embedded in the `GET /mechanics-panel`
payload. MechanicsPanel refetches that payload after every action it
takes, so after Billy's approval batch (Oct 27, 01:39–02:29Z) it
showed all seven mechanics approved. Correct.

**(b) The bottom "Equations" section — FROZEN AT MOUNT.**
EquationsPanel fetches `GET /api/workspaces/{id}/equations` exactly
once, in a `useEffect` on mount. The workbench keeps every tab
mounted (hidden with CSS) and provides **no invalidation path**:
MechanicsPanel actions reload only MechanicsPanel's own payload and
the workbench snapshot (`onSnapshotReload` → snapshot only);
EquationsPanel receives no reload signal, no prop change, no focus
refetch. Billy opened the page before approving anything, so the
panel held its pre-approval fetch — "Equation missing" × 7 — through
the 21:32 CT print, hours after the approvals. Same server store,
stale second fetch. (Verified in code; the API itself agreed with
(a) at print time.)

**(c) Header "Filing review: 3 implemented · 3 missing" — A
DIFFERENT QUESTION, UNLABELED.** WorkbenchPage's header reads
`snapshot.readinessDashboard.complianceSummary` (fallback:
`snapshot.complianceMatrix.summary`) plus the snapshot's gap count.
That summary is computed at **analysis time** and frozen into the
snapshot; it measures how the extraction covered the filing's stated
requirements, not what has since been approved. It was rendered in
the header with no as-of label, so an analysis-time coverage count
read as current approval state.

A fourth dialect rode along: the snapshot's chassis
`executableMechanics` statuses (`filed_evidence_review_required`
etc.), also frozen at analysis.

**Fix principle:** every panel that states equation/table status
reads the same live artifact store, invalidated by the same signal;
state that is legitimately frozen at a run is labeled with the run's
time; duplicate renderings are rebound to the one payload or
removed.

## The COI verdict — the assessment's hypothesis was wrong

The assessment suspected the equation evaluator's row matcher: that
a table row with `attained_age: null` failed to act as a wildcard
against a scenario's attained age. **Disproven by reading the
matcher** (`domain/equations.py::select_rows` / `_row_matches`):
row-side null (or "", "ANY", "All") is a wildcard for *every*
selector, attained_age included, and has been since before the
saved run. The filed COI rows also carry `selectorEvidence` from
their specimen documents.

The saved scenario failed for a different, narrower reason:

* The analyze pipeline and the workspace-GET rebuild construct the
  illustration request with **no underwriting selectors at all**
  (server: the analyze path passes only
  `_workspaceExecutableMechanics`; `_run_ul_projection` defaults age
  to 45 and reads sex/risk_class/tobacco_status as `None`).
* The filed COI rows are selector-carrying: their specimens state
  sex "M", risk class "Standard", tobacco status "Tobacco"
  (resp. "Non-Tobacco"). The matcher — correctly, by doctrine —
  does **not** treat a scenario-side null as a wildcard: silently
  pricing Tobacco rows for an unspecified scenario is exactly what
  the disclosed-fallback gate exists to prevent.
* So every year failed with "no COI table row applies at duration
  1, attained age 45", and the summary repeated that failure 30
  times instead of naming the cause once.
* The HTTP projection path was already protected:
  `_selector_match_issues` refuses with `selector_table_mismatch`
  (409) unless the user authorizes a disclosed fallback. The
  analyze/GET-rebuild paths had **no such gate and no naming** —
  that asymmetry is the defect.

**Decision:** the matcher does not change. Scenario-side null is
not a wildcard; that asymmetry is the honest semantics (a table may
say "applies to all"; a scenario may not silently claim a class it
did not state). What changes: the coverage check now runs on every
path (generalized below), and a run whose in-force tables cannot
serve the scenario names the blocker once, up front, with the years
it covers — instead of 30 identical per-year failures.

## The 242-row table — candidates were a queue, not a choice

Two specimen documents file the same schedules: the base S18PRUL
specimen (insured: M, Standard, **Non-Tobacco**) and its Nicotine
variant (M, Standard, **Tobacco**). Verified by running this repo's
extractor on both filed PDFs: each carries a 121-row COI table with
**identical rates per duration** (0.1142, 0.1251, …) — the same
table, stamped with each specimen's own insured class by the
extractor's selector evidence. The monthly-expense tables genuinely
differ (18.95 Non-Tobacco vs 27.40 Tobacco). The product treated
the candidates as a sequence, not a choice:

* Proposal generation emitted **one proposal per candidate**, so
  the user confirmed the COI table, then was offered the *other*
  document's COI table as another confirmation, and so on (fees
  were accepted five times on ws-0e4bd9b4).
* `accept_filed_mechanic` unioned **all** accepted candidates'
  rows into `usable`, so accepting both variants stacked 121 + 121
  rows into a 242-row "in force" table (fees reached 243) — one
  table counted twice, with the specimen class as the only
  difference between the copies.
* Separately, rows were summed in prose as durations:
  `_describe_rows` turned a 242-row table into "values in force
  over 242 years".

Fix (the brief's semantics): candidates that file the same table
(same mechanic; for fees, the same component set) are
**alternatives in one choice** — the user picks which filed table
is in force and sees which rows differ (here: the values are the
same; the specimen class stamped on the rows is what changes —
and for the expense table, the amounts genuinely differ, which the
diff shows). Accepting one supersedes the previously accepted
alternative in its group; identical rows (same selector, same
value) arriving via different groups dedupe into one row carrying
both provenances. A scenario the chosen table cannot serve is
named by the coverage check (above), never silently priced from
the other specimen.

## What was unified

1. **One approval reality (frontend).** WorkbenchPage owns an
   inputs epoch: every mutation from either panel bumps it, and
   both MechanicsPanel and EquationsPanel refetch on it. The two
   panels can no longer hold different generations of the truth.
   The header's filing-review counts are labeled as what they are —
   the analysis snapshot's coverage, with the analysis time. The
   stale-inputs banner now appears exactly once (in the page
   header, with the re-run action); the panel's duplicate banner
   is removed.
2. **Coverage naming (backend).** `_selector_match_issues` is
   generalized from {COI, monthly-expense fees} to every filed
   table an in-force equation can read (COI, surrender, corridor,
   and each fee component), and it names the missing selectors and
   the table's own selector values. `_run_ul_projection` runs it on
   every path and attaches `coverageIssues` to the run; the run
   summary (`missingMechanics`) names a coverage failure once with
   its year range (reason `table_coverage`), and
   `mechanicsExecution` gains a `failureSummary` that collapses
   identical per-year reasons into one entry with its years.
3. **Candidates as choices (backend + frontend).** Filed-table
   proposals are now `filed_table_choice` proposals: one per
   alternative group, carrying every candidate as an option with
   its evidence and a computed diff (identical / differing /
   only-in rows, with examples). Confirming requires choosing an
   option (a single-option choice confirms as before). Once any
   candidate in a group is accepted, the group leaves the proposal
   queue; switching is a slot-card action. The slot card lists all
   candidates with their state (in force / awaiting review /
   superseded) and the same diff. Accept supersedes within the
   group; identical rows dedupe with merged provenance
   (`alsoFiledAs`).
4. **Counts say what they count.** `_describe_rows` and the slot
   views now say "121 rows covering durations 1–121" (rows +
   duration coverage), never "over N years".
5. **Card collapse.** Slot cards show source · row count/coverage
   · status · used-by state (from the linkage derivation,
   including "not used by any approved equation" for orphans like
   the NAR factor table after its equation was replaced). Rows,
   replace, and correct live behind one Details expand per card —
   the same pattern the linkage pane uses. No more full-table
   walls or four cloned widget stacks per card.
6. **Provenance honesty.** The crediting slot's runtime-config
   value is labeled an **assumption** (origin: product runtime
   configuration, not the filing), with distinct styling, in the
   panel payload (`sourceKind: "assumption"`) and the card.
7. **Header identity.** The garbled `" UL` in the printout was not
   app data: the workspace's product type is `UL` (verified live),
   and the stray quote is the identity line's "·" separator mangled
   by PDF text extraction (the same artifact appears between the
   filing-review counts in the printout). The data needed no fix.
   The print rendering did: a print stylesheet now prints the
   header and the active tab only, so a printed run page cannot
   interleave five tabs' surfaces (or collide the scenario fields)
   again.

## What was deliberately NOT migrated

* **No live workspace data was rewritten.** Supersede and dedupe
  apply to new acceptances and to in-memory read views
  (`executable_mechanics_view` dedupes what a projection reads);
  recorded artifacts, candidate records, and the change history are
  untouched and preserved verbatim. A workspace that already holds
  a 242-row union will show deduped counts where rows are truly
  identical, but its stored rows are not rewritten — re-accepting
  a candidate through the new choice flow is the user's action,
  not a migration.
* The snapshot's frozen compliance/chassis views were **labeled**,
  not recomputed: they are the analysis run's record.
* The matcher semantics did not change (see the COI verdict).
* Approvals/rejections on real workspaces remain the user's; the
  acceptance below ran projections and payload checks, and used a
  throwaway workspace for the candidate-choice demonstration.

## Acceptance

Verified on the live deployment after the convergence chain (CI
Jobs-API success → GHCR `:main` at the new digest on two agreeing
reads with the image config's GIT_SHA → pod /health reporting the
commit). The live exercise, per the brief's hard gate:

* ws-b5ea66f5 (the surviving real-filings workspace, read-only):
  the panel payload proposes the COI table as ONE choice with both
  specimen candidates as options and a computed diff; the fees
  choices group by component; candidate coverage reads "121 rows
  covering durations 1–121"; the crediting slot carries
  `sourceKind: "assumption"`; the panel's embedded equations view
  and `GET /equations` agree on every mechanic; the served bundle
  carries the revamp UI (choice cards, labeled filing review,
  Details expand). Its `updatedAt` is unchanged by all of this.
* A throwaway single-document workspace (created, exercised, and
  deleted): confirming the COI choice puts the transcribed COI
  equation in force; a selector-less projection is refused up
  front (409) with the coverage issue naming the missing selectors
  and the table's Tobacco/Non-Tobacco class; the matching-class
  projection (M / Standard / Non-Tobacco) runs, COI computes, and
  the ledger cites the exact COI table row.
* The other pre-existing workspaces had already been deleted
  before this build began (observed at build start; the filings
  themselves untouched, and ws-b5ea66f5 is the surviving workspace).
  Nothing else remained to touch, and ws-b5ea66f5's recorded state
  is unchanged by all of the above.

Full suite: 324 passed, exactly the 5 inherited failures (the
baseline, verified against pristine HEAD before building). Seven
inherited tests across three files were updated for the deliberate
contract changes: the choice-shaped proposals (×3), the
rows-and-coverage phrasing in correction confirm-backs, the
unmatched-selector run now naming `table_coverage`, and the two
filed-candidate tests whose union semantics this revamp retires —
accepting an alternative now supersedes, and a same-selector
conflict is only possible across different alternative groups,
where it still refuses.


---

## Addendum — Oct 27, 2026: confirmed state survives re-analysis; candidates are selector slices

### What Billy found

The morning after the revamp shipped, Billy confirmed every table
choice and approved all seven equations on the live workspace
(08:54–08:58Z), then re-ran the analysis at the stale banner's own
advice. Afterwards the equations were still in force but every table
acceptance was gone — all candidates back to `review_required`, all
six choice proposals pending again — and a fresh projection priced
COI at $0 with `coverageIssues` empty. The stale banner also never
cleared, and the header simultaneously claimed "Projection current".

### Confirmed mechanism (not the first hypothesis)

The regression sequence (confirm → re-run analysis → assert still in
force) was written first and run against the unfixed code: it
reproduced the wipe exactly, at API level. In code:
`api_workspace_analyze` builds a FRESH executable-mechanics artifact
from the documents and carried over only `workspaceEdits`,
`corrections`, and equation records from the prior artifact.
Candidate acceptances, usable rows, override/supersede state,
proposal dismissals, and synthetic state were not carried — the
fresh artifact's candidates are `review_required` by construction.
Two aggravating details: the analysis job commits that fresh
artifact EARLY (its extracting-mechanics phase), so acceptances
vanish within about a minute of the job starting, while the
stale-clearing workspace update runs only at job end (~18 minutes
for 13 filings); and the slot-card accept path
(`POST /filed-mechanics/accept`) wrote neither a change-log record
nor a staleness mark, unlike every other mutation path.

### The fix

* `carry_over_decision_state(fresh, prior)` (workspace_ul_mechanics)
  runs inside analysis, before the edit/correction re-applies:
  synthetic state, `dismissedProposals`, per-candidate decision
  state (by candidate id — ids are content hashes of the canonical
  rows, so re-extraction of unchanged documents reproduces them),
  row-provenance decision fields, and `reviews` entries transplant;
  usable tables rebuild as the union of accepted candidates. A
  decided candidate the new extraction no longer produces is
  reported in the artifact's warnings, never silently dropped.
* Write-path audit: the direct filed-table accept now appends a
  `filed_table_accept` change record and marks the saved projection
  stale, as do the synthetic COI/surrender accept and remove
  endpoints (previously none of the four did either).

### Candidate model correction — selector slices (Billy, Oct 27)

Billy: *"I need to choose the nicotine pdf to run a tobacco
projection. Seems like I should be able to approve all of the
choices and they should cover the male/female, tobacco/non, etc."*
The revamp's own acceptance data proved him right: the COI choice
diff was 0 identical / 0 differing / 121 rows only in each —
selector-disjoint. The base specifications PDF and the Nicotine
specimen are complementary SELECTOR SLICES of one table, not
competing versions, so the one-choice-per-group model is retired:

* Each filed candidate is approved/rejected independently; the
  usable table is the UNION of all approved candidates' rows
  (identical-row dedupe with `alsoFiledAs` provenance unchanged).
  Selector-disjoint approvals accumulate coverage — no supersede
  between slices. Fees follow the same rule within a component.
* A decision is required only where two candidates overlap on
  selectors with DIFFERING values: the accept refuses (409, naming
  the other candidate and an example selector), the proposal becomes
  a two-option conflict choice (the version in force vs the
  challenger), and only the user's explicit override lets the
  challenger's rows govern the contested selectors. A candidate
  overridden on EVERY row is marked superseded — the one surviving
  meaning of the word: a corrected version of the same slice.
* UI: slot cards list per-version approvals with selector summaries
  ("Covers: …") and per-candidate state ("In force — part of the
  table"); a refused accept offers the explicit override on the
  card; conflict proposals state the disagreement and tag the
  option currently in force.


### One stale truth

`projectionStale` now has one precise meaning everywhere: **the
saved projection predates the latest input change** (the change's
timestamp is `projectionStaleSince`). Every input-changing writer
sets it (edits, corrections, proposal confirms/dismissals, equation
decisions, filed-table accepts, synthetic accept/remove). It is
cleared by whoever refreshes the saved projection from current
inputs: a completed projection run clears it on its success path,
and a completed analysis clears marks at or before the timestamp
the analysis observed at its start (`clear_projection_stale_through`)
— a change made WHILE an analysis runs postdates its recomputation
and stays marked. The analysis-failure path preserves the mark (its
snapshot was never refreshed). The workbench header's run-state
label derives from the same flag ("Saved projection is stale"),
never from session state, and the banner states the flag's actual
meaning. While an analysis runs, the open workbench polls the
workspace (~4 s); the reload that observes completion bumps the
inputs epoch, so both panels refetch the post-analysis artifact —
an open page can no longer show pre-analysis panel state beside a
post-analysis projection. The filing-review counts are labeled with
the last COMPLETED analysis time only.

### Missing tables are named

The coverage check now also derives, from each in-force equation's
formula body, the tables it reads: a table with no rows in force
produces a `table_not_in_force` issue naming the equation and the
table ("The approved COI charge equation reads the COI table, but
no COI table is in force — accept the filed COI table so it can be
calculated."). Naming is not blocking: unlike a selector mismatch
on an in-force table (which still refuses, 409), a missing table
lets the run proceed and states the absence — `missingMechanics`
carries reason `table_not_in_force` (replacing the bare
`evaluation_failed`), and per-year failures still collapse into one
`failureSummary` group.

### Tests

New `test_analysis_state_persistence.py` (8 tests) runs Billy's
exact sequence at API level plus the new model: both COI slices
approved → union of 6 rows → Tobacco and Non-Tobacco scenarios each
compute, priced by their own slice's rates → re-analysis → both
survive; the conflict path (direct accept refuses, proposal asks,
challenger governs, fully-overridden incumbent superseded; the
keep-incumbent branch records `proposal_conflict_kept`); dismissal
survival; the stale lifecycle (analyze → clear; confirm → set;
projection run → clear; filed accept → set; re-analysis → clear);
missing-table naming; carry-over unit coverage. Inherited tests
updated for the deliberate contract changes: the four revamp
choice/supersede tests (rewritten for slices), the
accepts-only-selected union half, `test_analysis_update_clears_staleness`
(the through-timestamp contract), and store-boundary stubs in the
synthetic/filed-accept tests for the two new store calls. Final:
332 passed, exactly the same 5 inherited failures; tsc error set
identical to pristine HEAD.


### Live acceptance (Oct 27, 2026, after the fix)

Convergence: CI run for `162229d4` succeeded (Jobs API, build-app
incl. build-push); GHCR `:main` leaf `c98ebf51…` with image config
`GIT_SHA=162229d4…`; the rolled pod's `/health` reports
`git_sha 162229d4…`; the served bundle is byte-identical in hash to
a local build of the new sources and carries the new UI copy
(per-version approvals, "Saved projection is stale", the conflict
override action).

On the running app, a throwaway workspace (`ws-3f698b27`, created
from the base Policy Specifications and the Nicotine specimen in
the object store, deleted afterwards): analysis produced the same
candidate ids as the live workspace (content hashes); BOTH COI
candidates were confirmed independently and stood in force together
— 242 rows, the union of the two 121-row slices; Tobacco and
Non-Tobacco projections each computed COI (year-1 charge 126.78 —
the filed specimens price identically per duration, so slice
discrimination is asserted by the API-level tests with distinct
rates). **The analysis was then re-run, and both acceptances
survived**: candidates still in force, 242 rows, no COI proposal
regenerated, `projectionStale` false, both projections still
computing COI. A direct filed-table accept then set
`projectionStale`; a projection run cleared it. The conflict
override flow was not exercised live (no naturally conflicting
pair exists on these filings; it is covered by the API-level
tests). ws-b5ea66f5 was read-only throughout: its `updatedAt`
(`2026-10-27T09:20:10.502959Z`, from Billy's own activity that
morning) is unchanged by this work — its tables remain for Billy
to re-confirm under the new model, its equations untouched.
