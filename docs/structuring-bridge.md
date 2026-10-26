# The Structuring Bridge

Phase 8 — turning harvested filing statements into valid formula-language
equations. This document carries the diagnosis first (what actually failed
on a real filing, with evidence), then the build that answers it, then the
architecture account Billy asked for: what was restructured, what was
deliberately not, and what the next constraint is.

Mission context: Phase 7's doctrine says the only equations that execute
are document-derived and human-approved (or actuary-authored). Harvesting
is the front end of that doctrine — it reads the filing's stated
calculations and proposes them as pending equations. On the first real
filing it was pointed at (the Promise UL actuarial memorandum + policy
form + statement of variability, workspace `ws-720c39d2`, 78 slices), it
structured **zero** of thirteen captured statements. This phase is the
repair of that step, at whatever depth the evidence required.

---

## Part 1 — Diagnosis (reproduced locally, 2026-10-26)

Method: the workspace's actual slices were pulled from the app bucket
(via its documentMaps) and the production harvest path was re-run locally
against them with the app's real model configuration (gpt-4o-mini),
instrumented to capture the model's raw output, each parsed body, the
validator's exact rejection reasons, and locate success/failure per
reading. The thirteen live records were classified from their stored
sources/notes; a fresh instrumented run (12 readings) confirmed the
classes and added two.

### The thirteen live records, classified

| # | Mechanic | Statement (abridged) | Class |
|---|----------|----------------------|-------|
| 1 | coi_charge | "Maximum Cost of Insurance Rates are shown in Appendix 2." (memo p.2) | C — model returned no body |
| 2 | coi_charge | COI annual→monthly conversion formula (quoted with Unicode math 𝑞𝑥) | B — quote not locatable |
| 3 | coi_charge | "…monthly COI rate does not exceed the lesser of {1 − (1 − qx)^(1/n)} / … or 1/n…" (memo p.2) | C — model returned no body |
| 4 | surrender_charge | "The Cash Surrender Value is the Policy Value less any Surrender Charge." (model quote) | B — quote not locatable |
| 5 | surrender_charge | "Surrender Charges are set to meet nonforfeiture limits…" (memo p.1) | C — no body (and not a calculation) |
| 6 | surrender_charge | "The Surrender Charge is equal to a specific amount that varies with the issue age and gender… for each $1,000 of a policy's initial Face Amount in accordance with the schedule shown in A…" (model quote) | B — quote not locatable |
| 7 | surrender_charge | "The Surrender Charge decreases by equal annual decrements until it reaches zero…" (model quote) | B — quote not locatable |
| 8 | premium_load | "A Premium Expense Charge is applied to each premium. The Premium Expense Charge is currently set at 10% for new issues." (memo p.2) | C — model returned no body |
| 9 | premium_load | "The Expense Charge is calculated as a monthly amount per $1,000 of face amount and varies by issue age, gender, risk class and face amount." (model quote) | B — quote not locatable (and mis-filed: it is the monthly expense charge, i.e. policy_fees) |
| 10 | policy_fees | "An Administrative Charge is deducted at the beginning of each policy month until the insured has attained age 121." (form p.2) | D — body returned, failed validation |
| 11 | death_benefit | "The Death Benefit under this Policy is subject to any increase required to qualify the Policy as Life Insurance…" (form p.5) | C — model returned no body |
| 12 | death_benefit | "Minimum Death Benefit – …determined based on the Death Benefit Qualification Test…" (model quote) | B — quote not locatable |
| 13 | death_benefit | "The Minimum Death Benefit is equal to the Minimum Death Benefit Percentage multiplied by the Policy Value." (model quote) | B′ — quote is a model synthesis; the phrase exists nowhere in the documents |

Plus two mechanics with **no records at all**:

| Mechanic | Finding |
|----------|---------|
| crediting | **Stated but missed.** Memo p.1: "The annual credited rate will not be less than the Guaranteed Minimum Annual Interest Rate shown in the Policy Specification which is currently set at 2% for new issues." The model never returned a crediting reading in any run. |
| nar_definition | **Stated but missed.** Form p.3/p.4: "Net Amount at Risk – is the difference between the Death Benefit and the Policy Value." The deterministic NAR pattern requires *less/minus/reduced by … account value*; the filing says *difference between … policy value*, so the pattern could not fire, and the model never returned it either. |

