# Candidate provenance — an approval shows its evidence

Oct 27, 2026. Built locally under the weekday push gate (staged
uncommitted; push after the gate).

## The defect (diagnosed live that morning)

Three of the eight filed-table candidates on a Promise UL
workspace were presented for approval with no source evidence: the
proposal read "Accept the filed surrender schedule table from the
filing", the panel payload carried `filename: None / page: None`,
and confirming one recorded **"(evidence: None)"** in the change
history. The affected candidates: the surrender schedule, the
1-row administrative-charge fees candidate, and the NAR factor.

## Where the provenance was dropped

`_extract_workspace_executable_mechanics` (ui/server.py) groups
extracted rows by (filename, page, heading), then merges groups
with identical canonical content into ONE candidate. The three
affected tables are filed *identically* in both specimen documents
(ICC18 S18PRUL.pdf and ICC18 S18PRUL Nicotine.pdf), so each merged
candidate had two sources — and the merge explicitly set
`candidate["filename"] = None` and `candidate["page"] = None`,
keeping the documents only on `candidate["sources"]` and on each
row's `provenance.supportingSources`. No consumer ever read those
fields: the proposal builder and the panel views read only
`candidate.filename/page`, and the change-log formatter interpolated
the None verbatim. COI, corridor, and the monthly-expense fees
escaped because their content differs per document (selector
slices) or appears in only one — single-source candidates kept
their filename/page all along. The data was never lost: the
table-detail view, which reads row-level provenance, showed the
true sources (surrender: Nicotine/base p. 3, "Surrender Charge
Rates") the whole time.

## The fix

- **Construction** (ui/server.py): a merged candidate keeps the
  filename/page its rows actually came from; `sources` (every
  document the identical table was filed in) and `sourceCount`
  remain, as does the rows' `supportingSources` stamp.
- **One derivation for every consumer** —
  `candidate_provenance()` in workspace_ul_mechanics.py returns
  `{filename, page, tableHeading, sources}`: the candidate's own
  fields first, then its recorded sources, then its rows'
  provenance. Artifacts stored before this change (fields nulled,
  sources intact) present correct evidence with no re-analysis.
- **Proposals** (workspace_mechanics_proposals.py): evidence,
  options, and conflict incumbents are built from that derivation
  and carry `sources`; change records format evidence through
  `_evidence_summary()`.
- **Panel** (workspace_mechanics_panel.py): pending and full
  candidate views carry the derived filename/page/heading plus
  `sources`.
- **Every other accept/evidence surface**: the slot-card accept
  change summary (ui/server.py), the linkage view's derived
  acceptance entries, and the filed-conflict refusal message.
- **"Source not recorded", said plainly**: wherever no provenance
  exists anywhere — candidate fields, sources, and rows all empty
  — the proposal label, confirm-back, card, and change record say
  "source not recorded". The string "None" never renders as
  evidence, and the vague fallback "the filing" is gone from every
  evidence position (web: MechanicsPanel ×3, EquationsPanel ×1).
  In the UI, a merged candidate's card additionally notes "filed
  identically in N documents" so the single name shown is not
  mistaken for the only place the table appears.

## Acceptance (local only)

- New tests: `src/actuarypoc/tests/test_candidate_provenance.py`
  (13) — the helper's precedence; all three shapes through
  proposal generation and both panel views; an accept of a
  merged candidate writing "(evidence: ICC18 S18PRUL.pdf, p. 3)";
  a no-provenance candidate saying "source not recorded" in label,
  confirm-back, panel, and change record; construction keeping
  filename/page for identical tables in two documents.
- Suite: 363 passed / the same 5 inherited failures (baseline
  350 + 13 new). tsc error set identical to baseline (2
  pre-existing ProductWorkspacePage.tsx errors); vite build clean.
- No live gate was run — the change is staged uncommitted under
  the push gate; the live exercise happens after the gated push,
  per the standing rule.
