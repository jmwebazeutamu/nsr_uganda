"""Bulk promotion must not 500, and promotion must be idempotent against
the REGISTRY rather than against its own bookkeeping.

Reported from the console as:

    Promoted failed: SyntaxError: Unexpected token 'I', "IntegrityE"...
      is not valid JSON

Three faults stacked up behind that one message:

1. `promote_stage_record`'s idempotency guard fired only when the stage
   record said it was promoted AND remembered which household it became.
   When those two facts disagreed with the registry, it fell through and
   INSERTed a household whose primary key already existed.
2. `_bulk_iterate` caught only DihError, so the IntegrityError escaped
   the view. Rows already promoted earlier in the same batch were
   committed but never reported, so the queue looked untouched.
3. The console called `r.json()` on the resulting HTML error page, and
   reported the parser's problem instead of the registry's.

The drift is not hypothetical and is not only caused by the obvious
mistake: a crash between the Household insert and the stage update, a
retried request, or two operators clicking Promote on the same row all
produce it.
"""

from __future__ import annotations

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.data_management.models import Household
from apps.ingestion_hub.models import (
    Connector,
    SourceSystem,
    SourceSystemKind,
    StageRecord,
    StageRecordState,
)
from apps.ingestion_hub.services import (
    promote_stage_record,
    submit_walk_in_capture,
)
from apps.reference_data.models import GeographicUnit


@pytest.fixture
def geo(db):
    codes = [
        ("region", "BP-R"), ("sub_region", "BP-SR"), ("district", "BP-D"),
        ("county", "BP-C"), ("sub_county", "BP-SC"), ("parish", "BP-P"),
    ]
    parent = None
    for level, code in codes:
        parent = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent,
            effective_from=date(2026, 1, 1),
        )
    return {level: code for level, code in codes}


@pytest.fixture
def walkin_connector(db):
    src, _ = SourceSystem.objects.get_or_create(
        code="PARISH-WALKIN",
        defaults={"name": "Parish walk-in", "kind": SourceSystemKind.CAPI_WALKIN},
    )
    connector, _ = Connector.objects.get_or_create(
        source_system=src, name="parish-walkin",
    )
    return connector


def _payload(geo, *, surname="Okello"):
    return {
        "geographic": dict(geo, village=""),
        "urban_rural": "2",
        "consent": "yes",
        "members": [{
            "line_number": 1, "surname": surname, "first_name": "Santo",
            "sex": "1", "relationship_to_head": "01", "is_head": True,
            "age_years": 40,
        }],
        "source_channel": "parish_walkin",
    }


@pytest.fixture
def drifted(geo, walkin_connector, db):
    """A stage record whose household exists but whose bookkeeping says
    it does not — the state that produced the IntegrityError."""
    stage = submit_walk_in_capture(_payload(geo), actor="op")
    promote_stage_record(stage, actor="reviewer")
    stage.refresh_from_db()
    assert Household.objects.filter(pk=stage.provisional_registry_id).exists()

    # Roll the bookkeeping back WITHOUT removing the household, which is
    # what a crash between the two writes leaves behind.
    stage.state = StageRecordState.PENDING_PROMOTION
    stage.promoted_household_id = ""
    stage.promoted_at = None
    stage.save(update_fields=[
        "state", "promoted_household_id", "promoted_at", "updated_at",
    ])
    return stage


@pytest.mark.django_db
class TestPromotionIsIdempotentAgainstTheRegistry:
    def test_promoting_a_drifted_record_does_not_raise(self, drifted):
        household = promote_stage_record(drifted, actor="reviewer")
        assert household.id == drifted.provisional_registry_id

    def test_it_returns_the_existing_household_rather_than_a_new_one(self, drifted):
        before = Household.objects.count()
        promote_stage_record(drifted, actor="reviewer")
        assert Household.objects.count() == before, (
            "promotion inserted a second household for one Registry ID"
        )

    def test_the_bookkeeping_is_reconciled_to_the_registry(self, drifted):
        promote_stage_record(drifted, actor="reviewer")
        drifted.refresh_from_db()
        assert drifted.state == StageRecordState.PROMOTED
        assert drifted.promoted_household_id == drifted.provisional_registry_id
        assert drifted.promoted_at is not None

    def test_the_reconciliation_is_audited_not_silent(self, drifted):
        from apps.security.models import AuditEvent

        before = AuditEvent.objects.filter(entity_id=drifted.id).count()
        promote_stage_record(drifted, actor="reviewer")
        events = AuditEvent.objects.filter(entity_id=drifted.id)
        assert events.count() > before
        assert any("reconciled" in (e.reason or "") for e in events), (
            "a stage record and the registry drifting apart is worth "
            "being able to find later"
        )

    def test_an_ordinary_promotion_is_untouched(self, geo, walkin_connector):
        stage = submit_walk_in_capture(_payload(geo, surname="Normal"), actor="op")
        household = promote_stage_record(stage, actor="reviewer")
        stage.refresh_from_db()
        assert stage.state == StageRecordState.PROMOTED
        assert household.id == stage.provisional_registry_id

    def test_a_rejected_record_is_still_refused(self, geo, walkin_connector):
        from apps.ingestion_hub.services import DihError

        stage = submit_walk_in_capture(_payload(geo, surname="Rejected"), actor="op")
        stage.state = StageRecordState.REJECTED
        stage.save(update_fields=["state"])
        with pytest.raises(DihError, match="cannot promote"):
            promote_stage_record(stage, actor="reviewer")


