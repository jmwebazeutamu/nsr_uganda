"""DIH pipeline services.

End-to-end surface:
- start_connector_run: opens a run, refusing if no active DPA exists for
  the source (AC-DIH-DPA-REQUIRED).
- land_payload: writes a RawLanding (append-only).
- stage_from_landing: creates a StageRecord with a fresh provisional
  Registry ID (AC-DIH-MAPPING-VERSIONED, AC-DIH-PROVISIONAL-ID).
- process_stage_record: runs the staging gates (DQA -> IDV -> DDUP) and
  routes the stage to the appropriate next state. Auto-promotes clean
  walk-ins per AC-DIH-FT-AUTO. Wires apps.dqa, apps.identity_verification,
  and apps.ddup as the SAD §4.6 pipeline expects.
- promote_stage_record: the atomic step that turns a StageRecord into a
  Household (and Members). The provisional ID becomes the confirmed
  Registry ID — no re-issue (AC-DIH-PROMOTE-ATOMIC). Idempotent on replay.
- reject_stage_record: voids the provisional ID (AC-DIH-REJECT-VOID).

Cross-app calls are in-process Python per ADR-0001. PMT recompute is a
documented TODO; it fires post-promotion when the PMT module is built.
"""

from __future__ import annotations

import hashlib
import logging
import re as _re

from django.db import models, transaction
from django.db.models import F
from django.utils import timezone
from nsr_mis.common.fields import generate_ulid

from apps.data_management.models import (
    AssetOwnership,
    CopingStrategy,
    Crop,
    Disability,
    Dwelling,
    Education,
    Employment,
    FoodConsumption,
    FoodSecurity,
    Health,
    Household,
    Livelihood,
    Livestock,
    Member,
    Shock,
    Utilities,
)
from apps.dqa.engine import evaluate_all as dqa_evaluate_all
from apps.identity_verification.mock import NiraError, verify_nin
from apps.reference_data.models import GeographicUnit
from apps.security.audit import emit as emit_audit
from apps.security.hashing import nin_hash as compute_nin_hash
from apps.security.hashing import nin_last4 as compute_nin_last4

from .models import (
    Connector,
    ConnectorRun,
    ConnectorRunStatus,
    DataProvisionAgreement,
    FastTrackAuditSample,
    MappingRuleVersion,
    PromotionAction,
    PromotionDecision,
    RawLanding,
    SourceSystemKind,
    StageRecord,
    StageRecordState,
)

# 1% of fast-track auto-promotions land in the NSR Unit audit queue
# (AC-DIH-FT-AUTO, SAD §4.6.4). Deterministic on the stage_record id so
# re-runs produce the same sample set.
FAST_TRACK_SAMPLE_RATE = 100  # 1 in N


def _is_sampled(stage_id: str) -> bool:
    # SHA-256 of the ULID modulo N gives a stable, uniform 1-in-N bucket.
    # Python's int(base=32) uses RFC 4648 alphabet (A-Z + 2-7) which
    # doesn't match Crockford ULID — hash sidesteps the encoding gap.
    digest = hashlib.sha256(stage_id.encode("ascii")).digest()
    return int.from_bytes(digest[:4], "big") % FAST_TRACK_SAMPLE_RATE == 0

log = logging.getLogger(__name__)


class DihError(Exception):
    """A DIH pipeline pre-condition is unmet."""


def _emit_audit(action: str, entity_type: str, entity_id: str, *, actor: str,
                reason: str = "", field_changes: dict | None = None) -> None:
    """Thin wrapper around the shared emitter — kept for call-site clarity."""
    emit_audit(action, entity_type, entity_id, actor=actor, actor_kind="system",
               reason=reason, field_changes=field_changes)


@transaction.atomic
def start_connector_run(connector: Connector, *, actor: str = "system") -> ConnectorRun:
    """Open a ConnectorRun. AC-DIH-DPA-REQUIRED: refuses if no active DPA
    covers the source system."""
    today = timezone.now().date()
    if not _has_active_dpa(connector.source_system_id, today):
        raise DihError(f"no active DPA for source {connector.source_system.code}")

    run = ConnectorRun.objects.create(connector=connector, status=ConnectorRunStatus.RUNNING)
    _emit_audit("create", "connector_run", run.id, actor=actor,
                field_changes={"connector_id": connector.id})
    return run


def _has_active_dpa(source_system_id: str, today) -> bool:
    return DataProvisionAgreement.objects.filter(
        source_system_id=source_system_id,
        valid_from__lte=today,
    ).filter(
        models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=today),
    ).exists()


@transaction.atomic
def land_payload(run: ConnectorRun, payload: dict, *, source_reference: str = "") -> RawLanding:
    """Append-only landing of a raw payload (AC-DIH-LANDING-IMMUTABLE)."""
    landing = RawLanding.objects.create(
        connector_run=run, payload=payload, source_reference=source_reference,
    )
    ConnectorRun.objects.filter(pk=run.pk).update(
        records_received=F("records_received") + 1,
        records_landed=F("records_landed") + 1,
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
        records_staged=F("records_staged") + 1,
    )
    return stage


def _emit_create(entity_type: str, entity_id: str, *, actor: str) -> None:
    """Audit a detail-entity create during promotion fanout. Per US-S22-DE-04
    every detail row written by the fanout helpers emits one AuditEvent
    with `action="create"` and `entity_type="<lowercase_model>"` (the
    AC-DE-AUDIT contract)."""
    _emit_audit(
        "create", entity_type, entity_id, actor=actor,
        reason="promotion fanout",
    )


# --- US-S22-DE-04 promotion fanout helpers ---------------------------------
#
# Each helper:
#   * is defensive — if its canonical_payload section is missing / empty,
#     it skips silently.
#   * is idempotent — `get_or_create` keyed on the parent FK (one-to-one)
#     or (parent FK, type code) (repeats). Audit emission fires only on
#     the `created=True` path so replay doesn't duplicate audit rows.
#   * inherits sub_region_code from the parent on the model's save() —
#     no explicit propagation needed here.
#
# Expected canonical_payload shape — see the build prompt §3.


def _create_dwelling(hh: Household, payload: dict, *, actor: str) -> None:
    sect = payload.get("dwelling") or {}
    legacy_tenure = (payload.get("dwelling_tenure") or "").strip()
    if not sect and not legacy_tenure:
        return
    tenure = sect.get("tenure") or legacy_tenure
    obj, created = Dwelling.objects.get_or_create(
        household=hh,
        defaults={
            "tenure": tenure,
            "dwelling_type": sect.get("dwelling_type", ""),
            "total_rooms": sect.get("total_rooms"),
            "sleeping_rooms": sect.get("sleeping_rooms"),
            "roof_material": sect.get("roof_material", ""),
            "wall_material": sect.get("wall_material", ""),
            "floor_material": sect.get("floor_material", ""),
        },
    )
    if created:
        _emit_create("dwelling", obj.id, actor=actor)


def _create_utilities(hh: Household, payload: dict, *, actor: str) -> None:
    sect = payload.get("utilities") or {}
    if not sect:
        return
    obj, created = Utilities.objects.get_or_create(
        household=hh,
        defaults={
            "cooking_fuel": sect.get("cooking_fuel", ""),
            "lighting_energy": sect.get("lighting_energy", ""),
            "drinking_water_source": sect.get("drinking_water_source", ""),
            "toilet_facility": sect.get("toilet_facility", ""),
            "toilet_shared": sect.get("toilet_shared"),
            "households_sharing_toilet": sect.get("households_sharing_toilet"),
            "waste_disposal": sect.get("waste_disposal", ""),
        },
    )
    if created:
        _emit_create("utilities", obj.id, actor=actor)


