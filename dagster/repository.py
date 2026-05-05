from __future__ import annotations

from pathlib import Path
from datetime import datetime

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
PAS_EXPORT_CSV = Path(__file__).resolve().parents[1] / "src" / "actuarypoc" / "sample_data" / "pas_export.csv"
ACTUARIAL_TABLE_CSV = Path(__file__).resolve().parents[1] / "src" / "actuarypoc" / "sample_data" / "actuarial_tables.csv"


@op
def run_sample_ingest() -> str:
    logger = get_dagster_logger()
    object_name = ingest_csv(str(SAMPLE_CSV))
    logger.info("Uploaded sample data to %s", object_name)
    return object_name


@op
def run_pas_export_ingest() -> str:
    logger = get_dagster_logger()
    object_name = ingest_csv(
        str(PAS_EXPORT_CSV),
        object_name=f"pas_export/pas-export-{int(datetime.utcnow().timestamp())}.json",
    )
    logger.info("Uploaded PAS export to %s", object_name)
    return object_name


@job
def sample_ingestion_job():
    run_sample_ingest()


@op
def run_actuarial_table_ingest() -> str:
    logger = get_dagster_logger()
    object_name = ingest_csv(
        str(ACTUARIAL_TABLE_CSV),
        object_name=f"actuarial_tables/actuarial-table-{int(datetime.utcnow().timestamp())}.json",
    )
    logger.info("Uploaded actuarial table data to %s", object_name)
    return object_name


@job
def pas_export_job():
    run_pas_export_ingest()


@job
def actuarial_table_job():
    run_actuarial_table_ingest()


definitions = Definitions(
    jobs=[sample_ingestion_job, pas_export_job, actuarial_table_job],
    schedules=[
        ScheduleDefinition(
            job=sample_ingestion_job,
            cron_schedule="0 * * * *",
            name="hourly_sample_ingest_schedule",
            default_status=DefaultScheduleStatus.STOPPED,
        ),
        ScheduleDefinition(
            job=pas_export_job,
            cron_schedule="30 1 * * *",
            name="daily_pas_export_schedule",
            default_status=DefaultScheduleStatus.STOPPED,
        ),
        ScheduleDefinition(
            job=actuarial_table_job,
            cron_schedule="15 2 * * *",
            name="daily_actuarial_table_schedule",
            default_status=DefaultScheduleStatus.STOPPED,
        ),
    ],
)
