"""A grievance arriving from another system keeps its place, its number
and its clock.

NSR is to receive grievances from STAAC's GRM. Nothing about that was
possible before: `open_grievance` took geography only off a Household,
had nowhere to put a tracking number, and started every SLA at the
moment our queue picked the case up.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from apps.grievance.intake import (
    STAAC_CATEGORY_LIST,
    STAAC_GENDER_LIST,
    UnmappedCategoryError,
    resolve_category,
    resolve_gender,
)
from apps.grievance.models import Category, Grievance
from apps.grievance.services import GrievanceError, open_grievance
from apps.reference_data.models import (
    ChoiceListStatus,
    ChoiceOption,
    GeographicUnit,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def parish(db):
    """A real ladder, built the way the registry holds one."""
    parent = None
    codes = [
        ("region", "R-X"), ("sub_region", "SR-X"), ("district", "D-X"),
        ("county", "C-X"), ("sub_county", "SC-X"), ("parish", "P-X"),
    ]
    for level, code in codes:
        parent = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent,
            effective_from=date(2026, 1, 1),
        )
    return parent


# ── 1. a case that names a place, not a household ─────────────────────

def test_a_parish_fills_the_whole_ladder(parish):
    """The scope columns are what `apps.security.abac` filters on, so a
    case with a parish and no household must still land in a district.
    Blank is not neutral: it meant the case belonged to no officer's
    scope and appeared for every officer nationally."""
    g = open_grievance(
        category=Category.EXCLUSION_ERROR, description="omitted",
        geographic_code="P-X", actor="t",
    )
    assert g.parish_code == "P-X"
    assert g.sub_county_code == "SC-X"
    assert g.district_code == "D-X"
    assert g.region_code == "R-X"
    # Nothing below the unit named is invented.
    assert g.village_code == ""


def test_a_code_naming_nothing_is_refused(db):
    """Better a refused case than one filed to nowhere."""
    with pytest.raises(GrievanceError, match="names no GeographicUnit"):
        open_grievance(
            category=Category.EXCLUSION_ERROR, description="x",
            geographic_code="NOT-A-PLACE", actor="t",
        )


def test_a_household_still_wins_over_a_code(parish, django_user_model):
    """A case naming a household takes that household's geography — the
    household is the more specific fact and the existing path."""
    from apps.data_management.models import Household

    unit = GeographicUnit.objects.get(code="P-X")
    hh = Household.objects.create(
        region=unit, sub_region=unit, district=unit, county=unit,
        sub_county=unit, parish=unit, village=unit,
    )
    g = open_grievance(
        category=Category.EXCLUSION_ERROR, description="x",
        household_id=str(hh.id), geographic_code="P-X", actor="t",
    )
    assert g.household_id == str(hh.id)
    assert g.parish_code == "P-X"


# ── 2. provenance and the clock ───────────────────────────────────────

def test_the_tracking_number_is_kept(parish):
    """An officer asked "what happened to C-26-057528-8" has to be able
    to answer."""
    g = open_grievance(
        category=Category.EXCLUSION_ERROR, description="x",
        geographic_code="P-X", source_system="STAAC_GRM",
        external_reference="C-26-057528-8", actor="t",
    )
    assert g.source_system == "STAAC_GRM"
    assert g.external_reference == "C-26-057528-8"


def test_a_resend_returns_the_same_case(parish):
    """Intake has to be safe to retry. A second push of one tracking
    number is the same grievance, not a duplicate complaint."""
    kw = dict(
        category=Category.EXCLUSION_ERROR, description="x",
        geographic_code="P-X", source_system="STAAC_GRM",
        external_reference="C-26-057528-8", actor="t",
    )
    first = open_grievance(**kw)
    second = open_grievance(**kw)
    assert first.id == second.id
    assert Grievance.objects.filter(external_reference="C-26-057528-8").count() == 1


def test_a_reference_with_no_system_is_refused(parish):
    """Nothing could look it up, and every system's numbering would
    share one space."""
    with pytest.raises(GrievanceError, match="requires source_system"):
        open_grievance(
            category=Category.EXCLUSION_ERROR, description="x",
            geographic_code="P-X", external_reference="C-1", actor="t",
        )


def test_the_clock_runs_from_when_they_reported(parish):
    """Time spent between the two systems is time the complainant has
    already waited. Starting at ingestion hands a transferred case a
    fresh deadline it had not earned."""
    reported = datetime.now(UTC) - timedelta(hours=10)
    g = open_grievance(
        category=Category.EXCLUSION_ERROR, description="x",
        geographic_code="P-X", source_system="STAAC_GRM",
        external_reference="C-2", reported_at=reported, actor="t",
    )
    assert g.reported_at == reported
    # The deadline is measured from the report, so it is ten hours
    # nearer than a case opened here right now.
    assert g.sla_deadline < g.opened_at + timedelta(hours=24)


def test_a_case_opened_here_is_unaffected(parish):
    """Most cases have no reported_at and must keep the old clock."""
    g = open_grievance(
        category=Category.EXCLUSION_ERROR, description="x",
        geographic_code="P-X", actor="t",
    )
    assert g.reported_at is None
    assert g.sla_deadline > g.opened_at


# ── 3. the category vocabulary ────────────────────────────────────────

def _bind(code, canonical):
    """Set, or with None clear, one approved binding.

    Clearing matters since reference_data.0029: the vocabulary ships
    bound, so a test about an unmapped category has to make one.
    """
    option = ChoiceOption.objects.get(
        choice_list__list_name=STAAC_CATEGORY_LIST, code=code,
    )
    option.canonical_code = canonical
    option.save(update_fields=["canonical_code"])
    from apps.reference_data.services import clear_resolver_cache
    clear_resolver_cache()


def test_an_unmapped_category_is_refused_not_defaulted(db):
    """Defaulting to `other` would accept the case and lose the
    classification silently — the failure this registry keeps finding
    in its own pipelines."""
    _bind("C07", None)
    with pytest.raises(UnmappedCategoryError) as exc:
        resolve_category("C07")
    assert exc.value.recognised is True
    assert "no approved binding" in str(exc.value)


def test_an_unknown_category_is_a_different_problem(db):
    """"We have never heard of this" and "nobody has decided what it
    means" have different owners, so they are different errors."""
    with pytest.raises(UnmappedCategoryError) as exc:
        resolve_category("C99")
    assert exc.value.recognised is False
    assert "needs reseeding" in str(exc.value)


