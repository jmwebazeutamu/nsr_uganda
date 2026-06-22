#!/usr/bin/env sh
# Web service entrypoint: bring the schema + static assets into the
# desired state, then exec the passed command (gunicorn). ONLY the `web`
# service uses this entrypoint — worker/beat run celery directly, so the
# migration runs exactly once per deploy (no multi-replica race).
set -eu

echo "[entrypoint] applying migrations..."
python manage.py migrate --noinput

echo "[entrypoint] collecting static files..."
python manage.py collectstatic --noinput

echo "[entrypoint] exec: $*"
exec "$@"
