# Holistic review pass (Oct 27, 2026)

Status: SHIPPED in the analysis job. Design record:
`actuarypoc-deploy/holistic-review-pass-design-2026-10-27.md`.

## What it is

Background SELF-CHECKING so the pipeline's suggestions are more
reliable before a person sees them — not a change to the approval
doctrine. Nothing the review does approves, accepts, or puts
anything in force. A suggestion arrives with its verification
evidence attached ("independently re-read with wider context —
identical"; "also stated in <doc>, p. <n>"), or flagged with the
disagreement quoted, instead of as a naked single reading.

## Where it runs

Inside the background analysis job (`api_workspace_analyze`), after
slice extraction and candidate assembly, before finalizing. The job
record gains a `holistic_review` phase; the pass reports
sub-progress through the same `phaseDetail` channel as slice
extraction. The review record persists on the mechanics artifact
(`holisticReview`) and on the snapshot — the analysis record a
later calibration / shadow evaluation reads.

Stated absence: with `ACTUARYPOC_HOLISTIC_REVIEW=off`, or with
`ACTUARYPOC_BACKEND_PROFILE=onprem_small` (a small local model
cannot spare a second pass; force with
`ACTUARYPOC_HOLISTIC_REVIEW=on`), or if the pass itself fails, the
record's status is `absent` with the plain reason, the workspace
payload states it, and the analysis still completes. Never silent.

## Self-checking

For each harvested mechanic candidate (pending equation records +
the deterministic harvest), an independent re-extraction runs under
DIFFERENT slicing: each document's slices dispatched together as
one wide unit, plus overlapping consecutive pairs
(`regroup_slices_wider`). Agreement attaches verification evidence
to the candidate (record source / proposal `review` field).
A mechanic the first pass missed but the wider re-read finds is
materialized as an ordinary PENDING record (provenance
`holistic_review_reread`) and reported in the review's `found`
list. Filed table candidates are re-checked deterministically
(rows re-validated; no selector priced two ways) — the
deterministic table channel is never re-sliced by a model.

## Reconciliation ladder

A divergence (two readings of one mechanic, from the originals or
the re-read) opens a case. Cases are pipeline work items, resolved
in order:

1. **Deterministic rules** — selector-disjoint table slices union
   (not a conflict); identical content merges; the reading that
   satisfies the filed arithmetic constraints wins (e.g. the
   premium-load prose reading matching the filed fee table's
   premium-expense percentage).
2. **Joint re-read** — both sources dispatched together; support is
   judged by whether a candidate's verbatim statement is present
   in the combined text (never by which match a pattern finds
   first).
3. **Repair** — ONE bounded round per localized case (mechanic +
   document + missing text named), capped at 5 per run: every
   document dispatched as one cross-referenced unit. A new reading
   arrives as a RIVAL pending record beside the originals — never
   a silent replacement — and the case escalates with it named.
4. **Source standing** — the document that DEFINES a mechanic
   (definitional statement; policy form / specifications;
   actuarial memorandum) governs over one that mentions or
   illustrates it; a margin of 2+ is required.
5. **Reasoned judgment** — via the typed decision interface
   (below), treated as UNcalibrated: two independent judgment runs
   must agree AND the winner's reading must be corroborated in at
   least two distinct filed documents, else the case escalates.
   Capped at 3 judged cases per run.

A reconciled case presents ONE suggestion: the winner carries the
resolution (`source.reviewReconciliation`: ladder step, rationale,
losing readings); a losing record is superseded (preserved, never
deleted); a losing harvest reading is not proposed. Escalation
happens only when the ladder genuinely cannot settle it — above
all two filed sources truly contradicting each other. The flag
carries the quoted evidence, attaches to the suggestion
(`reviewFlag`), and excludes it from bulk approval BY NAME (the
flag check runs before every other bulk eligibility rule);
reconciled items stay bulk-eligible, with the reconciliation noted
on their summary line (`reviewNote`).

V1 checks: self-check divergences, filed-table slice relations and
internal conflicts, cross-product mentions (a suggestion whose own
source statement names a different product/form — comparative
mentions resolve as framing), framing loss (a qualification stated
in another document that the candidate does not carry — resolved
by joint re-read with the qualification recorded as a
`framingNote`, else escalated with the text quoted), and summary
contradictions (which surface as ordinary divergences between the
memo's reading and any other).

## Compliance-header reconciliation

`filing_review_reconciliation` composes review-sourced entries
with the shipped approval-driven ones, in the same clause/data:
the frozen snapshot counts never move, but a requirement or gap
whose subject the review's `found` list establishes is named as
found-by-review (`reviewResolvedRequirements` /
`reviewResolvedGaps`, each with the check and rationale), before
any approval. A requirement the review found nothing for stays
missing.

## Decision logging + the typed interface

Every case records its candidates, evidence features (candidate
count, distinct documents, origins), the resolving ladder step or
the escalation, the rationale, and the verification outcome. The
case list IS the decision log, persisted with the analysis record.
Labels are VERIFIABLE outcomes (dual-slicing convergence,
arithmetic, filed-source corroboration); human clicks are workflow
data, never correctness labels.

Judgment calls sit behind `DecisionProvider`
(`choose` / `score` / `truth_probability`) in
`extract/holistic_review.py`. The interim implementation
(`InterimDecisionProvider`) wraps the current backend (an OpenAI
judge when a key is configured) and abstains when it cannot run —
an abstention escalates. A Jev-class calibrated decision model
swaps in behind the same interface without redesign.

**Pre-approval is HELD** (Billy, Oct 27, 2026) until a Jev-class
calibrated model can run on-prem; nothing in this build
pre-approves, and calibration anchors to verifiable outcomes, not
to agreement with any individual approver.

## Tuning knobs

- `ACTUARYPOC_HOLISTIC_REVIEW` — `off` disables (stated absence);
  `on` forces on small profiles.
- `ACTUARYPOC_BACKEND_PROFILE` — `onprem_small` (etc.) states the
  absence unless forced.
- Repair rounds and judged cases are hard-capped in code
  (`_MAX_REPAIRS`, `_MAX_JUDGED_CASES`).
