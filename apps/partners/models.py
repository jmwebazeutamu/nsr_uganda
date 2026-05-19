"""Partners module data model — US-S23 / ADR-0011.

NOTE: Every coded field on every model in this app is a plain
CharField(max_length=32). The DB-driven ChoiceList catalogue at
apps.reference_data is the single source of truth. The
data_management.E001 system check (US-S23-003) fails CI if any
coded field declares `choices=`.

Subsequent commits extend this module with:
  - PartnerContact + Programme (US-S23-005)
  - DataSharingAgreement + DsaSignature (US-S23-006)
  - PartnerUsageDaily + PartnerActivityEvent projection (US-S23-007)
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from nsr_mis.common.fields import EncryptedBinaryField, ULIDField


class Partner(models.Model):
    """A registered external organisation that exchanges data with
    NSR under a Data Sharing Agreement. Provider partners (NIRA)
    are modelled with status=provider; budget/usage are nullable
    and the breach detector skips them (ADR-0011 decision 3).
    """

    id = ULIDField(primary_key=True)

    # Identity
    code = models.CharField(
        max_length=16, unique=True,
        help_text="Short code shown as the partner mark (OPM, UBOS, ...). "
                  "3-5 uppercase letters by convention.",
    )
    name = models.CharField(max_length=256)
    registration_no = models.CharField(
        max_length=128, blank=True,
        help_text="URSB / NGO Bureau / Ministerial / IGO charter reference.",
    )
    country = models.CharField(max_length=128, blank=True)
    website = models.URLField(blank=True)
    primary_email = models.EmailField(blank=True)

    # Coded fields — resolved against ChoiceLists via
    # apps.reference_data.services. NO choices= on any of these.
    type = models.CharField(max_length=32)
    sector = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=32, default="onboarding")
    tone = models.CharField(max_length=32, blank=True)

    # Operational pointers
    lead_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partners_led",
        null=True, blank=True,
    )
    logo_short = models.CharField(
        max_length=16, blank=True,
        help_text="Optional override for the visible mark when `code` "
                  "isn't the right glyph (e.g. multi-word ministries).",
    )
    note = models.TextField(blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Partner"
        verbose_name_plural = "Partners"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["type"]),
            models.Index(fields=["last_activity_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.name})"


class PartnerContact(models.Model):
    """A named person on the partner side. Per ADR-0012 the
    Authorised Signatory, Data Steward, Partner DPO, and IT/Security
    contact are the four required roles; the `role` ChoiceList holds
    the canonical set. NIN is encrypted per ADR-0002.
    """

    id = ULIDField(primary_key=True)
    partner = models.ForeignKey(
        Partner, on_delete=models.PROTECT, related_name="contacts",
    )

    # Coded role — partner_contact_role ChoiceList.
    role = models.CharField(max_length=32)

    full_name = models.CharField(max_length=128)
    title = models.CharField(max_length=128, blank=True)
    email = models.EmailField()
    phone_e164 = models.CharField(
        max_length=20, blank=True,
        help_text="E.164 format including leading + (e.g. +256772000000).",
    )

    # NIN trio (ADR-0002). Optional — not every partner contact has a
    # Ugandan NIN; the verify_nin call is skipped when absent.
    nin_value = EncryptedBinaryField(null=True, blank=True)
    nin_hash = models.BinaryField(max_length=32, null=True, blank=True)
    nin_last4 = models.CharField(max_length=4, blank=True)
    nin_verified_at = models.DateTimeField(null=True, blank=True)

    # Document evidence (e.g. PS authorisation letter, ID card scan).
    # FK to apps.security.SupportingDoc or a future global blob ref;
    # captured as CharField for now so we don't couple before the
    # storage abstraction stabilises (DRS-O-02).
    supporting_doc_ref = models.CharField(max_length=128, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Partner contact"
        verbose_name_plural = "Partner contacts"
        constraints = [
            models.UniqueConstraint(
                fields=["partner", "role"],
                name="partner_contact_unique_role_per_partner",
            ),
        ]
        indexes = [
            models.Index(fields=["partner", "role"]),
            models.Index(fields=["nin_hash"]),
        ]

    def __str__(self) -> str:
        return f"{self.partner.code} · {self.role} · {self.full_name}"


class Programme(models.Model):
    """A programme the partner runs that consumes NSR data. Per
    ADR-0011, programmes are M2M-scoped under a DSA — the same
    programme can sit under multiple DSAs across renewal cycles.
    """

    id = ULIDField(primary_key=True)
    partner = models.ForeignKey(
        Partner, on_delete=models.PROTECT, related_name="programmes",
    )

    name = models.CharField(max_length=256)
    # Coded — programme_kind ChoiceList (cash_transfer, service, ...).
    kind = models.CharField(max_length=32)
    # Coded — programme_status ChoiceList (draft, active, closed).
    status = models.CharField(max_length=32, default="draft")

    scope_text = models.TextField(
        blank=True,
        help_text="Free-text geographic / cohort scope. Structured "
                  "GeographicUnit M2M lives on the DSA per ADR-0011.",
    )
    geographic_units = models.ManyToManyField(
        "reference_data.GeographicUnit",
        related_name="programmes",
        blank=True,
    )
    beneficiary_estimate = models.PositiveIntegerField(null=True, blank=True)

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Programme"
        verbose_name_plural = "Programmes"
        indexes = [
            models.Index(fields=["partner"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.partner.code} · {self.name}"


class DataSharingAgreement(models.Model):
    """The legal envelope between MGLSD's NSR Unit and a Partner.
    Carries the entity / field / geographic scope, the volume cap,
    and the breach SLA. Per ADR-0011 decision 2, monthly_row_budget
    counts rows DELIVERED. Per decision 3, provider-status partners
    have NULL budget (the breach detector skips them).
    """

    id = ULIDField(primary_key=True)
    reference = models.CharField(
        max_length=64, unique=True,
        help_text="Human-readable identifier (DSA-OPM-2026-001).",
    )
    partner = models.ForeignKey(
        Partner, on_delete=models.PROTECT, related_name="dsas",
    )
    programmes = models.ManyToManyField(
        Programme, related_name="dsas", blank=True,
    )
    version = models.PositiveIntegerField(default=1)

    # Coded — dsa_status ChoiceList (draft, pending_signature,
    # active, expiring, expired, suspended, renewed).
    status = models.CharField(max_length=32, default="draft")

    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    # Volume cap — rows delivered per calendar month. NULL for
    # provider-type partners (NIRA) per ADR-0011 decision 3.
    monthly_row_budget = models.PositiveIntegerField(null=True, blank=True)

    # Scope payloads. ChoiceList-backed fields render as raw codes;
    # JSON shapes carry richer structure (entity flags, field-group
    # toggles) without polluting the ChoiceOption catalogue.
    entities_scope = models.JSONField(
        default=dict, blank=True,
        help_text='e.g. {"household": true, "member": false, '
                  '"referral": true, "grievance": false}',
    )
    field_scope = models.JSONField(
        default=dict, blank=True,
        help_text='e.g. {"Identifiers": true, "PMT": true, ...}',
    )
    geographic_scope = models.ManyToManyField(
        "reference_data.GeographicUnit",
        related_name="dsas",
        blank=True,
        help_text="DSA scope at any geographic level (ADR-0011 decision 4).",
    )

    # Coded — sensitive_data_handling ChoiceList (none, specific, full).
    sensitive_data_handling = models.CharField(
        max_length=32, default="none",
    )
    retention_days = models.PositiveIntegerField(default=180)
    classification = models.CharField(max_length=128, blank=True)

    dpia_document_ref = models.CharField(
        max_length=128, blank=True,
        help_text="DPIA PDF reference (storage abstraction lands "
                  "with DRS-O-02).",
    )
    breach_sla_hours = models.PositiveIntegerField(
        default=72,
        help_text="Hours from breach detection to partner-side "
                  "notification of the NSR DPO.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Data Sharing Agreement"
        verbose_name_plural = "Data Sharing Agreements"
        constraints = [
            models.UniqueConstraint(
                fields=["reference", "version"],
                name="dsa_reference_version_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(effective_to__isnull=True)
                    | models.Q(effective_from__isnull=True)
                    | models.Q(effective_to__gt=models.F("effective_from"))
                ),
                name="dsa_effective_to_after_from",
            ),
        ]
        indexes = [
            models.Index(fields=["partner", "status"]),
            models.Index(fields=["effective_to"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference} v{self.version}"


class DsaSignature(models.Model):
    """One of the three signatures required to activate a DSA. The
    sign-off chain runs sequentially in `sequence_order` (1=Partner
    Authorised Signatory via DocuSign, 2=NSR Unit Lead, 3=DPO).
    Per ADR-0012 the same signer_email cannot appear twice on a
    single DSA — enforced by the service layer at submit-for-signoff.
    """

    id = ULIDField(primary_key=True)
    dsa = models.ForeignKey(
        DataSharingAgreement, on_delete=models.CASCADE,
        related_name="signatures",
    )

    sequence_order = models.PositiveSmallIntegerField(
        help_text="1, 2, 3 — order in which the signature is collected.",
    )

    # Coded fields — dsa_signer_role / signature_method / signature_status.
    signer_role = models.CharField(max_length=32)
    signer_name = models.CharField(max_length=128, blank=True)
    signer_email = models.EmailField()
    method = models.CharField(max_length=32, default="docusign")
    status = models.CharField(max_length=32, default="pending")

    signed_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True)

    # DocuSign envelope ID once dispatched; allows webhook lookups.
    docusign_envelope_id = models.CharField(max_length=64, blank=True)
    evidence_doc_ref = models.CharField(max_length=128, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "DSA signature"
        verbose_name_plural = "DSA signatures"
        constraints = [
            models.UniqueConstraint(
                fields=["dsa", "sequence_order"],
                name="dsa_signature_unique_order_per_dsa",
            ),
            models.UniqueConstraint(
                fields=["dsa", "signer_email"],
                name="dsa_signature_unique_email_per_dsa",
            ),
        ]
        indexes = [
            models.Index(fields=["dsa", "status"]),
            models.Index(fields=["docusign_envelope_id"]),
        ]
        ordering = ("dsa", "sequence_order")

    def __str__(self) -> str:
        return f"{self.dsa.reference} · step {self.sequence_order} · {self.signer_role}"


class PartnerUsageDaily(models.Model):
    """Per-day rollup of rows delivered + requests count, per partner.
    Populated by a Celery beat task (lands in US-S23-017). The
    dashboard's UsageBar reads a 30-day window of these rows for the
    `used / budget` ratio shown in the partners table. Per ADR-0011
    decision 3, provider partners (NIRA) have NO PartnerUsageDaily
    rows — the rollup skips them.
    """

    id = ULIDField(primary_key=True)
    partner = models.ForeignKey(
        Partner, on_delete=models.PROTECT, related_name="usage_daily",
    )
    day = models.DateField()

    rows_delivered = models.PositiveIntegerField(default=0)
    requests_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Partner usage (daily)"
        verbose_name_plural = "Partner usage (daily)"
        constraints = [
            models.UniqueConstraint(
                fields=["partner", "day"],
                name="partner_usage_daily_unique_per_day",
            ),
        ]
        indexes = [
            models.Index(fields=["partner", "day"]),
            models.Index(fields=["day"]),
        ]
        ordering = ("-day", "partner")

    def __str__(self) -> str:
        return f"{self.partner.code} · {self.day} · {self.rows_delivered} rows"
