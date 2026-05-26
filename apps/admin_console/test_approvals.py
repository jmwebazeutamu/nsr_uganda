"""Admin Console — unified Approvals queue."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

from apps.dqa.models import DqaRule, RuleStatus, Severity
from apps.pmt.models import ModelStatus, PMTModelVersion
from apps.reference_data.models import ChoiceList, ChoiceListStatus


@pytest.fixture
def admin_user(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_user(username="approvals-test", password="p")
    grp, _ = Group.objects.get_or_create(name="nsr_admin")
    u.groups.add(grp)
    return u


@pytest.fixture
def operator_user(db):
    user_cls = get_user_model()
    return user_cls.objects.create_user(username="operator-x", password="p")


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
def pending_choice_list(db):
    # version=900 dodges seeded production rows per
    # feedback_test_pmt_version_900_pattern.
    return ChoiceList.objects.create(
        list_name="approvals_test_color",
        version=900,
        status=ChoiceListStatus.PENDING_APPROVAL,
        author="approvals-author",
        submitted_at=timezone.now(),
    )


@pytest.fixture
def pending_dqa_rule(db):
    return DqaRule.objects.create(
        rule_id="AC-APPROVALS-TEST",
        version=900,
        description="Pending rule used in approvals queue test.",
        severity=Severity.WARNING,
        expression={"op": "always_pass"},
        error_message_template="-",
        status=RuleStatus.PENDING_APPROVAL,
        author="approvals-rule-author",
        submitted_at=timezone.now(),
    )


@pytest.fixture
def pending_pmt_version(db):
    return PMTModelVersion.objects.create(
        version=900,
        status=ModelStatus.PENDING_APPROVAL,
        description="Pending PMT model for approvals queue test.",
        author="approvals-pmt-author",
        variables=[],
        intercept=0,
    )


@pytest.mark.django_db
class TestApprovalsGate:
    def test_403_for_operator(self, operator_client):
        r = operator_client.get("/api/v1/admin/approvals/")
        assert r.status_code == 403

    def test_200_for_admin(self, admin_client):
        r = admin_client.get("/api/v1/admin/approvals/")
        assert r.status_code == 200
        assert "results" in r.data
        assert "count" in r.data
        assert "by_kind" in r.data


@pytest.mark.django_db
class TestApprovalsQueue:
    def test_lists_pending_choice_list(self, admin_client, pending_choice_list):
        r = admin_client.get("/api/v1/admin/approvals/")
        assert r.status_code == 200
        names = [row["name"] for row in r.data["results"] if row["kind"] == "choice_list"]
        assert "approvals_test_color" in names
        row = next(x for x in r.data["results"] if x["name"] == "approvals_test_color")
        assert row["version"] == 900
        assert row["author"] == "approvals-author"
        assert row["submitted_at"] is not None
        assert row["links"]["sign"].endswith("/sign/")
        assert row["links"]["reject"].endswith("/reject/")

    def test_lists_pending_dqa_rule(self, admin_client, pending_dqa_rule):
        r = admin_client.get("/api/v1/admin/approvals/")
        names = [row["name"] for row in r.data["results"] if row["kind"] == "dqa_rule"]
        assert "AC-APPROVALS-TEST" in names

    def test_lists_pending_pmt_version(self, admin_client, pending_pmt_version):
        r = admin_client.get("/api/v1/admin/approvals/")
        kinds = [row["kind"] for row in r.data["results"]]
        assert "pmt_model" in kinds
        row = next(x for x in r.data["results"] if x["kind"] == "pmt_model" and x["version"] == 900)
        # PMT items deep-link into the configuration screen rather than
        # exposing inline sign/reject (three-step sign-off).
        assert row["detail_screen"] == "admin-pmt-configuration"
        assert "configure" in row["links"]

    def test_by_kind_counts(
        self, admin_client,
        pending_choice_list, pending_dqa_rule, pending_pmt_version,
    ):
        r = admin_client.get("/api/v1/admin/approvals/")
        assert r.data["by_kind"].get("choice_list", 0) >= 1
        assert r.data["by_kind"].get("dqa_rule", 0) >= 1
        assert r.data["by_kind"].get("pmt_model", 0) >= 1
        assert r.data["count"] == sum(r.data["by_kind"].values())

    def test_excludes_active_and_draft(self, admin_client):
        # Active and draft choice lists must not show on the queue.
        ChoiceList.objects.create(
            list_name="approvals_active",
            version=900, status=ChoiceListStatus.ACTIVE,
            author="x",
        )
        ChoiceList.objects.create(
            list_name="approvals_draft",
            version=901, status=ChoiceListStatus.DRAFT,
            author="x",
        )
        r = admin_client.get("/api/v1/admin/approvals/")
        names = [row["name"] for row in r.data["results"]]
        assert "approvals_active" not in names
        assert "approvals_draft" not in names

    def test_kind_filter_narrows_results(
        self, admin_client, pending_choice_list, pending_dqa_rule,
    ):
        r = admin_client.get("/api/v1/admin/approvals/?kind=choice_list")
        kinds = {row["kind"] for row in r.data["results"]}
        assert kinds == {"choice_list"}
