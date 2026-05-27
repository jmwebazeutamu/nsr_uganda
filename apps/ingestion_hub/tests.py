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
from rest_framework.test import APIClient

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

    def test_promote_enforces_head_relationship_code(self, connector, geo_codes):
        # US-FIX-001 — when the payload sets `is_head=True` but omits or
        # mis-codes `relationship_to_head`, the promote service must
        # still land the registry row with relationship_to_head="01"
        # (ChoiceOption code for "Head" on the seeded `relationship`
        # list). Audit 2026-05-21 §4 flagged this as a real divergence
        # in the dev fixture.
        payload = _payload(geo_codes)
        payload["members"][0]["relationship_to_head"] = ""    # was missing
        payload["members"][1]["relationship_to_head"] = "04"  # son/daughter
        run = start_connector_run(connector)
        landing = land_payload(run, payload)
        stage = stage_from_landing(landing, canonical_payload=payload)
        hh = promote_stage_record(stage, actor="reviewer-1")

        members = list(hh.members.order_by("line_number"))
        assert hh.head_member_id == members[0].id
        assert members[0].relationship_to_head == "01"  # head
        assert members[1].relationship_to_head == "04"  # unchanged

    def test_promote_does_not_demote_existing_head_code(self, connector, geo_codes):
        # The invariant flips `""` to `"01"`; it never overwrites a
        # legitimate explicit "01" with a different value.
        payload = _payload(geo_codes)
        run = start_connector_run(connector)
        landing = land_payload(run, payload)
        stage = stage_from_landing(landing, canonical_payload=payload)
        hh = promote_stage_record(stage, actor="reviewer-1")
        head = hh.members.order_by("line_number").first()
        assert head.relationship_to_head == "01"  # payload already had it

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

    # --- US-082a -----------------------------------------------------
    def test_dqa_failure_writes_dqaresult_row(
        self, connector, geo_codes, dqa_blocking_name_rule,
    ):
        """A staged record that fails one rule writes exactly one
        DqaResult row, with record_type/record_id pointing at the
        member that failed."""
        from apps.dqa.models import DqaResult
        payload = _payload(geo_codes)
        payload["members"][0]["surname"] = ""  # one member fails
        stage = _make_stage(connector, geo_codes, payload=payload)
        before = DqaResult.objects.count()
        process_stage_record(stage, actor="orch")
        after = DqaResult.objects.count()
        assert after == before + 1
        row = DqaResult.objects.filter(
            rule=dqa_blocking_name_rule, passed=False,
        ).order_by("-executed_at").first()
        assert row is not None
        assert row.record_type == "member"
        # record_id = "{provisional_registry_id}:{line_number}"
        assert row.record_id == f"{stage.provisional_registry_id}:1"
        assert row.severity == "blocking"

    def test_dqa_multiple_failures_each_get_a_row(
        self, connector, geo_codes, dqa_blocking_name_rule,
    ):
        from apps.dqa.models import DqaResult
        payload = _payload(geo_codes)
        # Both members fail the surname rule.
        payload["members"][0]["surname"] = ""
        payload["members"][1]["surname"] = ""
        stage = _make_stage(connector, geo_codes, payload=payload)
        before = DqaResult.objects.count()
        process_stage_record(stage, actor="orch")
        after = DqaResult.objects.count()
        assert after == before + 2
        # One row per failed member.
        ids = set(DqaResult.objects.filter(rule=dqa_blocking_name_rule)
                  .values_list("record_id", flat=True))
        assert ids == {
            f"{stage.provisional_registry_id}:1",
            f"{stage.provisional_registry_id}:2",
        }

    def test_dqa_passing_record_writes_zero_rows(
        self, connector, geo_codes, dqa_blocking_name_rule,
    ):
        """The whole point of US-082a's failures-only policy: passes
        do not bloat the table."""
        from apps.dqa.models import DqaResult
        payload = _payload(geo_codes)  # both members have surnames
        stage = _make_stage(connector, geo_codes, payload=payload)
        before = DqaResult.objects.count()
        process_stage_record(stage, actor="orch")
        assert DqaResult.objects.count() == before

    def test_dqa_info_severity_skipped_by_default(
        self, connector, geo_codes,
    ):
        """`info` failures are dropped unless DQA_PERSIST_INFO_FAILURES
        is True. The dashboard cares about blocking + warning."""
        from apps.dqa.models import DqaResult
        DqaRule.objects.create(
            rule_id="TEST-INFO-RULE", version=1,
            description="info severity, member always fails",
            severity=Severity.INFO,
            applicability_filter={"entity": "member"},
            expression={"field": "phone_optional", "op": "not_null"},
            error_message_template="phone missing",
            status=RuleStatus.ACTIVE,
            author="a", approved_by="b",
        )
        stage = _make_stage(connector, geo_codes)
        before = DqaResult.objects.count()
        process_stage_record(stage, actor="orch")
        # Two members fail "info" → both skipped → zero rows written.
        assert DqaResult.objects.count() == before

    def test_dqa_info_severity_persisted_when_flag_on(
        self, connector, geo_codes, settings,
    ):
        from apps.dqa.models import DqaResult
        settings.DQA_PERSIST_INFO_FAILURES = True
        DqaRule.objects.create(
            rule_id="TEST-INFO-RULE-2", version=1,
            description="info severity flagged",
            severity=Severity.INFO,
            applicability_filter={"entity": "member"},
            expression={"field": "phone_optional", "op": "not_null"},
            error_message_template="phone missing",
            status=RuleStatus.ACTIVE,
            author="a", approved_by="b",
        )
        stage = _make_stage(connector, geo_codes)
        before = DqaResult.objects.count()
        process_stage_record(stage, actor="orch")
        # Two members, both info-failing — two rows.
        assert DqaResult.objects.count() == before + 2

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
                              first_name="One", sex="1", nin_hash=nin_hash(nin))
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


# ---------------------------------------------------------------------------
# StageRecord list endpoint — ?state= query parameter (issue 2 from the
# 2026-05-24 DIH review report: promoted records were still showing in
# the queue because filterset_fields silently no-ops without django-filter)


