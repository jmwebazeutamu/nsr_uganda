"""One definition of an open grievance.

Three surfaces counted it and each spelled it out for itself: the
dashboard tile excluded RESOLVED and CLOSED, the workbench title chip
filtered the rows it happened to have in the browser, and the sidebar
badge fetched 200 rows and filtered those. Three statements of one
idea, which is this project's recurring defect — and the badge's was
also capped at 200, so a queue of 250 open cases read as 200.

`?active=true` is the server's answer, from ACTIVE_GRIEVANCE_STATUSES.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.data_management.models import Household
from apps.grievance.models import (
    ACTIVE_GRIEVANCE_STATUSES, Grievance, GrievanceStatus,
)
from apps.grievance.services import open_grievance
from apps.reference_data.models import GeographicUnit
from apps.reporting.dashboard_views import _count_open_grievances
from apps.security.models import OperatorScope, ScopeLevel

pytestmark = pytest.mark.django_db

URL = "/api/v1/grm/grievances/"


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


@pytest.fixture
def admin_client(db, django_user_model):
    user = django_user_model.objects.create_user(username="counter", password="p")
    user.groups.add(Group.objects.get_or_create(name="nsr_admin")[0])
    OperatorScope.objects.get_or_create(
        user=user, scope_level=ScopeLevel.NATIONAL, scope_code="",
    )
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def mixed(db):
    """One grievance in each status."""
    household = _household("CNT")
    out = {}
    for status in GrievanceStatus.values:
        g = open_grievance(
            category="other", description=f"case in {status}",
            household_id=household.id,
        )
        Grievance.objects.filter(pk=g.pk).update(status=status)
        out[status] = g
    return out


class TestTheActiveFilter:

    def test_it_returns_only_the_active_statuses(self, mixed, admin_client):
        r = admin_client.get(URL, {"active": "true", "page_size": 100})
        assert r.status_code == 200
        statuses = {row["status"] for row in r.data["results"]}
        assert statuses == set(ACTIVE_GRIEVANCE_STATUSES)

    def test_resolved_and_closed_are_not_somebody_s_work(self, mixed, admin_client):
        r = admin_client.get(URL, {"active": "true", "page_size": 100})
        ids = {row["id"] for row in r.data["results"]}
        assert mixed[GrievanceStatus.RESOLVED].id not in ids
        assert mixed[GrievanceStatus.CLOSED].id not in ids

    def test_the_count_is_usable_without_fetching_the_rows(
        self, mixed, admin_client,
    ):
        """The badge asks with page_size=1 and reads `count`. Fetching
        rows to count them is what capped it at 200."""
        r = admin_client.get(URL, {"active": "true", "page_size": 1})
        assert r.data["count"] == len(ACTIVE_GRIEVANCE_STATUSES)
        assert len(r.data["results"]) == 1

    def test_it_is_off_unless_asked_for(self, mixed, admin_client):
        r = admin_client.get(URL, {"page_size": 100})
        assert r.data["count"] == len(GrievanceStatus.values)

    def test_a_falsy_value_does_not_filter(self, mixed, admin_client):
        r = admin_client.get(URL, {"active": "false", "page_size": 100})
        assert r.data["count"] == len(GrievanceStatus.values)


class TestTheBadgeAndTheTileAgree:

    def test_the_same_number_on_both_surfaces(
        self, mixed, admin_client, django_user_model,
    ):
        """The defect this pins is one screen, two numbers — the shape
        the GRM visibility fix already had to undo once."""
        user = django_user_model.objects.get(username="counter")
        badge = admin_client.get(URL, {"active": "true", "page_size": 1}).data["count"]
        assert badge == _count_open_grievances(user)

    def test_the_status_filter_still_takes_a_list(self, mixed, admin_client):
        """UPD's does, and the badge's predecessor would have needed
        it. Kept so a caller can ask a narrower question."""
        r = admin_client.get(URL, {"status": "open,escalated", "page_size": 100})
        assert {row["status"] for row in r.data["results"]} == {"open", "escalated"}

    def test_asking_for_one_status_still_works(self, mixed, admin_client):
        r = admin_client.get(URL, {"status": "closed", "page_size": 100})
        assert {row["status"] for row in r.data["results"]} == {"closed"}


class TestThereIsOnlyOneDefinition:

    def test_the_dashboard_reads_the_shared_constant(self):
        import inspect

        source = inspect.getsource(_count_open_grievances)
        assert "ACTIVE_GRIEVANCE_STATUSES" in source, (
            "the dashboard tile spells out the statuses again"
        )

    def test_the_console_asks_the_server_rather_than_filtering_rows(self):
        from pathlib import Path

        badge = Path("design/v0.1/data/use-nav-counts.jsx").read_text()
        assert "active=true" in badge
        assert 'r.status !== "closed"' not in badge, (
            "the sidebar badge is filtering statuses in the browser again"
        )
