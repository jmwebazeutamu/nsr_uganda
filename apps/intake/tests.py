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


# --- US-117b: builder UI (tree + reorder + validate) -----------------------

class TestQuestionnaireBuilderUI:
    """The change_form template renders the tree pane + the
    expression-validator panel when QUESTIONNAIRE_EDITOR_V2 is on.
    Falls back to the default admin form when off."""

    def _staff_client(self, db, django_user_model):
        from django.test import Client
        u = django_user_model.objects.create_user(
            username="qb-staff", password="p",
            is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        return c

    def _seeded_fv(self, db):
        from apps.intake.models import FormQuestion, FormSection, FormVersion
        fv = FormVersion.objects.create(
            version=3000, name="qb-test",
            effective_from=date(2026, 1, 1),
            status="draft", author="alice",
        )
        a = FormSection.objects.create(
            form_version=fv, code="A", name="ident", label="Identification", order=1,
        )
        b = FormSection.objects.create(
            form_version=fv, code="B", name="status", label="Survey status", order=2,
        )
        q1 = FormQuestion.objects.create(
            section=a, name="full_name", label="Full name",
            type="text", required=True, order_in_section=1,
        )
        q2 = FormQuestion.objects.create(
            section=a, name="phone", label="Phone",
            type="text", required=False, order_in_section=2,
        )
        return fv, a, b, q1, q2

    def test_change_form_renders_tree_when_flag_on(
        self, db, django_user_model, settings,
    ):
        settings.QUESTIONNAIRE_EDITOR_V2 = True
        fv, a, b, q1, q2 = self._seeded_fv(db)
        r = self._staff_client(db, django_user_model).get(
            f"/admin/intake/formversion/{fv.id}/change/",
        )
        assert r.status_code == 200
        body = r.content.decode()
        # Tree pane present.
        assert 'id="qe-tree"' in body
        # Both sections rendered (by code).
        assert "Identification" in body and "Survey status" in body
        # Both questions rendered (by name).
        assert "full_name" in body and "phone" in body
        # Validator panel present.
        assert 'id="qe-validate"' in body

    def test_change_form_omits_tree_when_flag_off(
        self, db, django_user_model, settings,
    ):
        settings.QUESTIONNAIRE_EDITOR_V2 = False
        fv, *_ = self._seeded_fv(db)
        r = self._staff_client(db, django_user_model).get(
            f"/admin/intake/formversion/{fv.id}/change/",
        )
        assert r.status_code == 200
        body = r.content.decode()
        assert 'id="qe-tree"' not in body
        assert 'id="qe-validate"' not in body

    def test_reorder_section_swaps_order(self, db, django_user_model):
        import json as _json
        fv, a, b, *_ = self._seeded_fv(db)
        # Initially: a.order=1, b.order=2. Move b up → swap.
        c = self._staff_client(db, django_user_model)
        r = c.post(
            f"/admin/intake/formversion/_us117b/reorder-section/{b.id}/",
            data=_json.dumps({"direction": "up"}),
            content_type="application/json",
        )
        assert r.status_code == 200
        a.refresh_from_db()
        b.refresh_from_db()
        assert b.order < a.order

    def test_reorder_section_boundary_no_op(self, db, django_user_model):
        import json as _json
        fv, a, *_ = self._seeded_fv(db)
        c = self._staff_client(db, django_user_model)
        r = c.post(
            f"/admin/intake/formversion/_us117b/reorder-section/{a.id}/",
            data=_json.dumps({"direction": "up"}),
            content_type="application/json",
        )
        assert r.status_code == 200
        body = r.json()
        assert body["moved"] is False

    def test_reorder_question_swaps_within_section(self, db, django_user_model):
        import json as _json
        fv, a, b, q1, q2 = self._seeded_fv(db)
        c = self._staff_client(db, django_user_model)
        # q2 (order=2) moves up over q1 (order=1).
        r = c.post(
            f"/admin/intake/formversion/_us117b/reorder-question/{q2.id}/",
            data=_json.dumps({"direction": "up"}),
            content_type="application/json",
        )
        assert r.status_code == 200
        q1.refresh_from_db()
        q2.refresh_from_db()
        assert q2.order_in_section < q1.order_in_section

    def test_validate_expression_ok(self, db, django_user_model):
        import json as _json
        c = self._staff_client(db, django_user_model)
        r = c.post(
            "/admin/intake/formversion/_us117b/validate-expression/",
            data=_json.dumps({
                "expression": {"field": "age", "op": "between",
                               "value": [0, 120]},
                "sample_record": {"age": 25},
            }),
            content_type="application/json",
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["result"] is True

    def test_validate_expression_dsl_error(self, db, django_user_model):
        import json as _json
        c = self._staff_client(db, django_user_model)
        r = c.post(
            "/admin/intake/formversion/_us117b/validate-expression/",
            data=_json.dumps({
                "expression": {"op": "no_such_op", "field": "x"},
                "sample_record": {},
            }),
            content_type="application/json",
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert "no_such_op" in body["error"]

    def test_validate_rejects_non_dict_expression(self, db, django_user_model):
        import json as _json
        c = self._staff_client(db, django_user_model)
        r = c.post(
            "/admin/intake/formversion/_us117b/validate-expression/",
            data=_json.dumps({"expression": "not-a-dict"}),
            content_type="application/json",
        )
        assert r.status_code == 400


# --- US-120: legacy questionnaire import -----------------------------------

class TestLegacyQuestionnaireImport:
    """The scripts/import_legacy_questionnaire.py end-to-end check.

    Reads k-forms/build_nsr_xlsform.py via exec (Workbook.save
    monkey-patched no-op) and builds FormVersion v1. Re-running is
    idempotent — section/question rows upsert on natural keys.
    """

    @pytest.fixture
    def _seed_choice_lists(self, db):
        """Migration-applied seed isn't visible in TransactionTestCase-style
        tests — call into the migration data loader directly here so the
        importer's ChoiceList look-ups resolve."""
        import json
        from datetime import date as _d
        from pathlib import Path

        from apps.reference_data.models import ChoiceList, ChoiceOption
        path = (
            Path(__file__).resolve().parent.parent / "reference_data"
            / "seeds" / "choice_lists_v1.json"
        )
        for name, options in json.loads(path.read_text()).items():
            cl, _ = ChoiceList.objects.get_or_create(
                list_name=name, version=1,
                defaults={"effective_from": _d(2026, 1, 1),
                          "status": "active",
                          "author": "system-migration",
                          "approved_by": "system-migration"},
            )
            for so, opt in enumerate(options, start=1):
                ChoiceOption.objects.get_or_create(
                    choice_list=cl, code=opt["code"], language="en",
                    defaults={"label": opt["label"], "sort_order": so},
                )

    def test_import_creates_form_version_one(self, _seed_choice_lists):
        from scripts.import_legacy_questionnaire import main

        from apps.intake.models import FormVersion
        result = main()
        fv = FormVersion.objects.get(version=1)
        assert fv.id == result["form_version_id"]
        assert fv.status == "active"
        assert fv.is_active is True
        # At least the 9 top-level sections we know about land.
        assert fv.sections.count() >= 9

    def test_import_links_choice_list_refs(self, _seed_choice_lists):
        from scripts.import_legacy_questionnaire import main

        from apps.intake.models import FormQuestion
        main()
        # The legacy script names the C2 column `c2_relationship`.
        q = FormQuestion.objects.filter(name="c2_relationship").first()
        assert q is not None, "c2_relationship question not imported"
        assert q.choice_list_ref is not None
        assert q.choice_list_ref.list_name == "relationship"
        # And confirm at least one select_one question landed with a
        # resolved ChoiceList ref overall.
        with_refs = FormQuestion.objects.filter(
            choice_list_ref__isnull=False,
        ).count()
        assert with_refs >= 20  # legacy form has dozens of selects

    def test_import_is_idempotent(self, _seed_choice_lists):
        from scripts.import_legacy_questionnaire import main

        from apps.intake.models import FormQuestion, FormSection
        main()
        sections_before = FormSection.objects.count()
        questions_before = FormQuestion.objects.count()
        main()
        # Re-run rebuilds in place — counts stay stable, no orphan
        # rows from the prior import.
        assert FormSection.objects.count() == sections_before
        assert FormQuestion.objects.count() == questions_before

    def test_import_preserves_xlsform_metadata_types(self, _seed_choice_lists):
        """US-120b regression: an earlier importer mapped any unknown
        legacy type (notably `time`) to END_GROUP via a misguided
        fallback. The `a15_start_time` row was the canary."""
        from scripts.import_legacy_questionnaire import main

        from apps.intake.models import FormQuestion
        main()
        q = FormQuestion.objects.get(name="a15_start_time")
        assert q.type == "time", (
            f"a15_start_time should import as type=time, got {q.type!r} — "
            "QuestionType enum is likely missing `time` again."
        )

    def test_import_attaches_pre_section_questions_to_prior_section(
        self, _seed_choice_lists,
    ):
        """US-120b regression: `hh_size` sits at the top level in the
        legacy script (between sections B and C) and was dropped on
        import. It now attaches to the most-recently-closed section
        so the begin_repeat that follows can reference it."""
        from scripts.import_legacy_questionnaire import main

        from apps.intake.models import FormQuestion
        main()
        q = FormQuestion.objects.get(name="hh_size")
        assert q.type == "integer"
        assert q.section.name == "survey_status"

    def test_import_marks_household_roster_as_repeat(self, _seed_choice_lists):
        """US-120b regression: the household_members section is a
        begin_repeat in the legacy script. The importer must capture
        its repeat_count attribute on the FormSection so the export
        round-trip re-emits a begin_repeat (not begin_group)."""
        from scripts.import_legacy_questionnaire import main

        from apps.intake.models import FormSection
        main()
        sec = FormSection.objects.get(name="household_members")
        assert sec.repeat_count == "${hh_size}", (
            f"household_members.repeat_count should be ${{hh_size}}, "
            f"got {sec.repeat_count!r}"
        )


# --- US-118: XLSForm export from FormVersion -------------------------------

class TestXlsformExport:
    """Round-trip: import legacy script → export → bytes are a valid
    XLSForm with the expected sheets/columns/rows. Tests pin the
    structural contract; not every row is asserted."""

    @pytest.fixture
    def _seeded_form(self, db):
        import json
        from datetime import date as _d
        from pathlib import Path

        from scripts.import_legacy_questionnaire import main as import_main

        from apps.intake.models import FormVersion
        from apps.reference_data.models import ChoiceList, ChoiceOption
        path = (
            Path(__file__).resolve().parent.parent / "reference_data"
            / "seeds" / "choice_lists_v1.json"
        )
        for name, options in json.loads(path.read_text()).items():
            cl, _ = ChoiceList.objects.get_or_create(
                list_name=name, version=1,
                defaults={"effective_from": _d(2026, 1, 1),
                          "status": "active",
                          "author": "system-migration",
                          "approved_by": "system-migration"},
            )
            for so, opt in enumerate(options, start=1):
                ChoiceOption.objects.get_or_create(
                    choice_list=cl, code=opt["code"], language="en",
                    defaults={"label": opt["label"], "sort_order": so},
                )
        import_main()
        return FormVersion.objects.get(version=1)

    def test_export_returns_xlsx_bytes(self, _seeded_form):
        from apps.intake.xlsform_export import export_to_xlsx
        out = export_to_xlsx(_seeded_form)
        assert isinstance(out, bytes)
        assert out[:2] == b"PK"  # ZIP magic — .xlsx is a zip

    def test_export_has_required_sheets(self, _seeded_form):
        import io

        import openpyxl

        from apps.intake.xlsform_export import export_to_xlsx
        wb = openpyxl.load_workbook(io.BytesIO(export_to_xlsx(_seeded_form)))
        assert {"survey", "choices", "settings"}.issubset(set(wb.sheetnames))

    def test_export_survey_sheet_has_questions(self, _seeded_form):
        import io

        import openpyxl

        from apps.intake.xlsform_export import export_to_xlsx
        wb = openpyxl.load_workbook(io.BytesIO(export_to_xlsx(_seeded_form)))
        ws = wb["survey"]
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        assert len(rows) >= 100  # 184 questions + structural markers
        types = {r[0] for r in rows if r and r[0]}
        assert "begin_group" in types
        assert any(t and t.startswith("select_one") for t in types)

    def test_export_choices_sheet_has_options(self, _seeded_form):
        import io

        import openpyxl

        from apps.intake.xlsform_export import export_to_xlsx
        wb = openpyxl.load_workbook(io.BytesIO(export_to_xlsx(_seeded_form)))
        ws = wb["choices"]
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        assert len(rows) >= 100
        names = {r[0] for r in rows if r and r[0]}
        assert "relationship" in names and "marital_status" in names

    def test_export_settings_sheet_has_form_metadata(self, _seeded_form):
        import io

        import openpyxl

        from apps.intake.xlsform_export import export_to_xlsx
        wb = openpyxl.load_workbook(io.BytesIO(export_to_xlsx(_seeded_form)))
        ws = wb["settings"]
        rows = list(ws.iter_rows(min_row=1, values_only=True))
        assert len(rows) >= 2
        header = {h for h in rows[0] if h}
        assert {"form_title", "form_id", "version"}.issubset(header)

    def test_admin_export_action_returns_xlsx(
        self, _seeded_form, db, django_user_model,
    ):
        from django.test import Client
        u = django_user_model.objects.create_user(
            username="xform-staff", password="p",
            is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        r = c.get(
            f"/admin/intake/formversion/_us118/export-xlsform/{_seeded_form.id}/",
        )
        assert r.status_code == 200
        assert "spreadsheetml" in r["Content-Type"]
        assert r.content[:2] == b"PK"

    def test_export_settings_uses_kobo_valid_values(self, _seeded_form):
        """US-118b regression: Kobo's web preview rejects forms whose
        settings sheet uses `default_language=en` (it expects the
        full language name) or `style=pages` (legacy used theme-grid).
        Also pins the form_id slug + datestamp version format."""
        import io

        import openpyxl

        from apps.intake.xlsform_export import export_to_xlsx
        wb = openpyxl.load_workbook(io.BytesIO(export_to_xlsx(_seeded_form)))
        ws = wb["settings"]
        rows = list(ws.iter_rows(min_row=1, values_only=True))
        header = list(rows[0])
        values = dict(zip(header, rows[1], strict=False))
        assert values["default_language"] == "English"
        assert values["style"] == "theme-grid"
        # form_id should be a slug, not the literal FormVersion.name
        # (which contains spaces).
        assert " " not in values["form_id"]
        # Version stamp is YYYYMMDDHHMM, not just the int version.
        assert len(values["version"]) == 12 and values["version"].isdigit()

    def test_export_prepends_top_level_metadata_rows(self, _seeded_form):
        """US-118b regression: every XLSForm needs start/end/today/
        deviceid/username rows at the top so Kobo can stamp submission
        metadata. The legacy file had them; ours didn't."""
        import io

        import openpyxl

        from apps.intake.xlsform_export import export_to_xlsx
        wb = openpyxl.load_workbook(io.BytesIO(export_to_xlsx(_seeded_form)))
        ws = wb["survey"]
        rows = list(ws.iter_rows(min_row=2, max_row=6, values_only=True))
        types = [r[0] for r in rows]
        assert types == ["start", "end", "today", "deviceid", "username"]

    def test_export_emits_begin_repeat_for_roster_section(self, _seeded_form):
        """US-118b regression: household_members is a roster — exported
        as begin_repeat with repeat_count, not begin_group. Without
        this, every form rendered in Kobo collapses the roster into a
        non-iterable group and only one member can be entered."""
        import io

        import openpyxl

        from apps.intake.xlsform_export import export_to_xlsx
        wb = openpyxl.load_workbook(io.BytesIO(export_to_xlsx(_seeded_form)))
        rows = list(wb["survey"].iter_rows(min_row=1, values_only=True))
        header = rows[0]
        type_col = header.index("type")
        name_col = header.index("name")
        repeat_col = header.index("repeat_count")
        roster_open = next(
            r for r in rows[1:]
            if r[type_col] == "begin_repeat" and r[name_col] == "household_members"
        )
        assert roster_open[repeat_col] == "${hh_size}"
        # And its closer is end_repeat (not end_group).
        roster_close = next(
            r for r in rows[1:]
            if r[type_col] == "end_repeat" and r[name_col] == "household_members_end"
        )
        assert roster_close is not None

    def test_export_falls_back_to_text_for_select_without_choice_list(
        self, _seeded_form,
    ):
        """US-118b regression: the geo selects (a0_region etc.) lack
        a seeded ChoiceList in the test fixture. A bare `select_one`
        row with no list name fails Kobo's "Survey information not
        complete" validation. We fall back to `text` with a hint
        annotation so the export still loads."""
        import io

        import openpyxl

        from apps.intake.xlsform_export import export_to_xlsx
        wb = openpyxl.load_workbook(io.BytesIO(export_to_xlsx(_seeded_form)))
        rows = list(wb["survey"].iter_rows(min_row=1, values_only=True))
        header = rows[0]
        type_col = header.index("type")
        name_col = header.index("name")
        hint_col = header.index("hint")
        region_row = next(r for r in rows[1:] if r[name_col] == "a0_region")
        assert region_row[type_col] == "text"
        assert "missing choice list" in (region_row[hint_col] or "").lower()
        # No row should be a bare select_one / select_multiple without
        # a list name attached.
        for r in rows[1:]:
            assert r[type_col] not in ("select_one", "select_multiple"), (
                f"row {r[name_col]} has bare {r[type_col]!r} — Kobo will reject"
            )


# --- US-119: rule-pack sync on FormVersion activation ----------------------

class TestRulePackSync:
    """When a FormVersion activates, fan out atomically to DAT-DQA:
    one DqaRule per FormQuestion that has a constraint or skip-logic
    DSL. Idempotent — running sync again upserts (rule_id, version).
    """

    @pytest.fixture
    def _fv_with_constraints(self, db):
        from apps.intake.models import (
            FormConstraint,
            FormQuestion,
            FormSection,
            FormVersion,
        )
        fv = FormVersion.objects.create(
            version=3001, name="sync-test",
            effective_from=date(2026, 1, 1),
            status="pending_approval", author="alice",
        )
        s = FormSection.objects.create(
            form_version=fv, code="C", name="roster", label="Roster", order=1,
        )
        q_age = FormQuestion.objects.create(
            section=s, name="age_years", label="Age", type="integer",
            constraint_expression=". >= 0 and . <= 120",
            constraint_message="age must be 0-120",
            order_in_section=1,
        )
        FormConstraint.objects.create(
            question=q_age,
            dsl={"field": "age_years", "op": "between", "value": [0, 120]},
            message="age must be 0-120",
        )
        q_phone = FormQuestion.objects.create(
            section=s, name="phone", label="Phone", type="text",
            constraint_expression="regex(., '^[+0-9]{9,15}$')",
            constraint_message="phone must be E.164-ish",
            order_in_section=2,
        )
        FormConstraint.objects.create(
            question=q_phone,
            dsl={"field": "phone", "op": "regex", "value": r"^\+[0-9]{9,15}$"},
            message="phone must be E.164-ish",
        )
        # A question with NO constraint — shouldn't produce a rule.
        FormQuestion.objects.create(
            section=s, name="full_name", label="Full name", type="text",
            order_in_section=3,
        )
        return fv

    def test_sync_creates_one_rule_per_constraint(self, _fv_with_constraints):
        from apps.dqa.models import DqaRule
        from apps.intake.rule_pack_sync import sync_rule_pack
        before = DqaRule.objects.count()
        report = sync_rule_pack(_fv_with_constraints, actor="alice")
        after = DqaRule.objects.count()
        assert after == before + 2
        # Returned summary lists what was created.
        assert report["created"] == 2
        assert report["updated"] == 0
        # Naming convention: AC-FORM-<version>-<question_name>
        rule_ids = set(DqaRule.objects.values_list("rule_id", flat=True))
        assert "AC-FORM-3001-age_years" in rule_ids
        assert "AC-FORM-3001-phone" in rule_ids

    def test_sync_links_dsl_into_rule_expression(self, _fv_with_constraints):
        from apps.dqa.models import DqaRule
        from apps.intake.rule_pack_sync import sync_rule_pack
        sync_rule_pack(_fv_with_constraints, actor="alice")
        rule = DqaRule.objects.get(rule_id="AC-FORM-3001-age_years")
        assert rule.expression == {
            "field": "age_years", "op": "between", "value": [0, 120],
        }
        assert rule.error_message_template == "age must be 0-120"
        assert rule.applicability_filter == {
            "entity": "member", "form_version": 3001,
        }

    def test_sync_is_idempotent(self, _fv_with_constraints):
        from apps.dqa.models import DqaRule
        from apps.intake.rule_pack_sync import sync_rule_pack
        sync_rule_pack(_fv_with_constraints, actor="alice")
        count_after_first = DqaRule.objects.count()
        report = sync_rule_pack(_fv_with_constraints, actor="alice")
        # Second pass updates existing rules; no new rows.
        assert DqaRule.objects.count() == count_after_first
        assert report["created"] == 0
        assert report["updated"] >= 2

    def test_sync_skips_questions_without_constraint(self, _fv_with_constraints):
        from apps.dqa.models import DqaRule
        from apps.intake.rule_pack_sync import sync_rule_pack
        sync_rule_pack(_fv_with_constraints, actor="alice")
        # `full_name` has no constraint — no rule emitted.
        assert not DqaRule.objects.filter(
            rule_id="AC-FORM-3001-full_name",
        ).exists()

    def test_sync_emits_audit_event(self, _fv_with_constraints):
        from apps.intake.rule_pack_sync import sync_rule_pack
        from apps.security.models import AuditEvent
        before = AuditEvent.objects.filter(
            entity_type="intake.form_version",
            action="rule_pack_synced",
        ).count()
        sync_rule_pack(_fv_with_constraints, actor="alice")
        after = AuditEvent.objects.filter(
            entity_type="intake.form_version",
            action="rule_pack_synced",
        ).count()
        assert after == before + 1


# --- US-117d: in-admin HTML preview ----------------------------------------

class TestFormVersionPreview:
    """Preview view renders the FormVersion as HTML — sections as
    cards, questions as disabled controls + annotation strip."""

    def _staff_client(self, db, django_user_model):
        from django.test import Client
        u = django_user_model.objects.create_user(
            username="prev-staff", password="p",
            is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        return c

    @pytest.fixture
    def _seeded_form(self, db):
        from apps.intake.models import (
            FormQuestion,
            FormSection,
            FormVersion,
        )
        from apps.reference_data.models import ChoiceList, ChoiceOption
        fv = FormVersion.objects.create(
            version=4000, name="preview-test",
            effective_from=date(2026, 1, 1),
            status="draft", author="alice",
        )
        # ChoiceList for a select_one question.
        cl = ChoiceList.objects.create(
            list_name="preview_sex", version=1,
            effective_from=date(2026, 1, 1),
            status="active", author="alice", approved_by="bob",
        )
        ChoiceOption.objects.create(
            choice_list=cl, code="M", label="Male",
            language="en", sort_order=1,
        )
        ChoiceOption.objects.create(
            choice_list=cl, code="F", label="Female",
            language="en", sort_order=2,
        )
        # Section + question variety.
        a = FormSection.objects.create(
            form_version=fv, code="A", name="ident", label="Identification", order=1,
        )
        FormQuestion.objects.create(
            section=a, name="full_name", label="Full name", type="text",
            required=True, hint="Surname, then first name", order_in_section=1,
        )
        FormQuestion.objects.create(
            section=a, name="sex", label="Sex", type="select_one",
            choice_list_ref=cl, required=True, order_in_section=2,
        )
        FormQuestion.objects.create(
            section=a, name="age_years", label="Age in years", type="integer",
            constraint_expression=". >= 0 and . <= 120",
            constraint_message="age must be 0-120",
            order_in_section=3,
        )
        FormQuestion.objects.create(
            section=a, name="age_hidden", label="Hidden if no age",
            type="text", relevant_expression="${age_years} != ''",
            order_in_section=4,
        )
        FormQuestion.objects.create(
            section=a, name="gps", label="GPS", type="geopoint",
            order_in_section=5,
        )
        return fv

    def test_preview_returns_200(self, _seeded_form, db, django_user_model):
        c = self._staff_client(db, django_user_model)
        r = c.get(f"/admin/intake/formversion/_us117b/preview/{_seeded_form.id}/")
        assert r.status_code == 200

    def test_preview_renders_section_and_questions(
        self, _seeded_form, db, django_user_model,
    ):
        c = self._staff_client(db, django_user_model)
        r = c.get(f"/admin/intake/formversion/_us117b/preview/{_seeded_form.id}/")
        body = r.content.decode()
        # Section heading + question labels.
        assert "Identification" in body
        assert "Full name" in body
        assert "Age in years" in body
        # Required marker.
        assert "*" in body
        # Hint text rendered.
        assert "Surname, then first name" in body
        # select_one renders the choice list options.
        assert "Male" in body and "Female" in body
        # geopoint placeholder shown.
        assert "latitude" in body or "GPS" in body
        # Annotation strip surfaces relevant + constraint.
        assert "relevant:" in body
        assert "constraint:" in body

    def test_preview_has_download_link(
        self, _seeded_form, db, django_user_model,
    ):
        c = self._staff_client(db, django_user_model)
        r = c.get(f"/admin/intake/formversion/_us117b/preview/{_seeded_form.id}/")
        body = r.content.decode()
        # Header has the XLSForm download link + Kobo external link.
        assert "Download XLSForm" in body
        assert f"export-xlsform/{_seeded_form.id}/" in body
        assert "kobotoolbox" in body

    def test_change_form_links_to_preview_and_download(
        self, _seeded_form, db, django_user_model, settings,
    ):
        settings.QUESTIONNAIRE_EDITOR_V2 = True
        c = self._staff_client(db, django_user_model)
        r = c.get(f"/admin/intake/formversion/{_seeded_form.id}/change/")
        body = r.content.decode()
        # The action bar in change_form template wires the two links.
        assert "Preview form" in body
        assert "Download XLSForm" in body

    def test_preview_accepts_version_number_as_fallback(
        self, _seeded_form, db, django_user_model,
    ):
        """`/preview/<version>/` works as a fallback for operators
        who type the URL by hand — FormVersion has ULID primary
        keys, but `1` is what they see on the changelist."""
        c = self._staff_client(db, django_user_model)
        # _seeded_form has version=4000; lookup by version number
        # resolves to the same row.
        r = c.get(
            f"/admin/intake/formversion/_us117b/preview/{_seeded_form.version}/",
        )
        assert r.status_code == 200
        body = r.content.decode()
        assert "Identification" in body

    def test_preview_404_on_unknown_id(self, db, django_user_model):
        c = self._staff_client(db, django_user_model)
        r = c.get("/admin/intake/formversion/_us117b/preview/999999/")
        assert r.status_code == 404

    def test_export_accepts_version_number_as_fallback(
        self, _seeded_form, db, django_user_model,
    ):
        """Same fallback for the US-118 download URL."""
        c = self._staff_client(db, django_user_model)
        r = c.get(
            f"/admin/intake/formversion/_us118/export-xlsform/{_seeded_form.version}/",
        )
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
