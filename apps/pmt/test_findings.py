"""A variable that carries weight and never moves a score is reported.

This is the alarm, not the explanation. It answers "has this variable
ever contributed", which is enough to stop a model shipping with a dead
term in it, and it is answerable from data the nightly snapshot already
collects. Why a variable failed is Phase 1 of
`docs/pmt_verification_scope.md`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import override_settings

from apps.pmt.findings import (
    FINDING_INSUFFICIENT_SAMPLE,
    FINDING_MISSING_DATA,
    FINDING_NEVER_FIRES,
    FINDING_OPERAND_NOT_IN_CHOICE_LIST,
    finding_for,
    findings_for_model,
    minimum_sample,
    payload_for_model,
)
from apps.pmt.models import ModelStatus, PMTModelVersion, PMTVariableInfluence
from apps.pmt.test_helpers import canonical_band_cutoffs
from apps.reference_data.models import (
    ChoiceList,
    ChoiceListStatus,
    ChoiceOption,
)


class _Row:
    """A PMTVariableInfluence-shaped stand-in for the pure classifier."""

    def __init__(self, name, weight, sample_size, nonzero_count):
        self.variable_name = name
        self.weight = Decimal(str(weight))
        self.sample_size = sample_size
        self.nonzero_count = nonzero_count
        self.missing_count = 0


# ── the classifier ────────────────────────────────────────────────────

def test_a_variable_that_never_fired_over_a_real_sample_is_reported():
    finding = finding_for(_Row("floor_material__tiles", 0.326, 400, 0))
    assert finding.code == FINDING_NEVER_FIRES
    assert finding.fire_rate == 0.0


def test_a_variable_that_fires_is_not_reported():
    finding = finding_for(_Row("sex__female", 0.13, 400, 206))
    assert finding.code == ""
    assert finding.fire_rate == pytest.approx(0.515, abs=0.001)


def test_one_firing_household_is_enough_to_clear_the_alarm():
    """The question is "has it EVER contributed", not "does it
    contribute often". A rare-but-real variable is not a defect."""
    assert finding_for(_Row("owns_car", 0.294, 400, 1)).code == ""


def test_a_small_sample_is_reported_as_too_early_to_judge():
    """A variable added yesterday has no history to be alarmed about,
    and crying wolf is how a column gets ignored."""
    finding = finding_for(_Row("new_variable", 0.2, 5, 0))
    assert finding.code == FINDING_INSUFFICIENT_SAMPLE


def test_a_zero_weight_variable_is_never_reported():
    """It cannot move a score, so whether it fires is not a defect —
    otherwise a draft full of placeholders alarms on every row."""
    assert finding_for(_Row("placeholder", 0.0, 400, 0)).code == ""


def test_a_negative_weight_still_counts_as_carrying_weight():
    """-0.128 moves a score exactly as much as +0.128."""
    assert finding_for(_Row("open_defecation", -0.128, 400, 0)).code == (
        FINDING_NEVER_FIRES
    )


def test_a_nonzero_mean_is_not_the_test():
    """`sample_mean` cannot answer this. A `direct` feature legitimately
    averages 5.0 and a `ratio` legitimately averages 0, so the question
    is whether the variable ever produced a non-zero value."""
    assert finding_for(_Row("member_count", -3.0, 400, 400)).code == ""


@override_settings(PMT_VARIABLE_FINDING_MIN_SAMPLE=1000)
def test_the_minimum_sample_is_configuration_not_a_literal():
    assert minimum_sample() == 1000
    # 400 households was enough under the default and is not now.
    assert finding_for(_Row("x", 0.3, 400, 0)).code == FINDING_INSUFFICIENT_SAMPLE


# ── every variable, not the interesting ones ──────────────────────────

