"""US-S11-044 — Pipeline gateway + per-stage routing.

Validates:
- Feature flag off → gate is a no-op (returns None).
- BLOCK at DIH_PROMOTE → DqaBlockError raised.
- BLOCK at DIH_INGEST → persisted but never raises.
- BLOCK at REGISTRY_POST_PROMOTE → persisted but never raises.
- REJECT_WITH_OVERRIDE without override_reason → raises.
- REJECT_WITH_OVERRIDE with override_reason → proceeds + audited.
- FLAG → emits dqa.household.flag AuditEvent.
- household_to_dqa_payload shape covers fields the seed rules read.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.dqa.models import (
    DqaRule,
    ExpressionType,
    RuleCategory,
    RuleScope,
    RuleStage,
    RuleStatus,
    Severity,
)
from apps.dqa.pipeline import (
    DqaBlockError,
    DqaRejectWithOverrideError,
    household_to_dqa_payload,
    run_household_gate,
)
from apps.security.models import AuditEvent


def _rule(rule_id: str, severity: str) -> DqaRule:
    """A minimal ACTIVE rule that always fails (count > 0 when there
    are zero heads). Lets us steer the gate's routing decision by
    only varying severity."""
    return DqaRule.objects.create(
        rule_id=rule_id, version=1,
        description=f"always-fails ({severity})",
        severity=severity,
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
        error_message_template="no head",
        status=RuleStatus.ACTIVE,
        author="test", approved_by="test-approver",
        approved_at=datetime.now(UTC),
    )


_NO_HEAD_PAYLOAD = {"members": [{"line_number": 1, "relationship_to_head": "spouse"}]}


@pytest.mark.django_db
class TestFlagOff:
    def test_no_op_when_flag_disabled(self, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = False
        result = run_household_gate(
            _NO_HEAD_PAYLOAD,
            stage="dih_promote",
            household_id="01HHGATEFLAG",
        )
        assert result is None


@pytest.mark.django_db
class TestBlockRouting:
    def test_block_at_promote_raises(self, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        _rule("AC-TEST-BLOCK", Severity.BLOCK)
        with pytest.raises(DqaBlockError) as excinfo:
            run_household_gate(
                _NO_HEAD_PAYLOAD,
                stage="dih_promote",
                household_id="01HHBLOCKPRO",
            )
        assert "AC-TEST-BLOCK" in excinfo.value.codes
        assert excinfo.value.evaluation_id

    def test_block_at_ingest_persists_but_does_not_raise(self, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        _rule("AC-TEST-BLOCK-ING", Severity.BLOCK)
        eval_row = run_household_gate(
            _NO_HEAD_PAYLOAD,
            stage="dih_ingest",
            household_id="01HHBLOCKING",
        )
        # Persists the failure but ingest never aborts — the queue
        # is the triage surface.
        assert eval_row is not None
        assert eval_row.outcome == "block"

    def test_block_at_post_promote_does_not_raise(self, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        _rule("AC-TEST-BLOCK-POST", Severity.BLOCK)
        eval_row = run_household_gate(
            _NO_HEAD_PAYLOAD,
            stage="registry_post_promote",
            household_id="01HHBLOCKPOST",
        )
        # Promotion already happened; gate can only record.
        assert eval_row is not None
        assert eval_row.outcome == "block"


@pytest.mark.django_db
class TestRejectWithOverride:
    def test_raises_without_override(self, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        _rule("AC-TEST-RWO", Severity.REJECT_WITH_OVERRIDE)
        with pytest.raises(DqaRejectWithOverrideError) as excinfo:
            run_household_gate(
                _NO_HEAD_PAYLOAD,
                stage="dih_promote",
                household_id="01HHRWO",
            )
        assert "AC-TEST-RWO" in excinfo.value.codes

    def test_proceeds_with_override_and_audits(self, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        _rule("AC-TEST-RWO-OK", Severity.REJECT_WITH_OVERRIDE)
        before = AuditEvent.objects.filter(
            action="dqa.household.override",
        ).count()
        eval_row = run_household_gate(
            _NO_HEAD_PAYLOAD,
            stage="dih_promote",
            household_id="01HHRWOOK",
            override_reason="Field officer reviewed in person — confirmed.",
        )
        assert eval_row is not None
        after = AuditEvent.objects.filter(
            action="dqa.household.override",
        ).count()
        assert after == before + 1


@pytest.mark.django_db
class TestFlagRouting:
    def test_flag_emits_review_audit(self, settings):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        _rule("AC-TEST-FLAG", Severity.FLAG)
        before = AuditEvent.objects.filter(
            action="dqa.household.flag",
        ).count()
        eval_row = run_household_gate(
            _NO_HEAD_PAYLOAD,
            stage="dih_promote",
            household_id="01HHFLAGD",
        )
        # FLAG never aborts.
        assert eval_row is not None
        assert eval_row.outcome == "review"
        after = AuditEvent.objects.filter(
            action="dqa.household.flag",
        ).count()
        assert after == before + 1


@pytest.mark.django_db
class TestPayloadProjection:
    def test_household_to_payload_includes_member_fields(self, db):
        """household_to_dqa_payload must expose the fields the seeded
        rules read: relationship_to_head, age, line_number, nin_hash,
        mother_line_number, father_line_number, orphan_flag, sex,
        disability_flag — plus reported_household_size on the hh."""
        # Build a minimal stub rather than a full ORM household so this
        # stays a pure projection test. The pipeline helper uses
        # getattr() with a None default, so any object with these
        # attributes is fine.
        class _M:
            def __init__(self, **kw):
                self.__dict__.update(kw)
        member = _M(
            id="01M1", line_number=1, relationship_to_head="head",
            age=42, sex="female", nin_hash="h1",
            mother_line_number=None, father_line_number=None,
            orphan_flag=False, disability_flag=False, alive=True,
        )

        class _Manager:
            def all(self):
                return [member]
        hh = _M(
            id="01HHHPAYLOAD",
            reported_household_size=1,
            members=_Manager(),
        )
        payload = household_to_dqa_payload(hh)
        assert payload["household_id"] == "01HHHPAYLOAD"
        assert payload["reported_household_size"] == 1
        assert len(payload["members"]) == 1
        m = payload["members"][0]
        for key in (
            "line_number", "relationship_to_head", "age", "sex",
            "nin_hash", "mother_line_number", "father_line_number",
            "orphan_flag", "disability_flag", "alive",
        ):
            assert key in m, f"missing {key} in projection"
