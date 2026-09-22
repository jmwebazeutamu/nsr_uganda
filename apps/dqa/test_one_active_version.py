"""A rule has exactly one active version, and the database says so.

AC-MEMBER-AGE-MAX sat on production with v1 and v2 both ACTIVE for four
months. `services.approve` retires the version it supersedes, and both
evaluators dedup by rule_id keeping the highest version — but v2 was
approved before that fix existed, and nothing at the storage layer
stopped it.

A rule is the policy a household is judged against. "Whichever version
the queryset yielded" is not an acceptable answer to which policy
applied, so the invariant is enforced where it cannot be bypassed.
"""

import pytest
from django.db import IntegrityError, transaction

from apps.dqa.models import DqaRule, RuleStatus
from apps.dqa.services import approve, submit_for_approval


def _rule(rule_id: str, version: int, status: str, **extra) -> DqaRule:
    return DqaRule.objects.create(
        rule_id=rule_id, version=version, status=status,
        description=f"{rule_id} v{version}", severity="block",
        expression={"op": "notnull", "args": ["$.surname"]},
        author="tests", **extra,
    )


@pytest.mark.django_db
class TestTheDatabaseEnforcesIt:
    def test_a_second_active_version_is_refused(self):
        _rule("AC-TEST-ONE", 1, RuleStatus.ACTIVE)
        with pytest.raises(IntegrityError), transaction.atomic():
            _rule("AC-TEST-ONE", 2, RuleStatus.ACTIVE)

    def test_other_statuses_are_unaffected(self):
        """Only ACTIVE is constrained — a rule can have any number of
        drafts, rejected and retired versions behind it."""
        _rule("AC-TEST-TWO", 1, RuleStatus.ACTIVE)
        _rule("AC-TEST-TWO", 2, RuleStatus.DRAFT)
        _rule("AC-TEST-TWO", 3, RuleStatus.PENDING_APPROVAL)
        _rule("AC-TEST-TWO", 4, RuleStatus.RETIRED)
        _rule("AC-TEST-TWO", 5, RuleStatus.REJECTED)
        assert DqaRule.objects.filter(rule_id="AC-TEST-TWO").count() == 5

    def test_different_rules_are_independent(self):
        _rule("AC-TEST-A", 1, RuleStatus.ACTIVE)
        _rule("AC-TEST-B", 1, RuleStatus.ACTIVE)
        assert DqaRule.objects.filter(status=RuleStatus.ACTIVE).count() >= 2

    def test_retiring_frees_the_slot(self):
        first = _rule("AC-TEST-THREE", 1, RuleStatus.ACTIVE)
        first.status = RuleStatus.RETIRED
        first.save(update_fields=["status"])
        _rule("AC-TEST-THREE", 2, RuleStatus.ACTIVE)
        assert DqaRule.objects.filter(
            rule_id="AC-TEST-THREE", status=RuleStatus.ACTIVE,
        ).count() == 1


@pytest.mark.django_db
class TestApprovalStillWorks:
    """The constraint must not break the normal path — approve() retires
    the old version in the same transaction, so the slot is free."""

    def test_approving_a_new_version_supersedes_the_old_one(self):
        old = _rule("AC-TEST-FLOW", 1, RuleStatus.ACTIVE)
        new = _rule("AC-TEST-FLOW", 2, RuleStatus.DRAFT)
        submit_for_approval(new, actor="author-b")
        approve(new, approver="approver-a", note="supersedes v1", actor="approver-a")

        old.refresh_from_db()
        new.refresh_from_db()
        assert old.status == RuleStatus.RETIRED
        assert new.status == RuleStatus.ACTIVE
        assert DqaRule.objects.filter(
            rule_id="AC-TEST-FLOW", status=RuleStatus.ACTIVE,
        ).count() == 1

    def test_the_first_ever_version_activates_with_nothing_to_supersede(self):
        only = _rule("AC-TEST-FIRST", 1, RuleStatus.DRAFT)
        submit_for_approval(only, actor="author-b")
        approve(only, approver="approver-a", note="first version", actor="approver-a")
        only.refresh_from_db()
        assert only.status == RuleStatus.ACTIVE


@pytest.mark.django_db
class TestTheMigrationFixesExistingData:
    def test_the_highest_version_is_the_one_kept(self):
        """Production had AC-MEMBER-AGE-MAX v1 and v2 both active. Both
        evaluators were already choosing the highest version in their
        ORDER BY, so keeping v2 changes no evaluation outcome — it makes
        the stored state say what the engine was already doing."""
        from apps.dqa.migrations import (
            __name__ as _,  # noqa: F401  (package import guard)
        )
        from importlib import import_module

        migration = import_module("apps.dqa.migrations.0005_one_active_rule_version")
        assert hasattr(migration, "retire_superseded_actives")
