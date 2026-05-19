"""DSA signature workflow — US-S23-010 / ADR-0012.

`SignatureProvider` is the abstract surface every DSA-signing
integration implements. `StubSignatureProvider` is the default
(in-memory, no external calls) used in tests, dev, and any
environment where PARTNERS_DOCUSIGN_ENABLED is false. The
concrete DocuSign client lives at
apps/partners/integrations/docusign.py and is only loaded when
the flag is on.

`submit_for_signoff(dsa, actor)` is the single state transition
the API surfaces. It:
  1. Validates dsa.status is "draft".
  2. Creates 3 DsaSignature rows (sequence_order 1/2/3) — one
     per role in the dsa_signer_role ChoiceList.
  3. Enforces ADR-0012's self-sign-off prohibition by checking
     signer_email uniqueness across the three signatures.
  4. Sets dsa.status = "pending_signature".
  5. Dispatches the first envelope via the active provider.
  6. Emits AuditEvent rows per ADR-0012's audit-chain table.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit as emit_audit

if TYPE_CHECKING:
    from apps.partners.models import DataSharingAgreement, DsaSignature


class SignatureError(Exception):
    """Raised when the signature workflow rejects a transition."""


@dataclass(slots=True)
class EnvelopeResult:
    """What a provider returns when it accepts an envelope."""
    envelope_id: str
    sent_at: object  # datetime


class SignatureProvider(ABC):
    """Per ADR-0012, the workflow is provider-agnostic. The
    StubSignatureProvider auto-completes envelopes synchronously
    so the dual-approval state machine exercises end-to-end in
    tests; the DocuSign client behaves asynchronously and feeds
    state through webhook callbacks."""

    @abstractmethod
    def send_envelope(
        self, signature: DsaSignature, template_key: str,
    ) -> EnvelopeResult:
        ...

    @abstractmethod
    def cancel_envelope(self, signature: DsaSignature) -> None:
        ...


class StubSignatureProvider(SignatureProvider):
    """No external network calls. Returns a deterministic envelope
    id derived from the signature's ULID so tests can assert on it.
    Does NOT auto-progress the signature row to "signed" — that
    transition stays in the caller's hands so the test verifies the
    full sign action separately."""

    def send_envelope(
        self, signature: DsaSignature, template_key: str,
    ) -> EnvelopeResult:
        envelope_id = f"stub-env-{signature.id}"
        signature.docusign_envelope_id = envelope_id
        signature.save(update_fields=["docusign_envelope_id", "updated_at"])
        return EnvelopeResult(
            envelope_id=envelope_id, sent_at=timezone.now(),
        )

    def cancel_envelope(self, signature: DsaSignature) -> None:
        signature.docusign_envelope_id = ""
        signature.save(update_fields=["docusign_envelope_id", "updated_at"])


def get_provider() -> SignatureProvider:
    """Returns the configured SignatureProvider. The DocuSign client
    is opt-in via PARTNERS_DOCUSIGN_ENABLED; everything else uses
    the stub."""
    if getattr(settings, "PARTNERS_DOCUSIGN_ENABLED", False):
        from apps.partners.integrations.docusign import DocuSignProvider
        return DocuSignProvider()
    return StubSignatureProvider()


# Sign-off chain shape per ADR-0012. Position 0 is the first
# signature collected (Partner Auth Signatory via DocuSign), 1 is
# NSR Unit Lead in console, 2 is DPO in console.
_CHAIN: list[tuple[int, str, str]] = [
    (1, "partner_auth_signatory", "docusign"),
    (2, "nsr_unit_lead",          "in_console"),
    (3, "dpo",                    "in_console"),
]


@transaction.atomic
def submit_for_signoff(
    dsa: DataSharingAgreement,
    *,
    actor: str,
    partner_signer_email: str,
    partner_signer_name: str = "",
    nsr_unit_lead_email: str,
    nsr_unit_lead_name: str = "",
    dpo_email: str,
    dpo_name: str = "",
) -> DataSharingAgreement:
    """Atomic submit. Raises SignatureError on validation failure.
    Returns the DSA with its three signatures attached."""
    from apps.partners.models import DsaSignature

    if dsa.status != "draft":
        raise SignatureError(
            f"DSA {dsa.reference} is not in draft (got {dsa.status!r})",
        )

    emails = {
        "partner_auth_signatory": partner_signer_email.strip().lower(),
        "nsr_unit_lead": nsr_unit_lead_email.strip().lower(),
        "dpo": dpo_email.strip().lower(),
    }
    if len(set(emails.values())) < 3:
        # ADR-0012 self-sign-off prohibition. Belt-and-braces with
        # the DB-level UniqueConstraint(dsa, signer_email).
        raise SignatureError(
            "Self sign-off: the three signatures must use distinct emails.",
        )

    name_for = {
        "partner_auth_signatory": partner_signer_name,
        "nsr_unit_lead": nsr_unit_lead_name,
        "dpo": dpo_name,
    }

    signatures = []
    for seq, role, method in _CHAIN:
        sig = DsaSignature.objects.create(
            dsa=dsa, sequence_order=seq,
            signer_role=role,
            signer_email=emails[role],
            signer_name=name_for[role],
            method=method,
            status="pending",
        )
        signatures.append(sig)

    dsa.status = "pending_signature"
    dsa.save(update_fields=["status", "updated_at"])

    emit_audit(
        actor=actor, action="submit",
        entity_type="dsa", entity_id=dsa.id,
        reason=f"submit-for-signoff: {len(signatures)} signatures pending",
    )

    # Dispatch the first envelope via the active provider.
    provider = get_provider()
    first = signatures[0]
    template_key = _template_key_for(dsa)
    provider.send_envelope(first, template_key)
    emit_audit(
        actor=actor, action="envelope_sent",
        entity_type="dsa_signature", entity_id=first.id,
        reason=first.docusign_envelope_id or "stub",
    )

    return dsa


def _template_key_for(dsa: DataSharingAgreement) -> str:
    """Per ADR-0011 decision 1, the DocuSign template is chosen by
    partner.type. Today we encode the type code directly as the key
    (e.g. 'ministry', 'multilateral'); future iterations can move
    this onto ChoiceOption.metadata if the catalogue gets richer."""
    return f"dsa-{dsa.partner.type or 'default'}"


@transaction.atomic
def record_signature(
    signature: DsaSignature,
    *,
    actor: str,
) -> DsaSignature:
    """Mark a signature as signed and advance the chain (dispatch
    the next envelope, or activate the DSA if this was the last
    one). Used both by the in-console click action and by the
    DocuSign webhook handler.
    """
    from apps.partners.models import DsaSignature

    if signature.status != "pending":
        raise SignatureError(
            f"Signature is not pending (got {signature.status!r})",
        )

    signature.status = "signed"
    signature.signed_at = timezone.now()
    signature.save(update_fields=["status", "signed_at", "updated_at"])

    emit_audit(
        actor=actor, action="sign",
        entity_type="dsa_signature", entity_id=signature.id,
        reason=f"{signature.signer_role} · {signature.signer_email}",
    )

    next_sig = (
        DsaSignature.objects
        .filter(dsa=signature.dsa, status="pending")
        .order_by("sequence_order")
        .first()
    )
    if next_sig:
        if next_sig.method == "docusign":
            get_provider().send_envelope(
                next_sig, template_key=_template_key_for(signature.dsa),
            )
            emit_audit(
                actor=actor, action="envelope_sent",
                entity_type="dsa_signature", entity_id=next_sig.id,
                reason=next_sig.docusign_envelope_id or "stub",
            )
    else:
        # All signed — activate.
        dsa = signature.dsa
        dsa.status = "active"
        dsa.signed_at = timezone.now()
        dsa.save(update_fields=["status", "signed_at", "updated_at"])
        emit_audit(
            actor=actor, action="activate",
            entity_type="dsa", entity_id=dsa.id,
            reason="all three signatures complete",
        )

    return signature


@transaction.atomic
def decline_signature(
    signature: DsaSignature,
    *,
    actor: str,
    reason: str,
) -> DsaSignature:
    """Decline a signature; the DSA reverts to draft so the
    originator can revise and resubmit (ADR-0012 §"Reversal")."""
    if signature.status != "pending":
        raise SignatureError(
            f"Signature is not pending (got {signature.status!r})",
        )

    signature.status = "declined"
    signature.decline_reason = reason
    signature.save(
        update_fields=["status", "decline_reason", "updated_at"],
    )
    emit_audit(
        actor=actor, action="decline",
        entity_type="dsa_signature", entity_id=signature.id,
        reason=f"{signature.signer_role} · {reason}",
    )

    dsa = signature.dsa
    dsa.status = "draft"
    dsa.save(update_fields=["status", "updated_at"])
    emit_audit(
        actor=actor, action="suspend",
        entity_type="dsa", entity_id=dsa.id,
        reason=f"declined by {signature.signer_role}",
    )
    return signature
