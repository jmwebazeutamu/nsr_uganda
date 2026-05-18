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


# --- US-119b: atomic approve + rule-pack sync ------------------------------

class FormApprovalError(IntakeError):
    """Approval refused for state / data reasons."""


# Statuses we accept as the source of the transition to ACTIVE. Approving
# a RETIRED or REJECTED form would be a policy reversal; force the
# operator to create a new FormVersion instead.
_APPROVABLE_FROM = {"draft", "pending_approval"}


@transaction.atomic
def approve_form_version(form_version: FormVersion, *, actor: str) -> dict:
    """Move a FormVersion to ACTIVE and fan out its rule pack to
    DAT-DQA in the same transaction.

    Atomic by design: if sync_rule_pack raises, the status transition
    rolls back and the form stays where it was. Avoids the dangling
    case where v2 looks ACTIVE in the admin but DAT-DQA never received
    the rules (US-119b — closes the gap left by US-119).

    Returns the rule_pack_sync report augmented with the new status +
    approver.
    """
    if form_version.status not in _APPROVABLE_FROM:
        raise FormApprovalError(
            f"FormVersion v{form_version.version} cannot be approved from "
            f"status={form_version.status!r}; allowed: {sorted(_APPROVABLE_FROM)}",
        )
    if not actor:
        raise FormApprovalError("actor required for approval")

    # Local import — apps.intake.services already pulls in DIH +
    # security; pulling rule_pack_sync at module-import would mean
    # apps.dqa loads at intake-app boot, which we want to avoid.
    from .rule_pack_sync import sync_rule_pack

    previous_status = form_version.status
    report = sync_rule_pack(form_version, actor=actor)

    form_version.status = "active"
    form_version.is_active = True
    form_version.approved_by = actor
    form_version.approved_at = timezone.now()
    form_version.save(update_fields=[
        "status", "is_active", "approved_by", "approved_at", "updated_at",
    ])

    emit_audit(
        action="approve", entity_type="intake.form_version",
        entity_id=form_version.id, actor=actor,
        reason=f"v{form_version.version} {previous_status}→active",
        field_changes={
            "status": ["active", previous_status],
            "rule_pack_created": report.get("created", 0),
            "rule_pack_updated": report.get("updated", 0),
        },
    )

    return {
        **report,
        "form_version_id": form_version.id,
        "version": form_version.version,
        "previous_status": previous_status,
        "new_status": form_version.status,
        "approved_by": actor,
    }


# --- US-S20-005: clone-to-new-version --------------------------------------

# Statuses where editing in place is forbidden — the form is the
# system-of-record for past submissions and can't change shape under
# them. Operators clone to a new DRAFT version instead.
LOCKED_STATUSES = ("active", "retired")


@transaction.atomic
def clone_form_version(form_version: FormVersion, *, actor: str) -> FormVersion:
    """Create a draft copy of `form_version` at version=max+1. All
    children (FormSection, FormQuestion, FormConstraint, FormSkipLogic)
    are duplicated. The new row carries the same name with a
    "(clone of vN)" suffix and inherits effective_from from today.

    Used when an operator needs to amend an active form — the original
    keeps its shape (submissions still resolve correctly), the new
    draft is editable.
    """
    if not actor:
        raise FormApprovalError("actor required for clone")
    from .models import FormConstraint, FormQuestion, FormSection, FormSkipLogic
    next_version = (
        FormVersion.objects.order_by("-version")
        .values_list("version", flat=True).first() or 0
    ) + 1
    today = timezone.now().date()
    new_fv = FormVersion.objects.create(
        version=next_version,
        name=f"{form_version.name} (clone of v{form_version.version})",
        description=form_version.description,
        effective_from=today,
        status="draft", is_active=False,
        author=actor,
    )

    for section in form_version.sections.order_by("order", "code"):
        new_section = FormSection.objects.create(
            form_version=new_fv,
            code=section.code, name=section.name,
            label=section.label, description=section.description,
            order=section.order, repeat_count=section.repeat_count,
        )
        for q in section.questions.order_by("order_in_section", "name"):
            new_q = FormQuestion.objects.create(
                section=new_section, name=q.name, label=q.label,
                hint=q.hint, type=q.type,
                choice_list_ref=q.choice_list_ref,
                required=q.required,
                relevant_expression=q.relevant_expression,
                constraint_expression=q.constraint_expression,
                constraint_message=q.constraint_message,
                appearance=q.appearance, repeat_count=q.repeat_count,
                parameters=q.parameters,
                order_in_section=q.order_in_section,
            )
            for c in q.constraints.all():
                FormConstraint.objects.create(
                    question=new_q, dsl=c.dsl,
                    message=c.message, description=c.description,
                )
            for sl in q.skip_logic.all():
                FormSkipLogic.objects.create(
                    question=new_q, dsl=sl.dsl,
                    description=sl.description,
                )

    emit_audit(
        action="clone", entity_type="intake.form_version",
        entity_id=new_fv.id, actor=actor,
        reason=f"cloned from v{form_version.version}",
        field_changes={
            "source_form_version": form_version.id,
            "source_version": form_version.version,
            "new_version": new_fv.version,
        },
    )
    return new_fv
