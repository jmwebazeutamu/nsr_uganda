"""GRM workflow tests."""

from __future__ import annotations

import pytest

from apps.grievance.models import (
    Category,
    Grievance,
    GrievanceStatus,
    TaskStatus,
    Tier,
)
from apps.grievance.services import (
    GrievanceError,
    assign,
    close,
    create_task,
    escalate,
    open_change_request_for_grievance,
    open_grievance,
    resolve,
    transition_task,
)


class TestOpenGrievance:
    def test_open_default_l1(self, db):
        g = open_grievance(
            category=Category.DATA_CORRECTION,
            description="Wrong head name",
            reporter_name="Sarah",
        )
        assert g.tier == Tier.L1_PARISH_CHIEF
        assert g.status == GrievanceStatus.OPEN
        assert g.sla_deadline is not None
        # 24h SLA for L1.
        assert (g.sla_deadline - g.opened_at).total_seconds() == 24 * 3600

    def test_open_unknown_category_raises(self, db):
        with pytest.raises(GrievanceError, match="unknown category"):
            open_grievance(category="not_a_category", description="x")

    def test_open_records_household_pointer(self, db):
        g = open_grievance(
            category=Category.EXCLUSION_ERROR, description="Missed",
            household_id="01HXY7K3B2N9PVQE4M6FZRWS18",
        )
        assert g.household_id == "01HXY7K3B2N9PVQE4M6FZRWS18"


