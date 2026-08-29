"""Registry figures on the landing page.

Two properties matter here and both are security properties, not
cosmetics:

1. The unauthenticated page carries no registry figures at all.
   Household counts are official statistics about a named population;
   publishing them without a session would be an outbound disclosure
   decision for the DPO and a DSA, not a layout choice.
2. The figures a signed-in operator sees are ABAC-scoped. A sub-region
   operator must never read another sub-region's count off the home
   page — the page reuses the scoped aggregator precisely so it cannot
   widen anyone's view.
"""

from datetime import date

import pytest
from django.contrib.auth.models import Group

from apps.data_management.models import Household
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent, OperatorScope, ScopeLevel


@pytest.fixture
def geo(db):
    out = {}
    for sr_key in ["SR-BUGANDA", "SR-KARAMOJA"]:
        nodes, parent = {}, None
        for level, key in [
            ("region", "r"), ("sub_region", "sr"), ("district", "d"),
            ("county", "c"), ("sub_county", "sc"), ("parish", "p"), ("village", "v"),
        ]:
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=f"L-{sr_key}-{key.upper()}", name=f"{sr_key} {key}",
                parent=parent, effective_from=date(2026, 1, 1),
            )
            parent = nodes[key]
        out[sr_key] = nodes
    return out


def _make_households(nodes, n):
    for _ in range(n):
        Household.objects.create(
            region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
            county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"],
            village=nodes["v"], urban_rural="2",
        )


@pytest.fixture
def seeded(geo):
    _make_households(geo["SR-BUGANDA"], 3)
    _make_households(geo["SR-KARAMOJA"], 5)
    return geo


def _scoped_operator(django_user_model, geo, sr_key, username):
    u = django_user_model.objects.create_user(username=username, password="pw")
    u.groups.add(Group.objects.get(name="enumerator"))
    OperatorScope.objects.create(
        user=u, scope_level=ScopeLevel.SUB_REGION,
        scope_code=geo[sr_key]["sr"].code,
    )
    return u


@pytest.mark.django_db
class TestAnonymousPageCarriesNoFigures:

    def test_no_counts_for_anonymous(self, client, seeded):
        body = client.get("/").content
        for marker in (b"Registry at a glance", b"Households registered",
                       b"Households by sub-region", b"Waiting in the intake hub"):
            assert marker not in body, (
                f"{marker!r} was served to an anonymous caller"
            )

    def test_no_sub_region_names_leak(self, client, seeded):
        body = client.get("/").content
        assert b"SR-KARAMOJA" not in body and b"SR-BUGANDA" not in body


@pytest.mark.django_db
class TestFiguresAreScoped:

    def test_superuser_sees_the_national_total(self, client, seeded, django_user_model):
        su = django_user_model.objects.create_user(
            username="root-fig", password="pw", is_superuser=True, is_staff=True,
        )
        client.force_login(su)
        html = client.get("/").content.decode()
        assert "Registry at a glance" in html
        assert "Figures cover the whole country." in html
        # 3 + 5 across both sub-regions.
        assert ">8<" in html.replace(" ", "").replace("\n", "")

    def test_sub_region_operator_sees_only_their_own(
        self, client, seeded, django_user_model,
    ):
        u = _scoped_operator(django_user_model, seeded, "SR-KARAMOJA", "kar-op")
        client.force_login(u)
        html = client.get("/").content.decode()
        assert "Registry at a glance" in html
        # Their own sub-region is named and counted; the other is absent.
        assert "SR-KARAMOJA sr" in html
        assert "SR-BUGANDA" not in html, "another sub-region leaked onto the home page"

    def test_the_page_says_whose_numbers_these_are(
        self, client, seeded, django_user_model,
    ):
        u = _scoped_operator(django_user_model, seeded, "SR-BUGANDA", "bug-op")
        client.force_login(u)
        html = client.get("/").content.decode()
        assert "the area your role allows" in html
        assert "Figures cover the whole country." not in html

    def test_unscoped_user_fails_closed_to_zero(
        self, client, seeded, django_user_model,
    ):
        """No OperatorScope → _scoped_codes returns [] → no rows."""
        u = django_user_model.objects.create_user(username="unscoped", password="pw")
        u.groups.add(Group.objects.get(name="enumerator"))
        client.force_login(u)
        html = client.get("/").content.decode()
        assert "SR-KARAMOJA" not in html and "SR-BUGANDA" not in html
        assert "No households have been registered in your area yet" in html


@pytest.mark.django_db
class TestFiguresAreAudited:

    def test_reading_the_home_page_emits_one_dashboard_read(
        self, client, seeded, django_user_model,
    ):
        u = _scoped_operator(django_user_model, seeded, "SR-BUGANDA", "audited-op")
        client.force_login(u)
        before = AuditEvent.objects.filter(action="dashboard_read").count()
        client.get("/")
        rows = AuditEvent.objects.filter(action="dashboard_read")
        assert rows.count() == before + 1
        assert rows.order_by("-id").first().entity_id == "landing_kpis"

    def test_anonymous_read_emits_nothing(self, client, seeded):
        before = AuditEvent.objects.filter(action="dashboard_read").count()
        client.get("/")
        assert AuditEvent.objects.filter(action="dashboard_read").count() == before
