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
