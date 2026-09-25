"""A closed grievance is read-only.

Every transition already refused a closed case — assign, escalate,
resolve, close all check the status. Three things still wrote to one:

  * a note could be appended to the thread, which was deliberate and
    documented ("a comment records what someone knew or did; refusing
    it loses the record rather than protecting anything");
  * a linked ChangeRequest could be opened from it, stamping
    linked_change_request_id onto the closed row;
  * a task could in principle be moved.

So a closed case was closed for the state machine and open for
everything else. The closing narrative is meant to be the last word on
what happened; a thread that keeps growing after it means the record of
a settled case is not settled. New information about a closed case is a
new case.

The rule lives in one place, services._require_open_for_writing, so
that adding a fourth writer does not quietly reopen the hole. These
tests are the statement of it.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth.models import Group

from apps.data_management.models import Household
from apps.grievance.models import Grievance, GrievanceStatus, TaskStatus
from apps.grievance.services import (
    GrievanceError, add_comment, assign, close, create_task, escalate,
    open_change_request_for_grievance, open_grievance, resolve,
    transition_task,
)
from apps.grievance.visibility import allowed_actions
from apps.reference_data.models import GeographicUnit
from apps.security.models import OperatorScope, ScopeLevel

pytestmark = pytest.mark.django_db


def _household(prefix: str = "RO") -> Household:
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


@pytest.fixture
def officer(django_user_model):
    user = django_user_model.objects.create_user(
        username="grm.desk", password="p", email="desk@example.test",
    )
    user.groups.add(Group.objects.get_or_create(name="GRM Officer")[0])
    OperatorScope.objects.get_or_create(
        user=user, scope_level=ScopeLevel.NATIONAL, scope_code="",
    )
    return user


@pytest.fixture
def closed_case(officer):
    household = _household()
    g = open_grievance(
        category="data_correction", description="wrong village on file",
        household_id=household.id, actor="parish.chief",
    )
    resolve(g, actor="officer", narrative="Village corrected on the record")
    close(g, actor="officer", narrative="30-day grace elapsed, no reply")
    assert g.status == GrievanceStatus.CLOSED
    return g


class TestNothingWritesToIt:

    def test_a_note_cannot_be_added(self, closed_case):
        with pytest.raises(GrievanceError, match="closed and read-only"):
            add_comment(closed_case, body="Reporter called back.",
                        actor="officer")
        assert closed_case.comments.count() == 0

    def test_a_linked_update_cannot_be_opened(self, closed_case):
        """This one left a mark: it wrote linked_change_request_id onto
        the closed row."""
        with pytest.raises(GrievanceError, match="closed and read-only"):
            open_change_request_for_grievance(
                closed_case, requester="officer",
                changes={"household": {"village": "somewhere else"}},
            )
        closed_case.refresh_from_db()
        assert closed_case.linked_change_request_id in ("", None)

    def test_a_task_cannot_be_moved(self, officer):
        """Unreachable through the normal lifecycle — a case cannot
        resolve with an open task, and close needs resolved — so this
        forces the state the guard describes rather than trusting that
        it cannot happen."""
        household = _household("RO2")
        g = open_grievance(category="other", description="x",
                           household_id=household.id)
        task = create_task(g, title="visit", description="",
                           assigned_to=officer.username, actor="officer")
        Grievance.objects.filter(pk=g.pk).update(status=GrievanceStatus.CLOSED)
        task.refresh_from_db()

        with pytest.raises(GrievanceError, match="closed and read-only"):
            transition_task(task, new_status=TaskStatus.CLOSED,
                            actor="officer", note="tidying up")

    def test_it_cannot_be_assigned(self, closed_case, officer):
        with pytest.raises(GrievanceError):
            assign(closed_case, assigned_to=officer.username, actor="officer")

    def test_it_cannot_be_escalated(self, closed_case):
        with pytest.raises(GrievanceError):
            escalate(closed_case, reason="second thoughts", actor="officer")

    def test_it_cannot_be_resolved_again(self, closed_case):
        with pytest.raises(GrievanceError):
            resolve(closed_case, actor="officer", narrative="again")

    def test_it_cannot_be_closed_again(self, closed_case):
        with pytest.raises(GrievanceError):
            close(closed_case, actor="officer", narrative="again")

    def test_a_new_task_cannot_be_added(self, closed_case, officer):
        with pytest.raises(GrievanceError):
            create_task(closed_case, title="one more", description="",
                        assigned_to=officer.username, actor="officer")


class TestTheConsoleIsToldSo:

    def test_a_closed_case_offers_nothing(self, closed_case):
        """The console renders allowed_actions. A closed case listing
        "comment" is how a composer stays on screen over an endpoint
        that refuses it."""
        assert allowed_actions(closed_case) == []

    def test_a_resolved_case_still_offers_what_it_accepts(self, officer):
        household = _household("RO3")
        g = open_grievance(category="other", description="x",
                           household_id=household.id)
        resolve(g, actor="officer", narrative="Sorted at the parish office")
        actions = allowed_actions(g)
        assert "comment" in actions
        assert "close" in actions

    def test_an_already_linked_case_does_not_offer_a_second_update(
        self, officer,
    ):
        """The service refuses a second ChangeRequest, so offering the
        button is offering an error."""
        household = _household("RO4")
        g = open_grievance(category="data_correction", description="x",
                           household_id=household.id)
        assert "open_change_request" in allowed_actions(g)

        open_change_request_for_grievance(
            g, requester="officer",
            changes={"household": {"village": "the right one"}},
        )
        g.refresh_from_db()
        assert "open_change_request" not in allowed_actions(g)


class TestWhatIsStillAllowed:
    """Read-only means read-only, not invisible."""

    def test_it_can_still_be_read(self, closed_case, officer):
        from rest_framework.test import APIClient

        c = APIClient()
        c.force_authenticate(user=officer)
        r = c.get(f"/api/v1/grm/grievances/{closed_case.id}/")
        assert r.status_code == 200
        assert r.data["status"] == "closed"

    def test_its_history_can_still_be_read(self, closed_case, officer):
        from rest_framework.test import APIClient

        c = APIClient()
        c.force_authenticate(user=officer)
        r = c.get(f"/api/v1/grm/grievances/{closed_case.id}/audit/")
        assert r.status_code == 200
        assert len(r.data) > 0

    def test_the_audit_chain_still_accepts_events_about_it(self, closed_case):
        """The chain is append-only by design and is where an
        operational annotation about a historical record belongs — the
        grievance row itself does not change. The phantom-assignee
        remediation depends on this."""
        from apps.security.audit import emit
        from apps.security.models import AuditEvent

        emit("grm.provenance_note", "grievance", closed_case.id,
             actor="ops", reason="Demo record from 18 May 2026.")
        assert AuditEvent.objects.filter(
            entity_id=str(closed_case.id), action="grm.provenance_note",
        ).exists()
        closed_case.refresh_from_db()
        assert closed_case.status == GrievanceStatus.CLOSED
