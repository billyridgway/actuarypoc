---
name: "Bug"
about: "Report a defect in the illustration backend, projection engine, or UI"
labels: ["bug"]
---

## Problem statement

Describe the bug in business terms first:

- What did you expect to happen?
- What actually happened?
- Which product(s) and scenario(s) are affected (e.g. P12TRF, horizon 40)?

Avoid including real policyholder data; if needed, reference anonymized IDs
or test cases.

## Acceptance criteria

- [ ] Bug is reproduced in a controlled test (unit/integration)
- [ ] A clear fix is implemented and tested
- [ ] Regression tests are added/updated so this does not silently return
- [ ] Any relevant docs (architecture/DoD/knowledge) are updated

## Technical notes

- Suspected components (files/modules)
- Relevant logs or error messages (redacted)
- Any correlation with specific MinIO objects or CRD status (by key/name)

Do **not** paste secrets, raw PAS exports, or full projection JSONs. Use
minimal, anonymized examples.

## Test plan

- Unit tests to reproduce and then validate the fix
- Golden tests to ensure projections stay stable (or intentionally updated)
- k3s validation: which `IllustrationProject` / projection object will be
  used as a smoke test?

## Audit considerations

- Does this bug indicate missing or incorrect assumptions?
- Do we need to flag past runs as suspect (e.g. via notes in audit records
  or docs)?
- Should RunDetail or the UI surface any additional warnings going forward?