def _create_livelihood(hh: Household, payload: dict, *, actor: str) -> None:
    sect = payload.get("livelihood") or {}
    if not sect:
        return
    obj, created = Livelihood.objects.get_or_create(
        household=hh,
        defaults={
            "main_livelihood": sect.get("main_livelihood", ""),
            "crop_production_zone": sect.get("crop_production_zone", ""),
            "livestock_zone": sect.get("livestock_zone", ""),
            "agricultural_purpose": sect.get("agricultural_purpose", ""),
            "land_ownership": sect.get("land_ownership", ""),
            "land_hectares": sect.get("land_hectares"),
            "land_title": sect.get("land_title", ""),
        },
    )
    if created:
        _emit_create("livelihood", obj.id, actor=actor)


def _create_food_security(hh: Household, payload: dict, *, actor: str) -> None:
    sect = payload.get("food_security") or {}
    if not sect:
        return
    obj, created = FoodSecurity.objects.get_or_create(
        household=hh,
        defaults={
            "worried_food": sect.get("worried_food", ""),
            "unhealthy_food": sect.get("unhealthy_food", ""),
            "limited_variety": sect.get("limited_variety", ""),
            "skipped_meal": sect.get("skipped_meal", ""),
            "ate_less": sect.get("ate_less", ""),
            "ran_out_food": sect.get("ran_out_food", ""),
            "hungry_no_eat": sect.get("hungry_no_eat", ""),
            "whole_day_no_eat": sect.get("whole_day_no_eat", ""),
        },
    )
    if created:
        _emit_create("food_security", obj.id, actor=actor)


def _create_food_consumption(
    hh: Household, payload: dict, *, actor: str,
) -> None:
    sect = payload.get("food_consumption") or {}
    if not sect:
        return
    # The build prompt's expected shape is per-food-group dicts:
    # {"staples": {"days_last_7": 7, "source_primary": "..."}, ...}.
    # The model flattens that to <group>_days / <group>_source columns.
    groups = (
        "staples", "pulses", "dairy", "meat",
        "vegetables", "fruits", "oils", "sugar", "condiments",
    )
    defaults: dict = {}
    for g in groups:
        grp = sect.get(g) or {}
        defaults[f"{g}_days"] = grp.get("days_last_7", 0) or 0
        defaults[f"{g}_source"] = grp.get("source_primary", "")
    obj, created = FoodConsumption.objects.get_or_create(
        household=hh, defaults=defaults,
    )
    if created:
        _emit_create("food_consumption", obj.id, actor=actor)


def _create_health(member: Member, m_payload: dict, *, actor: str) -> None:
    sect = m_payload.get("health") or {}
    if not sect:
        return
    obj, created = Health.objects.get_or_create(
        member=member,
        defaults={"chronic_illness_flag": sect.get("chronic_illness_flag", "")},
    )
    if created:
        # chronic_illness_types may include HIV/TB codes — set via the
        # encrypted helper so the plaintext never lands in the column.
        types = sect.get("chronic_illness_types") or []
        if types:
            obj.set_chronic_illness_types(list(types))
            obj.save(update_fields=["chronic_illness_types_encrypted", "updated_at"])
        _emit_create("health", obj.id, actor=actor)


def _create_disability(
    member: Member, m_payload: dict, *, actor: str,
) -> None:
    sect = m_payload.get("disability") or {}
    if not sect:
        return
    obj, created = Disability.objects.get_or_create(
        member=member,
        defaults={
            "seeing": sect.get("seeing", ""),
            "hearing": sect.get("hearing", ""),
            "walking": sect.get("walking", ""),
            "memory": sect.get("memory", ""),
            "selfcare": sect.get("selfcare", ""),
            "communication": sect.get("communication", ""),
        },
    )
    if created:
        _emit_create("disability", obj.id, actor=actor)


def _create_education(
    member: Member, m_payload: dict, *, actor: str,
) -> None:
    sect = m_payload.get("education") or {}
    if not sect:
        return
    obj, created = Education.objects.get_or_create(
        member=member,
        defaults={
            "literacy_status": sect.get("literacy_status", ""),
            "ever_attended": sect.get("ever_attended", ""),
            "never_attended_reason": sect.get("never_attended_reason", ""),
            "highest_grade": sect.get("highest_grade", ""),
            "currently_attending": sect.get("currently_attending", ""),
            "why_stopped": sect.get("why_stopped", ""),
        },
    )
    if created:
        _emit_create("education", obj.id, actor=actor)


def _create_employment(
    member: Member, m_payload: dict, *, actor: str,
) -> None:
    sect = m_payload.get("employment") or {}
    if not sect:
        return
    obj, created = Employment.objects.get_or_create(
        member=member,
        defaults={
            "main_activity_last_30d": sect.get("main_activity_last_30d", ""),
            "work_frequency": sect.get("work_frequency", ""),
            "sector": sect.get("sector", ""),
            "employment_status": sect.get("employment_status", ""),
            "not_working_reason": sect.get("not_working_reason", ""),
            "is_govt_programme_beneficiary": sect.get(
                "is_govt_programme_beneficiary", "",
            ),
            "programmes_benefited": sect.get("programmes_benefited") or [],
            "currently_benefiting": sect.get("currently_benefiting", ""),
            "made_savings": sect.get("made_savings", ""),
            "savings_location": sect.get("savings_location", ""),
        },
    )
    if created:
        _emit_create("employment", obj.id, actor=actor)


def _create_assets(hh: Household, payload: dict, *, actor: str) -> None:
    for row in payload.get("assets") or []:
        code = (row.get("asset_type") or "").strip()
        if not code:
            continue
        obj, created = AssetOwnership.objects.get_or_create(
            household=hh, asset_type=code,
            defaults={"count": row.get("count", 0) or 0},
        )
        if created:
            _emit_create("asset_ownership", obj.id, actor=actor)


def _create_crops(hh: Household, payload: dict, *, actor: str) -> None:
    for row in payload.get("crops") or []:
        name = (row.get("crop_name") or "").strip()
        if not name:
            continue
        obj, created = Crop.objects.get_or_create(
            household=hh, crop_name=name,
            defaults={"rank_order": row.get("rank_order", 0) or 0},
        )
        if created:
            _emit_create("crop", obj.id, actor=actor)


def _create_livestock(hh: Household, payload: dict, *, actor: str) -> None:
    for row in payload.get("livestock") or []:
        kind = (row.get("livestock_type") or "").strip()
        if not kind:
            continue
        obj, created = Livestock.objects.get_or_create(
            household=hh, livestock_type=kind,
            defaults={"count": row.get("count", 0) or 0},
        )
        if created:
            _emit_create("livestock", obj.id, actor=actor)


def _create_shocks(hh: Household, payload: dict, *, actor: str) -> None:
    for row in payload.get("shocks") or []:
        kind = (row.get("shock_type") or "").strip()
        if not kind:
            continue
        obj = Shock.objects.create(
            household=hh, shock_type=kind,
            livelihoods_affected=row.get("livelihoods_affected") or [],
            severity=row.get("severity", ""),
            crops_severity_score=row.get("crops_severity_score"),
            livestock_severity_score=row.get("livestock_severity_score"),
            labour_severity_score=row.get("labour_severity_score"),
            other_severity_score=row.get("other_severity_score"),
            event_date=row.get("event_date") or None,
        )
        _emit_create("shock", obj.id, actor=actor)


