"""Intake submission tests."""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household
from apps.ingestion_hub.models import (
    Connector,
    DataProvisionAgreement,
    SourceSystem,
    SourceSystemKind,
    StageRecord,
    StageRecordState,
)
from apps.intake.models import (
    FormVersion,
    Submission,
    SubmissionResult,
    SubmissionState,
)
from apps.intake.services import IntakeError, submit_intake
from apps.reference_data.models import GeographicUnit

# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def geo(db):
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"INT-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return nodes


@pytest.fixture
def web_source_with_connector(db):
    src = SourceSystem.objects.create(code="WEB-OD", name="Web on-demand",
                                      kind=SourceSystemKind.WEB)
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-WEB-1",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    return Connector.objects.create(source_system=src, name="web-default")


@pytest.fixture
def active_form_version(db):
    return FormVersion.objects.create(
        version=1, name="NSR Questionnaire", schema={"sections": ["id", "roster"]},
        is_active=True, effective_from=date(2026, 1, 1),
    )


def _payload(geo):
    return {
        "geographic": {
            "region": geo["r"].code, "sub_region": geo["sr"].code,
            "district": geo["d"].code, "county": geo["c"].code,
            "sub_county": geo["sc"].code, "parish": geo["p"].code,
            "village": geo["v"].code,
        },
        "urban_rural": "rural",
        "address_narrative": "Test homestead",
        "gps_lat": "1.234567", "gps_lng": "33.000000", "gps_accuracy_m": "5.00",
        "members": [
            {"line_number": 1, "surname": "Okot", "first_name": "James",
             "sex": "M", "relationship_to_head": "01", "is_head": True},
        ],
    }


# --- Refusal paths ----------------------------------------------------------

class TestSubmitIntakePreconditions:
    def test_no_active_form_version_raises(self, db, web_source_with_connector, geo):
        with pytest.raises(IntakeError, match="ACTIVE FormVersion"):
            submit_intake(
                channel="web", enumerator="e1",
                canonical_payload=_payload(geo),
            )

    def test_unsupported_channel_raises(self, db, active_form_version, geo):
        with pytest.raises(IntakeError, match="no DIH connector"):
            submit_intake(
                channel="partner_mis", enumerator="e1",
                canonical_payload=_payload(geo),
            )


# --- Happy path -------------------------------------------------------------

class TestSubmitIntake:
    def test_creates_submission_with_stage_and_provisional_id(
        self, db, web_source_with_connector, active_form_version, geo,
    ):
        sub = submit_intake(
            channel="web", enumerator="e1",
            canonical_payload=_payload(geo),
            auto_process=False,  # skip orchestrator for this test
        )
        assert sub.state == SubmissionState.PENDING_QA
        assert sub.result == SubmissionResult.COMPLETED
        assert sub.stage_record_id
        assert sub.provisional_registry_id
        # Stage row exists with the same provisional id.
        stage = StageRecord.objects.get(pk=sub.stage_record_id)
        assert stage.provisional_registry_id == sub.provisional_registry_id

    def test_auto_process_fast_tracks_clean_walkin_to_promoted(
        self, db, web_source_with_connector, active_form_version, geo,
    ):
        sub = submit_intake(
            channel="web", enumerator="e1",
            canonical_payload=_payload(geo),
            auto_process=True,
        )
        stage = StageRecord.objects.get(pk=sub.stage_record_id)
        # No DQA rules + no DDUP candidates + WEB channel -> AC-DIH-FT-AUTO.
        assert stage.state == StageRecordState.PROMOTED
        assert Household.objects.filter(pk=sub.provisional_registry_id).exists()


# --- HTTP surface -----------------------------------------------------------

class TestSubmitIntakeApi:
    def test_post_creates_submission_via_drf(
        self, db, web_source_with_connector, active_form_version, geo, django_user_model,
    ):
        from rest_framework.test import APIClient
        user = django_user_model.objects.create_user(
            username="enum-1", password="p", is_superuser=True, is_staff=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        r = client.post(
            "/api/v1/intake/submissions/submit/",
            data={
                "channel": "web",
                "enumerator": "enum-1",
                "canonical_payload": _payload(geo),
                "auto_process": False,
            },
            format="json",
        )
        assert r.status_code == 200, r.content
        assert r.data["state"] == SubmissionState.PENDING_QA
        assert r.data["stage_record_id"]
        assert Submission.objects.filter(pk=r.data["id"]).exists()
