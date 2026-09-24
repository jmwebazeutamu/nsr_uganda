"""Every /api/v1/ path the console calls must resolve in Django.

The grievance intake's household picker shipped pointing at
`/api/v1/households/`. The registry app is mounted under
`/api/v1/data-management/`, so every search returned 404 and the modal
read "Search failed: HTTP 404" — no household could be attached to a
grievance at all. The endpoint had a canonical home already
(`_HH_API_BASE` in screens-registry.jsx); the picker hardcoded a second
one and guessed it wrong.

Nothing could have caught that from the JS side: a fetch to a wrong URL
is a runtime 404, and the component's own tests stub fetch. The URLs
are only checkable against the thing that serves them, which is here.

So: pull every `/api/v1/...` string literal out of the design layer and
ask Django's resolver about it. A path nobody serves is a screen that
cannot work.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from django.urls import Resolver404, resolve

DESIGN = pathlib.Path("design")

# `"/api/v1/..."` or `` `/api/v1/...` `` up to the quote or the first
# interpolation. The trailing group tells us WHICH ended it: a path cut
# short by `${` is a prefix with an id about to be appended
# (`/api/v1/consent/members/${memberId}`), and asking the resolver about
# the prefix alone is a false alarm. A path that ends at the quote is
# the whole URL, and that is the kind that shipped wrong.
_PATH = re.compile(r"""["'`](/api/v1/[^"'`${?\s]*)(\$\{)?""")

# Paths that take an id or other segment inline. The literal prefix is
# what we check; the full path needs a value we do not have here.
_PREFIX_ONLY = re.compile(r"/api/v1/[a-z0-9-]+/(?:[a-z0-9-]+/)*$")


def _console_sources() -> list[pathlib.Path]:
    """Every .jsx the two console manifests load, plus shared data."""
    out: list[pathlib.Path] = []
    for sub in ("v0.1/screens", "v0.1/components", "v0.1/data"):
        out.extend(
            p for p in (DESIGN / sub).rglob("*.jsx")
            if not p.name.endswith(".test.jsx")
        )
    return sorted(out)


def _candidate_paths():
    """(file, path) for every literal API path worth resolving."""
    for source in _console_sources():
        text = source.read_text()
        for match in _PATH.finditer(text):
            path, interpolated = match.group(1), match.group(2)
            if interpolated or not path.endswith("/"):
                continue
            yield source, path


def test_the_console_calls_at_least_one_api_path():
    """Guard the guard: a regex that stops matching would pass silently."""
    assert list(_candidate_paths()), "no API paths found — the scan broke"


@pytest.mark.django_db
def test_every_console_api_path_resolves():
    broken = []
    for source, path in _candidate_paths():
        if not _PREFIX_ONLY.match(path):
            continue
        try:
            resolve(path)
        except Resolver404:
            broken.append(f"{source}: {path}")
    assert not broken, (
        "the console calls paths Django does not serve — every one of "
        "these is a 404 at runtime:\n  " + "\n  ".join(sorted(set(broken)))
    )


@pytest.mark.django_db
def test_the_pickers_point_at_the_endpoints_they_mean():
    """Named explicitly, because these two are what broke.

    Resolving proves the path is served; these assert it is served by
    the view the picker actually needs.
    """
    picker = (DESIGN / "v0.1/components/search-picker.jsx").read_text()

    household = re.search(r'HOUSEHOLD_SEARCH_API = "([^"]+)"', picker).group(1)
    users = re.search(r'USER_SEARCH_API = "([^"]+)"', picker).group(1)

    assert resolve(household).func.cls.__name__ == "HouseholdViewSet"
    # user_search is a DRF @api_view, so the resolved callable is the
    # generated wrapper — the route's name is the stable identity.
    assert resolve(users).url_name == "users-search"


# ---------------------------------------------------------------------------
# The picker has to FIND things, not just reach an endpoint
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestHouseholdSearchFindsWhatOperatorsType:
    """The endpoint resolving is half of it. `q` searched the head's
    name, the Registry ID and the PARISH name only — so an operator
    typing "Kampala", the district they actually know, got nothing.
    """

    @pytest.fixture
    def household(self, django_user_model):
        from datetime import date

        from apps.data_management.models import Household, Member
        from apps.reference_data.models import GeographicUnit

        names = {
            "region": "Central", "sub_region": "Kampala Central",
            "district": "Kampala", "county": "Nakawa Division",
            "sub_county": "Bukoto", "parish": "Kamwokya",
            "village": "Kisenyi Cell",
        }
        nodes, parent = {}, None
        for level in ("region", "sub_region", "district", "county",
                      "sub_county", "parish", "village"):
            nodes[level] = GeographicUnit.objects.create(
                level=level, code=f"SRCH-{level.upper()}", name=names[level],
                parent=parent, effective_from=date(2026, 1, 1),
            )
            parent = nodes[level]
        hh = Household.objects.create(urban_rural="1", **nodes)
        Member.objects.create(
            household=hh, line_number=1, surname="Nakato",
            first_name="Sarah", sex="2",
        )
        hh.head_member = hh.members.first()
        hh.save()
        return hh

    def _search(self, django_user_model, term):
        from rest_framework.test import APIClient
        user = django_user_model.objects.create_user(
            username=f"searcher-{abs(hash(term)) % 9999}", password="p",
            is_superuser=True, is_staff=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        r = client.get("/api/v1/data-management/households/", {"q": term})
        assert r.status_code == 200, r.data
        return r.data.get("results", r.data)

    @pytest.mark.parametrize(
        "term",
        ["Nakato", "Sarah", "Kampala", "Bukoto", "Kamwokya", "Kisenyi"],
    )
    def test_every_name_an_operator_might_type_finds_it(
        self, household, django_user_model, term,
    ):
        rows = self._search(django_user_model, term)
        assert [r["id"] for r in rows] == [household.id], term

    def test_the_registry_id_still_finds_it(self, household, django_user_model):
        rows = self._search(django_user_model, household.id[:10])
        assert [r["id"] for r in rows] == [household.id]

    def test_a_geography_code_finds_it(self, household, django_user_model):
        rows = self._search(django_user_model, "SRCH-DISTRICT")
        assert [r["id"] for r in rows] == [household.id]

    def test_the_result_says_who_the_household_is(
        self, household, django_user_model,
    ):
        """A result set that can only show a ULID is searchable but
        unreadable — which is what made intake ask for a typed ID."""
        rows = self._search(django_user_model, "Nakato")
        assert rows[0]["head_member_name"] == "Nakato Sarah"
        assert rows[0]["district_name"] == "Kampala"

    def test_an_unrelated_term_finds_nothing(self, household, django_user_model):
        assert self._search(django_user_model, "Gulu") == []
