"""UPD workflow services.

Lifecycle: DRAFT -> SUBMITTED -> PENDING_APPROVAL -> COMMITTED | REJECTED.

The commit step (commit_change_request) applies the diff to the target
entity in a single transaction, writes the paired HouseholdVersion /
MemberVersion row, and emits the audit chain entry. PMT recompute
fires via the post_change_committed signal; apps.pmt subscribes in
apps/pmt/signals.py.

Concurrency: commit re-reads the target row under select_for_update; if
the field's current value differs from the diff's "old" value the
commit aborts with UpdError("concurrent edit detected").

Auto-commit (SAD §4.4.4): VITAL_EVENT (NIRA-pushed death/birth) and
PROGRAMME_STATE (partner-MIS-pushed enrol/exit) bypass approver review
and commit at submit time. The 1% sample policy lives here too —
auto_commit_change_request flags `sampled_for_audit=True` on a
deterministic fraction so QA can audit auto decisions retrospectively.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

import django.dispatch
from django.db import models, transaction
from django.utils import timezone

from apps.data_management.models import (
    AssetOwnership,
    Household,
    HouseholdVersion,
    Member,
    MemberVersion,
)
from apps.security.audit import emit as emit_audit

from .field_catalog import field_meta
from .models import ChangeRequest, ChangeStatus, ChangeType, EntityType, UpdRoutingRule
from .routing import route

ESCALATION_ROLE = "district_m_and_e"
ESCALATION_WINDOW = timedelta(hours=48)

AUTO_COMMIT_CHANGE_TYPES = frozenset({
    ChangeType.VITAL_EVENT,
    ChangeType.PROGRAMME_STATE,
})

DEFAULT_AUTO_SAMPLE_RATE = 0.01  # 1% per SAD §4.4.4

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


def _jsonish_value(value):
    if value is None:
        return ""
    if hasattr(value, "pk") and hasattr(value, "_meta"):
        return value.pk
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _resolve_change_attr(root, key: str):
    if "." not in key:
        return root, key
    category, field = key.split(".", 1)
    if category == "assets":
        household = root if isinstance(root, Household) else root.household
        asset, _ = AssetOwnership.objects.get_or_create(
            household=household,
            asset_type=field,
            is_deleted=False,
            defaults={"count": 0, "sub_region_code": household.sub_region_code},
        )
        return asset, "count"
    if category in ("household", "member"):
        return root, field
    meta = field_meta(category, field)
    if not meta:
        raise UpdError(f"unknown field {key!r}")
    try:
        detail = getattr(root, category)
    except Exception as e:  # noqa: BLE001
        raise UpdError(f"missing detail record for {category!r}") from e
    return detail, field


def _coerce_for_field(obj, field_name: str, value):
    field = obj._meta.get_field(field_name)
    if value == "" and getattr(field, "null", False):
        return None
    if isinstance(field, models.ForeignKey):
        return field.remote_field.model.objects.get(pk=value)
    if isinstance(field, (models.BooleanField,)):
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes", "y")
    if isinstance(field, (models.IntegerField, models.PositiveIntegerField, models.PositiveSmallIntegerField)):
        return int(value)
    if isinstance(field, models.DecimalField):
        from decimal import Decimal
        return Decimal(str(value))
    if isinstance(field, models.DateField):
        from datetime import date
        return date.fromisoformat(str(value))
    return value


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
def hold_change_request(
    req: ChangeRequest, *, approver: str, reason: str,
) -> ChangeRequest:
    """PENDING_APPROVAL -> ON_HOLD. Reviewer parks the request pending
    more info (evidence, NIRA reconciliation, linked GRM case). Same
    no-self-approve + non-empty-reason guards as reject."""
    if req.status != ChangeStatus.PENDING_APPROVAL:
        raise UpdError(f"can only hold PENDING_APPROVAL (got {req.status})")
    if not reason:
        raise UpdError("hold requires a non-empty reason")
    if approver == req.requester:
        raise UpdError("AC-UPD-NO-SELF-APPROVE: requester cannot hold own request")
    req.status = ChangeStatus.ON_HOLD
    req.approver = approver
    req.decided_at = timezone.now()
    req.decision_reason = reason
    req.save(update_fields=[
        "status", "approver", "decided_at", "decision_reason", "updated_at",
    ])
    emit_audit("hold", "change_request", req.id, actor=approver, reason=reason)
    return req


@transaction.atomic
def release_change_request(
    req: ChangeRequest, *, approver: str, reason: str = "",
) -> ChangeRequest:
    """ON_HOLD -> PENDING_APPROVAL. Reviewer reopens after the held
    information arrives. SLA deadline is left untouched (the breach
    sweep handles re-escalation if it lapsed during the hold)."""
    if req.status != ChangeStatus.ON_HOLD:
        raise UpdError(f"can only release ON_HOLD (got {req.status})")
    if approver == req.requester:
        raise UpdError("AC-UPD-NO-SELF-APPROVE: requester cannot release own request")
    req.status = ChangeStatus.PENDING_APPROVAL
    req.approver = ""
    req.decided_at = None
    req.decision_reason = ""
    req.save(update_fields=[
        "status", "approver", "decided_at", "decision_reason", "updated_at",
    ])
    emit_audit("release", "change_request", req.id, actor=approver, reason=reason or "released from hold")
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
        obj, attr = _resolve_change_attr(target, field)
        current = _jsonish_value(getattr(obj, attr))
        if current != change["old"]:
            raise UpdError(
                f"concurrent edit detected on {field}: live={current!r} "
                f"expected_old={change['old']!r}"
            )

    # Apply the new values.
    saves: dict[models.Model, set[str]] = {}
    for field, change in (req.changes or {}).items():
        obj, attr = _resolve_change_attr(target, field)
        setattr(obj, attr, _coerce_for_field(obj, attr, change["new"]))
        saves.setdefault(obj, set()).add(attr)
    applied_fields = []
    for obj, fields in saves.items():
        update_fields = sorted(fields)
        if hasattr(obj, "updated_at"):
            update_fields.append("updated_at")
        obj.save(update_fields=update_fields)
        applied_fields.extend(
            f if obj is target else f"{obj._meta.model_name}.{f}"
            for f in sorted(fields)
        )

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

    # US-CONSENT-16 — head-change re-consent. If this change set a new
    # household head, the new head must carry active REGISTRATION consent or a
    # re-capture sub-task is opened. Inert when CONSENT_MODULE_ENABLED is off.
    head_changed = any(
        str(k).split(".")[-1] in ("head_member", "head_member_id")
        for k in (req.changes or {})
    )
    if (req.entity_type == EntityType.HOUSEHOLD and head_changed
            and getattr(target, "head_member_id", None)):
        from apps.consent import services as consent_services
        consent_services.require_head_registration_consent(
            head_member=target.head_member, actor=approver)

    return req


def _is_sampled(cr_id: str, sample_rate: float) -> bool:
    """Deterministic sampler — same CR id always samples the same way.

    Hash the id, take the leading bytes mod 10_000, compare to the
    rate × 10_000 threshold. Reproducible across runs, no RNG state.
    """
    if sample_rate <= 0:
        return False
    if sample_rate >= 1:
        return True
    digest = hashlib.sha256(cr_id.encode("ascii")).digest()
    bucket = int.from_bytes(digest[:4], "big") % 10_000
    return bucket < int(sample_rate * 10_000)


@transaction.atomic
def auto_commit_change_request(
    req: ChangeRequest, *, sample_rate: float = DEFAULT_AUTO_SAMPLE_RATE,
) -> ChangeRequest:
    """Auto-commit a VITAL_EVENT or PROGRAMME_STATE request.

    Routes through the same submit + commit pipeline so audit and
    versioning are identical to the manual path, but uses the system
    identifier from routing (e.g., 'nira_auto') as the approver and
    sets `allow_self=True` to bypass the no-self-approve guard.

    Refuses any change_type that isn't in AUTO_COMMIT_CHANGE_TYPES —
    a CORRECTION must go through human review, no shortcuts.

    Flags `sampled_for_audit=True` deterministically for a fraction of
    requests so QA can review auto decisions (SAD §4.4.4 sample policy).
    """
    if req.change_type not in AUTO_COMMIT_CHANGE_TYPES:
        raise UpdError(
            f"auto_commit_change_request rejects change_type={req.change_type!r}; "
            f"only {sorted(AUTO_COMMIT_CHANGE_TYPES)} are eligible"
        )
    if req.status != ChangeStatus.DRAFT:
        raise UpdError(f"auto-commit requires DRAFT (got {req.status})")

    submit_change_request(req)
    system_role, _ = route(req.change_type, pmt_relevant=req.pmt_relevant)
    commit_change_request(req, approver=system_role, allow_self=True)

    if _is_sampled(req.id, sample_rate):
        req.sampled_for_audit = True
        req.save(update_fields=["sampled_for_audit", "updated_at"])
        emit_audit(
            "sample", "change_request", req.id, actor="auto-sampler",
            reason=f"sample_rate={sample_rate}",
        )

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


# ---------------------------------------------------------------------------
# SLA-breach auto-escalation (US-S7-001)


@transaction.atomic
def escalate_change_request(cr: ChangeRequest) -> ChangeRequest:
    """Bump a single PENDING_APPROVAL request to district M&E and
    extend its SLA window. Caller is responsible for the
    'past sla_deadline' check — this is the per-row primitive."""
    if cr.status != ChangeStatus.PENDING_APPROVAL:
        raise UpdError(
            f"can only escalate PENDING_APPROVAL (got {cr.status})",
        )
    prev_role = cr.required_role
    cr.required_role = ESCALATION_ROLE
    cr.sla_deadline = timezone.now() + ESCALATION_WINDOW
    cr.save(update_fields=["required_role", "sla_deadline", "updated_at"])
    emit_audit(
        "escalate", "change_request", cr.id, actor="sla-auto-escalator",
        reason=f"SLA breached; was {prev_role}",
        field_changes={
            "from_role": prev_role, "to_role": ESCALATION_ROLE,
            "new_sla_deadline": cr.sla_deadline.isoformat(),
        },
    )
    return cr


def escalate_stale_change_requests() -> dict[str, int]:
    """Sweep every PENDING_APPROVAL row whose sla_deadline has lapsed
    AND whose required_role isn't already at the escalation role.
    The second clause makes the sweep idempotent — re-running cannot
    re-escalate an already-escalated row, so the audit chain doesn't
    fill up with duplicate escalate events."""
    now = timezone.now()
    stale = list(
        ChangeRequest.objects.filter(
            status=ChangeStatus.PENDING_APPROVAL,
            sla_deadline__lt=now,
        ).exclude(required_role=ESCALATION_ROLE),
    )
    for cr in stale:
        escalate_change_request(cr)
    return {"candidates": len(stale), "escalated": len(stale)}


# ---------------------------------------------------------------------------
# UpdRoutingRule — versioned replacement (HANDOFF Cat 2.1)

class RoutingReplaceError(Exception):
    """The requested routing-rule replacement is forbidden."""


@transaction.atomic
def replace_routing_rule(
    *,
    change_type: str,
    pmt_relevant: bool,
    required_role: str,
    sla_hours: int,
    note: str = "",
    actor: str = "system",
) -> UpdRoutingRule:
    """Replace the active routing row for `(change_type, pmt_relevant)`
    in two atomic steps:

    1. Insert a new row with `is_active=True` carrying the new
       `required_role` / `sla_hours` / `note`.
    2. Flip the previous active row to `is_active=False`.

    The model's partial-unique `upd_routing_unique_active_per_tuple`
    constraint enforces "at most one active row" — if the trigger ever
    fires we have a bug. Inactive rows are retained for the history
    endpoint.

    Emits `upd_routing.replaced` with old/new role + sla diff.
    """
    change_type = str(change_type)
    if change_type not in {c.value for c in ChangeType}:
        raise RoutingReplaceError(f"unknown change_type {change_type!r}")
    if sla_hours <= 0:
        raise RoutingReplaceError("sla_hours must be positive")
    if not required_role:
        raise RoutingReplaceError("required_role must be non-empty")

    prior = (
        UpdRoutingRule.objects
        .select_for_update()
        .filter(
            change_type=change_type,
            pmt_relevant=pmt_relevant,
            is_active=True,
        )
        .first()
    )

    # Short-circuit no-ops so we don't spam the audit chain with
    # identity replacements.
    if prior and (
        prior.required_role == required_role
        and prior.sla_hours == sla_hours
        and prior.note == note
    ):
        raise RoutingReplaceError("nothing changed")

    if prior:
        prior.is_active = False
        prior.save(update_fields=["is_active", "updated_at"])

    new_row = UpdRoutingRule.objects.create(
        change_type=change_type,
        pmt_relevant=pmt_relevant,
        required_role=required_role,
        sla_hours=sla_hours,
        is_active=True,
        note=note,
    )

    emit_audit(
        action="upd_routing.replaced",
        entity_type="update_workflow.routing_rule",
        entity_id=str(new_row.pk),
        actor=actor,
        reason=f"change_type={change_type} pmt_relevant={pmt_relevant}",
        field_changes={
            "before": {
                "id": prior.pk if prior else None,
                "required_role": prior.required_role if prior else None,
                "sla_hours": prior.sla_hours if prior else None,
                "note": prior.note if prior else None,
            },
            "after": {
                "id": new_row.pk,
                "required_role": new_row.required_role,
                "sla_hours": new_row.sla_hours,
                "note": new_row.note,
            },
        },
    )
    return new_row


def compute_breach_rate(*, change_type: str, days: int = 30) -> float:
    """Percentage of ChangeRequests in the last `days` whose
    `decided_at` exceeded `created_at + sla_hours`. Used by the Admin
    Console UPD-routing stats column."""
    cutoff = timezone.now() - timedelta(days=days)
    qs = ChangeRequest.objects.filter(
        change_type=change_type,
        decided_at__isnull=False,
        decided_at__gte=cutoff,
    )
    total = qs.count()
    if total == 0:
        return 0.0
    # SLA is enforced via sla_deadline on the ChangeRequest itself —
    # walk the queryset and count breaches in Python rather than try
    # to express "decided_at > sla_deadline" cross-DB.
    breached = sum(
        1 for cr in qs.only("decided_at", "sla_deadline")
        if cr.sla_deadline and cr.decided_at > cr.sla_deadline
    )
    return round(100.0 * breached / total, 2)