def _create_coping_strategies(
    hh: Household, payload: dict, *, actor: str,
) -> None:
    for row in payload.get("coping_strategies") or []:
        kind = (row.get("strategy_type") or "").strip()
        category = (row.get("category") or "").strip()
        if not kind or not category:
            continue
        obj, created = CopingStrategy.objects.get_or_create(
            household=hh, strategy_type=kind, category=category,
            defaults={
                "frequency": row.get("frequency", ""),
                "used_flag": bool(row.get("used_flag", False)),
            },
        )
        if created:
            _emit_create("coping_strategy", obj.id, actor=actor)


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

    # AC-DIH-EDIT-NO-SELF-APPROVE — the operator who corrected the
    # stage record cannot be the one who promotes it. Mirrors the
    # DQA / DDUP / PMT dual-approval pattern.
    if stage.last_edited_by and stage.last_edited_by == actor:
        raise DihError(
            f"actor {actor!r} edited this stage record and cannot also "
            f"promote it (AC-DIH-EDIT-NO-SELF-APPROVE)",
        )

    payload = stage.canonical_payload or {}
    geo_payload = payload.get("geographic", {})

    # Resolve the geographic ladder. The caller is expected to supply
    # GeographicUnit codes; we look them up by (level, code).
    # Levels in _OPTIONAL_LEVELS may be missing — _geo returns None
    # without raising when the payload omits them (per the UBOS
    # frame, village rows aren't seeded for every parish so they
    # commonly arrive blank from field capture).
    _optional_levels = {"village"}

    def _geo(level: str):
        code = geo_payload.get(level)
        if not code:
            if level in _optional_levels:
                return None
            raise DihError(f"canonical_payload.geographic.{level} required")
        row = (
            GeographicUnit.objects
            .filter(level=level, code=code)
            .order_by("-effective_from")
            .first()
        )
        if row is None:
            raise DihError(f"geographic unit {level}={code} not found")
        return row

    # US-S22-DE-04: thread the source-system kind through so the
    # current_intake_source reflects the real channel ("capi_walkin" /
    # "ubos" / "kobo" / etc.) instead of the hardcoded "dih". Falls
    # back to "dih" only when the chain is unresolvable (defensive —
    # the standard pipeline always has a connector / source).
    try:
        intake_source = stage.connector_run.connector.source_system.kind or "dih"
    except AttributeError:
        intake_source = "dih"

    # US-S22-DE-04: backward-compat for the legacy top-level
    # `dwelling_tenure` key — write to Household.dwelling_tenure AND
    # let _create_dwelling pick it up below to create a Dwelling row.
    # Nested `payload["dwelling"]["tenure"]` takes precedence.
    dwelling_sect = payload.get("dwelling") or {}
    hh_dwelling_tenure = (
        dwelling_sect.get("tenure")
        or payload.get("dwelling_tenure", "")
        or ""
    )

    hh = Household.objects.create(
        id=stage.provisional_registry_id,
        region=_geo("region"), sub_region=_geo("sub_region"),
        district=_geo("district"), county=_geo("county"),
        sub_county=_geo("sub_county"), parish=_geo("parish"), village=_geo("village"),
        # Stored as ChoiceOption.code on the rural_urban list (ADR-0010);
        # canonical_payload writers (e.g. Kobo connector) supply the
        # raw code. Default to blank rather than guessing "rural".
        urban_rural=payload.get("urban_rural", ""),
        address_narrative=payload.get("address_narrative", ""),
        gps_lat=payload.get("gps_lat"),
        gps_lng=payload.get("gps_lng"),
        gps_accuracy_m=payload.get("gps_accuracy_m"),
        dwelling_tenure=hh_dwelling_tenure,
        residence_status=payload.get("residence_status", ""),
        current_intake_source=intake_source,
    )

    # Create Members from the canonical payload's roster, if any.
    head_member = None
    created_members: list[tuple[Member, dict]] = []
    for i, m in enumerate(payload.get("members", []) or [], start=1):
        nin = (m.get("nin") or "").strip()
        member_kwargs = dict(
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
            # US-S22-DE-04: the typed columns the previous promote skipped.
            marital_status=m.get("marital_status", ""),
            nationality=m.get("nationality", ""),
            residency_status=m.get("residency_status", ""),
            birth_certificate_status=m.get("birth_certificate_status", ""),
            telephone_in_name_flag=bool(m.get("telephone_in_name_flag", False)),
            mobile_money_flag=bool(m.get("mobile_money_flag", False)),
            mother_alive_flag=m.get("mother_alive_flag"),
            father_alive_flag=m.get("father_alive_flag"),
            mother_line_number=m.get("mother_line_number"),
            father_line_number=m.get("father_line_number"),
            identification_documents=m.get("identification_documents") or [],
        )
        if nin:
            # NIN trio per ADR-0002 — populated via the canonical helpers so
            # the encrypted value, hash, and display suffix stay in lockstep.
            member_kwargs["nin_value"] = nin.encode("utf-8")
            member_kwargs["nin_hash"] = compute_nin_hash(nin)
            member_kwargs["nin_last4"] = compute_nin_last4(nin)
            # ChoiceOption code for "Yes, has card" on the nin_status list (ADR-0010).
            member_kwargs["nin_status"] = "1"
        member = Member.objects.create(**member_kwargs)
        created_members.append((member, m))
        if m.get("is_head") and head_member is None:
            head_member = member

    if head_member:
        # US-FIX-001 — the head-member invariant. `Household.head_member`
        # and `Member.relationship_to_head = "01"` (the ChoiceOption code
        # for "Head" on the seeded `relationship` list) must agree. The
        # promote payload sets `is_head` to identify the head row, but
        # historically didn't always carry `relationship_to_head`. We
        # now enforce it here so the audit-bearing path (the ONLY path
        # creating households on the registry side per CLAUDE.md) writes
        # consistent rows. The model-level `Household.clean()` below is
        # the guard for any non-promote write path.
        if head_member.relationship_to_head != "01":
            head_member.relationship_to_head = "01"
            head_member.save(update_fields=["relationship_to_head", "updated_at"])
        hh.head_member = head_member
        hh.save(update_fields=["head_member", "updated_at"])

    # US-S22-DE-04: detail-entity fanout. Population order per build
    # prompt §3: Household → Members → per-household details →
    # per-member details → repeat groups. PMT recompute (below) stays
    # last so it sees every detail row.
    _create_dwelling(hh, payload, actor=actor)
    _create_utilities(hh, payload, actor=actor)
    _create_livelihood(hh, payload, actor=actor)
    _create_food_security(hh, payload, actor=actor)
    _create_food_consumption(hh, payload, actor=actor)

    for _member, _m_payload in created_members:
        _create_health(_member, _m_payload, actor=actor)
        _create_disability(_member, _m_payload, actor=actor)
        _create_education(_member, _m_payload, actor=actor)
        _create_employment(_member, _m_payload, actor=actor)

    _create_assets(hh, payload, actor=actor)
    _create_crops(hh, payload, actor=actor)
    _create_livestock(hh, payload, actor=actor)
    _create_shocks(hh, payload, actor=actor)
    _create_coping_strategies(hh, payload, actor=actor)

    # Transfer provisional ID to confirmed status.
    stage.state = StageRecordState.PROMOTED
    stage.promoted_household_id = hh.id
    stage.promoted_at = timezone.now()
    stage.save(update_fields=["state", "promoted_household_id", "promoted_at", "updated_at"])

    PromotionDecision.objects.create(
        stage_record=stage, action=action, actor=actor, reason=reason,
    )
    ConnectorRun.objects.filter(pk=stage.connector_run_id).update(
        records_promoted=F("records_promoted") + 1,
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
    # AC-DIH-PMT-AFTER-PROMOTION — fire the registry-side recompute. Harmless
    # when no ACTIVE PMT model exists (recompute_for_household returns None).
    from apps.pmt.services import recompute_for_household
    recompute_for_household(hh, triggered_by="dih_promote", actor=actor)

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
        records_rejected=F("records_rejected") + 1,
    )
    _emit_audit("reject", "stage_record", stage.id, actor=actor, reason=reason)
    return stage


