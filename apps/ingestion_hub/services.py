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

from django.db import models, transaction
from django.db.models import F
from django.utils import timezone
from nsr_mis.common.fields import generate_ulid

from apps.data_management.models import Household, Member, NinStatus
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
        row = (
            GeographicUnit.objects
            .filter(level=level, code=code)
            .order_by("-effective_from")
            .first()
        )
        if row is None:
            raise DihError(f"geographic unit {level}={code} not found")
        return row

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
        )
        if nin:
            # NIN trio per ADR-0002 — populated via the canonical helpers so
            # the encrypted value, hash, and display suffix stay in lockstep.
            member_kwargs["nin_value"] = nin.encode("utf-8")
            member_kwargs["nin_hash"] = compute_nin_hash(nin)
            member_kwargs["nin_last4"] = compute_nin_last4(nin)
            member_kwargs["nin_status"] = NinStatus.HAS_CARD
        member = Member.objects.create(**member_kwargs)
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


def _evaluate_dqa(payload: dict) -> dict:
    """Run all ACTIVE DQA rules against the household-level dict and against
    each member dict. Returns a summary keyed by severity, suitable for
    storing in StageRecord.dqa_summary."""
    summary: dict[str, list[dict]] = {"blocking": [], "warning": [], "info": []}
    payload = payload or {}
    members = payload.get("members") or []

    def _record(evaluations, *, record_id: str) -> None:
        for ev in evaluations:
            if ev.passed:
                continue
            summary.setdefault(ev.rule.severity, []).append({
                "rule_id": ev.rule.rule_id,
                "rule_version": ev.rule.version,
                "record_id": record_id,
                "reason": ev.reason,
            })

    hh_payload = {k: v for k, v in payload.items() if k != "members"}
    _record(dqa_evaluate_all(hh_payload, record_type="household", record_id="staged"),
            record_id="staged")
    for m in members:
        line = str((m or {}).get("line_number", ""))
        _record(dqa_evaluate_all(m or {}, record_type="member", record_id=f"line-{line}"),
                record_id=f"line-{line}")

    return {
        "blocking_failures": summary["blocking"],
        "warnings": summary["warning"],
        "info": summary["info"],
    }


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

    # 1. DQA — runs over household-level + each member.
    dqa_summary = _evaluate_dqa(payload)
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
