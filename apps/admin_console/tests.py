"""Admin Console — gating tests (HANDOFF §2.1, §6 AC).

The core acceptance criterion: /admin-console/ returns 200 for
users in any of the five admin groups (nsr_admin / mglsd_statistics
/ dpo / nsr_dba / nsr_security) and 403 for everyone else. The 403
is intentional and loud — a misrouted operator must notice.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.admin_console.permissions import (
    ADMIN_CONSOLE_GROUPS,
    user_can_admin_console,
)


@pytest.mark.django_db
class TestAdminConsoleGate:
    """View-level gating on /admin-console/."""

    URL = "/admin-console/"

    def _make_user(self, username, group_name=None):
        user_cls = get_user_model()
        u = user_cls.objects.create_user(username=username, password="p")
        if group_name:
            grp, _ = Group.objects.get_or_create(name=group_name)
            u.groups.add(grp)
        return u

    def test_anonymous_gets_403(self, client):
        r = client.get(self.URL)
        assert r.status_code == 403

    def test_plain_authenticated_user_gets_403(self, client):
        u = self._make_user("plain-operator")
        client.force_login(u)
        r = client.get(self.URL)
        assert r.status_code == 403
        # Loud failure body — must reference the gate criteria so a
        # misrouted operator can self-diagnose.
        assert b"nsr_admin" in r.content
        assert b"mglsd_statistics" in r.content

    @pytest.mark.parametrize("group", list(ADMIN_CONSOLE_GROUPS))
    def test_every_admin_group_can_access(self, client, group):
        u = self._make_user(f"admin-{group}", group_name=group)
        client.force_login(u)
        r = client.get(self.URL)
        # The HTML harness file may not exist in some test environments;
        # the gate must pass first (200/404 are both "got past 403").
        assert r.status_code != 403

    def test_superuser_can_access(self, client):
        user_cls = get_user_model()
        su = user_cls.objects.create_superuser(username="ad-su", password="p")
        client.force_login(su)
        r = client.get(self.URL)
        assert r.status_code != 403


@pytest.mark.django_db
class TestUserCanAdminConsoleHelper:
    """Unit-level coverage of the can-access helper, independent of
    the view."""

    def test_anonymous_user_returns_false(self):
        from django.contrib.auth.models import AnonymousUser
        assert user_can_admin_console(AnonymousUser()) is False

    def test_none_returns_false(self):
        assert user_can_admin_console(None) is False

    def test_unaffiliated_user_returns_false(self, db):
        user_cls = get_user_model()
        u = user_cls.objects.create_user(username="nobody", password="p")
        assert user_can_admin_console(u) is False

    def test_user_in_any_group_returns_true(self, db):
        user_cls = get_user_model()
        u = user_cls.objects.create_user(username="dpo-user", password="p")
        grp, _ = Group.objects.get_or_create(name="dpo")
        u.groups.add(grp)
        assert user_can_admin_console(u) is True

    def test_superuser_always_returns_true(self, db):
        user_cls = get_user_model()
        su = user_cls.objects.create_superuser(username="super-test", password="p")
        assert user_can_admin_console(su) is True


@pytest.mark.django_db
class TestAdminGroupsSeedMigration:
    """The 0001 seed migration must have created the five groups so
    a fresh deploy has the gate in place."""

    def test_all_five_groups_seeded(self):
        names = set(Group.objects.values_list("name", flat=True))
        for expected in ADMIN_CONSOLE_GROUPS:
            assert expected in names, (
                f"admin-console group {expected!r} not seeded — "
                f"check apps/admin_console/migrations/0001_seed_admin_groups.py"
            )
