"""GRM services — open / assign / escalate / resolve / close.

SLA defaults match SAD §4.4.7 (UPD) framing extended to GRM tiers:
- L1 Parish Chief: 24h
- L2 CDO: 48h
- L3 District: 72h
- L4 NSR Unit: 7d

Per SAD AC: a grievance resolved to a data correction opens a linked
UPD ChangeRequest. The link is recorded here; the auto-open workflow
lands in Sprint 2.5.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit as emit_audit

from .models import Category, Grievance, GrievanceStatus, Tier

SLA_BY_TIER = {
    Tier.L1_PARISH_CHIEF: timedelta(hours=24),
    Tier.L2_CDO: timedelta(hours=48),
    Tier.L3_DISTRICT: timedelta(hours=72),
    Tier.L4_NSR_UNIT: timedelta(days=7),
}


class GrievanceError(Exception):
    """A GRM transition is forbidden under current state."""


def _set_sla(grievance: Grievance) -> None:
    grievance.sla_deadline = grievance.opened_at + SLA_BY_TIER[grievance.tier]


@transaction.atomic
def open_grievance(
    *,
    category: str,
    description: str,
    household_id: str = "",
    member_id: str = "",
    reporter_name: str = "",
    reporter_phone: str = "",
    reporter_relationship: str = "",
    tier: str = Tier.L1_PARISH_CHIEF,
    assigned_to: str = "",
    actor: str = "",
    sub_category: str = "",
) -> Grievance:
    if category not in Category.values:
        raise GrievanceError(f"unknown category: {category!r}")
    g = Grievance.objects.create(
        category=category,
        sub_category=sub_category,
        description=description,
        household_id=household_id,
        member_id=member_id,
        reporter_name=reporter_name,
        reporter_phone=reporter_phone,
        reporter_relationship=reporter_relationship,
        tier=tier,
        status=GrievanceStatus.OPEN,
        assigned_to=assigned_to,
    )
    _set_sla(g)
    g.save(update_fields=["sla_deadline"])
    emit_audit(
        "create", "grievance", g.id, actor=actor or reporter_name or "anonymous",
        reason=f"category={category} tier={tier}",
        field_changes={"household_id": household_id, "member_id": member_id},
    )
    return g


@transaction.atomic
def assign(grievance: Grievance, *, assigned_to: str, actor: str) -> Grievance:
    if grievance.status not in (GrievanceStatus.OPEN, GrievanceStatus.IN_PROGRESS):
        raise GrievanceError(f"cannot assign from {grievance.status}")
    grievance.assigned_to = assigned_to
    grievance.status = GrievanceStatus.IN_PROGRESS
    grievance.save(update_fields=["assigned_to", "status", "updated_at"])
    emit_audit("update", "grievance", grievance.id, actor=actor,
               reason="assigned",
               field_changes={"assigned_to": assigned_to})
    return grievance


@transaction.atomic
def escalate(grievance: Grievance, *, actor: str, reason: str) -> Grievance:
    """Bump the grievance one tier up. L4 cannot be escalated further."""
    if grievance.status in (GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED):
        raise GrievanceError(f"cannot escalate {grievance.status}")
    if not reason:
        raise GrievanceError("escalation requires a non-empty reason")
    next_tier = {
        Tier.L1_PARISH_CHIEF: Tier.L2_CDO,
        Tier.L2_CDO: Tier.L3_DISTRICT,
        Tier.L3_DISTRICT: Tier.L4_NSR_UNIT,
        Tier.L4_NSR_UNIT: None,
    }[grievance.tier]
    if next_tier is None:
        raise GrievanceError("already at L4 — cannot escalate further")
    prev_tier = grievance.tier
    grievance.tier = next_tier
    grievance.status = GrievanceStatus.ESCALATED
    grievance.assigned_to = ""  # the receiving tier reassigns
    _set_sla(grievance)
    grievance.save(update_fields=["tier", "status", "assigned_to", "sla_deadline", "updated_at"])
    emit_audit("update", "grievance", grievance.id, actor=actor,
               reason=f"escalated: {reason}",
               field_changes={"from": prev_tier, "to": next_tier})
    return grievance


@transaction.atomic
def resolve(
    grievance: Grievance, *, actor: str, narrative: str,
    linked_change_request_id: str = "",
) -> Grievance:
    if grievance.status in (GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED):
        raise GrievanceError(f"already {grievance.status}")
    if not narrative:
        raise GrievanceError("resolution requires a narrative")
    grievance.status = GrievanceStatus.RESOLVED
    grievance.resolved_at = timezone.now()
    grievance.resolution_narrative = narrative
    if linked_change_request_id:
        grievance.linked_change_request_id = linked_change_request_id
    grievance.save(update_fields=[
        "status", "resolved_at", "resolution_narrative",
        "linked_change_request_id", "updated_at",
    ])
    emit_audit("update", "grievance", grievance.id, actor=actor,
               reason="resolved",
               field_changes={"linked_change_request_id": linked_change_request_id})
    return grievance


@transaction.atomic
def close(grievance: Grievance, *, actor: str) -> Grievance:
    if grievance.status != GrievanceStatus.RESOLVED:
        raise GrievanceError(f"can only close RESOLVED (got {grievance.status})")
    grievance.status = GrievanceStatus.CLOSED
    grievance.closed_at = timezone.now()
    grievance.save(update_fields=["status", "closed_at", "updated_at"])
    emit_audit("update", "grievance", grievance.id, actor=actor, reason="closed")
    return grievance
