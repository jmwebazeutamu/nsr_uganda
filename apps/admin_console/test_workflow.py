"""Admin Console — Workflow API tests (Cat 2: UPD routing + DQA + DDUP)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ddup.models import (
    DdupModelVersion,
    MatchPair,
    MergeAction,
    MergeDecision,
    PairStatus,
)
from apps.ddup.models import (
    ModelStatus as DdupModelStatus,
)
from apps.dqa.models import DqaRule, RuleStatus, Severity
from apps.update_workflow.models import ChangeType, UpdRoutingRule
from apps.update_workflow.services import (
    RoutingReplaceError,
    replace_routing_rule,
)

# ───────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────

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
def routing_rule(db):
    # A migration may seed the (correction, false) row already.
    # get_or_create so the fixture is idempotent.
    rule, _ = UpdRoutingRule.objects.get_or_create(
        change_type=ChangeType.CORRECTION,
        pmt_relevant=False,
        is_active=True,
        defaults={
            "required_role": "parish_coordinator",
            "sla_hours": 72,
        },
    )
    return rule


@pytest.fixture
def dqa_rule(db):
    return DqaRule.objects.create(
        rule_id="AC-TEST-RULE",
        version=900,
        description="A test rule.",
        severity=Severity.WARNING,
        applicability_filter={},
        expression={"check": "always_true"},
        error_message_template="oops",
        status=RuleStatus.ACTIVE,
        author="seed",
        approved_by="another",
    )


@pytest.fixture
def ddup_model(db):
    return DdupModelVersion.objects.create(
        version=900,
        config={"tier3": {"auto_merge_threshold": 0.93}},
        status=DdupModelStatus.ACTIVE,
        author="seed",
    )


# ───────────────────────────────────────────────────────────────
# Permission gate
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestGate:
    @pytest.mark.parametrize("path", [
        "/api/v1/admin/workflow/upd-routing/",
        "/api/v1/admin/workflow/dqa/rules/",
        "/api/v1/admin/workflow/ddup/versions/",
        "/api/v1/admin/workflow/ddup/queue-stats/",
    ])
    def test_workflow_routes_gated(self, operator_client, path):
        assert operator_client.get(path).status_code == 403

    @pytest.mark.parametrize("path", [
        "/api/v1/admin/workflow/upd-routing/",
        "/api/v1/admin/workflow/dqa/rules/",
        "/api/v1/admin/workflow/ddup/versions/",
        "/api/v1/admin/workflow/ddup/queue-stats/",
    ])
    def test_workflow_routes_admin(self, admin_client, path):
        assert admin_client.get(path).status_code == 200


# ───────────────────────────────────────────────────────────────
# UPD routing — versioned-write
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestUpdRoutingVersionedWrite:
    def test_list_returns_active_rules(self, admin_client, routing_rule):
        r = admin_client.get("/api/v1/admin/workflow/upd-routing/")
        assert r.status_code == 200
        ctypes = [row["change_type"] for row in r.data["results"]]
        assert "correction" in ctypes

    def test_patch_creates_new_active_row(self, admin_client, routing_rule):
        r = admin_client.patch(
            "/api/v1/admin/workflow/upd-routing/correction/false/",
            {"required_role": "cdo", "sla_hours": 96, "note": "absorb backlog"},
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["required_role"] == "cdo"
        assert r.data["sla_hours"] == 96
        # Old rule deactivated.
        assert UpdRoutingRule.objects.filter(
            change_type="correction",
            pmt_relevant=False,
            is_active=True,
        ).count() == 1
        # History endpoint sees both rows.
        r = admin_client.get(
            "/api/v1/admin/workflow/upd-routing/history/?change_type=correction&pmt_relevant=false"
        )
        assert len(r.data["results"]) == 2

    def test_patch_noop_rejected(self, routing_rule):
        with pytest.raises(RoutingReplaceError):
            replace_routing_rule(
                change_type="correction",
                pmt_relevant=False,
                required_role=routing_rule.required_role,
                sla_hours=routing_rule.sla_hours,
                note=routing_rule.note,
                actor="t",
            )

    def test_unique_active_constraint(self, routing_rule):
        # Cannot create a parallel active row through the ORM either.
        # SQLite enforces partial uniques as full uniques on older
        # backends, but the IntegrityError shape is the same.
        from django.db import IntegrityError, transaction
        with pytest.raises(IntegrityError), transaction.atomic():
            UpdRoutingRule.objects.create(
                change_type=ChangeType.CORRECTION,
                pmt_relevant=False,
                required_role="dup",
                sla_hours=24,
                is_active=True,
            )

    def test_replace_emits_audit(self, admin_client, routing_rule):
        from apps.security.models import AuditEvent
        before = AuditEvent.objects.filter(action="upd_routing.replaced").count()
        admin_client.patch(
            "/api/v1/admin/workflow/upd-routing/correction/false/",
            {"required_role": "cdo", "sla_hours": 96},
            format="json",
        )
        after = AuditEvent.objects.filter(action="upd_routing.replaced").count()
        assert after == before + 1


# ───────────────────────────────────────────────────────────────
# DQA — preview never persists values + AC-DQA-NO-SELF-APPROVE
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDqaWorkflow:
    def test_list_returns_dqa_rule(self, admin_client, dqa_rule):
        r = admin_client.get("/api/v1/admin/workflow/dqa/rules/")
        assert r.status_code == 200
        ids = [row["rule_id"] for row in r.data["results"]]
        assert "AC-TEST-RULE" in ids

    def test_preview_writes_run_but_no_field_values(self, admin_client, dqa_rule):
        from apps.dqa.models import DqaRulePreviewRun
        before = DqaRulePreviewRun.objects.count()
        r = admin_client.post(
            "/api/v1/admin/workflow/dqa/rules/AC-TEST-RULE/preview/",
            {"sample_size": 50},
            format="json",
        )
        assert r.status_code == 200
        assert DqaRulePreviewRun.objects.count() == before + 1
        run = DqaRulePreviewRun.objects.latest("executed_at")
        # AC: the run row stores counts + a list of failed record IDs,
        # never field values from the sample.
        assert run.sample_size == 50
        # sample_failed_record_ids may be empty in the stub but must
        # remain a list type — verifies the contract.
        assert isinstance(run.sample_failed_record_ids, list)

    def test_clone_creates_new_draft(self, admin_client, dqa_rule):
        r = admin_client.post(
            "/api/v1/admin/workflow/dqa/rules/AC-TEST-RULE/clone/"
        )
        assert r.status_code == 201
        assert r.data["status"] == "draft"
        assert r.data["version"] > dqa_rule.version

    def test_self_approve_blocked(self, admin_client, dqa_rule):
        # Clone, submit, then try to sign as the same author.
        c = admin_client.post(
            "/api/v1/admin/workflow/dqa/rules/AC-TEST-RULE/clone/"
        )
        ver = c.data["version"]
        admin_client.post(
            f"/api/v1/admin/workflow/dqa/rules/AC-TEST-RULE/v{ver}/submit/"
        )
        # The clone's author is the calling user (admin-test).
        r = admin_client.post(
            f"/api/v1/admin/workflow/dqa/rules/AC-TEST-RULE/v{ver}/sign/",
            {"approver": "admin-test", "note": "lgtm"},
            format="json",
        )
        assert r.status_code == 409

    def test_external_approver_can_sign(self, admin_client, dqa_rule):
        c = admin_client.post(
            "/api/v1/admin/workflow/dqa/rules/AC-TEST-RULE/clone/"
        )
        ver = c.data["version"]
        admin_client.post(
            f"/api/v1/admin/workflow/dqa/rules/AC-TEST-RULE/v{ver}/submit/"
        )
        r = admin_client.post(
            f"/api/v1/admin/workflow/dqa/rules/AC-TEST-RULE/v{ver}/sign/",
            {"approver": "distinct-approver", "note": "approved"},
            format="json",
        )
        assert r.status_code == 200
        assert r.data["status"] == "active"

    def test_retire_active_rule(self, admin_client, dqa_rule):
        # Active by fixture — retire flips to RETIRED.
        ver = dqa_rule.version
        r = admin_client.post(
            f"/api/v1/admin/workflow/dqa/rules/AC-TEST-RULE/v{ver}/retire/"
        )
        assert r.status_code == 200, r.data
        assert r.data["status"] == "retired"

    def test_retire_draft_rejected(self, admin_client, dqa_rule):
        # Cloning produces a DRAFT; retiring DRAFT is invalid state.
        c = admin_client.post(
            "/api/v1/admin/workflow/dqa/rules/AC-TEST-RULE/clone/"
        )
        ver = c.data["version"]
        r = admin_client.post(
            f"/api/v1/admin/workflow/dqa/rules/AC-TEST-RULE/v{ver}/retire/"
        )
        assert r.status_code == 409


# ───────────────────────────────────────────────────────────────
# DDUP — clone + 30-day un-merge window
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDdupVersionWorkflow:
    def test_clone_creates_new_version(self, admin_client, ddup_model):
        r = admin_client.post(
            f"/api/v1/admin/workflow/ddup/versions/{ddup_model.id}/clone/",
            {"threshold_delta": 0.01, "reason": "test"},
            format="json",
        )
        assert r.status_code == 201
        assert r.data["status"] == "draft"
        assert r.data["threshold"] is not None

    def test_patch_active_rejected(self, admin_client, ddup_model):
        r = admin_client.patch(
            f"/api/v1/admin/workflow/ddup/versions/{ddup_model.id}/",
            {"threshold": 0.99},
            format="json",
        )
        assert r.status_code == 409


@pytest.mark.django_db
class TestDdupUnMergeWindow:
    def test_un_merge_within_window_succeeds_or_409(self, admin_client, ddup_model):
        # Create a synthetic merge decision with a future window.
        pair = MatchPair.objects.create(
            record_type="member",
            record_a_id="01TEST_AAA_AAAAAAAAAAAAAAA",
            record_b_id="01TEST_BBB_BBBBBBBBBBBBBBB",
            tier=1,
            match_reason="nin",
            model_version=ddup_model,
            status=PairStatus.MERGED,
        )
        decision = MergeDecision.objects.create(
            match_pair=pair,
            action=MergeAction.MERGE,
            surviving_record_id=pair.record_a_id,
            losing_record_id=pair.record_b_id,
            decided_by="seed",
            reverse_window_until=timezone.now() + timedelta(days=30),
        )
        r = admin_client.post(
            f"/api/v1/admin/workflow/ddup/decisions/{decision.id}/un-merge/",
            {"reason": "wrong merge"},
            format="json",
        )
        # The actual reverse_merge_decision may fail because the
        # underlying Member rows don't exist; we just need the
        # un-merge endpoint to NOT return 410 while inside the window.
        assert r.status_code != 410, r.data

    def test_un_merge_after_window_returns_410(self, admin_client, ddup_model):
        pair = MatchPair.objects.create(
            record_type="member",
            record_a_id="01TEST_CCC_CCCCCCCCCCCCCCC",
            record_b_id="01TEST_DDD_DDDDDDDDDDDDDDD",
            tier=1,
            match_reason="nin",
            model_version=ddup_model,
            status=PairStatus.MERGED,
        )
        decision = MergeDecision.objects.create(
            match_pair=pair,
            action=MergeAction.MERGE,
            surviving_record_id=pair.record_a_id,
            losing_record_id=pair.record_b_id,
            decided_by="seed",
            reverse_window_until=timezone.now() - timedelta(days=1),
        )
        r = admin_client.post(
            f"/api/v1/admin/workflow/ddup/decisions/{decision.id}/un-merge/",
            {"reason": "too late"},
            format="json",
        )
        assert r.status_code == 410


# ───────────────────────────────────────────────────────────────
# DDUP pair queue — hold / cross-household / reject
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDdupPairQueue:
    def test_pair_queue_lists_pending(self, admin_client, ddup_model):
        MatchPair.objects.create(
            record_type="member",
            record_a_id="01PAIR_A_AAAAAAAAAAAAAAAAA",
            record_b_id="01PAIR_A_BBBBBBBBBBBBBBBBB",
            tier=1,
            match_reason="nin",
            model_version=ddup_model,
        )
        r = admin_client.get("/api/v1/admin/workflow/ddup/pairs/")
        assert r.status_code == 200
        assert len(r.data["results"]) >= 1

    def test_hold_flips_status(self, admin_client, ddup_model):
        p = MatchPair.objects.create(
            record_type="member",
            record_a_id="01PAIR_B_AAAAAAAAAAAAAAAAA",
            record_b_id="01PAIR_B_BBBBBBBBBBBBBBBBB",
            tier=1,
            match_reason="nin",
            model_version=ddup_model,
        )
        r = admin_client.post(
            f"/api/v1/admin/workflow/ddup/pairs/{p.id}/hold/",
            {"reason": "needs steward review"},
            format="json",
        )
        assert r.status_code == 200
        p.refresh_from_db()
        assert p.status == PairStatus.ON_HOLD

    def test_cross_household_flips_status(self, admin_client, ddup_model):
        p = MatchPair.objects.create(
            record_type="member",
            record_a_id="01PAIR_C_AAAAAAAAAAAAAAAAA",
            record_b_id="01PAIR_C_BBBBBBBBBBBBBBBBB",
            tier=1,
            match_reason="nin",
            model_version=ddup_model,
        )
        r = admin_client.post(
            f"/api/v1/admin/workflow/ddup/pairs/{p.id}/cross-household/",
        )
        assert r.status_code == 200
        p.refresh_from_db()
        assert p.status == PairStatus.CROSS_HOUSEHOLD