### Failure classes

**B — Locate brittleness (6 of 13).** `_locate_statement` matched the
model's quote word-exact (`\s+` between words) against slice text. The
PDF text layer splits words mid-word — the slices literally contain
"surrende r", "policy va lue", "decrease s by equal annual decrements",
"spec ific", "gua ranteed" — so a faithfully-copied quote still fails
when the model's copy normalizes a split ("decreases" vs the text's
"decrease s") or the wording drifts at the edges ("is equal to the pv"
in the memo vs the model's "is the Policy Value", which is the *form's*
sentence modulo a split word). Verified: whitespace-stripped containment
finds #4, #6, #7, #9, #12 in the joined slice text; #2's formula is
present in the memo's own text with Unicode math glyphs (𝑞𝑥), which
NFKC folding resolves. The locate gate did its provenance job — it
refused to present model words as the filing's — but its matching was
stricter than the evidence required.

**B′ — Model synthesis (1 of 13).** #13's sentence exists nowhere in
the three documents. The underlying mechanic is real (Option A + the
§7702 Cash Value Accumulation Test floor; "The Minimum Death Benefit
Percentages … are shown in the Policy Specifications", form p.4), but
the quoted sentence is the model's synthesis of it. Correct outcome:
never recorded as the filing's words; the corridor is captured from
statements that do exist (#11 + memo p.1's Option A statement).

**C — The model declined to structure (5 of 13).** With a located
statement, the model returned `body: null` — including #8, a flat
"10% of each premium" that is one multiplication. The prompt describes
the formula language in prose with no worked examples and no canonical
templates, so the model had nothing to anchor on and defaulted to
declining. In the instrumented re-run it did the opposite error where
it tried at all (class D) — the two classes are the same root cause:
free-form body invention from a prose spec is the wrong contract.

**D — Wrong body dialect (1 of 13 live; 2 of 2 attempted bodies in the
re-run).** The bodies the model did produce used
`{"operator": "mul", "operands": [...]}` instead of `{"mul": [...]}`
and lookup tables named with the prompt's own prose notation
(`"coi(rate)"`, display-name fields). The validator's rejection —
"Each formula node must be an object with exactly one operator key" —
is precise and was recorded on record #10, then never used. There was
no repair loop.

**E — Model I/O fragility (harvest #1).** One mega-call carried all 49
calculation-bearing slices (~125K characters, ~48K prompt tokens
measured) with no `response_format`, a bare `json.loads`, and a 45s
timeout. It died with a JSONDecodeError that surfaced only as
"Model harvest unavailable (JSONDecodeError); deterministic readings
only." Nothing — no raw output, no finish reason, no content length —
was retained, so the precise trigger is unrecoverable after the fact.
That unobservability is itself a defect this phase fixes. (The re-run's
output arrived fence-wrapped and non-deterministic in scope: 12
readings, a different subset of statements than the live run's 13 —
coverage by lottery over a 49-slice prompt.)

**F — Coverage blindness (crediting, NAR).** Two stated calculations
were never returned by the model across three runs, and the
deterministic net was too narrow to catch them (NAR verb vocabulary;
no crediting pattern at all; the calculation-slice keyword gate lacks
"interest will be credited" / "annual credited rate" / "guaranteed
minimum annual interest rate"). A silent blank is the one outcome the
doctrine forbids — the harvest must account for every mechanic,
including "not stated in these documents."

**G — The reasons were recorded but unreachable.** Unmapped records
store the specific reason in `source.note`, but (a) the model's
rejected body was discarded (`body: None` stored), (b)
`equations_view` substituted a generic paragraph for the record's own
note in the conflicts list, and (c) the web pane rendered that same
generic paragraph on every unmapped card. The "why" existed in the
data and could not be seen in the product.

**H — Adjacent, not bridge-owned: the table channel is empty for this
workspace.** The mechanics pipeline extracted **zero** candidate or
usable tables from a memo whose Appendix 2 is a COI rate table and
whose form carries surrender/expense tables as text (all present in
slices as raw text). Table-shaped calculations (the COI charge, the
surrender schedule) therefore have no table to transcribe from yet.
The bridge's rule, set by the no-silent-zero invariant: a lookup body
is proposed only when its table is actually in the workspace's usable
set; otherwise the statement stays unmapped with the actionable reason
(the table has not been extracted/accepted — do that first). Fixing
table extraction itself is a separate build; it is named here as the
next constraint, not silently absorbed.

### What the statements actually need (per-statement disposition)

- **premium_load #8** — deterministic: `premium due × 0.10` (const
  body; the stated rate is in the words, not in a fee table this
  workspace doesn't hold). → pending.
- **policy_fees #10** — `policy_fees_body()` (the canonical rows_sum
  over the fee schedule; the statement states the monthly deduction,
  the schedule carries amounts). The model's malformed attempt is what
  the repair loop exists for; a deterministic pattern also fires. →
  pending.
- **crediting** — `crediting_body()` (account value × monthly
  conversion of the guaranteed annual rate), sourced to memo p.1's 2%
  guarantee statement. → pending.
- **nar_definition** — `nar_body("unadjusted")` =
  max(death benefit − account value, 0), sourced to the form's
  definition sentence. → pending.
- **death_benefit #11** — `death_benefit_body()` =
  max(face, corridor % × account value), sourced to memo p.1's
  Option A statement ("Death Benefit = Face amount. In no case will
  the death benefit be less than the amount required to qualify under
  Internal Revenue Code Section 7702…") + #11. → pending.
- **coi_charge #1/#2/#3** — the charge calculation itself ("equal to
  (1) multiplied by (2)", form p.10) is a table lookup whose table is
  not in the workspace (class H); #2/#3 state how the table's monthly
  rates are *derived* from annual mortality — a derivation of the
  table, not the charge, and the language has no mortality quantity
  distinct from the table's rate. → located, recorded, unmapped with
  those precise reasons.
- **surrender_charge #6/#7** — a per-$1,000 schedule charge grading by
  equal annual decrements: the equation is the schedule table's
  lookup, and the table is not in the workspace (class H). →
  unmapped with that reason. **#5** states a purpose (nonforfeiture),
  not a calculation → unmapped, reason says so. **#4** defines the
  cash surrender *value* net of the charge, not the charge →
  unmapped, reason says so.
- **#9** — the monthly expense charge's amount basis (per $1,000 of
  face, varying by issue age/gender/class): located; it belongs to
  policy_fees (mis-filed by the model) and its amounts are the fee
  schedule's — accounted under policy_fees' pending, with the
  mis-filing named. **#12** — locates (form p.4, the Qualification
  Test passage); qualitative pointer to the §7702 test → unmapped
  with reason; the corridor it points at is #11's pending. **#13** —
  stays an unlocated model claim, visibly a claim, never the filing's
  words.

---

## Part 2 — The build

All changes are in the harvest path; the doctrine invariants are
untouched (nothing executes unapproved, unmapped stays visible,
harvesting never auto-approves).

1. **Canonical-text matching** (`_canon` in
   `extract/workspace_equations.py`): every slice gets a canonical
   form — NFKC-folded (Unicode math 𝑞𝑥 → qx, curly quotes/dashes
   folded), all whitespace removed — with an index map back to the
   original text. `_locate_statement` and the deterministic patterns
   match against the canonical form; the recorded statement is the
   *slice's own sentence* around the mapped span, so provenance is the
   filing's extracted words, never the model's cleaned-up copy.
   Patterns are authored once and compiled to canonical regexes
   (spaces dropped, `\s` dropped), so the same pattern text works on
   clean and split-word text alike.

2. **Deterministic assists, second generation** — narrow patterns in
   the Phase 4 philosophy (a wrong fire costs trust; a no-fire costs
   a manual path), each with the real filing sentence as its test:
   premium expense charge stated as a percentage; administrative
   charge deducted monthly; guaranteed credited rate ("will not be
   less than the Guaranteed Minimum Annual Interest Rate … currently
   set at N%"); NAR defined as "the difference between the death
   benefit and the policy/account value" (the existing less/minus
   pattern kept); death benefit stated as "= face amount" with a
   §7702/qualify floor in the same slice. Plus an artifact-aware
   table-pointer step: a statement that points at a rate/schedule
   table yields the canonical lookup body **only if** that table is
   in the workspace's usable set; otherwise an unmapped candidate
   whose note names the missing table as the blocker.

3. **Model contract: templates, not invention.** The prompt now
   carries the canonical body for every mechanic (the builders'
   actual JSON), the exact node grammar with two worked examples,
   and a per-mechanic checklist of statement shapes to scan for
   (definition sentences of the form "X – is the difference
   between…", percentage-of-premium charges, monthly deductions,
   credited-rate guarantees, death-benefit option statements). The
   model's job is re-framed: pick the template that matches the
   statement, fill its stated parameters (a const for a stated
   percentage), or return null. Verbatim discipline is explicit:
   copy the statement exactly as printed, odd spacing included.

4. **Model I/O that cannot silently produce garbage.**
   `default_model_caller` now batches by document under a character
   budget (no more 49-slice mega-call), requests
   `response_format: json_object`, parses tolerantly (fence-strip,
   then first balanced object) as a stated fallback order, and on
   failure raises with the cause named — finish reason, content
   length, first characters — which the harvest warning carries
   verbatim. A truncated batch (finish_reason "length") is split and
   retried once. The timeout default rises to 120s per (smaller)
   batch call; still env-configurable.

5. **The repair loop.** Before candidates are applied, every located
   model reading is validated. A reading whose body fails validation,
   or that returned null where a template plausibly applies, gets up
   to two repair attempts: the model is handed the statement, its own
   body, the validator's exact errors, and the canonical templates,
   and asked for a corrected body (or an honest null). Attempts are
   logged in the harvest result's `repairLog`. A reading that still
   fails stays unmapped with its last validation errors **and** its
   rejected body recorded on the record (`source.validationErrors`,
   `source.rejectedBody`) — the why is data, not folklore.

6. **Upgrade and supersede, so re-harvesting heals.** If a candidate
   with a valid body arrives for a statement already recorded as
   unmapped, the unmapped record is superseded and the pending record
   created — history preserved, nothing silently rewritten. A
   previously unlocatable model claim whose text canon-matches a
   newly located statement is likewise superseded by it. New
   unlocatable claims store the claim in `source.claimedStatement`
   (it previously lived only inside a prose note).

7. **Coverage accounting.** The harvest result (and the endpoint's
   `harvest` block) now carries `coverage`: every mechanic with no
   record after the run is named with its class — "no statement
   found in these documents" — instead of a silent blank. Mechanics
   with records are not listed; the pane already shows them.

8. **The pane shows the why.** `equations_view`'s unmapped conflict
   entries now carry the record's own `source.note` when one exists,
   and the web pane renders that note on the unmapped card in place
   of the one-size paragraph (the generic text remains as the
   fallback when no note was recorded). The harvest block in the API
   response also carries `coverage` and the repair count.

### Deliberately not done

- **Table extraction** (class H) is untouched: why the mechanics
  pipeline produced zero candidate tables from these documents is a
  separate diagnosis. The bridge names it as the blocker on the two
  table-shaped mechanics rather than absorbing it.
- **The PDF text layer's split words** are matched around, not
  repaired: the stored statement remains the document's text as
  extracted. Repairing extraction itself belongs to the slice
  pipeline and would change evidence under every existing record.
- **`ui/server.py` was not split.** The monolith is real (15.9K
  lines) but nothing in this failure traces to it — the harvest
  endpoint is a thin pass-through. Splitting it now would be the
  cosmetic rewrite Billy's latitude explicitly is not.
- **No new mechanics, no language operators were needed.** The
  diagnosis found no statement whose calculation the existing
  language cannot express once the table exists; the mortality
  conversion (#2/#3) is a derivation *of* a table, and it stays
  recorded-but-unmapped for that stated reason rather than growing
  a mortality quantity the chassis has no data for.

### The next constraint

Table extraction for this filing family (class H). Until the COI
rate table and the surrender schedule exist in the workspace as
usable tables, two of the seven mechanics can be *read* but not
*transcribed*, and their equations — however approved — would have
nothing to look up. After that: the Policy Specifications document
(the corridor percentages' home) is not among this workspace's three
documents; adding it through the picker would let the death-benefit
corridor cite its percentages directly instead of through the
§7702 statements.

## Part 3 — As built, and what the rehearsals changed

Built in `extract/workspace_equations.py` (the harvest path only),
plus a two-line pass-through in `ui/server.py` and a note-rendering
change in `web/EquationsPanel.tsx`. No module was split and no
language construct was added: the diagnosis indicted the harvest
path, so the harvest path is what changed.

Two refinements the implementation forced, both verified against
the real slices before they were kept:

- **Statement-containment in the upgrade match.** The deterministic
  assists and the located model reading choose different spans of
  the same filing words (passage vs sentence), so exact
  `statementKey` equality alone would have left the premium and
  admin records unhealed. The upgrade and note-refresh paths also
  match an unmapped record whose statement is contained in — or
  contains — the candidate's, in loose canonical form.
- **Claim comparison is loose-canonical.** Punctuation drift (an
  en-dash the claim dropped) must not defeat the claim-supersede
  comparison; alphanumerics-only canon is used for that comparison
  only, never for matching or validation.

One correction to Part 1, delivered by the bridge itself: **record
#13 was not model synthesis.** The sentence — "The Minimum Death
Benefit is equal to the Minimum Death Benefit Percentage
multiplied by the Policy Value" — IS in the form (p.5), with
"Mi nimum" split by the text layer. The diagnosis's own containment
search missed it for exactly the brittleness class B describes;
class B′ is empty and is withdrawn. Canon search finds it, and it
now harvests as a located statement.

Three guardrails were added after the first full rehearsal against
the real artifact (32 readings, 27 repair attempts) showed the
tightened prompt had overshot — the model, given templates,
structured things it should not have:

1. **Repair translates, never invents.** Repair is attempted only
   for invalid bodies (not nulls — with templates in the prompt, a
   null is a decision), at most twice, and a repaired body is
   adopted only if its leaf content (quantities, constants,
   strings, table references) matches the proposed body's,
   allowing only renames of invalid quantity names into valid
   ones. Repair attempts fell from 27 to 2 in the second
   rehearsal, and the invented bodies disappeared with them.
2. **Anchor check.** A located model reading whose statement never
   mentions the mechanic it was filed under is recorded as a
   misfiling, never structured (the rehearsal filed a Net Cash
   Surrender Value sentence under `nar_definition` with an
   invented body; it is unmapped now, with the reason).
3. **The no-silent-zero rule binds every candidate.** A body
   containing a default-less lookup on the `coi` or `surrender`
   table is refused while that table is not in the workspace's
   usable set — from the model exactly as from the deterministic
   pointers — and recorded unmapped with `blockedReason:
   table_not_extracted` and the proposed body kept as evidence.
   Defaulted lookups state their own absence and are unaffected.
   A model reading also may not supersede the bridge's own
   pointer/capture record for the same statement: the caution
   stands until a deterministic reading (or the table itself)
   supersedes it.

What the rehearsals proved, against the real ws-720c39d2 artifact
and slices with the production model configuration: the harvest
completes with no warnings and no coverage gaps; the premium
expense charge and the administrative charge structure
deterministically as pending (`premium due × 0.1`; the fee-schedule
rows sum), as do crediting, the NAR definition, and the
death-benefit corridor; every one of the original 13 records is
accounted for — superseded by a structured reading of the same
words, or still unmapped with its reason recorded (one, the form's
§7702 qualification statement, keeps the generic reason; its
corridor is structured from the Option A statement beside it). The
model's free-form COI transcriptions of the form's "(1) multiplied
by (2)" statement varied between runs and are not relied on: COI
pends on the table, which is the next constraint named above.
Model coverage beyond the deterministic core is a lottery in both
directions (extra boilerplate statements filed as unmapped
readings; the reviewer rejects them) — the deterministic core is
the trustworthy yield, and nothing the model proposes executes
unapproved.
