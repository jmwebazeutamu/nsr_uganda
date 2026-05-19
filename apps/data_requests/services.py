"""API-DRS services — DSA scope validation + DataRequest lifecycle.

Lifecycle: DRAFT -> SUBMITTED -> APPROVED -> DELIVERED -> EXPIRED
                              \\-> REJECTED

Every transition emits one AuditEvent. The submit step calls
validate_against_dsa, which is the single point where partner-side
criteria are clipped to the DSA contract. If a partner asks for
fields/regions/programmes outside their DSA, the submit fails — never
silent truncation, per SAD §4.10.

Per ADR-0013 (US-S24) the DSA is the canonical one in apps.partners,
not a DRS-local row. The validator reads canonical fields directly:
field_scope dict, entities_scope.programmes_allowed list,
geographic_scope M2M (sub_region codes resolved per-DSA), and
monthly_row_budget.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.partners.models import DataSharingAgreement
from apps.security.audit import emit as emit_audit

from .models import (
    DataRequest,
    RequestStatus,
)

DEFAULT_DELIVERY_TTL = timedelta(days=30)


class DrsError(Exception):
    """An API-DRS transition or DSA scope check failed."""


# ---------------------------------------------------------------------------
# DSA scope helpers


def _allowed_field_groups(dsa: DataSharingAgreement) -> set[str] | None:
    """Set of allowed top-level field groups (e.g. 'household', 'member',
    'pmt'). Returns None when the DSA's field_scope is empty — by
    contract that means 'unrestricted on this dimension'."""
    fs = dsa.field_scope or {}
    if not fs:
        return None
    return {k for k, v in fs.items() if v}


def _allowed_sub_region_codes(dsa: DataSharingAgreement) -> set[str] | None:
    """Sub-region codes a DSA permits. Walks the canonical
    geographic_scope M2M. Returns None when the DSA isn't geo-scoped."""
    codes = list(
        dsa.geographic_scope
        .filter(level="sub_region")
        .values_list("code", flat=True),
    )
    if not codes:
        return None
    return set(codes)


def _allowed_programme_codes(dsa: DataSharingAgreement) -> set[str] | None:
    """Programme codes a DSA permits. Until the DSA↔Programme M2M lands
    (OI-S24-2), this reads from entities_scope.programmes_allowed."""
    es = dsa.entities_scope or {}
    progs = es.get("programmes_allowed")
    if progs is None:
        return None
    return set(progs)


def _trailing_30d_rows(dsa: DataSharingAgreement) -> int:
    """Sum of rows_delivered on this DSA's partner over the trailing
    30 days. Used by the budget gate at submit time."""
    from apps.partners.models import PartnerUsageDaily
    if not dsa.partner_id:
        return 0
    today = date.today()
    start = today - timedelta(days=29)
    agg = (
        PartnerUsageDaily.objects
        .filter(partner_id=dsa.partner_id, day__gte=start, day__lte=today)
        .aggregate(s=Sum("rows_delivered"))
    )
    return agg["s"] or 0


# ---------------------------------------------------------------------------
# DSA scope validation


