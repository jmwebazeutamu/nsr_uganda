"""UPD workflow tests."""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household, HouseholdVersion, Member, MemberVersion
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent
from apps.update_workflow.models import (
    ChangeRequest,
    ChangeStatus,
    ChangeType,
    EntityType,
    SourceChannel,
)
from apps.update_workflow.services import (
    AUTO_COMMIT_CHANGE_TYPES,
    UpdError,
    auto_commit_change_request,
    commit_change_request,
    compute_diff,
    hold_change_request,
    post_change_committed,
    reject_change_request,
    release_change_request,
    submit_change_request,
)

# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def geo(db):
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"U-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return nodes


@pytest.fixture
def household(db, geo):
    return Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"], county=geo["c"],
        sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
        urban_rural="2", address_narrative="Plot 1",
    )


@pytest.fixture
def member(db, household):
    return Member.objects.create(
        household=household, line_number=1, surname="Okot", first_name="James",
        sex="1", telephone_1="+256700000001",
    )


_DEFAULT_CHANGE = {"surname": {"old": "Okot", "new": "Okello"}}


def _draft(member, *, requester="enum-1", changes=_DEFAULT_CHANGE,
           pmt=False, ctype=ChangeType.CORRECTION):
    return ChangeRequest.objects.create(
        entity_type=EntityType.MEMBER, entity_id=member.id,
        change_type=ctype, pmt_relevant=pmt,
        changes=changes,
        source_channel=SourceChannel.PARISH, requester=requester,
    )


# --- compute_diff -----------------------------------------------------------

class TestDiff:
    def test_diff_picks_up_changed_field(self, member):
        d = compute_diff(EntityType.MEMBER, member.id,
                         proposed={"surname": "Okello", "first_name": "James"})
        assert d == {"surname": {"old": "Okot", "new": "Okello"}}

    def test_diff_empty_when_no_change(self, member):
        assert compute_diff(EntityType.MEMBER, member.id,
                            proposed={"surname": "Okot"}) == {}

    def test_diff_unknown_field_raises(self, member):
        with pytest.raises(UpdError, match="unknown field"):
            compute_diff(EntityType.MEMBER, member.id, proposed={"not_a_field": "x"})


# --- submit -----------------------------------------------------------------

class TestSubmit:
    def test_submit_sets_status_role_and_sla(self, member):
        req = _draft(member, pmt=False, ctype=ChangeType.CORRECTION)
        submit_change_request(req)
        req.refresh_from_db()
        assert req.status == ChangeStatus.PENDING_APPROVAL
        assert req.required_role == "supervisor"
        assert req.sla_deadline is not None

    def test_pmt_relevant_routes_to_cdo_with_tighter_sla(self, member):
        req = _draft(member, pmt=True, ctype=ChangeType.CORRECTION)
        submit_change_request(req)
        req.refresh_from_db()
        assert req.required_role == "cdo"

    def test_cannot_submit_empty_changes(self, member):
        req = _draft(member, changes={})
        with pytest.raises(UpdError, match="AC-UPD-DIFF"):
            submit_change_request(req)

    def test_cannot_resubmit(self, member):
        req = _draft(member)
        submit_change_request(req)
        with pytest.raises(UpdError, match="DRAFT"):
            submit_change_request(req)


# --- reject -----------------------------------------------------------------

