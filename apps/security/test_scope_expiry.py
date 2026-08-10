"""OperatorScope validity window (G5).

`active` was the only control, so a secondment or contractor grant could not be
time-boxed and revocation was manual.

The field is the easy half. The half worth testing is that expiry is *enforced*
— eight call sites resolved scopes independently, and a field that looks like a
control but is not consulted is worse than not having one. So these tests drive
the real API, not just the manager.
"""

from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.data_management.models import Household
from apps.reference_data.models import GeographicUnit
from apps.security.models import OperatorScope, ScopeLevel

HH_URL = "/api/v1/data-management/households/"


@pytest.fixture
def geo(db):
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"E-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return nodes


@pytest.fixture
def household(db, geo):
    return Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"],
        county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
        village=geo["v"], urban_rural="2", address_narrative="Plot 5",
    )


@pytest.fixture
def operator(db, django_user_model):
    return django_user_model.objects.create_user(username="seconded-officer")


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _scope(user, geo, **kw):
    return OperatorScope.objects.create(
        user=user, scope_level=ScopeLevel.SUB_REGION,
        scope_code=geo["sr"].code, active=True, **kw,
    )


@pytest.mark.django_db
class TestExpiryIsEnforcedThroughTheApi:

    def test_open_ended_scope_sees_the_household(self, operator, household, geo):
        _scope(operator, geo)  # expires_at NULL
        r = _client(operator).get(HH_URL)
        assert r.data["count"] == 1

    def test_future_expiry_still_sees_it(self, operator, household, geo):
        _scope(operator, geo, expires_at=timezone.now() + timedelta(days=30))
        r = _client(operator).get(HH_URL)
        assert r.data["count"] == 1

    def test_expired_scope_sees_nothing(self, operator, household, geo):
        """The point of the whole change: a lapsed secondment grants nothing,
        the moment it lapses, without waiting for a sweep to run."""
        _scope(operator, geo, expires_at=timezone.now() - timedelta(seconds=1))
        r = _client(operator).get(HH_URL)
        assert r.data["count"] == 0, (
            "an expired OperatorScope still granted visibility — expiry is "
            "not being consulted at this enforcement point"
        )

    def test_expiry_is_a_moment_not_a_day(self, operator, household, geo):
        s = _scope(operator, geo, expires_at=timezone.now() + timedelta(seconds=2))
        assert _client(operator).get(HH_URL).data["count"] == 1
        s.expires_at = timezone.now() - timedelta(microseconds=1)
        s.save(update_fields=["expires_at"])
        assert _client(operator).get(HH_URL).data["count"] == 0

    def test_inactive_beats_a_future_expiry(self, operator, household, geo):
        s = _scope(operator, geo, expires_at=timezone.now() + timedelta(days=30))
        s.active = False
        s.save(update_fields=["active"])
        assert _client(operator).get(HH_URL).data["count"] == 0


@pytest.mark.django_db
class TestManagerSemantics:

    def test_effective_excludes_expired_and_inactive(self, operator, geo):
        live = _scope(operator, geo)
        # A different level, so the (user, level, code) uniqueness holds.
        expired = OperatorScope.objects.create(
            user=operator, scope_level=ScopeLevel.DISTRICT,
            scope_code=geo["d"].code, active=True,
            expires_at=timezone.now() - timedelta(days=1),
        )

        effective = set(OperatorScope.objects.effective()
                        .filter(user=operator).values_list("id", flat=True))
        assert live.id in effective
        assert expired.id not in effective

    def test_expired_queryset(self, operator, geo):
        s = _scope(operator, geo, expires_at=timezone.now() - timedelta(days=1))
        assert s.id in set(
            OperatorScope.objects.expired().values_list("id", flat=True))

    def test_open_ended_is_never_expired(self, operator, geo):
        s = _scope(operator, geo)
        assert s.id not in set(
            OperatorScope.objects.expired().values_list("id", flat=True))

    def test_effective_accepts_an_as_of_moment(self, operator, geo):
        s = _scope(operator, geo, expires_at=timezone.now() + timedelta(days=5))
        later = timezone.now() + timedelta(days=6)
        assert s.id not in set(
            OperatorScope.objects.effective(at=later).values_list("id", flat=True))


@pytest.mark.django_db
class TestSingleEntityHelpersRespectExpiry:
    """The queryset mixins and the single-entity helpers are separate code
    paths; both are enforcement points."""

    def test_user_can_access_household_honours_expiry(
        self, operator, household, geo,
    ):
        from apps.security.abac import user_can_access_household

        s = _scope(operator, geo)
        assert user_can_access_household(operator, household.id) is True
        s.expires_at = timezone.now() - timedelta(seconds=1)
        s.save(update_fields=["expires_at"])
        assert user_can_access_household(operator, household.id) is False


@pytest.mark.django_db
class TestCreateOperatorExpiry:
    """A bare --expires date must mean the END of that day.

    Django's parse_datetime accepts "2099-09-30" and returns midnight, so a
    naive implementation lapses the scope at the START of that day — a day
    short, silently, which is the worst shape of access bug.
    """

    def _run(self, username, **kw):
        from django.core.management import call_command
        call_command("create_operator", username, role="cdo",
                     scope_code="E-D", **kw)
        return OperatorScope.objects.get(user__username=username)

    def test_bare_date_expires_at_end_of_day(self, db, geo):
        s = self._run("exp-bare", expires="2099-09-30")
        assert (s.expires_at.hour, s.expires_at.minute) == (23, 59)
        assert s.expires_at.date().isoformat() == "2099-09-30"

    def test_explicit_datetime_is_respected(self, db, geo):
        s = self._run("exp-dt", expires="2099-09-30T09:00")
        assert (s.expires_at.hour, s.expires_at.minute) == (9, 0)

    def test_open_ended_by_default(self, db, geo):
        s = self._run("exp-none")
        assert s.expires_at is None

    def test_past_expiry_is_refused(self, db, geo):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with pytest.raises(CommandError, match="in the past"):
            call_command("create_operator", "exp-past", role="cdo",
                         scope_code="E-D", expires="2020-01-01")

    def test_unparseable_expiry_is_refused(self, db, geo):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with pytest.raises(CommandError, match="could not parse"):
            call_command("create_operator", "exp-bad", role="cdo",
                         scope_code="E-D", expires="soon")
