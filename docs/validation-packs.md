# Validation packs

Phase 5 of the Eddy improvement plan. Eddy's working discipline is
"refine, refine until it matches": actuaries keep test cases with
expected results and check the model against them, because three
systems — admin, illustration, actuarial models — must agree, and
auditors back the math out of the contract. A **validation pack** is
that discipline as product data.

## The pack format

A pack is a versioned JSON document (format version 1), stored with
the workspace in the object store under
`workspaces/{id}/validation/packs/{packId}.json`, alongside the
analysis artifacts. It is validated whole on write — accepted complete
or rejected with every problem named.

```json
{
  "formatVersion": 1,
  "name": "Promise UL filed-mechanics pack",
  "version": "1.0",
  "productCode": "ICC18 P18PR UL",
  "defaultTolerances": { "absolute": 0.01, "relative": 0.0 },
  "cases": [
    {
      "id": "filed-base-case",
      "name": "Filed base case, age 45, $100k",
      "inputs": {
        "issueAge": 45, "faceAmount": 100000,
        "premiumMode": "ANNUAL", "modalPremium": 3600
      },
      "mechanics": { "mode": "workspace" },
      "expectations": [
        {
          "duration": 1, "field": "surrenderCharge", "value": 1250.00,
          "source": {
            "description": "Filed surrender schedule, $12.50 per $1,000 of face",
            "document": "filing.pdf", "page": 3
          },
          "tolerance": { "absolute": 0.02 }
        }
      ]
    }
  ]
}
```

- **Cases** carry the scenario inputs (the same shape as the
  workspace projection request) and the mechanics state they assume:
  `"workspace"` runs against the workspace's current slot state;
  `"pinned"` carries an exact executable-mechanics state in
  `mechanics.executableMechanics`, so the case means the same thing
  forever regardless of later edits.
- **Expectations** name a duration and a field from the registry
  (`accountValue`, `beginningValue`, `premium`, `premiumLoad`,
  `policyFee`, `coiCharge`, `interestCredited`, `surrenderCharge`,
  `surrenderValue`, `deathBenefit`, `netAmountAtRisk`,
  `cumulativePremium` — new fields enter via the registry in
  `extract/workspace_validation_packs.py` only).
- **Every expectation must state its source** — where the expected
  value comes from (filing page, carrier illustration, admin-system
  export). An expectation without provenance is rejected: an unsourced
  number is not an authority, and validation against an unknown
  authority is theatre.
- **Tolerances** are per expectation, falling back to the pack's
  `defaultTolerances`. The band is `max(absolute, relative ×
  |expected|)`; a result passes when `|actual − expected|` is within
  the band.

## Running a pack

`POST /api/workspaces/{id}/validation-packs/{packId}/run` executes
each case through the same projection path as the diagnostic
projection endpoint and reads actuals from the **Phase 1 ledger** —
the same numbers the product shows, produced the same way. The runner
is deterministic and involves no model.

Each result records the expected value, the actual, the signed delta,
the tolerance band it was judged against, and the **ledger basis** of
the actual — filed, synthetic, workspace table, corrected,
placeholder, scenario, or calculated. A mismatch on a filed line is a
genuine triage item; a mismatch on a placeholder or synthetic line
explains itself in the report ("this number rests on a stand-in, not
a filed value"), and every stand-in line is listed in the report
whether it passed or not. That basis accounting is what lets an
actuary know exactly which numbers in a run rest on placeholders.

## The run report

Each run is stored at `workspaces/{id}/validation/runs/{runId}.json`
and is the audit artifact:

- pack identity (id, name, the pack author's version, format version),
  workspace, product;
- who ran it and when;
- the engine state: ledger version and the **rule-bank switches the
  run executed** (from Phase 4's applied-mechanics records);
- per case: the inputs, the mechanics mode, a **fingerprint** of the
  exact mechanics state the case ran against, and the full
  expected-vs-actual table;
- the summary: pass/fail per case and per expectation, and counts of
  actuals by basis;
- versus the previous run of the same pack: which expectations newly
  fail, which newly pass, and which cases' mechanics changed — the
  regression story when a slot is edited, a correction is applied, or
  the bank grows.

Exports: `GET .../validation-runs/{runId}` (JSON) and
`GET .../validation-runs/{runId}/report.txt` (a human-readable
rendering for the audit file).

## The regression role

Packs persist per product with the workspace. The workflow they exist
for: run the pack before changing anything; make the slot edit /
correction / bank change; run it again. The second report names what
moved — an expected consequence shows up as understood, an unexpected
one shows up as a newly-failing expectation with its delta and its
basis. A pack that cannot fail is not a check; the deliberate-error
test in `tests/test_workspace_validation_packs.py` (perturb the filed
surrender charge by $2.50 per $1,000 and watch exactly the surrender
expectations fail by exactly $250) is the standing proof that these
packs bite.