@pytest.mark.django_db
class TestBulkPromoteSurvivesABadRow:
    URL = "/api/v1/dih/stage-records/bulk-promote/"

    def _client(self, django_user_model):
        user = django_user_model.objects.create_superuser(
            username="bp-reviewer", password="p", email="b@example.com",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_the_reported_case_returns_json_not_a_500(
        self, django_user_model, drifted,
    ):
        """The whole defect in one assertion: the operator gets a
        parseable answer instead of an HTML error page."""
        response = self._client(django_user_model).post(
            self.URL, {"stage_ids": [drifted.id], "reason": "x"}, format="json",
        )
        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/json")

    def test_a_row_that_fails_is_reported_per_row(
        self, django_user_model, geo, walkin_connector, monkeypatch,
    ):
        """Any failure — not just the ones the service anticipates — has
        to land in `results` beside every other outcome."""
        from apps.ingestion_hub import api as dih_api

        good = submit_walk_in_capture(_payload(geo, surname="Good"), actor="op")
        bad = submit_walk_in_capture(_payload(geo, surname="Bad"), actor="op")
        for stage in (good, bad):
            StageRecord.objects.filter(pk=stage.pk).update(
                state=StageRecordState.PENDING_PROMOTION,
            )

        real = dih_api.promote_stage_record

        def _explode(stage, **kwargs):
            if stage.pk == bad.pk:
                raise ValueError("something the service never anticipated")
            return real(stage, **kwargs)

        monkeypatch.setattr(dih_api, "promote_stage_record", _explode)

        response = self._client(django_user_model).post(
            self.URL, {"stage_ids": [good.id, bad.id], "reason": "x"}, format="json",
        )
        assert response.status_code == 200
        by_id = {r["stage_id"]: r for r in response.data["results"]}
        assert by_id[good.id]["ok"] is True
        assert by_id[bad.id]["ok"] is False
        assert "ValueError" in by_id[bad.id]["detail"]
        assert "never anticipated" in by_id[bad.id]["detail"]

    def test_a_bad_row_does_not_cost_the_good_ones(
        self, django_user_model, geo, walkin_connector, monkeypatch,
    ):
        """The rows that succeeded before the bad one used to be
        committed but never reported, so the queue looked untouched."""
        from apps.ingestion_hub import api as dih_api

        good = submit_walk_in_capture(_payload(geo, surname="Good2"), actor="op")
        bad = submit_walk_in_capture(_payload(geo, surname="Bad2"), actor="op")
        for stage in (good, bad):
            StageRecord.objects.filter(pk=stage.pk).update(
                state=StageRecordState.PENDING_PROMOTION,
            )
        real = dih_api.promote_stage_record
        monkeypatch.setattr(
            dih_api, "promote_stage_record",
            lambda stage, **kw: (_ for _ in ()).throw(ValueError("boom"))
            if stage.pk == bad.pk else real(stage, **kw),
        )
        response = self._client(django_user_model).post(
            self.URL, {"stage_ids": [bad.id, good.id], "reason": "x"}, format="json",
        )
        assert response.data["succeeded"] == 1
        assert response.data["skipped"] == 1
        good.refresh_from_db()
        assert good.state == StageRecordState.PROMOTED

    def test_a_batch_of_drifted_records_all_promote(
        self, django_user_model, geo, walkin_connector,
    ):
        stages = []
        for i in range(3):
            stage = submit_walk_in_capture(
                _payload(geo, surname=f"Drift{i}"), actor="op",
            )
            promote_stage_record(stage, actor="reviewer")
            StageRecord.objects.filter(pk=stage.pk).update(
                state=StageRecordState.PENDING_PROMOTION,
                promoted_household_id="", promoted_at=None,
            )
            stages.append(stage)

        response = self._client(django_user_model).post(
            self.URL, {"stage_ids": [s.id for s in stages], "reason": "x"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["succeeded"] == 3
        assert response.data["skipped"] == 0

    def test_a_wrong_state_is_still_a_plain_skip(
        self, django_user_model, geo, walkin_connector,
    ):
        """Widening the catch must not turn an ordinary refusal into an
        exception report."""
        stage = submit_walk_in_capture(_payload(geo, surname="Wrong"), actor="op")
        StageRecord.objects.filter(pk=stage.pk).update(
            state=StageRecordState.QUARANTINED,
        )
        response = self._client(django_user_model).post(
            self.URL, {"stage_ids": [stage.id], "reason": "x"}, format="json",
        )
        detail = response.data["results"][0]["detail"]
        assert "not pending_promotion" in detail
        assert "Error" not in detail
