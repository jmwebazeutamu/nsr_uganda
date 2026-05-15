"""IDV persistence — NIRA verification retry queue.

When the NIRA client raises NiraError (mock simulates this for NIN
suffix 'SU' — sandbox `service_unavailable`), the caller must NOT
crash and lose the verification attempt. queue_verification() lands
the request here; the management command `drain_nira_queue` retries
on an exponential backoff until success, hard-fail, or max attempts.

We persist `nin_hash` only — the raw NIN never lands in the DB
(consistent with the NSR-wide ADR-0002 NIN-trio rule). The mock NIRA
verify_nin() takes the raw NIN as a parameter, so callers pass it
in-memory at queue time; we hash before persisting.
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class AttemptStatus(models.TextChoices):
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    FAILED = "failed"  # exhausted max attempts


class NiraVerificationAttempt(models.Model):
    """One NIN verification request, queued because NIRA was unavailable.

    `attempts` is the number of times we've called verify_nin (including
    the initial queue-time attempt). The drain command increments it
    each retry. `last_error` captures the last NiraError message for
    diagnostics; redacted of any payload data the mock might emit.
    """

    id = ULIDField(primary_key=True)
    nin_hash = models.BinaryField(max_length=32)
    requester = models.CharField(max_length=64, default="system")

    status = models.CharField(
        max_length=16, choices=AttemptStatus.choices,
        default=AttemptStatus.QUEUED, db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=256, blank=True)

    next_retry_at = models.DateTimeField(db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # On success, the NIRA response body (demographics dict) lands here.
    # Callers that need it (UPD vital-event auto-commit, DIH staging)
    # poll the table for status=SUCCEEDED + completed_at >= their watermark.
    result_payload = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "NIRA verification attempt"
        indexes = [
            models.Index(fields=["status", "next_retry_at"]),
            models.Index(fields=["nin_hash"]),
        ]

    def __str__(self) -> str:
        return f"NIRA attempt {self.id} [{self.status}] x{self.attempts}"
