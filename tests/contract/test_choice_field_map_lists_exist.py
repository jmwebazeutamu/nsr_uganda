"""Every choice list the field map names must exist in the catalogue.

`apps/data_management/choice_field_map.py` maps a payload path to the
ChoiceList that decodes it. When the named list is not in the
catalogue, `resolve_label` finds nothing, logs `ref_data.unmapped_code`
and returns the raw code — so the screen shows "13" where it should
show "Free - private", and nothing fails.

That is how `("housing", "tenure")` came to point at `dwelling_tenure`
while the seeded list is `tenure`: two names for one concept, and the
map picked the one nobody seeds.
"""

from __future__ import annotations

import pytest

from apps.data_management.choice_field_map import PAYLOAD_FIELDS
from apps.reference_data.models import ChoiceList

pytestmark = pytest.mark.django_db


def _named_lists() -> set[str]:
    return {list_name for list_name, _kind in PAYLOAD_FIELDS.values()}


def test_the_map_names_some_lists():
    """Guard the guard — an empty map would pass everything below."""
    assert len(_named_lists()) > 20


def test_every_named_list_is_in_the_catalogue():
    seeded = set(
        ChoiceList.objects.values_list("list_name", flat=True).distinct(),
    )
    missing = sorted(_named_lists() - seeded)
    assert not missing, (
        "choice_field_map names lists that no seed creates, so these "
        "fields render as raw codes and nothing fails: " + ", ".join(missing)
    )


def test_every_named_list_has_options():
    """A list with no options decodes nothing, which looks identical."""
    empty = sorted(
        ChoiceList.objects
        .filter(list_name__in=_named_lists(), options__isnull=True)
        .values_list("list_name", flat=True)
        .distinct(),
    )
    assert not empty, f"named lists with no options: {empty}"
