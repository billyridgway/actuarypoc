# Actuary AI authoritative context

Read this index before planning or implementing Actuary AI work. The files in
this directory separate verified implementation from intent and history.

- [Current implemented state](current-state.md) — repository and live-runtime
  facts, with evidence dates and known limitations.
- [Product vision and MVP boundaries](vision-and-mvp.md) — intended outcome,
  current boundary, and unresolved product questions.
- [Architecture decisions](architecture-decisions.md) — accepted decisions and
  their evidence; this is an index, not a substitute for detailed design docs.
- [Definition of done](definition-of-done.md) — mandatory closeout gates.
- [Test and validation matrix](validation-matrix.md) — deterministic commands
  and required evidence by change type.

Authority order when sources disagree:

1. Current repository and live-runtime evidence.
2. Explicit accepted decisions in this directory and linked ADRs.
3. Current vision and MVP boundary.
4. Backlogs, memory, validation snapshots, and historical notes.

Historical notes are evidence that work occurred, not proof that it remains in
the current source or deployment. Update these files after meaningful work,
including evidence date, commit, deployment digest, and unresolved limitations.