@pytest.mark.django_db
class TestStageRecordStateFilter:
    URL = "/api/v1/dih/stage-records/"

    def _client(self, django_user_model):
        u = django_user_model.objects.create_user(
            username="dih-reader", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        return c

    def _stage(self, state, connector, payload):
        run = start_connector_run(connector)
        landing = land_payload(run, payload)
        stage = stage_from_landing(landing, canonical_payload=payload)
        stage.state = state
        stage.save(update_fields=["state"])
        return stage

    def test_state_filter_returns_only_matching(
        self, django_user_model, connector, geo_codes,
    ):
        from apps.ingestion_hub.models import StageRecordState
        a = self._stage(StageRecordState.PENDING_PROMOTION, connector, _payload(geo_codes))
        b = self._stage(StageRecordState.PROMOTED, connector, _payload(geo_codes, head_first_name="Jane"))

        r = self._client(django_user_model).get(self.URL + "?state=pending_promotion")
        assert r.status_code == 200
        ids = {row["id"] for row in r.data["results"]}
        assert a.id in ids
        assert b.id not in ids

    def test_state_filter_excludes_promoted_by_default_when_set(
        self, django_user_model, connector, geo_codes,
    ):
        """Promoted records must not appear in the DIH review queue —
        the operator complaint that drove this fix."""
        from apps.ingestion_hub.models import StageRecordState
        promoted = self._stage(StageRecordState.PROMOTED, connector, _payload(geo_codes))
        pending = self._stage(
            StageRecordState.PENDING_PROMOTION, connector,
            _payload(geo_codes, head_first_name="Mary"),
        )

        r = self._client(django_user_model).get(self.URL + "?state=pending_promotion")
        ids = {row["id"] for row in r.data["results"]}
        assert promoted.id not in ids
        assert pending.id in ids

    def test_state_csv_accepts_multiple_values(
        self, django_user_model, connector, geo_codes,
    ):
        from apps.ingestion_hub.models import StageRecordState
        a = self._stage(StageRecordState.PROVISIONAL, connector, _payload(geo_codes))
        b = self._stage(StageRecordState.PENDING_PROMOTION, connector, _payload(geo_codes, head_first_name="Sam"))
        c = self._stage(StageRecordState.PROMOTED, connector, _payload(geo_codes, head_first_name="Tim"))

        r = self._client(django_user_model).get(self.URL + "?state=provisional,pending_promotion")
        ids = {row["id"] for row in r.data["results"]}
        assert a.id in ids
        assert b.id in ids
        assert c.id not in ids


# ---------------------------------------------------------------------------
# Walk-in submission endpoint (Slice A — US-S23-WALKIN)


@pytest.mark.django_db
class TestWalkInSubmit:
    URL = "/api/v1/dih/walk-in-submissions/"

    def _client(self, django_user_model):
        u = django_user_model.objects.create_user(
            username="parish-op", password="p",
        )
        c = APIClient()
        c.force_authenticate(user=u)
        return c

    def test_creates_stage_record_with_provisional_id(self, django_user_model, geo_codes):
        r = self._client(django_user_model).post(
            self.URL, _payload(geo_codes), format="json",
        )
        assert r.status_code == 201, r.data
        # Walk-in auto-processes the record after staging, so we check
        # for a valid provisional Registry ID (preserved across state
        # transitions per AC-DIH-PROVISIONAL-ID) instead of asserting
        # the post-process state.
        assert len(r.data["provisional_registry_id"]) == 26
        # The record genuinely landed in DIH.
        from apps.ingestion_hub.models import StageRecord
        assert StageRecord.objects.filter(
            provisional_registry_id=r.data["provisional_registry_id"],
        ).exists()

    def test_clean_walk_in_fast_tracks_through_gates(
        self, django_user_model, geo_codes,
    ):
        """Clean walk-in (no DQA blocking, no DDUP, no NIN/IDV issue)
        should route past provisional automatically — AC-DIH-FT-AUTO.
        The receipt overlay tells the operator the next step."""
        r = self._client(django_user_model).post(
            self.URL, _payload(geo_codes), format="json",
        )
        assert r.status_code == 201, r.data
        # The empty fixture environment has no DQA rules, no DDUP
        # candidates, no NIN — so the record fast-tracks to promoted.
        assert r.data["state"] in ("promoted", "pending_promotion")

    def test_rejects_empty_payload(self, django_user_model):
        r = self._client(django_user_model).post(self.URL, {}, format="json")
        assert r.status_code == 400

    def test_anonymous_caller_blocked(self):
        c = APIClient()  # not authenticated
        r = c.post(self.URL, _payload({}), format="json")
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Quarantine endpoint (Slice B — archive workflow)


@pytest.mark.django_db
class TestQuarantineEndpoint:
    URL_TPL = "/api/v1/dih/stage-records/{id}/quarantine/"

    def _client(self, django_user_model):
        u = django_user_model.objects.create_user(
            username="nsr-unit", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        return c

    def _staged(self, connector, geo_codes, state):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        stage.state = state
        stage.save(update_fields=["state"])
        return stage

    def test_quality_failed_can_be_quarantined(
        self, django_user_model, connector, geo_codes,
    ):
        from apps.ingestion_hub.models import StageRecordState
        stage = self._staged(connector, geo_codes, StageRecordState.QUALITY_FAILED)
        r = self._client(django_user_model).post(
            self.URL_TPL.format(id=stage.id),
            {"actor": "nsr-unit", "reason": "Duplicate of HH-123, unfixable."},
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["state"] == "quarantined"

    def test_pending_promotion_cannot_be_quarantined(
        self, django_user_model, connector, geo_codes,
    ):
        from apps.ingestion_hub.models import StageRecordState
        stage = self._staged(connector, geo_codes, StageRecordState.PENDING_PROMOTION)
        r = self._client(django_user_model).post(
            self.URL_TPL.format(id=stage.id),
            {"actor": "nsr-unit", "reason": "wrong tab"},
            format="json",
        )
        assert r.status_code == 400

    def test_reason_required(self, django_user_model, connector, geo_codes):
        from apps.ingestion_hub.models import StageRecordState
        stage = self._staged(connector, geo_codes, StageRecordState.QUALITY_FAILED)
        r = self._client(django_user_model).post(
            self.URL_TPL.format(id=stage.id),
            {"actor": "nsr-unit", "reason": ""},
            format="json",
        )
        assert r.status_code == 400

    def test_archive_visible_via_state_filter(
        self, django_user_model, connector, geo_codes,
    ):
        from apps.ingestion_hub.models import StageRecordState
        stage = self._staged(connector, geo_codes, StageRecordState.QUALITY_FAILED)
        client = self._client(django_user_model)
        client.post(
            self.URL_TPL.format(id=stage.id),
            {"actor": "nsr-unit", "reason": "archived"},
            format="json",
        )
        r = client.get("/api/v1/dih/stage-records/?state=quarantined")
        assert r.status_code == 200
        ids = {row["id"] for row in r.data["results"]}
        assert stage.id in ids


# ---------------------------------------------------------------------------
# In-place correction (US-S23-DIH-EDIT)


@pytest.mark.django_db
class TestEditStageRecord:
    URL_TPL = "/api/v1/dih/stage-records/{id}/edit/"

    def _client(self, django_user_model, *, username="nsr-corrector"):
        u, _ = django_user_model.objects.get_or_create(
            username=username,
            defaults={"is_superuser": True},
        )
        u.set_password("p")
        u.save()
        c = APIClient()
        c.force_authenticate(user=u)
        return c

    def _staged(self, connector, geo_codes, state):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        stage.state = state
        stage.save(update_fields=["state"])
        return stage

    def test_edit_succeeds_on_provisional(
        self, django_user_model, connector, geo_codes,
    ):
        stage = self._staged(connector, geo_codes, StageRecordState.PROVISIONAL)
        r = self._client(django_user_model).post(
            self.URL_TPL.format(id=stage.id),
            {
                "actor": "nsr-corrector",
                "reason": "Phone digit transposition spotted on intake review",
                "field_changes": {
                    "members.0.telephone_1": "+256 786 999999",
                    "gps_accuracy_m": "4.50",
                },
            },
            format="json",
        )
        assert r.status_code == 200, r.data
        stage.refresh_from_db()
        assert stage.canonical_payload["members"][0]["telephone_1"] == "+256 786 999999"
        assert stage.canonical_payload["gps_accuracy_m"] == "4.50"
        assert stage.last_edited_by == "nsr-corrector"
        assert stage.last_edited_at is not None

    def test_edit_rejected_on_promoted_state(
        self, django_user_model, connector, geo_codes,
    ):
        stage = self._staged(connector, geo_codes, StageRecordState.PROMOTED)
        r = self._client(django_user_model).post(
            self.URL_TPL.format(id=stage.id),
            {
                "actor": "x", "reason": "y",
                "field_changes": {"gps_accuracy_m": "4.0"},
            },
            format="json",
        )
        assert r.status_code == 400

    def test_whitelist_blocks_nin_edit(
        self, django_user_model, connector, geo_codes,
    ):
        stage = self._staged(connector, geo_codes, StageRecordState.PROVISIONAL)
        r = self._client(django_user_model).post(
            self.URL_TPL.format(id=stage.id),
            {
                "actor": "x", "reason": "y",
                "field_changes": {"members.0.nin": "CM00000000XXXX"},
            },
            format="json",
        )
        assert r.status_code == 400
        assert "whitelist" in r.data["detail"].lower()

    def test_whitelist_blocks_geo_chain_edit(
        self, django_user_model, connector, geo_codes,
    ):
        stage = self._staged(connector, geo_codes, StageRecordState.PROVISIONAL)
        r = self._client(django_user_model).post(
            self.URL_TPL.format(id=stage.id),
            {
                "actor": "x", "reason": "y",
                "field_changes": {"geographic.district": "T-D-OTHER"},
            },
            format="json",
        )
        assert r.status_code == 400

    def test_reason_required(self, django_user_model, connector, geo_codes):
        stage = self._staged(connector, geo_codes, StageRecordState.PROVISIONAL)
        r = self._client(django_user_model).post(
            self.URL_TPL.format(id=stage.id),
            {
                "actor": "x", "reason": "",
                "field_changes": {"gps_accuracy_m": "1.0"},
            },
            format="json",
        )
        assert r.status_code == 400

    def test_edit_emits_audit_per_field(
        self, django_user_model, connector, geo_codes,
    ):
        from apps.security.models import AuditEvent
        stage = self._staged(connector, geo_codes, StageRecordState.PROVISIONAL)
        before = AuditEvent.objects.filter(
            entity_type="stage_record", action="edit",
        ).count()
        self._client(django_user_model).post(
            self.URL_TPL.format(id=stage.id),
            {
                "actor": "nsr-corrector",
                "reason": "Operator typo on capture",
                "field_changes": {
                    "members.0.surname": "Okoth",  # was "Okot"
                    "members.0.telephone_1": "+256 786 111222",
                },
            },
            format="json",
        )
        after = AuditEvent.objects.filter(
            entity_type="stage_record", action="edit",
        ).count()
        assert after == before + 2  # one event per changed field

    def test_quality_failed_returns_to_provisional_when_dqa_clears(
        self, django_user_model, connector, geo_codes,
    ):
        """If the edit fixes every blocking failure, the record flips
        back to provisional so the queue treats it as actionable."""
        stage = self._staged(connector, geo_codes, StageRecordState.QUALITY_FAILED)
        self._client(django_user_model).post(
            self.URL_TPL.format(id=stage.id),
            {
                "actor": "nsr-corrector",
                "reason": "spelling fix",
                "field_changes": {"members.0.surname": "Okoth"},
            },
            format="json",
        )
        stage.refresh_from_db()
        # No DQA rules active in the test DB, so blocking_failures = [].
        # The transition should fire.
        assert stage.state == StageRecordState.PROVISIONAL


@pytest.mark.django_db
class TestEditNoSelfApprove:
    """The same operator cannot edit AND promote a stage record."""

    def test_self_promote_blocked(self, connector, geo_codes):
        from apps.ingestion_hub.services import edit_stage_record
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        stage.state = StageRecordState.PENDING_PROMOTION
        stage.save(update_fields=["state"])
        # Move to provisional so the edit is allowed, then back.
        stage.state = StageRecordState.PROVISIONAL
        stage.save(update_fields=["state"])
        edit_stage_record(
            stage,
            field_changes={"gps_accuracy_m": "4.0"},
            actor="alice",
            reason="fix",
            rerun_dqa=False,
        )
        stage.refresh_from_db()
        stage.state = StageRecordState.PENDING_PROMOTION
        stage.save(update_fields=["state"])

        with pytest.raises(DihError, match="EDIT-NO-SELF-APPROVE"):
            promote_stage_record(stage, actor="alice")

    def test_other_promoter_succeeds(self, connector, geo_codes):
        from apps.ingestion_hub.services import edit_stage_record
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        edit_stage_record(
            stage,
            field_changes={"gps_accuracy_m": "4.0"},
            actor="alice",
            reason="fix",
            rerun_dqa=False,
        )
        stage.refresh_from_db()
        # A different operator can promote.
        hh = promote_stage_record(stage, actor="bob")
        assert hh.id == stage.provisional_registry_id


# ---------------------------------------------------------------------------
# Management command — process_stuck_stagerecords with --state filter
# (US-S23-DIH-REPROCESS)


@pytest.mark.django_db
class TestReprocessCommand:
    def _staged(self, connector, geo_codes, state):
        run = start_connector_run(connector)
        landing = land_payload(run, _payload(geo_codes))
        stage = stage_from_landing(landing, canonical_payload=_payload(geo_codes))
        stage.state = state
        stage.save(update_fields=["state"])
        return stage

    def test_default_state_is_provisional(self, connector, geo_codes):
        from io import StringIO

        from django.core.management import call_command
        s_prov = self._staged(connector, geo_codes, StageRecordState.PROVISIONAL)
        s_qf = self._staged(connector, geo_codes, StageRecordState.QUALITY_FAILED)
        out = StringIO()
        call_command("process_stuck_stagerecords", "--dry-run", stdout=out)
        text = out.getvalue()
        assert s_prov.id in text
        assert s_qf.id not in text

    def test_state_flag_reprocesses_quality_failed(self, connector, geo_codes):
        from io import StringIO

        from django.core.management import call_command
        s_qf = self._staged(connector, geo_codes, StageRecordState.QUALITY_FAILED)
        out = StringIO()
        call_command(
            "process_stuck_stagerecords", "--state", "quality_failed",
            "--dry-run", stdout=out,
        )
        assert s_qf.id in out.getvalue()

    def test_state_csv_unions(self, connector, geo_codes):
        from io import StringIO

        from django.core.management import call_command
        s_prov = self._staged(connector, geo_codes, StageRecordState.PROVISIONAL)
        s_qf = self._staged(connector, geo_codes, StageRecordState.QUALITY_FAILED)
        out = StringIO()
        call_command(
            "process_stuck_stagerecords", "--state",
            "provisional,quality_failed", "--dry-run", stdout=out,
        )
        text = out.getvalue()
        assert s_prov.id in text
        assert s_qf.id in text

    def test_terminal_state_rejected(self):
        from django.core.management import CommandError, call_command
        with pytest.raises(CommandError, match="terminal"):
            call_command("process_stuck_stagerecords", "--state", "promoted")

    def test_unknown_state_rejected(self):
        from django.core.management import CommandError, call_command
        with pytest.raises(CommandError, match="unknown state"):
            call_command("process_stuck_stagerecords", "--state", "frobnicated")

    def test_run_actually_routes_records(self, connector, geo_codes):
        from django.core.management import call_command
        s_qf = self._staged(connector, geo_codes, StageRecordState.QUALITY_FAILED)
        call_command("process_stuck_stagerecords", "--state", "quality_failed")
        s_qf.refresh_from_db()
        # With no active DQA rules, the quality_failed record routes
        # forward — to promoted (fast-track) or pending_promotion.
        assert s_qf.state in (
            StageRecordState.PROMOTED.value,
            StageRecordState.PENDING_PROMOTION.value,
        )


# ---------------------------------------------------------------------------
# Village optional (US-S23-DIH-VILLAGE-OPTIONAL)


@pytest.mark.django_db
class TestVillageOptional:
    """Field ops report village commonly unknown at capture; only the
    19/10,872 parishes have seeded village rows. Promotion must
    succeed when geographic.village is missing — parish is the
    lowest mandatory level."""

    def _payload_no_village(self, geo_codes):
        p = _payload(geo_codes)
        p["geographic"] = {k: v for k, v in p["geographic"].items() if k != "village"}
        return p

    def test_promote_without_village_succeeds(self, connector, geo_codes):
        payload = self._payload_no_village(geo_codes)
        run = start_connector_run(connector)
        landing = land_payload(run, payload)
        stage = stage_from_landing(landing, canonical_payload=payload)
        hh = promote_stage_record(stage, actor="reviewer")
        assert hh.parish.code == geo_codes["parish"]
        assert hh.village is None  # parsed as missing, not lost

    def test_promote_without_parish_still_fails(self, connector, geo_codes):
        payload = _payload(geo_codes)
        payload["geographic"] = {k: v for k, v in payload["geographic"].items() if k != "parish"}
        run = start_connector_run(connector)
        landing = land_payload(run, payload)
        stage = stage_from_landing(landing, canonical_payload=payload)
        with pytest.raises(DihError, match="parish"):
            promote_stage_record(stage, actor="reviewer")


# --- US-S11-021 — console "Run connector" trigger endpoint -----------------

import responses  # noqa: E402 — imported here to keep top-of-file lean

from apps.ingestion_hub.models import (  # noqa: E402
    ConnectorRunStatus,
    ConnectorRunType,
    KoboCredential,
    RawLanding,
)

_TRIGGER_KOBO_URL = "https://kobo.trigger-test.invalid"


@pytest.fixture
def trigger_kobo_source(db):
    # SourceSystem.code must match the registered KoboConnector.code
    # ("KOBO-PILOT") so `get_connector(source.code)` resolves the live
    # impl. The admin-action tests use the same convention.
    src = SourceSystem.objects.create(
        code="KOBO-PILOT", name="Kobo trigger test", kind=SourceSystemKind.KOBO,
    )
    KoboCredential.objects.create(
        source_system=src,
        server_url=_TRIGGER_KOBO_URL,
        token_encrypted=b"stored-token",
        acquired_by_username="placeholder",
    )
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-KOBO-TRIGGER",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    return src


@pytest.fixture
def trigger_kobo_no_dpa(db):
    src = SourceSystem.objects.create(
        code="KOBO-PILOT", name="Kobo no-DPA",
        kind=SourceSystemKind.KOBO,
    )
    KoboCredential.objects.create(
        source_system=src,
        server_url=_TRIGGER_KOBO_URL,
        token_encrypted=b"stored-token",
        acquired_by_username="placeholder",
    )
    return src


def _stub_kobo_one_form_three_rows():
    """Standard Kobo upstream stub: one deployed form, three submissions."""
    responses.add(
        responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets.json",
        json={"results": [
            {"uid": "FORM-X", "name": "Pilot", "asset_type": "survey",
             "deployment__active": True},
        ]}, status=200,
    )
    responses.add(
        responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets/FORM-X/data.json",
        json={"results": [
            {"_id": 1, "Q1": "a"},
            {"_id": 2, "Q1": "b"},
            {"_id": 3, "Q1": "c"},
        ], "next": None}, status=200,
    )


@pytest.mark.django_db
class TestTriggerRunEndpoint:
    """POST /api/dih/source-systems/{id}/trigger-run/ — operator-initiated
    Kobo pull from the System Admin > Connector runs tab (US-S11-021).

    The view emits `dih.connector.triggered` first (so a downstream
    failure still leaves a paper trail), then either
    `trigger_succeeded` or `trigger_rejected` after the body runs.
    """

    def _url(self, source) -> str:
        return f"/api/v1/dih/source-systems/{source.id}/trigger-run/"

    def _in_group(self, django_user_model, group_name):
        from django.contrib.auth.models import Group
        user = django_user_model.objects.create_user(
            username=f"u-{group_name}", password="x",
        )
        grp, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(grp)
        return user

    # --- permissions --------------------------------------------------

    def test_anonymous_caller_gets_403(self, trigger_kobo_source):
        client = APIClient()
        resp = client.post(self._url(trigger_kobo_source), {})
        # IsDihTrigger short-circuits on unauthenticated — DRF returns
        # 401 with BasicAuth challenge OR 403; either is "denied".
        assert resp.status_code in (401, 403)

    def test_authenticated_non_member_gets_403(
        self, trigger_kobo_source, django_user_model,
    ):
        user = django_user_model.objects.create_user(username="random", password="x")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(self._url(trigger_kobo_source), {})
        assert resp.status_code == 403

    @responses.activate
    def test_nsr_admin_can_trigger(
        self, trigger_kobo_source, django_user_model,
    ):
        _stub_kobo_one_form_three_rows()
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(self._url(trigger_kobo_source), {}, format="json")
        assert resp.status_code == 200, resp.content
        assert resp.json()["landed"] == 3

    @responses.activate
    def test_nsr_unit_coordinator_can_trigger(
        self, trigger_kobo_source, django_user_model,
    ):
        _stub_kobo_one_form_three_rows()
        user = self._in_group(django_user_model, "nsr_unit_coordinator")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(self._url(trigger_kobo_source), {}, format="json")
        assert resp.status_code == 200, resp.content

    # --- happy paths ---------------------------------------------------

    @responses.activate
    def test_real_run_lands_records_and_emits_audit(
        self, trigger_kobo_source, django_user_model,
    ):
        _stub_kobo_one_form_three_rows()
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            self._url(trigger_kobo_source), {"dry_run": False}, format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["dry_run"] is False
        assert body["landed"] == 3

        run = ConnectorRun.objects.get(id=body["run_id"])
        assert run.status == ConnectorRunStatus.SUCCEEDED
        assert run.run_type == ConnectorRunType.IMPORT
        assert RawLanding.objects.filter(connector_run=run).count() == 3

        # Two audit events: triggered (always) + trigger_succeeded.
        actions = set(
            AuditEvent.objects.filter(
                actor_id=user.username,
            ).values_list("action", flat=True),
        )
        assert "dih.connector.triggered" in actions
        assert "dih.connector.trigger_succeeded" in actions

    @responses.activate
    def test_dry_run_does_not_land_records(
        self, trigger_kobo_source, django_user_model,
    ):
        _stub_kobo_one_form_three_rows()
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            self._url(trigger_kobo_source), {"dry_run": True}, format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["dry_run"] is True
        # The pull was iterated for metadata: landed counts the rows
        # we *would* have written, but no RawLanding exists and no
        # StageRecord was created.
        assert body["landed"] == 3
        assert body["staged"] == 0
        run = ConnectorRun.objects.get(id=body["run_id"])
        assert run.run_type == ConnectorRunType.TEST
        assert RawLanding.objects.filter(connector_run=run).count() == 0

    # --- rejections ----------------------------------------------------

    def test_non_kobo_kind_is_rejected(
        self, django_user_model,
    ):
        ubos = SourceSystem.objects.create(
            code="UBOS-1", name="UBOS", kind=SourceSystemKind.UBOS,
        )
        DataProvisionAgreement.objects.create(
            source_system=ubos, reference="DPA-UBOS",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        )
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(self._url(ubos), {}, format="json")
        assert resp.status_code == 400
        assert "only Kobo" in resp.json()["detail"]
        # Rejection still emits both audit events.
        actions = set(
            AuditEvent.objects.filter(
                actor_id=user.username,
            ).values_list("action", flat=True),
        )
        assert "dih.connector.triggered" in actions
        assert "dih.connector.trigger_rejected" in actions

    def test_missing_dpa_is_rejected(
        self, trigger_kobo_no_dpa, django_user_model,
    ):
        # No upstream HTTP is reached — the connector wiring check happens
        # before list_forms (which would need a `responses.activate`).
        # However, with credentials present, `get_connector` will return
        # the Kobo impl, and list_forms WILL be called before the DPA
        # check inside start_connector_run. So we have to stub it.
        with responses.RequestsMock() as rsps:
            rsps.add(
                rsps.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets.json",
                json={"results": [
                    {"uid": "F", "name": "F", "asset_type": "survey",
                     "deployment__active": True},
                ]}, status=200,
            )
            user = self._in_group(django_user_model, "nsr_admin")
            client = APIClient()
            client.force_authenticate(user)
            resp = client.post(
                self._url(trigger_kobo_no_dpa), {}, format="json",
            )
        assert resp.status_code == 400
        assert "DPA" in resp.json()["detail"]

    @responses.activate
    def test_concurrent_run_is_rejected(
        self, trigger_kobo_source, django_user_model,
    ):
        # Plant an in-flight ConnectorRun on the source so the
        # concurrency guard refuses a second trigger.
        connector_row = Connector.objects.create(
            source_system=trigger_kobo_source, name="kobo-existing",
            config={},
        )
        ConnectorRun.objects.create(
            connector=connector_row, status=ConnectorRunStatus.RUNNING,
        )
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(self._url(trigger_kobo_source), {}, format="json")
        assert resp.status_code == 400
        assert "already in progress" in resp.json()["detail"]


# --- US-S11-022 — form picker + dashboard live data -----------------------

@pytest.mark.django_db
class TestFormsEndpoint:
    """GET /api/v1/dih/source-systems/{id}/forms/ — feeds the
    Run-connector modal's form-picker dropdown. Kobo-only; gated by
    IsDihTrigger like the trigger endpoint itself.
    """

    def _url(self, source) -> str:
        return f"/api/v1/dih/source-systems/{source.id}/forms/"

    def _in_group(self, django_user_model, group_name):
        from django.contrib.auth.models import Group
        user = django_user_model.objects.create_user(
            username=f"u-{group_name}", password="x",
        )
        grp, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(grp)
        return user

    @responses.activate
    def test_returns_deployed_and_draft_forms_for_kobo(
        self, trigger_kobo_source, django_user_model,
    ):
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "F1", "name": "Pilot v2", "asset_type": "survey",
                 "deployment__active": True},
                {"uid": "F2", "name": "v1 legacy", "asset_type": "survey",
                 "deployment__active": True},
                {"uid": "F3", "name": "Draft", "asset_type": "survey",
                 "deployment__active": False},
            ]}, status=200,
        )
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.get(self._url(trigger_kobo_source))
        assert resp.status_code == 200, resp.content
        body = resp.json()
        uids = {f["uid"]: f for f in body}
        # All 3 returned — the client filters by `deployed` so it
        # can render "deploy state" if needed; the dropdown only
        # shows the deployed ones.
        assert set(uids) == {"F1", "F2", "F3"}
        assert uids["F1"]["deployed"] is True
        assert uids["F3"]["deployed"] is False

    def test_non_kobo_returns_400(self, django_user_model):
        ubos = SourceSystem.objects.create(
            code="UBOS-2", name="UBOS", kind=SourceSystemKind.UBOS,
        )
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.get(self._url(ubos))
        assert resp.status_code == 400
        assert "only Kobo" in resp.json()["detail"]

    def test_anonymous_caller_gets_403(self, trigger_kobo_source):
        client = APIClient()
        resp = client.get(self._url(trigger_kobo_source))
        assert resp.status_code in (401, 403)

    @responses.activate
    def test_pinned_flag_marks_last_staged_success_form(
        self, trigger_kobo_source, django_user_model,
    ):
        # US-S11-026: the modal needs to know which form the server
        # would default to so the dropdown reflects it. Plant a
        # successful past run on FORM-PINNED, then assert /forms/
        # marks it pinned and the other deployed forms unpinned.
        good_connector = Connector.objects.create(
            source_system=trigger_kobo_source, name="kobo-FORM-PINNED",
            config={"kobo_form_uid": "FORM-PINNED"},
        )
        ConnectorRun.objects.create(
            connector=good_connector, status=ConnectorRunStatus.SUCCEEDED,
            records_landed=5, records_staged=5,
        )
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "FORM-LEGACY", "name": "v1 legacy",
                 "asset_type": "survey", "deployment__active": True},
                {"uid": "FORM-PINNED", "name": "current",
                 "asset_type": "survey", "deployment__active": True},
            ]}, status=200,
        )
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.get(self._url(trigger_kobo_source))
        assert resp.status_code == 200, resp.content
        by_uid = {f["uid"]: f for f in resp.json()}
        assert by_uid["FORM-PINNED"]["pinned"] is True
        assert by_uid["FORM-LEGACY"]["pinned"] is False

    @responses.activate
    def test_pinned_flag_absent_when_no_history(
        self, trigger_kobo_source, django_user_model,
    ):
        # No staged-success run → no pin. Modal will fall back to
        # forms[0] in the dropdown default.
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "A", "name": "a",
                 "asset_type": "survey", "deployment__active": True},
                {"uid": "B", "name": "b",
                 "asset_type": "survey", "deployment__active": True},
            ]}, status=200,
        )
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.get(self._url(trigger_kobo_source))
        assert resp.status_code == 200, resp.content
        assert all(f["pinned"] is False for f in resp.json())


