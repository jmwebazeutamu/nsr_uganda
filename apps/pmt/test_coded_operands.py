"""A PMT model cannot activate naming codes the questionnaire lacks.

The defect these cover is silent by construction: `_h_membership`
returns 0.0 for a code that matches nothing, so a model with a wrong
code scores every household zero on that variable and raises nothing.
The seeded v1 does exactly this — see `test_the_real_v1_defect_is_caught`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.intake.models import FormQuestion, FormSection, FormVersion
from apps.pmt.coded_operands import report_for_variables
from apps.pmt.models import ModelStatus, PMTModelVersion
from apps.pmt.services import PMTApprovalError, activate_model_version
from apps.pmt.test_helpers import canonical_band_cutoffs
from apps.reference_data.models import (
    ChoiceList,
    ChoiceListStatus,
    ChoiceOption,
)


@pytest.fixture
def coded_question(db):
    """A questionnaire field bound to a two-option list, codes padded.

    Padded on purpose: the real defect is `"4"` sent to a list that
    spells it `"04"`.
    """
    choice_list = ChoiceList.objects.create(
        list_name="test_grade", version=1,
        status=ChoiceListStatus.ACTIVE, author="fixture",
    )
    ChoiceOption.objects.create(
        choice_list=choice_list, code="04", label="P1",
        status=ChoiceOption.Status.ACTIVE,
    )
    ChoiceOption.objects.create(
        choice_list=choice_list, code="10", label="P7",
        status=ChoiceOption.Status.ACTIVE,
    )
    ChoiceOption.objects.create(
        choice_list=choice_list, code="98", label="Retired option",
        status=ChoiceOption.Status.DEPRECATED,
    )
    version = FormVersion.objects.create(
        version=90_001, name="Test instrument", status="draft",
        author="fixture", effective_from=date(2026, 1, 1),
    )
    section = FormSection.objects.create(
        form_version=version, code="T", name="test", label="Test", order=1,
    )
    return FormQuestion.objects.create(
        section=section, name="t1_grade", label="Grade",
        type="select_one", choice_list_ref=choice_list,
        canonical_field="test_grade_field",
        payload_aliases=["test_grade_field", "grade_alias"],
    )


def _membership(name, path, operand):
    return {
        "name": name, "weight": 0.1,
        "feature": {"type": "membership", "path": path, "operand": operand},
    }


# ── the canonical path ────────────────────────────────────────────────

def test_codes_on_the_questions_list_are_accepted(coded_question):
    report = report_for_variables(
        [_membership("ok", "member.test_grade_field", ["04", "10"])],
    )
    assert report.errors == []
    assert report.unresolved == []


def test_a_payload_alias_resolves_to_the_same_question(coded_question):
    """`payload_aliases` is part of the canonical record, so a path
    spelled with one must reach the same list.

    Asserted through a BAD code, not a good one. A good code passing
    proves nothing here: if the alias failed to resolve, the field would
    fall through to `unresolved` and `errors` would be empty either way.
    The only proof that the alias reached the list is that the list
    rejected something.
    """
    good = report_for_variables(
        [_membership("ok", "member.grade_alias", ["04"])],
    )
    assert good.errors == []
    assert good.unresolved == [], "the alias did not reach a question"

    bad = report_for_variables(
        [_membership("bad", "member.grade_alias", ["4"])],
    )
    assert len(bad.errors) == 1
    assert "test_grade" in bad.errors[0]


def test_a_field_with_no_choice_list_is_not_a_code_test(coded_question):
    FormQuestion.objects.create(
        section=coded_question.section, name="t2_rooms", label="Rooms",
        type="integer", canonical_field="rooms_counted",
    )
    report = report_for_variables(
        [{"name": "rooms", "weight": 1.0,
          "feature": {"type": "comparison", "path": "dwelling.rooms_counted",
                      "operator": "gt", "operand": 3}}],
    )
    assert report.errors == []
    assert report.unresolved == []


def test_the_legacy_variable_shape_names_no_codes(coded_question):
    report = report_for_variables(
        [{"variable": "household.dwelling.floor_material",
          "weight": 0.0, "transform": "identity"}],
    )
    assert report.errors == []


# ── the failure case ──────────────────────────────────────────────────

def test_an_unpadded_code_is_rejected(coded_question):
    """`"4"` against a list that spells it `"04"`. This is the whole
    defect: it is not a typo the evaluator would ever complain about."""
    report = report_for_variables(
        [_membership("unpadded", "member.test_grade_field", ["4"])],
    )
    assert len(report.errors) == 1
    assert "'4'" in report.errors[0]
    assert "test_grade" in report.errors[0]
    # The message has to be actionable — it must show what IS valid.
    assert "04" in report.errors[0]


def test_a_deprecated_option_is_not_an_active_code(coded_question):
    """Deprecated options stay readable for historical records but are
    not something a new model may score on."""
    report = report_for_variables(
        [_membership("deprecated", "member.test_grade_field", ["98"])],
    )
    assert len(report.errors) == 1
    assert "'98'" in report.errors[0]


def test_only_the_offending_codes_are_named(coded_question):
    report = report_for_variables(
        [_membership("mixed", "member.test_grade_field", ["04", "4", "10"])],
    )
    assert len(report.errors) == 1
    assert "'4'" in report.errors[0]
    assert "'04'" not in report.errors[0]


def test_collection_filter_codes_are_checked_too(coded_question):
    """`presence_in_collection` hides its codes in `filter`, not
    `operand` — the asset variables are all this shape."""
    report = report_for_variables(
        [{"name": "owns", "weight": 0.2,
          "feature": {"type": "presence_in_collection", "collection": "x",
                      "field": "count", "operator": "gt", "operand": 0,
                      "filter": {"test_grade_field__in": ["04", "nope"]}}}],
    )
    assert len(report.errors) == 1
    assert "'nope'" in report.errors[0]
    # `operand: 0` there is a count, not a code, and must not be flagged.
    assert "'0'" not in report.errors[0]


def test_a_magnitude_lookup_is_not_a_code_test(coded_question):
    report = report_for_variables(
        [{"name": "young", "weight": 0.2,
          "feature": {"type": "share_where", "collection": "members",
                      "filter": {"test_grade_field__lt": 15}}}],
    )
    assert report.errors == []


def test_an_unbound_field_is_reported_but_not_fatal(db):
    """No canonical question for the field: the binding is missing, which
    is reported rather than guessed at from another map."""
    report = report_for_variables(
        [{"name": "owns_tv", "weight": 0.2,
          "feature": {"type": "presence_in_collection", "collection": "assets",
                      "field": "count", "operator": "gt", "operand": 0,
                      "filter": {"asset_type__in": ["tv", "television"]}}}],
    )
    assert report.errors == []
    assert len(report.unresolved) == 1
    assert "asset_type" in report.unresolved[0]


# ── the gate ──────────────────────────────────────────────────────────

def _draft(variables):
    return PMTModelVersion.objects.create(
        version=90_001, status=ModelStatus.DRAFT, author="analyst",
        intercept=Decimal("0"), variables=variables,
        band_strategy="threshold", band_cutoffs=canonical_band_cutoffs(),
    )


def test_activation_refuses_a_model_with_a_bad_code(coded_question):
    version = _draft([_membership("bad", "member.test_grade_field", ["4"])])
    with pytest.raises(PMTApprovalError) as exc:
        activate_model_version(version, approver="approver")
    assert "does not carry" in str(exc.value)
    version.refresh_from_db()
    assert version.status == ModelStatus.DRAFT


def test_activation_allows_a_model_whose_codes_check_out(coded_question):
    version = _draft([_membership("good", "member.test_grade_field", ["04"])])
    activate_model_version(version, approver="approver")
    version.refresh_from_db()
    assert version.status == ModelStatus.ACTIVE


def test_an_unresolved_binding_does_not_block_activation(db):
    """Reported, not fatal — otherwise no model could activate until the
    questionnaire covers every ORM filter field."""
    version = _draft(
        [{"name": "owns_tv", "weight": 0.2,
          "feature": {"type": "presence_in_collection", "collection": "assets",
                      "field": "count", "operator": "gt", "operand": 0,
                      "filter": {"asset_type__in": ["tv"]}}}],
    )
    activate_model_version(version, approver="approver")
    version.refresh_from_db()
    assert version.status == ModelStatus.ACTIVE


# ── the model actually in production ──────────────────────────────────

@pytest.mark.django_db
def test_the_real_v1_defect_is_caught():
    """The seeded v1 asks `education_level` for `"4"` and `"8"`, which it
    spells `"04"` (P1) and `"08"` (P5). Both variables match nothing and
    collapse onto `head_edu_tertiary`, scoring P7-and-secondary heads as
    having no education.

    The binding is created here rather than assumed: the instrument is
    loaded by `manage.py load_instrument`, not by a migration, so the
    test database has no FormQuestion rows at all (see
    `test_the_gate_is_inert_without_the_questionnaire`). This pins the
    real model's real codes against the real seeded list.

    If this starts failing because the errors are gone, v1 was corrected
    — verify that, then delete this test.
    """
    version = PMTModelVersion.objects.filter(status=ModelStatus.ACTIVE).first()
    if version is None:
        pytest.skip("no active PMT model seeded in this database")
    education = ChoiceList.objects.filter(
        list_name="education_level", status=ChoiceListStatus.ACTIVE,
    ).first()
    if education is None:
        pytest.skip("education_level is not seeded in this database")

    form = FormVersion.objects.create(
        version=90_002, name="Binding under test", status="draft",
        author="fixture", effective_from=date(2026, 1, 1),
    )
    section = FormSection.objects.create(
        form_version=form, code="E", name="education", label="Education",
        order=1,
    )
    FormQuestion.objects.create(
        section=section, name="e4_highest_grade", label="Highest grade",
        type="select_one", choice_list_ref=education,
        canonical_field="highest_grade",
    )

    report = report_for_variables(version.variables)
    offenders = " ".join(report.errors)
    assert "head_edu_completed_primary" in offenders
    assert "head_edu_secondary" in offenders
    # Tertiary is correct today and must not be swept up with them.
    assert "head_edu_tertiary" not in offenders


@pytest.mark.django_db
def test_the_gate_is_inert_without_the_questionnaire():
    """A limitation worth stating out loud, not a feature.

    `FormQuestion` is populated by `manage.py load_instrument`, so an
    environment that has not run it has no canonical bindings and every
    coded value reports as unresolved rather than checked. The gate
    cannot be stricter than the record it reads. ADR-0041 records this
    as the open risk; seeding the instrument is what closes it.
    """
    assert FormQuestion.objects.count() == 0, (
        "the instrument is now seeded in the test database — good; "
        "this test has served its purpose and should be replaced by one "
        "asserting the gate is live"
    )
    version = PMTModelVersion.objects.filter(status=ModelStatus.ACTIVE).first()
    if version is None:
        pytest.skip("no active PMT model seeded in this database")
    report = report_for_variables(version.variables)
    assert report.errors == []
    assert report.unresolved, "expected every coded value to be unresolved"
