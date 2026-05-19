"""Activity projection over apps.security.AuditEvent for a partner.

Per ADR-0011, `PartnerActivityEvent` is NOT a database table — it's
a read-side projection. The dashboard's ActivityFeed renders this
shape:

    {
      "partner": "<code>",
      "kind": "<partner_activity_kind code>",
      "severity_tone": "<ui_tone code>",
      "summary": "...",
      "detail": "...",
      "occurred_at": "...",
      "related_object_type": "...",
      "related_object_id": "...",
    }

`kind` is the canonical ChoiceList code from `partner_activity_kind`
(dsa_breach, dsa_renewal_initiated, partner_onboarding, ...). The
`_AUDIT_ACTION_TO_KIND` table maps AuditEvent.action → kind +
default tone. Unknown actions are surfaced as kind="partner_status_change"
with tone="neutral" rather than dropped, so an auditor never loses
events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q

from apps.security.models import AuditEvent

# (kind, default_tone) keyed by AuditEvent.action. The action
# vocabulary is defined in ADR-0012 §"Audit chain"; this table is
# the only place app code translates action strings to UI tones.
_AUDIT_ACTION_TO_KIND: dict[str, tuple[str, str]] = {
    # DSA lifecycle
    "submit":           ("partner_onboarding", "update"),
    "activate":         ("partner_onboarding", "data"),
    "suspend":          ("partner_status_change", "danger"),
    "expire":           ("dsa_renewal_initiated", "quality"),
    "renew":            ("dsa_renewal_initiated", "update"),
    "envelope_sent":    ("partner_onboarding", "update"),
    "sign":             ("signature_received", "data"),
    "decline":          ("partner_status_change", "danger"),
    # Programme / partner
    "programme_added":  ("programme_added", "update"),
    "status_change":    ("partner_status_change", "system"),
    # DRS / breach
    "data_request_delivered": ("data_request_delivered", "data"),
    "breach_detected":  ("dsa_breach", "danger"),
    "dpia_reminder":    ("dpia_reminder", "quality"),
}


@dataclass(slots=True)
class ActivityEvent:
    """In-memory projection. Has no .save() — this is a view object."""
    partner_code: str
    kind: str
    severity_tone: str
    summary: str
    detail: str
    occurred_at: datetime
    related_object_type: str = ""
    related_object_id: str = ""

    def as_dict(self) -> dict:
        return {
            "partner": self.partner_code,
            "kind": self.kind,
            "severity_tone": self.severity_tone,
            "summary": self.summary,
            "detail": self.detail,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "related_object_type": self.related_object_type,
            "related_object_id": self.related_object_id,
        }


def project(event: AuditEvent, partner_code: str = "") -> ActivityEvent:
    kind, tone = _AUDIT_ACTION_TO_KIND.get(
        event.action, ("partner_status_change", "neutral"),
    )
    return ActivityEvent(
        partner_code=partner_code,
        kind=kind,
        severity_tone=tone,
        summary=event.action,
        detail=event.reason or "",
        occurred_at=event.occurred_at,
        related_object_type=event.entity_type,
        related_object_id=event.entity_id,
    )


def for_partner(partner_id: str, limit: int = 50):
    """Return the most-recent AuditEvents that touch this partner —
    directly (entity_type=partner) or transitively (DSA, signature,
    programme that's owned by the partner).

    Joining transitively without N queries is non-trivial; this
    implementation pulls partner-direct events plus DSA-keyed events
    via a UNION-like queryset chain. Lands as a simple two-query
    fetch — refactor to a denormalised partner_id on AuditEvent if
    the volume ever warrants it.
    """
    from apps.partners.models import DataSharingAgreement, Partner

    p = Partner.objects.get(pk=partner_id)
    dsa_ids = list(
        DataSharingAgreement.objects.filter(partner_id=partner_id)
        .values_list("id", flat=True),
    )
    sig_ids = list(
        AuditEvent.objects
        .filter(entity_type="dsa_signature")
        .filter(reason__icontains=p.code)  # weak; tightens in S23-008 wiring
        .values_list("entity_id", flat=True)[:limit],
    )
    qs = (
        AuditEvent.objects.filter(
            Q(entity_type="partner",   entity_id=partner_id)
            | Q(entity_type="dsa",     entity_id__in=dsa_ids)
            | Q(entity_type="dsa_signature", entity_id__in=sig_ids)
            | Q(entity_type="programme", entity_id__in=list(
                p.programmes.values_list("id", flat=True),
            ))
        )
        .order_by("-occurred_at")[:limit]
    )
    return [project(e, partner_code=p.code) for e in qs]
