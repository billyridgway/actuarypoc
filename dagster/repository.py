from __future__ import annotations

from pathlib import Path

from dagster import (
    DefaultScheduleStatus,
    Definitions,
    ScheduleDefinition,
    get_dagster_logger,
    job,
    op,
)

from actuarypoc.pipeline.ingest import ingest_csv


SAMPLE_CSV = Path(__file__).resolve().parents[1] / "src" / "actuarypoc" / "sample_data" / "policies.csv"


@op
def run_sample_ingest() -> str:
    logger = get_dagster_logger()
    object_name = ingest_csv(str(SAMPLE_CSV))
    logger.info("Uploaded sample data to %s", object_name)
    return object_name


@job
def sample_ingestion_job():
    run_sample_ingest()


definitions = Definitions(
    jobs=[sample_ingestion_job],
    schedules=[
        ScheduleDefinition(
            job=sample_ingestion_job,
            cron_schedule="0 * * * *",
            name="hourly_sample_ingest_schedule",
            default_status=DefaultScheduleStatus.STOPPED,
        )
    ],
)
