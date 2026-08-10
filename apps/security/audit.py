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
    purpose: str = "",
    field_changes: dict | None = None,
    ip_address: str | None = None,
    user_agent: str = "",
) -> AuditEvent:
    # Fold the purpose into `reason` as well as the column. `reason` is inside
    # the trigger's hashed payload, so this is what makes the purpose
    # tamper-evident; the column exists to make it queryable.
    if purpose:
        marker = f"purpose={purpose}"
        reason = f"{marker} {reason}".strip() if reason else marker

    return AuditEvent.objects.create(
        actor_id=actor,
        actor_kind=actor_kind,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        purpose=purpose,
        field_changes=field_changes,
        ip_address=ip_address,
        user_agent=user_agent[:255] if user_agent else "",
    )
