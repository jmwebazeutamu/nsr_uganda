"""Account administration: what it does, and what it refuses.

The refusals carry more weight than the happy path. An admin who can
grant themselves a role, or reset a superuser's password, is one
compromised account away from owning the registry — and an audit entry
proving they did it is not the same as their having been unable to.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail

from apps.security import user_management as um
from apps.security.models import AuditEvent

User = get_user_model()


@pytest.fixture
def admin(db):
    u = User.objects.create_user(username="the-admin", password="pw")
    u.groups.add(Group.objects.get(name="nsr_admin"))
    return u


@pytest.fixture
def operator(db):
    u = User.objects.create_user(username="an-operator", password="pw",
                                 email="op@example.test")
    u.groups.add(Group.objects.get(name="enumerator"))
    return u


@pytest.fixture
def root(db):
    return User.objects.create_superuser(username="root", password="pw")


@pytest.mark.django_db
class TestTheGuards:
    def test_an_admin_cannot_change_their_own_roles(self, admin):
        """Self-promotion is the cheapest escalation there is."""
        with pytest.raises(um.UserManagementError, match="your own roles"):
            um.set_roles(actor=admin, user=admin, roles=["nsr_admin", "dpo"],
                         reason="because I can")

    def test_no_action_may_target_a_superuser(self, admin, root):
        for call in (
            lambda: um.set_roles(actor=admin, user=root, roles=[], reason="r"),
            lambda: um.set_active(actor=admin, user=root, active=False, reason="r"),
            lambda: um.reset_password(actor=admin, user=root, reason="r"),
        ):
            with pytest.raises(um.UserManagementError, match="Superuser"):
                call()

    def test_an_admin_cannot_deactivate_themselves(self, admin):
        with pytest.raises(um.UserManagementError, match="your own account"):
            um.set_active(actor=admin, user=admin, active=False, reason="oops")

    def test_a_reason_is_required_for_every_change(self, admin, operator):
        for call in (
            lambda: um.set_roles(actor=admin, user=operator, roles=[], reason=""),
            lambda: um.set_active(actor=admin, user=operator, active=False, reason="  "),
            lambda: um.reset_password(actor=admin, user=operator, reason=""),
        ):
            with pytest.raises(um.UserManagementError, match="reason is required"):
                call()

    def test_a_created_account_is_never_staff_or_superuser(self, admin):
        user, _ = um.create_user(actor=admin, username="new-hire",
                                 reason="joined the unit")
        assert user.is_staff is False
        assert user.is_superuser is False


@pytest.mark.django_db
class TestRolesAreMembershipOnly:
    def test_an_unknown_role_is_refused(self, admin, operator):
        with pytest.raises(um.UserManagementError, match="catalogue"):
            um.set_roles(actor=admin, user=operator, roles=["wizard"],
                         reason="promotion")

    def test_the_catalogue_comes_from_code_not_the_database(self, admin):
        codes = {r["code"] for r in um.role_catalogue()}
        assert "nsr_admin" in codes and "enumerator" in codes
        # Inventing a Group must not invent a role.
        Group.objects.create(name="not-a-real-role")
        assert "not-a-real-role" not in {r["code"] for r in um.role_catalogue()}

    def test_setting_roles_replaces_rather_than_adds(self, admin, operator):
        um.set_roles(actor=admin, user=operator, roles=["supervisor"],
                     reason="moved to supervision")
        operator.refresh_from_db()
        assert sorted(g.name for g in operator.groups.all()) == ["supervisor"]

    def test_privileged_grants_are_marked_in_the_audit_reason(self, admin, operator):
        um.set_roles(actor=admin, user=operator, roles=["dpo"],
                     reason="appointed DPO")
        event = AuditEvent.objects.filter(
            entity_type="user", entity_id=str(operator.pk),
        ).order_by("-occurred_at").first()
        assert "privileged" in event.reason


@pytest.mark.django_db
class TestPasswordReset:
    def test_a_temporary_password_actually_works(self, admin, operator):
        result = um.reset_password(actor=admin, user=operator,
                                   method="temporary", reason="locked out")
        operator.refresh_from_db()
        assert operator.check_password(result["temporary_password"])

    def test_the_temporary_password_never_reaches_the_audit_chain(
        self, admin, operator,
    ):
        result = um.reset_password(actor=admin, user=operator,
                                   method="temporary", reason="locked out")
        secret = result["temporary_password"]
        for event in AuditEvent.objects.filter(entity_id=str(operator.pk)):
            assert secret not in (event.reason or "")
            assert secret not in str(event.field_changes or {})

    def test_it_avoids_characters_that_are_misread_aloud(self):
        # Read off a screen and dictated over a phone: O/0 and l/1/I are
        # where that goes wrong.
        for _ in range(40):
            assert not (set(um.generate_temporary_password()) & set("O0lI1"))

    def test_a_link_reset_emails_the_user_and_tells_nobody_the_password(
        self, admin, operator,
    ):
        result = um.reset_password(actor=admin, user=operator, method="link",
                                   reason="requested by the user",
                                   reset_url_base="https://example.test")
        assert result == {"method": "link", "sent_to": "op@example.test"}
        assert len(mail.outbox) == 1
        assert "op@example.test" in mail.outbox[0].to

    def test_a_link_reset_is_refused_when_there_is_no_mailbox(self, admin):
        no_email = User.objects.create_user(username="field-hand", password="pw")
        with pytest.raises(um.UserManagementError, match="no email address"):
            um.reset_password(actor=admin, user=no_email, method="link",
                              reason="locked out")


@pytest.mark.django_db
class TestDeactivation:
    def test_it_disables_rather_than_deletes(self, admin, operator):
        um.set_active(actor=admin, user=operator, active=False, reason="left the unit")
        operator.refresh_from_db()
        assert operator.is_active is False
        # The audit chain references users by username; deleting one
        # leaves the trail pointing at nobody.
        assert User.objects.filter(pk=operator.pk).exists()

    def test_reactivation_is_audited_too(self, admin, operator):
        um.set_active(actor=admin, user=operator, active=False, reason="suspended")
        um.set_active(actor=admin, user=operator, active=True, reason="cleared")
        reasons = [
            e.reason for e in
            AuditEvent.objects.filter(entity_id=str(operator.pk)).order_by("occurred_at")
        ]
        assert any("deactivated" in r for r in reasons)
        assert any("reactivated" in r for r in reasons)
