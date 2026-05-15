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
    post_change_committed,
    reject_change_request,
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
        urban_rural="rural", address_narrative="Plot 1",
    )


@pytest.fixture
def member(db, household):
    return Member.objects.create(
        household=household, line_number=1, surname="Okot", first_name="James",
        sex="M", telephone_1="+256700000001",
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
            changes={"nin_status": {"old": "unknown", "new": "verified"}},
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
            changes={"nin_status": {"old": "unknown", "new": "verified"}},
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
            changes={"nin_status": {"old": "unknown", "new": "verified"}},
        )
        auto_commit_change_request(req, sample_rate=1.0)
        req.refresh_from_db()
        assert req.sampled_for_audit is True

    def test_sample_rate_0_never_flags(self, member):
        req = _draft(
            member, ctype=ChangeType.VITAL_EVENT,
            changes={"nin_status": {"old": "unknown", "new": "verified"}},
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