def validate_against_dsa(
    payload: dict,
    dsa: DataSharingAgreement,
) -> None:
    """Raise DrsError when `payload` requests anything the canonical
    DSA doesn't authorise.

    Per ADR-0013 the validator runs against the canonical fields. The
    payload's shape is unchanged for backward compatibility with
    existing DRS callers: ``fields`` (group names), ``sub_region_codes``,
    ``programme_codes``, ``max_rows``.
    """
    payload = payload or {}

    def _violation(key: str, extras: list[str], allowed_label: str) -> None:
        emit_audit(
            actor="drs.validator", actor_kind="system",
            action="dsa_scope_violation",
            entity_type="dsa", entity_id=dsa.id,
            reason=f"{key}={sorted(extras)!r} outside {allowed_label}",
        )
        raise DrsError(
            f"{key}={sorted(extras)!r} outside DSA scope "
            f"(allowed {allowed_label})"
        )

    # Field groups
    wanted_fields = payload.get("fields")
    allowed_fields = _allowed_field_groups(dsa)
    if wanted_fields and allowed_fields is not None:
        # Map legacy 'household.id', 'member.name' style → group names.
        groups = {(f or "").partition(".")[0] for f in wanted_fields}
        extras = groups - allowed_fields
        if extras:
            _violation(
                "fields", list(extras),
                f"field_scope={sorted(allowed_fields)}",
            )

    # Geographic scope
    wanted_geo = payload.get("sub_region_codes")
    allowed_geo = _allowed_sub_region_codes(dsa)
    if wanted_geo and allowed_geo is not None:
        extras = set(wanted_geo) - allowed_geo
        if extras:
            _violation(
                "sub_region_codes", list(extras),
                f"geographic_scope={sorted(allowed_geo)}",
            )

    # Programme codes
    wanted_progs = payload.get("programme_codes")
    allowed_progs = _allowed_programme_codes(dsa)
    if wanted_progs and allowed_progs is not None:
        extras = set(wanted_progs) - allowed_progs
        if extras:
            _violation(
                "programme_codes", list(extras),
                f"entities_scope.programmes_allowed={sorted(allowed_progs)}",
            )

    # Monthly row budget — total cap on a single request
    # (kept here for compatibility with the legacy max_rows check;
    # the trailing-30d gate below catches the cumulative variant).
    requested_cap = payload.get("max_rows")
    budget = dsa.monthly_row_budget
    if budget is not None and requested_cap is not None and requested_cap > budget:
        emit_audit(
            actor="drs.validator", actor_kind="system",
            action="dsa_scope_violation",
            entity_type="dsa", entity_id=dsa.id,
            reason=f"max_rows={requested_cap} > monthly_row_budget={budget}",
        )
        raise DrsError(
            f"max_rows={requested_cap} exceeds DSA monthly_row_budget {budget}"
        )

    # Trailing-30d budget — reject if delivering this request would
    # push the partner over their monthly budget.
    if budget is not None and requested_cap is not None:
        already = _trailing_30d_rows(dsa)
        if already + requested_cap > budget:
            emit_audit(
                actor="drs.validator", actor_kind="system",
                action="dsa_budget_exceeded",
                entity_type="dsa", entity_id=dsa.id,
                reason=(
                    f"trailing-30d={already} + requested={requested_cap} "
                    f"> budget={budget}"
                ),
            )
            raise DrsError(
                f"trailing-30d usage {already} + this request {requested_cap} "
                f"would exceed DSA budget {budget}"
            )


# ---------------------------------------------------------------------------
# Lifecycle transitions


def _dsa_window_active(dsa: DataSharingAgreement) -> bool:
    """True when today falls within the DSA's effective window."""
    today = timezone.now().date()
    if dsa.effective_from and today < dsa.effective_from:
        return False
    if dsa.effective_to and today > dsa.effective_to:
        return False
    return True


def submit_data_request(req: DataRequest) -> DataRequest:
    """DRAFT -> SUBMITTED. Validates payload against parent DSA.
    Per ADR-0013 also rejects when partner.status == suspended.

    Validation runs OUTSIDE the atomic state transition so audit
    events written for scope violations / budget breaches survive
    even when the submit is rejected (the transition would otherwise
    roll back the audit row alongside the would-be save).
    """
    if req.status != RequestStatus.DRAFT:
        raise DrsError(f"can only submit DRAFT (got {req.status})")
    if req.dsa.status != "active":
        raise DrsError(
            f"DSA {req.dsa.reference} is not active ({req.dsa.status})"
        )
    if not _dsa_window_active(req.dsa):
        raise DrsError(
            f"DSA {req.dsa.reference} is outside its effective window "
            f"({req.dsa.effective_from}..{req.dsa.effective_to})"
        )
    if req.dsa.partner.status == "suspended":
        raise DrsError(
            f"Partner {req.dsa.partner.code} is suspended"
        )
    validate_against_dsa(req.request_payload or {}, req.dsa)
    return _submit_data_request_atomic(req)