def test_a_bound_category_resolves(db):
    _bind("C07", Category.EXCLUSION_ERROR)
    resolved = resolve_category("C07")
    assert resolved.nsr_category == Category.EXCLUSION_ERROR
    assert resolved.staac_code == "C07"
    assert resolved.label_lookup_used is False


def test_the_label_resolves_too_and_says_so(db):
    """STAAC's payload sends display text, not the code. A label is the
    part of a vocabulary expected to change without the code changing,
    so a caller is told it had to fall back to one."""
    _bind("C07", Category.EXCLUSION_ERROR)
    resolved = resolve_category("Targeting and selection irregularity")
    assert resolved.staac_code == "C07"
    assert resolved.label_lookup_used is True


def test_a_binding_to_a_category_we_do_not_have_is_refused(db):
    """A configuration error, reported as one rather than failing on
    insert."""
    _bind("C07", "not_an_nsr_category")
    with pytest.raises(UnmappedCategoryError):
        resolve_category("C07")


def test_every_category_is_bound_to_a_category_we_have(db):
    """The vocabulary shipped unbound and was bound on MGLSD's
    instruction in reference_data.0029. What matters now is not that
    bindings exist but that every one of them names a category this
    registry actually has — a binding pointing at a string we do not
    recognise refuses the case just as an absent one does, and looks
    like configuration rather than a typo."""
    options = ChoiceOption.objects.filter(
        choice_list__list_name=STAAC_CATEGORY_LIST,
        choice_list__status=ChoiceListStatus.ACTIVE,
    )
    assert options.count() == 16
    bound = {o.code: o.canonical_code for o in options}
    assert all(v for v in bound.values()), (
        f"unbound: {[k for k, v in bound.items() if not v]}"
    )
    unknown = {k: v for k, v in bound.items() if v not in Category.values}
    assert unknown == {}, f"bound to categories that do not exist: {unknown}"


def test_the_lossy_binding_is_the_one_we_documented(db):
    """C07 carries four NSR meanings behind one code — wrongful
    exclusion, wrongful inclusion, a PMT score dispute and list
    manipulation. It binds to the dominant one and triage
    re-categorises the rest. If this changes, the reasoning in
    reference_data.0029 needs changing with it."""
    option = ChoiceOption.objects.get(
        choice_list__list_name=STAAC_CATEGORY_LIST, code="C07",
    )
    assert option.canonical_code == Category.EXCLUSION_ERROR


def test_nothing_binds_to_data_correction(db):
    """Not an oversight: no STAAC category means "the registry holds
    the wrong facts about me". The nearest is a C07 PMT-score dispute,
    which arrives under C07's binding. Forcing a mapping to fill the
    gap would misfile the other three quarters of C07."""
    bound = set(
        ChoiceOption.objects
        .filter(choice_list__list_name=STAAC_CATEGORY_LIST)
        .values_list("canonical_code", flat=True),
    )
    assert Category.DATA_CORRECTION not in bound


# ── 4. who complained: sex and age ────────────────────────────────────

def _bind_gender(code, canonical):
    option = ChoiceOption.objects.get(
        choice_list__list_name=STAAC_GENDER_LIST, code=code,
    )
    option.canonical_code = canonical
    option.save(update_fields=["canonical_code"])
    from apps.reference_data.services import clear_resolver_cache
    clear_resolver_cache()


