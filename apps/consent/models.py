"""Consent Management (SEC) models — Epic 19, US-CONSENT-01..18.

Per-member, per-purpose consent per SAD §5 Appendix C and DPIA §1. The
module is gated by ``settings.CONSENT_MODULE_ENABLED``; when the flag is off
the downstream consent gates short-circuit to "transparent allow" so existing
functionality is unchanged (see apps.consent.services.consent_state).

Design anchors (see /docs/adr/0024-consent-management-module.md):
- IDs are ULIDs per ADR-0002 (nsr_mis.common.fields.ULIDField).
- ConsentRecord carries a denormalised ``sub_region_code`` copied from the
  member's household in ``save()`` for partition routing per ADR-0005 —
  exactly the Member.save() pattern in apps.data_management.models.
- Fixed enums are Django TextChoices (repo norm: GeographicUnit.Level,
  AuditEvent.Action, ChoiceListStatus) — NOT seeded bootstrap tables.
- ConsentRecordVersion is an append-only paired-version table per SAD §5.3
  following the _VersionBase precedent: it is NOT hash-chained. Integrity
  derives from the AuditEvent emitted on every state change (SEC), which IS
  hash-chained. Each version row records the id of its AuditEvent so the
  integrity job can assert referential completeness (US-CONSENT-10).
- Dual-approval (author != approver) on ConsentPurpose and
  ConsentStatementVersion is enforced in apps.consent.services, mirroring
  apps.dqa.services.approve.

Enum string VALUES are machine codes; the human labels are the display
strings the frontend consent-shared.jsx vocabulary expects verbatim
(CONSENT_STATE_TONE / TICKET_STATE_TONE / LIFECYCLE_TONE / BASIS_LABEL keys),
so serializers can emit get_*_display().
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField

# ---------------------------------------------------------------------------
# Enumerations (TextChoices — repo norm for fixed code lists)
# ---------------------------------------------------------------------------


class LawfulBasis(models.TextChoices):
    """DPPA 2019 lawful bases. Labels match BASIS_LABEL in consent-shared.jsx."""

    CONSENT = "CONSENT", "Consent"
    PUBLIC_TASK = "PUBLIC_TASK", "Public task"
    CONTRACT = "CONTRACT", "Contract"
    VITAL_INTEREST = "VITAL_INTEREST", "Vital interest"
    LEGAL_OBLIGATION = "LEGAL_OBLIGATION", "Legal obligation"
    STATISTICAL_EXEMPTION = "STATISTICAL_EXEMPTION", "Statistical exemption"


class ConsentState(models.TextChoices):
    """Per-record consent state. Labels match CONSENT_STATE_TONE keys."""

    GRANTED = "GRANTED", "Granted"
    REFUSED = "REFUSED", "Refused"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"
    PENDING_REVIEW = "PENDING_REVIEW", "Pending review"
    PENDING_RE_CONSENT = "PENDING_RE_CONSENT", "Pending re-consent"


class LifecycleStatus(models.TextChoices):
    """Catalogue lifecycle for purposes (dual-approved). Labels match
    LIFECYCLE_TONE keys plus the approval intermediate states."""

    DRAFT = "DRAFT", "Draft"
    PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
    ACTIVE = "ACTIVE", "Active"
    RETIRED = "RETIRED", "Retired"
    REJECTED = "REJECTED", "Rejected"


class StatementStatus(models.TextChoices):
    """Statement-version lifecycle. SUPERSEDED replaces an ACTIVE version
    when a successor activates. Labels match LIFECYCLE_TONE keys."""

    DRAFT = "DRAFT", "Draft"
    PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
    ACTIVE = "ACTIVE", "Active"
    SUPERSEDED = "SUPERSEDED", "Superseded"
    RETIRED = "RETIRED", "Retired"


class CaptureMethod(models.TextChoices):
    SIGNATURE = "SIGNATURE", "Signature"
    THUMBPRINT = "THUMBPRINT", "Thumbprint"
    VERBAL_WITNESSED = "VERBAL_WITNESSED", "Verbal (witnessed)"
    DIGITAL = "DIGITAL", "Digital"


class CapturedVia(models.TextChoices):
    WEB_INTAKE = "WEB_INTAKE", "Web intake"
    CAPI = "CAPI", "CAPI"
    CITIZEN_PORTAL = "CITIZEN_PORTAL", "Citizen portal"
    DIH_FAST_TRACK = "DIH_FAST_TRACK", "DIH fast-track"
    LEGACY_BACKFILL = "LEGACY_BACKFILL", "Legacy backfill"
    UPD_RECAPTURE = "UPD_RECAPTURE", "UPD re-capture"


class TicketState(models.TextChoices):
    """Withdrawal-ticket lifecycle. Labels match TICKET_STATE_TONE keys."""

    OPEN = "OPEN", "Open"
    IN_DPO_REVIEW = "IN_DPO_REVIEW", "In DPO review"
    CONFIRMED = "CONFIRMED", "Confirmed"
    PUBLIC_TASK_OVERRIDE = "PUBLIC_TASK_OVERRIDE", "Public-task override"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED", "Clarification requested"
    CLOSED = "CLOSED", "Closed"


class WithdrawalDecisionType(models.TextChoices):
    CONFIRM = "CONFIRM", "Confirm"
    OVERRIDE_PUBLIC_TASK = "OVERRIDE_PUBLIC_TASK", "Override (public task)"
    REQUEST_CLARIFICATION = "REQUEST_CLARIFICATION", "Request clarification"
    HOLD = "HOLD", "Hold"


class EvidenceType(models.TextChoices):
    SIGNATURE = "SIGNATURE", "Signature image"
    THUMBPRINT = "THUMBPRINT", "Thumbprint image"
    WITNESS_STATEMENT = "WITNESS_STATEMENT", "Witness statement"
    DPA_DOCUMENT = "DPA_DOCUMENT", "DPA document (fast-track)"


# ---------------------------------------------------------------------------
# Dual-approval mixin (mirrors the DqaRule author/approved_by lifecycle)
# ---------------------------------------------------------------------------


class _ApprovableBase(models.Model):
    """Author/approver lifecycle audit fields, shared by ConsentPurpose and
    ConsentStatementVersion. The author-cannot-approve rule is enforced in
    apps.consent.services, never at the ORM, so it cannot be bypassed."""

    author = models.CharField(max_length=64)
    approved_by = models.CharField(max_length=64, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_note = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Bootstrap reference table
# ---------------------------------------------------------------------------


class ConsentLanguage(models.Model):
    """The seven statement languages (English + six Ugandan). Seeded by
    migration. Statement i18n text is keyed by ``code``."""

    id = ULIDField(primary_key=True)
    code = models.CharField(max_length=8, unique=True)
    label = models.CharField(max_length=64)
    native_label = models.CharField(max_length=64, blank=True)
    is_ready = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Consent language"
        ordering = ["display_order", "code"]

    def __str__(self) -> str:
        return f"{self.code} ({self.label})"


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


class ConsentPurpose(_ApprovableBase):
    """The purpose catalogue (US-CONSENT-01). One row per purpose code; the
    seeded set is the scope-doc nine including ELIGIBILITY (CONSENT-O-01)."""

    id = ULIDField(primary_key=True)
    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=128)
    lawful_basis = models.CharField(max_length=24, choices=LawfulBasis.choices)
    withdrawable = models.BooleanField(default=True)
    default_on = models.BooleanField(default=False)
    is_primary = models.BooleanField(default=False)
    is_optional = models.BooleanField(default=True)
    blurb = models.TextField(blank=True)
    basis_note = models.TextField(blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    status = models.CharField(
        max_length=24, choices=LifecycleStatus.choices,
        default=LifecycleStatus.DRAFT,
    )

    class Meta:
        verbose_name = "Consent purpose"
        ordering = ["display_order", "code"]
        indexes = [
            models.Index(fields=["status", "code"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} [{self.status}]"


class ConsentStatementVersion(_ApprovableBase):
    """Versioned statement text per purpose (US-CONSENT-02). ``text_i18n`` is
    keyed by ConsentLanguage.code; ``placeholder_languages`` lists the codes
    whose text is a placeholder pending translation. A partial unique index
    enforces at most one ACTIVE version per purpose."""

    id = ULIDField(primary_key=True)
    purpose = models.ForeignKey(
        ConsentPurpose, on_delete=models.PROTECT,
        related_name="statement_versions",
    )
    version = models.PositiveIntegerField(default=1)
    text_i18n = models.JSONField(default=dict, blank=True)
    placeholder_languages = models.JSONField(default=list, blank=True)
    is_material = models.BooleanField(default=False)

    status = models.CharField(
        max_length=24, choices=StatementStatus.choices,
        default=StatementStatus.DRAFT,
    )
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Consent statement version"
        ordering = ["purpose", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["purpose", "version"],
                name="consent_statement_purpose_version_unique",
            ),
            # At most one ACTIVE statement version per purpose. Partial
            # index — Postgres-enforced (sqlite skips partial constraints).
            models.UniqueConstraint(
                fields=["purpose"],
                condition=models.Q(status="ACTIVE"),
                name="consent_statement_one_active_per_purpose",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.purpose.code} statement v{self.version} [{self.status}]"


# ---------------------------------------------------------------------------
# Records + append-only history
# ---------------------------------------------------------------------------


class ConsentRecord(models.Model):
    """Current consent state for one (member, purpose). Append-only history
    lives in ConsentRecordVersion; every state change emits an AuditEvent."""

    id = ULIDField(primary_key=True)
    member = models.ForeignKey(
        "data_management.Member", on_delete=models.PROTECT,
        related_name="consent_records",
    )
    purpose = models.ForeignKey(
        ConsentPurpose, on_delete=models.PROTECT, related_name="records",
    )
    state = models.CharField(max_length=24, choices=ConsentState.choices)
    statement_version = models.ForeignKey(
        ConsentStatementVersion, on_delete=models.PROTECT,
        null=True, blank=True, related_name="records",
    )
    captured_via = models.CharField(max_length=24, choices=CapturedVia.choices)
    capture_method = models.CharField(
        max_length=24, choices=CaptureMethod.choices, blank=True,
    )
    captured_by = models.CharField(max_length=64, blank=True)
    captured_at = models.DateTimeField(auto_now_add=True)

    # Minor-proxy capture (AC-CONSENT-MINOR-PROXY-PRESENT).
    proxy_member_id = models.CharField(max_length=26, blank=True)
    proxy_relationship = models.CharField(max_length=32, blank=True)

    # Denormalised partition key inherited from member.household (ADR-0005).
    sub_region_code = models.CharField(max_length=32, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Consent record"
        constraints = [
            models.UniqueConstraint(
                fields=["member", "purpose"],
                name="consent_record_unique_member_purpose",
            ),
        ]
        indexes = [
            models.Index(fields=["member", "purpose"]),
            models.Index(fields=["purpose", "state"]),
            models.Index(fields=["sub_region_code", "id"]),
        ]

    def __str__(self) -> str:
        return f"{self.member_id}/{self.purpose_id}={self.state}"

    def save(self, *args, **kwargs):
        # Inherit the partition key from the member's household (ADR-0005),
        # mirroring Member.save().
        if self.member_id and not self.sub_region_code:
            self.sub_region_code = self.member.sub_region_code
        super().save(*args, **kwargs)


class ConsentRecordVersion(models.Model):
    """Append-only history of ConsentRecord state changes (paired-version
    table per SAD §5.3). NOT hash-chained — see module docstring. Each row
    carries the id of the AuditEvent emitted for the change so the integrity
    job can verify referential completeness (US-CONSENT-10)."""

    id = ULIDField(primary_key=True)
    consent_record = models.ForeignKey(
        ConsentRecord, on_delete=models.PROTECT, related_name="versions",
    )
    # Denormalised so a version row is self-describing even if the parent
    # record is later reconciled (e.g. DDUP merge).
    member_id = models.CharField(max_length=26, db_index=True)
    purpose_code = models.CharField(max_length=32, db_index=True)
    state = models.CharField(max_length=24, choices=ConsentState.choices)
    state_from = models.CharField(max_length=24, blank=True)
    statement_version_id = models.CharField(max_length=26, blank=True)
    captured_via = models.CharField(max_length=24, blank=True)
    capture_method = models.CharField(max_length=24, blank=True)
    captured_by = models.CharField(max_length=64, blank=True)
    reason = models.CharField(max_length=128, blank=True)

    audit_event_id = models.CharField(max_length=26, blank=True, db_index=True)

    effective_from = models.DateTimeField(auto_now_add=True)
    effective_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Consent record version"
        ordering = ["consent_record", "-effective_from"]
        indexes = [
            models.Index(fields=["consent_record", "effective_from"]),
            models.Index(fields=["member_id", "purpose_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.member_id}/{self.purpose_code}={self.state} @ {self.effective_from}"


# ---------------------------------------------------------------------------
# Withdrawal workflow
# ---------------------------------------------------------------------------


class ConsentWithdrawalTicket(models.Model):
    """Withdrawal request (US-CONSENT-06). Owns the 30-day SLA clock
    (CONSENT-O-03). Idempotent on (member, purpose, requested_at_day)."""

    id = ULIDField(primary_key=True)
    member = models.ForeignKey(
        "data_management.Member", on_delete=models.PROTECT,
        related_name="consent_withdrawal_tickets",
    )
    purpose = models.ForeignKey(
        ConsentPurpose, on_delete=models.PROTECT,
        related_name="withdrawal_tickets",
    )
    consent_record = models.ForeignKey(
        ConsentRecord, on_delete=models.PROTECT,
        related_name="withdrawal_tickets", null=True, blank=True,
    )
    state = models.CharField(
        max_length=24, choices=TicketState.choices, default=TicketState.OPEN,
    )
    reason_code = models.CharField(max_length=64, blank=True)
    reason_note = models.TextField(blank=True)

    requested_by = models.CharField(max_length=64)
    requested_at = models.DateTimeField(auto_now_add=True)
    # Day bucket for idempotency (one ticket per member+purpose+day).
    requested_at_day = models.DateField(db_index=True)
    sla_deadline = models.DateTimeField()
    sla_breached_notified_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    sub_region_code = models.CharField(max_length=32, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Consent withdrawal ticket"
        ordering = ["-requested_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["member", "purpose", "requested_at_day"],
                name="consent_withdrawal_idempotent_per_day",
            ),
        ]
        indexes = [
            models.Index(fields=["state", "sla_deadline"]),
            models.Index(fields=["sub_region_code", "state"]),
        ]

    def __str__(self) -> str:
        return f"WithdrawalTicket {self.id} {self.member_id}/{self.purpose_id} [{self.state}]"


class WithdrawalDecision(models.Model):
    """A DPO decision on a withdrawal ticket (US-CONSENT-07). Append-only;
    a ticket can carry a sequence (e.g. clarification then confirm)."""

    id = ULIDField(primary_key=True)
    ticket = models.ForeignKey(
        ConsentWithdrawalTicket, on_delete=models.PROTECT,
        related_name="decisions",
    )
    decision = models.CharField(
        max_length=24, choices=WithdrawalDecisionType.choices,
    )
    rationale = models.TextField()
    decided_by = models.CharField(max_length=64)
    decided_at = models.DateTimeField(auto_now_add=True)
    # Second approver for bulk-confirm > 1000 tickets (US-CONSENT-07).
    second_approver = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name = "Withdrawal decision"
        ordering = ["ticket", "-decided_at"]

    def __str__(self) -> str:
        return f"{self.ticket_id}:{self.decision} by {self.decided_by}"


# ---------------------------------------------------------------------------
# Evidence (MinIO-backed)
# ---------------------------------------------------------------------------


class ConsentEvidence(models.Model):
    """Signature / thumbprint / witness-statement / DPA-document evidence for
    a consent record. The asset itself lives in MinIO; this row holds the
    object key + metadata (US-CONSENT-03 / -11)."""

    id = ULIDField(primary_key=True)
    consent_record = models.ForeignKey(
        ConsentRecord, on_delete=models.PROTECT, related_name="evidence",
    )
    evidence_type = models.CharField(
        max_length=24, choices=EvidenceType.choices,
    )
    object_key = models.CharField(max_length=512, blank=True)
    thumbprint_sha256 = models.CharField(max_length=64, blank=True)
    witness_name = models.CharField(max_length=128, blank=True)
    witness_role = models.CharField(max_length=64, blank=True)
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Consent evidence"
        ordering = ["consent_record", "-captured_at"]

    def __str__(self) -> str:
        return f"{self.evidence_type} for {self.consent_record_id}"