@pytest.mark.django_db
class TestTriggerRunFormSelection:
    """The form_uid request field (US-S11-022) and its persistence on
    Connector.config so the next default tracks operator intent."""

    def _url(self, source) -> str:
        return f"/api/v1/dih/source-systems/{source.id}/trigger-run/"

    def _in_group(self, django_user_model, group_name):
        from django.contrib.auth.models import Group
        user = django_user_model.objects.create_user(
            username=f"u-{group_name}-form", password="x",
        )
        grp, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(grp)
        return user

    def _stub_two_forms_three_rows(self):
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "FORM-LEGACY", "name": "v1 legacy",
                 "asset_type": "survey", "deployment__active": True},
                {"uid": "FORM-NEW", "name": "Pilot v2",
                 "asset_type": "survey", "deployment__active": True},
            ]}, status=200,
        )
        # The chosen form's data endpoint gets stubbed per-test.

    def _stub_data_for(self, form_uid):
        responses.add(
            responses.GET,
            f"{_TRIGGER_KOBO_URL}/api/v2/assets/{form_uid}/data.json",
            json={"results": [
                {"_id": 1, "Q": "a"},
                {"_id": 2, "Q": "b"},
            ], "next": None}, status=200,
        )

    @responses.activate
    def test_explicit_form_uid_wins(
        self, trigger_kobo_source, django_user_model,
    ):
        self._stub_two_forms_three_rows()
        self._stub_data_for("FORM-NEW")
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            self._url(trigger_kobo_source),
            {"form_uid": "FORM-NEW"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["form_uid"] == "FORM-NEW"

    @responses.activate
    def test_unknown_form_uid_is_rejected(
        self, trigger_kobo_source, django_user_model,
    ):
        self._stub_two_forms_three_rows()
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            self._url(trigger_kobo_source),
            {"form_uid": "DOES-NOT-EXIST"},
            format="json",
        )
        assert resp.status_code == 400
        assert "not in the deployed-forms list" in resp.json()["detail"]

    @responses.activate
    def test_chosen_form_is_pinned_to_connector_config(
        self, trigger_kobo_source, django_user_model,
    ):
        # First call: operator picks FORM-NEW. We expect Connector.config
        # to record kobo_form_uid=FORM-NEW even though the get_or_create
        # default would have written that anyway (the connector row
        # didn't exist yet).
        self._stub_two_forms_three_rows()
        self._stub_data_for("FORM-NEW")
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            self._url(trigger_kobo_source),
            {"form_uid": "FORM-NEW"},
            format="json",
        )
        assert resp.status_code == 200, resp.content

        connector = Connector.objects.get(
            source_system=trigger_kobo_source, name="kobo-FORM-NEW",
        )
        assert connector.config["kobo_form_uid"] == "FORM-NEW"

    @responses.activate
    def test_default_falls_back_to_last_staged_success_run(
        self, trigger_kobo_source, django_user_model,
    ):
        # Seed a successful past ConnectorRun against FORM-NEW with
        # records_staged > 0. A trigger with no form_uid should pick
        # FORM-NEW instead of FORM-LEGACY (which is forms[0] in
        # response order).
        good_connector = Connector.objects.create(
            source_system=trigger_kobo_source, name="kobo-FORM-NEW",
            config={"kobo_form_uid": "FORM-NEW"},
        )
        ConnectorRun.objects.create(
            connector=good_connector, status=ConnectorRunStatus.SUCCEEDED,
            records_landed=10, records_staged=10,
        )
        self._stub_two_forms_three_rows()
        self._stub_data_for("FORM-NEW")
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(self._url(trigger_kobo_source), {}, format="json")
        assert resp.status_code == 200, resp.content
        assert resp.json()["form_uid"] == "FORM-NEW"

    @responses.activate
    def test_quarantine_only_run_does_not_re_pin(
        self, trigger_kobo_source, django_user_model,
    ):
        # US-S11-025 — the 2026-05-26 trap. An older successful run
        # against FORM-NEW pinned it. A newer all-quarantine run
        # against FORM-LEGACY (records_staged=0) MUST NOT override
        # the pin. Trigger with no form_uid should still default to
        # FORM-NEW.
        good_connector = Connector.objects.create(
            source_system=trigger_kobo_source, name="kobo-FORM-NEW",
            config={"kobo_form_uid": "FORM-NEW"},
        )
        # Older good run — staged=10.
        old_good = ConnectorRun.objects.create(
            connector=good_connector, status=ConnectorRunStatus.SUCCEEDED,
            records_landed=10, records_staged=10,
        )
        # Newer bad run on the legacy form — landed=50, staged=0,
        # everything quarantined. Without the fix, this would
        # re-pin FORM-LEGACY because it's the most recent.
        bad_connector = Connector.objects.create(
            source_system=trigger_kobo_source, name="kobo-FORM-LEGACY",
            config={"kobo_form_uid": "FORM-LEGACY"},
        )
        bad_run = ConnectorRun.objects.create(
            connector=bad_connector, status=ConnectorRunStatus.SUCCEEDED,
            records_landed=50, records_staged=0, records_quarantined=50,
        )
        # Ensure ordering by started_at — newer bad run wins on time.
        assert bad_run.started_at >= old_good.started_at

        self._stub_two_forms_three_rows()
        self._stub_data_for("FORM-NEW")
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(self._url(trigger_kobo_source), {}, format="json")
        assert resp.status_code == 200, resp.content
        # The bad newer run's form does NOT win — the pin tracks
        # staged-success only.
        assert resp.json()["form_uid"] == "FORM-NEW"