class TestAssign:
    def test_assign_moves_to_in_progress(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        assign(g, assigned_to="parish-chief-3", actor="supervisor-1")
        g.refresh_from_db()
        assert g.status == GrievanceStatus.IN_PROGRESS
        assert g.assigned_to == "parish-chief-3"

    def test_cannot_assign_resolved(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        resolve(g, actor="a", narrative="fixed")
        with pytest.raises(GrievanceError, match="cannot assign"):
            assign(g, assigned_to="anyone", actor="anyone")


class TestEscalate:
    def test_l1_escalates_to_l2(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        escalate(g, actor="parish-chief-3", reason="needs CDO sign-off")
        g.refresh_from_db()
        assert g.tier == Tier.L2_CDO
        assert g.status == GrievanceStatus.ESCALATED
        # SLA window resets to 48h for L2.
        assert (g.sla_deadline - g.opened_at).total_seconds() == 48 * 3600

    def test_cannot_escalate_beyond_l4(self, db):
        g = open_grievance(
            category=Category.OTHER, description="x", tier=Tier.L4_NSR_UNIT,
        )
        with pytest.raises(GrievanceError, match="L4"):
            escalate(g, actor="nsr-coordinator", reason="anything")

    def test_escalate_requires_reason(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        with pytest.raises(GrievanceError, match="non-empty reason"):
            escalate(g, actor="op", reason="")

    def test_cannot_escalate_resolved(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        resolve(g, actor="a", narrative="fixed")
        with pytest.raises(GrievanceError, match="cannot escalate"):
            escalate(g, actor="b", reason="too late")


class TestResolve:
    def test_resolve_records_narrative_and_timestamp(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        resolve(g, actor="parish-chief-3", narrative="Spoke to the head")
        g.refresh_from_db()
        assert g.status == GrievanceStatus.RESOLVED
        assert g.resolved_at is not None
        assert "head" in g.resolution_narrative

    def test_resolve_records_linked_upd(self, db):
        g = open_grievance(category=Category.DATA_CORRECTION, description="x")
        resolve(g, actor="cdo-1", narrative="Linked to UPD",
                linked_change_request_id="01HXYUPDCHANGEREQUESTID000")
        g.refresh_from_db()
        assert g.linked_change_request_id == "01HXYUPDCHANGEREQUESTID000"

    def test_resolve_requires_narrative(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        with pytest.raises(GrievanceError, match="narrative"):
            resolve(g, actor="op", narrative="")

    def test_resolve_refused_when_open_tasks_exist(self, db):
        """US-S21-003 — every task must be CLOSED before resolve."""
        g = open_grievance(category=Category.OTHER, description="x")
        create_task(g, title="Visit reporter", description="",
                    assigned_to="cdo-1", actor="officer")
        with pytest.raises(GrievanceError, match="task"):
            resolve(g, actor="officer", narrative="ok")

    def test_resolve_succeeds_after_all_tasks_closed(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        t1 = create_task(g, title="A", description="", assigned_to="u1",
                         actor="officer")
        t2 = create_task(g, title="B", description="", assigned_to="u2",
                         actor="officer")
        transition_task(t1, new_status=TaskStatus.CLOSED, actor="u1")
        transition_task(t2, new_status=TaskStatus.CLOSED, actor="u2")
        resolve(g, actor="officer", narrative="done")
        g.refresh_from_db()
        assert g.status == GrievanceStatus.RESOLVED


class TestGrievanceTask:
    """US-S21-003 — task model + state machine. Tasks attach to a
    grievance and gate the resolve transition."""

    def test_create_task_records_audit(self, db):
        from apps.security.models import AuditEvent
        g = open_grievance(category=Category.OTHER, description="x")
        t = create_task(g, title="Visit reporter", description="bring NIN",
                        assigned_to="parish-chief-3", actor="officer")
        assert t.grievance_id == g.id
        assert t.status == TaskStatus.OPEN
        assert t.assigned_to == "parish-chief-3"
        assert t.created_by == "officer"
        assert AuditEvent.objects.filter(
            entity_type="grievance.task", action="create",
            entity_id=t.id,
        ).exists()

    def test_create_task_refused_on_resolved_grievance(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        resolve(g, actor="o", narrative="done")
        with pytest.raises(GrievanceError, match="cannot add task"):
            create_task(g, title="t", description="", assigned_to="u",
                        actor="officer")

    def test_create_task_requires_assignee(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        with pytest.raises(GrievanceError, match="assigned"):
            create_task(g, title="t", description="", assigned_to="",
                        actor="officer")

    def test_transition_open_to_in_progress_to_closed(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        t = create_task(g, title="t", description="", assigned_to="u",
                        actor="o")
        t = transition_task(t, new_status=TaskStatus.IN_PROGRESS, actor="u")
        assert t.status == TaskStatus.IN_PROGRESS
        t = transition_task(t, new_status=TaskStatus.CLOSED, actor="u")
        assert t.status == TaskStatus.CLOSED
        assert t.closed_at is not None
        assert t.closed_by == "u"

    def test_transition_closed_to_open_refused(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        t = create_task(g, title="t", description="", assigned_to="u",
                        actor="o")
        transition_task(t, new_status=TaskStatus.CLOSED, actor="u")
        with pytest.raises(GrievanceError, match="not allowed"):
            transition_task(t, new_status=TaskStatus.OPEN, actor="u")

    def test_transition_unknown_status_refused(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        t = create_task(g, title="t", description="", assigned_to="u",
                        actor="o")
        with pytest.raises(GrievanceError, match="unknown task status"):
            transition_task(t, new_status="weird", actor="u")

    def test_transition_records_audit(self, db):
        from apps.security.models import AuditEvent
        g = open_grievance(category=Category.OTHER, description="x")
        t = create_task(g, title="t", description="", assigned_to="u",
                        actor="o")
        before = AuditEvent.objects.filter(
            entity_type="grievance.task", action="update",
        ).count()
        transition_task(t, new_status=TaskStatus.IN_PROGRESS, actor="u")
        after = AuditEvent.objects.filter(
            entity_type="grievance.task", action="update",
        ).count()
        assert after == before + 1


# --- US-S21-003b: API visibility + task endpoints --------------------------

class TestGrievanceVisibility:
    """The Grievance list endpoint narrows by role:
    - GRM Officer group + superuser → see every row.
    - Other authenticated users → see only rows they own (assigned_to)
      or hold an open/in-progress task on.
    - Anonymous → see nothing.
    """

    @pytest.fixture
    def _users(self, db, django_user_model):
        from django.contrib.auth.models import Group
        officer = django_user_model.objects.create_user(
            username="officer", password="p", is_staff=True,
        )
        officer.groups.add(Group.objects.get(name="GRM Officer"))
        regular = django_user_model.objects.create_user(
            username="parish-chief-1", password="p", is_staff=True,
        )
        outsider = django_user_model.objects.create_user(
            username="outsider", password="p", is_staff=True,
        )
        return officer, regular, outsider

    @pytest.fixture
    def _seeded(self, db, _users):
        # g_mine: assigned to parish-chief-1.
        # g_task: parish-chief-1 holds a task on it.
        # g_other: belongs to a third party, no overlap.
        g_mine = open_grievance(
            category=Category.OTHER, description="mine",
            assigned_to="parish-chief-1",
        )
        g_task = open_grievance(category=Category.OTHER, description="task")
        create_task(g_task, title="visit", description="",
                    assigned_to="parish-chief-1", actor="officer")
        g_other = open_grievance(category=Category.OTHER, description="other",
                                 assigned_to="someone-else")
        return g_mine, g_task, g_other

    def _client(self, user):
        from django.test import Client
        c = Client()
        c.force_login(user)
        return c

    def test_officer_sees_every_grievance(self, _seeded, _users):
        officer, _, _ = _users
        g_mine, g_task, g_other = _seeded
        r = self._client(officer).get("/api/v1/grm/grievances/?page_size=100")
        assert r.status_code == 200
        ids = {row["id"] for row in r.json()["results"]}
        assert {g_mine.id, g_task.id, g_other.id}.issubset(ids)

    def test_regular_user_sees_only_assigned_and_tasked(self, _seeded, _users):
        _, regular, _ = _users
        g_mine, g_task, g_other = _seeded
        r = self._client(regular).get("/api/v1/grm/grievances/?page_size=100")
        assert r.status_code == 200
        ids = {row["id"] for row in r.json()["results"]}
        assert g_mine.id in ids
        assert g_task.id in ids
        assert g_other.id not in ids

    def test_outsider_sees_nothing(self, _seeded, _users):
        _, _, outsider = _users
        r = self._client(outsider).get("/api/v1/grm/grievances/?page_size=100")
        assert r.status_code == 200
        assert r.json()["count"] == 0


class TestGrievanceTaskApi:
    """REST contract for /api/v1/grm/tasks/. Only GRM Officers can
    POST a new task; only the assignee (or an officer) can transition."""

    @pytest.fixture
    def _users(self, db, django_user_model):
        from django.contrib.auth.models import Group
        officer = django_user_model.objects.create_user(
            username="officer", password="p", is_staff=True,
        )
        officer.groups.add(Group.objects.get(name="GRM Officer"))
        regular = django_user_model.objects.create_user(
            username="assignee-1", password="p", is_staff=True,
        )
        return officer, regular

    @pytest.fixture
    def _grievance(self, db, _users):
        return open_grievance(category=Category.OTHER, description="x")

    def _client(self, user):
        from django.test import Client
        c = Client()
        c.force_login(user)
        return c

    def test_officer_creates_task(self, _grievance, _users):
        officer, _ = _users
        r = self._client(officer).post(
            "/api/v1/grm/tasks/",
            data={
                "grievance": _grievance.id,
                "title": "Visit reporter",
                "description": "Bring NIN",
                "assigned_to": "assignee-1",
            },
            content_type="application/json",
        )
        assert r.status_code == 201, r.content
        assert r.json()["grievance"] == _grievance.id
        assert r.json()["status"] == "open"

    def test_non_officer_cannot_create_task(self, _grievance, _users):
        _, regular = _users
        r = self._client(regular).post(
            "/api/v1/grm/tasks/",
            data={
                "grievance": _grievance.id,
                "title": "t", "description": "",
                "assigned_to": "anyone",
            },
            content_type="application/json",
        )
        assert r.status_code == 403

    def test_assignee_can_transition_their_task(self, _grievance, _users):
        officer, regular = _users
        # Officer scopes the task onto the assignee.
        t = create_task(_grievance, title="t", description="",
                        assigned_to="assignee-1", actor="officer")
        r = self._client(regular).post(
            f"/api/v1/grm/tasks/{t.id}/transition/",
            data={"new_status": "in_progress"},
            content_type="application/json",
        )
        assert r.status_code == 200, r.content
        t.refresh_from_db()
        assert t.status == "in_progress"

    def test_non_assignee_cannot_transition(self, _grievance, _users):
        """The queryset narrowing in get_queryset hides tasks the user
        doesn't own — so a regular user who's neither the assignee nor
        the grievance owner sees a 404 (REST convention: don't leak
        existence) rather than a 403."""
        _, regular = _users
        t = create_task(_grievance, title="t", description="",
                        assigned_to="someone-else", actor="officer")
        r = self._client(regular).post(
            f"/api/v1/grm/tasks/{t.id}/transition/",
            data={"new_status": "in_progress"},
            content_type="application/json",
        )
        assert r.status_code == 404

    def test_officer_can_transition_any_task(self, _grievance, _users):
        officer, _ = _users
        t = create_task(_grievance, title="t", description="",
                        assigned_to="someone-else", actor="officer")
        r = self._client(officer).post(
            f"/api/v1/grm/tasks/{t.id}/transition/",
            data={"new_status": "closed"},
            content_type="application/json",
        )
        assert r.status_code == 200
        t.refresh_from_db()
        assert t.status == "closed"

    def test_assignee_lists_only_their_tasks(self, _grievance, _users):
        _, regular = _users
        create_task(_grievance, title="mine", description="",
                    assigned_to="assignee-1", actor="officer")
        create_task(_grievance, title="not mine", description="",
                    assigned_to="someone-else", actor="officer")
        r = self._client(regular).get("/api/v1/grm/tasks/?page_size=100")
        assert r.status_code == 200
        titles = {row["title"] for row in r.json()["results"]}
        assert "mine" in titles
        assert "not mine" not in titles


class TestClose:
    def test_close_resolved(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        resolve(g, actor="op", narrative="ok")
        close(g, actor="supervisor")
        g.refresh_from_db()
        assert g.status == GrievanceStatus.CLOSED
        assert g.closed_at is not None

    def test_cannot_close_unresolved(self, db):
        g = open_grievance(category=Category.OTHER, description="x")
        with pytest.raises(GrievanceError, match="RESOLVED"):
            close(g, actor="op")


class TestGrmUpdLinkage:
    """SAD §4.4: a DATA_CORRECTION grievance auto-opens a linked UPD;
    the UPD's commit closes the grievance."""

    @pytest.fixture
    def household_with_member(self, db):
        from datetime import date

        from apps.data_management.models import Household, Member
        from apps.reference_data.models import GeographicUnit
        nodes = {}
        for level, key, parent in [
            ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
            ("county", "c", "d"), ("sub_county", "sc", "c"),
            ("parish", "p", "sc"), ("village", "v", "p"),
        ]:
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=f"GRM-{key.upper()}", name=key.title(),
                parent=nodes.get(parent), effective_from=date(2026, 1, 1),
            )
        hh = Household.objects.create(
            region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
            county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"], village=nodes["v"],
            urban_rural="rural",
        )
        m = Member.objects.create(
            household=hh, line_number=1, surname="Okot", first_name="James", sex="M",
        )
        return hh, m

    def test_auto_open_creates_draft_change_request(self, household_with_member):
        from apps.update_workflow.models import ChangeStatus
        hh, m = household_with_member
        g = open_grievance(
            category=Category.DATA_CORRECTION,
            description="Wrong surname",
            household_id=hh.id, member_id=m.id,
        )
        cr = open_change_request_for_grievance(
            g, requester="parish-chief-7",
            changes={"surname": {"old": "Okot", "new": "Okello"}},
        )
        assert cr.status == ChangeStatus.DRAFT
        assert cr.entity_id == m.id
        g.refresh_from_db()
        assert g.linked_change_request_id == cr.id

    def test_refuses_non_data_correction(self, household_with_member):
        hh, _ = household_with_member
        g = open_grievance(
            category=Category.OPERATOR_CONDUCT, description="x",
            household_id=hh.id,
        )
        with pytest.raises(GrievanceError, match="DATA_CORRECTION"):
            open_change_request_for_grievance(
                g, requester="op", changes={"surname": {"old": "x", "new": "y"}},
            )

    def test_refuses_double_link(self, household_with_member):
        hh, m = household_with_member
        g = open_grievance(
            category=Category.DATA_CORRECTION, description="x",
            household_id=hh.id, member_id=m.id,
        )
        open_change_request_for_grievance(
            g, requester="op",
            changes={"surname": {"old": "Okot", "new": "Okello"}},
        )
        with pytest.raises(GrievanceError, match="already linked"):
            open_change_request_for_grievance(
                g, requester="op",
                changes={"surname": {"old": "Okot", "new": "Okeyo"}},
            )

    def test_commit_of_linked_cr_closes_grievance(self, household_with_member):
        from apps.update_workflow.services import (
            commit_change_request,
            submit_change_request,
        )
        hh, m = household_with_member
        g = open_grievance(
            category=Category.DATA_CORRECTION, description="Wrong surname",
            household_id=hh.id, member_id=m.id,
        )
        cr = open_change_request_for_grievance(
            g, requester="parish-chief-7",
            changes={"surname": {"old": "Okot", "new": "Okello"}},
        )
        submit_change_request(cr)
        commit_change_request(cr, approver="cdo-3")
        g.refresh_from_db()
        assert g.status == GrievanceStatus.CLOSED
        assert g.closed_at is not None


class TestApi:
    def test_post_creates_and_assigns(self, db, django_user_model):
        from rest_framework.test import APIClient
        u = django_user_model.objects.create_user(
            username="op", password="p", is_superuser=True, is_staff=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.post("/api/v1/grm/grievances/", data={
            "category": Category.DATA_CORRECTION,
            "description": "Wrong surname",
            "reporter_name": "Sarah Nakato",
        }, format="json")
        assert r.status_code == 201
        gid = r.data["id"]
        # Assign
        r = c.post(f"/api/v1/grm/grievances/{gid}/assign/",
                   data={"actor": "supervisor-1", "assigned_to": "pc-3"},
                   format="json")
        assert r.status_code == 200
        assert r.data["status"] == GrievanceStatus.IN_PROGRESS
        assert Grievance.objects.get(pk=gid).assigned_to == "pc-3"


class TestOverdueAction:
    """SAD §4.4.7 framing — supervisors need a list of grievances past
    their tier SLA so they can intervene or escalate. The /overdue/
    action returns exactly those rows, ABAC-scoped through the
    household."""

    @pytest.fixture
    def overdue_and_fresh(self, db):
        from datetime import timedelta

        from django.utils import timezone

        from apps.grievance.models import Tier

        # 1 grievance whose SLA has already lapsed → overdue
        overdue = open_grievance(
            category=Category.DATA_CORRECTION, description="overdue case",
            tier=Tier.L1_PARISH_CHIEF,
        )
        overdue.sla_deadline = timezone.now() - timedelta(hours=1)
        overdue.save(update_fields=["sla_deadline"])

        # 1 grievance whose SLA is still in the future → not overdue
        fresh = open_grievance(
            category=Category.DATA_CORRECTION, description="fresh case",
            tier=Tier.L1_PARISH_CHIEF,
        )

        # 1 resolved grievance, even though past SLA — must NOT show up
        resolved_past = open_grievance(
            category=Category.OTHER, description="late but resolved",
        )
        resolved_past.sla_deadline = timezone.now() - timedelta(hours=2)
        resolved_past.status = GrievanceStatus.RESOLVED
        resolved_past.save(update_fields=["sla_deadline", "status"])

        return overdue, fresh, resolved_past

    def test_overdue_returns_only_open_past_due(
        self, overdue_and_fresh, django_user_model,
    ):
        from rest_framework.test import APIClient
        overdue, _, _ = overdue_and_fresh
        u = django_user_model.objects.create_user(
            username="supervisor", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.get("/api/v1/grm/grievances/overdue/")
        assert r.status_code == 200
        results = r.data["results"] if isinstance(r.data, dict) else r.data
        ids = {row["id"] for row in results}
        assert ids == {overdue.id}


class TestAdminWorkbench:
    """Supervisors should be able to triage from /admin/grievance/.
    The admin layer is a thin wrapper around services so the audit
    chain, signal wiring, and state guards are identical to the REST
    surface."""

    @pytest.fixture
    def staff_user(self, db, django_user_model):
        return django_user_model.objects.create_user(
            username="supervisor", password="p",
            is_staff=True, is_superuser=True,
        )

    @pytest.fixture
    def admin_client(self, staff_user):
        from django.test import Client
        c = Client()
        c.force_login(staff_user)
        return c

    def test_changelist_renders(self, admin_client, db):
        open_grievance(
            category=Category.DATA_CORRECTION, description="x",
            household_id="01HXY7K3B2N9PVQE4M6FZRWS18",
        )
        r = admin_client.get("/admin/grievance/grievance/")
        assert r.status_code == 200
        assert b"01HXY7K3B2N9PVQE4M6FZRWS18" in r.content

    def test_sla_badge_shows_overdue_when_past_deadline(self, db):
        from datetime import timedelta

        from django.utils import timezone

        from apps.grievance.admin import GrievanceAdmin
        g = open_grievance(category=Category.OTHER, description="x")
        g.sla_deadline = timezone.now() - timedelta(hours=1)
        g.save(update_fields=["sla_deadline"])
        admin_instance = GrievanceAdmin(Grievance, admin_site=None)
        badge = admin_instance.sla_badge(g)
        assert "OVERDUE" in badge

    def test_sla_badge_neutral_when_closed(self, db):
        from apps.grievance.admin import GrievanceAdmin
        g = open_grievance(category=Category.OTHER, description="x")
        resolve(g, actor="op", narrative="ok")
        close(g, actor="op")
        admin_instance = GrievanceAdmin(Grievance, admin_site=None)
        badge = admin_instance.sla_badge(g)
        assert "OVERDUE" not in badge
        assert "—" in badge

    def test_bulk_escalate_action(self, admin_client, db):
        # Two open grievances at L1, both should escalate to L2.
        from apps.grievance.models import Tier
        g1 = open_grievance(category=Category.OTHER, description="x",
                            tier=Tier.L1_PARISH_CHIEF)
        g2 = open_grievance(category=Category.OTHER, description="y",
                            tier=Tier.L1_PARISH_CHIEF)
        r = admin_client.post("/admin/grievance/grievance/", data={
            "action": "admin_escalate",
            "_selected_action": [g1.id, g2.id],
        })
        assert r.status_code in (200, 302)
        for g in (g1, g2):
            g.refresh_from_db()
            assert g.tier == Tier.L2_CDO
            assert g.status == GrievanceStatus.ESCALATED

    def test_admin_create_sets_sla_deadline_via_service(
        self, admin_client, db,
    ):
        """Regression: the admin's "Add grievance" form was creating
        rows directly via Django's default save_model, skipping
        apps.grievance.services.open_grievance — leaving rows with
        sla_deadline=NULL that the workbench (US-S21-002) couldn't
        badge. save_model now routes through the service."""
        from apps.security.models import AuditEvent
        before_audit = AuditEvent.objects.filter(
            entity_type="grievance", action="create",
        ).count()
        r = admin_client.post(
            "/admin/grievance/grievance/add/",
            data={
                "category": Category.DATA_CORRECTION,
                "sub_category": "",
                "description": "Created via admin add form.",
                "tier": "l1_parish_chief",
                "status": GrievanceStatus.OPEN,
                "household_id": "", "member_id": "",
                "reporter_name": "", "reporter_phone": "",
                "reporter_relationship": "",
                "assigned_to": "",
                "resolution_narrative": "",
                "linked_change_request_id": "",
                "_save": "Save",
            },
        )
        assert r.status_code in (200, 302), r.content[:400]
        g = Grievance.objects.latest("created_at")
        # The service set both fields.
        assert g.sla_deadline is not None, "open_grievance wasn't routed"
        # And the audit row landed.
        assert AuditEvent.objects.filter(
            entity_type="grievance", action="create",
            entity_id=g.id,
        ).count() == 1
        assert AuditEvent.objects.filter(
            entity_type="grievance", action="create",
        ).count() == before_audit + 1

    def test_bulk_close_skips_non_resolved(self, admin_client, db):
        # One RESOLVED + one OPEN; only the RESOLVED should close.
        g_resolved = open_grievance(category=Category.OTHER, description="x")
        resolve(g_resolved, actor="op", narrative="ok")
        g_open = open_grievance(category=Category.OTHER, description="y")
        r = admin_client.post("/admin/grievance/grievance/", data={
            "action": "admin_close",
            "_selected_action": [g_resolved.id, g_open.id],
        })
        assert r.status_code in (200, 302)
        g_resolved.refresh_from_db()
        g_open.refresh_from_db()
        assert g_resolved.status == GrievanceStatus.CLOSED
        assert g_open.status == GrievanceStatus.OPEN
