# Dagster Scaffold

This directory contains a minimal Dagster repository that wraps the existing CSV ingestion pipeline so it can be orchestrated with Dagster tooling.

## Structure
- `repository.py`: defines a `sample_ingestion_job` and an hourly schedule using the same `ingest_csv` helper used elsewhere.

## Local execution
1. Install requirements (from repo root):
   ```bash
   pip install -r requirements.txt
   ```
2. Execute the job locally via Dagster CLI:
   ```bash
   dagster job execute -f dagster/repository.py -j sample_ingestion_job
   ```
   Provide the same MinIO env vars used elsewhere (e.g., `export $(cat .env | xargs)`).

## Dagster UI / daemon
To explore in Dagster UI:
```bash
dagster dev -f dagster/repository.py
```
This launches Dagster UI at http://127.0.0.1:3000 where the job and schedule appear. From there you can trigger runs or let the schedule start when the Dagster daemon is enabled.