# ---------------------------------------------------------------------------
# Staging gates orchestrator (SAD §4.6.2: Validate -> Verify -> Discover ->
# Route, with the AC-DIH-FT-AUTO fast-track for clean walk-ins)
# ---------------------------------------------------------------------------

_WALKIN_KINDS = {SourceSystemKind.CAPI_WALKIN, SourceSystemKind.WEB}


def _first_member_nin(payload: dict) -> str | None:
    members = (payload or {}).get("members") or []
    for m in members:
        nin = (m or {}).get("nin")
        if nin:
            return nin
    return None


def _evaluate_dqa(payload: dict, *, stage_id: str = "") -> dict:
    """Run all ACTIVE DQA rules against the household-level dict and against
    each member dict. Returns a summary keyed by severity, suitable for
    storing in StageRecord.dqa_summary.

    Side effect (US-082a): writes one DqaResult row per failed evaluation
    so the violations dashboard can aggregate. Passes are NOT persisted —
    the table would otherwise grow at intake rate × every active rule.
    `info` severity is dropped by default; set
    settings.DQA_PERSIST_INFO_FAILURES=True to include them. `stage_id`
    is the provisional registry id of the originating StageRecord; when
    empty, the function falls back to the old synthetic ids so the
    summary stays compatible with anything that doesn't have a stage
    (e.g. preview-style ad-hoc evaluations).
    """
    from django.conf import settings as _settings

    from apps.dqa.models import DqaResult

    summary: dict[str, list[dict]] = {"blocking": [], "warning": [], "info": []}
    payload = payload or {}
    members = payload.get("members") or []
    persist_info = bool(getattr(_settings, "DQA_PERSIST_INFO_FAILURES", False))
    rows_to_write: list[DqaResult] = []

    def _record(evaluations, *, record_id: str, record_type: str) -> None:
        for ev in evaluations:
            if ev.passed:
                continue
            summary.setdefault(ev.rule.severity, []).append({
                "rule_id": ev.rule.rule_id,
                "rule_version": ev.rule.version,
                "record_id": record_id,
                "reason": ev.reason,
            })
            if ev.rule.severity == "info" and not persist_info:
                continue
            rows_to_write.append(DqaResult(
                rule=ev.rule, record_type=record_type, record_id=record_id,
                passed=False, severity=ev.rule.severity, reason=ev.reason,
            ))

    hh_payload = {k: v for k, v in payload.items() if k != "members"}
    hh_record_id = stage_id or "staged"
    _record(
        dqa_evaluate_all(hh_payload, record_type="household", record_id=hh_record_id),
        record_id=hh_record_id, record_type="household",
    )
    for m in members:
        line = str((m or {}).get("line_number", ""))
        member_record_id = (
            f"{stage_id}:{line}" if stage_id else f"line-{line}"
        )
        _record(
            dqa_evaluate_all(m or {}, record_type="member", record_id=member_record_id),
            record_id=member_record_id, record_type="member",
        )

    if rows_to_write:
        DqaResult.objects.bulk_create(rows_to_write, batch_size=100)

    return {
        "blocking_failures": summary["blocking"],
        "warnings": summary["warning"],
        "info": summary["info"],
    }


@transaction.atomic
def resolve_idv_pending(
    stage: StageRecord, *, actor: str, reason: str, decision: str,
) -> StageRecord:
    """Operator-driven exit from the IDV_PENDING limbo.

    When NIRA returns service_unavailable / no_match / mismatch /
    bad_format, `process_stage_record` parks the record at
    IDV_PENDING. An operator with off-system evidence then chooses
    one of:

      decision='accept' — the NIN is trusted on the basis of paper /
        in-person verification. We override `idv_outcome` to
        'manual_accept', run DDUP discovery (which was skipped in the
        original gate run), and route to either PENDING_PROMOTION
        (clean) or DDUP_REVIEW (a strong candidate exists). No DQA
        re-run — DQA already passed before IDV was reached.

      decision='reject' — the identity claim is unsupportable;
        delegate to reject_stage_record so the provisional ID is
        voided per AC-DIH-REJECT-VOID. Reason prefixed with
        'idv-reject:' so the audit trail makes the route explicit.

    Refuses if the stage isn't currently IDV_PENDING (no double-
    resolve), or if the reason is blank (the audit trail is the
    only record of the operator's judgment).
    """
    if stage.state != StageRecordState.IDV_PENDING:
        raise DihError(
            f"resolve_idv_pending: stage is {stage.state}, not idv_pending",
        )
    if decision not in ("accept", "reject"):
        raise DihError(
            f"resolve_idv_pending: decision must be 'accept' or 'reject', "
            f"got {decision!r}",
        )
    if not actor:
        raise DihError("resolve_idv_pending: actor is required")
    if not reason or not reason.strip():
        raise DihError("resolve_idv_pending: reason is required")

    reason = reason.strip()
    if decision == "reject":
        return reject_stage_record(
            stage, actor=actor, reason=f"idv-reject: {reason}",
        )

    # Accept path: override IDV, run DDUP discovery, route.
    payload = stage.canonical_payload
    candidates = _discover_stage_candidates(payload)
    has_strong = any(c["score"] >= 0.80 for c in candidates)
    stage.idv_outcome = "manual_accept"
    stage.ddup_candidates = candidates
    if has_strong:
        stage.state = StageRecordState.DDUP_REVIEW
        next_state = StageRecordState.DDUP_REVIEW
    else:
        stage.state = StageRecordState.PENDING_PROMOTION
        next_state = StageRecordState.PENDING_PROMOTION
    stage.save(update_fields=[
        "state", "idv_outcome", "ddup_candidates", "updated_at",
    ])
    _emit_audit(
        "resolve_idv", "stage_record", stage.id, actor=actor,
        reason=f"manual-accept: {reason}",
        field_changes={
            "idv_outcome": "manual_accept",
            "next_state": next_state,
            "ddup_candidate_count": len(candidates),
        },
    )
    return stage


def _discover_stage_candidates(payload: dict) -> list[dict]:
    """Tier 1 NIN-exact match against existing registry Members. Returns
    [{member_id, score, reason}, ...]. Empty if no NIN supplied."""
    nin = _first_member_nin(payload)
    if not nin:
        return []
    rows = Member.objects.filter(
        nin_hash=compute_nin_hash(nin), is_deleted=False,
    ).values_list("id", flat=True)
    return [{"member_id": rid, "score": 1.0, "reason": "tier1-nin-exact"} for rid in rows]


