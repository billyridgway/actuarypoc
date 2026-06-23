FROM python:3.11-slim

ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ARG IMAGE_TAG=unknown

ENV DAGSTER_HOME=/opt/dagster/dagster_home \
    PYTHONUNBUFFERED=1 \
    GIT_SHA=${GIT_SHA} \
    BUILD_TIME=${BUILD_TIME} \
    IMAGE_TAG=${IMAGE_TAG}

WORKDIR /opt/dagster/app

# System dependencies for the projection UI build (Node + npm for Vite/React).
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build Dagster config used by the older orchestration POCs.
RUN mkdir -p ${DAGSTER_HOME} /opt/dagster/storage && \
    printf "storage:\n  sqlite:\n    base_dir: /opt/dagster/storage\nrun_coordinator:\n  queued:\n    max_concurrent_runs: 1\n" > ${DAGSTER_HOME}/dagster.yaml

# Build the projection React UI so it can be served by actuarypoc.ui.server.
WORKDIR /opt/dagster/app/web
RUN npm ci || npm install \
    && npm run build

# Reset workdir for runtime (Jobs, UI server, etc.).
WORKDIR /opt/dagster/app

EXPOSE 3000 8080
