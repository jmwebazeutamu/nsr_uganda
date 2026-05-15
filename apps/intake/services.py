"""INT services — submit_intake routes a raw payload through DIH.

Every intake submission lands in DIH (per ADR-0001 + SAD §4.6 — "every
record entering the registry passes through DIH"). The function here
creates a Submission row, calls apps.ingestion_hub.services to land the
payload + create a StageRecord, and links the two via stage_record_id.

The DIH orchestrator (process_stage_record) runs DQA / IDV / DDUP and
either auto-promotes (fast-track) or routes to NSR Unit review.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.ingestion_hub.models import Connector, SourceSystem, SourceSystemKind
from apps.ingestion_hub.services import (
    land_payload,
    process_stage_record,
    stage_from_landing,
    start_connector_run,
)
from apps.security.audit import emit as emit_audit

from .models import FormVersion, Submission, SubmissionResult, SubmissionState


class IntakeError(Exception):
    """An intake-side precondition is unmet."""


def _connector_for_channel(channel: str) -> Connector:
    """Map an intake channel to the DIH connector that handles it."""
    mapping = {
        "capi": SourceSystemKind.CAPI_WALKIN,
        "web":  SourceSystemKind.WEB,
        # USSD lands in the CAPI source in Sprint 2; per SAD §11.2 USSD
        # is a Release 2 own connector.
        "ussd": SourceSystemKind.CAPI_WALKIN,
        "bulk": SourceSystemKind.UBOS,
    }
    kind = mapping.get(channel)
    if not kind:
        raise IntakeError(f"no DIH connector configured for channel {channel!r}")
    src = SourceSystem.objects.filter(kind=kind, is_active=True).first()
    if not src:
        raise IntakeError(f"no active SourceSystem for kind {kind!r}")
    conn = Connector.objects.filter(source_system=src, is_active=True).first()
    if not conn:
        raise IntakeError(f"no active Connector for source {src.code!r}")
    return conn


def _active_form_version() -> FormVersion:
    fv = FormVersion.objects.filter(is_active=True).order_by("-version").first()
    if fv is None:
        raise IntakeError("no ACTIVE FormVersion")
    return fv


@transaction.atomic
def submit_intake(
    *,
    channel: str,
    canonical_payload: dict,
    enumerator: str,
    supervisor: str = "",
    started_at=None,
    finished_at=None,
    result: str = SubmissionResult.COMPLETED,
    actor: str = "",
    auto_process: bool = True,
) -> Submission:
    """Capture an intake. One transaction: Submission + DIH landing +
    StageRecord, optionally orchestrated through DQA/IDV/DDUP.

    Returns the persisted Submission with stage_record_id and
    provisional_registry_id populated.
    """
    fv = _active_form_version()
    connector = _connector_for_channel(channel)
    run = start_connector_run(connector, actor=actor or enumerator)
    landing = land_payload(run, canonical_payload, source_reference=f"int-{channel}")
    stage = stage_from_landing(landing, canonical_payload=canonical_payload)

    now = timezone.now()
    submission = Submission.objects.create(
        channel=channel,
        form_version=fv,
        enumerator=enumerator,
        supervisor=supervisor,
        gps_lat=canonical_payload.get("gps_lat"),
        gps_lng=canonical_payload.get("gps_lng"),
        gps_accuracy_m=canonical_payload.get("gps_accuracy_m"),
        started_at=started_at or now,
        finished_at=finished_at or now,
        result=result,
        state=SubmissionState.PENDING_QA,
        stage_record_id=stage.id,
        provisional_registry_id=stage.provisional_registry_id,
    )

    emit_audit(
        action="create", entity_type="submission", entity_id=submission.id,
        actor=actor or enumerator, reason=f"channel={channel}",
        field_changes={
            "stage_record_id": stage.id,
            "provisional_registry_id": stage.provisional_registry_id,
            "form_version": fv.version,
        },
    )

    if auto_process:
        process_stage_record(stage, actor=actor or enumerator)

    return submission
