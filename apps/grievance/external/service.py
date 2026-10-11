"""The mapping half: a snapshot becomes a grievance, or is held.

Nothing here opens a socket. It is given the dictionary STAAC
returned and decides what this registry makes of it, so the whole
translation — the part that can misfile a real complaint — is
testable without a partner.

Held, not dropped
-----------------
`intake.resolve_category` refuses an unmapped category rather than
defaulting it, which is right: a grievance nobody can classify cannot
be routed or worked. But refusing inside a server-to-server pull means
something different from refusing at a console form. There is no
operator to tell, STAAC will not send it again, and the collection
moves past it. Refusing alone would lose the complaint.

So the snapshot is always stored, and the outcome says what happened
to it. `HELD` means: received, kept verbatim, not filed, and here is
the sentence saying why. When the binding is approved, `file_held()`
files it from what was received — no second call to STAAC, and the
complainant's clock still runs from when they reported.

That is also why geography refuses. A grievance with blank geography
is not neutral: `apps.security.abac` filters on those columns, so a
case with none belongs to no district officer's scope and shows for
every officer nationally. Holding it is the safe failure.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.security.audit import emit as emit_audit

from ..intake import STAAC_SOURCE_SYSTEM, UnmappedCategory, resolve_category
from ..intake import resolve_gender
from ..models import HandoverOutcome, StaacHandover
from ..services import GrievanceError, open_grievance

#: Spec §4.2: the complainant object of an anonymous grievance is
#: exactly `{"identity_recorded": false}`. Nothing may be inferred.
_ANONYMOUS = "identity_recorded"


@dataclass(frozen=True)
class FilingResult:
    handover: StaacHandover
    created: bool
    #: Anything the caller should report but which did not stop the
    #: filing: an unmapped gender, a display name that disagrees with
    #: ours. Never a reason to lose a case.
    warnings: tuple[str, ...] = ()


def _text(source: dict, *keys: str) -> str:
    """A nested string, or "". Absent and null are the same thing
    here: spec §4.2.1 says a field that appears as null is "not
    recorded", and so is one the manifest withheld entirely."""
    node: object = source
    for key in keys:
        if not isinstance(node, dict):
            return ""
        node = node.get(key)
    return "" if node is None else str(node).strip()


def _when(value: str):
    """A timestamp from either spelling STAAC uses.

    The list endpoint renders `Z`, the frozen snapshot renders
    `+00:00`. Both are RFC 3339; `parse_datetime` reads both, which is
    why neither is pattern-matched.
    """
    parsed = parse_datetime(value) if value else None
    if parsed is None:
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


def _reporter_name(complainant: dict) -> str:
    if not complainant.get(_ANONYMOUS):
        return ""
    given = _text(complainant, "given_name")
    family = _text(complainant, "family_name")
    return " ".join(part for part in (given, family) if part)


def _age(complainant: dict):
    raw = complainant.get("age")
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _store(
    snapshot_body: dict, *, handover_id: str, exchange_version: int,
    etag: str, correlation_id: str,
) -> tuple[StaacHandover, bool]:
    """Land the snapshot, or return the one already landed.

    `(handover_id, exchange_version)` is the partner's own idempotency
    key, so a re-read of a page this registry already stored finds its
    row rather than making a second one.
    """
    shared = snapshot_body.get("shared_data") or {}
    row, created = StaacHandover.objects.get_or_create(
        handover_id=handover_id,
        exchange_version=exchange_version,
        defaults={
            "tracking_number": _text(snapshot_body, "source", "tracking_number"),
            "snapshot": snapshot_body,
            "fields_manifest": list(shared.get("fields") or []),
            "agreement_reference": str(shared.get("agreement_reference") or ""),
            "agreement_version": str(shared.get("agreement_version") or ""),
            "etag": etag,
            "correlation_id": correlation_id,
            "retrieved_at": timezone.now(),
            "outcome": HandoverOutcome.HELD,
        },
    )
    return row, created


@transaction.atomic
def file_snapshot(
    snapshot_body: dict, *, handover_id: str, exchange_version: int,
    etag: str = "", correlation_id: str = "", actor: str = "staac-pull",
) -> FilingResult:
    """Store a retrieved snapshot and file it if it can be filed."""
    row, created = _store(
        snapshot_body, handover_id=handover_id,
        exchange_version=exchange_version, etag=etag,
        correlation_id=correlation_id,
    )
    if not created:
        # Already landed. Never re-file: a second Grievance for one
        # delivery is the duplicate the contract exists to prevent.
        return FilingResult(handover=row, created=False)

    # The read of personal data, recorded before anything is made of
    # it. The manifest is what STAAC was permitted to disclose for
    # THIS handover and is the audit record of that permission; the
    # values it covers are deliberately not in the event.
    emit_audit(
        "read", "staac.handover", row.id, actor=actor, actor_kind="system",
        reason=f"retrieved handover {handover_id} v{exchange_version}",
        field_changes={
            "handover_id": str(handover_id),
            "exchange_version": exchange_version,
            "tracking_number": row.tracking_number,
            "etag": etag,
            "correlation_id": correlation_id,
            "fields_manifest": row.fields_manifest,
            "agreement_reference": row.agreement_reference,
        },
    )

    warnings = _apply(row, actor=actor)
    return FilingResult(handover=row, created=True, warnings=warnings)


