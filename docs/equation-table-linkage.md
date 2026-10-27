# Equation ↔ table linkage

The Inputs & Equations pane shows each equation decision together
with the data tables that equation depends on — linked both ways,
with decision provenance on both sides. An equation's approval
(filing statement, page, approved by/at) sits in the same card as
the tables it reads and each table's own acceptance record, so the
two decisions that together produce a number can be audited side by
side.

## How dependencies are derived (exact, not text-mined)

In the formula language a table reference is a structural node:

- `{"lookup": {"table": ..., "where": ..., "default": ...}}` reads
  one row's field (the field is fixed per table in
  `domain/equations.py: TABLES`);
- `{"rows_sum": {"table": ..., "where": ..., "exclude_where": ...,
  "expr": ...}}` sums a per-row expression over selected rows.

`extract/workspace_linkage.py: body_table_references` walks the
equation body generically (every dict/list node, including a lookup
nested inside another lookup's `default`) and collects those nodes.
Dependencies are never parsed out of the human rendering or the
filing prose: if the formula does not structurally read a table,
the equation has no dependency on it. (Example: the premium-load
equation in its common live form, `premium_due × 0.10`, reads no
table; the canonical fee-schedule form reads `fees` through a
`lookup` on the percent-of-premium row. Both are reported as
derived.)

References are deduplicated per (mechanic equation, node kind,
table, field, selectors) and carry `via` (`lookup` | `rows_sum`),
the `where` / `excludeWhere` selectors, and `hasDefault`.

## Resolution against the workspace

Each reference is resolved against the workspace's tables **in
force** (the artifact's `usable` rows — filed-and-accepted,
workspace-edited, corrected, or synthetic, per the mechanics
panel's own status derivation, which the linkage reuses rather
than re-deriving):

- `status: "filed"` — rows exist. The dependency carries
  `rowCount`, the table's `sourceFilename` / `sourcePage` (the
  first provenance group of the in-force rows), and the acceptance
  record `acceptedBy` / `acceptedAt` (the rows' review provenance,
  falling back to the workspace-edit stamp).
- `status: "missing"` — no rows in force. The dependency is never
  dropped: it carries `missingReason: "table_not_extracted"` (the
  reason class the product already states) and a note. The note
  distinguishes the two cases the formula language makes real: a
  lookup **with** a stated default falls back to that default until
  a table is in force; a lookup **without** one cannot be evaluated
  where a row is needed.

## Payload shapes

`GET /api/workspaces/{id}/equations` (and the single-mechanic
variant) is the Phase 7 payload, enriched:

- every record with a body — the in-force equation and each
  pending one alike — carries `tableDependencies: [dependency]`.
  Records without a body (stated-but-unmapped) carry `[]`: they
  propose no readable formula, so they depend on nothing yet, and
  their own stated reason stays on the record as before.
- a top-level `tables: [tableView]` list carries the reverse
  linkage (below).

`GET /api/workspaces/{id}/tables/{table}` returns one table in
full (deliberately not nested under `/equations/`, whose
`{mechanic}` segment would collide):

```
{ table, label, status, basis, statusLabel, rowCount,
  sources: [{filename, page, tableHeading, valueBasis,
             sourceType, reviewStatus, reviewedBy, reviewedAt}],
  sourceFilename, sourcePage, acceptedBy, acceptedAt,
  usedBy, usedByPending, unused,
  rows: [...], rowsReturned, offset, limit, truncated,
  history: [{kind, who, at, summary, prior, new, recordedAs}],
  workspaceId }
```

Rows are the accepted rows exactly as stored, provenance included.
Paging: `offset` (default 0) and `limit` (default 500, capped at
1000); `truncated` is true whenever the page is not the whole
table. The live 242-row COI table returns whole under the default.

## What "used by" means

`usedBy` names the mechanics whose **in-force** (approved)
equations structurally read the table — the live dependencies a
table swap would move. `usedByPending` names mechanics with a
*pending* equation that would read it; it is reported separately
and never merged into `usedBy`. A table no approved equation reads
has `unused: true` and the UI says so plainly ("Not used by any
approved equation yet"). Note the fee schedule serves two equation
mechanics (premium load and policy fees) — `usedBy` is
equation-mechanic names, and a table can list several.

## History — as recorded, never fabricated

The table detail's `history` is assembled only from what the store
actually holds:

1. the persisted change log (`mechanics-changes.json`), filtered
   to this table and to table-event kinds (`table_replace`,
   `proposal_accept`, `nar_factor`, `correction`,
   `correction_note`) — equation approvals/rejections are equation
   events and never appear as table history;
2. the filed acceptance stamped on the in-force rows' own
   provenance (`reviewedBy` / `reviewedAt`) — the manual review
   path records acceptance there and writes no change entry, so
   this is where e.g. a fee table accepted from a specimen filing
   shows up;
3. the workspace-edit stamp, when an edit replaced the table and
   no change entry already records that same edit.

A provenance acceptance and a change entry describing the same
event (same person, timestamps within two minutes — the two are
stamped moments apart by different code paths) are merged, the
change entry winning. Entries are newest-first, capped at 50.
Nothing is synthesized beyond these records: a table with no
recorded history says so.

## The stretch: ledger row citation (landed)

The evaluator (`domain/equations.py: evaluate`) accepts an
optional `trace` out-list. Every `lookup` appends a citation of
the row it used — table, field, value, unit, the row's addressing
key (duration / attained age / sex / risk class / tobacco status),
and the row's provenance (document, page, table heading). A lookup
that fell back to its stated default appends `defaulted: true`
with no row. The trace changes nothing about any value produced;
with `trace=None` evaluation is exactly as before (pinned by
tests comparing traced and untraced results).

The projection loop collects citations from the COI equation only,
per month, keeping a month's citations only when that month's
charge actually lands. Each projection year row's
`appliedMechanics.coi.tableRows` carries the distinct rows the
year's charges read, and the projection ledger's COI component
names up to three of them as "COI table row applied" inputs (with
a count line when the year read more) — so a year's COI charge is
auditable to a filed row of a named table in a named filing, not
just to a rate. Extending the same citation to the surrender and
corridor lookups is mechanical follow-up work in the same shape;
COI was the specified first step.

## Read-only

The feature adds no write paths and changes no approval
semantics. Nothing here approves, rejects, authors, or mutates a
workspace.
