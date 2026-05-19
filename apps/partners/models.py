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
from nsr_mis.common.fields import ULIDField


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
