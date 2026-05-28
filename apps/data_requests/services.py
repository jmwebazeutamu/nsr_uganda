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
from apps.security.notifications import send_notification

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


def _allowed_geo_codes(
    dsa: DataSharingAgreement, level: str,
) -> set[str] | None:
    """Codes the DSA permits at `level`. Walks `geographic_scope`
    filtered to that level. Returns None when the DSA isn't scoped
    at this level — meaning unrestricted on this dimension
    (per ADR-0011 §4: a DSA may scope at any level)."""
    codes = list(
        dsa.geographic_scope
        .filter(level=level)
        .values_list("code", flat=True),
    )
    if not codes:
        return None
    return set(codes)


def _allowed_sub_region_codes(dsa: DataSharingAgreement) -> set[str] | None:
    """Back-compat wrapper for the most commonly-used level. New
    callers should use `_allowed_geo_codes(dsa, 'sub_region')`."""
    return _allowed_geo_codes(dsa, "sub_region")


# US-S27-016: payload key → GeographicUnit.level. The validator
# walks each entry, asks the DSA which codes it permits at that
# level, and rejects extras. Add a new level here when the
# builder catalogue gains a new geographic predicate.
_GEO_PAYLOAD_KEYS: dict[str, str] = {
    "region_codes":     "region",
    "sub_region_codes": "sub_region",
    "district_codes":   "district",
    "county_codes":     "county",
    "sub_county_codes": "sub_county",
    "parish_codes":     "parish",
    "village_codes":    "village",
}


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

    # Geographic scope — one validator per UBOS level. The DSA's
    # geographic_scope M2M may be populated at any level; we only
    # constrain when it has codes at the level the payload asks
    # for. Unrestricted-on-this-level means the request passes
    # through, even if a coarser level is restricted (the request
    # would already have been rejected at that coarser key if it
    # supplied one). See ADR-0011 §4.
    for payload_key, level in _GEO_PAYLOAD_KEYS.items():
        wanted = payload.get(payload_key)
        if not wanted:
            continue
        allowed = _allowed_geo_codes(dsa, level)
        if allowed is None:
            continue
        extras = set(wanted) - allowed
        if extras:
            _violation(
                payload_key, list(extras),
                f"geographic_scope[{level}]={sorted(allowed)}",
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

    # Notify the partner that their request was approved and is now
    # queued for delivery. The actual extract bundle email lands later
    # (deliver_data_request); this is the "your request is moving"
    # signal so partners aren't left wondering.
    partner_email = getattr(req.dsa.partner, "primary_email", "") or ""
    send_notification(
        to=[partner_email, req.requester],
        subject=(
            f"[NSR MIS] Data request {str(req.id)[:12]}… approved"
        ),
        body=(
            f"Your data request against DSA {req.dsa.reference} "
            f"(v{req.dsa.version}) has been approved by {approver}.\n\n"
            f"The extract will be generated and delivered shortly. "
            f"You'll receive a second email when the bundle is ready, "
            f"including the manifest SHA-256 and download link.\n"
        ),
        entity_type="data_request",
        entity_id=str(req.id),
        audit_actor=approver,
        audit_action="data_request.approved.notified",
        audit_reason=f"approved by {approver}",
    )
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

    # Notify the requester + partner contact with the verbatim
    # reason so they know what to revise if they want to resubmit.
    partner_email = getattr(req.dsa.partner, "primary_email", "") or ""
    send_notification(
        to=[partner_email, req.requester],
        subject=(
            f"[NSR MIS] Data request {str(req.id)[:12]}… REJECTED"
        ),
        body=(
            f"Your data request against DSA {req.dsa.reference} "
            f"(v{req.dsa.version}) was rejected by {approver}.\n\n"
            f"Reason given:\n{reason}\n\n"
            f"Revise the request scope or contact the approver if "
            f"anything is unclear.\n"
        ),
        entity_type="data_request",
        entity_id=str(req.id),
        audit_actor=approver,
        audit_action="data_request.rejected.notified",
        audit_reason=f"rejected by {approver}",
    )
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

    # Tell the partner the bundle is ready, with the manifest SHA so
    # they can verify integrity, and the expiry window so they know
    # how long they have to download. Per ADR-0013 (Sprint 23) the
    # partner_code lives on the audit event too — keeping the body
    # human-readable here, the audit row is the structured form.
    partner_email = getattr(req.dsa.partner, "primary_email", "") or ""
    send_notification(
        to=[partner_email, req.requester],
        subject=(
            f"[NSR MIS] Data extract ready · "
            f"{str(req.id)[:12]}… · {row_count} rows"
        ),
        body=(
            f"The data extract for your request against DSA "
            f"{req.dsa.reference} (v{req.dsa.version}) is ready.\n\n"
            f"Rows delivered: {row_count:,}\n"
            f"Manifest SHA-256: {manifest_sha256}\n"
            f"Available until: {req.expires_at.isoformat()}\n\n"
            f"Download the bundle from the partner DRS portal before "
            f"the expiry date. After expiry the bundle is purged from "
            f"object storage; you'll need to re-request.\n\n"
            f"Verify the bundle against the manifest SHA-256 above "
            f"before processing — any mismatch indicates tampering "
            f"in transit and should be reported to the DPO immediately.\n"
        ),
        entity_type="data_request",
        entity_id=str(req.id),
        audit_actor=actor,
        audit_action="data_request.delivered.notified",
        audit_reason=(
            f"delivered · {row_count} rows · expires "
            f"{req.expires_at.isoformat()}"
        ),
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


# ---------------------------------------------------------------------------
# Draft seeding (DATA-EXP handoff — ADR-0023 D1)
#
# The Data Explorer module produces a DataRequestDraft when an analyst
# clicks "Request record-level data" on an aggregate view. The draft
# carries the canonical Query JSON the explorer ran, the geographic
# scope the user actually wanted (which may be below the explorer's
# sub-county floor), and the suppressed-aggregate row count as an
# estimate. The DRS workflow takes over from DRAFT → SUBMITTED.
#
# The DSA is supplied by the caller — the Explorer UI presents a
# DSA picker before the handoff fires; if none is supplied we raise
# so the caller can surface the right error (no silent placeholders).

def create_draft(
    payload: dict | None = None,
    *,
    dsa_id: str | None = None,
    requester: str | None = None,
    requester_note: str = "",
    request_payload: dict | None = None,
    source_module: str = "data_explorer",
    explorer_session_id: str | None = None,
    source_query_hash: str | None = None,
) -> DataRequest:
    """Seed a DRAFT DataRequest from the DATA-EXP handoff.

    Two calling forms are supported so the DATA-EXP handoff code +
    contract tests can both target this entry point:

      create_draft({"dsa_id":..., "request_payload":...,
                    "requester":..., ...})              # positional dict
      create_draft(dsa_id=..., requester=..., ...)      # keyword form

    `request_payload` is the canonical Query JSON shape API-DRS already
    accepts (fields, sub_region_codes, programme_codes, max_rows etc.).
    The explorer-side context (source module, session ID, query hash)
    is preserved in the same payload under `_source` so the DPO can
    see the discovery trail when reviewing the submit.

    Raises DrsError if the DSA is missing or inactive — callers must
    pick a DSA before the handoff lands."""
    if payload is not None:
        dsa_id = dsa_id or payload.get("dsa_id")
        requester = requester or payload.get("requester")
        requester_note = requester_note or payload.get("requester_note", "")
        request_payload = request_payload or payload.get("request_payload") or payload
        source_module = payload.get("source_module", source_module)
        explorer_session_id = (
            explorer_session_id or payload.get("explorer_session_id")
        )
        source_query_hash = (
            source_query_hash or payload.get("source_query_hash")
        )
    if not dsa_id:
        raise DrsError("create_draft requires dsa_id")
    if not requester:
        raise DrsError("create_draft requires requester")
    dsa = DataSharingAgreement.objects.filter(id=dsa_id).first()
    if dsa is None:
        raise DrsError(f"unknown DSA {dsa_id!r}")
    if dsa.status not in ("active", "draft", "pending_signature"):
        raise DrsError(
            f"DSA {dsa.reference} is in {dsa.status}; cannot accept a draft"
        )

    payload = dict(request_payload or {})
    source = payload.get("_source") or {}
    source.update({
        "module": source_module,
        "explorer_session_id": explorer_session_id or "",
        "source_query_hash": source_query_hash or "",
    })
    payload["_source"] = source

    req = DataRequest.objects.create(
        dsa=dsa,
        requester=requester,
        requester_note=requester_note,
        request_payload=payload,
        status=RequestStatus.DRAFT,
    )
    emit_audit(
        "draft_created", "data_request", req.id,
        actor=requester,
        reason=f"seeded from {source_module}",
        field_changes={
            "dsa_reference": dsa.reference,
            "source_module": source_module,
            "explorer_session_id": explorer_session_id or "",
            "source_query_hash": source_query_hash or "",
        },
    )
    return req
