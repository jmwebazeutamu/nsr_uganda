"""Sweep PENDING_APPROVAL ChangeRequests past their SLA and escalate
required_role to district M&E.

Same loop as apps.update_workflow.tasks.escalate_stale_change_requests_
task — the management command exists for ops/runbooks; production
runs the Celery task on the beat schedule.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.update_workflow.services import escalate_stale_change_requests


class Command(BaseCommand):
    help = ("Escalate PENDING_APPROVAL ChangeRequests past sla_deadline "
            "to district M&E (US-S7-001).")

    def handle(self, *args, **options):
        counts = escalate_stale_change_requests()
        self.stdout.write(
            "escalate_stale_change_requests: "
            + ", ".join(f"{k}={v}" for k, v in counts.items()),
        )