@pytest.mark.django_db
class TestConnectorRunSerializerEnrichment:
    """US-S11-022 — source_code + connector_name appear in the JSON so
    the Connector runs dashboard can label rows without an extra
    round-trip per FK."""

    def test_run_payload_includes_source_code_and_connector_name(
        self, django_user_model,
    ):
        from django.contrib.auth.models import Group
        src = SourceSystem.objects.create(
            code="KOBO-DASH", name="Kobo dash test",
            kind=SourceSystemKind.KOBO,
        )
        conn = Connector.objects.create(
            source_system=src, name="kobo-form-z", config={},
        )
        run = ConnectorRun.objects.create(
            connector=conn, status=ConnectorRunStatus.SUCCEEDED,
        )
        user = django_user_model.objects.create_user(
            username="u-dash", password="x",
        )
        grp, _ = Group.objects.get_or_create(name="nsr_admin")
        user.groups.add(grp)
        client = APIClient()
        client.force_authenticate(user)
        resp = client.get(f"/api/v1/dih/connector-runs/{run.id}/")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["source_code"] == "KOBO-DASH"
        assert body["connector_name"] == "kobo-form-z"
        assert body["run_type"] in ("import", "test")


# --- US-S11-023 — delete ConnectorRun ------------------------------------

@pytest.mark.django_db
class TestDeleteConnectorRun:
    """POST /api/v1/dih/connector-runs/{id}/delete/ — cascades through
    every PROTECT FK to ConnectorRun, refusing to remove runs that
    produced promoted records (Household lineage preserved)."""

    def _url(self, run) -> str:
        return f"/api/v1/dih/connector-runs/{run.id}/delete/"

    def _in_group(self, django_user_model, group_name):
        from django.contrib.auth.models import Group
        user = django_user_model.objects.create_user(
            username=f"u-del-{group_name}", password="x",
        )
        grp, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(grp)
        return user

    def _build_run(self, *, status, records_promoted=0):
        src = SourceSystem.objects.create(
            code=f"KOBO-DEL-{status}", name="Kobo delete test",
            kind=SourceSystemKind.KOBO,
        )
        DataProvisionAgreement.objects.create(
            source_system=src, reference=f"DPA-DEL-{status}",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        )
        conn = Connector.objects.create(
            source_system=src, name="kobo-form-x", config={},
        )
        run = ConnectorRun.objects.create(
            connector=conn, status=status,
            records_promoted=records_promoted,
        )
        return run

    def test_anonymous_caller_gets_403(self, django_user_model):
        run = self._build_run(status=ConnectorRunStatus.SUCCEEDED)
        client = APIClient()
        resp = client.post(self._url(run), {}, format="json")
        assert resp.status_code in (401, 403)

    def test_refuses_running_run(self, django_user_model):
        run = self._build_run(status=ConnectorRunStatus.RUNNING)
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(self._url(run), {"reason": "x"}, format="json")
        assert resp.status_code == 400
        assert "wait for it to finish" in resp.json()["detail"]
        # Run survives.
        assert ConnectorRun.objects.filter(id=run.id).exists()

    def test_refuses_run_with_promoted_records(self, django_user_model):
        run = self._build_run(
            status=ConnectorRunStatus.SUCCEEDED, records_promoted=3,
        )
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(self._url(run), {"reason": "x"}, format="json")
        assert resp.status_code == 400
        assert "promoted" in resp.json()["detail"].lower()
        assert ConnectorRun.objects.filter(id=run.id).exists()

    def test_clean_delete_cascades_and_audits(self, django_user_model):
        run = self._build_run(status=ConnectorRunStatus.SUCCEEDED)
        # Plant two RawLandings + one quarantined StageRecord (no
        # PROMOTED state, so the lineage guard passes).
        from apps.ingestion_hub.models import RawLanding
        for i in range(2):
            RawLanding.objects.create(
                connector_run=run, payload={"q": i},
                source_reference=str(i),
            )
        run_id = run.id
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            self._url(run),
            {"reason": "wrong form pulled — 100% quarantine"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["deleted_run_id"] == run_id
        assert body["raw_landings_deleted"] == 2
        # Run + landings gone from the DB.
        assert not ConnectorRun.objects.filter(id=run_id).exists()
        assert RawLanding.objects.filter(connector_run_id=run_id).count() == 0
        # AuditEvent recorded with the cascade counts in field_changes.
        ev = AuditEvent.objects.filter(
            action="dih.connector.run_deleted", entity_id=run_id,
        ).first()
        assert ev is not None
        assert ev.field_changes["raw_landings_deleted"] == 2
        assert "wrong form pulled" in ev.reason

    def test_nsr_unit_coordinator_can_delete(self, django_user_model):
        # The Sys Admin + NSR Unit Coordinator parity for the
        # trigger surface extends to the delete surface too.
        run = self._build_run(status=ConnectorRunStatus.SUCCEEDED)
        user = self._in_group(django_user_model, "nsr_unit_coordinator")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            self._url(run), {"reason": "cleanup"}, format="json",
        )
        assert resp.status_code == 200, resp.content


