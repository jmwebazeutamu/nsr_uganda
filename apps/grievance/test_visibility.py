"""Who sees which grievances, and why the numbers used to disagree.

The workbench asked `_is_grm_officer()` — Django's `is_superuser` flag
or membership of a group literally named "GRM Officer". The home
dashboard counted the same rows through the registry's ABAC scope,
where a national OperatorScope means everything. An `nsr_admin` with a
national scope — what a Super Admin account looks like here — matched
the second rule and not the first, so the dashboard read "5 open" and
the workbench read 0.

One rule now, in apps/grievance/visibility.py, used by both.
"""

from __future__ import annotations

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.data_management.models import Household
from apps.grievance.models import Grievance, GrievanceStatus, TaskStatus
from apps.grievance.services import create_task, open_grievance
from apps.grievance.visibility import visible_grievances
from apps.reference_data.models import GeographicUnit
from apps.reporting.dashboard_views import _count_open_grievances
from apps.security.models import OperatorScope, ScopeLevel

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/grm/grievances/"


def _chain(prefix: str) -> dict:
    nodes, parent = {}, None
    for level in ("region", "sub_region", "district", "county",
                  "sub_county", "parish", "village"):
        nodes[level] = GeographicUnit.objects.create(
            level=level, code=f"{prefix}-{level.upper()}",
            name=f"{prefix} {level}", parent=parent,
            effective_from=date(2026, 1, 1),
        )
        parent = nodes[level]
    return nodes


def _household(prefix: str) -> Household:
    return Household.objects.create(urban_rural="2", **_chain(prefix))


@pytest.fixture
def two_areas(db):
    """A household in each of two sub-regions, with one grievance each."""
    north, south = _household("NORTH"), _household("SOUTH")
    return {
        "north": north, "south": south,
        "north_g": open_grievance(
            category="exclusion_error", description="north case",
            household_id=north.id,
        ),
        "south_g": open_grievance(
            category="exclusion_error", description="south case",
            household_id=south.id,
        ),
    }


def _user(django_user_model, username, **kw):
    return django_user_model.objects.create_user(
        username=username, password="p", **kw,
    )


def _scope(user, level, code):
    # get_or_create: adding a role group fires the G7 signal, which
    # already grants that role's default scope. Asking for the same
    # scope explicitly must not collide with it.
    scope, _ = OperatorScope.objects.get_or_create(
        user=user, scope_level=level, scope_code=code,
    )
    return scope


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


# --- the reported bug -------------------------------------------------

class TestTheReportedBug:

    def test_an_nsr_admin_with_a_national_scope_sees_everything(
        self, two_areas, django_user_model,
    ):
        """The exact account from the report: group nsr_admin, national
        scope, NOT a Django superuser and NOT in a "GRM Officer" group.
        It saw 0."""
        from django.contrib.auth.models import Group

        user = _user(django_user_model, "jmwebaze")
        user.groups.add(Group.objects.get_or_create(name="nsr_admin")[0])
        _scope(user, ScopeLevel.NATIONAL, "")

        assert visible_grievances(user).count() == 2

        r = _client(user).get(LIST_URL, {"page_size": 100})
        assert r.status_code == 200
        assert r.data["count"] == 2

    def test_the_dashboard_and_the_list_agree(
        self, two_areas, django_user_model,
    ):
        """The symptom that made it obvious: one screen, two numbers."""
        from django.contrib.auth.models import Group

        user = _user(django_user_model, "counts-match")
        user.groups.add(Group.objects.get_or_create(name="nsr_admin")[0])
        _scope(user, ScopeLevel.NATIONAL, "")

        open_in_list = visible_grievances(user).exclude(
            status__in=[GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED],
        ).count()

        assert _count_open_grievances(user) == open_in_list == 2


# --- the scope rules --------------------------------------------------