@transaction.atomic
def process_stage_record(
    stage: StageRecord, *, actor: str = "system", allow_fast_track: bool = True,
) -> StageRecord:
    """Run the staging gates and route the stage to its next state.

    Outcomes per SAD §4.6.2:
    - DQA blocking -> QUALITY_FAILED
    - IDV NIRA outage -> IDV_PENDING (retried by nightly job)
    - IDV mismatch -> IDV_PENDING (operator must reconcile)
    - DDUP candidate (>= 0.80) -> DDUP_REVIEW
    - DQA warning but otherwise clean -> PENDING_PROMOTION (NSR Unit review)
    - Fully clean + walk-in channel + (positive IDV when NIN present)
      -> auto-promote per AC-DIH-FT-AUTO and return the PROMOTED stage.
    - Fully clean otherwise -> PENDING_PROMOTION.

    Idempotent on already-terminal states (PROMOTED / REJECTED / QUARANTINED).
    """
    stage = StageRecord.objects.select_for_update().get(pk=stage.pk)
    terminal = {StageRecordState.PROMOTED, StageRecordState.REJECTED, StageRecordState.QUARANTINED}
    if stage.state in terminal:
        return stage

    payload = stage.canonical_payload or {}

    # 1. DQA — runs over household-level + each member. Stage id flows
    # into the DqaResult record_ids so the violations dashboard can
    # aggregate by rule and trace back to the originating stage.
    dqa_summary = _evaluate_dqa(payload, stage_id=stage.provisional_registry_id)
    stage.dqa_summary = dqa_summary

    if dqa_summary["blocking_failures"]:
        stage.state = StageRecordState.QUALITY_FAILED
        stage.save(update_fields=["state", "dqa_summary", "updated_at"])
        _emit_audit("evaluate", "stage_record", stage.id, actor=actor,
                    reason="dqa-blocking", field_changes={"dqa": dqa_summary})
        return stage

    # 2. IDV — only when a NIN is in the payload.
    nin = _first_member_nin(payload)
    idv_status = ""
    if nin:
        try:
            idv = verify_nin(nin)
            idv_status = idv.get("status", "unknown")
        except NiraError:
            idv_status = "service_unavailable"
        stage.idv_outcome = idv_status
        if idv_status in ("service_unavailable", "mismatch", "no_match", "bad_format"):
            stage.state = StageRecordState.IDV_PENDING
            stage.save(update_fields=["state", "dqa_summary", "idv_outcome", "updated_at"])
            _emit_audit("verify", "stage_record", stage.id, actor=actor,
                        reason=f"idv-{idv_status}",
                        field_changes={"idv_outcome": idv_status})
            return stage

    # 3. DDUP — tier 1 NIN-exact against registry.
    candidates = _discover_stage_candidates(payload)
    stage.ddup_candidates = candidates
    has_strong_candidate = any(c["score"] >= 0.80 for c in candidates)
    if has_strong_candidate:
        stage.state = StageRecordState.DDUP_REVIEW
        stage.save(update_fields=[
            "state", "dqa_summary", "idv_outcome", "ddup_candidates", "updated_at",
        ])
        _emit_audit("discover", "stage_record", stage.id, actor=actor,
                    reason="ddup-candidate", field_changes={"candidates": candidates})
        return stage

    # 4. Fast-track auto-promote (AC-DIH-FT-AUTO): zero DQA warnings AND
    #    zero blocking AND no DDUP candidate >= 0.80 AND positive IDV (where
    #    NIN supplied) AND channel is CAPI/Web.
    source_kind = stage.connector_run.connector.source_system.kind
    walkin = source_kind in _WALKIN_KINDS
    idv_ok = (not nin) or idv_status == "match"
    if (allow_fast_track and walkin and idv_ok
            and not dqa_summary["warnings"] and not has_strong_candidate):
        stage.save(update_fields=[
            "dqa_summary", "idv_outcome", "ddup_candidates", "updated_at",
        ])
        promote_stage_record(stage, actor=actor, action=PromotionAction.AUTO_PROMOTE,
                             reason="fast-track auto-promote (AC-DIH-FT-AUTO)")
        promoted = StageRecord.objects.get(pk=stage.pk)
        # 1% sample to NSR Unit audit queue. Deterministic + idempotent.
        if _is_sampled(promoted.id):
            FastTrackAuditSample.objects.get_or_create(
                stage_record=promoted,
                defaults={"household_id": promoted.promoted_household_id or ""},
            )
            _emit_audit("sample", "fast_track_promotion", promoted.id,
                        actor=actor, reason="ac-dih-ft-auto 1% sample",
                        field_changes={"household_id": promoted.promoted_household_id})
        return promoted

    # 5. Default: queue for NSR Unit review.
    stage.state = StageRecordState.PENDING_PROMOTION
    stage.save(update_fields=[
        "state", "dqa_summary", "idv_outcome", "ddup_candidates", "updated_at",
    ])
    _emit_audit("route", "stage_record", stage.id, actor=actor,
                reason="pending-nsr-review",
                field_changes={
                    "dqa_warning_count": len(dqa_summary["warnings"]),
                    "ddup_candidate_count": len(candidates),
                    "idv": idv_status,
                })
    return stage


# ---------------------------------------------------------------------------
# Walk-in submission (Slice A — US-S23-WALKIN)
#
# Operator captures a household at a parish office via the wizard;
# submit_walk_in_capture lands the canonical payload as a StageRecord
# under the dedicated PARISH-WALKIN source system. The provisional
# Registry ID returned here is THE Registry ID once promoted.

PARISH_WALKIN_SOURCE_CODE = "PARISH-WALKIN"
PARISH_WALKIN_CONNECTOR_NAME = "parish-walkin"


@transaction.atomic
def submit_walk_in_capture(
    payload: dict,
    *,
    actor: str,
) -> StageRecord:
    """Atomic write-path for parish-office captures.

    Opens a tiny one-record ConnectorRun under the seeded parish
    walk-in connector (so the lineage chain stays uniform with the
    bulk connectors), lands the raw payload, stages it.

    Returns the StageRecord; caller reads
    .provisional_registry_id for the receipt slip.
    """
    if not isinstance(payload, dict) or not payload:
        raise DihError("payload must be a non-empty object")
    if not actor:
        raise DihError("actor is required")

    try:
        connector = (
            Connector.objects
            .select_related("source_system")
            .get(
                source_system__code=PARISH_WALKIN_SOURCE_CODE,
                name=PARISH_WALKIN_CONNECTOR_NAME,
            )
        )
    except Connector.DoesNotExist as e:
        raise DihError(
            "parish walk-in connector not seeded — run migration "
            "ingestion_hub.0004_seed_parish_walkin_source",
        ) from e

    run = start_connector_run(connector, actor=actor)
    landing = land_payload(
        run, payload,
        source_reference=f"walkin:{actor}",
    )
    stage = stage_from_landing(landing, canonical_payload=payload)

    # The walk-in form already ran client-side DQA + collected consent,
    # so the run is one-shot. Close it immediately to keep
    # ConnectorRun.is_running() honest.
    ConnectorRun.objects.filter(pk=run.pk).update(
        status=ConnectorRunStatus.SUCCEEDED,
        finished_at=timezone.now(),
    )

    _emit_audit(
        "create", "stage_record", stage.id,
        actor=actor,
        reason=f"parish walk-in submission · provisional={stage.provisional_registry_id}",
    )
    return stage


# ---------------------------------------------------------------------------
# Quarantine (Slice B — archive workflow for quality_failed records)

@transaction.atomic
def quarantine_stage_record(
    stage: StageRecord,
    *,
    actor: str,
    reason: str,
) -> StageRecord:
    """Move a quality_failed StageRecord into the archive
    (state=quarantined). One-way transition — quarantined records
    cannot be promoted into the registry.

    Required when a record's quality issues are unfixable (e.g.
    irreconcilable duplicates, fraudulent submissions, lost original
    forms). The audit trail preserves the operator's reason.
    """
    if stage.state != StageRecordState.QUALITY_FAILED:
        raise DihError(
            f"only quality_failed records can be quarantined "
            f"(got {stage.state})",
        )
    if not actor:
        raise DihError("actor is required to quarantine a record")
    if not reason or not reason.strip():
        raise DihError("reason is required to quarantine a record")

    before = stage.state
    stage.state = StageRecordState.QUARANTINED
    stage.rejected_reason = reason.strip()  # reuse existing column
    stage.rejected_at = timezone.now()
    stage.rejected_by = actor
    stage.save(update_fields=[
        "state", "rejected_reason", "rejected_at", "rejected_by", "updated_at",
    ])
    _emit_audit(
        "quarantine", "stage_record", stage.id,
        actor=actor,
        reason=reason.strip(),
        field_changes={"state_before": before, "state_after": stage.state},
    )
    return stage