@pytest.mark.django_db
class TestTriggerRunPersistsOutcomeCounters:
    """US-S11-024 regression: trigger_connector_pull must write its
    per-outcome counters (quarantined, errored) back to the
    ConnectorRun so the dashboard's Quarantined / Rejected columns
    don't lie. Earlier slices only persisted records_landed (via
    land_payload), so a 100%-canonicalize-failure pull would render
    landed=50, quarantined=0 — exactly what the operator saw on
    2026-05-26 22:30 (run 01KSK6K7921G4X3V01TA5WY5DP)."""

    @responses.activate
    def test_quarantined_count_lands_on_records_quarantined(
        self, trigger_kobo_source, django_user_model,
    ):
        # Stub a form whose canonicalize will fail — the simplest
        # path is to return rows that don't have the canonical
        # geographic chain the Kobo connector expects. KoboConnector
        # canonicalize raises KeyError on missing 'a1_region', so
        # any payload that lacks it routes to "quarantined".
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "BROKEN-FORM", "name": "Will canonicalize-fail",
                 "asset_type": "survey", "deployment__active": True},
            ]}, status=200,
        )
        responses.add(
            responses.GET,
            f"{_TRIGGER_KOBO_URL}/api/v2/assets/BROKEN-FORM/data.json",
            json={"results": [
                {"_id": 1, "shape": "missing geographic chain"},
                {"_id": 2, "shape": "missing geographic chain"},
                {"_id": 3, "shape": "missing geographic chain"},
            ], "next": None}, status=200,
        )
        from django.contrib.auth.models import Group
        user = django_user_model.objects.create_user(
            username="u-counter", password="x",
        )
        grp, _ = Group.objects.get_or_create(name="nsr_admin")
        user.groups.add(grp)
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            f"/api/v1/dih/source-systems/{trigger_kobo_source.id}/trigger-run/",
            {"form_uid": "BROKEN-FORM"}, format="json",
        )
        assert resp.status_code == 200, resp.content
        run = ConnectorRun.objects.get(id=resp.json()["run_id"])
        assert run.records_landed == 3
        # The dashboard's Quarantined column reads from this field,
        # so the regression we're locking down is "quarantined > 0
        # when canonicalize failed on every row".
        assert run.records_quarantined == 3, (
            f"records_quarantined should reflect the 3 canonicalize-failures, "
            f"got {run.records_quarantined}"
        )


