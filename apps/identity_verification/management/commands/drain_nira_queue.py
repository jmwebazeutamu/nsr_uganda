"""Drain the NIRA verification retry queue.

Run from cron / systemd timer until Celery beat is wired:

    python manage.py drain_nira_queue

Per US-S5-005: queue_verification persists rows with status=QUEUED
when NIRA raises NiraError; this command picks each up after the
exponential-backoff window has lapsed and retries.

NIN resolution: the queue stores nin_hash only (never the raw NIN).
The resolver here walks Member.nin_hash to find a matching live row
and decrypts Member.nin_value through the AES seam. When no Member
carries the hash any more (member merged + soft-deleted), drain marks
the attempt FAILED so it stops cycling.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.data_management.models import Member
from apps.identity_verification.queue import drain_queue


def _resolve_nin(nin_hash: bytes) -> str | None:
    """Find a live Member with this nin_hash and return their NIN.

    Today this reads the AES-decrypted Member.nin_value column. When
    KMS lands (US-S2-004), the same call goes through the KMS unwrap
    seam without changing this signature.
    """
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


class Command(BaseCommand):
    help = "Drain the NIRA verification retry queue (US-S5-005)."

    def handle(self, *args, **options):
        counts = drain_queue(_resolve_nin)
        self.stdout.write(
            "drain_nira_queue: "
            + ", ".join(f"{k}={v}" for k, v in counts.items()),
        )