# ---------------------------------------------------------------------------
# In-place correction of a StageRecord (US-S23-DIH-EDIT)
#
# Whitelist of dotted paths into canonical_payload that NSR Unit
# operators may correct without round-tripping the citizen. Three
# whole categories are deliberately OUT:
#   - NIN / nin_last4 / nin_hash    (legal identity — re-capture only)
#   - geographic.*                  (chain integrity — re-capture only)
#   - consent / urban_rural         (legal + PMT semantics)
#
# Paths support `members.<int>.<field>` for per-row corrections.

EDITABLE_PATH_PATTERNS = (
    _re.compile(r"^gps_(?:lat|lng|accuracy_m)$"),
    _re.compile(
        r"^members\.\d+\.(?:surname|first_name|other_name|date_of_birth|age_years|telephone_1|telephone_2)$",
    ),
)


class StageEditError(Exception):
    """The edit is forbidden under current state or path policy."""


def _path_editable(path: str) -> bool:
    return any(p.match(path) for p in EDITABLE_PATH_PATTERNS)


def _set_dotted(node: dict, path: str, value):
    """Walk node along the dotted path and write `value` at the leaf.
    Numeric segments index an existing list element (will NOT extend
    lists). Object segments may create missing leaf keys — the
    whitelist already restricts which keys are reachable, and
    operators legitimately add missing phone numbers / DoBs that
    weren't captured originally."""
    parts = path.split(".")
    cur = node
    for i, part in enumerate(parts):
        last = (i == len(parts) - 1)
        if part.isdigit():
            idx = int(part)
            if not isinstance(cur, list) or idx >= len(cur):
                raise StageEditError(
                    f"path {path!r} indexes a missing array element",
                )
            if last:
                cur[idx] = value
                return
            cur = cur[idx]
        else:
            if not isinstance(cur, dict):
                raise StageEditError(
                    f"path {path!r} traverses a non-object node",
                )
            if last:
                cur[part] = value
                return
            if part not in cur:
                # Create the intermediate container so e.g.
                # `housing.dwelling.roof_material` works when the
                # `dwelling` block was empty.
                cur[part] = {}
            cur = cur[part]


def _get_dotted(node, path: str, default=None):
    parts = path.split(".")
    cur = node
    for part in parts:
        if isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if idx >= len(cur):
                return default
            cur = cur[idx]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


_EDITABLE_STATES = frozenset({
    StageRecordState.PROVISIONAL,
    StageRecordState.QUALITY_FAILED,
    StageRecordState.DDUP_REVIEW,
})


@transaction.atomic
def edit_stage_record(
    stage: StageRecord,
    *,
    field_changes: dict,
    actor: str,
    reason: str,
    rerun_dqa: bool = True,
) -> StageRecord:
    """Apply sparse corrections to a StageRecord's canonical_payload.

    `field_changes` is a dotted-path → new-value dict. Every path
    must match EDITABLE_PATH_PATTERNS — anything outside that
    whitelist is rejected before we touch the payload, so a bad
    request can never persist.

    On success:
      - canonical_payload mutated (deep copy first; transaction.atomic
        gives us rollback on any later raise).
      - last_edited_by / last_edited_at stamped.
      - One AuditEvent per changed field with before/after snapshots.
      - DQA re-runs against the new payload (caller can disable with
        `rerun_dqa=False` for unit tests).

    `promote_stage_record` reads last_edited_by to block the same
    operator from promoting a record they just edited
    (AC-DIH-EDIT-NO-SELF-APPROVE).
    """
    if stage.state not in _EDITABLE_STATES:
        raise StageEditError(
            f"only provisional / quality_failed / ddup_review stage "
            f"records can be edited (got {stage.state})",
        )
    if not actor:
        raise StageEditError("actor is required")
    if not reason or not reason.strip():
        raise StageEditError("reason is required")
    if not isinstance(field_changes, dict) or not field_changes:
        raise StageEditError("field_changes must be a non-empty object")

    illegal = [p for p in field_changes if not _path_editable(p)]
    if illegal:
        raise StageEditError(
            "paths outside the editable whitelist: " + ", ".join(sorted(illegal)),
        )

    import copy
    new_payload = copy.deepcopy(stage.canonical_payload or {})
    diffs = []
    for path, new_val in field_changes.items():
        before = _get_dotted(new_payload, path)
        _set_dotted(new_payload, path, new_val)
        diffs.append({"path": path, "before": before, "after": new_val})

    stage.canonical_payload = new_payload
    stage.last_edited_by = actor
    stage.last_edited_at = timezone.now()
    stage.save(update_fields=[
        "canonical_payload", "last_edited_by", "last_edited_at", "updated_at",
    ])

    for d in diffs:
        _emit_audit(
            "edit", "stage_record", stage.id,
            actor=actor,
            reason=reason.strip(),
            field_changes={"path": d["path"], "before": d["before"], "after": d["after"]},
        )

    if rerun_dqa:
        # Re-run DQA against the new payload. Reuse the existing
        # evaluator; the DDUP + IDV gates do not re-run because their
        # inputs (NIN, geo) are not in the editable whitelist.
        try:
            results = dqa_evaluate_all(
                new_payload,
                record_type="stage_record",
                record_id=stage.id,
            )
            blocking = [r.rule_id for r in results if not r.passed and r.severity == "blocking"]
            warnings = [r.rule_id for r in results if not r.passed and r.severity == "warning"]
            info = [r.rule_id for r in results if not r.passed and r.severity == "info"]
            stage.dqa_summary = {
                "blocking_failures": blocking,
                "warnings": warnings,
                "info": info,
                "rerun_after_edit": True,
            }
            # If the edit cleared every blocking failure, the record
            # automatically returns to PROVISIONAL so the queue treats
            # it as actionable again.
            if stage.state == StageRecordState.QUALITY_FAILED and not blocking:
                stage.state = StageRecordState.PROVISIONAL
            stage.save(update_fields=["dqa_summary", "state", "updated_at"])
        except Exception as exc:  # noqa: BLE001 — DQA must not fail the edit
            log.warning(
                "dqa rerun after edit failed: %s", exc,
                extra={"stage_id": stage.id},
            )

    return stage


# ---------------------------------------------------------------------------
# Trigger a connector pull (US-S11-021)
#
# Operator-initiated Kobo pull from the System Admin > Connector runs tab.
# Lifted out of `admin_credentials.pull_kobo_submissions_action` so the
# admin action and the new POST /source-systems/{id}/trigger-run/ endpoint
# share one implementation. Behaviour parity with the admin action is the
# acceptance gate — see apps/ingestion_hub/tests.py.

# Submissions landed per click. The admin action used the same cap;
# moved here so the constant lives next to the implementation. Scheduled
# pulls (future Celery beat) won't apply it.
TRIGGER_PULL_BATCH_CAP = 50


class TriggerError(DihError):
    """Caller-facing pre-condition failure for trigger_connector_pull
    (concurrency, kind, missing connector wiring). Distinct subclass so
    the API layer can map these to 4xx without catching every DihError."""