@pytest.fixture
def scored_model(db):
    version = PMTModelVersion.objects.create(
        version=92_001, status=ModelStatus.ACTIVE, author="fixture",
        intercept=Decimal("0"), band_strategy="threshold",
        band_cutoffs=canonical_band_cutoffs(),
        variables=[
            {"name": "fires", "weight": 0.5,
             "feature": {"type": "direct", "path": "member_count"}},
            {"name": "dead", "weight": 0.326,
             "feature": {"type": "direct", "path": "member_count"}},
        ],
    )
    PMTVariableInfluence.objects.create(
        model_version=version, variable_name="fires",
        weight=Decimal("0.5"), sample_mean=Decimal("2"),
        influence=Decimal("1"), sample_size=400, nonzero_count=400,
    )
    PMTVariableInfluence.objects.create(
        model_version=version, variable_name="dead",
        weight=Decimal("0.326"), sample_mean=Decimal("0"),
        influence=Decimal("0"), sample_size=400, nonzero_count=0,
    )
    return version


def test_a_dead_variable_is_found_even_though_its_influence_is_zero(scored_model):
    """The regression this whole feature exists for.

    `_variables_top_payload` orders by influence and takes the top ten,
    and a variable that never fires has influence exactly 0 — so the one
    view that would show the defect is the one that structurally cannot.
    Findings must scan every variable.
    """
    reported = [f for f in findings_for_model(scored_model) if f.code]
    assert [f.variable_name for f in reported] == ["dead"]


def test_only_the_latest_influence_row_per_variable_is_read(scored_model):
    """Influence rows accumulate nightly. A variable that was dead last
    month and fires now is not a defect."""
    PMTVariableInfluence.objects.create(
        model_version=scored_model, variable_name="dead",
        weight=Decimal("0.326"), sample_mean=Decimal("1"),
        influence=Decimal("0.326"), sample_size=400, nonzero_count=12,
    )
    reported = [f for f in findings_for_model(scored_model) if f.code]
    assert reported == []


def test_the_payload_carries_a_tone_the_console_does_not_decide(scored_model):
    row = next(r for r in payload_for_model(scored_model) if r["variable"] == "dead")
    assert row["finding"] == FINDING_NEVER_FIRES
    assert row["finding_tone"] == "danger"
    assert row["sample_size"] == 400
    assert row["nonzero_count"] == 0


# ── the operand defect, which firing counts cannot see ────────────────

@pytest.fixture
def model_with_a_bad_operand(db):
    """A variable whose operand half-matches: the education defect.

    `head_edu_completed_primary` asks for "4" and 17-23. The 17-23 part
    matches, so the variable FIRES and no firing count can flag it — it
    just fires on the wrong population.
    """
    from datetime import date

    from apps.intake.models import FormQuestion, FormSection, FormVersion

    choice_list = ChoiceList.objects.create(
        list_name="find_grade", version=1,
        status=ChoiceListStatus.ACTIVE, author="fixture",
    )
    for code in ("04", "10", "17", "23"):
        ChoiceOption.objects.create(
            choice_list=choice_list, code=code, label=f"Grade {code}",
            status=ChoiceOption.Status.ACTIVE,
        )
    form = FormVersion.objects.create(
        version=92_002, name="Findings test", status="draft",
        author="fixture", effective_from=date(2026, 1, 1),
    )
    section = FormSection.objects.create(
        form_version=form, code="E", name="edu", label="Education", order=1,
    )
    FormQuestion.objects.create(
        section=section, name="e4_grade", label="Grade", type="select_one",
        choice_list_ref=choice_list, canonical_field="find_grade_field",
    )
    return PMTModelVersion.objects.create(
        version=92_003, status=ModelStatus.ACTIVE, author="fixture",
        intercept=Decimal("0"), band_strategy="threshold",
        band_cutoffs=canonical_band_cutoffs(),
        variables=[{
            "name": "half_matching", "weight": 0.099,
            "feature": {"type": "membership",
                        "path": "member.find_grade_field",
                        "operand": ["4", "17", "23"]},
        }],
    )