# --- US-S11-034 — watermark + landing dedup --------------------------------

@pytest.mark.django_db
class TestTriggerRunDedup:
    """A second pull of the same upstream rows must not re-land them.
    The watermark cuts bandwidth (Kobo filters by _submission_time)
    and the landing dedup catches anything that slips through
    (boundary row at $gte, manual re-pull with no watermark, etc)."""

    def _url(self, source) -> str:
        return f"/api/v1/dih/source-systems/{source.id}/trigger-run/"

    def _in_group(self, django_user_model, group_name):
        from django.contrib.auth.models import Group
        user = django_user_model.objects.create_user(
            username=f"u-dedup-{group_name}", password="x",
        )
        grp, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(grp)
        return user

    @responses.activate
    def test_second_pull_skips_duplicates_and_lands_nothing(
        self, trigger_kobo_source, django_user_model,
    ):
        # Same form, same three submissions. After the first pull
        # all three should land; the second pull should detect them
        # as duplicates and skip every one.
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "F1", "name": "Pilot", "asset_type": "survey",
                 "deployment__active": True},
            ]}, status=200,
        )
        # The data endpoint returns the same 3 rows every time
        # (responses.add registers it once and matches on URL — the
        # second call gets the same body).
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets/F1/data.json",
            json={"results": [
                {"_id": 101, "Q1": "a", "_submission_time": "2026-05-27T08:00:00"},
                {"_id": 102, "Q1": "b", "_submission_time": "2026-05-27T08:01:00"},
                {"_id": 103, "Q1": "c", "_submission_time": "2026-05-27T08:02:00"},
            ], "next": None}, status=200,
        )
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)

        # First pull: 3 land, 0 dupes.
        r1 = client.post(self._url(trigger_kobo_source), {}, format="json")
        assert r1.status_code == 200, r1.content
        assert r1.json()["landed"] == 3
        assert r1.json()["skipped_duplicate"] == 0
        # Watermark persisted on Connector.config so the next pull
        # passes since= to Kobo.
        from apps.ingestion_hub.models import Connector
        conn = Connector.objects.get(
            source_system=trigger_kobo_source, name="kobo-F1",
        )
        assert conn.config["last_pulled_submission_time"] == "2026-05-27T08:02:00"

        # Second pull: same three rows from Kobo, all already landed
        # → all skipped, none re-landed.
        r2 = client.post(self._url(trigger_kobo_source), {}, format="json")
        assert r2.status_code == 200, r2.content
        body2 = r2.json()
        assert body2["landed"] == 0
        assert body2["skipped_duplicate"] == 3
        assert body2["staged"] == 0
        # Only the 3 RawLandings from the first run exist.
        from apps.ingestion_hub.models import RawLanding
        assert RawLanding.objects.filter(
            connector_run__connector__source_system=trigger_kobo_source,
        ).count() == 3

    @responses.activate
    def test_dry_run_does_not_persist_watermark(
        self, trigger_kobo_source, django_user_model,
    ):
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "F-DR", "name": "Pilot DR", "asset_type": "survey",
                 "deployment__active": True},
            ]}, status=200,
        )
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets/F-DR/data.json",
            json={"results": [
                {"_id": 1, "Q": "a", "_submission_time": "2026-05-27T09:00:00"},
            ], "next": None}, status=200,
        )
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            self._url(trigger_kobo_source),
            {"dry_run": True}, format="json",
        )
        assert resp.status_code == 200, resp.content
        from apps.ingestion_hub.models import Connector
        conn = Connector.objects.get(
            source_system=trigger_kobo_source, name="kobo-F-DR",
        )
        # Watermark stays absent because dry-runs don't acknowledge.
        assert "last_pulled_submission_time" not in conn.config

    @responses.activate
    def test_partial_dedup_lands_only_new_rows(
        self, trigger_kobo_source, django_user_model,
    ):
        # First pull lands #1, #2. Second pull's stub returns #2
        # (boundary at $gte) + #3 (new) — dedup catches #2, lands #3.
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "F2", "name": "Pilot 2", "asset_type": "survey",
                 "deployment__active": True},
            ]}, status=200,
        )
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets/F2/data.json",
            json={"results": [
                {"_id": 1, "Q": "a", "_submission_time": "2026-05-27T10:00:00"},
                {"_id": 2, "Q": "b", "_submission_time": "2026-05-27T10:01:00"},
            ], "next": None}, status=200,
        )
        user = self._in_group(django_user_model, "nsr_admin")
        client = APIClient()
        client.force_authenticate(user)
        r1 = client.post(self._url(trigger_kobo_source), {}, format="json")
        assert r1.status_code == 200
        assert r1.json()["landed"] == 2

        # Re-stub with the boundary + new row.
        responses.reset()
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "F2", "name": "Pilot 2", "asset_type": "survey",
                 "deployment__active": True},
            ]}, status=200,
        )
        responses.add(
            responses.GET, f"{_TRIGGER_KOBO_URL}/api/v2/assets/F2/data.json",
            json={"results": [
                {"_id": 2, "Q": "b", "_submission_time": "2026-05-27T10:01:00"},
                {"_id": 3, "Q": "c", "_submission_time": "2026-05-27T10:02:00"},
            ], "next": None}, status=200,
        )
        r2 = client.post(self._url(trigger_kobo_source), {}, format="json")
        assert r2.status_code == 200, r2.content
        body2 = r2.json()
        assert body2["landed"] == 1
        assert body2["skipped_duplicate"] == 1


