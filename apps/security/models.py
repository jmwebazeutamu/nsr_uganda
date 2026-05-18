"""SEC models.

- AuditEvent — append-only audit chain (Sprint 0).
- OperatorScope — ABAC geographic visibility per user (Sprint 2).

References:
- SAD §8.2 (ABAC scope per parish/sub-county/district/region)
- SAD §8.4 audit and observability (hash-chained, append-only, 10y retention)
- ADR-0002 (AuditEvent.id is ULID — externally referenced for compliance)
"""

from __future__ import annotations

from django.conf import settings
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

    # Width widened from 24→64 (US-S21-001) so hierarchical action
    # names from feature-flagged modules fit: the DQA Rule Editor's
    # "dqa.rule_version.submitted_for_approval" (40 chars) couldn't
    # land on Postgres CI under the old limit. CharField.choices is
    # an authoring-time validator only — the DB column accepts any
    # string up to max_length, so widening doesn't lock anyone out
    # of using the existing Action enum values.
    action = models.CharField(max_length=64, choices=Action.choices)
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


class ScopeLevel(models.TextChoices):
    NATIONAL = "national"
    REGION = "region"
    SUB_REGION = "sub_region"
    DISTRICT = "district"
    SUB_COUNTY = "sub_county"
    PARISH = "parish"
    VILLAGE = "village"
    # Non-geographic — a partner-affiliated user who sees DataRequests
    # under DSAs belonging to their Partner (scope_code = Partner.code).
    PARTNER = "partner"


class OperatorScope(models.Model):
    """ABAC geographic scope per SAD §8.2.

    An operator can carry multiple scopes (e.g., two parishes). Sprint 2
    enforces visibility at the sub_region level using the partition key
    introduced by ADR-0005. Finer-grained scopes (district / parish /
    village) are modelled here so the Sprint 2.5 enforcement story
    can land without a schema change.

    `scope_code` is matched against the GeographicUnit.code at the same
    level — e.g. scope_level="sub_region" + scope_code="SR-BUGANDA-SOUTH-CENTRAL"
    grants visibility to every Household whose sub_region_code == that
    value. scope_level="national" is the wildcard for NSR Unit Coordinator
    and DPO roles.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scopes",
    )
    scope_level = models.CharField(max_length=16, choices=ScopeLevel.choices)
    scope_code = models.CharField(max_length=64, blank=True)  # empty for 'national'
    active = models.BooleanField(default=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.CharField(max_length=64, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        verbose_name = "Operator scope"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "scope_level", "scope_code"],
                name="operator_scope_unique_per_user_level",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "active"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}/{self.scope_level}={self.scope_code or '*'}"