def resolve_pinned_form_uid(source) -> str | None:
    """Return the Kobo form_uid that the trigger would default to for
    this SourceSystem (US-S11-025 pin), or None if no staged-success
    run exists yet.

    Same query the trigger uses; lifted out so the /forms/ endpoint
    (US-S11-026) can mark the recommended form on the form-picker
    response and the modal can default the dropdown to it. Before
    this, the modal defaulted to forms[0] regardless of history,
    which meant the operator visually saw the legacy form selected
    even when the server was ready to pin the correct one.
    """
    last_good_run = (
        ConnectorRun.objects
        .filter(
            connector__source_system=source,
            records_staged__gt=0,
        )
        .select_related("connector")
        .order_by("-started_at")
        .first()
    )
    if last_good_run is None:
        return None
    return last_good_run.connector.config.get("kobo_form_uid") or None


def trigger_connector_pull(
    source,
    *,
    actor: str,
    dry_run: bool = False,
    batch_cap: int = TRIGGER_PULL_BATCH_CAP,
    form_uid: str | None = None,
) -> dict:
    """Pull submissions for `source` and return a summary dict.

    Kobo-only for v1 — non-Kobo kinds raise TriggerError. The shared
    pull body is otherwise the same as the admin action (US-S11-014):
    open a ConnectorRun, list deployed forms, pull the chosen one, land
    + process each row, geo-backfill, close the run.

    Form selection precedence (US-S11-022 + US-S11-025):
      1. Explicit `form_uid` from the caller — wins if it appears in
         the upstream's list_forms output. TriggerError if it doesn't.
      2. The `kobo_form_uid` from the Connector of the most recent
         ConnectorRun on this source with records_staged > 0. A run
         where everything quarantined at canonicalize CANNOT pin
         itself as the default — that was the 2026-05-26 trap where
         the legacy v1 form kept being re-defaulted after a 100%-
         quarantine pull.
      3. The first DEPLOYED form returned by list_forms.

    The chosen form_uid is still persisted back to Connector.config so
    operators reading the admin can see what form a Connector typically
    pulls; but it's the run-outcome history, not the config field,
    that drives the default.

    dry_run=True: the run is opened as run_type=TEST, list_forms is
    called (so credentials get exercised against the upstream), and
    pull_submissions is iterated for metadata only — no RawLanding is
    written and no canonicalize/process runs. The run finishes
    SUCCEEDED with a note like "dry-run: would have landed N row(s)".

    Concurrency guard: if a PENDING or RUNNING ConnectorRun already
    exists for the source, raise TriggerError. Two operators clicking
    "Run" at the same time should not produce two overlapping pulls.
    """
    from .connection_test import CredentialMissingError, credentials_for
    from .connectors.base import get_connector
    from .geo_backfill import backfill_missing_geo_from_stages
    from .models import Connector as ConnectorModel
    from .models import ConnectorRunType, SourceSystemKind

    if source.kind != SourceSystemKind.KOBO:
        raise TriggerError(
            f"{source.code}: only Kobo sources can be triggered today "
            f"(got kind={source.kind})",
        )

    # Concurrency guard. start_connector_run() already opens the new
    # run inside a transaction, so this read is a best-effort precheck
    # — two simultaneous triggers can still race the DPA check. The
    # DB-level guarantee is the ConnectorRun PK uniqueness; the audit
    # trail captures both.
    busy = ConnectorRun.objects.filter(
        connector__source_system=source,
        status__in=(ConnectorRunStatus.PENDING, ConnectorRunStatus.RUNNING),
    ).exists()
    if busy:
        raise TriggerError(
            f"{source.code}: a run is already in progress — wait for it "
            "to finish before triggering another",
        )

    connector_impl = get_connector(source.code)
    if connector_impl is None or connector_impl.pull_submissions is None:
        raise TriggerError(
            f"{source.code}: no live connector registered",
        )
    try:
        creds = credentials_for(source)
    except CredentialMissingError as exc:
        raise TriggerError(f"{source.code}: {exc}") from exc

    try:
        forms = [f for f in connector_impl.list_forms(creds) if f["deployed"]]
    except Exception as exc:  # noqa: BLE001 — surface upstream errors
        raise TriggerError(
            f"{source.code}: list_forms failed: {exc}",
        ) from exc
    if not forms:
        raise TriggerError(
            f"{source.code}: no deployed forms — nothing to pull",
        )

    # Form selection — see docstring for the precedence chain. The
    # default-from-history branch (US-S11-025) walks ConnectorRuns
    # filtered to records_staged > 0 so a previous canonicalize-
    # failure run can't silently re-pin the wrong form. Before this,
    # any pull (regardless of outcome) updated Connector.config and
    # became the next default — which is how the legacy v1 form kept
    # winning after the 2026-05-26 incident even after the form-picker
    # landed.
    forms_by_uid = {f["uid"]: f for f in forms}
    if form_uid:
        if form_uid not in forms_by_uid:
            raise TriggerError(
                f"{source.code}: form_uid {form_uid!r} is not in the "
                f"deployed-forms list — available: "
                f"{sorted(forms_by_uid.keys())}",
            )
        form = forms_by_uid[form_uid]
    else:
        pinned_uid = resolve_pinned_form_uid(source)
        if pinned_uid and pinned_uid in forms_by_uid:
            form = forms_by_uid[pinned_uid]
        else:
            form = forms[0]

    connector_row, _ = ConnectorModel.objects.get_or_create(
        source_system=source, name=f"kobo-{form['uid']}",
        defaults={"config": {"kobo_form_uid": form["uid"]}},
    )
    # Pin the chosen form back to the Connector so next pull defaults
    # to it — even an explicit pick should persist as operator intent.
    if connector_row.config.get("kobo_form_uid") != form["uid"]:
        connector_row.config["kobo_form_uid"] = form["uid"]
        connector_row.save(update_fields=("config", "updated_at"))

    # start_connector_run() enforces AC-DIH-DPA-REQUIRED (raises
    # DihError). Surface that as TriggerError too so the caller has a
    # single exception type to handle.
    try:
        run = start_connector_run(connector_row, actor=actor)
    except DihError as exc:
        raise TriggerError(str(exc)) from exc

    if dry_run:
        # Mark the run as a TEST so dashboards keep dry-runs out of
        # promotion-latency aggregates (matches test_connection_action
        # behaviour).
        ConnectorRun.objects.filter(pk=run.pk).update(
            run_type=ConnectorRunType.TEST,
        )

    # US-S11-034: watermark + landing dedup. The watermark filters
    # Kobo to rows >= last_pulled_submission_time so we don't re-page
    # through everything; the landing-dedup catches the boundary row
    # (Kobo's filter is $gte, so the equal-timestamp row comes back)
    # plus any manual re-pull where the watermark didn't help.
    watermark = connector_row.config.get("last_pulled_submission_time") or None
    max_submission_time = watermark or ""

    landed = 0
    outcomes: dict[str, int] = {
        "staged": 0, "quarantined": 0, "error": 0, "skipped_duplicate": 0,
    }
    stage_states: dict[str, int] = {}
    try:
        for raw in connector_impl.pull_submissions(
            creds, form_id=form["uid"], since=watermark,
        ):
            if landed >= batch_cap:
                break
            sub_time = str(raw.get("_submission_time") or "")
            if sub_time and sub_time > max_submission_time:
                max_submission_time = sub_time
            if dry_run:
                # Don't land or process — we're just verifying creds +
                # row shape. Dry-run counts every row Kobo yields so
                # operators see the upstream backlog, dedup or not.
                landed += 1
                continue
            source_ref = str(raw.get("_id") or raw.get("_uuid") or "")
            if source_ref and RawLanding.objects.filter(
                connector_run__connector__source_system=source,
                source_reference=source_ref,
            ).exists():
                # Already landed this Kobo submission for this source.
                # Skip the entire chain — RawLanding through DDUP —
                # so a re-pull doesn't double up the queue.
                outcomes["skipped_duplicate"] += 1
                continue
            landing = land_payload(run, raw, source_reference=source_ref)
            landed += 1
            from .admin_credentials import _process_one_landing
            outcome, detail = _process_one_landing(
                landing, connector_impl, actor=actor,
            )
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            if outcome == "staged":
                stage_states[detail] = stage_states.get(detail, 0) + 1
    except Exception as exc:  # noqa: BLE001 — partial-run cleanup below
        ConnectorRun.objects.filter(pk=run.pk).update(
            status=ConnectorRunStatus.FAILED,
            finished_at=timezone.now(),
            note=f"pull failed after {landed} row(s): {exc}",
        )
        emit_audit(
            "trigger_failed", "connector_run", run.id, actor=actor,
            reason=f"{source.code}: {exc}",
        )
        raise TriggerError(
            f"{source.code}: pull failed after {landed} row(s): {exc}",
        ) from exc

    state_summary = (
        "; ".join(f"{s}={n}" for s, n in sorted(stage_states.items()))
        or "(none staged)"
    )

    geo_total = 0
    if not dry_run:
        run_stages = StageRecord.objects.filter(connector_run=run)
        geo_total = backfill_missing_geo_from_stages(run_stages).total_created
        # Persist the watermark only on a real pull — dry-runs don't
        # acknowledge the rows. If the upstream returned 0 rows the
        # watermark stays where it was.
        if max_submission_time and max_submission_time != watermark:
            connector_row.config["last_pulled_submission_time"] = max_submission_time
            connector_row.save(update_fields=("config", "updated_at"))

    skipped = outcomes.get("skipped_duplicate", 0)
    skipped_clause = f", skipped_duplicate={skipped}" if skipped else ""
    note = (
        f"dry-run: would have pulled {landed} row(s) from form "
        f"{form['uid']} ({form['name']})"
        if dry_run else
        f"pulled {landed} new row(s) from form {form['uid']} ({form['name']}); "
        f"staged={outcomes['staged']}, quarantined={outcomes['quarantined']}, "
        f"errors={outcomes['error']}{skipped_clause}; {state_summary}; "
        f"geo backfill: +{geo_total} GeographicUnit row(s)"
        + (f"; cap {batch_cap} hit" if landed >= batch_cap else "")
    )
    # Persist the per-outcome counters so the Connector runs
    # dashboard columns reflect reality. Before this, only
    # records_landed got incremented (by land_payload), so a pull
    # where canonicalize raised on every row would show landed=50
    # with quarantined=0 — actively misleading. records_staged
    # already tracks via stage_from_landing inside _process_one_landing
    # so it doesn't get touched here. F() so a post-run operator
    # reject (which also does +1 on records_rejected) doesn't get
    # clobbered — defensive even though the close is synchronous.
    ConnectorRun.objects.filter(pk=run.pk).update(
        status=ConnectorRunStatus.SUCCEEDED,
        finished_at=timezone.now(),
        note=note,
        records_quarantined=F("records_quarantined") + outcomes["quarantined"],
        records_rejected=F("records_rejected") + outcomes["error"],
    )

    return {
        "run_id": run.id,
        "source_code": source.code,
        "form_uid": form["uid"],
        "form_name": form["name"],
        "dry_run": dry_run,
        "landed": landed,
        "staged": outcomes["staged"],
        "quarantined": outcomes["quarantined"],
        "errored": outcomes["error"],
        "skipped_duplicate": outcomes.get("skipped_duplicate", 0),
        "stage_states": stage_states,
        "geo_backfill_created": geo_total,
        "batch_cap_hit": landed >= batch_cap,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Delete a ConnectorRun (US-S11-023)
#
# Operator-initiated cleanup of bad runs from the System Admin >
# Connector runs tab. Every FK pointing at ConnectorRun (and its
# StageRecord children) is `on_delete=PROTECT` per SAD §4.6, so a
# naked `.delete()` would always raise. This service walks the chain
# explicitly:
#
#   FastTrackAuditSample (OneToOne on StageRecord)
#   PromotionDecision    (FK to StageRecord)
#   Quarantine           (FK to ConnectorRun + RawLanding)
#   StageRecord          (FK to ConnectorRun + RawLanding)
#   RawLanding           (FK to ConnectorRun)
#   ConnectorRun
#
# It refuses to delete runs that have produced Households — even
# though Household.id is referenced from StageRecord.promoted_
# household_id as a plain CharField (no DB-level FK), deleting the
# StageRecord would orphan the audit-lineage chain documented in
# AC-DIH-LINEAGE.


class DeleteError(DihError):
    """A ConnectorRun cannot be safely deleted from the current state
    (still running, or has produced promoted Households)."""


@transaction.atomic
def delete_connector_run(
    run: ConnectorRun, *, actor: str, reason: str = "",
) -> dict:
    """Hard-delete a ConnectorRun + every dependent row, atomically.

    Pre-checks (any failure raises DeleteError):
      * run.status must not be PENDING or RUNNING — refuse to delete
        a run that's still in flight, since we'd race the worker.
      * run.records_promoted must be 0.
      * No StageRecord on this run may be in state=PROMOTED.

    Returns a counts dict so the audit trail (and the operator toast)
    can show exactly what was removed.
    """
    if run.status in (ConnectorRunStatus.PENDING, ConnectorRunStatus.RUNNING):
        raise DeleteError(
            f"run {run.id} is {run.status} — wait for it to finish "
            "(or mark stuck) before deleting",
        )
    if run.records_promoted > 0:
        raise DeleteError(
            f"run {run.id} promoted {run.records_promoted} record(s) — "
            "deleting it would orphan the Household lineage chain "
            "(AC-DIH-LINEAGE)",
        )
    promoted_stages = StageRecord.objects.filter(
        connector_run=run, state=StageRecordState.PROMOTED,
    )
    if promoted_stages.exists():
        raise DeleteError(
            f"run {run.id} has {promoted_stages.count()} promoted "
            "StageRecord(s) — refuse to delete (lineage)",
        )

    from .models import FastTrackAuditSample, PromotionDecision, Quarantine

    stage_ids = list(
        StageRecord.objects.filter(connector_run=run)
        .values_list("id", flat=True),
    )
    fast_track_deleted, _ = (
        FastTrackAuditSample.objects.filter(stage_record_id__in=stage_ids)
        .delete()
    )
    decisions_deleted, _ = (
        PromotionDecision.objects.filter(stage_record_id__in=stage_ids)
        .delete()
    )
    quarantine_deleted, _ = (
        Quarantine.objects.filter(connector_run=run).delete()
    )
    stages_deleted, _ = (
        StageRecord.objects.filter(connector_run=run).delete()
    )
    landings_deleted, _ = (
        RawLanding.objects.filter(connector_run=run).delete()
    )
    run_id = run.id
    source_code = (
        run.connector.source_system.code if run.connector_id else ""
    )
    run.delete()

    counts = {
        "deleted_run_id": run_id,
        "source_code": source_code,
        "fast_track_samples_deleted": fast_track_deleted,
        "promotion_decisions_deleted": decisions_deleted,
        "quarantine_rows_deleted": quarantine_deleted,
        "stage_records_deleted": stages_deleted,
        "raw_landings_deleted": landings_deleted,
    }
    emit_audit(
        "dih.connector.run_deleted", "connector_run", run_id,
        actor=actor,
        reason=reason or "no reason provided",
        field_changes=counts,
    )
    return counts
