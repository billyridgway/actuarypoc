# Gap semantics — "missing" means missing from the documents

(Billy, Oct 27, 2026.) The product called things "missing" that were
not missing from the documents: on a fresh workspace, all seven
mechanics showed as open "equation missing" gaps purely because their
equations were not approved yet — while the documents stated each
mechanic, the evidence was extracted, and the equation sat in the
suggestions. Three states were conflated; they are now separated
everywhere a gap or a compliance count is produced.

## The three states

For every mechanic (and, through its slot, every compliance
requirement) the analysis determines **document coverage**
(`workspace_equations.equation_document_coverage`, composed with
table coverage in `workspace_mechanics_panel.document_coverage`):

1. **Covered** — the documents state the calculation and extraction
   holds an evidenced candidate: a pending harvested record with a
   body, an approved record sourced from a document, or a
   deterministic-harvest candidate with a body. For `coi_charge`, a
   timing statement counts when the filed table's single rate unit
   supplies the body (the proposal path's derivation). A filed table
   whose transcription compiles to a body also covers its governing
   mechanic (`coi_charge`, `surrender_charge`, `policy_fees`,
   `nar_definition`, `death_benefit`) — accepting the table is what
   puts that equation in force. `premium_load` is never
   table-covered: its transcription applies a chassis percentage,
   while the filed percentage is stated in prose. Finally, any
   mechanic carrying an equation proposal on the suggestions surface
   is covered by construction — coverage unions the proposal
   builder's output so the two can never diverge. The holistic
   review's found-by-review candidates are ordinary pending records
   by the time coverage is computed, so they cover exactly like
   first-pass candidates. **Covered is not a gap, whatever the
   approval state.**
2. **Not in the documents** — no statement of the calculation was
   found. This is the only genuine document gap.
3. **Stated but not extracted** — the documents state it but
   extraction holds no usable body (an unmapped record, or a harvest
   statement it could not structure). That is our shortcoming, not
   the document's, and it is labeled as such.

## Where the semantics apply

- **Gaps** (`_build_ul_projection_view`, when the caller supplies
  `_documentCoverage` — analysis finalization, projection runs, and
  snapshot rebuilds all do): a `missing_<mechanic>_equation` gap is
  emitted only for states 2 and 3. State 2 is titled "<Label>
  equation not stated in the documents" (`coverage:
  "not_in_documents"`, suggested uploads kept — adding the document
  is the remedy). State 3 is titled "<Label> equation stated in the
  documents but not extracted" (`coverage: "stated_not_extracted"`,
  no uploads — the document is already here; entering the equation
  or recording a correction is the remedy). A mechanic whose equation
  is in force but failed evaluation, or whose table cannot serve the
  scenario, is not a document gap either: the run names it in
  `missingMechanics` / `coverageIssues`, which are unchanged.
  Without coverage (the product-level snapshot), the legacy emission
  is preserved.
- **Compliance counts**: at analysis finalization,
  `apply_document_coverage_to_requirements` rewrites a requirement
  the bare snapshot counted "missing" to the distinct **covered**
  status when its slot is document-covered (filed table candidate or
  evidenced equation candidate). `_reconcile_workspace_readiness`
  counts covered in its own bucket — never folded into missing — and
  publishes it in the summary/message only when nonzero, so older
  snapshots keep their shape. The header shows "· N covered" when
  nonzero. Covered behaves like partial for the projection trust
  level (draft illustration), and like partial/missing for the
  overall status (yellow, not green, while approvals are pending).
- **Filing-review reconciliation**: the snapshot stays frozen with
  the new semantics. A covered-at-analysis requirement that later
  comes into force is named by the clause with its covered count
  ("3 covered at analysis — now in force: …"), and a requirement the
  holistic review found can be named from the covered state too.
  Snapshots stored before this change are historical and untouched.

Run-time truth is deliberately unchanged: a projection still names
every unapproved mechanic in `missingMechanics` — that is about
calculation, not documents.
