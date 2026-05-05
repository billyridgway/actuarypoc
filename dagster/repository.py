from __future__ import annotations

from pathlib import Path
from datetime import datetime

from dagster import (
    DefaultScheduleStatus,
    Definitions,
    ScheduleDefinition,
    RunRequest,
    get_dagster_logger,
    job,
    op,
    sensor,
)

from actuarypoc.pipeline.ingest import ingest_csv
from actuarypoc.projection.service import (
    build_projection_summary,
    get_latest_object_name,
    store_projection,
)


SAMPLE_CSV = Path(__file__).resolve().parents[1] / "src" / "actuarypoc" / "sample_data" / "policies.csv"
PAS_EXPORT_CSV = Path(__file__).resolve().parents[1] / "src" / "actuarypoc" / "sample_data" / "pas_export.csv"
ACTUARIAL_TABLE_CSV = Path(__file__).resolve().parents[1] / "src" / "actuarypoc" / "sample_data" / "actuarial_tables.csv"
CRM_ACCOUNTS_CSV = Path(__file__).resolve().parents[1] / "src" / "actuarypoc" / "sample_data" / "crm_accounts.csv"
RATE_CURVE_CSV = Path(__file__).resolve().parents[1] / "src" / "actuarypoc" / "sample_data" / "rate_curves.csv"


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


@op
def run_crm_data_ingest() -> str:
    logger = get_dagster_logger()
    object_name = ingest_csv(
        str(CRM_ACCOUNTS_CSV),
        object_name=f"crm_accounts/crm-accounts-{int(datetime.utcnow().timestamp())}.json",
    )
    logger.info("Uploaded CRM data to %s", object_name)
    return object_name


@op
def run_rate_curve_ingest() -> str:
    logger = get_dagster_logger()
    object_name = ingest_csv(
        str(RATE_CURVE_CSV),
        object_name=f"rate_curves/rate-curve-{int(datetime.utcnow().timestamp())}.json",
    )
    logger.info("Uploaded rate curve data to %s", object_name)
    return object_name


@job
def actuarial_table_job():
    run_actuarial_table_ingest()


@job
def crm_data_job():
    run_crm_data_ingest()


@job
def rate_curve_job():
    run_rate_curve_ingest()


@op
def generate_projection(context):
    summary = build_projection_summary()
    object_name = store_projection(summary)
    context.log.info("Stored projection summary at %s", object_name)
    return object_name


@job
def projection_job():
    generate_projection()


@sensor(job=projection_job, minimum_interval_seconds=300)
def pas_projection_sensor(context):
    try:
        latest_pas = get_latest_object_name("pas_export/")
    except RuntimeError:
        context.log.info("No PAS snapshots detected yet")
        return

    if context.cursor == latest_pas:
        return

    context.update_cursor(latest_pas)
    yield RunRequest(run_key=latest_pas)


definitions = Definitions(
    jobs=[
        sample_ingestion_job,
        pas_export_job,
        actuarial_table_job,
        crm_data_job,
        rate_curve_job,
        projection_job,
    ],
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
        ScheduleDefinition(
            job=crm_data_job,
            cron_schedule="0 3 * * *",
            name="daily_crm_data_schedule",
            default_status=DefaultScheduleStatus.STOPPED,
        ),
        ScheduleDefinition(
            job=rate_curve_job,
            cron_schedule="0 4 * * *",
            name="daily_rate_curve_schedule",
            default_status=DefaultScheduleStatus.STOPPED,
        ),
    ],
    sensors=[pas_projection_sensor],
)
