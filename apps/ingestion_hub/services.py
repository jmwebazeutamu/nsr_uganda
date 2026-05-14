"""DIH pipeline services.

Sprint 0 surface:
- start_connector_run: opens a run, refusing if no active DPA exists for
  the source (AC-DIH-DPA-REQUIRED).
- land_payload: writes a RawLanding (append-only).
- stage_from_landing: creates a StageRecord with a fresh provisional
  Registry ID (AC-DIH-MAPPING-VERSIONED, AC-DIH-PROVISIONAL-ID).
- promote_stage_record: the atomic step that turns a StageRecord into a
  Household (and Members, when the canonical payload carries them). The
  provisional ID becomes the confirmed Registry ID — no re-issue, no
  churn (AC-DIH-PROMOTE-ATOMIC). Idempotent on replay.
- reject_stage_record: voids the provisional ID and notifies (AC-DIH-
  REJECT-VOID).

Wiring stubs:
- DQA / DDUP / IDV calls live behind clear hooks but are no-ops in Sprint
  0; the orchestrator that fires them lands with item 7's API skeleton.
- PMT recompute is a documented TODO; it fires post-promotion when the
  PMT module is built.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from nsr_mis.common.fields import generate_ulid

from apps.data_management.models import Household, Member
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent

from .models import (
    Connector,
    ConnectorRun,
    ConnectorRunStatus,
    DataProvisionAgreement,
    MappingRuleVersion,
    PromotionAction,
    PromotionDecision,
    RawLanding,
    StageRecord,
    StageRecordState,
)

log = logging.getLogger(__name__)


class DihError(Exception):
    """A DIH pipeline pre-condition is unmet."""


def _emit_audit(action: str, entity_type: str, entity_id: str, *, actor: str,
                reason: str = "", field_changes: dict | None = None) -> None:
    AuditEvent.objects.create(
        actor_id=actor, actor_kind="system",
        action=action, entity_type=entity_type, entity_id=entity_id,
        reason=reason, field_changes=field_changes,
    )


@transaction.atomic
def start_connector_run(connector: Connector, *, actor: str = "system") -> ConnectorRun:
    """Open a ConnectorRun. AC-DIH-DPA-REQUIRED: refuses if no active DPA
    covers the source system."""
    today = timezone.now().date()
    has_dpa = DataProvisionAgreement.objects.filter(
        source_system=connector.source_system,
        valid_from__lte=today,
    ).filter(
        models_or(valid_to__isnull=True, valid_to__gte=today),
    ).exists() if False else _has_active_dpa(connector.source_system_id, today)
    if not has_dpa:
        raise DihError(f"no active DPA for source {connector.source_system.code}")

    run = ConnectorRun.objects.create(connector=connector, status=ConnectorRunStatus.RUNNING)
    _emit_audit("create", "connector_run", run.id, actor=actor,
                field_changes={"connector_id": connector.id})
    return run


def _has_active_dpa(source_system_id: str, today) -> bool:
    qs = DataProvisionAgreement.objects.filter(
        source_system_id=source_system_id, valid_from__lte=today,
    )
    return qs.filter(valid_to__isnull=True).exists() or qs.filter(valid_to__gte=today).exists()


@transaction.atomic
def land_payload(run: ConnectorRun, payload: dict, *, source_reference: str = "") -> RawLanding:
    """Append-only landing of a raw payload (AC-DIH-LANDING-IMMUTABLE)."""
    landing = RawLanding.objects.create(
        connector_run=run, payload=payload, source_reference=source_reference,
    )
    ConnectorRun.objects.filter(pk=run.pk).update(
        records_received=models_f("records_received") + 1,
        records_landed=models_f("records_landed") + 1,
    )
    return landing


@transaction.atomic
def stage_from_landing(
    landing: RawLanding,
    *,
    canonical_payload: dict,
    mapping_rule_version: MappingRuleVersion | None = None,
) -> StageRecord:
    """Create a StageRecord with a fresh provisional Registry ID.

    The mapping itself is done by the caller (the connector knows its own
    payload shape); this function just records the result + lineage.
    """
    stage = StageRecord.objects.create(
        provisional_registry_id=generate_ulid(),
        raw_landing=landing,
        connector_run=landing.connector_run,
        mapping_rule_version=mapping_rule_version,
        canonical_payload=canonical_payload,
        state=StageRecordState.PROVISIONAL,
    )
    ConnectorRun.objects.filter(pk=landing.connector_run_id).update(
        records_staged=models_f("records_staged") + 1,
    )
    return stage


@transaction.atomic
def promote_stage_record(
    stage: StageRecord,
    *,
    actor: str,
    action: str = PromotionAction.PROMOTE,
    reason: str = "",
) -> Household:
    """AC-DIH-PROMOTE-ATOMIC. Creates registry rows, transfers the
    provisional ID to confirmed status, writes lineage to landing +
    connector_run, emits AuditEvent. Idempotent on replay: if the
    stage record has already been promoted, returns the existing
    Household."""
    stage = StageRecord.objects.select_for_update().get(pk=stage.pk)

    if stage.state == StageRecordState.PROMOTED and stage.promoted_household_id:
        return Household.objects.get(pk=stage.promoted_household_id)

    if stage.state in (StageRecordState.REJECTED, StageRecordState.QUARANTINED):
        raise DihError(f"cannot promote a {stage.state} stage record")

    payload = stage.canonical_payload or {}
    geo_payload = payload.get("geographic", {})

    # Resolve the geographic ladder. The caller is expected to supply
    # GeographicUnit codes; we look them up by (level, code).
    def _geo(level: str) -> GeographicUnit:
        code = geo_payload.get(level)
        if not code:
            raise DihError(f"canonical_payload.geographic.{level} required")
        try:
            return GeographicUnit.objects.filter(level=level, code=code).order_by("-effective_from").first() \
                   or GeographicUnit.objects.get(level=level, code=code)
        except GeographicUnit.DoesNotExist as exc:
            raise DihError(f"geographic unit {level}={code} not found") from exc

    hh = Household.objects.create(
        id=stage.provisional_registry_id,
        region=_geo("region"), sub_region=_geo("sub_region"),
        district=_geo("district"), county=_geo("county"),
        sub_county=_geo("sub_county"), parish=_geo("parish"), village=_geo("village"),
        urban_rural=payload.get("urban_rural", "rural"),
        address_narrative=payload.get("address_narrative", ""),
        gps_lat=payload.get("gps_lat"),
        gps_lng=payload.get("gps_lng"),
        gps_accuracy_m=payload.get("gps_accuracy_m"),
        current_intake_source="dih",
    )

    # Create Members from the canonical payload's roster, if any.
    head_member = None
    for i, m in enumerate(payload.get("members", []) or [], start=1):
        member = Member.objects.create(
            household=hh,
            line_number=m.get("line_number", i),
            surname=m.get("surname", ""),
            first_name=m.get("first_name", ""),
            other_name=m.get("other_name", ""),
            relationship_to_head=m.get("relationship_to_head", ""),
            sex=m.get("sex", ""),
            date_of_birth=m.get("date_of_birth") or None,
            age_years=m.get("age_years"),
            telephone_1=m.get("telephone_1", ""),
            telephone_2=m.get("telephone_2", ""),
        )
        if m.get("is_head") and head_member is None:
            head_member = member

    if head_member:
        hh.head_member = head_member
        hh.save(update_fields=["head_member", "updated_at"])

    # Transfer provisional ID to confirmed status.
    stage.state = StageRecordState.PROMOTED
    stage.promoted_household_id = hh.id
    stage.promoted_at = timezone.now()
    stage.save(update_fields=["state", "promoted_household_id", "promoted_at", "updated_at"])

    PromotionDecision.objects.create(
        stage_record=stage, action=action, actor=actor, reason=reason,
    )
    ConnectorRun.objects.filter(pk=stage.connector_run_id).update(
        records_promoted=models_f("records_promoted") + 1,
    )

    _emit_audit(
        action="promote", entity_type="household", entity_id=hh.id,
        actor=actor, reason=reason,
        field_changes={
            "stage_record_id": stage.id,
            "raw_landing_id": stage.raw_landing_id,
            "connector_run_id": stage.connector_run_id,
            "mapping_rule_version_id": stage.mapping_rule_version_id,
        },
    )
    # TODO: trigger PMT recompute via event bus once apps.pmt lands
    #       (AC-DIH-PMT-AFTER-PROMOTION).

    return hh


@transaction.atomic
def reject_stage_record(stage: StageRecord, *, actor: str, reason: str) -> StageRecord:
    """AC-DIH-REJECT-VOID. Voids the provisional ID; the citizen or source
    must be notified with a reason (notification path lands separately)."""
    if stage.state == StageRecordState.PROMOTED:
        raise DihError("cannot reject a promoted stage record")
    if not reason:
        raise DihError("reject requires a non-empty reason")

    stage.state = StageRecordState.REJECTED
    stage.rejected_reason = reason
    stage.rejected_at = timezone.now()
    stage.rejected_by = actor
    stage.save(update_fields=[
        "state", "rejected_reason", "rejected_at", "rejected_by", "updated_at",
    ])
    PromotionDecision.objects.create(
        stage_record=stage, action=PromotionAction.REJECT, actor=actor, reason=reason,
    )
    ConnectorRun.objects.filter(pk=stage.connector_run_id).update(
        records_rejected=models_f("records_rejected") + 1,
    )
    _emit_audit("reject", "stage_record", stage.id, actor=actor, reason=reason)
    return stage


# --- Helpers ---------------------------------------------------------------

from django.db import models  # noqa: E402  (imported here to keep top of file clean)


def models_f(name: str):
    return models.F(name)


def models_or(**kwargs):  # tiny shim for readability in start_connector_run
    return models.Q(**kwargs)
