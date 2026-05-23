"""Admin Console — ChoiceList endpoints + lifecycle invariants."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.reference_data import lifecycle
from apps.reference_data.models import (
    ChoiceList,
    ChoiceListStatus,
    ChoiceOption,
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


@pytest.fixture
def active_list(db):
    """Active list with two options. version=900 to avoid colliding
    with seed migrations (see feedback_test_pmt_version_900_pattern)."""
    cl = ChoiceList.objects.create(
        list_name="test_color",
        version=900,
        status=ChoiceListStatus.ACTIVE,
        author="seed-author",
        approved_by="seed-approver",
    )
    ChoiceOption.objects.create(
        choice_list=cl, code="01", label="Red", sort_order=1,
    )
    ChoiceOption.objects.create(
        choice_list=cl, code="02", label="Blue", sort_order=2,
    )
    return cl


# ───────────────────────────────────────────────────────────────
# Permission gate
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRefdataGate:
    def test_listing_403_for_operator(self, operator_client):
        r = operator_client.get("/api/v1/admin/refdata/choice-lists/")
        assert r.status_code == 403

    def test_listing_200_for_admin(self, admin_client):
        r = admin_client.get("/api/v1/admin/refdata/choice-lists/")
        assert r.status_code == 200


# ───────────────────────────────────────────────────────────────
# Listing + versions + options
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestListing:
    def test_collapses_versions_into_one_row(self, admin_client, active_list):
        r = admin_client.get("/api/v1/admin/refdata/choice-lists/")
        assert r.status_code == 200
        rows = {row["list_name"]: row for row in r.data["results"]}
        assert "test_color" in rows
        row = rows["test_color"]
        assert row["active_version"] == 900
        assert row["draft_version"] is None
        assert row["options_count"] == 2

    def test_versions_endpoint_lists_all(self, admin_client, active_list):
        # Add a draft clone alongside the active row.
        lifecycle.clone_to_draft(active_list, author="cloner")
        r = admin_client.get("/api/v1/admin/refdata/choice-lists/test_color/versions/")
        assert r.status_code == 200
        versions = [v["version"] for v in r.data["versions"]]
        assert 900 in versions
        assert 901 in versions

    def test_options_endpoint_returns_options(self, admin_client, active_list):
        r = admin_client.get(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/900/options/"
        )
        assert r.status_code == 200
        codes = [o["code"] for o in r.data["options"]]
        assert "01" in codes
        assert "02" in codes


# ───────────────────────────────────────────────────────────────
# Edits restricted to DRAFT only
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDraftOnlyEdits:
    def test_active_options_cannot_be_added_to(self, admin_client, active_list):
        r = admin_client.post(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/900/options/",
            {"code": "03", "label": "Green"},
            format="json",
        )
        assert r.status_code == 409

    def test_active_options_cannot_be_patched(self, admin_client, active_list):
        r = admin_client.patch(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/900/options/01/",
            {"label": "Crimson"},
            format="json",
        )
        assert r.status_code == 409

    def test_draft_options_can_be_added(self, admin_client, active_list):
        admin_client.post("/api/v1/admin/refdata/choice-lists/test_color/clone/")
        r = admin_client.post(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/901/options/",
            {"code": "03", "label": "Green", "sort_order": 3},
            format="json",
        )
        assert r.status_code == 201

    def test_draft_options_can_be_patched(self, admin_client, active_list):
        admin_client.post("/api/v1/admin/refdata/choice-lists/test_color/clone/")
        r = admin_client.patch(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/901/options/01/",
            {"label": "Crimson"},
            format="json",
        )
        assert r.status_code == 200


# ───────────────────────────────────────────────────────────────
# Deletion forbidden — soft-deprecate instead
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestNoDelete:
    def test_delete_returns_405(self, admin_client, active_list):
        r = admin_client.delete(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/900/options/01/"
        )
        assert r.status_code == 405

    def test_deprecate_via_patch_works(self, admin_client, active_list):
        admin_client.post("/api/v1/admin/refdata/choice-lists/test_color/clone/")
        r = admin_client.patch(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/901/options/01/",
            {"status": "deprecated"},
            format="json",
        )
        assert r.status_code == 200
        # Confirm the option survived as deprecated, not deleted.
        opt = ChoiceOption.objects.get(
            choice_list__list_name="test_color",
            choice_list__version=901,
            code="01",
        )
        assert opt.status == "deprecated"


# ───────────────────────────────────────────────────────────────
# Approval workflow — AC-CHOICELIST-NO-SELF-APPROVE
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestApprovalWorkflow:
    def test_author_cannot_approve_own_list(self, admin_client, active_list):
        # Clone → submit → try to sign as the same author.
        admin_client.post("/api/v1/admin/refdata/choice-lists/test_color/clone/")
        # The clone's author == admin-test (the calling user).
        admin_client.post(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/901/submit/"
        )
        r = admin_client.post(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/901/sign/",
            {"approver": "admin-test", "note": "lgtm"},
            format="json",
        )
        assert r.status_code == 409
        assert "cannot approve" in r.data["detail"].lower()

    def test_atomic_retire_of_prior_active(self, admin_client, active_list):
        admin_client.post("/api/v1/admin/refdata/choice-lists/test_color/clone/")
        admin_client.post(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/901/submit/"
        )
        # A different approver signs.
        r = admin_client.post(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/901/sign/",
            {"approver": "approver-distinct", "note": "approved"},
            format="json",
        )
        assert r.status_code == 200
        assert r.data["status"] == "active"

        prior = ChoiceList.objects.get(list_name="test_color", version=900)
        assert prior.status == ChoiceListStatus.RETIRED
        # And the new row is active.
        new = ChoiceList.objects.get(list_name="test_color", version=901)
        assert new.status == ChoiceListStatus.ACTIVE

    def test_rejection_routes_back_to_draft(self, admin_client, active_list):
        admin_client.post("/api/v1/admin/refdata/choice-lists/test_color/clone/")
        admin_client.post(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/901/submit/"
        )
        r = admin_client.post(
            "/api/v1/admin/refdata/choice-lists/test_color/versions/901/reject/",
            {"approver": "approver-distinct", "reason": "Validation regression on opt 03."},
            format="json",
        )
        assert r.status_code == 200
        assert r.data["status"] == "draft"


# ───────────────────────────────────────────────────────────────
# Deprecated codes remain readable from historical data
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestHistoricalReadability:
    def test_deprecated_option_still_in_db(self, active_list):
        opt = active_list.options.first()
        lifecycle.deprecate_option(opt, actor="tester")
        # Refresh from DB and confirm it's a soft-delete.
        opt.refresh_from_db()
        assert opt.status == "deprecated"
        assert ChoiceOption.objects.filter(pk=opt.pk).exists()


# ───────────────────────────────────────────────────────────────
# Service-layer guards (covers cases the API may not reach)
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestServiceLayer:
    def test_submit_only_from_draft(self):
        cl = ChoiceList.objects.create(
            list_name="x", version=900, status=ChoiceListStatus.ACTIVE,
            author="a",
        )
        with pytest.raises(lifecycle.ChoiceListApprovalError):
            lifecycle.submit_for_approval(cl)

    def test_sign_requires_note(self):
        cl = ChoiceList.objects.create(
            list_name="x", version=900,
            status=ChoiceListStatus.PENDING_APPROVAL,
            author="a",
        )
        with pytest.raises(lifecycle.ChoiceListApprovalError):
            lifecycle.sign(cl, approver="b", note="")

    def test_clone_carries_pii_flag(self):
        cl = ChoiceList.objects.create(
            list_name="pii_list", version=900,
            status=ChoiceListStatus.ACTIVE,
            author="a", is_pii_classified=True,
        )
        draft = lifecycle.clone_to_draft(cl, author="cloner")
        assert draft.is_pii_classified is True
