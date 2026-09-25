"""API-DRS — Data Request Service models.

SAD §4.10: partner MDAs and programmes request bulk extracts of NSR
data under a signed Data Sharing Agreement (DSA). Every request is
scoped against its parent DSA at submit time; an APPROVED request
produces a signed manifest at delivery time so the partner can
verify integrity.

ADR-0013 (US-S24): Partner and DataSharingAgreement are owned by
apps.partners. This module's DataRequest is the only model that
lives here; the DSA FK points at apps.partners.DataSharingAgreement.

Lifecycle: DRAFT -> SUBMITTED -> APPROVED -> DELIVERED -> EXPIRED
                              \\-> REJECTED

Audit on every read (AuditReadMixin) plus one AuditEvent per state
transition (apps/data_requests/services.py).
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


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

    #: The case number people use — "DRS-2026-0001".
    #:
    #: The request number a partner quotes in email and a DSA officer writes in a decision note.
    #: The ULID above stays the key, stays in the URLs and stays in the
    #: audit chain; this is the string a person can carry.
    #:
    #: Blank only for a row mid-creation; save() fills it in. See
    #: apps/reference_data/references.py and ADR-0039.
    reference = models.CharField(max_length=16, unique=True, blank=True)
    dsa = models.ForeignKey(
        "partners.DataSharingAgreement",
        on_delete=models.PROTECT, related_name="requests",
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


    def save(self, *args, **kwargs):
        if not self.reference:
            from apps.reference_data.references import assign, DATA_REQUEST
            # Inside whatever transaction is writing this row, so the
            # select_for_update in assign() serialises and a rollback
            # gives the number back.
            self.reference = assign(self, DATA_REQUEST)
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = [*update_fields, "reference"]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"DataRequest {self.id} dsa={self.dsa_id} [{self.status}]"
