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
    "escalate-stale-change-requests": {
        "task": "apps.update_workflow.tasks.escalate_stale_change_requests_task",
        # Every 15 minutes — finer than the hourly DRS sweep because
        # approval SLAs are tighter (24h-72h) and supervisor pressure
        # builds in real time.
        "schedule": crontab(minute="*/15"),
    },
    "consent-withdrawal-sla-sweep": {
        "task": "apps.consent.tasks.scan_withdrawal_sla_breaches",
        # Hourly — withdrawal SLA is 30 days (CONSENT-O-03); an hourly
        # sweep gives the DPO ~24 reminders of head-room before breach
        # and emits consent.withdrawal.sla_breached once per ticket
        # (US-CONSENT-07).
        "schedule": crontab(minute=30),
    },
    "auto-merge-high-confidence-pairs": {
        "task": "apps.ddup.tasks.auto_merge_high_confidence_pairs_task",
        # Hourly — high-confidence tier-3 pairs are rare; we don't
        # need real-time auto-merge, and an hour gives reviewers
        # time to manually pre-empt anything edge-case.
        "schedule": crontab(minute=15),
    },
    "process-pending-kobo-landings": {
        "task": "apps.ingestion_hub.tasks.process_pending_kobo_landings_task",
        # Every 5 minutes — Kobo pulls happen on operator action
        # today, but the beat picks up any RawLandings the admin
        # "Pull" action created without auto-processing (e.g., older
        # pulls from before S11-014 landed). Once push-via-webhook
        # is wired (DIH-O-CONN-04) this becomes the path that drives
        # ALL Kobo intake.
        "schedule": crontab(minute="*/5"),
    },
    "verify-audit-chain": {
        "task": "apps.security.tasks.verify_audit_chain_task",
        # Daily at 03:00 EAT — off-peak so the whole-table scan
        # doesn't compete with intake or DRS bundle generation.
        # The DPO is the consumer of the result (US-S16-004); a
        # daily cadence gives a 24-hour upper bound on detection
        # latency, which is consistent with the prior manual-audit
        # SOP we're replacing.
        "schedule": crontab(minute=0, hour=3),
    },
    "rollup-partner-usage-daily": {
        "task": "apps.partners.tasks.rollup_partner_usage_daily_task",
        # Daily at 01:00 EAT — runs after midnight so the rollup
        # picks up the full previous day of DRS deliveries. Feeds
        # the UsageBar on the partners dashboard.
        "schedule": crontab(minute=0, hour=1),
    },
    "detect-dsa-budget-breaches": {
        "task": "apps.partners.tasks.detect_dsa_budget_breaches_task",
        # Daily at 01:15 EAT — 15 minutes after the rollup so the
        # detector sees the freshest day in the 30d window. Emits
        # `breach_detected` AuditEvents + flips the partner status
        # to "alert" per ADR-0011.
        "schedule": crontab(minute=15, hour=1),
    },
    "recompute-pmt-band-thresholds": {
        "task": "apps.pmt.tasks.recompute_band_thresholds_task",
        # Daily at 02:00 EAT — off-peak, after the partner-usage
        # rollups but before the 03:00 audit-chain verify. The
        # percentile pass walks every PMTResult.score for each
        # ACTIVE PMTModelVersion (US-S22-PMT-BAND-THRESHOLD); MGLSD
        # eligibility decisions read derive_band, which reads the
        # latest empirical PMTBandThreshold row written here.
        "schedule": crontab(minute=0, hour=2),
    },
}