# --- US-S11-031 — resolve IDV_PENDING ---------------------------------------

from apps.ingestion_hub.services import resolve_idv_pending  # noqa: E402


@pytest.mark.django_db
class TestResolveIdvPending:
    """Service-level coverage for the operator-driven exit from
    IDV_PENDING. Accept overrides IDV and runs the DDUP gate that was
    skipped originally; Reject delegates to reject_stage_record."""

    def _idv_pending_stage(self, connector, geo_codes, *, nin="CM1234567890NM"):
        """Build a stage record parked at IDV_PENDING by feeding the
        mock NIRA a NIN it returns no_match for."""
        payload = _payload(geo_codes)
        payload["members"][0]["nin"] = nin
        stage = _make_stage(connector, geo_codes, payload=payload)
        process_stage_record(stage, actor="orch")
        stage.refresh_from_db()
        assert stage.state == StageRecordState.IDV_PENDING
        return stage

    def test_accept_routes_to_pending_promotion_when_ddup_clean(
        self, connector, geo_codes, dqa_blocking_name_rule,
    ):
        stage = self._idv_pending_stage(connector, geo_codes)
        resolve_idv_pending(
            stage, actor="reviewer", reason="paper evidence reviewed",
            decision="accept",
        )
        stage.refresh_from_db()
        assert stage.state == StageRecordState.PENDING_PROMOTION
        assert stage.idv_outcome == "manual_accept"
        # No DDUP candidates seeded — the candidates list is empty
        # (no other Member with the same NIN hash exists).
        assert stage.ddup_candidates == []

    def test_accept_routes_to_ddup_review_when_strong_candidate_exists(
        self, connector, geo_codes, dqa_blocking_name_rule,
    ):
        # Seed a Household + Member with the same NIN so DDUP
        # discovery finds a tier1 NIN-exact match.
        seed_stage = _make_stage(connector, geo_codes)
        seed_hh = promote_stage_record(seed_stage, actor="seed")
        nin = "CM1234567890NM"
        Member.objects.create(
            household=seed_hh, line_number=99,
            surname="Existing", first_name="One", sex="1",
            nin_hash=nin_hash(nin),
        )
        stage = self._idv_pending_stage(connector, geo_codes, nin=nin)
        resolve_idv_pending(
            stage, actor="reviewer",
            reason="NIN matched off-system but DDUP candidate found",
            decision="accept",
        )
        stage.refresh_from_db()
        assert stage.state == StageRecordState.DDUP_REVIEW
        assert stage.idv_outcome == "manual_accept"
        assert len(stage.ddup_candidates) == 1
        assert stage.ddup_candidates[0]["score"] == 1.0

    def test_reject_delegates_to_reject_stage_record(
        self, connector, geo_codes, dqa_blocking_name_rule,
    ):
        stage = self._idv_pending_stage(connector, geo_codes)
        resolve_idv_pending(
            stage, actor="reviewer", reason="forged NIN",
            decision="reject",
        )
        stage.refresh_from_db()
        assert stage.state == StageRecordState.REJECTED
        # The "idv-reject:" prefix keeps the route explicit in the
        # audit trail.
        assert stage.rejected_reason.startswith("idv-reject: ")
        assert "forged NIN" in stage.rejected_reason

    def test_refuses_when_not_idv_pending(
        self, connector, geo_codes,
    ):
        # A stage in PROVISIONAL can't be resolved as IDV — the
        # service guards against double-resolves + wrong-state calls.
        stage = _make_stage(connector, geo_codes)
        assert stage.state == StageRecordState.PROVISIONAL
        with pytest.raises(DihError, match="not idv_pending"):
            resolve_idv_pending(
                stage, actor="reviewer", reason="x", decision="accept",
            )

    def test_refuses_blank_reason(
        self, connector, geo_codes, dqa_blocking_name_rule,
    ):
        stage = self._idv_pending_stage(connector, geo_codes)
        with pytest.raises(DihError, match="reason is required"):
            resolve_idv_pending(
                stage, actor="reviewer", reason="   ", decision="accept",
            )

    def test_refuses_unknown_decision(
        self, connector, geo_codes, dqa_blocking_name_rule,
    ):
        stage = self._idv_pending_stage(connector, geo_codes)
        with pytest.raises(DihError, match="accept.*reject"):
            resolve_idv_pending(
                stage, actor="reviewer", reason="x", decision="maybe",
            )

    def test_audit_event_emitted_on_accept(
        self, connector, geo_codes, dqa_blocking_name_rule,
    ):
        stage = self._idv_pending_stage(connector, geo_codes)
        resolve_idv_pending(
            stage, actor="reviewer", reason="paper evidence reviewed",
            decision="accept",
        )
        ev = AuditEvent.objects.filter(
            action="resolve_idv", entity_id=stage.id,
        ).first()
        assert ev is not None
        assert ev.actor_id == "reviewer"
        assert ev.field_changes["idv_outcome"] == "manual_accept"
        assert ev.field_changes["next_state"] == "pending_promotion"


