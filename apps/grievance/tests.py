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