def test_a_half_matching_operand_is_reported_though_the_variable_fires(
    model_with_a_bad_operand,
):
    """The finding the firing count cannot produce.

    This variable has no influence row at all — it has never been
    scored — and even when it is, it will fire on the 17/23 codes. Only
    a comparison against the code list sees that "4" is not a code this
    questionnaire carries.
    """
    rows = payload_for_model(model_with_a_bad_operand)
    assert len(rows) == 1
    assert rows[0]["variable"] == "half_matching"
    assert rows[0]["finding"] == FINDING_OPERAND_NOT_IN_CHOICE_LIST
    assert rows[0]["finding_tone"] == "danger"


def test_a_broken_operand_is_reported_as_the_cause_not_as_never_fires(
    model_with_a_bad_operand,
):
    """One row per variable, naming the cause. Reporting the same
    variable twice, once as a symptom, is how a findings list stops
    being read."""
    PMTVariableInfluence.objects.create(
        model_version=model_with_a_bad_operand,
        variable_name="half_matching",
        weight=Decimal("0.099"), sample_mean=Decimal("0"),
        influence=Decimal("0"), sample_size=400, nonzero_count=0,
    )
    rows = payload_for_model(model_with_a_bad_operand)
    assert len(rows) == 1
    assert rows[0]["finding"] == FINDING_OPERAND_NOT_IN_CHOICE_LIST


# ── the vocabulary is reference data ──────────────────────────────────

@pytest.mark.django_db
def test_finding_codes_are_seeded():
    """The constants in `findings.py` are the ChoiceList's codes.

    If a code is renamed in one place and not the other, the console
    renders a blank label for a real defect — which is worse than no
    alarm, because the row is there and says nothing.
    """
    seeded = set(
        ChoiceOption.objects
        .filter(choice_list__list_name="pmt_variable_finding",
                choice_list__status=ChoiceListStatus.ACTIVE)
        .values_list("code", flat=True)
    )
    assert {
        FINDING_NEVER_FIRES,
        FINDING_INSUFFICIENT_SAMPLE,
        FINDING_OPERAND_NOT_IN_CHOICE_LIST,
    } <= seeded


@pytest.mark.django_db
def test_every_finding_tone_is_a_real_ui_tone_code():
    """The tone is a `ui_tone` code, not a colour and not a guess."""
    from apps.pmt.findings import _FINDING_TONE

    tones = set(
        ChoiceOption.objects
        .filter(choice_list__list_name="ui_tone",
                choice_list__status=ChoiceListStatus.ACTIVE)
        .values_list("code", flat=True)
    )
    if not tones:
        pytest.skip("ui_tone is not seeded in this database")
    assert set(_FINDING_TONE.values()) <= tones


# ── the writer the alarm depends on ───────────────────────────────────

