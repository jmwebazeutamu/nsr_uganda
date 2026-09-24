"""The merge that repairs what the two code frames left behind.

A placeholder is a unit `geo_backfill` fabricated because the code it
was handed did not resolve — `name = code`, sitting beside a real UBOS
row for the same place. Households promoted from those records attached
to the fabrication, so one real county held households under two codes.
"""

from __future__ import annotations

from datetime import date
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.data_management.models import Household
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent, OperatorScope, ScopeLevel

pytestmark = pytest.mark.django_db


@pytest.fixture
def frame():
    """Maracha: a real UBOS chain, and the padded fabrication beside it."""
    nodes = {}
    nodes["region"] = GeographicUnit.objects.create(
        level="region", code="R-NORTHERN", name="Northern",
        effective_from=date(2026, 1, 1),
    )
    nodes["sub_region"] = GeographicUnit.objects.create(
        level="sub_region", code="SR-WEST-NILE", name="West Nile",
        parent=nodes["region"], effective_from=date(2026, 1, 1),
    )
    nodes["district"] = GeographicUnit.objects.create(
        level="district", code="320", name="Maracha",
        parent=nodes["sub_region"], effective_from=date(2026, 1, 1),
    )
    # The real frame, from the UBOS workbook.
    nodes["county"] = GeographicUnit.objects.create(
        level="county", code="320.2", name="Maracha East County",
        parent=nodes["district"], effective_from=date(2026, 1, 1),
    )
    nodes["sub_county"] = GeographicUnit.objects.create(
        level="sub_county", code="320.2.11", name="Yivu",
        parent=nodes["county"], effective_from=date(2026, 1, 1),
    )
    nodes["parish"] = GeographicUnit.objects.create(
        level="parish", code="320.2.11.08", name="Ovujo",
        parent=nodes["sub_county"], effective_from=date(2026, 1, 1),
    )
    # The fabrications, from a Kobo pull that padded the county segment.
    nodes["ph_county"] = GeographicUnit.objects.create(
        level="county", code="320.02", name="320.02",
        parent=nodes["district"], effective_from=date(2026, 1, 1),
    )
    nodes["ph_sub_county"] = GeographicUnit.objects.create(
        level="sub_county", code="320.02.11", name="320.02.11",
        parent=nodes["ph_county"], effective_from=date(2026, 1, 1),
    )
    nodes["ph_parish"] = GeographicUnit.objects.create(
        level="parish", code="320.02.11.08", name="320.02.11.08",
        parent=nodes["ph_sub_county"], effective_from=date(2026, 1, 1),
    )
    # A village the pull fabricated under the placeholder parish. It has
    # no UBOS equivalent — UBOS carries no village rows — so it must be
    # reparented, not merged.
    nodes["village"] = GeographicUnit.objects.create(
        level="village", code="320.02.11.08.NAMATA-VILLAGE",
        name="Namata Village", parent=nodes["ph_parish"],
        effective_from=date(2026, 1, 1),
    )
    return nodes


@pytest.fixture
def stranded_household(frame):
    """A household on the fabricated chain."""
    return Household.objects.create(
        region=frame["region"], sub_region=frame["sub_region"],
        district=frame["district"], county=frame["ph_county"],
        sub_county=frame["ph_sub_county"], parish=frame["ph_parish"],
        village=frame["village"], urban_rural="2",
    )


def _run(*args):
    out = StringIO()
    call_command("merge_padded_geo_codes", *args, stdout=out)
    return out.getvalue()


def test_dry_run_writes_nothing(frame, stranded_household):
    output = _run()

    assert "would merge" in output
    assert "Dry run" in output
    stranded_household.refresh_from_db()
    assert stranded_household.county_id == frame["ph_county"].pk
    frame["ph_county"].refresh_from_db()
    assert frame["ph_county"].status == GeographicUnit.Status.ACTIVE


def test_apply_requires_an_actor(frame):
    with pytest.raises(CommandError, match="--actor is required"):
        _run("--apply")


def test_the_household_moves_to_the_ubos_frame(frame, stranded_household):
    _run("--apply", "--actor", "ops.merge")

    stranded_household.refresh_from_db()
    assert stranded_household.county_id == frame["county"].pk
    assert stranded_household.sub_county_id == frame["sub_county"].pk
    assert stranded_household.parish_id == frame["parish"].pk


