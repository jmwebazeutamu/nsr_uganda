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

from django.db import models, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.security.audit import emit as emit_audit

from ..intake import (
    STAAC_CATEGORY_LIST,
    STAAC_SOURCE_SYSTEM,
    UnmappedCategory,
    resolve_category,
)
from ..intake import resolve_gender
from apps.reference_data.code_frames import ancestor_codes

from ..models import HandoverOutcome, HeldReason, StaacHandover
from . import PULL_ACTOR
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
    snapshot_body: dict, *, run, handover_id: str, exchange_version: int,
    etag: str, correlation_id: str,
) -> tuple[StaacHandover, bool]:
    """Land the snapshot, or return the one already landed.

    `(handover_id, exchange_version)` is the partner's own idempotency
    key, so a re-read of a page this registry already stored finds its
    row rather than making a second one — and, crucially, does not
    land a second copy of the payload.

    The payload goes to `RawLanding`, the registry's one append-only
    landing table, which also moves the run's `records_received` and
    `records_landed` counters.
    """
    from apps.ingestion_hub.services import land_payload

    existing = StaacHandover.objects.filter(
        handover_id=handover_id, exchange_version=exchange_version,
    ).first()
    if existing is not None:
        return existing, False

    shared = snapshot_body.get("shared_data") or {}
    landing = land_payload(
        run, snapshot_body, source_reference=str(handover_id),
    )
    row = StaacHandover.objects.create(
        handover_id=handover_id,
        exchange_version=exchange_version,
        tracking_number=_text(snapshot_body, "source", "tracking_number"),
        raw_landing=landing,
        fields_manifest=list(shared.get("fields") or []),
        agreement_reference=str(shared.get("agreement_reference") or ""),
        agreement_version=str(shared.get("agreement_version") or ""),
        etag=etag,
        correlation_id=correlation_id,
        retrieved_at=timezone.now(),
        outcome=HandoverOutcome.HELD,
    )
    return row, True


@transaction.atomic
def file_snapshot(
    snapshot_body: dict, *, run, handover_id: str, exchange_version: int,
    etag: str = "", correlation_id: str = "", actor: str = PULL_ACTOR,
) -> FilingResult:
    """Store a retrieved snapshot and file it if it can be filed."""
    row, created = _store(
        snapshot_body, run=run, handover_id=handover_id,
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


@dataclass(frozen=True)
class Assessment:
    """What this registry would make of a snapshot, deciding nothing.

    Pure: it reads reference data and writes nothing, so a dry run can
    answer "what would this pull do" without the pull happening. The
    real filing calls the same function, which is the point — two
    implementations of "would this be held" would eventually disagree,
    and the one an operator trusts is the one that never runs.
    """

    will_file: bool
    #: The NSR category it would be filed under, when it would be.
    nsr_category: str = ""
    #: Why not, when it would not.
    held_reason: str = ""
    held_choice_list: str = ""
    held_source_code: str = ""
    detail: str = ""
    warnings: tuple[str, ...] = ()
    tracking_number: str = ""
    staac_category: str = ""
    parish_key: str = ""


def assess(body: dict, *, agreement_reference: str = "") -> Assessment:
    """Decide what would happen to this snapshot, without writing.

    The order matters and mirrors the filing exactly: the agreement
    first, because an unauthorised disclosure is not something to
    classify; then the category, because a case nobody can classify
    cannot be routed; then the place, because blank geography shows a
    case to every officer in the country.
    """
    body = body if isinstance(body, dict) else {}
    warnings: list[str] = []
    tracking = _text(body, "source", "tracking_number")
    category_name = _text(body, "grievance", "category")
    parish_key = _text(body, "location", "parish_key")
    reference = (
        agreement_reference
        or _text(body, "shared_data", "agreement_reference")
    )

    def held(reason, *, kind, choice_list="", source_code=""):
        return Assessment(
            will_file=False, held_reason=kind, held_choice_list=choice_list,
            held_source_code=str(source_code or "")[:128], detail=reason,
            warnings=tuple(warnings), tracking_number=tracking,
            staac_category=category_name, parish_key=parish_key,
        )

    unlawful = _agreement_not_in_force(reference)
    if unlawful:
        return held(
            unlawful, kind=HeldReason.UNVERIFIED_AGREEMENT,
            source_code=reference,
        )

    try:
        resolved = resolve_category(category_name)
    except UnmappedCategory as exc:
        return held(
            str(exc),
            kind=(
                HeldReason.UNBOUND_CATEGORY if exc.recognised
                else HeldReason.UNKNOWN_CATEGORY
            ),
            choice_list=STAAC_CATEGORY_LIST, source_code=exc.value,
        )

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

    sent = body.get("attachments") or []
    if sent:
        warnings.append(
            f"STAAC sent {len(sent)} attachment(s) with "
            f"{tracking or 'this handover'}; v1 of the partner contract "
            "has no transfer for them, so they are recorded in the "
            "stored snapshot and not filed against the case",
        )

    told = _text(body, "location", "display_name")
    if told and parish_key and parish_key not in told:
        warnings.append(
            f"STAAC called {parish_key} {told!r}; this registry resolves "
            "it from its own code frame",
        )

    if parish_key and not ancestor_codes(parish_key):
        return held(
            f"geographic_code {parish_key!r} names no GeographicUnit",
            kind=HeldReason.UNRESOLVED_PLACE, source_code=parish_key,
        )

    return Assessment(
        will_file=True, nsr_category=resolved.nsr_category,
        warnings=tuple(warnings), tracking_number=tracking,
        staac_category=category_name, parish_key=parish_key,
    )


def _agreement_not_in_force(reference: str) -> str:
    """"" when the registry's own register authorises this disclosure.

    The snapshot names the agreement it was released under. Storing
    that and auditing it as the record of permission means the chain
    holds the PARTNER's assertion — a handover sent under an expired,
    withdrawn or invented reference would land, be audited as lawful
    and be filed, with the registry never consulting what it is
    actually permitted to receive.

    `DataProvisionAgreement` is that register: the inbound counterpart
    of a DSA, the thing AC-DIH-DPA-REQUIRED already gates every
    connector run on. The reference STAAC sends must match one of ours
    that is in force today.
    """
    from apps.ingestion_hub.models import DataProvisionAgreement

    from apps.grievance.external import SOURCE_CODE

    reference = (reference or "").strip()
    if not reference:
        return (
            "the snapshot names no data-sharing agreement, so nothing "
            "records what this registry was permitted to receive"
        )
    today = timezone.now().date()
    covered = DataProvisionAgreement.objects.filter(
        source_system__code=SOURCE_CODE,
        reference=reference,
        valid_from__lte=today,
    ).filter(
        models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=today),
    ).exists()
    if covered:
        return ""
    return (
        f"the snapshot cites agreement {reference!r}, which is not a "
        f"data-provision agreement in force for {SOURCE_CODE} in this "
        "registry"
    )


