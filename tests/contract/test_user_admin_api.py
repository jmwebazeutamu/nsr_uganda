"""The account-administration API contract.

Gated on nsr_admin alone. The admin console itself admits five groups,
so this asserts the narrower gate holds: a DPO or a statistics user can
open the console and still not administer accounts.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

User = get_user_model()

LIST = "/api/v1/security/user-accounts/"


def _user(username, group=None, **kw):
    u = User.objects.create_user(username=username, password="pw", **kw)
    if group:
        u.groups.add(Group.objects.get(name=group))
    return u


@pytest.fixture
def admin(db):
    return _user("api-admin", "nsr_admin")


@pytest.fixture
def target(db):
    return _user("api-target", "enumerator", email="t@example.test")


@pytest.mark.django_db
class TestTheGate:
    def test_anonymous_is_refused(self, client):
        assert client.get(LIST).status_code in (401, 403)

    def test_an_ordinary_operator_is_refused(self, client, db):
        client.force_login(_user("just-an-operator", "enumerator"))
        assert client.get(LIST).status_code == 403

    @pytest.mark.parametrize("group", ["dpo", "nsr_dba", "nsr_security"])
    def test_other_admin_console_groups_are_refused(self, client, db, group):
        """These groups can open the admin console. They cannot administer
        accounts — that was the point of choosing one role."""
        client.force_login(_user(f"console-{group}", group))
        assert client.get(LIST).status_code == 403

    def test_nsr_admin_is_allowed(self, client, admin):
        client.force_login(admin)
        assert client.get(LIST).status_code == 200

    def test_the_refusal_says_why(self, client, db):
        client.force_login(_user("curious", "enumerator"))
        assert "nsr_admin" in client.get(LIST).json()["detail"]


@pytest.mark.django_db
class TestTheSurface:
    def test_there_is_no_delete(self, client, admin, target):
        """Accounts are deactivated, never deleted."""
        client.force_login(admin)
        assert client.delete(f"{LIST}{target.pk}/").status_code in (403, 405)

    def test_a_superuser_is_listed_but_marked_unmanageable(self, client, admin, target):
        User.objects.create_superuser(username="api-root", password="pw")
        client.force_login(admin)
        rows = {r["username"]: r for r in client.get(LIST).json()["results"]}
        assert rows["api-root"]["manageable"] is False
        assert rows["api-target"]["manageable"] is True

    def test_creating_an_account_returns_the_password_once(self, client, admin):
        client.force_login(admin)
        r = client.post(f"{LIST}create/", {
            "username": "brand-new", "email": "bn@example.test",
            "roles": ["enumerator"], "reason": "new starter",
        }, content_type="application/json")
        assert r.status_code == 201
        body = r.json()
        assert body["temporary_password"]
        assert body["user"]["roles"] == ["enumerator"]

        # And it is not retrievable afterwards.
        created = User.objects.get(username="brand-new")
        detail = client.get(f"{LIST}{created.pk}/").json()
        assert "temporary_password" not in detail
        assert "password" not in detail

    def test_the_role_catalogue_is_read_only_and_from_code(self, client, admin):
        client.force_login(admin)
        r = client.get(f"{LIST}roles/")
        assert r.status_code == 200
        codes = {x["code"] for x in r.json()["roles"]}
        assert "nsr_admin" in codes
        # No write verb on the catalogue.
        assert client.post(f"{LIST}roles/", {}, content_type="application/json").status_code in (400, 403, 405)

    def test_a_refused_action_returns_400_with_the_reason(self, client, admin, db):
        root = User.objects.create_superuser(username="api-root2", password="pw")
        client.force_login(admin)
        r = client.post(f"{LIST}{root.pk}/set-active/",
                        {"active": False, "reason": "testing"},
                        content_type="application/json")
        assert r.status_code == 400
        assert "Superuser" in r.json()["detail"]

    def test_search_narrows_the_list(self, client, admin, target):
        client.force_login(admin)
        names = [r["username"] for r in client.get(f"{LIST}?q=target").json()["results"]]
        assert names == ["api-target"]


@pytest.mark.django_db
class TestItDidNotShadowTheScopePicker:
    """`users/` was already taken.

    The Grant Scope modal's user picker and the Roles & scopes screen both
    read /api/v1/security/users/, which is `user_search` — a different
    permission class and a different response shape. Registering the
    account-administration router on `users` shadowed it, because router
    urls come first in urlpatterns. Nothing failed loudly; the picker
    would simply have started getting 403s and an unfamiliar body.
    """

    def test_the_search_endpoint_still_answers_its_own_path(self):
        from django.urls import resolve
        assert resolve("/api/v1/security/users/").url_name == "users-search"

    def test_account_administration_lives_somewhere_else(self):
        from django.urls import resolve
        assert resolve("/api/v1/security/user-accounts/").url_name == "managed-user-list"

    def test_the_picker_still_works_for_a_non_nsr_admin_caller(self, client, db):
        """The whole point of the separation: scope administration has its
        own, wider gate."""
        user = _user("scope-admin-only", "nsr_admin")
        client.force_login(user)
        assert client.get("/api/v1/security/users/?q=scope").status_code == 200


@pytest.mark.django_db
class TestScopeLevelsComeFromTheEnum:
    """The console carried its own copy of the scope levels, taken from
    the default-scope constants in roles.py — a different and smaller set
    — so region, sub_region and village could not be granted at all.

    Nobody noticed, because a missing option looks exactly like a level
    that does not exist. These assert the served list IS ScopeLevel, so
    adding a level to the model is enough and there is no second list to
    remember.
    """

    def test_every_scope_level_is_served(self, client, admin):
        from apps.security.models import ScopeLevel

        client.force_login(admin)
        served = client.get("/api/v1/security/user-accounts/roles/").json()
        values = [lvl["value"] for lvl in served["scope_levels"]]
        assert values == [lvl.value for lvl in ScopeLevel], (
            "the served scope levels have drifted from ScopeLevel"
        )

    def test_the_levels_the_first_cut_dropped_are_present(self, client, admin):
        client.force_login(admin)
        served = client.get("/api/v1/security/user-accounts/roles/").json()
        values = {lvl["value"] for lvl in served["scope_levels"]}
        for missing_before in ("region", "sub_region", "village"):
            assert missing_before in values

    def test_national_is_marked_as_taking_no_codes(self, client, admin):
        """The grant endpoint rejects codes alongside national rather than
        ignoring them, so the screen has to know."""
        client.force_login(admin)
        served = client.get("/api/v1/security/user-accounts/roles/").json()
        by_value = {lvl["value"]: lvl for lvl in served["scope_levels"]}
        assert by_value["national"]["takes_codes"] is False
        assert by_value["district"]["takes_codes"] is True

    def test_partner_is_marked_non_geographic(self, client, admin):
        """Its codes are Partner.code, so the picker must query partners
        rather than the geographic hierarchy."""
        client.force_login(admin)
        served = client.get("/api/v1/security/user-accounts/roles/").json()
        by_value = {lvl["value"]: lvl for lvl in served["scope_levels"]}
        assert by_value["partner"]["geographic"] is False
        assert by_value["district"]["geographic"] is True


class TestTheConsoleKeepsNoCopy:
    def test_the_screen_does_not_list_scope_levels_itself(self):
        """A hand-kept list in the console is the defect, not the
        symptom. This fails if one comes back."""
        from pathlib import Path

        repo = Path(__file__).resolve().parent.parent.parent
        src = (repo / "design" / "v0.1" / "screens"
               / "screens-admin-users.jsx").read_text()
        code = "\n".join(
            line for line in src.splitlines()
            if not line.strip().startswith("//")
        )
        for level in ("sub_region", "sub_county", "village"):
            assert f'value: "{level}"' not in code, (
                f"the screen declares scope level {level!r} itself; it must "
                f"read them from /user-accounts/roles/"
            )
