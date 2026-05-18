"""GRM workflow tests."""

from __future__ import annotations

import pytest

from apps.grievance.models import (
    Category,
    Grievance,
    GrievanceStatus,
    Tier,
)
from apps.grievance.services import (
    GrievanceError,
    assign,
    close,
    escalate,
    open_change_request_for_grievance,
    open_grievance,
    resolve,
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
