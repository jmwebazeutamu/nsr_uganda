"""The variable catalogue is assembled from canonical sources, not authored.

The two things it states for itself — `ROOTS`, the engine's feature-tree
prefixes, and `DERIVED`, the scalars the engine computes — are pinned
here against a feature dict the engine actually produced. A prefix that
stops resolving, or a derived scalar that gets renamed, fails here
rather than silently emptying the Add-variable dialog.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.intake.models import FormQuestion, FormSection, FormVersion
from apps.pmt.variable_catalogue import (
    DERIVED,
    ROOTS,
    canonical_name,
    catalogue,
    field_for_name,
)
from apps.reference_data.models import ChoiceList, ChoiceListStatus, ChoiceOption

# ── the naming rule ───────────────────────────────────────────────────

def test_an_unqualified_variable_is_named_for_its_field():
    assert canonical_name("floor_material") == "floor_material"


def test_a_qualifier_keeps_the_field_as_the_prefix():
    assert canonical_name("floor_material", "tiles_terrazzo") == (
        "floor_material__tiles_terrazzo"
    )


def test_the_field_is_recoverable_from_either_spelling():
    assert field_for_name("floor_material__tiles_terrazzo") == "floor_material"
    assert field_for_name("member_count") == "member_count"


def test_a_qualifier_is_normalised_not_doubled():
    """`__wall` and `wall` must not produce different names for the same
    thing — the whole point is that the name is derivable."""
    assert canonical_name("wall_material", "__adobe") == "wall_material__adobe"


# ── assembled, not authored ───────────────────────────────────────────

@pytest.fixture
def seeded_question(db):
    choice_list = ChoiceList.objects.create(
        list_name="cat_floor", version=1,
        status=ChoiceListStatus.ACTIVE, author="fixture",
    )
    ChoiceOption.objects.create(
        choice_list=choice_list, code="11", label="Earth",
        status=ChoiceOption.Status.ACTIVE, sort_order=1,
    )
    ChoiceOption.objects.create(
        choice_list=choice_list, code="17", label="Tiles",
        status=ChoiceOption.Status.ACTIVE, sort_order=2,
    )
    ChoiceOption.objects.create(
        choice_list=choice_list, code="99", label="Withdrawn",
        status=ChoiceOption.Status.DEPRECATED, sort_order=3,
    )
    version = FormVersion.objects.create(
        version=91_001, name="Catalogue test", status="draft",
        author="fixture", effective_from=date(2026, 1, 1),
    )
    section = FormSection.objects.create(
        form_version=version, code="G", name="dwelling", label="Dwelling",
        order=1,
    )
    return FormQuestion.objects.create(
        section=section, name="g7_floor_material", label="Floor material",
        type="select_one", choice_list_ref=choice_list,
        canonical_field="floor_material",
    )


def test_a_coded_field_carries_its_options_and_its_path(seeded_question):
    entry = next(
        f for f in catalogue()["fields"] if f["field"] == "floor_material"
    )
    assert entry["path"] == "dwelling.floor_material"
    assert entry["kind"] == "coded"
    assert entry["choice_list"] == "cat_floor"
    # The operator-facing label is the QUESTION's, not the column name.
    assert entry["label"] == "Floor material"
    assert [o["code"] for o in entry["options"]] == ["11", "17"]


def test_a_deprecated_option_is_not_offered(seeded_question):
    entry = next(
        f for f in catalogue()["fields"] if f["field"] == "floor_material"
    )
    assert "99" not in [o["code"] for o in entry["options"]]


def test_a_field_with_no_question_is_not_offered(db):
    """Fields the engine can reach but the questionnaire does not
    describe have no authority for their values, so offering them would
    invite the free-typed codes ADR-0041 exists to stop."""
    fields = catalogue()["fields"]
    assert fields == []


def test_the_derived_scalars_are_offered_separately(db):
    derived = catalogue()["derived"]
    names = [d["name"] for d in derived]
    assert "member_count" in names
    assert all(d["kind"] == "derived" for d in derived)
    assert all(d["options"] == [] for d in derived)
    # A derived scalar has no question, and must not pretend otherwise.
    assert all(d["question"] == "" for d in derived)


# ── pinned against the engine ─────────────────────────────────────────

@pytest.fixture
def engine_features(db):
    """A real feature dict, built the way scoring builds one.

    Built here rather than found: an earlier version skipped when the
    database held no household, which meant the three checks below — the
    only ones that pin this module against the engine — never ran in CI.
    A test that always skips is not a test.
    """
    from apps.data_management.models import Household
    from apps.pmt.engine import _household_features
    from apps.reference_data.models import GeographicUnit

    unit = GeographicUnit.objects.create(
        level="sub_region", code="SR-PMT-CAT",
        name="Catalogue sub-region", effective_from=date(2026, 1, 1),
    )
    household = Household.objects.create(
        region=unit, sub_region=unit, district=unit, county=unit,
        sub_county=unit, parish=unit, village=unit,
    )
    return _household_features(household)


def test_catalogue_roots_match_the_engine(engine_features):
    """Every prefix in ROOTS must be a key the engine actually exposes.

    If the engine renames a root, a variable built from this catalogue
    would carry a path that resolves to None and score zero for every
    household — the silent failure ADR-0041 is about, reintroduced one
    level up.
    """
    from django.apps import apps as django_apps

    features = engine_features
    for prefix, model_label, _group in ROOTS:
        root = prefix.split(".")[0]
        assert root in features, (
            f"ROOTS names {prefix!r} but the engine exposes no {root!r} key"
        )
        django_apps.get_model(model_label)  # raises LookupError if gone


def test_declared_derived_features_exist(engine_features):
    features = engine_features
    for entry in DERIVED:
        assert entry["name"] in features, (
            f"DERIVED names {entry['name']!r}, which the engine does not compute"
        )


def test_nested_roots_resolve_through_their_parent(engine_features):
    """`head_member.education` is a reverse one-to-one hung off the head
    member, not a top-level key — check the chain, not just the root."""
    from apps.pmt.feature_evaluator import resolve_path

    features = engine_features
    for prefix, _model, _group in ROOTS:
        if "." not in prefix:
            continue
        # None is a legitimate answer (no such detail row); a raised
        # exception or a missing intermediate is not.
        resolve_path(features, prefix)


# ── the migration's inlined copy of the rule ──────────────────────────

@pytest.mark.django_db
def test_v2_names_match_the_catalogue_rule():
    """Migration pmt.0010 inlines `canonical_name` rather than importing
    it, so that it keeps working when this module changes. That is the
    right call for a migration and it is also how the two drift apart,
    so the seeded result is checked against the live rule here.
    """
    import importlib

    from apps.pmt.models import PMTModelVersion

    module = importlib.import_module(
        "apps.pmt.migrations.0010_seed_v2_canonical_variable_names",
    )
    for field, qualifier in module.RENAMES.values():
        if not field:
            continue
        assert module._canonical_name(field, qualifier) == canonical_name(
            field, qualifier,
        ), "migration pmt.0010 and variable_catalogue disagree on naming"

    v2 = PMTModelVersion.objects.filter(version=2).first()
    if v2 is None:
        pytest.skip("v2 is seeded from v1, which this database lacks")
    for entry in v2.variables:
        name = entry["name"]
        field = field_for_name(name)
        assert name == canonical_name(field, name[len(field) + 2:]), (
            f"{name!r} is not a name `canonical_name` would produce"
        )
