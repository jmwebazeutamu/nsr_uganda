"""NIRA reverse-feed connector — vital events.

NIRA pushes vital events (births, deaths) at NSR. This module is the
canonical mapper + driver that takes a NIRA push payload and routes
it through the UPD vital-event auto-commit pipeline shipped in
S3-003.

NIRA payload shape (per the MoU draft, finalised when NIRA-O-01
closes):
    {
      "event_type": "death" | "birth",
      "nin": "CMxxxxxxxxxxxXX",
      "event_date": "2026-04-12",
      "registration_ref": "NIRA-DTH-2026-00012345",
      # birth only:
      "demographics": {"surname": ..., "first_name": ..., "sex": ...,
                       "date_of_birth": ...},
    }

Death path:
    Resolves NIN → live Member (via nin_hash); generates a VITAL_EVENT
    ChangeRequest that flips Member.residency_status from its current
    value to 'deceased', auto-committed (S3-003) under NIRA's audit
    identity. Idempotent: if the member already has residency_status=
    'deceased', the call is a no-op.

Birth path:
    Today this records the registration_ref for lineage and returns
    None — births normally arrive through enumeration (CAPI walk-in)
    so the new identity gains a household context. Once NIRA-O-01
    closes and we have a confirmed household-association mechanism
    (e.g., NIN of head + relationship), this path will emit an
    ADDITION ChangeRequest.

Pure mapping (nira_vital_to_canonical) lives separately from the
side-effecting driver (process_nira_vital_event) so the mapping is
trivially unit-testable.
"""

from __future__ import annotations

from typing import Any

from .base import register_connector


def nira_vital_to_canonical(raw: dict) -> dict:
    """Normalise a NIRA vital-event payload to a canonical dict.

    Required keys: event_type, nin, event_date. Missing keys raise
    KeyError so the caller routes the row to Quarantine (the
    standard DIH connector contract — see PDM/NUSAF/WFP SCOPE).
    """
    event_type = raw["event_type"].strip().lower()
    if event_type not in {"death", "birth"}:
        raise ValueError(
            f"unknown NIRA event_type {raw['event_type']!r}; "
            "expected 'death' or 'birth'",
        )
    return {
        "event_type": event_type,
        "nin": raw["nin"].strip().upper(),
        "event_date": raw["event_date"],
        "registration_ref": raw.get("registration_ref", ""),
        "demographics": raw.get("demographics", {}),
    }


class NiraVitalEventError(Exception):
    """Raised when a NIRA vital event can't be routed (unknown NIN,
    deferred birth path, etc.)."""


def process_nira_vital_event(raw: dict, *, actor: str = "nira-reverse-feed") -> Any:
    """End-to-end driver: canonicalise -> route -> auto-commit.

    Returns the committed ChangeRequest on success, or None when the
    event was a no-op (e.g., death push for a member already marked
    deceased). Raises NiraVitalEventError when the NIN doesn't
    resolve or when the event_type isn't yet wired (births).
    """
    from apps.data_management.models import Member
    from apps.security.hashing import nin_hash as _hash
    from apps.update_workflow.models import (
        ChangeRequest,
        ChangeType,
        EntityType,
        SourceChannel,
    )
    from apps.update_workflow.services import auto_commit_change_request

    canonical = nira_vital_to_canonical(raw)

    if canonical["event_type"] == "birth":
        # Births need household context; deferred until NIRA-O-01
        # closes with a confirmed household-association mechanism.
        raise NiraVitalEventError(
            "NIRA birth events are not yet auto-promoted — births land "
            "through enumeration so the new identity gains a household. "
            f"Registration ref preserved: {canonical['registration_ref']}",
        )

    # Death path. Resolve NIN -> Member.
    member = (
        Member.objects.filter(
            nin_hash=_hash(canonical["nin"]), is_deleted=False,
        )
        .first()
    )
    if member is None:
        raise NiraVitalEventError(
            f"NIRA death event for NIN {canonical['nin'][-4:]}**** does "
            "not match any live Member; possibly already merged out "
            "or never registered.",
        )

    # Idempotent: already marked deceased -> no-op.
    if member.residency_status == "deceased":
        return None

    old_value = member.residency_status or ""
    cr = ChangeRequest.objects.create(
        entity_type=EntityType.MEMBER, entity_id=member.id,
        change_type=ChangeType.VITAL_EVENT, pmt_relevant=False,
        changes={"residency_status": {"old": old_value, "new": "deceased"}},
        source_channel=SourceChannel.NIRA, requester=actor,
        requester_note=(
            f"NIRA vital event: death, ref={canonical['registration_ref']}, "
            f"date={canonical['event_date']}"
        ),
    )
    return auto_commit_change_request(cr)


class _NiraVitalConnector:
    code = "NIRA-REVERSE"

    def canonicalize(self, raw: dict) -> dict:
        return nira_vital_to_canonical(raw)

    def process(self, raw: dict, *, actor: str = "nira-reverse-feed") -> Any:
        return process_nira_vital_event(raw, actor=actor)


register_connector(_NiraVitalConnector())
