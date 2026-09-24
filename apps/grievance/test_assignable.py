"""QA P2.10 — who a case can be given to.

The console's assignee picker searched `/api/v1/security/users/`: the
whole directory, every account, active or not, with no regard for what
the case needed. So an L3 District grievance could be assigned to an
enumerator in another sub-region — a person with neither the authority
to decide it nor the scope to open it. They would receive the email,
follow the link, and be refused their own work.

Two conditions now, from the GrmTierRule ladder and the registry's
ordinary ABAC scope, applied in one place and enforced at the service
boundary. A picker that offers the right names is a convenience; the
guard is the rule.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.data_management.models import Household
from apps.grievance import assignees
from apps.grievance.models import GrmTierRule, Tier
from apps.grievance.services import (
    GrievanceError, assign, create_task, open_grievance,
)
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


def _user(django_user_model, username, *, role=None, scope=None, code="",
          active=True):
    user = django_user_model.objects.create_user(
        username=username, password="p", email=f"{username}@example.test",
        is_active=active,
    )
    if role:
        user.groups.add(Group.objects.get_or_create(name=role)[0])
    if scope:
        OperatorScope.objects.get_or_create(
            user=user, scope_level=scope, scope_code=code,
        )
    return user


@pytest.fixture
def north(db):
    return _household("PICK-N")


@pytest.fixture
def south(db):
    return _household("PICK-S")


@pytest.fixture
def case(north):
    """An L1 case about a northern household."""
    return open_grievance(
        category="exclusion_error", description="left out",
        household_id=north.id,
    )


# --- the ladder is configuration, not a constant ----------------------

class TestTheLadderIsConfigured:

    def test_every_tier_has_an_active_rule(self):
        configured = set(
            GrmTierRule.objects.filter(is_active=True)
            .values_list("tier", flat=True),
        )
        assert configured == set(Tier.values), (
            "a tier with no rule cannot be assigned or given an SLA"
        )

    def test_the_roles_come_from_the_catalogue(self):
        from apps.security.roles import ROLE_CODES

        for rule in GrmTierRule.objects.filter(is_active=True):
            assert rule.required_role in ROLE_CODES, (
                f"{rule.tier} requires {rule.required_role!r}, which is not "
                "a role in apps/security/roles.py"
            )

    def test_the_sla_window_reads_the_rule_rather_than_a_constant(self):
        from apps.grievance.services import sla_for

        rule = GrmTierRule.objects.get(tier=Tier.L2_CDO, is_active=True)
        rule.sla_hours = 96
        rule.save(update_fields=["sla_hours"])

        assert sla_for(Tier.L2_CDO).total_seconds() == 96 * 3600, (
            "the SLA window did not follow the configured ladder — "
            "rebalancing it still needs a deploy"
        )

    def test_an_unconfigured_tier_refuses_rather_than_guessing(self):
        GrmTierRule.objects.filter(tier=Tier.L3_DISTRICT).update(is_active=False)
        with pytest.raises(assignees.IneligibleAssignee, match="not configured"):
            assignees.tier_rule(Tier.L3_DISTRICT)


# --- the rule ---------------------------------------------------------

class TestWhoMayCarryACase:

    def test_the_tier_s_role_may(self, case, django_user_model):
        user = _user(django_user_model, "pc.north", role="parish_chief",
                     scope=ScopeLevel.NATIONAL)
        assignees.check(user, tier=case.tier, household_id=case.household_id)

    def test_another_role_may_not(self, case, django_user_model):
        user = _user(django_user_model, "field.hand", role="enumerator",
                     scope=ScopeLevel.NATIONAL)
        with pytest.raises(assignees.IneligibleAssignee, match="parish_chief"):
            assignees.check(user, tier=case.tier, household_id=case.household_id)

    def test_the_right_role_out_of_scope_may_not(
        self, case, south, django_user_model,
    ):
        user = _user(django_user_model, "pc.south", role="parish_chief",
                     scope=ScopeLevel.SUB_REGION, code="PICK-S-SUB_REGION")
        with pytest.raises(assignees.IneligibleAssignee,
                           match="no access to the household"):
            assignees.check(user, tier=case.tier, household_id=case.household_id)

    def test_a_queue_wide_role_is_exempt_from_the_role_condition(
        self, case, django_user_model,
    ):
        """nsr_admin and GRM Officer already see and act on every case.
        A rule that let them read one but not be given it would be a
        second visibility vocabulary."""
        user = _user(django_user_model, "grm.desk", role="GRM Officer",
                     scope=ScopeLevel.NATIONAL)
        assignees.check(user, tier=case.tier, household_id=case.household_id)

    def test_a_case_about_no_household_is_not_decided_by_geography(
        self, django_user_model,
    ):
        """Same treatment visible_grievances gives these rows."""
        case = open_grievance(category="other", description="hotline call")
        user = _user(django_user_model, "pc.somewhere", role="parish_chief",
                     scope=ScopeLevel.SUB_REGION, code="ELSEWHERE")
        assignees.check(user, tier=case.tier, household_id=case.household_id or "")

    def test_an_unscoped_user_may_not(self, case, django_user_model):
        """scope_q_for_field is fail-closed, and so is this."""
        user = _user(django_user_model, "no.scope", role="parish_chief")
        with pytest.raises(assignees.IneligibleAssignee,
                           match="no access to the household"):
            assignees.check(user, tier=case.tier, household_id=case.household_id)

    def test_the_tier_asked_about_is_the_case_s_tier(
        self, case, django_user_model,
    ):
        """A CDO does not carry an L1 case, and the picker must not
        offer them for one."""
        user = _user(django_user_model, "cdo.north", role="cdo",
                     scope=ScopeLevel.NATIONAL)
        with pytest.raises(assignees.IneligibleAssignee):
            assignees.check(user, tier=Tier.L1_PARISH_CHIEF,
                            household_id=case.household_id)
        assignees.check(user, tier=Tier.L2_CDO, household_id=case.household_id)


# --- enforced at the service boundary, not only in the picker ---------

class TestTheServerEnforcesIt:

    def test_assign_refuses_the_wrong_role(self, case, django_user_model):
        _user(django_user_model, "wrong.role", role="enumerator",
              scope=ScopeLevel.NATIONAL)
        with pytest.raises(GrievanceError, match="does not hold"):
            assign(case, assigned_to="wrong.role", actor="officer")

    def test_assign_refuses_out_of_scope(self, case, django_user_model):
        _user(django_user_model, "wrong.place", role="parish_chief",
              scope=ScopeLevel.SUB_REGION, code="PICK-S-SUB_REGION")
        with pytest.raises(GrievanceError, match="no access to the household"):
            assign(case, assigned_to="wrong.place", actor="officer")

    def test_assign_accepts_an_eligible_user(self, case, django_user_model):
        _user(django_user_model, "right.one", role="parish_chief",
              scope=ScopeLevel.NATIONAL)
        assign(case, assigned_to="right.one", actor="officer")
        case.refresh_from_db()
        assert case.assigned_to == "right.one"

    def test_a_task_takes_the_case_s_rule(self, case, django_user_model):
        _user(django_user_model, "task.wrong", role="enumerator",
              scope=ScopeLevel.NATIONAL)
        with pytest.raises(GrievanceError, match="does not hold"):
            create_task(case, title="visit", description="",
                        assigned_to="task.wrong", actor="officer")

    def test_an_inactive_user_is_still_refused(self, case, django_user_model):
        _user(django_user_model, "gone.home", role="parish_chief",
              scope=ScopeLevel.NATIONAL, active=False)
        with pytest.raises(GrievanceError, match="not an active MIS user"):
            assign(case, assigned_to="gone.home", actor="officer")


# --- the picker -------------------------------------------------------

def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def caller(db, django_user_model):
    return _user(django_user_model, "caller", role="nsr_admin",
                 scope=ScopeLevel.NATIONAL)


def _names(response):
    return {row["username"] for row in response.data}


class TestThePicker:

    def test_it_lists_the_tier_s_role(self, case, caller, django_user_model):
        _user(django_user_model, "pc.a", role="parish_chief",
              scope=ScopeLevel.NATIONAL)
        r = _client(caller).get(f"/api/v1/grm/grievances/{case.id}/assignable/")
        assert r.status_code == 200
        assert "pc.a" in _names(r)

    def test_it_leaves_out_other_roles(self, case, caller, django_user_model):
        _user(django_user_model, "enum.a", role="enumerator",
              scope=ScopeLevel.NATIONAL)
        r = _client(caller).get(f"/api/v1/grm/grievances/{case.id}/assignable/")
        assert "enum.a" not in _names(r)

    def test_it_leaves_out_the_out_of_scope(
        self, case, south, caller, django_user_model,
    ):
        _user(django_user_model, "pc.south", role="parish_chief",
              scope=ScopeLevel.SUB_REGION, code="PICK-S-SUB_REGION")
        r = _client(caller).get(f"/api/v1/grm/grievances/{case.id}/assignable/")
        assert "pc.south" not in _names(r)

    def test_it_leaves_out_deactivated_accounts(
        self, case, caller, django_user_model,
    ):
        _user(django_user_model, "pc.retired", role="parish_chief",
              scope=ScopeLevel.NATIONAL, active=False)
        r = _client(caller).get(f"/api/v1/grm/grievances/{case.id}/assignable/")
        assert "pc.retired" not in _names(r)

    def test_everyone_it_offers_would_be_accepted(
        self, case, caller, django_user_model,
    ):
        """The picker and the guard are the same rule, so the list can
        never contain a name that /assign/ would refuse."""
        for name, role in [("pc.b", "parish_chief"), ("desk.b", "GRM Officer"),
                           ("enum.b", "enumerator"), ("cdo.b", "cdo")]:
            _user(django_user_model, name, role=role, scope=ScopeLevel.NATIONAL)

        r = _client(caller).get(f"/api/v1/grm/grievances/{case.id}/assignable/")
        for username in _names(r):
            assign(case, assigned_to=username, actor="officer")

    def test_it_can_be_asked_about_the_tier_a_case_is_heading_for(
        self, case, caller, django_user_model,
    ):
        """`for_tier`, not `tier`: the viewset already reads `tier`
        from the query string to mean "cases at this tier", and on a
        detail route that filters away the very case being asked
        about — a 404 that looks like a permission problem."""
        _user(django_user_model, "cdo.next", role="cdo",
              scope=ScopeLevel.NATIONAL)
        r = _client(caller).get(
            f"/api/v1/grm/grievances/{case.id}/assignable/",
            {"for_tier": Tier.L2_CDO.value},
        )
        assert "cdo.next" in _names(r)

    def test_q_narrows_by_name(self, case, caller, django_user_model):
        _user(django_user_model, "akello.p", role="parish_chief",
              scope=ScopeLevel.NATIONAL)
        _user(django_user_model, "okello.p", role="parish_chief",
              scope=ScopeLevel.NATIONAL)
        r = _client(caller).get(
            f"/api/v1/grm/grievances/{case.id}/assignable/", {"q": "akello"},
        )
        assert _names(r) == {"akello.p"}

    def test_a_user_who_cannot_see_the_case_cannot_list_its_assignees(
        self, case, south, django_user_model,
    ):
        """The candidate list names operators and their areas. It gets
        the case's own visibility rule."""
        outsider = _user(django_user_model, "outsider", role="parish_chief",
                         scope=ScopeLevel.SUB_REGION, code="PICK-S-SUB_REGION")
        r = _client(outsider).get(
            f"/api/v1/grm/grievances/{case.id}/assignable/",
        )
        assert r.status_code == 404
