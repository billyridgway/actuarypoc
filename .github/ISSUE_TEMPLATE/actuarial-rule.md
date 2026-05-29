---
name: "Actuarial rule"
about: "Capture or change a specific actuarial rule/assumption"
labels: ["actuarial-rule"]
---

## Problem statement

Describe the rule/assumption in actuarial terms:

- What rule is being added/changed (e.g. mortality basis, risk class mapping,
  premium modalization, reserve method)?
- Which products and filings does it affect?
- What is the source (SERFF memo, internal spec, spreadsheet, etc.)?

## Acceptance criteria

- [ ] Rule is documented in `docs/knowledge/` or relevant DSL/assumption
      metadata
- [ ] Code/DSL/AssumptionSets reflect the rule
- [ ] Golden tests (where applicable) updated to match the rule
- [ ] Any impacted projections are understood and, if needed, re-baselined

## Technical notes

- Pointers to DSL files, config, or AssumptionSets likely to be affected
- References to `FilingRecord` / `ProductDefinition` if known
- Any constraints (e.g. we only apply this rule for certain issue ages or
  states)

Do **not** include proprietary rate factors or confidential tables; reference
where they live (e.g. MinIO object keys) instead.

## Test plan

- Unit tests targeting the changed logic/rule
- Golden tests comparing projections before/after (if applicable)
- k3s validation: example `IllustrationProject` and projection run that
  should show the updated rule in action

## Audit considerations

- How should this rule change appear in AuditRecords and RunDetail?
- Do we need to link this change to a FilingRecord (e.g. new SERFF memo)?
- Should we annotate docs to flag that historical runs used a different rule?
