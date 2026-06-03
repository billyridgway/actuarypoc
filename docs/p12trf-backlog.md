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

**Operational verification (Pi k3s cluster, 2026-06-02):**

- Re-ran the illustration Jobs for `p12trf-e2e-operator-6` and `p12trf-e2e-operator-8` by:
  - Deleting their existing Jobs:
    - `illustration-p12trf-e2e-operator-6`
    - `illustration-p12trf-e2e-operator-8`
  - Patching the corresponding `IllustrationProject` specs to bump `spec.notes` and trigger a reconcile.
  - Observed new Jobs created and completed successfully, using the runner image:
    - `ghcr.io/billyridgway/actuarypoc:main` (imagePullPolicy `Always`, so latest digest including `policy_inputs` plumbing).
  - Confirmed the regenerated projection objects for S1 and S2:
    - `projections/p12trf/282101b0-3062-471c-be2f-e414c5dd06f7/projection.json` (S1)
    - `projections/p12trf/b5bb75ee-c635-4e2d-b0cf-8fd768a94cc5/projection.json` (S2)
    now contain an `inputs.policy_inputs` block with:
    - `face_amount = 450000`
    - `premium_mode = "Annual"`
    - other fields (`issue_age`, `gender`, `smoker_class`, `risk_class`, `level_period`) present but `null`.
- `/api/run-detail?key=...` for these projection keys now surfaces:
  - `policy_input.core_fields.face_amount = 450000.0`
  - `policy_input.core_fields.premium_mode = "Annual"`
  - `issue_age = 0`, `gender = ""`, `smoker_class = ""`, `risk_class = ""`, `level_period = 0` — reflecting the fact that the upstream PAS/export data used by `project-minio` does not currently carry those richer fields.
- `/api/product-model-review/p12trf` still reports S1/S2 `inputs` as:
  - `age: "unknown"`, `sex: "unknown"`, `smokerClass: "unknown"`,
  - `termYears: 20` (derived from projection horizon for now),
  - `faceAmount: 450000.0`, `premiumMode: "ANNUAL"`.

This confirms that the **Trust Surface plumbing no longer drops policy inputs** (they are preserved into `inputs.policy_inputs` and surfaced through RunDetail), and that S1/S2 now show `"unknown"` *only because the upstream PAS/export does not yet carry real age/sex/smoker/term fields for these runs*.

**Next data step:** enrich the P12TRF PAS/export source (or the `p12trf/` policies slice used for P12TRF projections) so that `issue_age`, `gender`, `smoker_class`, `risk_class`, and `level_period` are populated for the runs corresponding to S1/S2. Once the upstream data is present, the existing projection + RunDetail + PMR wiring will surface real values end-to-end without further code changes.

## Create meaningful scenario catalog for P12TRF

Reason:

- Current Product Model Review scenarios S1 and S2 both point at the same underlying projection artefact: same face amount, term years, premium mode, and status.
- This is acceptable for the initial Trust Surface plumbing but does not yet represent distinct business cases.

Acceptance criteria:

- Define a small scenario catalog for P12TRF with clearly differentiated business cases (e.g. typical case, short term / young age, edge age / older issue).
- Each scenario is wired to a distinct projection artefact with its own policy inputs (age, sex/gender, smoker/risk class, term, face, premium mode).
- Product Model Review surfaces those distinct inputs and behaviours in the Scenario Evidence and Drill-Down sections.
- Documentation describes the intent of each scenario and how it maps back to PAS / projection inputs.

### Status (configurable scenario inputs wired end-to-end)

- Added a configurable P12TRF scenario fixture at `examples/p12trf_scenarios.json` with three business cases:
  - **S1 – Typical mid-age non-smoker**
    - `issue_age = 35`, `gender = "M"`, `smoker_class = "NS"`, `risk_class = "SUPER_PREFERRED_NON_TOBACCO"`,
      `level_period = 20`, `face_amount = 450000`, `premium_mode = "ANNUAL"`.
  - **S2 – Young short-term coverage**
    - `issue_age = 30`, `gender = "F"`, `smoker_class = "NS"`, `risk_class = "STANDARD_NON_TOBACCO"`,
      `level_period = 10`, `face_amount = 250000`, `premium_mode = "ANNUAL"`.
  - **S3 – Edge older age smoker**
    - `issue_age = 60`, `gender = "M"`, `smoker_class = "S"`, `risk_class = "STANDARD_TOBACCO"`,
      `level_period = 10`, `face_amount = 100000`, `premium_mode = "ANNUAL"`.
- Implemented a CLI helper `project-p12trf-scenarios-minio` in `actuarypoc.cli.main` that:
  - Reads the fixture JSON.
  - Uses the P12TRF DSL (`dsl/examples/p12trf_term.yaml`) and Term23 mortality slice.
  - Projects each scenario policy and writes a projection summary to MinIO under:
    - `projections/p12trf/scenarios/S1.json`
    - `projections/p12trf/scenarios/S2.json`
    - `projections/p12trf/scenarios/S3.json`
  - Each summary includes `inputs.policy_inputs` mirroring the configured scenario inputs.
- Updated `_P12TRF_SCENARIO_CONFIG` in `ui.server` so Product Model Review uses these scenario artefacts instead of generic operator runs.

**Runtime verification (Pi k3s cluster, 2026-06-03):**

- Ran `python -m actuarypoc.cli.main project-p12trf-scenarios-minio` inside the `projection-ui` pod, producing:
  - `S1: projections/p12trf/scenarios/S1.json`
  - `S2: projections/p12trf/scenarios/S2.json`
  - `S3: projections/p12trf/scenarios/S3.json`
- Inspected the resulting projection JSON via `get_projection(...)` from within the pod and confirmed:
  - `inputs.policy_inputs` for each scenario exactly matches the configured fixture values (issue_age, gender, smoker_class, risk_class, level_period, face_amount, premium_mode).
- `/api/run-detail?key=projections/p12trf/scenarios/SX.json` now exposes:
  - `policy_input.core_fields.issue_age` ∈ {35, 30, 60}
  - `gender` ∈ {"M", "F"}
  - `smoker_class` ∈ {"NS", "S"}
  - `risk_class` ∈ {"SUPER_PREFERRED_NON_TOBACCO", "STANDARD_NON_TOBACCO", "STANDARD_TOBACCO"}
  - `level_period` ∈ {20, 10}
  - `face_amount` ∈ {450000.0, 250000.0, 100000.0}
  - `premium_mode = "ANNUAL"`.
- `/api/product-model-review/p12trf` scenarios now show real inputs instead of `"unknown"`:
  - **S1** – `age = 35`, `sex = "male"`, `smokerClass = "NS"`, `termYears = 20`, `faceAmount = 450000.0`, `premiumMode = "ANNUAL"`.
  - **S2** – `age = 30`, `sex = "female"`, `smokerClass = "NS"`, `termYears = 10`, `faceAmount = 250000.0`, `premiumMode = "ANNUAL"`.
  - **S3** – `age = 60`, `sex = "male"`, `smokerClass = "S"`, `termYears = 10`, `faceAmount = 100000.0`, `premiumMode = "ANNUAL"`.

This completes the MVP wiring for a configurable P12TRF scenario catalog: scenario inputs live in a fixture, are used directly for projections, are persisted into `policy_inputs`, surfaced via RunDetail, and rendered in the Product Model Review Trust Surface as distinguishable business cases.
