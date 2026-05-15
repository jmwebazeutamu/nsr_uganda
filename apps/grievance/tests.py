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
