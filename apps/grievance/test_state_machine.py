"""The grievance state machine, and the claims a transition makes.

Every bug here was the same shape: the server trusted a string the
console sent. "ab" resolved a case. "30-day grace expired without
dispute" was accepted two minutes after resolve. "Data correction
committed via linked UPD" was accepted while the linked change request
was an empty draft. And an escalated case could not be assigned, so
the tier it had been escalated TO could not pick it up.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.grievance.models import (
    Category, Grievance, GrievanceStatus, Tier,
)
from apps.grievance.services import (
    GrievanceError, assign, close, escalate, open_grievance, resolve,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _assignee(django_user_model):
    """One operator who can take any case here.

    Assignment checks the assignee's role against the tier's
    GrmTierRule and their scope against the household (QA P2.10).
    These tests are about the state machine, not about who may hold a
    case, so this is the role that carries the whole queue.
    """
    from django.contrib.auth.models import Group

    from apps.security.models import OperatorScope, ScopeLevel

    user = django_user_model.objects.create_user(
        username="cdo-1", password="p", email="cdo@example.test",
    )
    user.groups.add(Group.objects.get_or_create(name="GRM Officer")[0])
    OperatorScope.objects.get_or_create(
        user=user, scope_level=ScopeLevel.NATIONAL, scope_code="",
    )
    return user


def _open(**kw):
    kw.setdefault("category", Category.OTHER)
    kw.setdefault("description", "[TEST] a case")
    return open_grievance(**kw)


# --- assign -----------------------------------------------------------

class TestAssignTransitions:

    @pytest.mark.parametrize(
        "status", [GrievanceStatus.OPEN, GrievanceStatus.IN_PROGRESS],
    )
    def test_assignable_from(self, status):
        g = _open()
        Grievance.objects.filter(pk=g.pk).update(status=status)
        g.refresh_from_db()

        assign(g, assigned_to="cdo-1", actor="supervisor")

        g.refresh_from_db()
        assert g.status == GrievanceStatus.IN_PROGRESS

    def test_an_escalated_case_can_be_assigned(self):
        """The blocking bug. ESCALATED is the state a case is IN while
        it waits for the receiving tier — refusing to assign it meant
        nobody at that tier could take it."""
        g = _open()
        escalate(g, actor="chief", reason="needs CDO")
        g.refresh_from_db()
        assert g.status == GrievanceStatus.ESCALATED

        assign(g, assigned_to="cdo-1", actor="supervisor")

        g.refresh_from_db()
        assert g.status == GrievanceStatus.IN_PROGRESS
        assert g.assigned_to == "cdo-1"

    def test_assigning_an_escalated_case_keeps_the_new_tier(self):
        """It moves to in_progress AT THE CURRENT TIER — assignment is
        not a demotion back to where it came from."""
        g = _open()
        escalate(g, actor="chief", reason="needs CDO")

        assign(g, assigned_to="cdo-1", actor="supervisor")

        g.refresh_from_db()
        assert g.tier == Tier.L2_CDO

    @pytest.mark.parametrize(
        "status", [GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED],
    )
    def test_refused_from_a_terminal_state(self, status):
        g = _open()
        Grievance.objects.filter(pk=g.pk).update(status=status)
        g.refresh_from_db()

        with pytest.raises(GrievanceError, match="cannot assign"):
            assign(g, assigned_to="cdo-1", actor="supervisor")


# --- the SLA clock ----------------------------------------------------

class TestSlaRestartsOnEscalation:

    def test_the_receiving_tier_gets_its_whole_window(self):
        g = _open()
        escalate(g, actor="chief", reason="needs CDO")

        g.refresh_from_db()
        assert (g.sla_deadline - g.tier_started_at) == timedelta(hours=48)

    def test_an_already_breached_case_does_not_arrive_pre_breached(self):
        """The reported symptom: 2,900 hours overdue at a tier the case
        had only just reached, because the window was measured from
        opened_at however many tiers ago that was."""
        g = _open()
        long_ago = timezone.now() - timedelta(days=120)
        Grievance.objects.filter(pk=g.pk).update(
            opened_at=long_ago, sla_deadline=long_ago + timedelta(hours=24),
        )
        g.refresh_from_db()

        escalate(g, actor="chief", reason="breached at L1")

        g.refresh_from_db()
        assert g.sla_deadline > timezone.now()

    def test_each_tier_restarts_it_again(self):
        g = _open()
        escalate(g, actor="a", reason="to L2")
        g.refresh_from_db()
        first = g.tier_started_at

        escalate(g, actor="b", reason="to L3")

        g.refresh_from_db()
        assert g.tier_started_at > first
        assert g.tier == Tier.L3_DISTRICT


# --- resolve ----------------------------------------------------------

class TestResolveRules:

    def test_a_two_character_narrative_is_refused(self):
        """The API accepted "ab"."""
        g = _open()

        with pytest.raises(GrievanceError, match="at least"):
            resolve(g, actor="op", reason_code="other", note="ab")

    def test_an_unknown_reason_is_refused(self):
        g = _open()

        with pytest.raises(GrievanceError, match="unknown resolve reason"):
            resolve(g, actor="op", reason_code="made_up", note="a real note")

    def test_a_valid_reason_and_note_resolve_it(self):
        g = _open()

        resolve(g, actor="op", reason_code="withdrawn",
                note="reporter called to withdraw")

        g.refresh_from_db()
        assert g.status == GrievanceStatus.RESOLVED
        assert "Citizen withdrew complaint" in g.resolution_narrative
        assert "reporter called to withdraw" in g.resolution_narrative

    def test_upd_reason_refused_with_no_linked_cr(self):
        g = _open()

        with pytest.raises(GrievanceError, match="no change request is linked"):
            resolve(g, actor="op", reason_code="upd_committed",
                    note="corrected the surname")

    def test_upd_reason_refused_while_the_cr_is_a_draft(self):
        """The reported case: an empty draft counted as a correction."""
        from apps.update_workflow.models import (
            ChangeRequest, ChangeStatus, ChangeType, EntityType,
        )

        cr = ChangeRequest.objects.create(
            entity_type=EntityType.HOUSEHOLD, entity_id="01HH",
            change_type=ChangeType.CORRECTION, changes={},
            requester="op", status=ChangeStatus.DRAFT,
        )
        g = _open()

        with pytest.raises(GrievanceError, match="not committed"):
            resolve(g, actor="op", reason_code="upd_committed",
                    note="corrected the surname",
                    linked_change_request_id=cr.id)

    def test_upd_reason_allowed_once_the_cr_is_committed(self):
        from apps.update_workflow.models import (
            ChangeRequest, ChangeStatus, ChangeType, EntityType,
        )

        cr = ChangeRequest.objects.create(
            entity_type=EntityType.HOUSEHOLD, entity_id="01HH",
            change_type=ChangeType.CORRECTION, changes={},
            requester="op", status=ChangeStatus.COMMITTED,
        )
        g = _open()

        resolve(g, actor="op", reason_code="upd_committed",
                note="corrected the surname",
                linked_change_request_id=cr.id)

        g.refresh_from_db()
        assert g.status == GrievanceStatus.RESOLVED


# --- close ------------------------------------------------------------

class TestCloseRules:

    def _resolved(self):
        g = _open()
        resolve(g, actor="op", reason_code="other", note="dealt with it")
        g.refresh_from_db()
        return g

    def test_grace_reason_refused_before_the_period_elapses(self):
        """Accepted two minutes after resolve."""
        g = self._resolved()

        with pytest.raises(GrievanceError, match="grace period has not expired"):
            close(g, actor="op", reason_code="grace_expired",
                  note="no dispute received")

    def test_grace_reason_allowed_once_it_has(self, settings):
        settings.GRM_CLOSE_GRACE_DAYS = 30
        g = self._resolved()
        Grievance.objects.filter(pk=g.pk).update(
            resolved_at=timezone.now() - timedelta(days=31),
        )
        g.refresh_from_db()

        close(g, actor="op", reason_code="grace_expired",
              note="no dispute received")

        g.refresh_from_db()
        assert g.status == GrievanceStatus.CLOSED

    def test_the_grace_period_is_configurable(self, settings):
        settings.GRM_CLOSE_GRACE_DAYS = 1
        g = self._resolved()
        Grievance.objects.filter(pk=g.pk).update(
            resolved_at=timezone.now() - timedelta(days=2),
        )
        g.refresh_from_db()

        close(g, actor="op", reason_code="grace_expired",
              note="no dispute received")

        g.refresh_from_db()
        assert g.status == GrievanceStatus.CLOSED

    def test_another_reason_closes_it_immediately(self):
        """The grace period gates one claim, not closing itself."""
        g = self._resolved()

        close(g, actor="op", reason_code="reporter_confirmed",
              note="reporter confirmed on the phone")

        g.refresh_from_db()
        assert g.status == CLOSED_STATUS

    def test_a_short_note_is_refused(self):
        g = self._resolved()

        with pytest.raises(GrievanceError, match="at least"):
            close(g, actor="op", reason_code="other", note="ok")

    @pytest.mark.parametrize(
        "status",
        [GrievanceStatus.OPEN, GrievanceStatus.IN_PROGRESS,
         GrievanceStatus.ESCALATED],
    )
    def test_only_a_resolved_case_can_close(self, status):
        g = _open()
        Grievance.objects.filter(pk=g.pk).update(status=status)
        g.refresh_from_db()

        with pytest.raises(GrievanceError, match="can only close RESOLVED"):
            close(g, actor="op", reason_code="other", note="closing early")


CLOSED_STATUS = GrievanceStatus.CLOSED


# --- escalate ---------------------------------------------------------

class TestEscalateRules:

    def test_a_short_note_is_refused(self):
        g = _open()

        with pytest.raises(GrievanceError, match="at least"):
            escalate(g, actor="op", reason_code="other", note="ab")

    def test_a_valid_reason_escalates(self):
        g = _open()

        escalate(g, actor="op", reason_code="citizen_request",
                 note="reporter asked for the CDO")

        g.refresh_from_db()
        assert g.tier == Tier.L2_CDO
        assert g.status == GrievanceStatus.ESCALATED


# --- reporter phone ---------------------------------------------------

class TestReporterPhone:

    @pytest.mark.parametrize("raw", ["abc123", "12345", "+4477009000"])
    def test_a_non_ugandan_number_is_refused(self, raw):
        with pytest.raises(GrievanceError, match="not a Ugandan mobile"):
            _open(reporter_phone=raw)

    @pytest.mark.parametrize(
        ("raw", "stored"),
        [
            ("0772123456", "+256772123456"),
            ("+256772123456", "+256772123456"),
            ("0772 123 456", "+256772123456"),
            ("0772-123-456", "+256772123456"),
        ],
    )
    def test_a_ugandan_number_is_normalised(self, raw, stored):
        g = _open(reporter_phone=raw)

        assert g.reporter_phone == stored

    def test_no_phone_is_fine(self):
        """Anonymous reporting is a channel, not an error."""
        assert _open(reporter_phone="").reporter_phone == ""
