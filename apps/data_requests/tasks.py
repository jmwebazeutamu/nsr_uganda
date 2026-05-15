"""Celery tasks for API-DRS.

expire_data_requests_task — recurring sweep scheduled by Celery beat
(see nsr_mis/celery.py). Identical effect to the
`expire_data_requests` management command from S5-006; both can
coexist.
"""

from __future__ import annotations

from celery import shared_task
from django.utils import timezone

from .models import DataRequest, RequestStatus
from .services import DrsError, expire_data_request


@shared_task(name="apps.data_requests.tasks.expire_data_requests_task")
def expire_data_requests_task(actor: str = "celery-beat") -> dict[str, int]:
    """Same loop as the management command. Returns counts dict so
    the Celery result backend (if configured) carries operational
    metrics."""
    now = timezone.now()
    candidates = DataRequest.objects.filter(
        status=RequestStatus.DELIVERED, expires_at__lt=now,
    ).order_by("expires_at")

    expired = 0
    errors = 0
    total = candidates.count()
    for req in candidates:
        try:
            expire_data_request(req, actor=actor)
            expired += 1
        except DrsError:
            errors += 1
    return {"candidates": total, "expired": expired, "errors": errors}
