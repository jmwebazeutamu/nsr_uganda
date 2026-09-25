"""REF models — outbound programme referral and inbound enrolment.

SAD §5.1:
- Referral: programme FK (-> apps.partners.Programme per ADR-0015),
  eligibility rule version, status (sent, accepted, enrolled,
  rejected, exited via the referral_status ChoiceList), timestamps,
  programme-side ID.
- ProgrammeEnrolment: programme FK (-> apps.partners.Programme),
  household FK, status (active, suspended, pending, exited via the
  programme_enrolment_status ChoiceList), effective date, exit
  reason, payment metadata.

Per ADR-0015 (US-S26-005) the legacy apps.referral.Programme model
was dropped; both FKs now resolve to the canonical
apps.partners.Programme. Webhook signing reads
`programme.webhook_secret_encrypted` (ADR-0015 §"Decision 3").
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class Referral(models.Model):
    """One referral of a Household to a Programme.

    Per ADR-0015 (US-S26-003) `status` is a plain CharField resolved
    against the `referral_status` ChoiceList (sent / accepted /
    enrolled / rejected / exited). The TextChoices class that used
    to declare these values was removed.
    """

    id = ULIDField(primary_key=True)

    #: The case number people use — "REF-2026-0001".
    #:
    #: The referral number a programme officer quotes back when they ask what happened to a household.
    #: The ULID above stays the key, stays in the URLs and stays in the
    #: audit chain; this is the string a person can carry.
    #:
    #: Blank only for a row mid-creation; save() fills it in. See
    #: apps/reference_data/references.py and ADR-0039.
    reference = models.CharField(max_length=16, unique=True, blank=True)
    programme = models.ForeignKey(
        "partners.Programme", on_delete=models.PROTECT,
        related_name="referrals",
    )
    household = models.ForeignKey(
        "data_management.Household", on_delete=models.PROTECT, related_name="referrals",
    )

    eligibility_rule_version = models.PositiveIntegerField(default=1)
    # Coded — referral_status ChoiceList (US-S26-002).
    status = models.CharField(max_length=32, default="sent")

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


    def save(self, *args, **kwargs):
        if not self.reference:
            from apps.reference_data.references import assign, REFERRAL
            # Inside whatever transaction is writing this row, so the
            # select_for_update in assign() serialises and a rollback
            # gives the number back.
            # sent_at, not created_at: a referral has no created_at,
            # and when it was SENT is when it happened.
            self.reference = assign(self, REFERRAL, date_field="sent_at")
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = [*update_fields, "reference"]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Referral {self.id} {self.household_id}->{self.programme_id} [{self.status}]"


class ProgrammeEnrolment(models.Model):
    """Programme-side enrolment events pushed back to the NSR.

    Per ADR-0015 (US-S26-003) `status` is a plain CharField resolved
    against the `programme_enrolment_status` ChoiceList (active /
    suspended / pending / exited). The TextChoices class that used
    to declare these values was removed; the data migration renames
    existing 'enrolled' rows to 'active' to align with the
    ChoiceList vocabulary (see ADR-0015 §"Decision 4").
    """

    id = ULIDField(primary_key=True)
    programme = models.ForeignKey(
        "partners.Programme", on_delete=models.PROTECT,
        related_name="enrolments",
    )
    household = models.ForeignKey(
        "data_management.Household", on_delete=models.PROTECT, related_name="enrolments",
    )
    referral = models.ForeignKey(
        Referral, on_delete=models.PROTECT, related_name="enrolments", null=True, blank=True,
    )

    # Coded — programme_enrolment_status ChoiceList (US-S25-006).
    status = models.CharField(max_length=32, default="active")
    effective_date = models.DateField()
    exit_reason = models.CharField(max_length=128, blank=True)
    payment_metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Programme enrolment"
        constraints = [
            models.UniqueConstraint(
                fields=["programme", "household"],
                name="programme_enrolment_unique_household",
            ),
        ]
        indexes = [
            models.Index(fields=["programme", "household"]),
            models.Index(fields=["status", "effective_date"]),
        ]

    def __str__(self) -> str:
        return f"Enrolment {self.programme_id}/{self.household_id} [{self.status}]"
