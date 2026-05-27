"""US-S11-042 — Impersonation service + endpoints + middleware guard."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.security.models import AuditEvent

URL_START = "/api/v1/security/impersonate/"
URL_STOP = "/api/v1/security/impersonate/stop/"
URL_ME = "/api/v1/security/users/me/"


@pytest.fixture
def admin_user(db):
    user = get_user_model().objects.create_user(
        username="admin-imp", password="x",
    )
    grp, _ = Group.objects.get_or_create(name="nsr_admin")
    user.groups.add(grp)
    return user


@pytest.fixture
def superuser(db):
    return get_user_model().objects.create_superuser(
        username="super-imp", password="x",
    )


@pytest.fixture
def plain_user(db):
    return get_user_model().objects.create_user(
        username="ops-grace", password="x",
        first_name="Grace", last_name="Akello",
    )


@pytest.fixture
def other_superuser(db):
    return get_user_model().objects.create_superuser(
        username="super-other", password="x",
    )


def _login(client, user):
    """Force a real login (sets _auth_user_id + _auth_user_backend in
    session) so the impersonation swap has something to swap."""
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestImpersonateStart:
    def test_admin_can_impersonate_non_admin(self, admin_user, plain_user):
        c = _login(APIClient(), admin_user)
        r = c.post(URL_START, {
            "user_id": plain_user.id,
            "reason": "Debugging partner-affiliated view",
        }, format="json")
        assert r.status_code == 200, r.content
        # /me/ now reports the target user with the impersonator block.
        me = c.get(URL_ME)
        assert me.data["username"] == plain_user.username
        assert me.data["impersonator"]["username"] == admin_user.username
        assert "partner-affiliated" in me.data["impersonator"]["reason"]
        # Audit emitted.
        ev = AuditEvent.objects.filter(
            action="security.impersonation.started",
        ).first()
        assert ev is not None
        assert ev.actor_id == admin_user.username
        assert ev.field_changes["target_username"] == plain_user.username

    def test_superuser_can_impersonate_non_admin(self, superuser, plain_user):
        c = _login(APIClient(), superuser)
        r = c.post(URL_START, {
            "user_id": plain_user.id, "reason": "support ticket #42",
        }, format="json")
        assert r.status_code == 200

    def test_non_admin_cannot_impersonate(self, plain_user):
        # plain_user has no admin group → IsOperatorScopeAdmin 403s.
        target = get_user_model().objects.create_user(username="t1", password="x")
        c = _login(APIClient(), plain_user)
        r = c.post(URL_START, {"user_id": target.id, "reason": "x"}, format="json")
        assert r.status_code == 403

    def test_cannot_impersonate_another_superuser(
        self, admin_user, other_superuser,
    ):
        c = _login(APIClient(), admin_user)
        r = c.post(URL_START, {
            "user_id": other_superuser.id, "reason": "x",
        }, format="json")
        assert r.status_code == 400
        assert "superuser" in r.json()["detail"]

    def test_cannot_impersonate_self(self, admin_user):
        c = _login(APIClient(), admin_user)
        r = c.post(URL_START, {
            "user_id": admin_user.id, "reason": "x",
        }, format="json")
        assert r.status_code == 400
        assert "yourself" in r.json()["detail"]

    def test_blank_reason_is_rejected(self, admin_user, plain_user):
        c = _login(APIClient(), admin_user)
        r = c.post(URL_START, {
            "user_id": plain_user.id, "reason": "   ",
        }, format="json")
        assert r.status_code == 400
        assert "Reason is required" in r.json()["detail"]

    def test_double_start_is_rejected(self, admin_user, plain_user, db):
        target2 = get_user_model().objects.create_user(username="t2", password="x")
        c = _login(APIClient(), admin_user)
        r1 = c.post(URL_START, {"user_id": plain_user.id, "reason": "x"}, format="json")
        assert r1.status_code == 200
        r2 = c.post(URL_START, {"user_id": target2.id, "reason": "y"}, format="json")
        # 403 from the read-only middleware (you're already
        # impersonating, so writes are blocked even for start).
        assert r2.status_code == 403
        assert "impersonating" in r2.json()["detail"]


@pytest.mark.django_db
class TestImpersonateStop:
    def test_stop_reverts_session(self, admin_user, plain_user):
        c = _login(APIClient(), admin_user)
        c.post(URL_START, {
            "user_id": plain_user.id, "reason": "Debugging",
        }, format="json")
        r = c.post(URL_STOP, {}, format="json")
        assert r.status_code == 200, r.content
        # /me/ now reports the admin again, with no impersonator block.
        me = c.get(URL_ME)
        assert me.data["username"] == admin_user.username
        assert me.data["impersonator"] is None
        # Audit emitted.
        ev = AuditEvent.objects.filter(
            action="security.impersonation.stopped",
        ).first()
        assert ev is not None
        assert ev.actor_id == admin_user.username

    def test_stop_without_active_session_is_rejected(self, admin_user):
        c = _login(APIClient(), admin_user)
        r = c.post(URL_STOP, {}, format="json")
        assert r.status_code == 400
        assert "No active impersonation" in r.json()["detail"]


@pytest.mark.django_db
class TestImpersonationReadOnlyGuard:
    """ImpersonationGuardMiddleware blocks non-SAFE methods while
    impersonating; the /stop/ endpoint itself is exempt."""

    def test_write_blocked_during_impersonation(self, admin_user, plain_user):
        c = _login(APIClient(), admin_user)
        c.post(URL_START, {
            "user_id": plain_user.id, "reason": "Debugging",
        }, format="json")
        # Any non-safe method — try POST to bulk-grant (which the
        # plain user wouldn't have permission for anyway, but the
        # middleware runs first).
        r = c.post(
            "/api/v1/security/operator-scopes/bulk-grant/",
            {"user_id": plain_user.id, "scope_level": "national", "scope_codes": []},
            format="json",
        )
        assert r.status_code == 403
        assert "impersonation mode" in r.json()["detail"]

    def test_safe_methods_still_work(self, admin_user, plain_user):
        c = _login(APIClient(), admin_user)
        c.post(URL_START, {
            "user_id": plain_user.id, "reason": "Debugging",
        }, format="json")
        r = c.get("/api/v1/security/users/me/")
        assert r.status_code == 200

    def test_stop_endpoint_exempt(self, admin_user, plain_user):
        c = _login(APIClient(), admin_user)
        c.post(URL_START, {
            "user_id": plain_user.id, "reason": "Debugging",
        }, format="json")
        # Even though POST + impersonating, /stop/ must work.
        r = c.post(URL_STOP, {}, format="json")
        assert r.status_code == 200
