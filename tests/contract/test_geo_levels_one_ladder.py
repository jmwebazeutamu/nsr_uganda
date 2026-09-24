"""The geographic ladder is the same ladder in Python and in the console.

Instance after instance of the same defect class: one concept named in
two places, kept in step by nobody. This one is the UBOS hierarchy, and
it has drifted twice in a week —

  * ``apps/data_explorer/query_builder.field_map`` carried three of the
    seven rungs, so a county-scoped aggregate returned the whole
    country;
  * ``design/v0.1/screens/screens-admin-refdata-geography.jsx`` and
    ``design/v0.1/components/scope-edit-modal.jsx`` both declared
    ``GEO_LEVELS`` at the top level of a shared global scope, one as an
    array of strings and one as an array of objects.

So: ``GeographicUnit.Level`` is the frame. ``apps/data_explorer/
geography.py`` derives the backend ladder from it, and
``design/v0.1/data/geo-levels.jsx`` is the console's single copy. This
test asserts on **both originals at once** — parsing the JSX rather than
importing a mirror of it — because a test written against either one
alone passes happily while the other says something else.
"""

from __future__ import annotations

import pathlib
import re

from apps.data_explorer.geography import LADDER, NATIONAL
from apps.reference_data.models import GeographicUnit

GEO_LEVELS_JSX = pathlib.Path("design/v0.1/data/geo-levels.jsx")

# `{ value: "sub_region", label: "Sub-region" },`
_ENTRY = re.compile(
    r"""\{\s*value:\s*["'](?P<value>[a-z_]+)["']\s*,\s*"""
    r"""label:\s*["'](?P<label>[^"']+)["']\s*,?\s*\}""",
)


def _jsx_ladder() -> list[tuple[str, str]]:
    source = GEO_LEVELS_JSX.read_text()
    start = source.index("const GEO_LEVELS = [")
    end = source.index("]", start)
    return [
        (m.group("value"), m.group("label"))
        for m in _ENTRY.finditer(source[start:end])
    ]


def test_jsx_ladder_is_the_ubos_frame_in_order():
    """Same rungs, same order, as GeographicUnit.Level declares them."""
    assert [value for value, _label in _jsx_ladder()] == [
        level.value for level in GeographicUnit.Level
    ]


def test_jsx_ladder_matches_the_backend_ladder():
    """And the same ladder the Data Explorer filters on, minus the
    synthetic `national` root, which is not a UBOS unit."""
    assert [value for value, _label in _jsx_ladder()] == [
        name for name in LADDER if name != NATIONAL
    ]


def test_county_is_present_in_both():
    """Named on its own because county is the rung that keeps vanishing."""
    assert "county" in {value for value, _label in _jsx_ladder()}
    assert "county" in LADDER
    assert "county" in {level.value for level in GeographicUnit.Level}


def test_the_console_declares_the_ladder_exactly_once():
    """A second top-level `const GEO_LEVELS` anywhere in the design
    layer re-creates the collision: these files load as classic scripts
    sharing one global scope, so the last one loaded wins silently."""
    offenders = [
        str(path)
        for path in pathlib.Path("design").rglob("*.jsx")
        if path != GEO_LEVELS_JSX
        and not path.name.endswith(".test.jsx")
        and re.search(r"^const GEO_LEVELS\s*=", path.read_text(), re.MULTILINE)
    ]
    assert not offenders, f"GEO_LEVELS redeclared in: {offenders}"


# ---------------------------------------------------------------------------
# The screens read what the API serves — for every rung, not four of them
# ---------------------------------------------------------------------------

def test_household_serializer_names_every_rung():
    """`HouseholdSerializer` exposes `<level>_name` for the whole ladder.

    It already did. The household detail screen's Location card did not
    read them: it listed village, parish, district and sub-region and
    silently dropped region, county and sub-county, so a household in
    Kasese displayed no county at all. The card now renders from the
    shared ladder, and this asserts the API side of that contract so a
    new rung cannot be served-but-unshowable or shown-but-unserved.
    """
    from apps.data_management.api import HouseholdSerializer

    declared = set(HouseholdSerializer().fields)
    for level, _label in _jsx_ladder():
        assert f"{level}_name" in declared, f"no {level}_name on the serializer"
        assert level in declared, f"no {level} code field on the serializer"


def test_the_location_card_renders_every_rung():
    """The card builds its rows from GEO_LEVELS rather than a list.

    Asserted by reading the source: the rows come from the shared
    ladder, so adding a rung to the ladder adds it to the screen. A
    hand-written row per level is what dropped county.
    """
    screen = pathlib.Path("design/v0.1/screens/screens-household.jsx").read_text()
    card = screen[screen.index('<KVCard title="Location"'):]
    card = card[:card.index("/>")]
    assert "GEO_LEVELS" in card, (
        "the Location card no longer derives its rows from the shared "
        "ladder — a level will go missing from the screen again"
    )
    # And no level is hand-listed beside it.
    for _level, label in _jsx_ladder():
        assert f'"{label}"' not in card, (
            f"{label} is hand-written into the Location card as well as "
            "coming from the ladder"
        )
