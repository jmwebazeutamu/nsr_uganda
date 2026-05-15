"""DIH framework tests.

Covers Sprint 0 ACs that are wired end-to-end:
- AC-DIH-DPA-REQUIRED: connector run refuses without an active DPA
- AC-DIH-PROVISIONAL-ID: stage record gets a 26-char ULID
- AC-DIH-PROMOTE-ATOMIC: idempotent, single Household created with the
  provisional ID transferred to confirmed
- AC-DIH-REJECT-VOID: rejection writes reason and prevents promotion
- AC-DIH-AUDIT: promote and reject emit AuditEvent rows
- AC-DIH-LINEAGE: promoted Household traces back to ConnectorRun and
  SourceSystem
- AC-DIH-DQA-IN-STAGING + AC-DIH-IDV-PRE-PROMOTION + AC-DIH-DDUP-DISCOVERY:
  process_stage_record orchestrator routes the stage based on the gates.
- AC-DIH-FT-AUTO: clean walk-in fast-tracks to PROMOTED.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household, Member
from apps.dqa.models import DqaRule, RuleStatus, Severity
from apps.ingestion_hub.models import (
    Connector,
    ConnectorRun,
    DataProvisionAgreement,
    SourceSystem,
    SourceSystemKind,
    StageRecordState,
)
from apps.ingestion_hub.services import (
    DihError,
    land_payload,
    process_stage_record,
    promote_stage_record,
    reject_stage_record,
    stage_from_landing,
    start_connector_run,
)
from apps.reference_data.models import GeographicUnit
from apps.security.hashing import nin_hash
from apps.security.models import AuditEvent

# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def geo_codes(db):
    """7-level UBOS ladder; codes also referenced in the canonical payload."""
    codes = [
        ("region", "T-R"), ("sub_region", "T-SR"), ("district", "T-D"),
        ("county", "T-C"), ("sub_county", "T-SC"), ("parish", "T-P"),
        ("village", "T-V"),
    ]
    parent = None
    out = {}
    for level, code in codes:
        node = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent, effective_from=date(2026, 1, 1),
        )
        out[level] = code
        parent = node
    return out


@pytest.fixture
def source_with_dpa(db):
    src = SourceSystem.objects.create(code="KOBO-PILOT", name="Kobo pilot",
                                      kind=SourceSystemKind.KOBO)
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-KOBO-1",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    return src


@pytest.fixture
def source_no_dpa(db):
    return SourceSystem.objects.create(code="UBOS-BULK", name="UBOS bulk",
                                       kind=SourceSystemKind.UBOS)


@pytest.fixture
def connector(db, source_with_dpa):
    return Connector.objects.create(source_system=source_with_dpa, name="kobo-pilot")


def _payload(geo: dict, *, head_first_name="James") -> dict:
    return {
        "geographic": geo,
        "urban_rural": "rural",
        "address_narrative": "Test homestead",
        "gps_lat": "1.234567", "gps_lng": "33.000000", "gps_accuracy_m": "5.00",
        "members": [
            {"line_number": 1, "surname": "Okot", "first_name": head_first_name,
             "sex": "M", "relationship_to_head": "01", "is_head": True},
            {"line_number": 2, "surname": "Okot", "first_name": "Mary",
             "sex": "F", "relationship_to_head": "02"},
        ],
    }


# --- AC-DIH-DPA-REQUIRED ----------------------------------------------------

class TestDPARequired:
    def test_run_refuses_without_active_dpa(self, db, source_no_dpa):
        c = Connector.objects.create(source_system=source_no_dpa, name="ubos")
        with pytest.raises(DihError, match="DPA"):
            start_connector_run(c)

    def test_run_proceeds_with_active_dpa(self, connector):
        run = start_connector_run(connector)
        assert run.connector_id == connector.id

    def test_run_refuses_with_expired_dpa(self, db, source_with_dpa):
        DataProvisionAgreement.objects.update(valid_to=date(2025, 12, 31))
        c = Connector.objects.create(source_system=source_with_dpa, name="kobo-expired")
        with pytest.raises(DihError, match="DPA"):
            start_connector_run(c)


# --- AC-DIH-PROVISIONAL-ID --------------------------------------------------

class TestProvisionalId:
    def test_stage_record_has_ulid_provisional_id(self, connector, geo_codes):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        assert len(stage.provisional_registry_id) == 26
        assert stage.state == StageRecordState.PROVISIONAL
        assert stage.connector_run_id == run.id
        assert stage.raw_landing_id == landing.id


# --- AC-DIH-PROMOTE-ATOMIC + AC-DIH-LINEAGE --------------------------------

class TestPromoteAtomic:
    def test_promote_transfers_id_to_confirmed(self, connector, geo_codes):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        provisional_id = stage.provisional_registry_id

        hh = promote_stage_record(stage, actor="reviewer-1")
        stage.refresh_from_db()

        assert hh.id == provisional_id  # AC-DIH-PROVISIONAL-ID transfer
        assert stage.state == StageRecordState.PROMOTED
        assert stage.promoted_household_id == hh.id
        assert stage.promoted_at is not None
        # Lineage: Household -> StageRecord -> ConnectorRun -> SourceSystem
        # is observable through the StageRecord that records all three FKs.
        assert stage.connector_run.connector.source_system_id == connector.source_system_id

    def test_promote_creates_members(self, connector, geo_codes):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        hh = promote_stage_record(stage, actor="reviewer-1")

        members = list(hh.members.order_by("line_number"))
        assert len(members) == 2
        assert hh.head_member_id == members[0].id  # is_head=True on line 1

    def test_promote_is_idempotent_on_replay(self, connector, geo_codes):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        hh1 = promote_stage_record(stage, actor="reviewer-1")
        hh2 = promote_stage_record(stage, actor="reviewer-1")
        assert hh1.id == hh2.id
        assert Household.objects.filter(id=hh1.id).count() == 1


# --- AC-DIH-REJECT-VOID -----------------------------------------------------

class TestRejectVoid:
    def test_reject_voids_provisional_id(self, connector, geo_codes):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))

        reject_stage_record(stage, actor="reviewer-1", reason="duplicate of existing household")
        stage.refresh_from_db()
        assert stage.state == StageRecordState.REJECTED
        assert stage.rejected_reason == "duplicate of existing household"
        assert not Household.objects.filter(id=stage.provisional_registry_id).exists()

    def test_cannot_reject_without_reason(self, connector, geo_codes):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        with pytest.raises(DihError, match="reason"):
            reject_stage_record(stage, actor="reviewer-1", reason="")

    def test_cannot_promote_after_reject(self, connector, geo_codes):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        reject_stage_record(stage, actor="reviewer-1", reason="bad")
        with pytest.raises(DihError, match="rejected"):
            promote_stage_record(stage, actor="reviewer-1")


# --- AC-DIH-AUDIT -----------------------------------------------------------

class TestAuditTrail:
    def test_promote_emits_audit_event(self, connector, geo_codes):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        before = AuditEvent.objects.filter(action="promote").count()
        promote_stage_record(stage, actor="reviewer-1", reason="clean walk-in")
        stage.refresh_from_db()
        events = AuditEvent.objects.filter(action="promote").order_by("-occurred_at")
        assert events.count() == before + 1
        last = events.first()
        assert last.entity_id == stage.promoted_household_id
        assert last.field_changes["connector_run_id"] == stage.connector_run_id

    def test_reject_emits_audit_event(self, connector, geo_codes):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        before = AuditEvent.objects.filter(action="reject").count()
        reject_stage_record(stage, actor="reviewer-1", reason="oops")
        assert AuditEvent.objects.filter(action="reject").count() == before + 1


# --- process_stage_record orchestrator -------------------------------------

@pytest.fixture
def dqa_blocking_name_rule(db):
    """Active blocking DQA rule: every member must have a surname."""
    return DqaRule.objects.create(
        rule_id="TEST-MEMBER-SURNAME",
        version=1, description="surname required",
        severity=Severity.BLOCKING,
        applicability_filter={"entity": "member"},
        expression={"field": "surname", "op": "not_null"},
        error_message_template="surname missing",
        status=RuleStatus.ACTIVE,
        author="test-author", approved_by="test-approver",
    )


def _make_stage(connector, geo_codes, *, payload=None):
    run = start_connector_run(connector)
    pl = payload or _payload(geo_codes)
    landing = land_payload(run, pl)
    return stage_from_landing(landing, canonical_payload=pl)


class TestProcessOrchestrator:
    def test_dqa_blocking_routes_to_quality_failed(self, connector, geo_codes, dqa_blocking_name_rule):
        payload = _payload(geo_codes)
        payload["members"][0]["surname"] = ""  # triggers the blocking rule
        stage = _make_stage(connector, geo_codes, payload=payload)
        process_stage_record(stage, actor="orch")
        stage.refresh_from_db()
        assert stage.state == StageRecordState.QUALITY_FAILED
        assert stage.dqa_summary["blocking_failures"]

    def test_idv_service_unavailable_routes_to_idv_pending(self, connector, geo_codes,
                                                           dqa_blocking_name_rule):
        payload = _payload(geo_codes)
        payload["members"][0]["nin"] = "CM1234567890SU"  # mock raises NiraError
        stage = _make_stage(connector, geo_codes, payload=payload)
        process_stage_record(stage, actor="orch")
        stage.refresh_from_db()
        assert stage.state == StageRecordState.IDV_PENDING
        assert stage.idv_outcome == "service_unavailable"

    def test_idv_no_match_routes_to_idv_pending(self, connector, geo_codes, dqa_blocking_name_rule):
        payload = _payload(geo_codes)
        payload["members"][0]["nin"] = "CM1234567890NM"
        stage = _make_stage(connector, geo_codes, payload=payload)
        process_stage_record(stage, actor="orch")
        stage.refresh_from_db()
        assert stage.state == StageRecordState.IDV_PENDING
        assert stage.idv_outcome == "no_match"

    def test_ddup_strong_candidate_routes_to_ddup_review(self, connector, geo_codes,
                                                        dqa_blocking_name_rule):
        # Plant an existing Member with a known NIN hash; staged payload uses
        # the same NIN -> tier1 NIN-exact hits. Need a Household to satisfy
        # the FK; build one inline via promote().
        seed_stage = _make_stage(connector, geo_codes)
        seed_hh = promote_stage_record(seed_stage, actor="seed")
        nin = "CM1234567890AB"
        Member.objects.create(household=seed_hh, line_number=99, surname="Existing",
                              first_name="One", sex="M", nin_hash=nin_hash(nin))
        payload = _payload(geo_codes)
        payload["members"][0]["nin"] = nin
        stage = _make_stage(connector, geo_codes, payload=payload)
        process_stage_record(stage, actor="orch")
        stage.refresh_from_db()
        assert stage.state == StageRecordState.DDUP_REVIEW
        assert stage.ddup_candidates
        assert stage.ddup_candidates[0]["score"] == 1.0

    def test_clean_walkin_auto_promotes(self, connector, geo_codes, dqa_blocking_name_rule):
        # KOBO-PILOT fixture uses kind=kobo, NOT a walk-in. Swap to web.
        connector.source_system.kind = SourceSystemKind.WEB
        connector.source_system.save()
        stage = _make_stage(connector, geo_codes)
        process_stage_record(stage, actor="orch")
        stage.refresh_from_db()
        assert stage.state == StageRecordState.PROMOTED
        assert stage.promoted_household_id

    def test_clean_non_walkin_pends_for_review(self, connector, geo_codes, dqa_blocking_name_rule):
        # Default fixture connector is KOBO (not walk-in) — should route to
        # PENDING_PROMOTION, not auto-promote.
        stage = _make_stage(connector, geo_codes)
        process_stage_record(stage, actor="orch")
        stage.refresh_from_db()
        assert stage.state == StageRecordState.PENDING_PROMOTION

    def test_explicit_allow_fast_track_false_pends_for_review(self, connector, geo_codes,
                                                              dqa_blocking_name_rule):
        connector.source_system.kind = SourceSystemKind.WEB
        connector.source_system.save()
        stage = _make_stage(connector, geo_codes)
        process_stage_record(stage, actor="orch", allow_fast_track=False)
        stage.refresh_from_db()
        assert stage.state == StageRecordState.PENDING_PROMOTION

    def test_process_is_idempotent_on_promoted(self, connector, geo_codes, dqa_blocking_name_rule):
        stage = _make_stage(connector, geo_codes)
        promote_stage_record(stage, actor="op")  # already PROMOTED
        result = process_stage_record(stage, actor="orch")
        result.refresh_from_db()
        assert result.state == StageRecordState.PROMOTED  # unchanged


# --- AC-DIH-FT-AUTO 1% audit sampling -------------------------------------

class TestFastTrackSampling:
    def _walkin_connector(self, connector):
        connector.source_system.kind = SourceSystemKind.WEB
        connector.source_system.save()
        return connector

    def test_sample_deterministic_on_stage_id(self, connector, geo_codes, dqa_blocking_name_rule):
        from apps.ingestion_hub.models import FastTrackAuditSample
        from apps.ingestion_hub.services import _is_sampled

        c = self._walkin_connector(connector)

        # Build enough stages that at least one ULID lands in the 1% bucket.
        # The function is deterministic, so we sample 200 promoted stage ids
        # and assert: (a) every id with _is_sampled(id)==True has a sample row;
        # (b) every id with _is_sampled(id)==False has no sample row.
        promoted_ids = []
        for _ in range(200):
            stage = _make_stage(c, geo_codes)
            process_stage_record(stage, actor="orch")
            stage.refresh_from_db()
            assert stage.state == StageRecordState.PROMOTED
            promoted_ids.append(stage.id)

        for sid in promoted_ids:
            if _is_sampled(sid):
                assert FastTrackAuditSample.objects.filter(stage_record_id=sid).exists(), \
                    f"expected sample for {sid}"
            else:
                assert not FastTrackAuditSample.objects.filter(stage_record_id=sid).exists(), \
                    f"did not expect sample for {sid}"

    def test_sample_is_idempotent_across_process_re_entry(self, connector, geo_codes,
                                                          dqa_blocking_name_rule):
        from apps.ingestion_hub.models import FastTrackAuditSample
        from apps.ingestion_hub.services import _is_sampled

        c = self._walkin_connector(connector)
        # Find a stage id that will be sampled. The function is deterministic
        # on the ULID tail; just iterate until we hit one.
        stage = None
        for _ in range(500):
            candidate = _make_stage(c, geo_codes)
            if _is_sampled(candidate.id):
                stage = candidate
                break
        assert stage is not None, "could not find a stage id that hits the 1% bucket"

        process_stage_record(stage, actor="orch")
        process_stage_record(stage, actor="orch")  # second call hits the PROMOTED idempotent path
        assert FastTrackAuditSample.objects.filter(stage_record_id=stage.id).count() == 1

    def test_non_fast_track_never_samples(self, connector, geo_codes, dqa_blocking_name_rule):
        # Default fixture is KOBO (not walk-in) -> routes to PENDING_PROMOTION,
        # so no auto-promote and no sample, regardless of the stage id bucket.
        from apps.ingestion_hub.models import FastTrackAuditSample

        for _ in range(50):
            stage = _make_stage(connector, geo_codes)
            process_stage_record(stage, actor="orch")
        assert FastTrackAuditSample.objects.count() == 0


# --- US-S10-005 — ConnectorRun admin enhancements -------------------------


class TestConnectorRunAdmin:
    """list_display shows status badge + duration; bulk action
    "mark stuck FAILED" only acts on RUNNING rows older than the
    6-hour threshold."""

    @pytest.fixture
    def admin_client(self, db, django_user_model):
        from django.test import Client
        u = django_user_model.objects.create_user(
            username="ops", password="p", is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        return c

    def _running_run(self, hours_ago: int):
        from datetime import date, timedelta

        from django.utils import timezone

        from apps.ingestion_hub.models import (
            Connector,
            ConnectorRunStatus,
            DataProvisionAgreement,
            SourceSystem,
            SourceSystemKind,
        )
        src = SourceSystem.objects.create(
            code=f"SRC-{hours_ago}", name="x", kind=SourceSystemKind.WEB,
        )
        DataProvisionAgreement.objects.create(
            source_system=src, reference=f"DPA-{hours_ago}",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        )
        conn = Connector.objects.create(source_system=src, name="c")
        run = ConnectorRun.objects.create(
            connector=conn, status=ConnectorRunStatus.RUNNING,
        )
        ConnectorRun.objects.filter(pk=run.pk).update(
            started_at=timezone.now() - timedelta(hours=hours_ago),
        )
        run.refresh_from_db()
        return run

    def test_status_badge_marks_stuck_for_long_running(self, db):
        from apps.ingestion_hub.admin import ConnectorRunAdmin
        run = self._running_run(hours_ago=12)
        html = str(ConnectorRunAdmin(ConnectorRun, admin_site=None).status_badge(run))
        assert "STUCK" in html

    def test_status_badge_does_not_mark_recent_running(self, db):
        from apps.ingestion_hub.admin import ConnectorRunAdmin
        run = self._running_run(hours_ago=1)
        html = str(ConnectorRunAdmin(ConnectorRun, admin_site=None).status_badge(run))
        assert "STUCK" not in html
        # Falls through to the normal "running" colour.
        assert "running" in html

    def test_duration_display_for_running_row(self, db):
        from apps.ingestion_hub.admin import ConnectorRunAdmin
        run = self._running_run(hours_ago=2)
        s = ConnectorRunAdmin(ConnectorRun, admin_site=None).duration_display(run)
        assert "running" in s

    def test_bulk_mark_stuck_only_affects_old_running(self, admin_client):
        from apps.ingestion_hub.models import ConnectorRunStatus
        stuck = self._running_run(hours_ago=12)
        fresh = self._running_run(hours_ago=1)
        admin_client.post("/admin/ingestion_hub/connectorrun/", data={
            "action": "mark_stuck_runs_failed",
            "_selected_action": [stuck.pk, fresh.pk],
        })
        stuck.refresh_from_db()
        fresh.refresh_from_db()
        assert stuck.status == ConnectorRunStatus.FAILED
        assert stuck.finished_at is not None
        assert "stuck since" in stuck.note
        # Fresh run untouched.
        assert fresh.status == ConnectorRunStatus.RUNNING
        assert fresh.finished_at is None
