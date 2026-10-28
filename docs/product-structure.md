# Product structure — approvals organized by the product's anatomy

Billy (Oct 28, 2026): the suggestions and equations "feel like a random
set of things that need to be approved." A product type has a normal
structure; the choices a person must make live inside it.

## The declared structure (the proto-pack)

`extract/workspace_structure.py` declares the UL anatomy as data —
ordered steps, each with a plain-language sentence saying what the step
is in the policy's life, and its member mechanics (the step's equation
AND its tables):

1. Premium & loads — `premium_load`
2. Policy fees — `policy_fees` + the fees tables
3. Interest crediting — `crediting`
4. Death benefit & corridor — `death_benefit` + the corridor table
5. Net amount at risk — `nar_definition` + the NAR factor table
6. COI charges — `coi_charge` + the COI tables
7. Surrender & exit — `surrender_charge` + the surrender tables

Order and grouping come only from this declaration, never from model
output. Mechanics the declaration does not name render in a trailing
"Also found in the documents" group — never forced into the anatomy.
When the analyze engine is extracted into Roost, this declaration is
the domain pack's structure layer.

## Readings, provenance classes, step states

Every reading of a step's equation — the artifact's records and the
deterministic harvest, unified and deduplicated by formula body —
carries its evidence (document / page / quoted statement) and a
provenance class:

- **Filed definition** — stated as a definition in a filed document
  (the policy form's "Net Amount at Risk – is the difference between
  the Death Benefit and the Policy Value").
- **From the filing** — document-derived.
- **Derived** — compiled by transcribing a filed table.
- **Carried over — no filed statement** — materialized from
  pre-doctrine workspace state; nothing filed stands behind it.
- **Entered in this workspace** — actuary-authored or a correction.

Step states are composed once, server-side, into the mechanics-panel
payload (`structure`), so the structure view and the Decisions
checklist derive from one composition: **settled** (equation + needed
tables in effect), **choice** (more than one evidenced reading, or an
incumbent whose body differs from a document-derived candidate),
**approval** (one reading awaiting approval), **carried** (the
operative reading is carried over with no filed statement),
**not in documents** / **stated but not extracted** (the gap-semantics
coverage states, reused verbatim). The header reads "Product
structure: N of 7 steps settled · M choice(s) awaiting you".

## Choices are explicit, and choosing is the approval act

Where a step's equation has multiple readings, the step presents them
as named option cards (radio choice): typeset formula, "In words"
caption, evidence, provenance chip. Selecting an option — with an
inline confirmation — is the approval act, recorded in the change
history under the option's identity; switching later is the same act.

Projection runs stamp the chosen option per step into the run record
(`definitionsUsed` / `definitionsLine` on the projection view), and
the ledger names the definitions a run used.

## The bulk seam fix

On ws-f107485a the factor-adjusted NAR reading — carried over from
pre-doctrine state, no filed statement — was bulk-approved as
"uncontested" while the policy form's own definition waited as a
replacement proposal. `plan_bulk_approval` now compares formula
bodies across every reading of a mechanic: whenever an incumbent or
candidate reading's body differs from a document-derived candidate's
body — including a carried-over incumbent, including an incumbent
already in effect — the slot is contested, excluded from bulk, and
named with BOTH readings. Bulk items carry their provenance class;
the summary names carried-over items as such. `apply_bulk_approval`
re-checks for a divergent record mid-batch.

## Tests

`src/actuarypoc/tests/test_product_structure.py` (13 tests): declared
order/grouping and the Also-found group; every step state, including
choice-by-incumbent-divergence and carried; provenance-class
assignment; bulk exclusion for a divergent incumbent with both
readings named; option selection recording history and the projection
run stamp. Suite: 423 passed / the same 5 inherited failures; tsc at
the 2 pre-existing errors; render contract 24/24.
