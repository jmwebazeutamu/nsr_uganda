"""Landing page, the login gate on every resource, and permission enforcement.

Audit finding F2 was that /console/ and /manual/ were registered
unconditionally despite comments claiming they were dev-only, and were
reachable without a session. These tests make that a build failure if it
regresses.
"""

import pytest
from django.contrib.auth.models import Group
from django.test import override_settings
from rest_framework.test import APIClient


@pytest.fixture
def admin_user(db, django_user_model):
    u = django_user_model.objects.create_user(username="an-admin", password="pw")
    u.groups.add(Group.objects.get(name="nsr_admin"))
    return u


@pytest.fixture
def plain_user(db, django_user_model):
    u = django_user_model.objects.create_user(username="an-operator", password="pw")
    u.groups.add(Group.objects.get(name="enumerator"))
    return u


@pytest.mark.django_db
class TestLandingPage:

    def test_landing_is_public(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"National Social Registry" in r.content

    def test_landing_offers_sign_in_when_anonymous(self, client):
        r = client.get("/")
        assert b"/login/" in r.content

    def test_signed_in_operator_sees_console_only(self, client, plain_user):
        client.force_login(plain_user)
        r = client.get("/")
        assert r.status_code == 200
        assert b'href="/console/"' in r.content
        assert b'href="/admin-console/"' not in r.content

    def test_signed_in_admin_sees_both_consoles(self, client, admin_user):
        client.force_login(admin_user)
        r = client.get("/")
        assert b'href="/console/"' in r.content
        assert b'href="/admin-console/"' in r.content

    def test_roleless_user_is_told(self, client, django_user_model):
        u = django_user_model.objects.create_user(username="nobody", password="pw")
        client.force_login(u)
        r = client.get("/")
        assert b"No role has been assigned" in r.content


@pytest.mark.django_db
class TestEverythingElseRequiresLogin:
    """F2 regression guard."""

    @pytest.mark.parametrize("path", ["/console/", "/manual/"])
    def test_anonymous_is_redirected_to_login(self, client, path):
        r = client.get(path)
        assert r.status_code in (301, 302), (
            f"{path} served content to an anonymous caller"
        )
        assert "/login/" in r["Location"]

    def test_admin_console_refuses_anonymous(self, client):
        r = client.get("/admin-console/")
        assert r.status_code in (301, 302, 403)

    def test_console_reachable_once_signed_in(self, client, plain_user):
        client.force_login(plain_user)
        r = client.get("/console/")
        assert r.status_code == 200

    def test_admin_console_refuses_a_plain_operator(self, client, plain_user):
        client.force_login(plain_user)
        r = client.get("/admin-console/")
        assert r.status_code == 403

    def test_admin_console_allows_an_admin(self, client, admin_user):
        client.force_login(admin_user)
        r = client.get("/admin-console/")
        assert r.status_code == 200

    def test_healthz_stays_anonymous(self, client):
        assert client.get("/healthz").status_code == 200


@pytest.mark.django_db
class TestDataPermissionEnforcement:

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_read_is_not_action_gated(self, plain_user):
        """Reads are bounded by IsAuthenticated + ABAC, not by an action class."""
        r = self._api(plain_user).get("/api/v1/data-management/households/")
        assert r.status_code == 200

    def test_write_without_the_permission_is_refused(self, db, django_user_model):
        u = django_user_model.objects.create_user(username="viewer-only", password="pw")
        u.groups.add(Group.objects.get(name="auditor"))  # read + export, no entry
        r = self._api(u).post("/api/v1/grm/grievances/", {}, format="json")
        assert r.status_code == 403
        assert "data entry" in str(r.data).lower()

    def test_write_with_the_permission_is_not_refused_by_this_layer(
        self, db, django_user_model,
    ):
        u = django_user_model.objects.create_user(username="enum-2", password="pw")
        u.groups.add(Group.objects.get(name="enumerator"))  # has data_entry
        r = self._api(u).post("/api/v1/grm/grievances/", {}, format="json")
        # 400 (validation) rather than 403 — the permission layer let it through.
        assert r.status_code != 403

    def test_superuser_bypasses(self, db, django_user_model):
        su = django_user_model.objects.create_user(
            username="root-1", password="pw", is_superuser=True,
        )
        r = self._api(su).post("/api/v1/grm/grievances/", {}, format="json")
        assert r.status_code != 403

    @override_settings(NSR_ENFORCE_DATA_PERMISSIONS=False)
    def test_flag_off_disables_the_layer(self, db, django_user_model):
        u = django_user_model.objects.create_user(username="viewer-2", password="pw")
        u.groups.add(Group.objects.get(name="auditor"))
        r = self._api(u).post("/api/v1/grm/grievances/", {}, format="json")
        assert r.status_code != 403
