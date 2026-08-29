"""Role catalogue — US-063 / ADR-0028.

The point of the catalogue is that three lists (the TOR's roles, ADR-0006's
realm roles, and the Django Groups) stop being maintained by hand. These tests
assert that property, not just that the data loads.
"""

import json

import pytest
from django.contrib.auth.models import Group, Permission

from apps.security import roles

# Groups that predate the catalogue and are compared by exact name in live
# authorisation checks. Renaming any of them silently disables that check.
LOAD_BEARING = {
    "nsr_admin": "apps/security/impersonation.py + OperatorScope admin",
    "GRM Officer": "apps/grievance/api.py",
    "EXPLORER": "data explorer surface",
    "nsr_dba": "apps/admin_console/refdata_api.py",
}


class TestCatalogueIntegrity:

    def test_every_role_grants_at_least_view(self):
        for role in roles.ROLES:
            assert roles.DATA_VIEW in role.permissions, (
                f"{role.code} grants no Data View — a role that cannot read "
                "anything is almost certainly a mistake"
            )

    def test_permissions_are_all_declared(self):
        for role in roles.ROLES:
            unknown = role.permissions - set(roles.PERMISSIONS)
            assert not unknown, f"{role.code} references unknown permissions {unknown}"

    def test_codes_are_unique(self):
        codes = [r.code for r in roles.ROLES]
        assert len(codes) == len(set(codes))

    def test_scope_levels_are_real(self):
        from apps.security.models import ScopeLevel
        valid = {c for c, _ in ScopeLevel.choices}
        for role in roles.ROLES:
            assert role.default_scope in valid, (
                f"{role.code} has scope {role.default_scope!r}, not a ScopeLevel"
            )

    def test_external_roles_are_partner_scoped(self):
        for role in roles.ROLES:
            if role.external:
                assert role.default_scope == roles.PARTNER

    def test_tor_role_count(self):
        """US-063's acceptance criteria name 18 roles."""
        assert sum(1 for r in roles.ROLES if r.in_tor) == 18

    def test_the_eight_tor_permissions(self):
        assert len(roles.PERMISSIONS) == 8

    def test_read_only_roles_cannot_write(self):
        """Roles documented as read-only must not carry write permissions."""
        writes = {roles.DATA_ENTRY, roles.DATA_MODIFY, roles.DATA_DELETE, roles.DATA_UPLOAD}
        for code in ("dpo", "auditor", "application_developer", "systems_architect",
                     "partner_dpo", "programme_caseworker"):
            got = roles.BY_CODE[code].permissions & writes
            assert not got, f"{code} is read-only by design but has {got}"


class TestAdr0006Crosswalk:

    def test_every_adr0006_role_maps(self):
        expected = {
            "NSR_UNIT_COORDINATOR", "DPO", "SA", "CDO", "PARISH_CHIEF",
            "FIELD_ENUMERATOR", "DISTRICT_M_AND_E", "PARTNER_ANALYST",
            "PARTNER_DPO",
        }
        assert set(roles.ADR0006_TO_CODE) == expected

    def test_crosswalk_targets_exist(self):
        for adr_name, code in roles.ADR0006_TO_CODE.items():
            assert code in roles.BY_CODE, f"{adr_name} maps to unknown role {code}"


@pytest.mark.django_db
class TestGroupSync:

    def test_migration_created_every_group(self):
        existing = set(Group.objects.values_list("name", flat=True))
        assert roles.ROLE_CODES <= existing

    def test_load_bearing_group_names_survive(self):
        for name, why in LOAD_BEARING.items():
            assert Group.objects.filter(name=name).exists(), (
                f"{name!r} is compared by exact name in {why}; renaming it "
                "silently disables that check"
            )

    def test_permissions_attached(self):
        g = Group.objects.get(name="nsr_admin")
        assert g.permissions.count() == 8
        g = Group.objects.get(name="enumerator")
        assert {p.codename for p in g.permissions.all()} == {"data_view", "data_entry"}

    def test_sync_is_idempotent(self):
        before = (Group.objects.count(), Permission.objects.count())
        roles.sync_groups()
        roles.sync_groups()
        assert (Group.objects.count(), Permission.objects.count()) == before

    def test_sync_leaves_foreign_groups_alone(self):
        Group.objects.create(name="some-operational-group")
        roles.sync_groups()
        assert Group.objects.filter(name="some-operational-group").exists()

    def test_has_perm_works_for_a_member(self, django_user_model):
        u = django_user_model.objects.create_user(username="cdo-1", password="pw")
        u.groups.add(Group.objects.get(name="cdo"))
        u = django_user_model.objects.get(pk=u.pk)  # clear the perm cache
        assert u.has_perm("security.data_approve")
        assert not u.has_perm("security.data_delete")


class TestRealmParityCheck:

    def test_realm_declares_exactly_the_catalogue(self):
        from django.conf import settings

        from apps.security.checks import (
            KEYCLOAK_BUILTIN_PREFIXES,
            REALM_ONLY_ROLES,
        )

        path = (settings.BASE_DIR / "infrastructure" / "keycloak"
                / "realm-nsr-mis.json")
        realm = json.loads(path.read_text())
        declared = {
            r["name"] for r in realm["roles"]["realm"]
            if r["name"] not in REALM_ONLY_ROLES
            and not r["name"].startswith(KEYCLOAK_BUILTIN_PREFIXES)
        }
        assert declared == set(roles.ROLE_CODES)

    def test_check_passes_as_shipped(self):
        from apps.security.checks import check_role_catalogue_matches_realm
        assert check_role_catalogue_matches_realm(None) == []

    def test_check_fires_when_they_diverge(self, monkeypatch):
        """A check that cannot fail is not a check."""
        from apps.security import checks

        monkeypatch.setattr(
            "apps.security.roles.ROLE_CODES",
            frozenset(roles.ROLE_CODES | {"invented_role"}),
        )
        errors = checks.check_role_catalogue_matches_realm(None)
        assert [e.id for e in errors] == ["security.E005"]
        assert "invented_role" in errors[0].msg

    def test_realm_descriptions_fit_keycloaks_column(self):
        """Keycloak's DESCRIPTION is varchar(255); a longer value fails the
        import and the container exits 1 rather than starting degraded."""
        from django.conf import settings

        path = (settings.BASE_DIR / "infrastructure" / "keycloak"
                / "realm-nsr-mis.json")
        realm = json.loads(path.read_text())
        for section in ("roles", "clients"):
            blob = realm.get(section)
            items = blob["realm"] if section == "roles" else blob
            for item in items:
                desc = item.get("description", "")
                assert len(desc) <= 255, f"{item.get('name') or item.get('clientId')}: {len(desc)}"
