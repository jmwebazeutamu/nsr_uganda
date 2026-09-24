"""The Kigezi seed put every rung one level too high.

Nyakagyeme is a sub-county of Rujumbura County, and the stopgap seeder
made it a county. Kabwoma is a parish of Nyakagyeme, and the seeder
made it a sub-county. A household captured there carried a county that
does not exist, and never named its real county at all.

Unlike the padded-code merge, the target cannot be derived — it is a
different place, not a different spelling — so the mapping is stated
and every pair is checked to be level-for-level before anything moves.
"""

from __future__ import annotations

from datetime import date
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.data_management.models import Household
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent

pytestmark = pytest.mark.django_db


def _unit(level, code, name, parent=None):
    return GeographicUnit.objects.create(
        level=level, code=code, name=name, parent=parent,
        effective_from=date(2026, 1, 1),
    )


@pytest.fixture
def frame():
    f = {}
    f["region"] = _unit("region", "R-WESTERN", "Western")
    f["sub_region"] = _unit("sub_region", "SR-KIGEZI-WESTERN", "Kigezi", f["region"])
    f["district"] = _unit("district", "412", "Rukungiri", f["sub_region"])
    # The real UBOS chain.
    f["rujumbura"] = _unit("county", "412.2", "Rujumbura County", f["district"])
    f["nyakagyeme_sc"] = _unit("sub_county", "412.2.05", "Nyakagyeme", f["rujumbura"])
    f["kabwoma_parish"] = _unit("parish", "412.2.05.01", "Kabwoma", f["nyakagyeme_sc"])
    # The seeded chain, one level too high at every rung.
    f["seeded_county"] = _unit("county", "412.02", "Nyakagyeme", f["district"])
    f["seeded_sc"] = _unit("sub_county", "412.02.05", "Kabwoma", f["seeded_county"])
    f["seeded_parish"] = _unit(
        "parish", "412.02.05.01", "Kabwoma Parish", f["seeded_sc"],
    )
    f["village"] = _unit(
        "village", "412.02.05.01.AKELLO-VILLAGE", "Akello Village",
        f["seeded_parish"],
    )
    return f


@pytest.fixture
def household(frame):
    return Household.objects.create(
        region=frame["region"], sub_region=frame["sub_region"],
        district=frame["district"], county=frame["seeded_county"],
        sub_county=frame["seeded_sc"], parish=frame["seeded_parish"],
        village=frame["village"], urban_rural="2",
    )


def _run(*args):
    out = StringIO()
    call_command("fix_kigezi_seed_levels", *args, stdout=out)
    return out.getvalue()


def test_dry_run_changes_nothing(frame, household):
    output = _run()

    assert "would merge" in output
    household.refresh_from_db()
    assert household.county_id == frame["seeded_county"].pk


def test_the_household_lands_on_the_real_ladder(frame, household):
    _run("--apply", "--actor", "ops.kigezi")

    household.refresh_from_db()
    assert household.county_id == frame["rujumbura"].pk
    assert household.sub_county_id == frame["nyakagyeme_sc"].pk
    assert household.parish_id == frame["kabwoma_parish"].pk


def test_the_household_finally_names_its_real_county(frame, household):
    """The point of the whole repair: Rujumbura appears on the record."""
    _run("--apply", "--actor", "ops.kigezi")

    household.refresh_from_db()
    assert household.county.name == "Rujumbura County"
    assert household.sub_county.name == "Nyakagyeme"
    assert household.parish.name == "Kabwoma"


def test_the_denormalised_codes_follow(frame, household):
    _run("--apply", "--actor", "ops.kigezi")

    household.refresh_from_db()
    assert household.county_code == "412.2"
    assert household.sub_county_code == "412.2.05"
    assert household.parish_code == "412.2.05.01"


def test_the_village_is_reparented_onto_the_real_parish(frame, household):
    """UBOS carries no villages, so this fabricated row is the only one
    there is — it moves rather than being retired."""
    _run("--apply", "--actor", "ops.kigezi")

    frame["village"].refresh_from_db()
    assert frame["village"].parent_id == frame["kabwoma_parish"].pk
    assert frame["village"].status == GeographicUnit.Status.ACTIVE


def test_the_seeded_units_are_retired(frame, household):
    _run("--apply", "--actor", "ops.kigezi")

    for key in ("seeded_county", "seeded_sc", "seeded_parish"):
        frame[key].refresh_from_db()
        assert frame[key].status == GeographicUnit.Status.RETIRED, key


def test_the_real_units_are_untouched(frame, household):
    _run("--apply", "--actor", "ops.kigezi")

    for key in ("rujumbura", "nyakagyeme_sc", "kabwoma_parish"):
        frame[key].refresh_from_db()
        assert frame[key].status == GeographicUnit.Status.ACTIVE, key


def test_the_move_is_audited_with_both_names(frame, household):
    _run("--apply", "--actor", "ops.kigezi")

    event = AuditEvent.objects.filter(
        action="geo_unit.merged", entity_id=str(frame["seeded_county"].pk),
    ).first()
    assert event is not None
    assert event.field_changes["name"] == ["Nyakagyeme", "Rujumbura County"]
    assert "one level too high" in event.reason


def test_it_refuses_when_the_target_is_not_active(frame, household):
    """Better to stop than to put a household on a retired rung.

    Deleting the target is not even possible — GeographicUnit.parent is
    PROTECT — so the realistic failure is a target that has been
    superseded or retired out from under the mapping.
    """
    frame["rujumbura"].status = GeographicUnit.Status.RETIRED
    frame["rujumbura"].save(update_fields=["status"])

    with pytest.raises(CommandError, match="does not match the frame"):
        _run("--apply", "--actor", "ops.kigezi")

    household.refresh_from_db()
    assert household.county_id == frame["seeded_county"].pk
    # And nothing partial: the other two rungs are untouched too.
    frame["seeded_sc"].refresh_from_db()
    assert frame["seeded_sc"].status == GeographicUnit.Status.ACTIVE


def test_rerunning_is_a_no_op(frame, household):
    _run("--apply", "--actor", "ops.kigezi")
    assert "already merged" in _run("--apply", "--actor", "ops.kigezi")


def test_apply_requires_an_actor(frame):
    with pytest.raises(CommandError, match="--actor is required"):
        _run("--apply")
