"""Which purpose is this request serving? (G2 / US-014)

Purpose limitation is the attribute that separates ABAC from scope-bounded
RBAC: it answers *why* a record is being read, which is the question DPPA 2019
turns on and the one the audit trail could not previously answer.

The vocabulary is not invented here. It is the `ConsentPurpose` catalogue —
nine codes already seeded, already carrying a `lawful_basis`, and already taken
through the DPO (DEP-22, resolved 2026-05-30). Inventing a second list of
purposes beside the consent one is exactly the kind of parallel vocabulary that
put three role catalogues out of step with each other.

A surface declares what it is for, in the same shape as `data_permission`:

    class ReferralViewSet(...):
        access_purpose = "REFERRAL"

    class SomeViewSet(...):
        access_purpose_map = {"export": "RESEARCH"}

Undeclared is permitted and means "not attributed". It is reported rather than
enforced: making a missing purpose a hard failure would break every surface at
once, and a wrong purpose recorded to satisfy a check is worse than an honest
blank. `manage.py audit_access_purposes` reports the coverage.
"""

from __future__ import annotations

_UNSET = object()


def resolve_purpose(request, view) -> str:
    """The declared purpose for this request, or "" when none is declared."""
    action = getattr(view, "action", None)
    per_action = getattr(view, "access_purpose_map", None) or {}
    if action and action in per_action:
        return per_action[action] or ""

    declared = getattr(view, "access_purpose", _UNSET)
    if declared is not _UNSET:
        return declared or ""
    return ""


def known_purpose_codes() -> set[str]:
    """ACTIVE purpose codes from the consent catalogue.

    Fails open (empty set) when the table is not there yet — `manage.py check`
    runs before migrate on a first deploy.
    """
    try:
        from apps.consent.models import ConsentPurpose
        return set(
            ConsentPurpose.objects.filter(status="ACTIVE")
            .values_list("code", flat=True),
        )
    except Exception:
        return set()
