"""UPD workflow services.

Lifecycle: DRAFT -> SUBMITTED -> PENDING_APPROVAL -> COMMITTED | REJECTED.

The commit step (commit_change_request) applies the diff to the target
entity in a single transaction, writes the paired HouseholdVersion /
MemberVersion row, and emits the audit chain entry. PMT recompute fires
via the post_change_committed signal — apps.pmt subscribes when it
lands; today the signal has no listeners (no-op).

Concurrency: commit re-reads the target row under select_for_update; if
the field's current value differs from the diff's "old" value the
commit aborts with UpdError("concurrent edit detected").
"""

from __future__ import annotations

from typing import Any

import django.dispatch
from django.db import transaction
from django.utils import timezone

from apps.data_management.models import Household, HouseholdVersion, Member, MemberVersion
from apps.security.audit import emit as emit_audit

from .models import ChangeRequest, ChangeStatus, EntityType
from .routing import route

# Signal fired after a successful commit. apps.pmt will subscribe when
# it exists; until then this is a no-op event bus.
post_change_committed = django.dispatch.Signal()


class UpdError(Exception):
    """A UPD transition is forbidden under current state."""


# ---------------------------------------------------------------------------
# Diff + preview helpers


def compute_diff(entity_type: str, entity_id: str, proposed: dict[str, Any]) -> dict[str, Any]:
    """Compute the field-level diff between the live row and `proposed`.

    Returns {field: {"old": current_value, "new": proposed_value}} skipping
    fields whose current and proposed values already match.
    """
    target = _load_target(entity_type, entity_id)
    diff: dict[str, Any] = {}
    for field, new_value in (proposed or {}).items():
        if not hasattr(target, field):
            raise UpdError(f"unknown field {field!r} on {entity_type}")
        current = getattr(target, field)
        if current != new_value:
            diff[field] = {"old": current, "new": new_value}
    return diff


def _load_target(entity_type: str, entity_id: str, *, lock: bool = False):
    qs = (Household if entity_type == EntityType.HOUSEHOLD else Member).objects.all()
    if lock:
        qs = qs.select_for_update()
    return qs.get(pk=entity_id)


# ---------------------------------------------------------------------------
# Lifecycle transitions


@transaction.atomic
def submit_change_request(req: ChangeRequest) -> ChangeRequest:
    """DRAFT -> PENDING_APPROVAL. Applies routing + SLA from the matrix."""
    if req.status != ChangeStatus.DRAFT:
        raise UpdError(f"can only submit a DRAFT request (got {req.status})")
    if not req.changes:
        raise UpdError("cannot submit a request with no field changes (AC-UPD-DIFF)")
    role, sla_window = route(req.change_type, pmt_relevant=req.pmt_relevant)
    req.required_role = role
    req.sla_deadline = timezone.now() + sla_window
    req.status = ChangeStatus.PENDING_APPROVAL
    req.save(update_fields=["required_role", "sla_deadline", "status", "updated_at"])
    emit_audit(
        "submit", "change_request", req.id, actor=req.requester,
        reason=f"change_type={req.change_type} pmt_relevant={req.pmt_relevant}",
        field_changes={"role": role, "sla_deadline": req.sla_deadline.isoformat()},
    )
    return req


@transaction.atomic
def reject_change_request(req: ChangeRequest, *, approver: str, reason: str) -> ChangeRequest:
    if req.status != ChangeStatus.PENDING_APPROVAL:
        raise UpdError(f"can only reject PENDING_APPROVAL (got {req.status})")
    if not reason:
        raise UpdError("reject requires a non-empty reason")
    if approver == req.requester:
        raise UpdError("AC-UPD-NO-SELF-APPROVE: requester cannot reject own request")
    req.status = ChangeStatus.REJECTED
    req.approver = approver
    req.decided_at = timezone.now()
    req.decision_reason = reason
    req.save(update_fields=[
        "status", "approver", "decided_at", "decision_reason", "updated_at",
    ])
    emit_audit("reject", "change_request", req.id, actor=approver, reason=reason)
    return req


