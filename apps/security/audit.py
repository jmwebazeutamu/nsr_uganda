"""Single audit emission helper used by every audit-bearing module.

Replaces the per-module _emit_audit copies that drifted between
apps/ingestion_hub/services.py and apps/ddup/services.py. Importing
across modules is permitted per ADR-0001 (shared service via internal
Python API).
"""

from __future__ import annotations

from .models import AuditEvent


def emit(
    action: str,
    entity_type: str,
    entity_id: str,
    *,
    actor: str,
    actor_kind: str = "user",
    reason: str = "",
    field_changes: dict | None = None,
) -> AuditEvent:
    return AuditEvent.objects.create(
        actor_id=actor,
        actor_kind=actor_kind,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        field_changes=field_changes,
    )
