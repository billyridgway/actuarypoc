# P12TRF Backlog

## Persist true policy inputs into projection artefacts / PAS snapshot

Acceptance criteria:

- Projection artefacts (projection JSON + inputs snapshot and/or PAS export) include:
  - issue_age / age
  - sex / gender
  - risk_class and smoker_class
  - term / level_period
  - face_amount
  - premium_mode
- Product Model Review (`_build_p12trf_scenarios_and_rates`) uses those stored values directly instead of inferring from projection horizon or defaulting to `"unknown"`.
- Trust Surface no longer needs to infer `termYears` from projection years for P12TRF; it reads `level_period` (or equivalent) from the stored inputs.
- Scenario inputs only show `"unknown"` when the upstream source data truly lacks that field (not because the pipeline dropped it).

## Create meaningful scenario catalog for P12TRF

Reason:

- Current Product Model Review scenarios S1 and S2 both point at the same underlying projection artefact: same face amount, term years, premium mode, and status.
- This is acceptable for the initial Trust Surface plumbing but does not yet represent distinct business cases.

Acceptance criteria:

- Define a small scenario catalog for P12TRF with clearly differentiated business cases (e.g. typical case, short term / young age, edge age / older issue).
- Each scenario is wired to a distinct projection artefact with its own policy inputs (age, sex/gender, smoker/risk class, term, face, premium mode).
- Product Model Review surfaces those distinct inputs and behaviours in the Scenario Evidence and Drill-Down sections.
- Documentation describes the intent of each scenario and how it maps back to PAS / projection inputs.

