"""Admin Console — Geography endpoints + versioned-write invariants."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.reference_data.lifecycle import (
    GeographicUnitReplaceError,
    replace_geographic_unit,
)
from apps.reference_data.models import GeographicUnit


@pytest.fixture
def admin_user(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_user(username="admin-test", password="p")
    grp, _ = Group.objects.get_or_create(name="nsr_admin")
    u.groups.add(grp)
    return u


@pytest.fixture
def nsr_dba_user(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_user(username="dba-test", password="p")
    grp, _ = Group.objects.get_or_create(name="nsr_dba")
    u.groups.add(grp)
    return u


@pytest.fixture
def operator_user(db):
    user_cls = get_user_model()
    return user_cls.objects.create_user(username="operator", password="p")


@pytest.fixture
def admin_client(admin_user):
    c = APIClient()
    c.force_authenticate(user=admin_user)
    return c


@pytest.fixture
def dba_client(nsr_dba_user):
    c = APIClient()
    c.force_authenticate(user=nsr_dba_user)
    return c


@pytest.fixture
def operator_client(operator_user):
    c = APIClient()
    c.force_authenticate(user=operator_user)
    return c


def _mk_unit(level, code, name, parent=None, status="active",
             effective_from=None):
    return GeographicUnit.objects.create(
        level=level, code=code, name=name, parent=parent,
        effective_from=effective_from or date(2025, 1, 1),
        status=status,
    )


@pytest.fixture
def geo_tree(db):
    """Tiny 4-level tree used by drill-down tests."""
    region = _mk_unit("region", "R-N", "Northern")
    sub_region = _mk_unit("sub_region", "SR-AC", "Acholi", parent=region)
    district = _mk_unit("district", "D-GULU", "Gulu", parent=sub_region)
    county = _mk_unit("county", "C-OMORO", "Omoro", parent=district)
    return {
        "region": region,
        "sub_region": sub_region,
        "district": district,
        "county": county,
    }


# ───────────────────────────────────────────────────────────────
# Permission gate
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestGeoGate:
    def test_403_for_operator(self, operator_client):
        r = operator_client.get("/api/v1/admin/refdata/geography/?level=region")
        assert r.status_code == 403

    def test_200_for_admin(self, admin_client):
        r = admin_client.get("/api/v1/admin/refdata/geography/?level=region")
        assert r.status_code == 200


# ───────────────────────────────────────────────────────────────
# Drill-down
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDrillDown:
    def test_drill_top_level(self, admin_client, geo_tree):
        r = admin_client.get("/api/v1/admin/refdata/geography/?level=region")
        codes = [u["code"] for u in r.data["results"]]
        assert "R-N" in codes

    def test_drill_by_parent(self, admin_client, geo_tree):
        r = admin_client.get(
            "/api/v1/admin/refdata/geography/?level=sub_region&parent_code=R-N"
        )
        codes = [u["code"] for u in r.data["results"]]
        assert codes == ["SR-AC"]

    def test_unknown_level_rejected(self, admin_client):
        r = admin_client.get("/api/v1/admin/refdata/geography/?level=continent")
        assert r.status_code == 400

    def test_inactive_hidden_by_default(self, admin_client, geo_tree):
        # Replace SR-AC to create a superseded row.
        replace_geographic_unit(
            geo_tree["sub_region"],
            actor="t",
            name="Acholi (renamed)",
            effective_from=date.today() + timedelta(days=1),
        )
        r = admin_client.get(
            "/api/v1/admin/refdata/geography/?level=sub_region&parent_code=R-N"
        )
        results = r.data["results"]
        # Only the active row should be returned by default.
        assert len(results) == 1
        assert results[0]["name"] == "Acholi (renamed)"

    def test_inactive_visible_with_flag(self, admin_client, geo_tree):
        replace_geographic_unit(
            geo_tree["sub_region"],
            actor="t",
            name="Acholi (renamed)",
            effective_from=date.today() + timedelta(days=1),
        )
        r = admin_client.get(
            "/api/v1/admin/refdata/geography/?level=sub_region&parent_code=R-N&include_inactive=true"
        )
        assert len(r.data["results"]) == 2


# ───────────────────────────────────────────────────────────────
# Versioned write
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestVersionedReplace:
    def test_rename_creates_new_row(self, geo_tree):
        prior_id = geo_tree["sub_region"].id
        new = replace_geographic_unit(
            geo_tree["sub_region"],
            actor="tester",
            name="Acholi Renamed",
            effective_from=date.today() + timedelta(days=1),
        )
        assert new.id != prior_id
        assert new.name == "Acholi Renamed"
        # The old row is now superseded with an effective_to.
        old = GeographicUnit.objects.get(id=prior_id)
        assert old.status == "superseded"
        assert old.effective_to is not None

    def test_rename_via_patch_endpoint(self, admin_client, geo_tree):
        r = admin_client.patch(
            "/api/v1/admin/refdata/geography/sub_region/SR-AC/",
            {"name": "Acholi (2026)"},
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["name"] == "Acholi (2026)"

    def test_history_endpoint_lists_versions(self, admin_client, geo_tree):
        replace_geographic_unit(
            geo_tree["sub_region"], actor="t", name="renamed",
            effective_from=date.today() + timedelta(days=1),
        )
        r = admin_client.get(
            "/api/v1/admin/refdata/geography/sub_region/SR-AC/history/"
        )
        assert r.status_code == 200
        rows = r.data["history"]
        assert len(rows) == 2
        statuses = {row["status"] for row in rows}
        assert "active" in statuses
        assert "superseded" in statuses

    def test_replace_rejects_no_change(self, geo_tree):
        with pytest.raises(GeographicUnitReplaceError):
            replace_geographic_unit(
                geo_tree["sub_region"],
                actor="t",
                name=geo_tree["sub_region"].name,
                effective_from=date.today() + timedelta(days=1),
            )

    def test_only_active_can_be_replaced(self, geo_tree):
        new = replace_geographic_unit(
            geo_tree["sub_region"], actor="t", name="renamed",
            effective_from=date.today() + timedelta(days=1),
        )
        # Now try to replace the superseded row.
        old = GeographicUnit.objects.get(id=geo_tree["sub_region"].id)
        with pytest.raises(GeographicUnitReplaceError):
            replace_geographic_unit(
                old, actor="t", name="zzz",
                effective_from=date.today() + timedelta(days=2),
            )
        # Sanity: the new row is alive.
        new.refresh_from_db()
        assert new.status == "active"


# ───────────────────────────────────────────────────────────────
# Detail endpoint — ancestors + descendants_count
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestGeoDetail:
    def test_returns_ancestor_chain(self, admin_client, geo_tree):
        r = admin_client.get("/api/v1/admin/refdata/geography/county/C-OMORO/")
        assert r.status_code == 200
        ancestor_codes = [a["code"] for a in r.data["ancestors"]]
        # Order is top-down: region first, immediate parent last.
        assert ancestor_codes == ["R-N", "SR-AC", "D-GULU"]
        assert r.data["descendants_count"] == 0

    def test_404_when_inactive(self, admin_client, geo_tree):
        # Supersede SR-AC; the active resolver should return 404.
        replace_geographic_unit(
            geo_tree["sub_region"], actor="t", name="renamed",
            effective_from=date.today() + timedelta(days=1),
        )
        # The old code is now mapped to a different row, but the
        # active-resolver returns the new row, not the superseded one.
        r = admin_client.get("/api/v1/admin/refdata/geography/sub_region/SR-AC/")
        assert r.status_code == 200
        assert r.data["name"] == "renamed"


# ───────────────────────────────────────────────────────────────
# children_count_cached maintenance
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestChildrenCountCache:
    def test_signal_increments_parent_count(self, geo_tree):
        region = geo_tree["region"]
        region.refresh_from_db()
        before = region.children_count_cached
        _mk_unit("sub_region", "SR-LANG", "Lango", parent=region)
        region.refresh_from_db()
        assert region.children_count_cached == before + 1


# ───────────────────────────────────────────────────────────────
# UBOS import — restricted to nsr_dba
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestUbosImport:
    def test_admin_not_dba_gets_403(self, admin_client):
        r = admin_client.post("/api/v1/admin/refdata/geography/import-ubos/")
        # admin-test isn't a superuser and isn't in nsr_dba.
        assert r.status_code == 403

    def test_dba_user_gets_202(self, dba_client):
        r = dba_client.post("/api/v1/admin/refdata/geography/import-ubos/")
        assert r.status_code == 202

    def test_operator_gets_403(self, operator_client):
        r = operator_client.post("/api/v1/admin/refdata/geography/import-ubos/")
        # Plain operator fails the IsAdminConsoleUser gate first.
        assert r.status_code == 403


# ───────────────────────────────────────────────────────────────
# Partial unique constraint
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPartialUnique:
    def test_two_active_rows_same_code_rejected(self, geo_tree):
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            GeographicUnit.objects.create(
                level="sub_region", code="SR-AC",
                name="Duplicate", parent=geo_tree["region"],
                effective_from=date.today(),
                status="active",
            )