def _apply(row: StaacHandover, *, actor: str) -> tuple[str, ...]:
    """Turn a landed snapshot into a Grievance, or hold it."""
    body = row.snapshot or {}
    warnings: list[str] = []

    category_name = _text(body, "grievance", "category")
    try:
        resolved = resolve_category(category_name)
    except UnmappedCategory as exc:
        _hold(row, str(exc), actor=actor)
        return tuple(warnings)

    complainant = body.get("complainant") or {}
    if not isinstance(complainant, dict):
        complainant = {}
    gender = resolve_gender(_text(complainant, "gender"))
    if gender.unmapped:
        # Not a reason to lose the case — see `intake`'s docstring on
        # why this differs from the category. Reported so the gap is
        # somebody's to close rather than nobody's to notice.
        warnings.append(
            f"complainant gender {gender.received!r} has no approved "
            "binding to a sex code; the case is filed without it",
        )

    parish_key = _text(body, "location", "parish_key")
    try:
        grievance = open_grievance(
            category=resolved.nsr_category,
            description=_text(body, "grievance", "narrative"),
            geographic_code=parish_key,
            reporter_name=_reporter_name(complainant),
            reporter_phone=_text(complainant, "phone"),
            reporter_gender=gender.nsr_code,
            reporter_age_years=_age(complainant),
            source_system=STAAC_SOURCE_SYSTEM,
            external_reference=_text(body, "source", "tracking_number"),
            reported_at=_when(_text(body, "source", "received_at")),
            actor=actor,
        )
    except GrievanceError as exc:
        _hold(row, str(exc), actor=actor)
        return tuple(warnings)

    row.grievance = grievance
    row.outcome = HandoverOutcome.FILED
    row.outcome_detail = ""
    row.save(update_fields=["grievance", "outcome", "outcome_detail", "updated_at"])

    # STAAC's own word for the place, compared rather than trusted.
    # `ssot_register.md` reserves code-to-name resolution for this
    # registry's own code frame, and STAAC's display_name is
    # `str(Parish)` — "BUJUMBA [101.1.01.01]", not a bare name — so
    # treating it as one would be wrong even when it agrees.
    told = _text(body, "location", "display_name")
    if told and parish_key and parish_key not in told:
        warnings.append(
            f"STAAC called {parish_key} {told!r}; this registry resolves it "
            "from its own code frame",
        )

    emit_audit(
        "create", "staac.handover", row.id, actor=actor, actor_kind="system",
        reason=f"filed as grievance {grievance.reference or grievance.id}",
        field_changes={
            "handover_id": str(row.handover_id),
            "exchange_version": row.exchange_version,
            "grievance_id": grievance.id,
            "nsr_category": resolved.nsr_category,
            "staac_category": category_name,
            "category_by_label": resolved.label_lookup_used,
        },
    )
    return tuple(warnings)


def _hold(row: StaacHandover, reason: str, *, actor: str) -> None:
    """Keep the snapshot, file nothing, and say why in one sentence."""
    row.outcome = HandoverOutcome.HELD
    row.outcome_detail = reason
    row.save(update_fields=["outcome", "outcome_detail", "updated_at"])
    emit_audit(
        "update", "staac.handover", row.id, actor=actor, actor_kind="system",
        reason="held — not filed",
        field_changes={
            "handover_id": str(row.handover_id),
            "exchange_version": row.exchange_version,
            "outcome": HandoverOutcome.HELD,
            "outcome_detail": reason,
        },
    )


def file_held(*, actor: str = "staac-pull", limit: int = 0) -> list[FilingResult]:
    """File the snapshots that were held, now that configuration allows.

    This is what makes holding honest rather than a quiet bin. When a
    category binding is approved, the complaints that arrived before
    it can be filed from what was already received — no second call to
    STAAC, no re-reading of a complainant's identity, and the SLA
    still runs from when they reported.
    """
    held = StaacHandover.objects.filter(
        outcome=HandoverOutcome.HELD,
    ).order_by("retrieved_at")
    if limit:
        held = held[:limit]
    out: list[FilingResult] = []
    for row in list(held):
        with transaction.atomic():
            warnings = _apply(row, actor=actor)
        row.refresh_from_db()
        out.append(
            FilingResult(
                handover=row,
                created=row.outcome == HandoverOutcome.FILED,
                warnings=warnings,
            ),
        )
    return out
