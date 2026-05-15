"""Sweep DELIVERED DataRequests past expires_at and mark them EXPIRED.

Run from cron / systemd timer until Celery beat is wired:

    python manage.py expire_data_requests

Calls into the existing apps.data_requests.services.expire_data_request
service so audit emission, idempotency, and state-transition guards
are identical to the per-request /expire/ API action. Designed to be
safe under re-run — already-EXPIRED rows are skipped silently.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.data_requests.models import DataRequest, RequestStatus
from apps.data_requests.services import DrsError, expire_data_request


class Command(BaseCommand):
    help = ("Sweep DELIVERED DataRequests past expires_at and mark "
            "them EXPIRED (US-S5-006).")

    def add_arguments(self, parser):
        parser.add_argument(
            "--actor", default="expire-sweep-bot",
            help="actor identifier recorded on the audit event "
                 "(default: expire-sweep-bot)",
        )

    def handle(self, *args, **options):
        actor = options["actor"]
        now = timezone.now()
        candidates = DataRequest.objects.filter(
            status=RequestStatus.DELIVERED,
            expires_at__lt=now,
        ).order_by("expires_at")

        expired = 0
        errors = 0
        for req in candidates:
            try:
                expire_data_request(req, actor=actor)
                expired += 1
            except DrsError:
                # Race: another worker / API call already expired this
                # row. expire_data_request is idempotent on a no-op
                # EXPIRED but raises on any other transition; either
                # way the sweep should keep going.
                errors += 1
        self.stdout.write(
            f"expire_data_requests: candidates={candidates.count()} "
            f"expired={expired} errors={errors}",
        )
