"""US-S11-044 — Contract tests for the intra-household DQA API.

Covers:
- POST /api/v1/dqa/evaluate/household (sync + persist mode)
- GET  /api/v1/dqa/evaluations/{household_id}
- GET  /api/v1/dqa/severity-vocabulary
- Feature-flag-disabled returns 503
- DqaRule serializer exposes the new US-S11-044 fields
- AuditEvent is emitted on persist=true (audit contract)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.dqa.models import (
    DqaEvaluation,
    DqaRule,
    ExpressionType,
    RuleCategory,
    RuleScope,
    RuleStage,
    RuleStatus,
    Severity,
)
from apps.security.models import AuditEvent


@pytest.fixture
def api_client(db):
    from apps.security.models import OperatorScope, ScopeLevel

    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="dqa-tester", password="x", is_active=True,
    )
    # National-scope operator: the DQA evaluation API operates across
    # pre-promotion provisional ids (DIH visibility), so the canonical
    # API caller is national. Geographic gating is covered by the
    # negative test below.
    OperatorScope.objects.create(
        user=user, scope_level=ScopeLevel.NATIONAL, scope_code="",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def hoh_exists_rule(db):
    """A minimal ACTIVE rule the evaluator can pick up. Fails when the
    household has zero members claiming relationship_to_head='head'."""
    return DqaRule.objects.create(
        rule_id="AC-HOH-EXISTS",
        version=1,
        description="Exactly one head per household",
        severity=Severity.BLOCK,
        category=RuleCategory.INTRA_HOUSEHOLD,
        scope=RuleScope.HOUSEHOLD,
        expression_type=ExpressionType.DSL,
        stages=[
            RuleStage.DIH_INGEST.value,
            RuleStage.DIH_PROMOTE.value,
            RuleStage.REGISTRY_POST_PROMOTE.value,
        ],
        parameters={"head_code": "head", "expected_count": 1},
        applies_to={"members": ["relationship_to_head"]},
        expression={
            "op": "count_where",
            "predicate": {
                "op": "eq",
                "args": ["$.relationship_to_head", "$parameters.head_code"],
            },
            "_fail_when": {
                "op": "neq",
                "args": ["$", "$parameters.expected_count"],
            },
        },
        error_message_template="Expected 1 head, found {actual}",
        status=RuleStatus.ACTIVE,
        author="seed",
        approved_by="seed-approver",
        approved_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Feature flag gating

@pytest.mark.django_db
class TestFeatureFlagGate:
    def test_evaluate_returns_503_when_flag_off(self, api_client, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = False
        r = api_client.post(
            "/api/v1/dqa/evaluate/household",
            data={"payload": {}, "stage": "dih_ingest"},
            format="json",
        )
        assert r.status_code == 503

    def test_history_returns_503_when_flag_off(self, api_client, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = False
        r = api_client.get("/api/v1/dqa/evaluations/01HXXXX")
        assert r.status_code == 503

    def test_vocabulary_returns_503_when_flag_off(self, api_client, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = False
        r = api_client.get("/api/v1/dqa/severity-vocabulary")
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# Sync evaluation

@pytest.mark.django_db
class TestEvaluateHouseholdSync:
    def _payload(self, members):
        return {"members": members}

    def test_pass_when_exactly_one_head(
        self, api_client, settings, hoh_exists_rule,
    ):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        payload = self._payload([
            {"line_number": 1, "relationship_to_head": "head"},
            {"line_number": 2, "relationship_to_head": "spouse"},
        ])
        r = api_client.post(
            "/api/v1/dqa/evaluate/household",
            data={"payload": payload, "stage": "dih_ingest"},
            format="json",
        )
        assert r.status_code == 200
        body = r.json()
        assert body["outcome"] == "pass"
        assert body["rules_evaluated"] == 1
        assert body["evaluator_service_version"]
        assert body["results"][0]["status"] == "pass"

    def test_block_when_zero_heads(
        self, api_client, settings, hoh_exists_rule,
    ):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        payload = self._payload([
            {"line_number": 1, "relationship_to_head": "spouse"},
        ])
        r = api_client.post(
            "/api/v1/dqa/evaluate/household",
            data={"payload": payload, "stage": "dih_ingest"},
            format="json",
        )
        assert r.status_code == 200
        body = r.json()
        assert body["outcome"] == "block"
        assert body["results"][0]["status"] == "fail"
        assert body["results"][0]["severity"] == "block"

    def test_stage_filter_skips_rules_with_mismatched_stage(
        self, api_client, settings, hoh_exists_rule,
    ):
        """Rule only applies to dih_ingest + dih_promote. Calling with
        registry_post_promote off the rule's stage list still picks
        the rule up because the seed applies it everywhere. Confirm by
        narrowing the rule's stage list."""
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        hoh_exists_rule.stages = ["dih_ingest"]
        hoh_exists_rule.save()
        r = api_client.post(
            "/api/v1/dqa/evaluate/household",
            data={
                "payload": self._payload([]),
                "stage": "registry_post_promote",
            },
            format="json",
        )
        assert r.status_code == 200
        body = r.json()
        assert body["rules_evaluated"] == 0
        assert body["outcome"] == "pass"

    def test_persist_requires_household_id(
        self, api_client, settings, hoh_exists_rule,
    ):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        r = api_client.post(
            "/api/v1/dqa/evaluate/household",
            data={
                "payload": self._payload([]),
                "stage": "dih_ingest",
                "persist": True,
            },
            format="json",
        )
        assert r.status_code == 400
        assert "household_id" in r.json()["detail"]

    def test_persist_writes_row_and_emits_audit(
        self, api_client, settings, hoh_exists_rule,
    ):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        before_audits = AuditEvent.objects.filter(
            action="dqa.household.evaluated",
        ).count()
        r = api_client.post(
            "/api/v1/dqa/evaluate/household",
            data={
                "payload": self._payload([
                    {"line_number": 1, "relationship_to_head": "head"},
                ]),
                "stage": "dih_ingest",
                "persist": True,
                "household_id": "01HHHTESTPERSIST",
            },
            format="json",
        )
        assert r.status_code == 200, r.json()
        body = r.json()
        # Persistence path returns the row id.
        assert body["evaluation_id"]
        assert DqaEvaluation.objects.filter(
            household_id="01HHHTESTPERSIST",
        ).count() == 1
        # Audit contract — SAD §8.4. Action emitted, household_id
        # referenced by id (not payload contents duplicated).
        after_audits = AuditEvent.objects.filter(
            action="dqa.household.evaluated",
        ).count()
        assert after_audits == before_audits + 1


