# syntax=docker/dockerfile:1.7
#
# NSR MIS production image.
# - Python 3.12 (locked per CLAUDE.md).
# - Single-stage for Sprint 0; multi-stage optimisation lands when image size
#   starts to matter (CI cache or pull time).
# - Runs as a non-root user.
# - Entrypoint: gunicorn on port 8000. Override via `command:` in compose for
#   local dev (runserver).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=nsr_mis.settings

# Build + runtime deps. libpq-dev for psycopg; build-essential for any
# wheel that needs to compile. Trim once we move to multi-stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY nsr_mis ./nsr_mis
COPY apps ./apps
COPY manage.py ./
# Web-service entrypoint (migrate + collectstatic). Only the `web` service
# uses it; worker/beat run celery directly. See compose.prod.yml.
COPY infrastructure/docker/web-entrypoint.sh /usr/local/bin/web-entrypoint.sh

# Install CPU-only torch FIRST so sentence-transformers (chatbot embeddings,
# US-CHB) doesn't pull the ~2.5GB CUDA build — this box has no GPU. Cuts the
# image from ~9GB to ~2GB and speeds up every CD build/pull. pip then sees
# torch already satisfied when installing the project.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install .

# Create the static + media mountpoints owned by the runtime user BEFORE
# the named volumes attach, so a fresh volume inherits app ownership and
# collectstatic (run as `app`) can write to it.
RUN chmod +x /usr/local/bin/web-entrypoint.sh \
    && mkdir -p /app/staticfiles /app/media \
    && groupadd --system app \
    && useradd --system --gid app --no-create-home --home-dir /app app \
    && chown -R app:app /app

USER app

EXPOSE 8000

# Production default. Compose overrides with runserver for local dev.
CMD ["gunicorn", "nsr_mis.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