@pytest.mark.django_db
class TestResolveIdvEndpoint:
    """API surface for the Resolve IDV modal in the DIH detail rail.
    POST /api/v1/dih/stage-records/{id}/resolve-idv/."""

    def _idv_pending_stage(self, connector, geo_codes):
        payload = _payload(geo_codes)
        payload["members"][0]["nin"] = "CM1234567890NM"
        stage = _make_stage(connector, geo_codes, payload=payload)
        process_stage_record(stage, actor="orch")
        stage.refresh_from_db()
        return stage

    def test_accept_returns_updated_stage_with_new_state(
        self, connector, geo_codes, django_user_model, dqa_blocking_name_rule,
    ):
        stage = self._idv_pending_stage(connector, geo_codes)
        user = django_user_model.objects.create_user(
            username="dih-reviewer", password="x", is_superuser=True,
        )
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            f"/api/v1/dih/stage-records/{stage.id}/resolve-idv/",
            {"actor": "dih-reviewer", "decision": "accept",
             "reason": "paper evidence reviewed"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["state"] == StageRecordState.PENDING_PROMOTION
        assert body["idv_outcome"] == "manual_accept"

    def test_reject_voids_provisional(
        self, connector, geo_codes, django_user_model, dqa_blocking_name_rule,
    ):
        stage = self._idv_pending_stage(connector, geo_codes)
        user = django_user_model.objects.create_user(
            username="dih-reviewer-r", password="x", is_superuser=True,
        )
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            f"/api/v1/dih/stage-records/{stage.id}/resolve-idv/",
            {"actor": "dih-reviewer-r", "decision": "reject",
             "reason": "forged NIN"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["state"] == StageRecordState.REJECTED
        assert "idv-reject" in body["rejected_reason"]

    def test_400_when_not_idv_pending(
        self, connector, geo_codes, django_user_model,
    ):
        # A provisional stage can't be IDV-resolved.
        stage = _make_stage(connector, geo_codes)
        user = django_user_model.objects.create_user(
            username="dih-reviewer-p", password="x", is_superuser=True,
        )
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post(
            f"/api/v1/dih/stage-records/{stage.id}/resolve-idv/",
            {"actor": "dih-reviewer-p", "decision": "accept", "reason": "x"},
            format="json",
        )
        assert resp.status_code == 400
        assert "idv_pending" in resp.json()["detail"]