class TestScope:

    def test_a_wildcard_user_sees_all(self, two_areas, django_user_model):
        user = _user(django_user_model, "national-op")
        _scope(user, ScopeLevel.NATIONAL, "")

        assert visible_grievances(user).count() == 2

    def test_a_superuser_sees_all(self, two_areas, django_user_model):
        user = _user(django_user_model, "root", is_superuser=True)

        assert visible_grievances(user).count() == 2

    def test_a_scoped_user_sees_only_their_own_area(
        self, two_areas, django_user_model,
    ):
        user = _user(django_user_model, "north-chief")
        _scope(user, ScopeLevel.SUB_REGION, "NORTH-SUB_REGION")

        visible = visible_grievances(user)

        assert [g.id for g in visible] == [two_areas["north_g"].id]

    def test_a_scoped_user_sees_a_grievance_they_have_just_opened(
        self, two_areas, django_user_model,
    ):
        user = _user(django_user_model, "district-op")
        _scope(user, ScopeLevel.DISTRICT, "NORTH-DISTRICT")

        fresh = open_grievance(
            category="data_correction", description="just filed",
            household_id=two_areas["north"].id,
        )

        assert fresh.id in {g.id for g in visible_grievances(user)}

    def test_a_user_with_no_scope_sees_none(
        self, two_areas, django_user_model,
    ):
        """Fail-closed. Not an empty list because nothing matched — an
        empty list because nothing was granted."""
        user = _user(django_user_model, "no-scope")

        assert visible_grievances(user).count() == 0
        assert _client(user).get(LIST_URL).data["count"] == 0

    def test_an_anonymous_caller_sees_none(self, two_areas):
        assert APIClient().get(LIST_URL).status_code in (401, 403)

    def test_a_partner_scope_is_not_a_geographic_one(
        self, two_areas, django_user_model,
    ):
        user = _user(django_user_model, "partner-op")
        _scope(user, ScopeLevel.PARTNER, "OPM")

        assert visible_grievances(user).count() == 0


class TestOwnership:
    """A grievance someone was deliberately given, outside their area.
    This grants one row, never a class of rows."""

    def test_an_assignee_sees_their_own_case_out_of_area(
        self, two_areas, django_user_model,
    ):
        user = _user(django_user_model, "north-op-2")
        _scope(user, ScopeLevel.SUB_REGION, "NORTH-SUB_REGION")
        south = two_areas["south_g"]
        south.assigned_to = user.username
        south.save(update_fields=["assigned_to"])

        assert south.id in {g.id for g in visible_grievances(user)}

    def test_a_task_holder_sees_the_grievance(
        self, two_areas, django_user_model,
    ):
        user = _user(django_user_model, "task-holder")
        _scope(user, ScopeLevel.SUB_REGION, "NORTH-SUB_REGION")
        create_task(
            two_areas["south_g"], title="visit", description="",
            assigned_to=user.username, actor="officer",
        )

        assert two_areas["south_g"].id in {
            g.id for g in visible_grievances(user)
        }

    def test_ownership_does_not_widen_the_area(
        self, two_areas, django_user_model,
    ):
        """Being given one southern case does not reveal the others."""
        user = _user(django_user_model, "narrow")
        _scope(user, ScopeLevel.SUB_REGION, "NORTH-SUB_REGION")
        south = two_areas["south_g"]
        south.assigned_to = user.username
        south.save(update_fields=["assigned_to"])
        other_south = open_grievance(
            category="other", description="not theirs",
            household_id=two_areas["south"].id,
        )

        assert other_south.id not in {g.id for g in visible_grievances(user)}


class TestCreateStoresLocation:

    def test_a_new_grievance_carries_the_household_geography(self, db):
        household = _household("GEO")

        g = open_grievance(
            category="data_correction", description="x",
            household_id=household.id,
        )

        assert g.sub_region_code == household.sub_region_code
        assert g.district_code == household.district_code
        assert g.parish_code == household.parish_code

    def test_a_grievance_about_no_household_has_no_geography(self, db):
        """Operator conduct belongs to nobody's district."""
        g = open_grievance(
            category="operator_conduct", description="rude enumerator",
        )

        assert g.sub_region_code == ""
        assert g.district_code == ""

    def test_a_grievance_with_no_household_is_not_hidden_by_scope(
        self, db, django_user_model,
    ):
        """It has no geography, so geography cannot decide it — the
        officers see it, a district operator does not."""
        from django.contrib.auth.models import Group

        unplaced = open_grievance(
            category="operator_conduct", description="rude enumerator",
        )
        officer = _user(django_user_model, "queue-officer")
        officer.groups.add(Group.objects.get_or_create(name="nsr_admin")[0])
        _scope(officer, ScopeLevel.NATIONAL, "")
        scoped = _user(django_user_model, "scoped-op")
        _scope(scoped, ScopeLevel.SUB_REGION, "NORTH-SUB_REGION")

        assert unplaced.id in {g.id for g in visible_grievances(officer)}
        assert unplaced.id not in {g.id for g in visible_grievances(scoped)}