def _apply(row: StaacHandover, *, actor: str) -> tuple[str, ...]:
    """Turn a landed snapshot into a Grievance, or hold it.

    The decision is `assess()`'s, not this function's. This writes
    what that decided, so a dry run and a real run cannot give
    different answers about the same snapshot.
    """
    body = row.snapshot or {}
    verdict = assess(body, agreement_reference=row.agreement_reference)

    if not verdict.will_file:
        _hold(
            row, verdict.detail, kind=verdict.held_reason,
            choice_list=verdict.held_choice_list,
            source_code=verdict.held_source_code, actor=actor,
        )
        return verdict.warnings

    complainant = body.get("complainant") or {}
    if not isinstance(complainant, dict):
        complainant = {}
    gender = resolve_gender(_text(complainant, "gender"))

    try:
        grievance = open_grievance(
            category=verdict.nsr_category,
            description=_text(body, "grievance", "narrative"),
            geographic_code=verdict.parish_key,
            reporter_name=_reporter_name(complainant),
            reporter_phone=_text(complainant, "phone"),
            reporter_gender=gender.nsr_code,
            reporter_age_years=_age(complainant),
            source_system=STAAC_SOURCE_SYSTEM,
            external_reference=verdict.tracking_number,
            reported_at=_when(_text(body, "source", "received_at")),
            actor=actor,
        )
    except GrievanceError as exc:
        # `assess` checked the place; anything left is a refusal it
        # could not foresee — a malformed phone, a category removed
        # between the two calls — and is held rather than lost.
        _hold(row, str(exc), kind=HeldReason.REFUSED, actor=actor)
        return verdict.warnings

    row.grievance = grievance
    row.outcome = HandoverOutcome.FILED
    row.outcome_detail = ""
    row.held_reason = ""
    row.held_choice_list = ""
    row.held_source_code = ""
    row.save(update_fields=[
        "grievance", "outcome", "outcome_detail", "held_reason",
        "held_choice_list", "held_source_code", "updated_at",
    ])

    emit_audit(
        "create", "staac.handover", row.id, actor=actor, actor_kind="system",
        reason=f"filed as grievance {grievance.reference or grievance.id}",
        field_changes={
            "handover_id": str(row.handover_id),
            "exchange_version": row.exchange_version,
            "grievance_id": grievance.id,
            "nsr_category": verdict.nsr_category,
            "staac_category": verdict.staac_category,
        },
    )
    return verdict.warnings


def _hold(
    row: StaacHandover, reason: str, *, kind: str,
    choice_list: str = "", source_code: str = "", actor: str,
) -> None:
    """Keep the snapshot, file nothing, and say why — twice.

    `kind` and `source_code` are what an operator filters and counts
    on ("which categories are blocking cases, and how many each");
    `reason` is the sentence for whoever opens one case.
    """
    row.outcome = HandoverOutcome.HELD
    row.outcome_detail = reason
    row.held_reason = kind
    row.held_choice_list = choice_list
    row.held_source_code = str(source_code or "")[:128]
    row.save(update_fields=[
        "outcome", "outcome_detail", "held_reason", "held_choice_list",
        "held_source_code", "updated_at",
    ])
    emit_audit(
        "update", "staac.handover", row.id, actor=actor, actor_kind="system",
        reason="held — not filed",
        field_changes={
            "handover_id": str(row.handover_id),
            "exchange_version": row.exchange_version,
            "outcome": HandoverOutcome.HELD,
            "held_reason": kind,
            "held_choice_list": choice_list,
            "held_source_code": row.held_source_code,
            "outcome_detail": reason,
        },
    )


def file_held(*, actor: str = PULL_ACTOR, limit: int = 0) -> list[FilingResult]:
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
