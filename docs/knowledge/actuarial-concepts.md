# Actuarial Concepts (Focused on the POC)

> Status: This document focuses on the subset of actuarial concepts directly
> exercised by the current POC (P12TRF term product, Term23 slice, simple
> reserves and premiums). It is **not** a full actuarial textbook.

## 1. Mortality and Survival

### 1.1 Mortality Rate (qₓ)

In life insurance, **qₓ** typically denotes the probability that a life aged
`x` dies within the next year (or other time period). In the POC:

- Mortality rates are supplied via actuarial tables (e.g.
  `actuarial_tables_term23.csv`).
- The projection engine builds a **mortality surface** from these tables using
  helper functions in `src/actuarypoc/projection/mortality.py`.

For some POC runs, qₓ may be simplified or even set to zero – these are POC
choices to keep the example readable, not production assumptions.

### 1.2 Survival Probability

Survival probabilities represent the chance that a policy is still in force
at each time step. In the POC:

- `survival_probabilities` is an array returned in `projection` JSON.
- It is derived from mortality and lapse assumptions (simplified for now).

These probabilities are used to reason about expected premiums and claims
under the modeled assumptions.

---

## 2. Premiums

### 2.1 Table‑Derived Premiums

The POC includes a synthetic **premium table** for P12TRF in
`src/actuarypoc/sample_data/p12trf_premiums.synthetic.csv`. This table is used
by `src/actuarypoc/projection/premium.py` to:

- look up a premium rate per $1,000 of face amount, given:
  - issue age
  - gender
  - risk class
  - face band
  - level term period
- compute an **annual premium** from that rate and the face amount.

These table premiums are intended to mimic (but not equal) filed rates.

### 2.2 Modal Premiums

The POC uses a simple modalization rule:

- When `premium_mode` is `MONTHLY`, the expected modal premium is:

  ```
  expected_modal = annual_premium / 12
  ```

- For other modes, the POC currently treats PAS modal premium as annual or
  does not adjust it.

This is deliberately simplified and should be treated as **POC logic**.

### 2.3 Premium Comparison and Mismatch

The Run Detail builder compares:

- PAS modal premium (`modal_premium` from PAS export), and
- table‑derived expected modal premium.

If the difference exceeds a threshold, it records a **premium mismatch
warning**, which is surfaced in the Run Detail JSON and UI. This is part of
the **trust surface**: highlighting where PAS inputs and table‑derived values
are materially different.

---

## 3. Reserves (POC‑Level)

The POC computes and returns certain reserve‑like quantities, but they are
**not full actuarial reserves**. They are meant to illustrate how reserves
might be structured:

- `pv_premiums` – present value of future premiums.
- `pv_claims` – present value of future claims (simplified or zero in some
  POC runs).
- `pv_reserves` – running present value of reserve under simple assumptions.
- `nf_reserves` / `pv_nf_reserves` – net‑level premium reserve constructs.

These are intentionally simplified and are **not production‑grade** statutory
or GAAP reserves.

---

## 4. Projection Horizon

The projection horizon (in years) controls how far into the future the engine
simulates.

- In `actuarypoc`, the CLI default for P12TRF is often 20 or 40 years.
- In the operator, `horizonYears` in `IllustrationProject.spec` controls the
  horizon used by the projection Job.

Longer horizons produce more rows/arrays in the projection output.

---

## 5. Assumptions and Assumption Sets

### 5.1 AssumptionSet Objects

The POC defines an `AssumptionSet` structure (see
`src/actuarypoc/config/assumptions.py`) that captures:

- `id` – logical identifier (e.g. `term-risk-class-mapping-v1`).
- `product_code` – product code like `P12TRF`.
- `description` – human‑readable description.
- other fields depending on the schema.

Assumption sets are stored in MinIO and can be:

- created directly (e.g. from JSON), or
- extracted from text documents using an LLM (`extract-assumptions-minio`).

### 5.2 Approval and Current Set

Assumption sets can be marked as **approved** and **current** for a product:

- `approve-assumption` CLI updates status and de‑marks other sets as current.
- Projection code can then look up the **current** assumptions for a product.

The illustration operator uses the assumption set ID and `assumptionApproved`
flag on `IllustrationProject.status` to gate projections when LLM extraction
is used.

---

## 6. Trust Surface Concepts

### 6.1 Trust Status

The POC surfaces a **trust status** per run, summarizing:

- whether premium tables were available
- whether premium mismatches were detected
- whether any warnings were logged.

Trust status is not yet a regulatory metric, but it is a useful internal
indicator of where human review is needed.

### 6.2 Audit Trail

The audit trail ties together:

- which PAS export, tables, rates, and CRM data were used
- which assumption set and DSL file were used
- which engine/image version produced the result.

In the POC:

- Much of this appears in the projection JSON `inputs` and `metadata`.
- Additional summaries exist as audit snapshot objects and CRD status fields
  in the operator.

Future work will formalize this into a more rigid audit record format.