# ---------------------------------------------------------------------------
# Evaluation history

@pytest.mark.django_db
class TestEvaluationHistory:
    def _make_eval(self, household_id, stage, outcome):
        return DqaEvaluation.objects.create(
            household_id=household_id, stage=stage, outcome=outcome,
            results=[], evaluator_service_version="1.0", actor="test",
        )

    def test_history_returns_newest_first(self, api_client, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        self._make_eval("01HHH1", "dih_ingest", "pass")
        self._make_eval("01HHH1", "dih_promote", "review")
        self._make_eval("01HHH1", "registry_post_promote", "block")
        r = api_client.get("/api/v1/dqa/evaluations/01HHH1")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 3
        # Newest first (we created post_promote last).
        assert rows[0]["stage"] == "registry_post_promote"

    def test_history_filters_by_stage(self, api_client, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        self._make_eval("01HHH2", "dih_ingest", "pass")
        self._make_eval("01HHH2", "dih_promote", "block")
        r = api_client.get(
            "/api/v1/dqa/evaluations/01HHH2?stage=dih_promote",
        )
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["stage"] == "dih_promote"

    def test_history_filters_by_outcome(self, api_client, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        self._make_eval("01HHH3", "dih_ingest", "pass")
        self._make_eval("01HHH3", "dih_promote", "block")
        r = api_client.get(
            "/api/v1/dqa/evaluations/01HHH3?outcome=block",
        )
        assert r.status_code == 200
        rows = r.json()
        assert all(r["outcome"] == "block" for r in rows)
        assert len(rows) == 1

    def test_history_scoped_to_household_id(self, api_client, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        self._make_eval("01HHH-A", "dih_ingest", "pass")
        self._make_eval("01HHH-B", "dih_ingest", "pass")
        r = api_client.get("/api/v1/dqa/evaluations/01HHH-A")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["household_id"] == "01HHH-A"


# ---------------------------------------------------------------------------
# Vocabulary

@pytest.mark.django_db
class TestSeverityVocabulary:
    def test_returns_all_severities_with_design_tokens(
        self, api_client, settings,
    ):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        r = api_client.get("/api/v1/dqa/severity-vocabulary")
        assert r.status_code == 200
        body = r.json()
        severities = body["severities"]
        values = {s["value"] for s in severities}
        assert values == {"block", "reject_with_override", "flag", "info"}
        # Wizard relies on blocks_save to gate Save / Next.
        block = next(s for s in severities if s["value"] == "block")
        flag = next(s for s in severities if s["value"] == "flag")
        assert block["blocks_save"] is True
        assert flag["blocks_save"] is False
        # Stage + outcome + scope + category vocabulary also exposed
        # so the Rule Editor populates dropdowns from one call.
        assert {s["value"] for s in body["stages"]} == {
            "dih_ingest", "dih_promote", "registry_post_promote",
        }
        assert {o["value"] for o in body["outcomes"]} == {
            "pass", "review", "block",
        }
        assert {c["value"] for c in body["categories"]} >= {
            "intra_household", "field_level",
        }


# ---------------------------------------------------------------------------
# Rule serializer surface

@pytest.mark.django_db
class TestDqaRuleSerializerSurface:
    def test_new_fields_round_trip(self, api_client, hoh_exists_rule):
        """The Rule Editor needs to read category/scope/stages/
        parameters/applies_to/test_fixtures/message_template_i18n_key
        off the rule list/detail responses."""
        r = api_client.get(f"/api/v1/dqa/rules/{hoh_exists_rule.id}/")
        assert r.status_code == 200
        body = r.json()
        assert body["category"] == "intra_household"
        assert body["scope"] == "household"
        assert body["expression_type"] == "dsl"
        assert "dih_ingest" in body["stages"]
        assert body["parameters"]["head_code"] == "head"
        assert body["applies_to"]["members"] == ["relationship_to_head"]
        assert body["test_fixtures"] == []
        assert "message_template_i18n_key" in body


@pytest.mark.django_db
class TestEvaluationAbacScope:
    """ABAC: a geographically-scoped operator cannot read or persist DQA
    evaluations for households outside their scope (US-S11-044 / SAD §8.2)."""

    def _scoped_op_and_household(self, settings):
        from datetime import date

        from apps.data_management.models import Household
        from apps.reference_data.models import GeographicUnit
        from apps.security.models import OperatorScope, ScopeLevel

        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        nodes = {}
        for level, key, parent in [
            ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
            ("county", "c", "d"), ("sub_county", "sc", "c"),
            ("parish", "p", "sc"), ("village", "v", "p"),
        ]:
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=f"DQ-{key.upper()}", name=key,
                parent=nodes.get(parent), effective_from=date(2026, 1, 1),
            )
        hh = Household.objects.create(
            region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
            county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"],
            village=nodes["v"], urban_rural="2",
        )
        user = get_user_model().objects.create_user(username="dqa-elsewhere", password="x")
        OperatorScope.objects.create(
            user=user, scope_level=ScopeLevel.SUB_REGION, scope_code="OTHER-SR",
        )
        c = APIClient()
        c.force_authenticate(user=user)
        return c, hh

    def test_history_out_of_scope_returns_empty(self, db, settings):
        c, hh = self._scoped_op_and_household(settings)
        DqaEvaluation.objects.create(
            household_id=hh.id, stage="dih_ingest", outcome="block",
            results=[], evaluator_service_version="t", actor="x",
        )
        r = c.get(f"/api/v1/dqa/evaluations/{hh.id}")
        assert r.status_code == 200
        assert r.json() == []

    def test_persist_out_of_scope_returns_404(self, db, settings):
        c, hh = self._scoped_op_and_household(settings)
        r = c.post(
            "/api/v1/dqa/evaluate/household",
            data={"payload": {"members": []}, "stage": "dih_ingest",
                  "persist": True, "household_id": hh.id},
            format="json",
        )
        assert r.status_code == 404
