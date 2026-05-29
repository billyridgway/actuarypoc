# SERFF Data Model (POC Perspective)

> Status: Describes how SERFF‑style data *should* fit into this platform and
> what is partially implemented today. It does **not** imply a complete SERFF
> ingestion pipeline already exists.

The System for Electronic Rate and Form Filing (SERFF) is how many life
insurance products are filed with regulators. SERFF filings contain a mix of
forms, rates, actuarial memos, statements of variability, and supporting
documentation.

This POC only uses **fragments** of that world:

- references to SERFF filings in notes and docs
- experimental PDF/text extraction helpers
- LLM‑based triage of candidate documents for assumptions.

There is currently **no single, fully implemented SERFF → illustration
pipeline**. Instead, this document lays out how SERFF artefacts are expected
to map into the platform.

---

## 1. SERFF Artefact Types

Common artefacts in a SERFF filing include:

- **Policy forms** – contract language for specific products and riders.
- **Rate tables** – premium grids, often by age, gender, risk class, face
  amount bands, and term period.
- **Actuarial memoranda** – narrative descriptions of assumptions, methods,
  and justifications.
- **Statements of variability (SOV)** – which values in the forms can vary
  and within what ranges.
- **Marketing/sales material** – illustrations, brochures (less central for
  assumptions but may be useful context).

The POC only directly works with:

- premium‑like tables (synthetic, not true SERFF rates)
- actuarial‑style textual descriptions when extracting assumptions.

---

## 2. Target MinIO Layout (Planned)

A future SERFF ingestion pipeline is expected to map filings into MinIO using
prefixes along these lines:

- `filings/<product_code>/raw/` – original SERFF zips/PDFs.
- `filings/<product_code>/text/` – extracted text from PDFs/Word docs.
- `filings/<product_code>/classified/` – AI‑triaged subsets of docs:
  - `actuarial_memo`
  - `risk_mapping`
  - `premium_tables`
  - `sov`

From these, downstream processes (LLM extraction, human review) would produce
structured artefacts like:

- **Assumption sets** stored in the existing assumptions registry.
- **Premium tables** loaded into `rate_curves/`‑ or
  `p12trf_premiums.synthetic.csv`‑style structures.

> **Implemented today:**
>
> - MinIO helpers (`storage/minio_client.py`).
> - PDF/text extraction utilities and AI‑triage logic in older POC code.
> - `extract-assumptions-minio` CLI that reads the latest doc under a prefix
>   and produces an `AssumptionSet`.
>
> **Not yet implemented:**
>
> - A standardized, documented prefix layout for SERFF artefacts.
> - A single API/CLI that executes the full ingestion + classification
>   workflow.

---

## 3. Filing Metadata and Provenance (Planned)

For each filing, we ultimately want a **filing record** that tracks:

- product code(s) and form numbers
- jurisdiction(s)
- effective/approval dates
- pointers to key docs (actuarial memo, SOV, rate tables)
- versioning (if a product has multiple filings over time).

In the current POC:

- Some of this information is embedded in comments, notes, and filenames
  (e.g. P12TRF references in notes).
- There is no single `FilingRecord` structure or storage location yet.

A future implementation would likely:

- define a `FilingRecord` schema in Python (and/or a CRD),
- store these records in MinIO and/or Postgres,
- reference them from assumption sets and projection runs.

---

## 4. Relationship to Assumptions and DSL

SERFF artefacts are important because they are the **source of truth** for
assumptions used in illustrations.

In the desired architecture:

- Each `AssumptionSet` should:
  - reference one or more SERFF documents (by MinIO key or filing ID), and
  - document which parts of the filing justify each assumption.
- DSL files (e.g. `p12trf_term.yaml`) should:
  - include `meta` fields referencing the relevant SERFF filings and
    assumption sets.

Today, the POC has:

- DSL `meta` fields for premium tables and risk class mapping.
- A small MinIO‑backed assumptions registry.

It does **not yet** maintain strong links between SERFF filing artefacts and
specific assumptions; that remains planned.

---

## 5. How This Ties into the Projection Lifecycle

When SERFF ingestion is fully wired, the expected flow will be:

1. **Upload SERFF filing**.
2. **Store raw docs and extracted text in MinIO** under standardized
   `filings/<product>/...` prefixes.
3. **Classify and extract** key docs and assumptions using AI + human review.
4. **Create/approve AssumptionSets** tied to products and filings.
5. **Run projections** using those AssumptionSets and DSL definitions.
6. **Audit**: every projection can be traced back to:
   - SERFF filing IDs
   - specific documents within those filings
   - the exact assumption set version used.

Steps (1)–(3) are the main missing pieces today. The rest of the platform
(projection engine, assumptions registry, operator, UI) is already structured
around the idea that such provenance will exist.
