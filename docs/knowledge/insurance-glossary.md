# Insurance Glossary (ActuaryPOC Context)

> Status: Focused on terms used in the current POC and codebase. This is not
> an exhaustive industry glossary.

## Core Product Terms

### Term Life Insurance

A life insurance product that provides coverage for a specified **term**
(e.g. 10, 20, 30 years). If the insured dies during the term, a **death
benefit** is paid; otherwise, coverage expires with no value at the end of the
term.

In this POC, `P12TRF` is a sample term product modeled in the DSL.

### Whole Life Insurance (stub in POC)

A permanent life insurance product that provides lifetime coverage with
combination of **death benefit** and **cash value** accumulation. The POC has
an example DSL file (`whole_life.yaml`), but the current focus is on term
products.

### Face Amount

The nominal **death benefit** amount specified in the policy (e.g.
`$250,000`). In the POC, this is often called `face_amount` in PAS exports and
is used by the projection engine and premium table logic.

### Issue Age

The insured's age at policy issue. Typically denoted `issue_age` in data and
used for mortality and premium calculations.

### Risk Class / Smoker Class

Categorization of the insured's risk profile:

- **Risk class** – e.g. Preferred, Standard, Substandard.
- **Smoker class** – e.g. Smoker, Non‑Smoker, Non‑Tobacco.

The POC uses these fields in both PAS exports and premium tables to look up
appropriate premium rates.

### Premium Mode

How often premiums are paid:

- Annual
- Semi‑annual
- Quarterly
- Monthly

In the POC, `premium_mode` is stored as text (e.g. `Monthly`) and is used to
convert an annual premium into modal premium (for simple modalization rules
like divide‑by‑12).

### Modal Premium

The premium amount paid per mode (e.g. monthly payment amount). In PAS data
this is often `modal_premium`. The POC compares PAS modal premium against a
**table‑derived expected modal premium** and flags discrepancies.

---

## Data / System Terms

### PAS Export

A snapshot of policy administration system (PAS) data exported as CSV and
loaded into MinIO. In the POC this lands under the `pas_export/` prefix and is
used as the policy input for projections.

### CRM Accounts

Customer relationship management data associated with policies (e.g. accounts,
agencies). In the POC, this is stored under `crm_accounts/` in MinIO and can
be included in projection summaries for context.

### Actuarial Tables

Tabular data that encodes mortality rates, lapse rates, or other actuarial
assumptions. In this POC, actuarial tables are represented by CSV files and
loaded under:

- `actuarial_tables/` – primary tables
- `actuarial_tables_term23/` – Term23 mortality slice supporting P12TRF.

### Rate Curves

Yield curves or discount rates used to compute present values. Stored under
`rate_curves/` in MinIO. The current POC uses simple rate curves, but the
architecture assumes these can be swapped or extended.

### Assumption Set

A structured representation of assumptions for a product, such as:

- mortality basis
- lapse assumptions
- expenses
- premium table conventions

In the POC, `AssumptionSet` objects are stored in a MinIO‑backed registry and
identified by an `id` (e.g. `term-risk-class-mapping-v1`). They can be
extracted via LLM from text documents and approved by a human.

### Illustration Project

A Kubernetes **Custom Resource** (`IllustrationProject`) representing a
specific projection run or scenario. It holds configuration like:

- product ID
- projection horizon in years
- PAS input source (ConfigMap or MinIO)

The illustration operator watches these resources and runs Jobs to perform
illustrations.

---

## Platform Terms

### Run Detail

A structured JSON representation of one projection run, produced by
`/api/run-detail` in the ActuaryPOC FastAPI app. It includes:

- run metadata (IDs, timestamps)
- policy input summary
- premium comparison
- assumptions summary
- projection arrays (years, cash values, death benefits)
- audit sources (MinIO object keys, documents).

### Trust Status

A coarse summary of whether a projection appears trustworthy given available
inputs and assumptions. In the POC this is calculated in `Run Detail` and
surfaced in the UI as one of:

- `clean`
- `warnings_found`
- `missing_premium_table`

The exact semantics may evolve, but the idea is stable: flag issues that
should trigger human review.

### Audit Snapshot

A synthesized JSON object (written by `project-minio` when configured) that
captures metadata about which inputs and assumptions were used for a run
without embedding full projection data. It is designed to make audits easier
without leaking full details into CRD status.

### Golden Test Case

A hand‑curated pair of **input** and **expected projection** for a product
(e.g. P12TRF) that serves as a regression anchor. Golden cases live under
`src/actuarypoc/tests/golden/` and are enforced by unit tests.