@pytest.mark.django_db
def test_the_nightly_snapshot_records_what_the_alarm_reads():
    """`_refresh_variable_influence` must persist the firing counts.

    Everything above tests the classifier against rows that a fixture
    wrote. If the nightly writer stopped recording `nonzero_count`, the
    classifier would be perfectly correct about data that was perfectly
    wrong — and every weighted variable in the registry would be
    reported as dead. Caught by injection: blanking the writer left all
    fifteen tests above green.
    """
    from apps.admin_console.snapshots import _refresh_variable_influence
    from apps.data_management.models import Household
    from apps.pmt.models import PMTResult
    from apps.reference_data.models import GeographicUnit

    version = PMTModelVersion.objects.create(
        version=92_004, status=ModelStatus.ACTIVE, author="fixture",
        intercept=Decimal("0"), band_strategy="threshold",
        band_cutoffs=canonical_band_cutoffs(),
        variables=[
            {"name": "fires_sometimes", "weight": 0.4,
             "feature": {"type": "membership", "path": "x.y", "operand": ["1"]}},
            {"name": "never", "weight": 0.3,
             "feature": {"type": "membership", "path": "x.z", "operand": ["9"]}},
            {"name": "uncaptured", "weight": 0.2,
             "feature": {"type": "membership", "path": "dwelling.q",
                         "operand": ["1"]}},
        ],
    )
    unit = GeographicUnit.objects.create(
        level="sub_region", code="SR-FIND", name="Findings",
        effective_from=__import__("datetime").date(2026, 1, 1),
    )
    # Three households: the first variable fires for one of them, the
    # second for none.
    for i, fired in enumerate((1.0, 0.0, 0.0)):
        household = Household.objects.create(
            region=unit, sub_region=unit, district=unit, county=unit,
            sub_county=unit, parish=unit, village=unit,
        )
        PMTResult.objects.create(
            household=household, model_version=version,
            score=Decimal("1"), band="not_poor",
            inputs_snapshot={
                "fires_sometimes": {"value": fired, "weight": 0.4,
                                    "contribution": fired * 0.4,
                                    "feature_type": "membership"},
                "never": {"value": 0.0, "weight": 0.3, "contribution": 0.0,
                          "feature_type": "membership"},
                # Present for every household: the branch was absent.
                "uncaptured": {"value": 0.0, "weight": 0.2,
                               "contribution": 0.0,
                               "feature_type": "membership",
                               "missing": "dwelling"},
            },
        )

    _refresh_variable_influence(version)

    fires = PMTVariableInfluence.objects.filter(
        model_version=version, variable_name="fires_sometimes",
    ).latest("computed_at")
    never = PMTVariableInfluence.objects.filter(
        model_version=version, variable_name="never",
    ).latest("computed_at")

    uncaptured = PMTVariableInfluence.objects.filter(
        model_version=version, variable_name="uncaptured",
    ).latest("computed_at")

    assert fires.sample_size == 3 and fires.nonzero_count == 1
    assert never.sample_size == 3 and never.nonzero_count == 0
    assert never.missing_count == 0
    # The writer must persist the missing counts too, or every dead
    # variable reads as a model defect when the real problem is that
    # nobody captured the data.
    assert uncaptured.missing_count == 3

    # And the alarm reads them, telling the two apart.
    with override_settings(PMT_VARIABLE_FINDING_MIN_SAMPLE=1):
        reported = {
            f.variable_name: f.code
            for f in findings_for_model(version) if f.code
        }
    assert reported == {
        "never": FINDING_NEVER_FIRES,
        "uncaptured": FINDING_MISSING_DATA,
    }


# ── missing data is not a broken model ────────────────────────────────

def test_a_branch_absent_for_everyone_is_missing_data_not_never_fires():
    """Eleven of v1's eighteen dead variables resolve perfectly through
    the questionnaire and score zero only because `Dwelling` holds no
    rows. Calling that a model defect sends it to the wrong desk."""
    row = _Row("floor_material__tiles", 0.326, 374, 0)
    row.missing_count = 374
    assert finding_for(row).code == FINDING_MISSING_DATA


def test_data_present_and_still_never_matching_stays_a_model_finding():
    """Some households HAD the entity and it still never matched, which
    is the model's problem and not the registry's."""
    row = _Row("floor_material__tiles", 0.326, 374, 0)
    row.missing_count = 100
    assert finding_for(row).code == FINDING_NEVER_FIRES


def test_a_feature_with_no_path_is_never_reported_as_missing_data():
    """`owns_*` and `rooms_per_capita` read collections, not a path. An
    empty asset list is genuinely ambiguous — never captured and owns
    nothing look identical — so it must not be claimed as missing."""
    row = _Row("owns_radio", 0.107, 374, 0)
    row.missing_count = 0
    assert finding_for(row).code == FINDING_NEVER_FIRES


def test_missing_data_is_not_toned_as_a_defect():
    row = _Row("x", 0.3, 374, 0)
    row.missing_count = 374
    assert finding_for(row).tone == "quality"
    # A broken formula and uncaptured data must not look the same.
    assert finding_for(_Row("y", 0.3, 374, 0)).tone == "danger"


