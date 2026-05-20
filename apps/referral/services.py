"""REF services — outbound referral state machine + signed webhook.

State machine: SENT → ACCEPTED → ENROLLED → EXITED, with REJECTED as a
terminal alternative at any point. send_referral_webhook is a stub that
returns a delivery id; actual HTTP delivery is via a Celery task (see
SAD §6.1 — signed payload, mTLS) that lands when the Celery surface
arrives in Sprint 3.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit as emit_audit

from .models import (
    Programme,
    ProgrammeEnrolment,
    Referral,
)

# Coded values — sourced from the referral_status and
# programme_enrolment_status ChoiceLists (US-S26-002 / US-S25-006).
# Per ADR-0015 the TextChoices enums were removed; service code
# uses the bare codes alongside the ChoiceList catalogue.
REF_SENT     = "sent"
REF_ACCEPTED = "accepted"
REF_ENROLLED = "enrolled"  # terminal — referral became an enrolment
REF_REJECTED = "rejected"
REF_EXITED   = "exited"

ENROL_ACTIVE    = "active"     # renamed from 'enrolled' per ADR-0015 §"Decision 4"
ENROL_SUSPENDED = "suspended"
ENROL_PENDING   = "pending"
ENROL_EXITED    = "exited"


class ReferralError(Exception):
    """A referral transition is forbidden under current state."""


def sign_payload(payload: dict, secret: str) -> str:
    """HMAC-SHA256 signature of the canonical JSON payload, hex-encoded."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), blob, hashlib.sha256).hexdigest()


@transaction.atomic
def send_referral(*, programme: Programme, household, actor: str,
                  eligibility_rule_version: int = 1) -> Referral:
    """Open a new referral with status=SENT. The webhook delivery is a
    follow-up via send_referral_webhook (Celery-driven in Sprint 3)."""
    if not programme.is_active:
        raise ReferralError(f"programme {programme.code} is inactive")
    referral = Referral.objects.create(
        programme=programme, household=household,
        eligibility_rule_version=eligibility_rule_version,
        status=REF_SENT,
    )
    emit_audit(
        "create", "referral", referral.id, actor=actor,
        reason=f"send to programme {programme.code}",
        field_changes={"household_id": household.id, "programme_id": programme.id},
    )
    return referral


@transaction.atomic
def send_referral_webhook(referral: Referral) -> str:
    """Stub the outbound HTTP POST. Returns a fresh delivery id and
    records when we 'sent' it. The actual network call lands when the
    Celery + retry framework is wired (Sprint 3).
    """
    payload = {
        "referral_id": referral.id,
        "household_id": referral.household_id,
        "programme_code": referral.programme.code,
        "eligibility_rule_version": referral.eligibility_rule_version,
        "sent_at": referral.sent_at.isoformat(),
    }
    signature = sign_payload(payload, referral.programme.webhook_secret or "dev-secret")
    delivery_id = f"dly-{uuid.uuid4().hex[:16]}"
    referral.last_delivery_id = delivery_id
    referral.last_delivery_at = timezone.now()
    referral.save(update_fields=["last_delivery_id", "last_delivery_at"])
    emit_audit(
        "update", "referral", referral.id, actor="system",
        reason="webhook-delivered (stub)",
        field_changes={"delivery_id": delivery_id, "signature": signature[:16] + "..."},
    )
    return delivery_id


@transaction.atomic
def accept_referral(referral: Referral, *, actor: str,
                    programme_side_id: str = "") -> Referral:
    if referral.status != REF_SENT:
        raise ReferralError(f"only SENT can be accepted (got {referral.status})")
    referral.status = REF_ACCEPTED
    referral.accepted_at = timezone.now()
    if programme_side_id:
        referral.programme_side_id = programme_side_id
    referral.save(update_fields=["status", "accepted_at", "programme_side_id"])
    emit_audit("update", "referral", referral.id, actor=actor, reason="accepted")
    return referral


@transaction.atomic
def reject_referral(referral: Referral, *, actor: str, reason: str) -> Referral:
    if referral.status not in (REF_SENT, REF_ACCEPTED):
        raise ReferralError(f"cannot reject from {referral.status}")
    if not reason:
        raise ReferralError("reject requires a non-empty reason")
    referral.status = REF_REJECTED
    referral.rejected_at = timezone.now()
    referral.reason = reason
    referral.save(update_fields=["status", "rejected_at", "reason"])
    emit_audit("reject", "referral", referral.id, actor=actor, reason=reason)
    return referral


@transaction.atomic
def enrol_household(
    referral: Referral, *, actor: str,
    effective_date: date | None = None,
    payment_metadata: dict | None = None,
) -> ProgrammeEnrolment:
    """ACCEPTED -> ENROLLED, and create the ProgrammeEnrolment row."""
    if referral.status != REF_ACCEPTED:
        raise ReferralError(f"only ACCEPTED can enrol (got {referral.status})")
    enrolment = ProgrammeEnrolment.objects.create(
        programme=referral.programme,
        household=referral.household,
        referral=referral,
        status=ENROL_ACTIVE,
        effective_date=effective_date or timezone.now().date(),
        payment_metadata=payment_metadata or {},
    )
    referral.status = REF_ENROLLED
    referral.enrolled_at = timezone.now()
    referral.save(update_fields=["status", "enrolled_at"])
    emit_audit(
        "create", "programme_enrolment", enrolment.id, actor=actor,
        reason=f"enrolled in {referral.programme.code}",
        field_changes={
            "referral_id": referral.id,
            "household_id": referral.household_id,
        },
    )
    return enrolment


@transaction.atomic
def exit_enrolment(enrolment: ProgrammeEnrolment, *, actor: str, reason: str) -> ProgrammeEnrolment:
    if enrolment.status == ENROL_EXITED:
        raise ReferralError("already EXITED")
    if not reason:
        raise ReferralError("exit requires a reason")
    enrolment.status = ENROL_EXITED
    enrolment.exit_reason = reason
    enrolment.save(update_fields=["status", "exit_reason", "updated_at"])
    # Bubble up to the originating referral if any.
    if enrolment.referral_id:
        ref = enrolment.referral
        ref.status = REF_EXITED
        ref.exited_at = timezone.now()
        ref.reason = reason
        ref.save(update_fields=["status", "exited_at", "reason"])
    emit_audit("update", "programme_enrolment", enrolment.id, actor=actor,
               reason=f"exited: {reason}")
    return enrolment