@transaction.atomic
def commit_change_request(
    req: ChangeRequest, *, approver: str, allow_self: bool = False,
) -> ChangeRequest:
    """PENDING_APPROVAL -> COMMITTED. Atomic apply + version snapshot + audit.

    `allow_self` is reserved for the NIRA/programme auto-commit paths
    where 'approver' is a system identifier (route() returns *_auto roles).
    """
    if req.status != ChangeStatus.PENDING_APPROVAL:
        raise UpdError(f"can only commit PENDING_APPROVAL (got {req.status})")
    if not allow_self and approver == req.requester:
        raise UpdError("AC-UPD-NO-SELF-APPROVE: requester cannot approve own request")

    # Re-validate the diff against the live row (concurrent edit detection).
    target = _load_target(req.entity_type, req.entity_id, lock=True)
    for field, change in (req.changes or {}).items():
        current = getattr(target, field)
        if current != change["old"]:
            raise UpdError(
                f"concurrent edit detected on {field}: live={current!r} "
                f"expected_old={change['old']!r}"
            )

    # Apply the new values.
    applied_fields = []
    for field, change in (req.changes or {}).items():
        setattr(target, field, change["new"])
        applied_fields.append(field)
    if applied_fields:
        target.save(update_fields=applied_fields + ["updated_at"])

    # Write the paired _Version row.
    _write_version(req.entity_type, target, req)

    # Mark committed.
    req.status = ChangeStatus.COMMITTED
    req.approver = approver
    req.decided_at = timezone.now()
    req.save(update_fields=["status", "approver", "decided_at", "updated_at"])

    emit_audit(
        "commit", "change_request", req.id, actor=approver,
        reason=f"{len(applied_fields)} field(s)",
        field_changes={"fields": applied_fields, "entity_id": req.entity_id},
    )

    # Fire the post-commit event. PMT subscribes when it lands.
    post_change_committed.send(sender=ChangeRequest, change_request=req, target=target)

    return req


def _write_version(entity_type: str, target, req: ChangeRequest) -> None:
    """Snapshot the now-applied state into the paired *Version table."""
    now = timezone.now()
    if entity_type == EntityType.HOUSEHOLD:
        last = HouseholdVersion.objects.filter(household=target).order_by("-version_number").first()
        next_version = (last.version_number + 1) if last else 1
        if last and last.effective_to is None:
            last.effective_to = now
            last.save(update_fields=["effective_to"])
        HouseholdVersion.objects.create(
            household=target, version_number=next_version,
            effective_from=now, change_request_id=req.id, created_by=req.approver,
            head_member_id=target.head_member_id or "",
            urban_rural=target.urban_rural,
            address_narrative=target.address_narrative,
            gps_lat=target.gps_lat, gps_lng=target.gps_lng,
            gps_accuracy_m=target.gps_accuracy_m,
            dwelling_tenure=target.dwelling_tenure,
            residence_status=target.residence_status,
            current_pmt_score=target.current_pmt_score,
            current_vulnerability_band=target.current_vulnerability_band,
        )
    else:
        last = MemberVersion.objects.filter(member=target).order_by("-version_number").first()
        next_version = (last.version_number + 1) if last else 1
        if last and last.effective_to is None:
            last.effective_to = now
            last.save(update_fields=["effective_to"])
        MemberVersion.objects.create(
            member=target, version_number=next_version,
            effective_from=now, change_request_id=req.id, created_by=req.approver,
            surname=target.surname, first_name=target.first_name,
            other_name=target.other_name,
            relationship_to_head=target.relationship_to_head,
            marital_status=target.marital_status,
            nationality=target.nationality,
            residency_status=target.residency_status,
            birth_certificate_status=target.birth_certificate_status,
            nin_status=target.nin_status,
            nin_hash=target.nin_hash,
            nin_last4=target.nin_last4,
            telephone_1=target.telephone_1,
            telephone_2=target.telephone_2,
        )
