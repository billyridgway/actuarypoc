---
name: "Filing ingestion enhancement"
about: "Improve SERFF/filer ingestion, classification, or provenance"
labels: ["filing-ingestion"]
---

## Problem statement

Describe the ingestion or provenance gap:

- What part of the SERFF → FilingRecord → ProductDefinition pipeline is
  missing or weak?
- Is this about upload, text extraction, classification, FilingRecord
  creation, or linking to assumptions/products?

## Acceptance criteria

- [ ] New or improved step in `docs/workflows/serff-to-illustration.md` is
      clearly documented
- [ ] Implementation plan considers MinIO layout, LLM costs, and human review
- [ ] At least one end-to-end path from a sample filing to
      FilingRecord/ProductDefinition is validated (even if POC)

## Technical notes

- Which prefixes and objects in MinIO are involved (`filings/...`,
  `premium_tables/...`, etc.)?
- Which CLIs/APIs are in scope (`extract-assumptions-minio`, future
  `serff-upload`, etc.)?
- Any libraries or external services (PDF parsers, LLM providers)?

## Test plan

- Synthetic SERFF sample or anonymized filing to run through the pipeline
- Checks that expected FilingRecord and ProductDefinition artefacts are
  created/updated
- Validation that downstream projections pick up the new provenance/assumptions

## Audit considerations

- How does this enhancement improve traceability from projection back to
  filings and docs?
- What new information (if any) should appear in FilingRecords,
  ProductDefinitions, AssumptionSets, or AuditRecords?
- Are there privacy concerns with storing or classifying certain documents?
