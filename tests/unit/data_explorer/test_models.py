"""DATA-EXP model-layer tests.

Anchored to ADR-0023:
- All externally-visible IDs are ULIDs.
- PrivacyClass.k_floor is non-negative.
- Dataset.code is unique.
- Variable.privacy_class is required (FK PROTECT) and (dataset, code)
  is a unique pair.
- AggregateQueryLog indexes (actor, executed_at) for the overlap-burst
  detector to scan a single actor's last 24h efficiently.

These tests check the contract; they don't rely on the Coder's
internal helper signatures.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.db.models import Index


pytestmark = pytest.mark.django_db


def _model(name: str):
    from apps.data_explorer import models as m
    return getattr(m, name)


def test_privacy_class_code_unique(privacy_classes):
    PrivacyClass = _model("PrivacyClass")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PrivacyClass.objects.create(
                code="internal", label="Dup", k_floor=5,
            )


def test_privacy_class_k_floor_non_negative(privacy_classes):
    """k_floor is PositiveSmallIntegerField — DB / Django rejects < 0."""
    PrivacyClass = _model("PrivacyClass")
    cls = privacy_classes["internal"]
    cls.k_floor = -1
    with pytest.raises(Exception):
        cls.full_clean()


def test_privacy_class_id_is_ulid(privacy_classes):
    """ULIDs are 26 chars, Crockford base32, no integers."""
    pid = privacy_classes["internal"].id
    assert isinstance(pid, str)
    assert len(pid) == 26
    assert not pid.isdigit()


def test_dataset_code_unique(dataset, privacy_classes, refresh_cadences):
    Dataset = _model("Dataset")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Dataset.objects.create(
                code=dataset.code,  # duplicate
                label="Dup",
                privacy_class=privacy_classes["internal"],
                refresh_cadence=refresh_cadences["daily"],
            )


def test_dataset_id_is_ulid(dataset):
    assert isinstance(dataset.id, str)
    assert len(dataset.id) == 26


def test_dataset_privacy_class_protect(dataset, privacy_classes):
    """Cannot delete a PrivacyClass while a Dataset references it."""
    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError):
        privacy_classes["internal"].delete()


def test_variable_requires_privacy_class(dataset):
    """The FK is NOT NULL — every Variable must have a PrivacyClass."""
    Variable = _model("Variable")
    with pytest.raises(Exception):
        with transaction.atomic():
            Variable.objects.create(
                dataset=dataset,
                code="x.no_class",
                label="No class",
                # privacy_class missing → IntegrityError / ValueError
            )


def test_variable_unique_dataset_code(dataset, variable_internal):
    Variable = _model("Variable")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Variable.objects.create(
                dataset=dataset,
                code=variable_internal.code,
                label="Dup",
                privacy_class=variable_internal.privacy_class,
            )


def test_variable_starts_inactive_when_default(dataset, privacy_classes):
    """ADR-0023 D5: new Variable rows seeded INACTIVE."""
    Variable = _model("Variable")
    v = Variable.objects.create(
        dataset=dataset,
        code="household.new_field",
        label="New field — pending approval",
        privacy_class=privacy_classes["internal"],
    )
    assert v.status == "inactive"


def test_aggregate_query_log_actor_executed_at_index(privacy_classes, dataset):
    """The (actor, executed_at) index is what the overlap-burst detector
    scans. Drop it and a national load will table-scan."""
    AggregateQueryLog = _model("AggregateQueryLog")
    indexes = AggregateQueryLog._meta.indexes
    fields_pairs = {tuple(i.fields) for i in indexes if isinstance(i, Index)}
    assert ("actor", "executed_at") in fields_pairs


def test_aggregate_query_log_filter_hash_db_indexed():
    """The differencing-attack detector groups by filter_hash — must
    be indexed for the nightly task to be tractable."""
    AggregateQueryLog = _model("AggregateQueryLog")
    field = AggregateQueryLog._meta.get_field("filter_hash")
    assert field.db_index is True


def test_aggregate_query_log_id_is_ulid(privacy_classes, dataset):
    AggregateQueryLog = _model("AggregateQueryLog")
    row = AggregateQueryLog.objects.create(
        actor="user-1",
        dataset=dataset,
        filter_hash="a" * 64,
        query_hash="b" * 64,
        strictest_privacy_class="internal",
    )
    assert len(row.id) == 26


def test_explorer_session_id_is_ulid(privacy_classes, dataset):
    ExplorerSession = _model("ExplorerSession")
    s = ExplorerSession.objects.create(actor="user-1")
    assert len(s.id) == 26
    assert s.handoff_status == "draft"


def test_variable_approval_unique_per_role(variable_internal):
    """Mirrors DqaRule + PMTModelVersion: at most one approval row per
    (variable, role) so 'two distinct DQA approvers' can't satisfy the
    dual-approval gate."""
    VariableApproval = _model("VariableApproval")
    VariableApproval.objects.create(
        variable=variable_internal,
        approver="dqa-alice",
        approval_role="dqa",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            VariableApproval.objects.create(
                variable=variable_internal,
                approver="dqa-bob",
                approval_role="dqa",
            )


def test_query_throttle_counter_unique_actor_class_day(privacy_classes):
    """Counter is keyed on (actor, privacy_class, date_utc). A second
    row with the same key must fail — atomic update is increment-in-
    place, never a fresh row."""
    from datetime import date

    QueryThrottleCounter = _model("QueryThrottleCounter")
    QueryThrottleCounter.objects.create(
        actor="u1",
        privacy_class=privacy_classes["internal"],
        date_utc=date(2026, 5, 27),
        count=1,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            QueryThrottleCounter.objects.create(
                actor="u1",
                privacy_class=privacy_classes["internal"],
                date_utc=date(2026, 5, 27),
                count=99,
            )
