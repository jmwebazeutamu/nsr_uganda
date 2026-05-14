"""SEC models.

Sprint 0 scope: AuditEvent only. The role catalogue, ABAC scope, and
session-recording infrastructure land in later stories. AuditEvent is the
foundation of the integrity story — every personal-data read/write writes one.

References:
- SAD §8.4 audit and observability (hash-chained, append-only, 10y retention)
- ADR-0002 (AuditEvent.id is ULID — externally referenced for compliance)
"""

from __future__ import annotations

from django.db import models

from nsr_mis.common.fields import ULIDField


class AuditEvent(models.Model):
    """Append-only audit row, hash-chained to its predecessor.

    The hash chain is computed by a database trigger so that application-side
    bugs cannot break the chain. See migration 0002 for the trigger.
    """

    class Action(models.TextChoices):
        CREATE = "create"
        READ = "read"
        UPDATE = "update"
        SOFT_DELETE = "soft_delete"
        HARD_DELETE = "hard_delete"
        MERGE = "merge"
        UNMERGE = "unmerge"
        PROMOTE = "promote"
        REJECT = "reject"

    id = ULIDField(primary_key=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    actor_id = models.CharField(max_length=64, db_index=True)
    actor_kind = models.CharField(max_length=16, default="user")

    action = models.CharField(max_length=24, choices=Action.choices)
    entity_type = models.CharField(max_length=64, db_index=True)
    entity_id = models.CharField(max_length=64, db_index=True)

    field_changes = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=256, blank=True)

    prev_hash = models.BinaryField(max_length=32, null=True, blank=True)
    self_hash = models.BinaryField(max_length=32, null=True, blank=True)

    class Meta:
        verbose_name = "Audit event"
        verbose_name_plural = "Audit events"
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["action", "occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.entity_type}:{self.entity_id} @ {self.occurred_at}"
