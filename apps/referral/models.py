"""REF models — outbound programme referral and inbound enrolment.

SAD §5.1:
- Referral: programme FK, eligibility rule version, status (sent,
  accepted, enrolled, rejected, exited), timestamps, programme-side ID.
- ProgrammeEnrolment: programme FK, household FK, status (enrolled,
  suspended, exited), effective date, exit reason, payment metadata.

Sprint 2 scope: one pilot programme end-to-end. Webhook signing per
SAD §6.1; the actual HTTP delivery is via a Celery task that we leave
as a TODO (apps.referral.services.send_referral_webhook returns a stub
delivery_id today).
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class Programme(models.Model):
    """One row per partner programme MIS (e.g., PDM, NUSAF). The
    webhook_url + webhook_secret describe how we push referrals; the
    DSA reference ties this to the data-sharing agreement on file."""

    id = ULIDField(primary_key=True)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)

    webhook_url = models.URLField(blank=True)
    webhook_secret = models.CharField(max_length=64, blank=True)
    dsa_reference = models.CharField(max_length=64, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Programme"

    def __str__(self) -> str:
        return f"{self.code} ({self.name})"


class ReferralStatus(models.TextChoices):
    SENT = "sent"
    ACCEPTED = "accepted"
    ENROLLED = "enrolled"
    REJECTED = "rejected"
    EXITED = "exited"


class Referral(models.Model):
    """One referral of a Household to a Programme."""

    id = ULIDField(primary_key=True)
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="referrals")
    household = models.ForeignKey(
        "data_management.Household", on_delete=models.PROTECT, related_name="referrals",
    )

    eligibility_rule_version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=24, choices=ReferralStatus.choices,
                              default=ReferralStatus.SENT)

    sent_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    enrolled_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    exited_at = models.DateTimeField(null=True, blank=True)

    programme_side_id = models.CharField(max_length=64, blank=True)
    reason = models.TextField(blank=True)

    # Mock webhook delivery metadata.
    last_delivery_id = models.CharField(max_length=64, blank=True)
    last_delivery_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Referral"
        indexes = [
            models.Index(fields=["programme", "status"]),
            models.Index(fields=["household", "status"]),
        ]

    def __str__(self) -> str:
        return f"Referral {self.id} {self.household_id}->{self.programme_id} [{self.status}]"


class EnrolmentStatus(models.TextChoices):
    ENROLLED = "enrolled"
    SUSPENDED = "suspended"
    EXITED = "exited"


class ProgrammeEnrolment(models.Model):
    """Programme-side enrolment events pushed back to the NSR."""

    id = ULIDField(primary_key=True)
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="enrolments")
    household = models.ForeignKey(
        "data_management.Household", on_delete=models.PROTECT, related_name="enrolments",
    )
    referral = models.ForeignKey(
        Referral, on_delete=models.PROTECT, related_name="enrolments", null=True, blank=True,
    )

    status = models.CharField(max_length=24, choices=EnrolmentStatus.choices)
    effective_date = models.DateField()
    exit_reason = models.CharField(max_length=128, blank=True)
    payment_metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Programme enrolment"
        indexes = [
            models.Index(fields=["programme", "household"]),
            models.Index(fields=["status", "effective_date"]),
        ]

    def __str__(self) -> str:
        return f"Enrolment {self.programme_id}/{self.household_id} [{self.status}]"
