"""A grievance arriving from another system keeps its place, its number
and its clock.

NSR is to receive grievances from STAAC's GRM. Nothing about that was
possible before: `open_grievance` took geography only off a Household,
had nowhere to put a tracking number, and started every SLA at the
moment our queue picked the case up.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from apps.grievance.intake import (
    STAAC_CATEGORY_LIST,
    UnmappedCategory,
    resolve_category,
)
from apps.grievance.models import Category, Grievance
from apps.grievance.services import GrievanceError, open_grievance
from apps.reference_data.models import (
    ChoiceList,
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
    reported = datetime.now(timezone.utc) - timedelta(hours=10)
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
    with pytest.raises(UnmappedCategory) as exc:
        resolve_category("C07")
    assert exc.value.recognised is True
    assert "no approved binding" in str(exc.value)


def test_an_unknown_category_is_a_different_problem(db):
    """"We have never heard of this" and "nobody has decided what it
    means" have different owners, so they are different errors."""
    with pytest.raises(UnmappedCategory) as exc:
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
    with pytest.raises(UnmappedCategory):
        resolve_category("C07")


def test_the_vocabulary_ships_unmapped(db):
    """Every STAAC code is registered and none is bound, because the
    correspondence is MGLSD's to state. If this starts failing, someone
    has set bindings — check they were approved, then delete this."""
    options = ChoiceOption.objects.filter(
        choice_list__list_name=STAAC_CATEGORY_LIST,
        choice_list__status=ChoiceListStatus.ACTIVE,
    )
    assert options.count() == 16
    assert not options.exclude(canonical_code=None).exists()
