"""Admin Console API tests — dashboard + configuration endpoints."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.pmt.models import (
    PMTCoverageSnapshot,
    PMTModelVersion,
    PMTRecomputeJobRun,
)


@pytest.fixture
def admin_user(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_user(username="admin-test", password="p")
    grp, _ = Group.objects.get_or_create(name="nsr_admin")
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
def operator_client(operator_user):
    c = APIClient()
    c.force_authenticate(user=operator_user)
    return c


# ───────────────────────────────────────────────────────────────
# Permission gate
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAdminApiGate:

    def test_dashboard_403_for_operator(self, operator_client):
        r = operator_client.get("/api/v1/admin/pmt/dashboard/")
        assert r.status_code == 403

    def test_dashboard_200_for_admin(self, admin_client):
        r = admin_client.get("/api/v1/admin/pmt/dashboard/")
        assert r.status_code == 200

    @pytest.mark.parametrize("path", [
        "/api/v1/admin/pmt/dashboard/",
        "/api/v1/admin/pmt/versions/",
        "/api/v1/admin/pmt/transforms/",
        "/api/v1/admin/pmt/events/",
    ])
    def test_admin_routes_gated(self, operator_client, path):
        assert operator_client.get(path).status_code == 403


# ───────────────────────────────────────────────────────────────
# Dashboard payload shape
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDashboardPayload:

    def test_dashboard_returns_active_model(self, admin_client):
        # The seed migration v1 is ACTIVE. Confirm it surfaces.
        r = admin_client.get("/api/v1/admin/pmt/dashboard/")
        assert r.status_code == 200
        active = r.data.get("active") or {}
        assert active.get("status") == "active"
        assert active.get("version") == 1
        assert active.get("variables_count") == 25

    def test_dashboard_assembles_all_sections(self, admin_client):
        r = admin_client.get("/api/v1/admin/pmt/dashboard/")
        for key in (
            "active", "bands", "coverage", "variables_top",
            "geo", "drift", "triggers", "job", "recent_events",
        ):
            assert key in r.data, f"dashboard payload missing key {key!r}"


# ───────────────────────────────────────────────────────────────
# Recompute-now action
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRecomputeRunNow:

    def test_writes_a_job_run_row(self, admin_client):
        before = PMTRecomputeJobRun.objects.count()
        r = admin_client.post("/api/v1/admin/pmt/recompute/run-now/")
        assert r.status_code == 202
        assert PMTRecomputeJobRun.objects.count() == before + 1

    def test_recompute_writes_coverage_snapshot(self, admin_client):
        admin_client.post("/api/v1/admin/pmt/recompute/run-now/")
        assert PMTCoverageSnapshot.objects.exists()


# ───────────────────────────────────────────────────────────────
# Configuration: versions list + clone + edit-active-refusal
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestVersionsEndpoint:

    def test_list_returns_seeded_v1(self, admin_client):
        r = admin_client.get("/api/v1/admin/pmt/versions/")
        assert r.status_code == 200
        versions = [row["version"] for row in r.data["results"]]
        assert 1 in versions

    def test_retrieve_returns_signoffs_array(self, admin_client):
        v1 = PMTModelVersion.objects.get(version=1)
        r = admin_client.get(f"/api/v1/admin/pmt/versions/{v1.id}/")
        assert r.status_code == 200
        assert r.data["version"] == 1
        # signoffs may be empty at this point — just need the key
        assert "signoffs" in r.data
        assert "variables" in r.data

    def test_patch_active_refuses_with_409(self, admin_client):
        v1 = PMTModelVersion.objects.get(version=1)
        r = admin_client.patch(
            f"/api/v1/admin/pmt/versions/{v1.id}/",
            {"description": "tampered"},
            format="json",
        )
        assert r.status_code == 409
        assert "clone" in r.data["detail"].lower()

    def test_clone_creates_a_draft_with_same_variables(self, admin_client):
        v1 = PMTModelVersion.objects.get(version=1)
        existing_max = (
            PMTModelVersion.objects.order_by("-version").first().version
        )
        r = admin_client.post(f"/api/v1/admin/pmt/versions/{v1.id}/clone/")
        assert r.status_code == 201
        assert r.data["status"] == "draft"
        # Clone bumps to max+1 — the seed migration leaves a placeholder
        # v22001 around, so the new number isn't simply 2.
        assert r.data["version"] == existing_max + 1
        # Variables copied through.
        assert len(r.data["variables"]) == len(v1.variables)


# ───────────────────────────────────────────────────────────────
# Sign-off via API
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSignoffViaApi:

    def test_submit_and_sign_round_trip(self, admin_client):
        # Use the seeded v1's clone for a clean sign-off cycle.
        v1 = PMTModelVersion.objects.get(version=1)
        r = admin_client.post(f"/api/v1/admin/pmt/versions/{v1.id}/clone/")
        clone_id = r.data["id"]
        # Set author explicitly so we can sign as someone else.
        admin_client.patch(
            f"/api/v1/admin/pmt/versions/{clone_id}/",
            {"description": "test"}, format="json",
        )
        # Submit
        r = admin_client.post(
            f"/api/v1/admin/pmt/versions/{clone_id}/submit/",
            {
                "author_email": "analyst@nsr.go.ug",
                "mglsd_steward_email": "steward@mglsd.go.ug",
                "ubos_dg_email": "dg@ubos.go.ug",
            },
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["status"] == "pending_approval"
        # Sign step 2
        r = admin_client.post(
            f"/api/v1/admin/pmt/versions/{clone_id}/sign/2/",
            {"actor_email": "steward@mglsd.go.ug", "note": "approved"},
            format="json",
        )
        assert r.status_code == 200, r.data
        # Sign step 3 → activates
        r = admin_client.post(
            f"/api/v1/admin/pmt/versions/{clone_id}/sign/3/",
            {"actor_email": "dg@ubos.go.ug", "note": "approved"},
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["status"] == "active"

    def test_reject_endpoint(self, admin_client):
        v1 = PMTModelVersion.objects.get(version=1)
        r = admin_client.post(f"/api/v1/admin/pmt/versions/{v1.id}/clone/")
        clone_id = r.data["id"]
        admin_client.patch(
            f"/api/v1/admin/pmt/versions/{clone_id}/",
            {"description": "test"}, format="json",
        )
        admin_client.post(
            f"/api/v1/admin/pmt/versions/{clone_id}/submit/",
            {
                "author_email": "analyst@nsr.go.ug",
                "mglsd_steward_email": "steward@mglsd.go.ug",
                "ubos_dg_email": "dg@ubos.go.ug",
            },
            format="json",
        )
        r = admin_client.post(
            f"/api/v1/admin/pmt/versions/{clone_id}/reject/2/",
            {
                "actor_email": "steward@mglsd.go.ug",
                "reason": "Validation regression on the held-out sample.",
            },
            format="json",
        )
        assert r.status_code == 200
        # Rejection is terminal — version stays on record but is no
        # longer eligible for resubmission. Author must clone fresh.
        assert r.data["status"] == "rejected"

    def test_rejected_versions_hidden_from_default_list(self, admin_client):
        v1 = PMTModelVersion.objects.get(version=1)
        clone = admin_client.post(f"/api/v1/admin/pmt/versions/{v1.id}/clone/")
        clone_id = clone.data["id"]
        admin_client.post(
            f"/api/v1/admin/pmt/versions/{clone_id}/submit/",
            {
                "author_email": "analyst@nsr.go.ug",
                "mglsd_steward_email": "steward@mglsd.go.ug",
                "ubos_dg_email": "dg@ubos.go.ug",
            }, format="json",
        )
        admin_client.post(
            f"/api/v1/admin/pmt/versions/{clone_id}/reject/2/",
            {
                "actor_email": "steward@mglsd.go.ug",
                "reason": "Validation regression on the held-out sample.",
            }, format="json",
        )
        # Default list — rejected version is hidden.
        r = admin_client.get("/api/v1/admin/pmt/versions/")
        ids = {row["id"] for row in r.data["results"]}
        assert clone_id not in ids
        # Opt-in surfaces it (for audit / forensics screens).
        r = admin_client.get(
            "/api/v1/admin/pmt/versions/?include_rejected=1",
        )
        ids = {row["id"] for row in r.data["results"]}
        assert clone_id in ids


# ───────────────────────────────────────────────────────────────
# Score simulator (no PMTResult write)
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSimulator:

    def test_returns_score_and_top_contributions(self, admin_client):
        v1 = PMTModelVersion.objects.get(version=1)
        from apps.pmt.models import PMTResult
        before = PMTResult.objects.count()
        r = admin_client.post(
            f"/api/v1/admin/pmt/versions/{v1.id}/simulate/",
            {"features": {"member_count": 5, "head_member": {"sex": "2"}}},
            format="json",
        )
        assert r.status_code == 200
        assert "score" in r.data
        assert "contributing_variables" in r.data
        assert len(r.data["contributing_variables"]) <= 5
        # No PMTResult row written.
        assert PMTResult.objects.count() == before


# ───────────────────────────────────────────────────────────────
# Transforms endpoint
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTransformsEndpoint:

    def test_lists_dsl_types(self, admin_client):
        r = admin_client.get("/api/v1/admin/pmt/transforms/")
        assert r.status_code == 200
        assert "direct" in r.data["dsl_types"]
        assert "registered_function" in r.data["dsl_types"]
        # Registered features include the seeded FCS / FIES readers.
        assert "food_consumption_score_v1" in r.data["registered_functions"]
