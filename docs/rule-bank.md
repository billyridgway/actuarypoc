# The rule bank — SUPERSEDED by Phase 7 (the equation doctrine)

> **This document describes a retired design.** Phase 7 (Oct 2026)
> abolished the rule bank: there is no switch library, and no fallback
> or placeholder calculation exists as a safety net. The only
> equations that execute are document-derived and human-approved (or
> actuary-authored) equation artifacts, plus the universal identities
> that every document assumes. See `docs/phase-7-equations.md`. The
> text below is kept as the historical record of the Phase 4 design.

Phase 4 of the Eddy improvement plan. The bank is how "teach it every
market variation" happens: every way a covered mechanic can vary —
COI rate units and deduction timing, net-amount-at-risk definitions,
surrender bases and schedule shapes, fee units, crediting conversion —
is a **banked switch** in `src/actuarypoc/domain/rule_bank.py`, and the
projection engine only ever executes banked implementations.

## What a banked switch is

Each entry in the registry (`rule_bank.SWITCHES`) carries:

- a **stable id** (`coi.timing.end`, `surrender.schedule.banded`, …) —
  ids are recorded in projections' applied-mechanics annotations and in
  ledger derivations, so they never change once shipped;
- the **mechanic** it belongs to and its **kind** (rate unit, timing
  step, NAR definition, surrender basis, fee unit, crediting,
  schedule materializer, placeholder);
- an **actuarial plain-language description** — what an actuary would
  call this variation, shown in the panel and used in confirm-backs;
- a **parameter schema** (`ParamSpec`s) that validation runs against;
- the **deterministic implementation** the engine dispatches to.

## The engine-purity rule

The UL projection loop contains no per-unit formula branches. It asks
the bank: the charge for this rate unit, the NAR under this definition,
the month step for this timing, the charge for this surrender basis,
the monthly fee for this fee unit. Asking the bank for something it
does not hold raises — the engine never improvises a meaning for an
unbanked unit, timing, or basis.

Anything with no banked switch behind it is a **labeled placeholder**,
never a silent formula: the no-COI-table charge is
`coi.placeholder.flat_face`, the no-surrender-schedule charge is
`surrender.placeholder.linear_account_value`, and the no-fee-rows
fallback is `fees.fallback.configured_annual`. The ledger labels those
lines `placeholder` and names the placeholder switch, so a reviewer can
always tell a real filed/corrected value from a stand-in.

## How a variation enters the bank

A variation enters the bank only as **code + tests in this repo**:

1. Implement the deterministic function in `rule_bank.py` (pure
   arithmetic, no I/O, no model calls).
2. Register it in `SWITCHES` with its stable id, plain-language
   description, and parameter schema.
3. Add tests in `tests/test_rule_bank.py`: the implementation against
   hand-computed values, the registry completeness checks (every unit
   vocabulary in `workspace_ul_mechanics` maps to a switch), and — if
   the switch is reachable from a correction variant or a proposal —
   the confirm-gated flow that sets it.
4. If users set it, surface it through the existing governed paths
   only: a Phase 2 slot value, a Phase 3 correction variant (which
   names its `bankSwitches`), or a Phase 4 extraction proposal. There
   is no other way for a switch to take effect.

Corrections and slot defaults resolve through the bank: the correction
module's timing/definition/basis vocabularies are the bank's, its
graded and banded materializers are the bank's, and the projection
loop dispatches through the bank. Refactor toward the bank; never
duplicate a formula beside it.

## Piecewise (banded) schedules

Eddy's hard case — a rule that changes by duration band ("years 1–10
one rule, thereafter another") — is banked as schedule materializers
(`surrender.schedule.banded`, `coi.schedule.banded`). A band set is
validated strictly: bands start at year 1, join with no gaps or
overlaps, only the final band is open-ended, units are banked units,
and values are in sane ranges. A band may grade linearly to a second
value across its span. The materializer emits one ordinary schedule
row per duration, each tagged with its band, so the projection loop
stays a plain table lookup and the **ledger derivation names the band
applied for each period**.

## Extraction proposals

Proposals (`extract/workspace_mechanics_proposals.py`) are how a new
product gets onboarded without hand-building its inputs: deterministic
signals from the filing — extracted table candidates, stated factors,
schedule shapes, prose statements of timing/definition/basis — become
proposals with page evidence, presented in the panel. The Phase 3
confirm-back discipline governs them: a proposal restates the change
in actuarial language and applies only on confirmation, through the
same acceptance/correction paths as the manual action, with the
proposal's evidence in the applied record's provenance.

A configured model may help **author** a proposal, but a proposal is
data, not authority: the mapping is confirmed by the actuary, nothing
applies unconfirmed, and with no model configured the deterministic
proposals still work. The projection path never sees proposals — only
confirmed mechanics.

One deliberate exclusion: there are no crediting-rate proposals. The
crediting slot is display-only — the guaranteed rate comes from the
product's assumption set, not from a mechanics switch an actuary
confirms in this panel — so proposing it here would create a second,
divergent source for the same number.
