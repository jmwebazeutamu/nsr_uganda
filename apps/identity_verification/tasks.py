"""Celery tasks for IDV.

drain_nira_queue_task — recurring retry sweep scheduled by Celery
beat (see nsr_mis/celery.py). Identical effect to the
`drain_nira_queue` management command from S5-005, just driven by
beat instead of cron. Both can coexist; production runs beat,
ops/runbooks can still invoke the command for one-off sweeps.
"""

from __future__ import annotations

from apps.data_management.models import Member
from celery import shared_task

from .queue import drain_queue


def _resolve_nin(nin_hash: bytes) -> str | None:
    """Same Member.nin_hash → nin_value lookup as the management
    command. Duplicated to keep the task independent of the command's
    import path; both go through Member.nin_value (decrypted by the
    EncryptedBinaryField on access)."""
    member = (
        Member.objects.filter(nin_hash=nin_hash, is_deleted=False)
        .only("nin_value")
        .first()
    )
    if member is None or not member.nin_value:
        return None
    raw = bytes(member.nin_value)
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return None


@shared_task(name="apps.identity_verification.tasks.drain_nira_queue_task")
def drain_nira_queue_task() -> dict[str, int]:
    """Return the counts dict from drain_queue so monitoring can read
    it off the Celery result backend if one is configured."""
    return drain_queue(_resolve_nin)
