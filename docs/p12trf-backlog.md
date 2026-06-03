# P12TRF Backlog

## P12TRF Product Model Review – MVP Validation

Short validation note for the P12TRF Product Model Review MVP slice:

- Deployed image digest (projection-ui):
  - `ghcr.io/billyridgway/actuarypoc@sha256:846a0d7b72443711d665900f1659c41966c1418a498f9ea9e87b2295fd7a2987`
- POST endpoint exercised from the k3s cluster:
  - `POST /api/product-model-review/P12TRF/decision`
- Persisted response from the live endpoint included:
  - `id = 1` (non-null)
  - `created_at = 2026-06-02T22:06:44.804800+00:00` (non-null)
  - `decision = "approve_for_poc"`
- The FastAPI handler calls `record_product_model_review_decision(...)`, which performs a single
  `INSERT INTO product_model_review_decisions (...) VALUES (...) RETURNING id, product_code, reviewer, decision, exclusions, comments, created_at`.
  The non-null `id` and `created_at` in the response confirm the row was materialised by Postgres
  via this `RETURNING` clause, not fabricated by the UI or API layer.

## MVP Status

Completed for P12TRF Product Model Review MVP:

- Trust Surface Review Summary
- Scenario Evidence
- Scenario Drill-Down
- Decision Persistence (POST `/api/product-model-review/{product_code}/decision` with Postgres-backed storage)

Remaining / next candidate slices:

- **True policy input persistence** – persist real age / sex / smoker / term inputs into projection artefacts / PAS snapshot and surface them directly in the Trust Surface.
- **Meaningful P12TRF scenario catalog** – distinct scenarios with different business cases and inputs, each wired to its own projection artefact.
- **Rate reconciliation drill-down** – expose a richer view of the internal rate reconciliation (beyond the current aggregate counts and simple spot checks).
- **Coverage matrix** – visual matrix relating product features / scenarios to evidence and known gaps for P12TRF.

## Persist true policy inputs into projection artefacts / PAS snapshot

### Status

- **Implemented in code and image** (projection-ui digest `ghcr.io/billyridgway/actuarypoc@sha256:89950259e2072e12ea15373ff89061839484dfe7931d76f197973862aab68cd9`):
  - `build_projection_summary(...)` now writes a `policy_inputs` block under `summary.inputs` containing:
    - `issue_age`, `gender`, `smoker_class`, `risk_class`, `level_period`, `face_amount`, `premium_mode`.
  - `build_p12trf_projection_summary(...)` does the same for the P12TRF sample path using `policies_p12trf.csv`.
  - `build_input_snapshot_from_summary(...)` already copies `summary.inputs` verbatim, so `policy_inputs` is preserved in the input snapshot artefact.
  - `_build_run_detail(...)` now:
    - Prefers real PAS fields when present.
    - Falls back to `inputs.policy_inputs` only when PAS fields are missing / defaulty (`""` / `0` / `None`).
    - Leaves values at their existing defaults when neither PAS nor `policy_inputs` supplies a value (no fabrication).
  - `_build_p12trf_scenarios_and_rates(...)` continues to read from `RunDetail.policy_input.core_fields`, so when upstream inputs are present, Product Model Review scenarios automatically surface real values.

- **Runtime verification (Pi k3s cluster)**:
  - Deployed the new image and confirmed that `/api/product-model-review/p12trf` remains healthy and that the `policy_inputs` preservation path is live in the container.
  - Existing P12TRF projection artefacts referenced by S1/S2 were created *before* `policy_inputs` was added, and the PAS snapshot for those runs does not carry rich policy fields beyond `face_amount` and `premium_mode`. As a result, S1/S2 still show `"unknown"` for age/sex/smoker today, which is now an honest reflection of the upstream data rather than a drop in the Trust Surface plumbing.

### Acceptance criteria

- Projection artefacts (projection JSON + inputs snapshot and/or PAS export) include:
  - issue_age / age
  - sex / gender
  - risk_class and smoker_class
  - term / level_period
  - face_amount
  - premium_mode
- Product Model Review (`_build_p12trf_scenarios_and_rates`) uses those stored values directly instead of inferring from projection horizon or defaulting to `"unknown"` **for newly generated runs where upstream inputs are present**.
- Trust Surface no longer needs to infer `termYears` from projection years for P12TRF; it reads `level_period` (or equivalent) from the stored inputs when available, and only falls back to horizon-based derivation when `level_period` is truly missing.
- Scenario inputs only show `"unknown"` when the upstream source data truly lacks that field (not because the pipeline dropped it).

**Next operational step:** re-run the P12TRF projection Job (or regenerate the specific S1/S2 projection artefacts) under the new image so that their projection JSON objects gain a `policy_inputs` block populated from real policy data. Once that happens, the existing PMR wiring will surface real values for S1/S2 without further code changes.

## Create meaningful scenario catalog for P12TRF

Reason:

- Current Product Model Review scenarios S1 and S2 both point at the same underlying projection artefact: same face amount, term years, premium mode, and status.
- This is acceptable for the initial Trust Surface plumbing but does not yet represent distinct business cases.

Acceptance criteria:

- Define a small scenario catalog for P12TRF with clearly differentiated business cases (e.g. typical case, short term / young age, edge age / older issue).
- Each scenario is wired to a distinct projection artefact with its own policy inputs (age, sex/gender, smoker/risk class, term, face, premium mode).
- Product Model Review surfaces those distinct inputs and behaviours in the Scenario Evidence and Drill-Down sections.
- Documentation describes the intent of each scenario and how it maps back to PAS / projection inputs.
