"""GRM models — grievance case with 4-tier escalation.

Sprint 2 scope: L1 (Parish Chief) and L2 (CDO) intake + manual
escalation to L3 (District) and L4 (NSR Unit) per SAD §11.1 MVP. The
GRM ↔ UPD linkage (a grievance that resolves to a data correction
opens a linked UPD ChangeRequest) is modelled via linked_change_request_id;
the workflow that auto-opens the UPD is a Sprint 2.5 follow-up.

References:
- SAD §5.1 Grievance entity, §11.1 MVP scope
- ADR-0002 (Grievance.id is ULID — citizen-facing reference code)
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class Category(models.TextChoices):
    DATA_CORRECTION = "data_correction"
    EXCLUSION_ERROR = "exclusion_error"
    INCLUSION_ERROR = "inclusion_error"
    PROGRAMME_ISSUE = "programme_issue"
    OPERATOR_CONDUCT = "operator_conduct"
    OTHER = "other"


class Tier(models.TextChoices):
    L1_PARISH_CHIEF = "l1_parish_chief"
    L2_CDO = "l2_cdo"
    L3_DISTRICT = "l3_district"
    L4_NSR_UNIT = "l4_nsr_unit"


class GrievanceStatus(models.TextChoices):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Grievance(models.Model):
    id = ULIDField(primary_key=True)

    category = models.CharField(max_length=32, choices=Category.choices)
    sub_category = models.CharField(max_length=64, blank=True)
    description = models.TextField()

    # Subject of the grievance. household_id is the citizen-facing
    # Registry ID; member_id (optional) points at a specific Member.
    household_id = models.CharField(max_length=26, blank=True, db_index=True)
    member_id = models.CharField(max_length=26, blank=True)

    # Reporter — usually the head of household or a witness. Phone is
    # E.164 per AC-PHONE-FORMAT; full identification is optional.
    reporter_name = models.CharField(max_length=128, blank=True)
    reporter_phone = models.CharField(max_length=20, blank=True)
    reporter_relationship = models.CharField(max_length=32, blank=True)

    tier = models.CharField(max_length=24, choices=Tier.choices, default=Tier.L1_PARISH_CHIEF)
    status = models.CharField(
        max_length=24, choices=GrievanceStatus.choices, default=GrievanceStatus.OPEN,
    )

    # Assigned operator — string for now until Keycloak (US-S2-002) lands.
    assigned_to = models.CharField(max_length=64, blank=True)

    opened_at = models.DateTimeField(auto_now_add=True)
    sla_deadline = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    resolution_narrative = models.TextField(blank=True)

    # GRM → UPD linkage. Populated when a grievance produces a data
    # correction. The actual auto-open workflow is a Sprint 2.5 story.
    linked_change_request_id = models.CharField(max_length=26, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Grievance"
        indexes = [
            models.Index(fields=["status", "tier"]),
            models.Index(fields=["category", "status"]),
            models.Index(fields=["sla_deadline"]),
        ]

    def __str__(self) -> str:
        return f"Grievance {self.id} [{self.tier}/{self.status}]"