def test_the_gender_vocabulary_ships_unmapped(db):
    """`female` -> `2` is obvious and still not ours to seed. Every
    other external binding in this registry is approved through the
    ChoiceList workflow and the one that writes a person's recorded sex
    is not the exception. If this starts failing, someone has set
    bindings — check they were approved, then delete this."""
    options = ChoiceOption.objects.filter(
        choice_list__list_name=STAAC_GENDER_LIST,
        choice_list__status=ChoiceListStatus.ACTIVE,
    )
    assert options.count() == 3
    assert not options.exclude(canonical_code=None).exists()


def test_an_unmapped_gender_comes_back_named_not_raised(db):
    """The asymmetry with category, stated. An unusable category makes
    the case unworkable; an unusable gender makes one count less
    precise. So the value returns, flagged and named, and the caller
    reports it instead of losing a real complaint."""
    resolved = resolve_gender("female")
    assert resolved.nsr_code == ""
    assert resolved.received == "female"
    assert resolved.recognised is True
    assert resolved.unmapped is True


def test_a_gender_nobody_registered_says_so(db):
    """In STAAC this field is free text, so a value outside the list is
    expected rather than impossible — and is a different problem, with
    a different owner, from one nobody has bound."""
    resolved = resolve_gender("Mwana")
    assert resolved.nsr_code == ""
    assert resolved.recognised is False
    assert resolved.unmapped is True


def test_a_bound_gender_resolves_to_a_sex_code(db):
    _bind_gender("female", "2")
    resolved = resolve_gender("female")
    assert resolved.nsr_code == "2"
    assert resolved.unmapped is False
    assert resolved.label_lookup_used is False


def test_a_gender_label_resolves_too_and_says_so(db):
    """The field is free text in STAAC, so "Female" is as likely as
    "female"."""
    _bind_gender("female", "2")
    resolved = resolve_gender("Female")
    assert resolved.nsr_code == "2"
    assert resolved.label_lookup_used is True


def test_nothing_sent_is_not_a_failure(db):
    """Most complaints are anonymous. No gender is the ordinary case,
    not an unmapped one."""
    resolved = resolve_gender("")
    assert resolved.nsr_code == ""
    assert resolved.received == ""
    assert resolved.unmapped is False


def test_a_binding_to_a_sex_code_we_do_not_have_is_not_returned(db):
    """`not_said` has nothing to bind to: NSR's `sex` list has no
    "prefer not to say". A binding pointing outside the list would put
    a value in the column that nothing reads back as a word."""
    _bind_gender("not_said", "9")
    resolved = resolve_gender("not_said")
    assert resolved.nsr_code == ""
    assert resolved.unmapped is True


def test_the_reporter_gender_column_only_takes_a_sex_code(parish):
    """What makes returning safe instead of raising. An untranslated
    value cannot reach the column, so the failure mode is a blank
    column and a result the caller was handed — never a `sex` column
    holding "F"."""
    with pytest.raises(GrievanceError, match="is not a code on the 'sex' list"):
        open_grievance(
            category=Category.EXCLUSION_ERROR, description="omitted",
            geographic_code="P-X", reporter_gender="female", actor="t",
        )


def test_a_translated_gender_and_age_are_kept(parish):
    g = open_grievance(
        category=Category.EXCLUSION_ERROR, description="omitted",
        geographic_code="P-X", reporter_gender="2", reporter_age_years=64,
        actor="t",
    )
    g.refresh_from_db()
    assert g.reporter_gender == "2"
    assert g.reporter_age_years == 64


def test_an_age_that_is_not_a_number_is_refused(parish):
    with pytest.raises(GrievanceError, match="is not a number of years"):
        open_grievance(
            category=Category.EXCLUSION_ERROR, description="omitted",
            geographic_code="P-X", reporter_age_years="sixty-four", actor="t",
        )


def test_no_age_is_not_zero(parish):
    """A complainant who did not say their age is not a newborn, and an
    unanswered question must not be counted as an answer."""
    g = open_grievance(
        category=Category.EXCLUSION_ERROR, description="omitted",
        geographic_code="P-X", reporter_age_years="", actor="t",
    )
    g.refresh_from_db()
    assert g.reporter_age_years is None


def test_no_local_age_ceiling(parish):
    """The registry's implausible-age threshold is the DQA rule
    AC-MEMBER-AGE-MAX, which applies to members and FLAGS rather than
    refuses. A second ceiling here would be a copy of a number already
    owned, free to drift from it — so an implausible age is stored and
    left to be reported, not rejected at the door."""
    g = open_grievance(
        category=Category.EXCLUSION_ERROR, description="omitted",
        geographic_code="P-X", reporter_age_years=131, actor="t",
    )
    assert g.reporter_age_years == 131
