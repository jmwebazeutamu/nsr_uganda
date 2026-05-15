"""API-DRS — Data Request Service models.

SAD §4.10: partner MDAs and programmes request bulk extracts of NSR
data under a signed Data Sharing Agreement (DSA). Every request is
scoped by the DSA's allowed_scopes (fields, geography, programme,
max_rows) at submit time; an APPROVED request produces a signed
manifest at delivery time so the partner can verify integrity.

Lifecycle: DRAFT -> SUBMITTED -> APPROVED -> DELIVERED -> EXPIRED
                              \\-> REJECTED

Audit on every read (AuditReadMixin) plus one AuditEvent per state
transition (apps/data_requests/services.py).
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class PartnerStatus(models.TextChoices):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class Partner(models.Model):
    """External organisation that can receive NSR data — MDA, programme,
    NGO. One Partner can hold multiple DSAs over time."""

    id = ULIDField(primary_key=True)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    contact_email = models.EmailField(blank=True)
    status = models.CharField(
        max_length=16, choices=PartnerStatus.choices,
        default=PartnerStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Partner"

    def __str__(self) -> str:
        return f"Partner {self.code} ({self.name})"


class DsaStatus(models.TextChoices):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"


class DataSharingAgreement(models.Model):
    """Signed contract describing what a Partner is allowed to receive.

    `allowed_scopes` is a JSON document of the form:
        {
          "fields": ["household.id", "household.sub_region_code", ...],
          "sub_region_codes": ["SR-X", "SR-Y"],
          "programme_codes": ["PDM"],
          "max_rows_per_request": 50000
        }

    A DataRequest validates its request_payload against this on submit;
    the requester sees a clean rejection if scope is exceeded rather
    than getting partial data silently truncated.
    """

    id = ULIDField(primary_key=True)
    partner = models.ForeignKey(
        Partner, on_delete=models.PROTECT, related_name="agreements",
    )
    reference = models.CharField(max_length=64, unique=True)
    purpose = models.TextField(blank=True)

    allowed_scopes = models.JSONField(default=dict)

    valid_from = models.DateField()
    valid_to = models.DateField()

    status = models.CharField(
        max_length=16, choices=DsaStatus.choices, default=DsaStatus.DRAFT,
    )
    signed_by = models.CharField(max_length=64, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Data sharing agreement"
        indexes = [
            models.Index(fields=["partner", "status"]),
            models.Index(fields=["status", "valid_to"]),
        ]

    def __str__(self) -> str:
        return f"DSA {self.reference} [{self.status}]"


class RequestStatus(models.TextChoices):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    DELIVERED = "delivered"
    EXPIRED = "expired"


class DataRequest(models.Model):
    """One bulk-extract request under a DSA.

    `request_payload` is the partner's filter — fields requested,
    sub_region_codes, programme_codes, row cap. It is validated against
    the parent DSA's allowed_scopes at submit time.

    `manifest_sha256` is the SHA-256 of the delivered payload (set at
    delivery time, immutable thereafter). Partners verify integrity by
    re-hashing the bundle they receive and comparing.

    `expires_at` is the deadline beyond which the partner must
    re-request. Default policy (SAD §4.10): 30 days after delivery.
    """

    id = ULIDField(primary_key=True)
    dsa = models.ForeignKey(
        DataSharingAgreement, on_delete=models.PROTECT, related_name="requests",
    )
    requester = models.CharField(max_length=64)
    requester_note = models.TextField(blank=True)
    request_payload = models.JSONField(default=dict)

    status = models.CharField(
        max_length=16, choices=RequestStatus.choices, default=RequestStatus.DRAFT,
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    approver = models.CharField(max_length=64, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    manifest_sha256 = models.CharField(max_length=64, blank=True)
    row_count_delivered = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Data request"
        indexes = [
            models.Index(fields=["dsa", "status"]),
            models.Index(fields=["status", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"DataRequest {self.id} dsa={self.dsa_id} [{self.status}]"
