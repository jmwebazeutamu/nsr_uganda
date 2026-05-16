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


# --- US-117a: questionnaire authoring models -------------------------------

class TestFormVersionLifecycleFields:
    """The new status/author/approval_note fields landed alongside the
    child-model structure. Defaults match the DqaRule/ChoiceList pattern."""

    def test_new_form_version_defaults_to_draft(self, db):
        fv = FormVersion.objects.create(
            version=999, name="test-form",
            effective_from=date(2026, 1, 1),
        )
        assert fv.status == "draft"
        assert fv.author == ""
        assert fv.approval_note == ""
        assert fv.submitted_at is None


class TestQuestionnaireSchema:
    @pytest.fixture
    def fv(self, db):
        return FormVersion.objects.create(
            version=2026, name="nsr-questionnaire",
            effective_from=date(2026, 1, 1),
            status="draft", author="alice",
        )

    def test_section_creation(self, fv):
        from apps.intake.models import FormSection
        s = FormSection.objects.create(
            form_version=fv, code="A", name="identification",
            label="Identification particulars", order=1,
        )
        assert str(s).endswith("A: Identification particulars")
        assert s.form_version_id == fv.id

    def test_section_code_unique_per_version(self, fv):
        from django.db import IntegrityError

        from apps.intake.models import FormSection
        FormSection.objects.create(
            form_version=fv, code="A", name="ident", label="x", order=1,
        )
        with pytest.raises(IntegrityError):
            FormSection.objects.create(
                form_version=fv, code="A", name="ident2", label="y", order=2,
            )

    def test_section_name_unique_per_version(self, db):
        from django.db import IntegrityError

        from apps.intake.models import FormSection
        fv = FormVersion.objects.create(
            version=2027, name="test-form",
            effective_from=date(2026, 1, 1),
        )
        FormSection.objects.create(
            form_version=fv, code="A", name="ident", label="x",
        )
        with pytest.raises(IntegrityError):
            FormSection.objects.create(
                form_version=fv, code="B", name="ident", label="y",
            )

    def test_question_with_choice_list_ref(self, fv):
        from apps.intake.models import FormQuestion, FormSection
        from apps.reference_data.models import ChoiceList
        # Use the seeded `relationship` choice list (v=1, status=active).
        rel = ChoiceList.objects.get(list_name="relationship", version=1)
        section = FormSection.objects.create(
            form_version=fv, code="C", name="roster", label="Household roster",
        )
        q = FormQuestion.objects.create(
            section=section, name="relationship_to_head",
            label="Relationship to head", type="select_one",
            choice_list_ref=rel, required=True, order_in_section=2,
        )
        assert q.choice_list_ref == rel
        assert q.type == "select_one"
        assert q.required is True

    def test_question_name_unique_per_section(self, fv):
        from django.db import IntegrityError

        from apps.intake.models import FormQuestion, FormSection
        s = FormSection.objects.create(
            form_version=fv, code="A", name="ident", label="x",
        )
        FormQuestion.objects.create(
            section=s, name="full_name", label="Full name", type="text",
        )
        with pytest.raises(IntegrityError):
            FormQuestion.objects.create(
                section=s, name="full_name", label="dup", type="text",
            )

    def test_skip_logic_and_constraint_attach_to_question(self, fv):
        from apps.intake.models import (
            FormConstraint,
            FormQuestion,
            FormSection,
            FormSkipLogic,
        )
        s = FormSection.objects.create(
            form_version=fv, code="C", name="roster", label="x",
        )
        q = FormQuestion.objects.create(
            section=s, name="age_years", label="Age in years", type="integer",
        )
        FormSkipLogic.objects.create(
            question=q,
            dsl={"field": "age_years", "op": "is_null"},
            description="don't ask when age missing",
        )
        FormConstraint.objects.create(
            question=q,
            dsl={"field": "age_years", "op": "between", "value": [0, 120]},
            message="age must be 0-120",
        )
        assert q.skip_logic.count() == 1
        assert q.constraints.count() == 1

    def test_section_questions_in_order(self, fv):
        from apps.intake.models import FormQuestion, FormSection
        s = FormSection.objects.create(
            form_version=fv, code="A", name="ident", label="x",
        )
        FormQuestion.objects.create(
            section=s, name="b", label="b", type="text", order_in_section=2,
        )
        FormQuestion.objects.create(
            section=s, name="a", label="a", type="text", order_in_section=1,
        )
        FormQuestion.objects.create(
            section=s, name="c", label="c", type="text", order_in_section=3,
        )
        names = list(s.questions.values_list("name", flat=True))
        assert names == ["a", "b", "c"]


class TestQuestionnaireAdminSmoke:
    """The admin pages render without 500 — the v2 tree UI lands in
    US-117b; this smoke test pins the inline + changelist contract."""

    def test_form_version_changelist(self, db, django_user_model):
        from django.test import Client
        # Need at least one row for the changelist to render column
        # headers — Django omits the table on an empty list.
        FormVersion.objects.create(
            version=2029, name="changelist-test", status="active",
            effective_from=date(2026, 1, 1),
        )
        u = django_user_model.objects.create_user(
            username="qa-staff", password="p",
            is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        r = c.get("/admin/intake/formversion/")
        assert r.status_code == 200
        body = r.content.decode()
        # changelist-test row + Status column wired into list_display.
        assert "changelist-test" in body
        assert "Status" in body

    def test_form_section_admin(self, db, django_user_model):
        from django.test import Client

        from apps.intake.models import FormSection
        fv = FormVersion.objects.create(
            version=2028, name="admin-test-form",
            effective_from=date(2026, 1, 1),
        )
        FormSection.objects.create(
            form_version=fv, code="A", name="ident",
            label="Identification", order=1,
        )
        u = django_user_model.objects.create_user(
            username="qa-staff2", password="p",
            is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        r = c.get("/admin/intake/formsection/")
        assert r.status_code == 200
        assert "Identification" in r.content.decode()
