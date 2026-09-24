"""The audit drawer reads the chain; it does not reconstruct it.

The console built its "audit" events from the grievance's CURRENT
state: a reporter phone became "Via parish channel", any escalation
became "System GRM · SLA breach auto-escalator · 48h later" even when a
named officer had just done it by hand, and every row carried an id of
the form A-2026-05-<last two chars of the grievance id>-001. The drawer
was a story about what probably happened.

It could not have done better on its own. Task and comment events are
keyed by the task's or comment's own id — the grievance id lives inside
`field_changes` — so a client filtering the audit list by the grievance
id gets the grievance-level rows and nothing else. Hence one endpoint
that assembles the case's chain server-side, behind the same visibility
rule as every other detail route.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.data_management.models import Household
from apps.grievance.services import (
    add_comment, assign, create_task, escalate, open_grievance,
    transition_task,
)
from apps.grievance.models import TaskStatus
from apps.reference_data.models import GeographicUnit
from apps.security.models import OperatorScope, ScopeLevel

pytestmark = pytest.mark.django_db


def _household(prefix: str) -> Household:
    nodes, parent = {}, None
    for level in ("region", "sub_region", "district", "county",
                  "sub_county", "parish", "village"):
        nodes[level] = GeographicUnit.objects.create(
            level=level, code=f"{prefix}-{level.upper()}",
            name=f"{prefix} {level}", parent=parent,
            effective_from=date(2026, 1, 1),
        )
        parent = nodes[level]
    return Household.objects.create(urban_rural="2", **nodes)


def _admin(django_user_model, username="auditor"):
    user = django_user_model.objects.create_user(username=username, password="p")
    user.groups.add(Group.objects.get_or_create(name="nsr_admin")[0])
    OperatorScope.objects.get_or_create(
        user=user, scope_level=ScopeLevel.NATIONAL, scope_code="",
    )
    return user


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def worked_case(django_user_model):
    """A grievance that has been opened, assigned, escalated, given a
    task, commented on, and had the task closed — one of each kind of
    event the drawer claims to show."""
    household = _household("AUD")
    # Assignment checks the assignee's role and scope (QA P2.10). This
    # officer works the queue, which is what carries a case through
    # L1 assignment and an L2 task in one fixture.
    officer = django_user_model.objects.create_user(username="cdo.aine", password="p")
    officer.groups.add(Group.objects.get_or_create(name="GRM Officer")[0])
    OperatorScope.objects.get_or_create(
        user=officer, scope_level=ScopeLevel.NATIONAL, scope_code="",
    )
    g = open_grievance(
        category="data_correction", description="wrong district on file",
        household_id=household.id, actor="parish.chief",
    )
    assign(g, assigned_to=officer.username, actor="parish.chief")
    escalate(g, reason="Requires CDO authority", actor="parish.chief")
    task = create_task(
        g, title="Verify at the parish",
        description="Confirm the village with the LC1.",
        assigned_to=officer.username, actor="cdo.aine",
    )
    add_comment(g, body="Citizen called back with the correct village.",
                actor="cdo.aine")
    transition_task(task, new_status=TaskStatus.CLOSED, actor="cdo.aine",
                    note="Verified against the LC1 register.")
    return {"grievance": g, "task": task, "officer": officer}


def _chain(user, grievance):
    r = _client(user).get(f"/api/v1/grm/grievances/{grievance.id}/audit/")
    assert r.status_code == 200, r.data
    return r.data


class TestItReturnsTheWholeCase:

    def test_the_grievance_level_events_are_there(self, worked_case, django_user_model):
        rows = _chain(_admin(django_user_model), worked_case["grievance"])
        reasons = " | ".join(r["reason"] or "" for r in rows)
        assert any(r["action"] == "create" and r["entity_type"] == "grievance"
                   for r in rows), "the opening is missing"
        assert "assigned" in reasons
        assert "escalated" in reasons

    def test_task_events_are_included(self, worked_case, django_user_model):
        """The reason the client could not assemble this itself: these
        rows carry the TASK's id, not the grievance's."""
        rows = _chain(_admin(django_user_model), worked_case["grievance"])
        task_rows = [r for r in rows if r["entity_type"] == "grievance.task"]
        assert len(task_rows) >= 2, "task creation and closure both belong here"
        assert {r["entity_id"] for r in task_rows} == {str(worked_case["task"].id)}

    def test_comment_events_are_included(self, worked_case, django_user_model):
        rows = _chain(_admin(django_user_model), worked_case["grievance"])
        assert any(r["entity_type"] == "grievance.comment" for r in rows)

    def test_a_grievance_id_filter_alone_would_have_missed_them(
        self, worked_case, django_user_model,
    ):
        """Pins the reason this endpoint exists. If task and comment
        events ever start carrying the grievance id as their entity_id,
        this test fails and the endpoint can be reconsidered — it does
        not fail silently into a drawer showing half a case."""
        g = worked_case["grievance"]
        user = _admin(django_user_model)
        direct = _client(user).get(
            "/api/v1/security/audit-events/", {"entity_id": str(g.id)},
        )
        assert direct.status_code == 200
        types = {row["entity_type"] for row in direct.data["results"]}
        assert "grievance.task" not in types
        assert "grievance.comment" not in types

    def test_events_are_oldest_first(self, worked_case, django_user_model):
        rows = _chain(_admin(django_user_model), worked_case["grievance"])
        times = [r["occurred_at"] for r in rows]
        assert times == sorted(times)

    def test_every_row_carries_a_real_actor_time_and_hash(
        self, worked_case, django_user_model,
    ):
        """What the fabricated drawer could not supply."""
        rows = _chain(_admin(django_user_model), worked_case["grievance"])
        assert rows, "no events at all"
        for row in rows:
            assert row["actor_id"], row
            assert row["occurred_at"], row
            assert row["self_hash"], row
        assert {r["actor_id"] for r in rows} & {"parish.chief", "cdo.aine"}, (
            "the actors are not the people who acted"
        )

    def test_it_does_not_leak_another_grievance(self, worked_case, django_user_model):
        other = open_grievance(
            category="exclusion_error", description="unrelated",
            household_id=_household("OTH").id, actor="someone.else",
        )
        rows = _chain(_admin(django_user_model), worked_case["grievance"])
        assert str(other.id) not in {r["entity_id"] for r in rows}

    def test_the_linked_update_appears_once_one_exists(
        self, worked_case, django_user_model,
    ):
        from apps.grievance.services import open_change_request_for_grievance

        cr = open_change_request_for_grievance(
            worked_case["grievance"], requester="cdo.aine",
            changes={"household": {"village": "the right one"}},
        )
        rows = _chain(_admin(django_user_model), worked_case["grievance"])
        assert any(r["entity_type"] == "change_request"
                   and r["entity_id"] == str(cr.id) for r in rows)


class TestItIsBehindTheSameVisibilityRule:

    def test_a_user_outside_the_case_scope_cannot_read_its_chain(
        self, worked_case, django_user_model,
    ):
        """The chain names actors, households and narratives. It gets
        the detail route's rule, not a weaker one."""
        outsider = django_user_model.objects.create_user(
            username="other.district", password="p",
        )
        OperatorScope.objects.get_or_create(
            user=outsider, scope_level=ScopeLevel.SUB_REGION,
            scope_code="ELSEWHERE-SUB_REGION",
        )
        r = _client(outsider).get(
            f"/api/v1/grm/grievances/{worked_case['grievance'].id}/audit/",
        )
        assert r.status_code == 404

    def test_anonymous_gets_nothing(self, worked_case):
        r = APIClient().get(
            f"/api/v1/grm/grievances/{worked_case['grievance'].id}/audit/",
        )
        assert r.status_code in (401, 403, 404)

    def test_reading_the_chain_is_itself_audited(
        self, worked_case, django_user_model,
    ):
        from apps.security.models import AuditEvent

        user = _admin(django_user_model, "watcher")
        _chain(user, worked_case["grievance"])
        assert AuditEvent.objects.filter(
            actor_id="watcher", action="read", entity_type="grievance",
            entity_id=str(worked_case["grievance"].id),
        ).exists(), "a read of the case history left no trace"