class TestReject:
    def test_reject_records_decision(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        reject_change_request(req, approver="bob", reason="evidence missing")
        req.refresh_from_db()
        assert req.status == ChangeStatus.REJECTED
        assert req.approver == "bob"
        assert req.decision_reason == "evidence missing"

    def test_no_self_reject(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        with pytest.raises(UpdError, match="AC-UPD-NO-SELF-APPROVE"):
            reject_change_request(req, approver="alice", reason="x")

    def test_reject_requires_reason(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        with pytest.raises(UpdError, match="non-empty reason"):
            reject_change_request(req, approver="bob", reason="")


# --- US-S22-001 — hold / release transitions -------------------------------

class TestHoldRelease:
    """PENDING_APPROVAL ↔ ON_HOLD. Reviewer parks a request pending
    more info, then releases it back into the queue. Both transitions
    enforce AC-UPD-NO-SELF-APPROVE and emit an audit event."""

    def test_hold_parks_request_with_reason(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        hold_change_request(req, approver="bob", reason="awaiting NIRA reconciliation")
        req.refresh_from_db()
        assert req.status == ChangeStatus.ON_HOLD
        assert req.approver == "bob"
        assert req.decision_reason == "awaiting NIRA reconciliation"
        assert req.decided_at is not None

    def test_hold_requires_pending_approval(self, member):
        req = _draft(member)  # DRAFT, not submitted
        with pytest.raises(UpdError, match="can only hold PENDING_APPROVAL"):
            hold_change_request(req, approver="bob", reason="x")

    def test_hold_requires_reason(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        with pytest.raises(UpdError, match="non-empty reason"):
            hold_change_request(req, approver="bob", reason="")

    def test_hold_no_self(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        with pytest.raises(UpdError, match="AC-UPD-NO-SELF-APPROVE"):
            hold_change_request(req, approver="alice", reason="x")

    def test_hold_emits_audit_event(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        hold_change_request(req, approver="bob", reason="awaiting evidence")
        ev = AuditEvent.objects.filter(
            entity_type="change_request", entity_id=req.id, action="hold",
        ).first()
        assert ev is not None
        assert ev.actor_id == "bob"
        assert "awaiting evidence" in ev.reason

    def test_release_returns_to_pending_approval(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        hold_change_request(req, approver="bob", reason="x")
        release_change_request(req, approver="bob")
        req.refresh_from_db()
        assert req.status == ChangeStatus.PENDING_APPROVAL
        # Decision metadata cleared so the next decision is recorded clean.
        assert req.approver == ""
        assert req.decided_at is None
        assert req.decision_reason == ""

    def test_release_requires_on_hold(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        with pytest.raises(UpdError, match="can only release ON_HOLD"):
            release_change_request(req, approver="bob")

    def test_release_no_self(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        hold_change_request(req, approver="bob", reason="x")
        with pytest.raises(UpdError, match="AC-UPD-NO-SELF-APPROVE"):
            release_change_request(req, approver="alice")

    def test_release_emits_audit_event(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        hold_change_request(req, approver="bob", reason="x")
        release_change_request(req, approver="bob")
        ev = AuditEvent.objects.filter(
            entity_type="change_request", entity_id=req.id, action="release",
        ).first()
        assert ev is not None
        assert ev.actor_id == "bob"


# --- commit -----------------------------------------------------------------

class TestCommit:
    def test_commit_applies_changes_and_writes_version(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        commit_change_request(req, approver="bob")
        member.refresh_from_db()
        req.refresh_from_db()
        assert member.surname == "Okello"
        assert req.status == ChangeStatus.COMMITTED
        # Paired version row created with effective_from set, effective_to NULL.
        versions = MemberVersion.objects.filter(member=member).order_by("version_number")
        assert versions.count() == 1
        assert versions[0].surname == "Okello"
        assert versions[0].effective_to is None
        assert versions[0].change_request_id == req.id

    def test_second_commit_closes_prior_version_window(self, member):
        req1 = _draft(member, requester="alice",
                      changes={"surname": {"old": "Okot", "new": "Okello"}})
        submit_change_request(req1)
        commit_change_request(req1, approver="bob")
        member.refresh_from_db()

        req2 = _draft(member, requester="alice",
                      changes={"surname": {"old": "Okello", "new": "Okoth"}})
        submit_change_request(req2)
        commit_change_request(req2, approver="bob")
        versions = MemberVersion.objects.filter(member=member).order_by("version_number")
        assert versions.count() == 2
        assert versions[0].effective_to is not None  # window closed
        assert versions[1].effective_to is None      # current

    def test_no_self_approve_on_commit(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        with pytest.raises(UpdError, match="AC-UPD-NO-SELF-APPROVE"):
            commit_change_request(req, approver="alice")

    def test_concurrent_edit_detected(self, member):
        req = _draft(member, requester="alice",
                     changes={"surname": {"old": "Okot", "new": "Okello"}})
        submit_change_request(req)
        # Simulate another writer landing first.
        member.surname = "Stolen"
        member.save(update_fields=["surname", "updated_at"])
        with pytest.raises(UpdError, match="concurrent edit"):
            commit_change_request(req, approver="bob")

    def test_commit_emits_audit_event(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        before = AuditEvent.objects.filter(action="commit", entity_type="change_request").count()
        commit_change_request(req, approver="bob")
        assert AuditEvent.objects.filter(
            action="commit", entity_type="change_request",
        ).count() == before + 1

    def test_commit_fires_post_change_committed_signal(self, member):
        captured = []

        def listener(sender, **kwargs):
            captured.append(kwargs)

        post_change_committed.connect(listener, dispatch_uid="t")
        try:
            req = _draft(member, requester="alice")
            submit_change_request(req)
            commit_change_request(req, approver="bob")
        finally:
            post_change_committed.disconnect(dispatch_uid="t")
        assert len(captured) == 1
        assert captured[0]["change_request"].id == req.id


# --- household path (versioning is symmetric) -------------------------------

class TestHouseholdCommit:
    def test_household_change_writes_household_version(self, household):
        req = ChangeRequest.objects.create(
            entity_type=EntityType.HOUSEHOLD, entity_id=household.id,
            change_type=ChangeType.CORRECTION, pmt_relevant=False,
            changes={"address_narrative": {"old": "Plot 1", "new": "Plot 1A"}},
            source_channel=SourceChannel.PARISH, requester="alice",
        )
        submit_change_request(req)
        commit_change_request(req, approver="bob")
        household.refresh_from_db()
        assert household.address_narrative == "Plot 1A"
        versions = HouseholdVersion.objects.filter(household=household)
        assert versions.count() == 1
        assert versions.first().address_narrative == "Plot 1A"


# --- auto-commit path ------------------------------------------------------


class TestAutoCommit:
    """SAD §4.4.4: VITAL_EVENT (NIRA push) and PROGRAMME_STATE (partner
    MIS push) bypass approver review and commit at submit time. The 1%
    sample policy flags a deterministic fraction for retro audit."""

    def test_vital_event_auto_commits(self, member):
        req = _draft(
            member, requester="nira-system", ctype=ChangeType.VITAL_EVENT,
            changes={"nin_status": {"old": "8", "new": "verified"}},
        )
        auto_commit_change_request(req)
        req.refresh_from_db()
        assert req.status == ChangeStatus.COMMITTED
        # Auto-commit uses the routed system identifier as approver.
        assert req.approver == "nira_auto"
        member.refresh_from_db()
        assert member.nin_status == "verified"
        # Version row was written.
        assert MemberVersion.objects.filter(member=member).exists()

    def test_programme_state_auto_commits(self, member):
        req = _draft(
            member, requester="pdm-mis", ctype=ChangeType.PROGRAMME_STATE,
            changes={"residency_status": {"old": "", "new": "absent"}},
        )
        auto_commit_change_request(req)
        req.refresh_from_db()
        assert req.status == ChangeStatus.COMMITTED
        assert req.approver == "programme_auto"

    def test_correction_cannot_use_auto_path(self, member):
        req = _draft(member, ctype=ChangeType.CORRECTION)
        with pytest.raises(UpdError, match="rejects change_type"):
            auto_commit_change_request(req)

    def test_addition_cannot_use_auto_path(self, member):
        req = _draft(member, ctype=ChangeType.ADDITION)
        with pytest.raises(UpdError, match="rejects change_type"):
            auto_commit_change_request(req)

    def test_must_be_draft(self, member):
        req = _draft(member, ctype=ChangeType.VITAL_EVENT)
        submit_change_request(req)
        with pytest.raises(UpdError, match="DRAFT"):
            auto_commit_change_request(req)

    def test_auto_commit_emits_audit_chain(self, member):
        req = _draft(
            member, ctype=ChangeType.VITAL_EVENT,
            changes={"nin_status": {"old": "8", "new": "verified"}},
        )
        auto_commit_change_request(req)
        events = AuditEvent.objects.filter(
            entity_type="change_request", entity_id=req.id,
        ).values_list("action", flat=True)
        # Both submit and commit emit; the chain is intact.
        assert "submit" in events
        assert "commit" in events

    def test_sample_rate_1_always_flags(self, member):
        req = _draft(
            member, ctype=ChangeType.VITAL_EVENT,
            changes={"nin_status": {"old": "8", "new": "verified"}},
        )
        auto_commit_change_request(req, sample_rate=1.0)
        req.refresh_from_db()
        assert req.sampled_for_audit is True

    def test_sample_rate_0_never_flags(self, member):
        req = _draft(
            member, ctype=ChangeType.VITAL_EVENT,
            changes={"nin_status": {"old": "8", "new": "verified"}},
        )
        auto_commit_change_request(req, sample_rate=0.0)
        req.refresh_from_db()
        assert req.sampled_for_audit is False

    def test_sample_is_deterministic_per_id(self, member):
        """Same CR id should sample the same way every time — important
        for reproducible audits."""
        from apps.update_workflow.services import _is_sampled
        cr_id = "01HXYTESTCRID0123456789ABC"
        a = _is_sampled(cr_id, 0.5)
        b = _is_sampled(cr_id, 0.5)
        assert a == b

    def test_auto_commit_change_types_frozenset(self):
        assert ChangeType.VITAL_EVENT in AUTO_COMMIT_CHANGE_TYPES
        assert ChangeType.PROGRAMME_STATE in AUTO_COMMIT_CHANGE_TYPES
        assert ChangeType.CORRECTION not in AUTO_COMMIT_CHANGE_TYPES


class TestRoutingMatrixViaRefData:
    """UPD-O-01: routing matrix is operations-editable via
    UpdRoutingRule. route() prefers the active DB row; if none exists
    it falls back to the hardcoded DEFAULT_MATRIX so deleting all rows
    cannot break the system."""

    def test_seed_migration_populated_defaults(self, db):
        from apps.update_workflow.models import UpdRoutingRule
        # Migration 0004 seeded 12 rows (6 change_types x 2 pmt_relevant).
        assert UpdRoutingRule.objects.filter(is_active=True).count() == 12

    def test_db_row_overrides_default(self, db):
        from datetime import timedelta

        from apps.update_workflow.models import UpdRoutingRule
        from apps.update_workflow.routing import route

        # Operations decide to relax CORRECTION/non-PMT SLA from 72h to 96h
        # and move it from 'supervisor' to 'cdo'.
        UpdRoutingRule.objects.filter(
            change_type=ChangeType.CORRECTION, pmt_relevant=False,
        ).update(required_role="cdo", sla_hours=96)

        role, window = route(ChangeType.CORRECTION, pmt_relevant=False)
        assert role == "cdo"
        assert window == timedelta(hours=96)

    def test_fallback_when_no_active_row(self, db):
        from datetime import timedelta

        from apps.update_workflow.models import UpdRoutingRule
        from apps.update_workflow.routing import route

        # Soft-delete (deactivate) the seeded row for CORRECTION/PMT=True.
        UpdRoutingRule.objects.filter(
            change_type=ChangeType.CORRECTION, pmt_relevant=True,
        ).update(is_active=False)

        # Fallback to DEFAULT_MATRIX kicks in.
        role, window = route(ChangeType.CORRECTION, pmt_relevant=True)
        assert role == "cdo"
        assert window == timedelta(hours=48)

    def test_unique_active_constraint_per_tuple(self, db):
        """Cannot have two active rules for the same
        (change_type, pmt_relevant). Inactive duplicates are fine."""
        from django.db import IntegrityError, transaction

        from apps.update_workflow.models import UpdRoutingRule

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                UpdRoutingRule.objects.create(
                    change_type=ChangeType.CORRECTION, pmt_relevant=False,
                    required_role="other", sla_hours=24, is_active=True,
                )

    def test_inactive_duplicate_allowed_for_history(self, db):
        from apps.update_workflow.models import UpdRoutingRule
        # Inactive duplicate is fine — supports version history.
        UpdRoutingRule.objects.create(
            change_type=ChangeType.CORRECTION, pmt_relevant=False,
            required_role="old_role", sla_hours=24, is_active=False,
            note="historical",
        )
        active = UpdRoutingRule.objects.filter(
            change_type=ChangeType.CORRECTION, pmt_relevant=False,
            is_active=True,
        ).count()
        assert active == 1  # only the seeded one remains active


class TestChangeRequestAdminWorkbench:
    """Sprint 5 parallel of GRM S4-005. Approvers need a triage surface
    when the React console isn't deployed. The admin delegates to
    services so audit + signal wiring are identical to the REST API."""

    @pytest.fixture
    def staff_user(self, db, django_user_model):
        return django_user_model.objects.create_user(
            username="approver", password="p",
            is_staff=True, is_superuser=True,
        )

    @pytest.fixture
    def admin_client(self, staff_user):
        from django.test import Client
        c = Client()
        c.force_login(staff_user)
        return c

    def test_changelist_renders(self, admin_client, member):
        req = _draft(member, requester="enum-9")
        r = admin_client.get("/admin/update_workflow/changerequest/")
        assert r.status_code == 200
        assert req.id.encode() in r.content

    def test_sla_badge_overdue_when_past_deadline(self, db, member):
        from datetime import timedelta

        from django.utils import timezone

        from apps.update_workflow.admin import ChangeRequestAdmin
        req = _draft(member)
        submit_change_request(req)
        req.sla_deadline = timezone.now() - timedelta(hours=1)
        req.save(update_fields=["sla_deadline"])
        a = ChangeRequestAdmin(ChangeRequest, admin_site=None)
        assert "OVERDUE" in a.sla_badge(req)

    def test_sla_badge_neutral_for_terminal_states(self, member):
        from apps.update_workflow.admin import ChangeRequestAdmin
        req = _draft(member)
        submit_change_request(req)
        commit_change_request(req, approver="someone-else")
        a = ChangeRequestAdmin(ChangeRequest, admin_site=None)
        badge = a.sla_badge(req)
        assert "OVERDUE" not in badge
        assert "—" in badge

    def test_bulk_reject_skips_non_pending(self, admin_client, member):
        # Two requests: one PENDING_APPROVAL (eligible), one DRAFT (skipped).
        eligible = _draft(member, requester="enum-1")
        submit_change_request(eligible)
        draft = _draft(member, requester="enum-2",
                       changes={"first_name": {"old": "James", "new": "Jane"}})
        r = admin_client.post("/admin/update_workflow/changerequest/", data={
            "action": "admin_reject",
            "_selected_action": [eligible.id, draft.id],
        })
        assert r.status_code in (200, 302)
        eligible.refresh_from_db()
        draft.refresh_from_db()
        assert eligible.status == ChangeStatus.REJECTED
        assert draft.status == ChangeStatus.DRAFT  # unchanged

    def test_bulk_reject_skips_self_approve(self, db, member, django_user_model):
        """Admin user can't reject their own request — the no-self-approve
        guard from services.reject_change_request fires."""
        from django.test import Client

        # Set up admin user whose username matches the requester.
        u = django_user_model.objects.create_user(
            username="enum-self", password="p",
            is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        req = _draft(member, requester="enum-self")
        submit_change_request(req)
        c.post("/admin/update_workflow/changerequest/", data={
            "action": "admin_reject",
            "_selected_action": [req.id],
        })
        req.refresh_from_db()
        # Still PENDING_APPROVAL — bulk action skipped, did not reject.
        assert req.status == ChangeStatus.PENDING_APPROVAL


# --- US-S7-001 — SLA-breach auto-escalation -------------------------------


class TestAutoEscalation:
    """Stale PENDING_APPROVAL rows get their required_role bumped to
    district M&E and their sla_deadline extended by 48h. Idempotent
    (re-runs cannot re-escalate already-escalated rows). Audit
    emission carries the from_role / to_role / new_sla_deadline."""

    def _stale(self, member, *, requester="enum-x", role="supervisor"):
        from datetime import timedelta

        from django.utils import timezone
        req = _draft(member, requester=requester)
        submit_change_request(req)
        # Pretend the routed role and SLA are what we expect, then
        # back-date the SLA so the sweep sees it as breached.
        req.required_role = role
        req.sla_deadline = timezone.now() - timedelta(hours=1)
        req.save(update_fields=["required_role", "sla_deadline"])
        return req

    def test_escalates_stale_row(self, db, member):
        from apps.update_workflow.services import (
            ESCALATION_ROLE,
            escalate_stale_change_requests,
        )
        req = self._stale(member, role="supervisor")
        counts = escalate_stale_change_requests()
        assert counts == {"candidates": 1, "escalated": 1}
        req.refresh_from_db()
        assert req.required_role == ESCALATION_ROLE
        # SLA window pushed forward (now > original past-due deadline).
        from django.utils import timezone
        assert req.sla_deadline > timezone.now()

    def test_does_not_escalate_fresh_row(self, db, member):
        from apps.update_workflow.services import (
            escalate_stale_change_requests,
        )
        req = _draft(member)
        submit_change_request(req)
        # SLA deadline is in the future — submit_change_request just set it.
        counts = escalate_stale_change_requests()
        assert counts == {"candidates": 0, "escalated": 0}
        req.refresh_from_db()
        # Role unchanged from whatever the routing matrix returned.
        assert req.required_role != "district_m_and_e"

    def test_idempotent_on_re_run(self, db, member):
        from apps.update_workflow.services import (
            escalate_stale_change_requests,
        )
        self._stale(member)
        first = escalate_stale_change_requests()
        second = escalate_stale_change_requests()
        assert first["escalated"] == 1
        # Already at ESCALATION_ROLE -> excluded from the second sweep.
        assert second == {"candidates": 0, "escalated": 0}

    def test_escalate_emits_audit(self, db, member):
        from apps.update_workflow.services import (
            escalate_stale_change_requests,
        )
        req = self._stale(member, role="supervisor")
        escalate_stale_change_requests()
        events = list(
            AuditEvent.objects.filter(
                entity_type="change_request", entity_id=req.id,
                action="escalate",
            ),
        )
        assert len(events) == 1
        ev = events[0]
        assert ev.actor_id == "sla-auto-escalator"
        assert ev.field_changes["from_role"] == "supervisor"
        assert ev.field_changes["to_role"] == "district_m_and_e"

    def test_management_command_runs(self, db, member, capsys):
        from django.core.management import call_command
        self._stale(member)
        call_command("escalate_stale_change_requests")
        out = capsys.readouterr().out
        assert "escalated=1" in out

    def test_celery_task_runs(self, db, member):
        from apps.update_workflow.tasks import (
            escalate_stale_change_requests_task,
        )
        self._stale(member)
        result = escalate_stale_change_requests_task.run()
        assert result == {"candidates": 1, "escalated": 1}

    def test_beat_schedule_includes_escalation(self):
        from nsr_mis.celery import app
        tasks = {entry["task"] for entry in app.conf.beat_schedule.values()}
        assert (
            "apps.update_workflow.tasks.escalate_stale_change_requests_task"
            in tasks
        )


# --- US-S10-004 — bulk-action endpoints ----------------------------------


class TestBulkActions:
    """Bulk endpoints run rows through the same services as per-row.
    Guards (no-self-approve, wrong state, missing reason) surface as
    `skipped` per row; out-of-scope ids surface as `not_found`."""

    @pytest.fixture
    def staff_user(self, db, django_user_model):
        return django_user_model.objects.create_user(
            username="reviewer", password="p",
            is_staff=True, is_superuser=True,
        )

    @pytest.fixture
    def api_client(self, staff_user):
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(user=staff_user)
        return c

    def _submitted(self, member, *, requester="enum-a"):
        req = _draft(member, requester=requester)
        submit_change_request(req)
        return req

    def test_bulk_approve_commits_all_eligible(self, db, member, api_client):
        a = self._submitted(member, requester="enum-1")
        # Second CR — different surname to avoid concurrent edit clash.
        b = _draft(member, requester="enum-2",
                    changes={"first_name": {"old": "James", "new": "Jane"}})
        submit_change_request(b)
        r = api_client.post("/api/v1/upd/change-requests/bulk-approve/",
                             data={"ids": [a.id, b.id], "actor": "approver-x"},
                             format="json")
        assert r.status_code == 200
        assert set(r.data["acted"]) == {a.id, b.id}
        assert r.data["skipped"] == []
        assert r.data["not_found"] == []
        a.refresh_from_db()
        assert a.status == ChangeStatus.COMMITTED

    def test_bulk_reject_requires_reason(self, db, member, api_client):
        a = self._submitted(member)
        r = api_client.post("/api/v1/upd/change-requests/bulk-reject/",
                             data={"ids": [a.id], "actor": "approver-x"},
                             format="json")
        assert r.status_code == 400
        assert "reason" in r.data["detail"].lower()

    def test_bulk_reject_with_reason(self, db, member, api_client):
        a = self._submitted(member)
        r = api_client.post("/api/v1/upd/change-requests/bulk-reject/",
                             data={"ids": [a.id], "actor": "approver-x",
                                   "reason": "Insufficient evidence (AC-UPD-EVIDENCE)"},
                             format="json")
        assert r.status_code == 200
        assert r.data["acted"] == [a.id]
        a.refresh_from_db()
        assert a.status == ChangeStatus.REJECTED

    def test_bulk_skips_self_approve(self, db, member, api_client):
        """A row whose requester == actor must NOT be approved by the
        same actor; it lands in `skipped`."""
        a = self._submitted(member, requester="self")
        b = self._submitted(member, requester="someone-else")
        r = api_client.post("/api/v1/upd/change-requests/bulk-approve/",
                             data={"ids": [a.id, b.id], "actor": "self"},
                             format="json")
        assert r.status_code == 200
        # 'b' acted (different requester), 'a' skipped (self-approve).
        assert b.id in r.data["acted"]
        skipped_ids = {s["id"] for s in r.data["skipped"]}
        assert a.id in skipped_ids
        skipped_reasons = " ".join(s["reason"] for s in r.data["skipped"])
        assert "NO-SELF-APPROVE" in skipped_reasons

    def test_bulk_skips_wrong_state(self, db, member, api_client):
        """A DRAFT row (not submitted) can't be approved — bulk should
        skip without aborting the batch."""
        draft = _draft(member)  # status=DRAFT, not SUBMITTED
        submitted = self._submitted(member, requester="other")
        r = api_client.post("/api/v1/upd/change-requests/bulk-approve/",
                             data={"ids": [draft.id, submitted.id], "actor": "approver"},
                             format="json")
        assert r.status_code == 200
        assert submitted.id in r.data["acted"]
        assert any(s["id"] == draft.id for s in r.data["skipped"])

    def test_unknown_id_reports_not_found(self, db, member, api_client):
        a = self._submitted(member)
        unknown = "01ABSENT00000000000000000A"
        r = api_client.post("/api/v1/upd/change-requests/bulk-approve/",
                             data={"ids": [a.id, unknown], "actor": "approver"},
                             format="json")
        assert r.status_code == 200
        assert r.data["acted"] == [a.id]
        assert r.data["not_found"] == [unknown]

    def test_bulk_escalate_bumps_role(self, db, member, api_client):
        from apps.update_workflow.services import ESCALATION_ROLE
        a = self._submitted(member)
        r = api_client.post("/api/v1/upd/change-requests/bulk-escalate/",
                             data={"ids": [a.id], "actor": "supervisor"},
                             format="json")
        assert r.status_code == 200
        assert r.data["acted"] == [a.id]
        a.refresh_from_db()
        assert a.required_role == ESCALATION_ROLE

    def test_bulk_caps_batch_size(self, db, member, api_client):
        """The serializer caps `ids` at 200 items so a runaway client
        can't queue an unbounded batch."""
        a = self._submitted(member)
        big = [a.id] + [f"01ABSENT{i:018d}" for i in range(250)]
        r = api_client.post("/api/v1/upd/change-requests/bulk-approve/",
                             data={"ids": big, "actor": "approver"},
                             format="json")
        assert r.status_code == 400


# --- US-S22-001 — hold / release / me endpoints --------------------------


class TestHoldReleaseEndpoints:
    """Per-row hold and release POSTs. Mirror the reject endpoint:
    {actor, reason}; guards from the services surface as 400."""

    @pytest.fixture
    def staff_user(self, db, django_user_model):
        return django_user_model.objects.create_user(
            username="reviewer", password="p",
            is_staff=True, is_superuser=True,
        )

    @pytest.fixture
    def api_client(self, staff_user):
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(user=staff_user)
        return c

    def _submitted(self, member, *, requester="enum-a"):
        req = _draft(member, requester=requester)
        submit_change_request(req)
        return req

    def test_hold_endpoint_parks_request(self, db, member, api_client):
        req = self._submitted(member)
        r = api_client.post(
            f"/api/v1/upd/change-requests/{req.id}/hold/",
            data={"actor": "reviewer", "reason": "awaiting birth certificate"},
            format="json",
        )
        assert r.status_code == 200
        assert r.data["status"] == ChangeStatus.ON_HOLD
        req.refresh_from_db()
        assert req.status == ChangeStatus.ON_HOLD

    def test_hold_endpoint_400_on_missing_reason(self, db, member, api_client):
        req = self._submitted(member)
        r = api_client.post(
            f"/api/v1/upd/change-requests/{req.id}/hold/",
            data={"actor": "reviewer"},
            format="json",
        )
        assert r.status_code == 400

    def test_hold_endpoint_400_on_self(self, db, member, api_client):
        req = self._submitted(member, requester="self-actor")
        r = api_client.post(
            f"/api/v1/upd/change-requests/{req.id}/hold/",
            data={"actor": "self-actor", "reason": "x"},
            format="json",
        )
        assert r.status_code == 400
        assert "NO-SELF-APPROVE" in r.data["detail"]

    def test_release_endpoint_reopens(self, db, member, api_client):
        req = self._submitted(member)
        hold_change_request(req, approver="reviewer-1", reason="x")
        r = api_client.post(
            f"/api/v1/upd/change-requests/{req.id}/release/",
            data={"actor": "reviewer-2"},
            format="json",
        )
        assert r.status_code == 200
        assert r.data["status"] == ChangeStatus.PENDING_APPROVAL

    def test_release_endpoint_400_when_not_on_hold(self, db, member, api_client):
        req = self._submitted(member)
        r = api_client.post(
            f"/api/v1/upd/change-requests/{req.id}/release/",
            data={"actor": "reviewer"},
            format="json",
        )
        assert r.status_code == 400


class TestMeEndpoint:
    """GET /me/ returns the requesting user's identity for the React
    workbench to bind as `actor` in subsequent action POSTs."""

    def test_me_returns_username(self, db, django_user_model):
        from rest_framework.test import APIClient
        u = django_user_model.objects.create_user(username="florence", password="p")
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.get("/api/v1/upd/change-requests/me/")
        assert r.status_code == 200
        assert r.data["username"] == "florence"
        assert r.data["is_staff"] is False

    def test_me_requires_authentication(self, db):
        from rest_framework.test import APIClient
        r = APIClient().get("/api/v1/upd/change-requests/me/")
        assert r.status_code in (401, 403)


# --- US-S22-003 — Open-CR modal bundle endpoint + routing ---------------


class TestRoutingMatrixExtensions:
    """The Open-CR modal vocabulary (life_event / verification /
    address_move / roster_change / asset_change) has its own routing
    rows. The label-only map is operator-facing; the canonical
    required_role stays in DEFAULT_MATRIX for downstream sweeps."""

    def test_default_matrix_has_every_new_change_type(self):
        from apps.update_workflow.routing import DEFAULT_MATRIX
        for ct in [
            ChangeType.LIFE_EVENT, ChangeType.VERIFICATION,
            ChangeType.ADDRESS_MOVE, ChangeType.ROSTER_CHANGE,
            ChangeType.ASSET_CHANGE,
        ]:
            assert (ct, False) in DEFAULT_MATRIX
            assert (ct, True) in DEFAULT_MATRIX

    def test_route_label_spec_matrix(self):
        from apps.update_workflow.routing import route_label
        # Spec table: correction / life_event / verification
        assert route_label(ChangeType.CORRECTION, pmt_relevant=False) == "CDO (parish)"
        assert route_label(ChangeType.CORRECTION, pmt_relevant=True)  == "M&E Officer"
        assert route_label(ChangeType.LIFE_EVENT,  pmt_relevant=False) == "CDO (parish)"
        assert route_label(ChangeType.LIFE_EVENT,  pmt_relevant=True)  == "M&E Officer"
        assert route_label(ChangeType.VERIFICATION, pmt_relevant=False) == "CDO (parish)"
        assert route_label(ChangeType.VERIFICATION, pmt_relevant=True)  == "M&E Officer"

    def test_route_label_address_move(self):
        from apps.update_workflow.routing import route_label
        assert (route_label(ChangeType.ADDRESS_MOVE, pmt_relevant=False)
                == "CDO + receiving CDO")
        assert (route_label(ChangeType.ADDRESS_MOVE, pmt_relevant=True)
                == "District M&E")

    def test_route_label_roster_and_asset_changes(self):
        from apps.update_workflow.routing import route_label
        for ct in [ChangeType.ROSTER_CHANGE, ChangeType.ASSET_CHANGE]:
            assert route_label(ct, pmt_relevant=False) == "CDO (parish)"
            assert route_label(ct, pmt_relevant=True)  == "District M&E"

    def test_route_label_falls_back_to_role_for_legacy(self):
        from apps.update_workflow.routing import route_label
        # ADDITION isn't in the spec matrix; falls back to the
        # canonical role name from DEFAULT_MATRIX.
        assert route_label(ChangeType.ADDITION, pmt_relevant=False) == "parish_chief"


class TestFieldCatalog:
    """Server-side catalog matches the spec's minimum field list."""

    def test_catalog_has_every_required_category(self):
        from apps.update_workflow.field_catalog import category_keys
        assert category_keys() == {"iden", "loc", "rost", "hd", "ed", "emp", "hous", "food"}

    def test_pmt_relevance_on_housing_fields(self):
        from apps.update_workflow.field_catalog import is_pmt_relevant
        for f in ["roof", "wall", "floor", "water", "toilet", "fuel", "light",
                  "tenure", "land_acres", "cattle", "goats", "radio", "tv",
                  "phone_owned"]:
            assert is_pmt_relevant("hous", f), f

    def test_pmt_relevance_negative_on_iden(self):
        from apps.update_workflow.field_catalog import is_pmt_relevant
        for f in ["phone", "email", "head_name", "head_nin", "lang"]:
            assert not is_pmt_relevant("iden", f), f

    def test_validate_row_raises_on_unknown(self):
        from apps.update_workflow.field_catalog import validate_row
        with pytest.raises(ValueError, match="unknown category"):
            validate_row("nope", "roof")
        with pytest.raises(ValueError, match="unknown field"):
            validate_row("hous", "rooftop")


class TestBundleEndpoint:
    """POST /api/v1/upd/change-requests/bundle/ — accepts the modal
    payload, builds one ChangeRequest in PENDING_APPROVAL, returns
    {cr_id, audit_id, routed_to, ...}."""

    @pytest.fixture
    def staff_user(self, db, django_user_model):
        return django_user_model.objects.create_user(
            username="reviewer", password="p",
            is_staff=True, is_superuser=True,
        )

    @pytest.fixture
    def api_client(self, staff_user):
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(user=staff_user)
        return c

    def _payload(self, household, **over):
        base = {
            "household_id": household.id,
            "entity": "household",
            "change_type": "correction",
            "pmt_relevant": False,
            "rows": [{"category": "iden", "field": "phone",
                       "new_value": "+256 700 000 000"}],
            "note": "Phone updated per field visit.",
        }
        base.update(over)
        return base

    def test_creates_pending_approval_cr_and_returns_routing(self, household, api_client):
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=self._payload(household), format="json")
        assert r.status_code == 201, r.data
        assert r.data["status"] == ChangeStatus.PENDING_APPROVAL
        assert r.data["routed_to"] == "CDO (parish)"
        assert r.data["pmt_relevant"] is False
        assert r.data["changes"] == 1
        # CR persisted with the changes JSON.
        cr = ChangeRequest.objects.get(pk=r.data["cr_id"])
        assert cr.changes == {"phone": {"old": "", "new": "+256 700 000 000"}}
        assert cr.status == ChangeStatus.PENDING_APPROVAL

    def test_auto_derives_pmt_relevant_from_rows(self, household, api_client):
        payload = self._payload(household, rows=[
            {"category": "hous", "field": "roof", "new_value": "Tiles"},
        ])
        # pmt_relevant=False at the API layer; server auto-bumps to
        # True because roof is PMT-relevant in the catalog.
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 201, r.data
        assert r.data["pmt_relevant"] is True
        assert r.data["routed_to"] == "M&E Officer"

    def test_emits_audit_event_and_returns_audit_id(self, household, api_client):
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=self._payload(household), format="json")
        assert r.data["audit_id"]  # non-empty
        ev = AuditEvent.objects.get(id=r.data["audit_id"])
        assert ev.entity_type == "change_request"
        assert ev.entity_id == r.data["cr_id"]
        assert ev.action == "submit"

    def test_address_move_label(self, household, api_client):
        payload = self._payload(household, change_type="address_move", rows=[
            {"category": "loc", "field": "village", "new_value": "Lopuwapuwa B"},
        ])
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 201
        assert r.data["routed_to"] == "CDO + receiving CDO"

    def test_rejects_empty_rows(self, household, api_client):
        payload = self._payload(household, rows=[])
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 400

    def test_rejects_short_note(self, household, api_client):
        payload = self._payload(household, note="hi")
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 400

    def test_rejects_unknown_field(self, household, api_client):
        payload = self._payload(household, rows=[
            {"category": "hous", "field": "rooftop", "new_value": "x"},
        ])
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 400

    def test_rejects_duplicate_rows(self, household, api_client):
        payload = self._payload(household, rows=[
            {"category": "iden", "field": "phone", "new_value": "+256 700 111 111"},
            {"category": "iden", "field": "phone", "new_value": "+256 700 222 222"},
        ])
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 400
        assert "duplicate" in str(r.data).lower()

    def test_member_entity_requires_member_id(self, household, api_client):
        payload = self._payload(
            household, entity="member",
            rows=[{"category": "hd", "field": "chronic", "new_value": "yes"}],
        )
        # member_id omitted
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 400
        assert "member_id" in str(r.data).lower()

    def test_member_entity_validates_membership(self, household, member, api_client):
        # member_id is a real ULID but doesn't belong to the named household.
        bogus = "01HBOGUS00000000000000000Z"
        payload = self._payload(
            household, entity="member", member_id=bogus,
            rows=[{"category": "hd", "field": "chronic", "new_value": "yes"}],
        )
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 400
        assert "does not belong" in str(r.data).lower()

    def test_member_entity_rejects_household_scope_fields(self, household, member, api_client):
        payload = self._payload(
            household, entity="member", member_id=member.id,
            rows=[{"category": "iden", "field": "phone",
                    "new_value": "+256 700 999 999"}],
        )
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 400
        assert "member-scope" in str(r.data).lower() or "household-scope" in str(r.data).lower()

    def test_household_entity_rejects_member_scope_fields(self, household, api_client):
        payload = self._payload(
            household, entity="household",
            rows=[{"category": "hd", "field": "chronic", "new_value": "yes"}],
        )
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 400
        assert "member-scope" in str(r.data).lower()

    def test_member_entity_creates_member_cr(self, household, member, api_client):
        payload = self._payload(
            household, entity="member", member_id=member.id,
            rows=[{"category": "hd", "field": "chronic", "new_value": "yes"}],
            note="Diagnosed during clinic visit last week.",
        )
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 201, r.data
        cr = ChangeRequest.objects.get(pk=r.data["cr_id"])
        assert cr.entity_type == EntityType.MEMBER
        assert cr.entity_id == member.id
        assert cr.status == "pending_approval"

    def test_documents_attach_evidence_rows_and_blob(self, household, api_client):
        import base64
        import hashlib

        body = b"%PDF-1.4 fake pdf bytes for the test"
        b64 = base64.b64encode(body).decode("ascii")
        payload = self._payload(
            household,
            documents=[{
                "filename": "clinic-card.pdf",
                "content_type": "application/pdf",
                "data_base64": b64,
            }],
        )
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 201, r.data
        cr = ChangeRequest.objects.get(pk=r.data["cr_id"])
        # One note row + one document row.
        kinds = [e["kind"] for e in cr.evidence]
        assert "document" in kinds
        doc_row = next(e for e in cr.evidence if e["kind"] == "document")
        assert doc_row["filename"] == "clinic-card.pdf"
        assert doc_row["content_type"] == "application/pdf"
        assert doc_row["size"] == len(body)
        assert doc_row["sha256"] == hashlib.sha256(body).hexdigest()

        # And the blob is retrievable from the storage backend.
        from apps.update_workflow.evidence_storage import get_evidence_storage
        assert get_evidence_storage().get(doc_row["sha256"]) == body

    def test_documents_reject_unsupported_mime(self, household, api_client):
        import base64

        payload = self._payload(
            household,
            documents=[{
                "filename": "evil.exe",
                "content_type": "application/x-msdownload",
                "data_base64": base64.b64encode(b"MZ\x90").decode("ascii"),
            }],
        )
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 400
        assert "content_type" in str(r.data).lower()

    def test_documents_reject_oversized_file(self, household, api_client):
        import base64

        body = b"x" * (5 * 1024 * 1024 + 1)
        payload = self._payload(
            household,
            documents=[{
                "filename": "huge.pdf",
                "content_type": "application/pdf",
                "data_base64": base64.b64encode(body).decode("ascii"),
            }],
        )
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 400
        assert "max per file" in str(r.data).lower()

    def test_documents_reject_more_than_three(self, household, api_client):
        import base64

        body = b"%PDF-1.4 tiny"
        b64 = base64.b64encode(body).decode("ascii")
        docs = [
            {"filename": f"f{i}.pdf", "content_type": "application/pdf",
             "data_base64": b64}
            for i in range(4)
        ]
        payload = self._payload(household, documents=docs)
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 400
        assert "at most" in str(r.data).lower()

    def test_documents_optional(self, household, api_client):
        # Submitting without documents stays the happy path.
        payload = self._payload(household)
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 201, r.data
        cr = ChangeRequest.objects.get(pk=r.data["cr_id"])
        assert all(e["kind"] != "document" for e in cr.evidence)

    def test_all_members_entity_records_intent_in_note(self, household, api_client):
        payload = self._payload(household, entity="all_members",
                                 note="Family migrated; update everyone")
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 201
        cr = ChangeRequest.objects.get(pk=r.data["cr_id"])
        assert cr.entity_type == EntityType.HOUSEHOLD
        assert "all_members" in cr.requester_note

    def test_multi_row_multi_category_payload(self, household, api_client):
        payload = self._payload(household, change_type="correction", rows=[
            {"category": "iden", "field": "phone",   "new_value": "+256 700 333 333"},
            {"category": "loc",  "field": "village", "new_value": "Lopuwapuwa A"},
            {"category": "hous", "field": "roof",    "new_value": "Tiles"},
        ])
        r = api_client.post("/api/v1/upd/change-requests/bundle/",
                             data=payload, format="json")
        assert r.status_code == 201
        assert r.data["changes"] == 3
        cr = ChangeRequest.objects.get(pk=r.data["cr_id"])
        assert set(cr.changes.keys()) == {"phone", "village", "roof"}
        assert r.data["pmt_relevant"] is True  # roof is PMT-relevant


class TestListFilters:
    """The Decided tab in the UPD workbench depends on the list
    endpoint narrowing by ?status=. django-filter isn't installed
    so `filterset_fields` is silently a no-op; the viewset filters
    manually in get_queryset(). These tests pin that behaviour."""

    @pytest.fixture
    def staff_user(self, db, django_user_model):
        return django_user_model.objects.create_user(
            username="reviewer-list", password="p",
            is_staff=True, is_superuser=True,
        )

    @pytest.fixture
    def api_client(self, staff_user):
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(user=staff_user)
        return c

    @pytest.fixture
    def fixture_set(self, db, member):
        """One pending, one committed, one rejected CR — minimal set
        to verify each filter value narrows the result list."""
        pending = _draft(member, requester="enum-pending")
        submit_change_request(pending)

        committed = _draft(member, requester="enum-committed",
                           changes={"first_name": {"old": "James", "new": "Jane"}})
        submit_change_request(committed)
        commit_change_request(committed, approver="reviewer-list")

        rejected = _draft(member, requester="enum-rejected",
                          changes={"telephone_1": {"old": "+256700000001", "new": "+256700000002"}})
        submit_change_request(rejected)
        reject_change_request(rejected, approver="reviewer-list", reason="not enough evidence")

        return {"pending": pending, "committed": committed, "rejected": rejected}

    def test_status_filter_pending(self, api_client, fixture_set):
        r = api_client.get("/api/v1/upd/change-requests/?status=pending_approval")
        assert r.status_code == 200
        ids = {row["id"] for row in r.data["results"]}
        assert ids == {fixture_set["pending"].id}

    def test_status_filter_committed(self, api_client, fixture_set):
        r = api_client.get("/api/v1/upd/change-requests/?status=committed")
        assert r.status_code == 200
        ids = {row["id"] for row in r.data["results"]}
        assert ids == {fixture_set["committed"].id}

    def test_status_filter_comma_separated(self, api_client, fixture_set):
        """Decided tab uses ?status=committed,rejected to get both
        terminal states in one round-trip."""
        r = api_client.get("/api/v1/upd/change-requests/?status=committed,rejected")
        assert r.status_code == 200
        ids = {row["id"] for row in r.data["results"]}
        assert ids == {fixture_set["committed"].id, fixture_set["rejected"].id}

    def test_status_filter_missing_returns_all(self, api_client, fixture_set):
        r = api_client.get("/api/v1/upd/change-requests/")
        assert r.status_code == 200
        ids = {row["id"] for row in r.data["results"]}
        assert ids == {fixture_set["pending"].id, fixture_set["committed"].id, fixture_set["rejected"].id}

    def test_entity_id_filter(self, api_client, fixture_set, member):
        """Household-detail Updates tab uses ?entity_id= to scope to
        a single record's CR history."""
        other = Member.objects.create(
            household=member.household, line_number=2,
            surname="Other", first_name="Person", sex="2",
        )
        unrelated = _draft(other, requester="enum-other")
        submit_change_request(unrelated)

        r = api_client.get(f"/api/v1/upd/change-requests/?entity_id={member.id}")
        assert r.status_code == 200
        ids = {row["id"] for row in r.data["results"]}
        assert unrelated.id not in ids
        assert ids == {
            fixture_set["pending"].id,
            fixture_set["committed"].id,
            fixture_set["rejected"].id,
        }


# --- US-S28-CATALOG — field catalog endpoint -------------------------------


class TestFieldCatalogEndpoint:
    """GET /api/v1/upd/field-catalog/ — single round-trip used by the
    Open-CR modal. Tagged select fields (`choice_list`) get options
    resolved against the active ChoiceList version at request time."""

    @pytest.fixture
    def staff_user(self, db, django_user_model):
        return django_user_model.objects.create_user(
            username="catalog-reader", password="p",
            is_staff=True, is_superuser=True,
        )

    @pytest.fixture
    def api_client(self, staff_user):
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(user=staff_user)
        return c

    # rural_urban v1 is seeded by migration 0003_seed_choice_lists with
    # 1=Urban, 2=Rural in English. The tests below exercise the
    # resolver against that real seed, NOT a fixture — so a future
    # migration that breaks the seed gets caught here.

    def test_returns_every_catalog_category(self, db, api_client):
        from apps.update_workflow.field_catalog import CATEGORIES
        r = api_client.get("/api/v1/upd/field-catalog/")
        assert r.status_code == 200
        returned_keys = {c["key"] for c in r.data["categories"]}
        assert returned_keys == {c["key"] for c in CATEGORIES}

    def test_select_field_with_choice_list_resolves_to_choicelist_labels(
        self, db, api_client,
    ):
        """urban_rural is tagged `choice_list: "rural_urban"`. The
        active seed ships 1=Urban, 2=Rural — options must come back
        as {code, label} pairs with those labels, NOT the bare codes."""
        from apps.reference_data.services import clear_resolver_cache
        clear_resolver_cache()
        r = api_client.get("/api/v1/upd/field-catalog/")
        assert r.status_code == 200
        loc = next(c for c in r.data["categories"] if c["key"] == "loc")
        urban_rural = next(f for f in loc["fields"] if f["key"] == "urban_rural")
        assert urban_rural["type"] == "select"
        assert urban_rural["choice_list"] == "rural_urban"
        assert urban_rural["options"] == [
            {"code": "1", "label": "Urban"},
            {"code": "2", "label": "Rural"},
        ]

    def test_select_field_without_choice_list_falls_back_to_hardcoded(
        self, db, api_client,
    ):
        """Legacy select fields whose labels haven't been promoted to
        a ChoiceList ship their hardcoded `options` array as {code,
        label} pairs where code == label."""
        r = api_client.get("/api/v1/upd/field-catalog/")
        assert r.status_code == 200
        hous = next(c for c in r.data["categories"] if c["key"] == "hous")
        roof = next(f for f in hous["fields"] if f["key"] == "roof")
        assert roof["type"] == "select"
        assert roof.get("choice_list") is None
        assert roof["options"][0] == {"code": "Iron sheets", "label": "Iron sheets"}

    def test_choice_list_retired_falls_back_to_hardcoded(self, db, api_client):
        """If the rural_urban ChoiceList is retired (no active row),
        the endpoint falls back to the field's hardcoded options.
        Codes stay correct; labels equal codes — the modal still
        renders something usable."""
        from apps.reference_data.models import ChoiceList, ChoiceListStatus
        from apps.reference_data.services import clear_resolver_cache
        ChoiceList.objects.filter(list_name="rural_urban").update(
            status=ChoiceListStatus.RETIRED,
        )
        clear_resolver_cache()

        r = api_client.get("/api/v1/upd/field-catalog/")
        assert r.status_code == 200
        loc = next(c for c in r.data["categories"] if c["key"] == "loc")
        urban_rural = next(f for f in loc["fields"] if f["key"] == "urban_rural")
        assert urban_rural["options"] == [
            {"code": "1", "label": "1"},
            {"code": "2", "label": "2"},
        ]

    def test_member_entity_field_carries_entity_flag(self, db, api_client):
        r = api_client.get("/api/v1/upd/field-catalog/")
        rost = next(c for c in r.data["categories"] if c["key"] == "rost")
        sex = next(f for f in rost["fields"] if f["key"] == "member_sex")
        assert sex["entity"] == "member"

    def test_household_default_entity(self, db, api_client):
        r = api_client.get("/api/v1/upd/field-catalog/")
        iden = next(c for c in r.data["categories"] if c["key"] == "iden")
        phone = next(f for f in iden["fields"] if f["key"] == "phone")
        assert phone["entity"] == "household"

    def test_etag_cache_returns_304(self, db, api_client):
        r1 = api_client.get("/api/v1/upd/field-catalog/")
        assert r1.status_code == 200
        etag = r1["ETag"]
        r2 = api_client.get("/api/v1/upd/field-catalog/", HTTP_IF_NONE_MATCH=etag)
        assert r2.status_code == 304
        assert r2["ETag"] == etag

    def test_lang_param_changes_resolved_labels(self, db, api_client):
        """Add a Luganda label to the existing rural_urban v1 options.
        ?lang=lg returns the Luganda labels; English remains default."""
        from apps.reference_data.models import ChoiceList, ChoiceOption
        from apps.reference_data.services import clear_resolver_cache
        cl = ChoiceList.objects.get(list_name="rural_urban", version=1)
        ChoiceOption.objects.create(
            choice_list=cl, code="1", label="Ekibuga", language="lg",
            sort_order=1, status=ChoiceOption.Status.ACTIVE,
        )
        ChoiceOption.objects.create(
            choice_list=cl, code="2", label="Bya kyalo", language="lg",
            sort_order=2, status=ChoiceOption.Status.ACTIVE,
        )
        clear_resolver_cache()

        r = api_client.get("/api/v1/upd/field-catalog/?lang=lg")
        loc = next(c for c in r.data["categories"] if c["key"] == "loc")
        urban_rural = next(f for f in loc["fields"] if f["key"] == "urban_rural")
        assert urban_rural["options"] == [
            {"code": "1", "label": "Ekibuga"},
            {"code": "2", "label": "Bya kyalo"},
        ]

    def test_requires_authentication(self, db):
        from rest_framework.test import APIClient
        r = APIClient().get("/api/v1/upd/field-catalog/")
        assert r.status_code in (401, 403)

    def test_numeric_field_carries_constraints(self, db, api_client):
        """hh_size is constrained {min:1, max:30, step:1} per the
        questionnaire. The endpoint must pass this through unchanged
        so the modal's HTML5 number input can advertise them."""
        r = api_client.get("/api/v1/upd/field-catalog/")
        rost = next(c for c in r.data["categories"] if c["key"] == "rost")
        hh_size = next(f for f in rost["fields"] if f["key"] == "hh_size")
        assert hh_size["constraints"] == {"min": 1, "max": 30, "step": 1}

    def test_decimal_step_passes_through(self, db, api_client):
        """land_acres allows fractional acres — step=0.1 must come
        through as a number, not coerced to an int."""
        r = api_client.get("/api/v1/upd/field-catalog/")
        hous = next(c for c in r.data["categories"] if c["key"] == "hous")
        land = next(f for f in hous["fields"] if f["key"] == "land_acres")
        assert land["constraints"] == {"min": 0, "step": 0.1}

    def test_date_field_max_today_sentinel(self, db, api_client):
        """member_dob declares max_today=True so the modal computes
        today's date dynamically — birthdays can't be in the future.
        The wire shape preserves the sentinel; the modal resolves it."""
        r = api_client.get("/api/v1/upd/field-catalog/")
        rost = next(c for c in r.data["categories"] if c["key"] == "rost")
        dob = next(f for f in rost["fields"] if f["key"] == "member_dob")
        assert dob["constraints"] == {"min": "1900-01-01", "max_today": True}

    def test_unconstrained_field_has_no_constraints_key(self, db, api_client):
        """Fields that don't define constraints (most text / select)
        ship without the key — modal RowInput treats missing
        constraints as unconstrained."""
        r = api_client.get("/api/v1/upd/field-catalog/")
        iden = next(c for c in r.data["categories"] if c["key"] == "iden")
        phone = next(f for f in iden["fields"] if f["key"] == "phone")
        assert "constraints" not in phone
