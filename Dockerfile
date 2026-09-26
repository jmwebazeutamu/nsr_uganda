# syntax=docker/dockerfile:1.7
#
# NSR MIS production image.
# - Python 3.12 (locked per CLAUDE.md).
# - Single-stage for Sprint 0; multi-stage optimisation lands when image size
#   starts to matter (CI cache or pull time).
# - Runs as a non-root user.
# - Entrypoint: gunicorn on port 8000. Override via `command:` in compose for
#   local dev (runserver).

# ---------------------------------------------------------------------
# Stage 1 — compile the operator console.
#
# The console sources are 47 JSX files that the design harness compiles
# in the BROWSER with a 3.1 MB Babel-standalone, pulling React, ReactDOM
# and d3 from unpkg. That is a design-review tool, not an operator
# surface: see scripts/build_console.mjs for the full reasoning.
#
# This stage moves the JSX compile to build time. Only the compiled
# output crosses into the runtime image — no JSX, no Babel, no node.
# ---------------------------------------------------------------------
FROM node:22-slim AS console-build

WORKDIR /build
COPY package.json package-lock.json ./
# npm ci needs the lockfile to match package.json; --omit=optional keeps
# the platform-specific esbuild download to the one binary we need.
RUN npm ci --no-audit --no-fund

COPY scripts/build_console.mjs ./scripts/
COPY design ./design
COPY static ./static
RUN node scripts/build_console.mjs

# ---------------------------------------------------------------------
# Stage 2 — build the user manual.
#
# /manual/ is served by nsr_mis.views.manual from
# docs/user-manual/site/, which is MkDocs build output and is
# gitignored. Until now nothing built it in the image, so production
# answered every /manual/ URL with "Manual not built" — the manual has
# only ever existed on whichever machine last ran mkdocs by hand.
#
# Same shape as the console stage above: the build tool stays behind,
# only the rendered HTML crosses into the runtime image. mkdocs and
# mkdocs-material are pinned because an unpinned docs toolchain is a
# build that starts failing on a day nobody changed anything.
# ---------------------------------------------------------------------
FROM python:3.12-slim AS manual-build

WORKDIR /build
RUN pip install --no-cache-dir mkdocs==1.6.1 mkdocs-material==9.7.7

COPY docs/user-manual ./docs/user-manual
# --strict so a broken cross-link fails the build rather than shipping
# a manual with dead links in it.
RUN cd docs/user-manual && mkdocs build --strict

# ---------------------------------------------------------------------
# Stage 3 — the application image.
# ---------------------------------------------------------------------
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
# Project-level static source (the public site's tokens + self-hosted Inter).
# STATICFILES_DIRS points here; without this COPY the directory is simply
# absent in the image, collectstatic finds nothing, and every /static/
# public-site URL 404s while Django only WARNS. tests/contract/
# test_static_is_in_the_image.py fails the build path instead.
COPY static ./static
# The compiled console, from stage 1. Nothing else crosses over: the JSX
# sources, Babel and node all stay behind in the build stage.
COPY --from=console-build /build/static/console ./static/console
# The rendered manual, from stage 2. mkdocs, mkdocs-material and the
# Markdown sources all stay behind in that stage; only the HTML the
# view actually serves crosses over.
COPY --from=manual-build /build/docs/user-manual/site ./docs/user-manual/site
# Web-service entrypoint (migrate + collectstatic). Only the `web` service
# uses it; worker/beat run celery directly. See compose.prod.yml.
COPY infrastructure/docker/web-entrypoint.sh /usr/local/bin/web-entrypoint.sh

# Install CPU-only torch FIRST so sentence-transformers (chatbot embeddings,
# US-CHB) doesn't pull the ~2.5GB CUDA build — this box has no GPU. Cuts the
# image from ~9GB to ~2GB and speeds up every CD build/pull. pip then sees
# torch already satisfied when installing the project.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install .

# Create the static + media + data mountpoints owned by the runtime user
# BEFORE the named volumes attach, so a fresh volume inherits app
# ownership and collectstatic (run as `app`) can write to it.
#
# /app/data/* are the production persistence targets for the three
# file-backed stores (DRS bundles, UPD evidence, consent evidence).
# Docker seeds a fresh named volume from the image path INCLUDING its
# ownership — so if these directories did not exist here, the volumes
# would mount root-owned and every write as `app` would fail with
# EACCES at runtime rather than at build time. Dev is unaffected:
# docker-compose.override.yml bind-mounts the repo over /app, and the
# dev settings default these stores to BASE_DIR/.drs-bundles etc.
RUN chmod +x /usr/local/bin/web-entrypoint.sh \
    && mkdir -p /app/staticfiles /app/media \
    && mkdir -p /app/data/drs-bundles /app/data/upd-evidence \
                /app/data/consent-evidence \
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
