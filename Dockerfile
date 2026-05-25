FROM python:3.11-slim

ENV DAGSTER_HOME=/opt/dagster/dagster_home \
    PYTHONUNBUFFERED=1

WORKDIR /opt/dagster/app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p ${DAGSTER_HOME} /opt/dagster/storage && \
    printf "storage:\n  sqlite:\n    base_dir: /opt/dagster/storage\nrun_coordinator:\n  queued:\n    max_concurrent_runs: 1\n" > ${DAGSTER_HOME}/dagster.yaml

EXPOSE 3000
