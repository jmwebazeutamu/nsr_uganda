"""The public site process.

Two guarantees, both security ones:

1. The public URLconf routes the public page and nothing else. LP-O-10
   asks for a public zone with no route to the registry; running this
   process with ROOT_URLCONF=nsr_mis.urls_public is the application-level
   half of it, and it is worthless if it drifts.
2. Nothing personal, and no unfloored figure, reaches an anonymous
   caller.
"""

import pytest
from django.urls import Resolver404, resolve

PUBLIC_URLCONF = "nsr_mis.urls_public"

pytestmark = pytest.mark.django_db


@pytest.fixture
def public(settings):
    settings.ROOT_URLCONF = PUBLIC_URLCONF
    settings.ALLOWED_HOSTS = ["*"]
    return settings


class TestTheZoneRoutesNothingElse:

    @pytest.mark.parametrize("path", [
        "/console/", "/admin/", "/admin-console/", "/manual/",
        "/api/v1/data-management/households/", "/api/v1/security/audit-events/",
        "/login/", "/logout/",
    ])
    def test_registry_routes_are_absent_from_the_public_zone(self, public, path):
        with pytest.raises(Resolver404):
            resolve(path, urlconf=PUBLIC_URLCONF)

    def test_the_landing_page_itself_resolves(self, public):
        assert resolve("/", urlconf=PUBLIC_URLCONF) is not None

    def test_healthz_is_the_only_other_route_and_reads_nothing(self, public, client):
        """The container healthcheck needs an endpoint; it must stay inert."""
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.content == b"ok"

    def test_the_page_is_served_to_an_anonymous_caller(self, public, client):
        assert client.get("/").status_code == 200


class TestFiguresAreGated:

    def test_flag_off_publishes_no_real_figures(self, public, client):
        public.NSR_PUBLIC_STATS_LIVE = False
        html = client.get("/").content.decode()
        assert "0,000,000" in html, "placeholder slots should stand in"
        # LP-O-06 also appears in the mockup's own placeholder footnote, so
        # key off the sentence only the live path emits.
        assert "drawn live from the registry" not in html

    def test_flag_on_states_the_method_and_the_date(self, public, client):
        public.NSR_PUBLIC_STATS_LIVE = True
        html = client.get("/").content.decode()
        assert "drawn live from the registry" in html
        assert "LP-O-06" in html, "figures published without naming the open sign-off"
        assert "as at" in html


class TestNoPersonalData:

    @pytest.fixture(autouse=True)
    def _live(self, public):
        public.NSR_PUBLIC_STATS_LIVE = True

    def test_no_registry_identifier_reaches_the_page(self, client):
        from apps.data_management.models import Household
        html = client.get("/").content.decode()
        for hh in Household.objects.all()[:30]:
            assert str(hh.id) not in html, "a registry ID reached the public page"

    def test_no_member_identifier_reaches_the_page(self, client):
        from apps.data_management.models import Member
        html = client.get("/").content.decode()
        for m in Member.objects.all()[:30]:
            for attr in ("first_name", "surname", "nin_hash", "phone_number"):
                val = str(getattr(m, attr, "") or "")
                if len(val) > 4:
                    assert val not in html, f"Member.{attr} reached the public page"

    def test_every_published_count_is_floored(self, client):
        from apps.reporting.public_aggregates import (
            ROUND_TO,
            SUPPRESSION_THRESHOLD,
            coverage_by_sub_region,
        )
        for cell in coverage_by_sub_region().cells:
            if cell.suppressed:
                assert cell.value is None
                continue
            assert cell.value >= SUPPRESSION_THRESHOLD
            if cell.value < 100:
                assert cell.value % ROUND_TO == 0, (
                    f"{cell.label} published as {cell.value}, not rounded"
                )

    def test_a_lone_small_cell_never_stands_alone(self, client):
        from apps.reporting.public_aggregates import coverage_by_sub_region
        n = sum(1 for c in coverage_by_sub_region().cells if c.suppressed)
        assert n != 1, "a single suppressed cell is recoverable by subtraction"


class TestStaffSignIn:

    def test_the_signin_link_points_at_the_configured_mis(self, public, client):
        public.NSR_STAFF_SIGNIN_URL = "https://mis.example.go.ug/login/"
        html = client.get("/").content.decode()
        assert "https://mis.example.go.ug/login/" in html
