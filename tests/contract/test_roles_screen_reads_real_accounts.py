"""The Roles & scopes screen must read accounts, not invent them.

The admin console's user-administration screen rendered ten fabricated
operator accounts — plausible names on @mglsd.go.ug, @opm.go.ug and
district addresses, each with a role, scopes and an MFA state — from a
`SEC_USERS` array. It issued no request for users at all. Its Save and
Delete buttons wrote to React state, so "Akello P. deleted from this
workspace" left the account untouched and said otherwise.

Two earlier cleanup passes marked the screen done, because each one
searched for the fixture named in the previous finding and `SEC_USERS`
was never that fixture.

These cases pin both halves of the fix: the endpoints the screen needs
exist and return the registry's own data, and the screen reads them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rest_framework.test import APIClient

REPO = Path(__file__).resolve().parent.parent.parent
SCREEN = REPO / "design" / "v0.1" / "screens" / "screens-admin-security-roles.jsx"


def _nsr_admin(django_user_model):
    from django.contrib.auth.models import Group
    user = django_user_model.objects.create_user(username="roles-admin", password="x")
    grp, _ = Group.objects.get_or_create(name="nsr_admin")
    user.groups.add(grp)
    return user


# --- the API the screen depends on ----------------------------------------

@pytest.mark.django_db
class TestRoleCatalogueEndpoint:
    URL = "/api/v1/security/roles/"

    def test_returns_the_catalogue_in_roles_py(self, django_user_model):
        from apps.security.roles import ROLES
        client = APIClient()
        client.force_authenticate(_nsr_admin(django_user_model))
        resp = client.get(self.URL)
        assert resp.status_code == 200, resp.content
        # Exactly the catalogue — not a subset, and nothing invented. The
        # screen's own nine-role fixture named roles ("parish_coordinator")
        # that have never existed in this system.
        assert [r["code"] for r in resp.json()] == [r.code for r in ROLES]

    def test_permissions_are_the_catalogue_permissions(self, django_user_model):
        from apps.security.roles import BY_CODE
        client = APIClient()
        client.force_authenticate(_nsr_admin(django_user_model))
        rows = {r["code"]: r for r in client.get(self.URL).json()}
        for code, row in rows.items():
            assert set(row["permissions"]) == set(BY_CODE[code].permissions)
            assert row["default_scope"] == BY_CODE[code].default_scope

    def test_member_count_is_real_group_membership(self, django_user_model):
        from django.contrib.auth.models import Group
        admin = _nsr_admin(django_user_model)  # already in nsr_admin
        cdo, _ = Group.objects.get_or_create(name="cdo")
        django_user_model.objects.create_user(username="a", password="x").groups.add(cdo)
        django_user_model.objects.create_user(username="b", password="x").groups.add(cdo)
        client = APIClient()
        client.force_authenticate(admin)
        rows = {r["code"]: r for r in client.get(self.URL).json()}
        assert rows["cdo"]["member_count"] == 2
        assert rows["nsr_admin"]["member_count"] == 1

    def test_role_with_no_group_yet_counts_zero_rather_than_vanishing(
        self, django_user_model,
    ):
        # sync_roles may not have run. The role must still be listed —
        # an absent row reads as "this role does not exist".
        client = APIClient()
        client.force_authenticate(_nsr_admin(django_user_model))
        rows = {r["code"]: r for r in client.get(self.URL).json()}
        assert rows["auditor"]["member_count"] == 0

    def test_non_admin_gets_403(self, django_user_model):
        u = django_user_model.objects.create_user(username="plain", password="x")
        client = APIClient()
        client.force_authenticate(u)
        assert client.get(self.URL).status_code == 403


@pytest.mark.django_db
class TestUserListCarriesWhatTheScreenRenders:
    URL = "/api/v1/security/users/"

    def test_returns_status_login_and_email(self, django_user_model):
        admin = _nsr_admin(django_user_model)
        django_user_model.objects.create_user(
            username="ops-grace", password="x", email="grace@example.test",
            first_name="Grace", last_name="Akello", is_active=False,
        )
        client = APIClient()
        client.force_authenticate(admin)
        rows = {u["username"]: u for u in client.get(self.URL).json()}
        row = rows["ops-grace"]
        assert row["email"] == "grace@example.test"
        assert row["is_active"] is False
        assert row["is_superuser"] is False
        assert row["last_login"] is None       # never signed in — not a date
        assert row["date_joined"]
        assert row["display_name"] == "Grace Akello"

    def test_keeps_the_grant_scope_picker_contract(self, django_user_model):
        # US-S11-028's user picker reads these four. The screen's extra
        # fields were added alongside them, not in place of them.
        admin = _nsr_admin(django_user_model)
        client = APIClient()
        client.force_authenticate(admin)
        row = client.get(self.URL).json()[0]
        assert {"id", "username", "display_name", "groups"} <= set(row)

    def test_reports_no_mfa_state(self, django_user_model):
        # There is no MFA implementation in this system. The screen used
        # to show an MFA method and an "MFA not enrolled" KPI for every
        # account; the endpoint must not start supplying one by accident.
        admin = _nsr_admin(django_user_model)
        client = APIClient()
        client.force_authenticate(admin)
        row = client.get(self.URL).json()[0]
        assert not any("mfa" in key.lower() for key in row)


# --- the screen that consumes it ------------------------------------------

def _source() -> str:
    return SCREEN.read_text()


def test_screen_fetches_all_three_sources():
    src = _source()
    for endpoint in (
        "/api/v1/security/users/",
        "/api/v1/security/operator-scopes/",
        "/api/v1/security/roles/",
    ):
        assert endpoint in src, f"the screen no longer reads {endpoint}"


def test_screen_holds_no_account_fixture():
    src = _source()
    body = re.sub(r"//.*$", "", src, flags=re.M)
    assert "SEC_USERS" not in body, "the fabricated account fixture is back"
    assert "SEC_ROLES" not in body, "the fabricated role fixture is back"
    # The addresses the fixture used. Catching the shape, not the names,
    # is what the previous sweeps failed to do.
    assert not re.search(r"@(?:[a-z0-9-]+\.)*go\.ug", body), (
        "a government e-mail literal is in the roles screen again"
    )


def test_screen_starts_empty_rather_than_seeded():
    src = _source()
    for state in ("users", "scopes", "roles"):
        assert re.search(rf"\[{state},\s*set\w+\]\s*=\s*useStateSEC\(null\)", src), (
            f"`{state}` no longer starts as null, so the screen cannot tell "
            f"'still loading' from 'loaded and empty'"
        )


def test_screen_does_not_offer_writes_it_cannot_make():
    # Roles are code-defined (ADR-0028 D1) and scope grants belong to the
    # Operator scopes tab, which audits them. Local-state Save/Delete
    # buttons told an administrator that access had changed when it had not.
    src = _source()
    for ghost in ("saveUser", "deleteUser", "saveRole", "deleteRole", "secBlankUser"):
        assert ghost not in src, f"{ghost} is back — it writes to nothing"
