"""Celery app + beat schedule.

US-S6-004: replace the cron-driven management commands from S5-005 +
S5-006 with a single Celery beat process. In dev/CI we never run a
broker — the tasks are importable so unit tests can call them, but
the worker / beat processes only start in environments where
CELERY_ENABLED=True (production + staging).

Following Celery's standard layout: app instance lives at this
module path so a worker is launched with:

    celery -A nsr_mis worker --beat -l info

Tasks live in `tasks.py` modules under each Django app; autodiscover
picks them up from INSTALLED_APPS at startup.
"""

from __future__ import annotations

import os

from celery.schedules import crontab

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsr_mis.settings")

app = Celery("nsr_mis")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# --- Beat schedule ---------------------------------------------------------
# Two recurring sweeps replace the S5 management commands:
# - drain_nira_queue every 5 minutes — retries QUEUED NIRA attempts
#   whose next_retry_at has lapsed.
# - expire_data_requests at the top of every hour — flips DELIVERED
#   DataRequests past expires_at to EXPIRED.
#
# Schedules live here (not in app-level apps.py) so a single grep
# answers "what's scheduled to run automatically?".
app.conf.beat_schedule = {
    "drain-nira-queue": {
        "task": "apps.identity_verification.tasks.drain_nira_queue_task",
        # Every 5 minutes — matches the shortest 60s backoff cell with
        # some slack so we don't oversample the first-failure bucket.
        "schedule": crontab(minute="*/5"),
    },
    "expire-data-requests": {
        "task": "apps.data_requests.tasks.expire_data_requests_task",
        # Top of every hour — coarse is fine, expires_at granularity
        # is seconds but partner-facing TTL is days.
        "schedule": crontab(minute=0),
    },
}
