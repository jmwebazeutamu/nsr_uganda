"""Role grant applies the catalogue's default scope (G7).

Before this, `default_scope` was documentation: adding someone to `cdo` gave
them the permissions and no OperatorScope, and because the ABAC mixins fail
closed the symptom was an empty screen rather than an error.

The behaviour is deliberately asymmetric, and these tests pin both halves —
including the half that does nothing, which is the easier one to erode later.
"""

import pytest
from django.contrib.auth.models import Group

from apps.security.models import AuditEvent, OperatorScope
from apps.security.scope_provisioning import ensure_default_scopes


@pytest.fixture
def user(db, django_user_model):
    return django_user_model.objects.create_user(username="g7-subject")


@pytest.mark.django_db
class TestNationalRolesAreProvisioned:

    def test_granting_a_national_role_creates_the_scope(self, user):
        user.groups.add(Group.objects.get(name="nsr_unit_coordinator"))
        scopes = OperatorScope.objects.filter(user=user, active=True)
        assert [(s.scope_level, s.scope_code) for s in scopes] == [("national", "")]

    def test_the_grant_is_audited(self, user):
        """National scope is visibility over the whole registry — not silent."""
        user.groups.add(Group.objects.get(name="dpo"))
        assert AuditEvent.objects.filter(
            entity_type="operator_scope", entity_id=f"{user.pk}:national",
        ).exists()

    def test_idempotent_across_several_national_roles(self, user):
        user.groups.add(Group.objects.get(name="nsr_unit_coordinator"))
        user.groups.add(Group.objects.get(name="auditor"))
        assert OperatorScope.objects.filter(
            user=user, scope_level="national").count() == 1

    def test_reverse_side_assignment_also_provisions(self, user):
        """group.user_set.add(user) must behave like user.groups.add(group)."""
        Group.objects.get(name="auditor").user_set.add(user)
        assert OperatorScope.objects.filter(
            user=user, scope_level="national", active=True).exists()

    def test_an_existing_inactive_scope_is_not_reactivated(self, user):
        OperatorScope.objects.create(
            user=user, scope_level="national", scope_code="", active=False,
            granted_by="someone", note="revoked deliberately",
        )
        user.groups.add(Group.objects.get(name="auditor"))
        # Re-activating a deliberately revoked scope would undo a decision.
        assert not OperatorScope.objects.filter(
            user=user, scope_level="national", active=True).exists()


@pytest.mark.django_db
class TestScopedRolesAreNeverInvented:

    @pytest.mark.parametrize("code,level", [
        ("cdo", "district"),
        ("parish_chief", "parish"),
        ("supervisor", "sub_county"),
        ("programme_manager", "partner"),
    ])
    def test_no_scope_is_created(self, user, code, level):
        """An empty scope_code at a non-national level matches nothing, so
        inventing one swaps a visible 'no scope' for an invisible 'scope that
        matches nothing' — strictly worse."""
        user.groups.add(Group.objects.get(name=code))
        assert not OperatorScope.objects.filter(user=user).exists()

    def test_it_is_reported_as_needing_a_human(self, user):
        user.groups.add(Group.objects.get(name="cdo"))
        result = ensure_default_scopes(user)
        assert ("cdo", "district") in result.needs_manual_scope
        assert result.blind is True


@pytest.mark.django_db
class TestRemovalIsNotHandled:

    def test_dropping_a_role_leaves_the_scope_alone(self, user):
        """ADR-0006 leaves revocation to a DPO sweep; a group edit must not
        pre-empt that decision."""
        g = Group.objects.get(name="auditor")
        user.groups.add(g)
        assert OperatorScope.objects.filter(
            user=user, scope_level="national", active=True).exists()
        user.groups.remove(g)
        assert OperatorScope.objects.filter(
            user=user, scope_level="national", active=True).exists()


@pytest.mark.django_db
class TestNonCatalogueGroups:

    def test_a_group_outside_the_catalogue_carries_no_scope_contract(self, user):
        g = Group.objects.create(name="some-operational-group")
        user.groups.add(g)
        assert not OperatorScope.objects.filter(user=user).exists()