@transaction.atomic
def _submit_data_request_atomic(req: DataRequest) -> DataRequest:
    req.status = RequestStatus.SUBMITTED
    req.submitted_at = timezone.now()
    req.save(update_fields=["status", "submitted_at", "updated_at"])
    emit_audit(
        "submit", "data_request", req.id, actor=req.requester,
        reason=f"dsa={req.dsa.reference}",
        field_changes={"payload_keys": sorted((req.request_payload or {}).keys())},
    )
    return req


@transaction.atomic
def approve_data_request(req: DataRequest, *, approver: str) -> DataRequest:
    """SUBMITTED -> APPROVED. No self-approve."""
    if req.status != RequestStatus.SUBMITTED:
        raise DrsError(f"can only approve SUBMITTED (got {req.status})")
    if approver == req.requester:
        raise DrsError("AC-DRS-NO-SELF-APPROVE: requester cannot approve own request")
    req.status = RequestStatus.APPROVED
    req.approver = approver
    req.decided_at = timezone.now()
    req.save(update_fields=["status", "approver", "decided_at", "updated_at"])
    emit_audit("approve", "data_request", req.id, actor=approver,
               reason="approved")
    return req


@transaction.atomic
def reject_data_request(req: DataRequest, *, approver: str, reason: str) -> DataRequest:
    if req.status != RequestStatus.SUBMITTED:
        raise DrsError(f"can only reject SUBMITTED (got {req.status})")
    if not reason:
        raise DrsError("reject requires a non-empty reason")
    if approver == req.requester:
        raise DrsError("AC-DRS-NO-SELF-APPROVE: requester cannot reject own request")
    req.status = RequestStatus.REJECTED
    req.approver = approver
    req.decided_at = timezone.now()
    req.decision_reason = reason
    req.save(update_fields=[
        "status", "approver", "decided_at", "decision_reason", "updated_at",
    ])
    emit_audit("reject", "data_request", req.id, actor=approver, reason=reason)
    return req


@transaction.atomic
def deliver_data_request(
    req: DataRequest, *, manifest_sha256: str, row_count: int,
    actor: str, ttl: timedelta = DEFAULT_DELIVERY_TTL,
) -> DataRequest:
    """APPROVED -> DELIVERED. Locks the manifest SHA-256 and sets expires_at.

    Delivery itself (writing the export bundle to MinIO, signing the
    URL) is a separate concern handled by a Celery task; this function
    is the side-effect commitment point.

    Per ADR-0013 the AuditEvent now carries structured field_changes
    so the Sprint 23 usage-rollup task can read partner_code without
    parsing free text.
    """
    if req.status != RequestStatus.APPROVED:
        raise DrsError(f"can only deliver APPROVED (got {req.status})")
    if len(manifest_sha256) != 64:
        raise DrsError("manifest_sha256 must be 64 hex chars")
    now = timezone.now()
    req.status = RequestStatus.DELIVERED
    req.delivered_at = now
    req.expires_at = now + ttl
    req.manifest_sha256 = manifest_sha256
    req.row_count_delivered = row_count
    req.save(update_fields=[
        "status", "delivered_at", "expires_at",
        "manifest_sha256", "row_count_delivered", "updated_at",
    ])
    emit_audit(
        "data_request_delivered", "data_request", req.id, actor=actor,
        reason=f"rows={row_count}",
        field_changes={
            "manifest_sha256": manifest_sha256,
            "expires_at": req.expires_at.isoformat(),
            "partner_code": req.dsa.partner.code,
            "partner_id": req.dsa.partner_id,
            "dsa_reference": req.dsa.reference,
            "rows_delivered": row_count,
        },
    )
    return req


@transaction.atomic
def expire_data_request(req: DataRequest, *, actor: str = "system") -> DataRequest:
    """DELIVERED -> EXPIRED. Idempotent — repeats are no-ops."""
    if req.status == RequestStatus.EXPIRED:
        return req
    if req.status != RequestStatus.DELIVERED:
        raise DrsError(f"can only expire DELIVERED (got {req.status})")
    req.status = RequestStatus.EXPIRED
    req.save(update_fields=["status", "updated_at"])
    emit_audit("expire", "data_request", req.id, actor=actor, reason="ttl-reached")
    return req
