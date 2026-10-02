# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.10.9 AS uv

FROM python:3.12-slim-bookworm AS builder
COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /build

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY infra/download_models.py infra/download_models.py
COPY models/download-manifest.json models/download-manifest.json
RUN python infra/download_models.py \
    --manifest models/download-manifest.json \
    --destination /opt/models

FROM python:3.12-slim-bookworm AS runtime

ENV HOME=/home/app \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FACE_MODEL_DIR=/app/models \
    FACE_LANDMARKER_PATH=/app/models/face_landmarker.task \
    FACE_EMBEDDING_MODEL_PATH=/app/models/face-reidentification-retail-0095.xml

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app \
        --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --from=builder --chown=app:app /opt/models /app/models
COPY --from=builder --chown=app:app /build/models/download-manifest.json /app/models/download-manifest.json
COPY --chown=app:app \
    face_api.py \
    face_config.py \
    face_models.py \
    face_pipeline.py \
    face_tracker.py \
    ./
COPY --chown=app:app infra/healthcheck.py /app/healthcheck.py

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

CMD ["sh", "-c", "exec uvicorn face_api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
