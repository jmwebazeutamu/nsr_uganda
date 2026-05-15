"""API-DRS services — DSA scope validation + DataRequest lifecycle.

Lifecycle: DRAFT -> SUBMITTED -> APPROVED -> DELIVERED -> EXPIRED
                              \\-> REJECTED

Every transition emits one AuditEvent. The submit step calls
validate_against_dsa, which is the single point where partner-side
criteria are clipped to the DSA contract. If a partner asks for
fields/regions/programmes outside their DSA, the submit fails — never
silent truncation, per SAD §4.10.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit as emit_audit

from .models import (
    DataRequest,
    DataSharingAgreement,
    DsaStatus,
    RequestStatus,
)

DEFAULT_DELIVERY_TTL = timedelta(days=30)


class DrsError(Exception):
    """An API-DRS transition or DSA scope check failed."""


# ---------------------------------------------------------------------------
# DSA scope validation


def validate_against_dsa(payload: dict, dsa: DataSharingAgreement) -> None:
    """Raise DrsError if `payload` requests anything the DSA does not allow.

    Checks every key the DSA constrains. Missing keys on the DSA side
    mean 'unrestricted on this dimension' — a DSA with no
    'sub_region_codes' allows all sub-regions, by contract.
    """
    scopes = dsa.allowed_scopes or {}

    def _subset(payload_key: str, dsa_key: str) -> None:
        wanted = payload.get(payload_key)
        allowed = scopes.get(dsa_key)
        if wanted is None or allowed is None:
            return
        extras = sorted(set(wanted) - set(allowed))
        if extras:
            raise DrsError(
                f"{payload_key}={extras!r} outside DSA scope "
                f"(allowed {dsa_key}={allowed!r})"
            )

    _subset("fields", "fields")
    _subset("sub_region_codes", "sub_region_codes")
    _subset("programme_codes", "programme_codes")

    max_rows = scopes.get("max_rows_per_request")
    requested_cap = payload.get("max_rows")
    if max_rows is not None and requested_cap is not None and requested_cap > max_rows:
        raise DrsError(
            f"max_rows={requested_cap} exceeds DSA cap {max_rows}"
        )


# ---------------------------------------------------------------------------
# Lifecycle transitions


@transaction.atomic
def submit_data_request(req: DataRequest) -> DataRequest:
    """DRAFT -> SUBMITTED. Validates payload against parent DSA."""
    if req.status != RequestStatus.DRAFT:
        raise DrsError(f"can only submit DRAFT (got {req.status})")
    if req.dsa.status != DsaStatus.ACTIVE:
        raise DrsError(f"DSA {req.dsa.reference} is not ACTIVE ({req.dsa.status})")
    today = timezone.now().date()
    if not (req.dsa.valid_from <= today <= req.dsa.valid_to):
        raise DrsError(
            f"DSA {req.dsa.reference} is outside its validity window "
            f"({req.dsa.valid_from}..{req.dsa.valid_to})"
        )
    validate_against_dsa(req.request_payload or {}, req.dsa)

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
        "deliver", "data_request", req.id, actor=actor,
        reason=f"rows={row_count}",
        field_changes={"manifest_sha256": manifest_sha256,
                       "expires_at": req.expires_at.isoformat()},
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
