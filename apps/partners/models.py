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

    US-S25-002 extends this model with the cohort / disbursement /
    lifecycle / webhook columns captured by the registration wizard
    (apps.referral.Programme keeps the operational referral side
    until that legacy app is consolidated in a Sprint 26 follow-up).
    """

    id = ULIDField(primary_key=True)
    partner = models.ForeignKey(
        Partner, on_delete=models.PROTECT, related_name="programmes",
    )

    # Identity (US-S25-002).
    code = models.CharField(
        max_length=24, blank=True,
        help_text="Short programme mark (MGLSD-DVA). Unique per partner.",
    )
    name = models.CharField(max_length=256)
    summary = models.TextField(
        blank=True,
        help_text="One-sentence description shown in the partner "
                  "programmes tab and the registration wizard preview.",
    )

    # Coded — programme_kind ChoiceList (cash_transfer, service, ...).
    kind = models.CharField(max_length=32)
    # Coded — programme_status ChoiceList (draft, active, closed).
    status = models.CharField(max_length=32, default="draft")

    # Optional DSA the programme registers under (used by the wizard
    # to inherit the geo + entity scope cap). The DSA<->Programme M2M
    # on DataSharingAgreement.programmes remains the canonical join.
    dsa = models.ForeignKey(
        "DataSharingAgreement",
        on_delete=models.SET_NULL,
        related_name="programmes_via_fk",
        null=True, blank=True,
    )

    # Cohort & targeting (US-S25-002).
    # Coded — programme_unit_of_enrolment ChoiceList.
    unit_of_enrolment = models.CharField(max_length=32, blank=True)
    cohort_target = models.PositiveIntegerField(null=True, blank=True)
    # Coded — programme_sex_filter ChoiceList (any/1/2).
    sex_filter = models.CharField(max_length=8, blank=True)
    age_min = models.PositiveSmallIntegerField(null=True, blank=True)
    age_max = models.PositiveSmallIntegerField(null=True, blank=True)
    # Lists of ChoiceOption codes — not native ChoiceLists themselves
    # (storing the option codes in a JSON array preserves the multi-
    # select semantics without joining a Through model).
    pmt_bands = models.JSONField(
        default=list, blank=True,
        help_text='List of programme_pmt_band codes, e.g. '
                  '["poorest_20", "poorest_40"].',
    )
    composition_flags = models.JSONField(
        default=list, blank=True,
        help_text='List of programme_composition_flag codes, e.g. '
                  '["female_headed", "under_five"].',
    )

    # Disbursement (US-S25-002).
    amount_ugx = models.PositiveBigIntegerField(null=True, blank=True)
    # Coded — programme_disbursement_cycle ChoiceList.
    disbursement_cycle = models.CharField(max_length=32, blank=True)
    duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    channel = models.CharField(max_length=128, blank=True)
    start_month = models.CharField(
        max_length=24, blank=True,
        help_text="Free-text 'Aug 2026' — first cycle target. Concrete "
                  "calendar lands when the scheduler app boots.",
    )

    # Geographic scope — M2M to GeographicUnit (kept from earlier).
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

    # Lifecycle policy (US-S25-002).
    exit_codes_allowed = models.JSONField(
        default=list, blank=True,
        help_text='List of programme_exit_reason codes, e.g. '
                  '["10","20","30","40","50","60","70"].',
    )
    auto_exit_triggers = models.JSONField(
        default=list, blank=True,
        help_text='List of programme_auto_exit_trigger codes.',
    )
    suspend_on_grievance = models.BooleanField(default=False)

    # Partner MIS callback (US-S25-002 — mirrors apps.referral.Programme
    # webhook contract). Secret is stored as an HMAC hash; the cleartext
    # is shown only once at create-time.
    webhook_url = models.URLField(blank=True)
    webhook_secret_hash = models.CharField(
        max_length=64, blank=True,
        help_text="sha256(webhook_secret). The cleartext secret is "
                  "returned in the create response and never persisted.",
    )
    # ADR-0015 §"Decision 3": HMAC webhook signing needs the cleartext
    # at send time, which ADR-0014 ruled out for new programmes. The
    # encrypted column carries the cleartext for legacy referral.Programme
    # rows that get lifted in US-S26-004 + any future call site that
    # needs the cleartext. The WebhookCredential factoring (OI-S26-3)
    # supersedes this column when it lands.
    webhook_secret_encrypted = EncryptedBinaryField(null=True, blank=True)

    # Preserves the free-text DSA reference from apps.referral.Programme
    # for lifted rows. The structured FK + M2M to DataSharingAgreement
    # remain the canonical join; this column is read-only history.
    dsa_reference_legacy = models.CharField(max_length=64, blank=True)

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Programme"
        verbose_name_plural = "Programmes"
        constraints = [
            models.UniqueConstraint(
                fields=["partner", "code"],
                condition=models.Q(code__gt=""),
                name="programme_partner_code_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["partner"]),
            models.Index(fields=["status"]),
            models.Index(fields=["dsa"]),
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
        max_length=64,
        help_text=(
            "Human-readable identifier (DSA-OPM-2026-001). Stable "
            "across versions: v(N+1) shares the reference of v(N); "
            "uniqueness is enforced by the (reference, version) "
            "composite constraint."
        ),
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