def test_the_denormalised_codes_move_with_it(frame, stranded_household):
    """The mirrors ABAC matches on must follow the FK, or the household
    is repointed and still invisible to the right operator."""
    _run("--apply", "--actor", "ops.merge")

    stranded_household.refresh_from_db()
    assert stranded_household.county_code == "320.2"
    assert stranded_household.sub_county_code == "320.2.11"
    assert stranded_household.parish_code == "320.2.11.08"


def test_the_village_is_reparented_not_retired(frame, stranded_household):
    """UBOS carries no villages, so the fabricated one is the only row
    there is — it moves under the real parish."""
    _run("--apply", "--actor", "ops.merge")

    frame["village"].refresh_from_db()
    assert frame["village"].parent_id == frame["parish"].pk
    assert frame["village"].status == GeographicUnit.Status.ACTIVE


def test_placeholders_are_retired_not_deleted(frame, stranded_household):
    _run("--apply", "--actor", "ops.merge")

    for key in ("ph_county", "ph_sub_county", "ph_parish"):
        frame[key].refresh_from_db()
        assert frame[key].status == GeographicUnit.Status.RETIRED, key
        assert frame[key].effective_to is not None, key


def test_an_operator_scope_follows_the_households(frame, stranded_household,
                                                  django_user_model):
    """Rewriting the code keeps the operator seeing the same places.
    Leaving it would scope them to a retired unit and empty their view."""
    user = django_user_model.objects.create(username="demo-chief")
    OperatorScope.objects.create(
        user=user, scope_level=ScopeLevel.PARISH, scope_code="320.02.11.08",
    )

    _run("--apply", "--actor", "ops.merge")

    scope = OperatorScope.objects.get(user=user)
    assert scope.scope_code == "320.2.11.08"


def test_the_household_change_is_audited(frame, stranded_household):
    """Repointing a household's geography rewrites a registry record."""
    _run("--apply", "--actor", "ops.merge")

    event = AuditEvent.objects.filter(
        action="household.geography_corrected",
        entity_id=str(stranded_household.id),
    ).first()
    assert event is not None
    assert event.actor_id == "ops.merge"
    assert event.field_changes["county_code"] == ["320.02", "320.2"]
    assert event.field_changes["parish_code"] == ["320.02.11.08", "320.2.11.08"]


def test_one_event_per_household_not_one_per_level(frame, stranded_household):
    _run("--apply", "--actor", "ops.merge")

    assert AuditEvent.objects.filter(
        action="household.geography_corrected",
        entity_id=str(stranded_household.id),
    ).count() == 1


def test_the_retirement_is_audited(frame, stranded_household):
    _run("--apply", "--actor", "ops.merge")

    assert AuditEvent.objects.filter(
        action="geo_unit.merged",
        entity_id=str(frame["ph_county"].pk),
    ).exists()


def test_a_placeholder_with_no_twin_is_left_alone(frame):
    """Only a duplicate is merged. A placeholder naming a place that is
    genuinely absent from the frame has nowhere to go, and guessing
    would put households somewhere they are not."""
    orphan = GeographicUnit.objects.create(
        level="county", code="999.01", name="999.01",
        parent=frame["district"], effective_from=date(2026, 1, 1),
    )

    output = _run("--apply", "--actor", "ops.merge")

    assert "no twin: county 999.01" in output
    orphan.refresh_from_db()
    assert orphan.status == GeographicUnit.Status.ACTIVE


def test_a_real_padded_county_is_not_touched(frame):
    """412.02 Nyakagyeme is named, so it is not a placeholder and the
    command never considers it — even though 412.2 Rujumbura exists."""
    nyakagyeme = GeographicUnit.objects.create(
        level="county", code="412.02", name="Nyakagyeme",
        parent=frame["district"], effective_from=date(2026, 1, 1),
    )
    rujumbura = GeographicUnit.objects.create(
        level="county", code="412.2", name="Rujumbura County",
        parent=frame["district"], effective_from=date(2026, 1, 1),
    )

    _run("--apply", "--actor", "ops.merge")

    nyakagyeme.refresh_from_db()
    rujumbura.refresh_from_db()
    assert nyakagyeme.status == GeographicUnit.Status.ACTIVE
    assert rujumbura.status == GeographicUnit.Status.ACTIVE


def test_rerunning_is_a_no_op(frame, stranded_household):
    _run("--apply", "--actor", "ops.merge")
    output = _run("--apply", "--actor", "ops.merge")

    assert "No placeholder geographic units" in output
