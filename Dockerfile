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

RUN pip install .

RUN groupadd --system app \
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