def test_too_small_a_sample_still_wins_over_missing_data():
    """Four households with no Dwelling row is not evidence that the
    country has no dwellings."""
    row = _Row("x", 0.3, 4, 0)
    row.missing_count = 4
    assert finding_for(row).code == FINDING_INSUFFICIENT_SAMPLE


# ── the segment resolver ──────────────────────────────────────────────

def test_missing_segment_names_the_branch_that_was_absent():
    from apps.pmt.feature_evaluator import missing_segment

    record = {"household": {}, "dwelling": None}
    assert missing_segment(record, "dwelling.floor_material") == "dwelling"


def test_missing_segment_is_empty_when_the_leaf_resolves():
    from apps.pmt.feature_evaluator import missing_segment

    record = {"dwelling": {"floor_material": "11"}}
    assert missing_segment(record, "dwelling.floor_material") == ""


def test_a_blank_leaf_is_not_reported_as_missing():
    """A captured Dwelling whose floor_material is blank is a different
    fact from a household that was never asked. Conflating them is what
    this whole split exists to stop."""
    from apps.pmt.feature_evaluator import missing_segment

    record = {"dwelling": {"floor_material": None}}
    assert missing_segment(record, "dwelling.floor_material") == ""


def test_missing_segment_names_the_deepest_branch_it_reached():
    from apps.pmt.feature_evaluator import missing_segment

    record = {"head_member": {"education": None}}
    assert missing_segment(record, "head_member.education.highest_grade") == (
        "education"
    )


@pytest.mark.django_db
def test_the_engine_records_the_missing_segment():
    """End to end: a household with no Dwelling row must say so."""
    from datetime import date

    from apps.data_management.models import Household
    from apps.pmt.engine import compute_score
    from apps.reference_data.models import GeographicUnit

    unit = GeographicUnit.objects.create(
        level="sub_region", code="SR-MISS", name="Missing",
        effective_from=date(2026, 1, 1),
    )
    household = Household.objects.create(
        region=unit, sub_region=unit, district=unit, county=unit,
        sub_county=unit, parish=unit, village=unit,
    )
    version = PMTModelVersion.objects.create(
        version=92_005, status=ModelStatus.ACTIVE, author="fixture",
        intercept=Decimal("0"), band_strategy="threshold",
        band_cutoffs=canonical_band_cutoffs(),
        variables=[{
            "name": "floor", "weight": 0.3,
            "feature": {"type": "membership",
                        "path": "dwelling.floor_material",
                        "operand": ["11"]},
        }],
    )
    _score, snapshot = compute_score(household, version)
    assert snapshot["floor"]["missing"] == "dwelling"


@pytest.mark.django_db
def test_a_resolving_path_writes_no_missing_key():
    """Recorded only when non-empty, so the common case costs nothing
    in a snapshot stored 12 million times."""
    from datetime import date

    from apps.data_management.models import Household
    from apps.pmt.engine import compute_score
    from apps.reference_data.models import GeographicUnit

    unit = GeographicUnit.objects.create(
        level="sub_region", code="SR-PRESENT", name="Present",
        effective_from=date(2026, 1, 1),
    )
    household = Household.objects.create(
        region=unit, sub_region=unit, district=unit, county=unit,
        sub_county=unit, parish=unit, village=unit,
    )
    version = PMTModelVersion.objects.create(
        version=92_006, status=ModelStatus.ACTIVE, author="fixture",
        intercept=Decimal("0"), band_strategy="threshold",
        band_cutoffs=canonical_band_cutoffs(),
        variables=[{
            "name": "size", "weight": 0.3,
            "feature": {"type": "direct", "path": "member_count"},
        }],
    )
    _score, snapshot = compute_score(household, version)
    assert "missing" not in snapshot["size"]
