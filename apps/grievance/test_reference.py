"""The case number people actually use.

`Grievance.id` is a ULID: `01M3AT4JSSXFYG02CXC8S6K20X`. Right as a
primary key, unusable as a case number. A Parish Chief reads it back to
a citizen over the phone, writes it in a ledger, and quotes it on a
follow-up visit — twenty-six characters with no grouping and nothing in
the string to say when one has been dropped.

`reference` is the number for that job: `GRM-7K4P-2QX9`. The ULID stays
the key, stays in the URLs and stays in the audit chain.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.data_management.models import Household
from apps.grievance import reference as ref
from apps.grievance.models import Grievance
from apps.grievance.services import open_grievance
from apps.reference_data.models import GeographicUnit
from apps.security.models import OperatorScope, ScopeLevel

pytestmark = pytest.mark.django_db

URL = "/api/v1/grm/grievances/"


def _household(prefix: str = "REF") -> Household:
    nodes, parent = {}, None
    for level in ("region", "sub_region", "district", "county",
                  "sub_county", "parish", "village"):
        nodes[level] = GeographicUnit.objects.create(
            level=level, code=f"{prefix}-{level.upper()}",
            name=f"{prefix} {level}", parent=parent,
            effective_from=date(2026, 1, 1),
        )
        parent = nodes[level]
    return Household.objects.create(urban_rural="2", **nodes)


@pytest.fixture
def client(db, django_user_model):
    user = django_user_model.objects.create_user(username="desk", password="p")
    user.groups.add(Group.objects.get_or_create(name="nsr_admin")[0])
    OperatorScope.objects.get_or_create(
        user=user, scope_level=ScopeLevel.NATIONAL, scope_code="",
    )
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestTheShape:

    def test_it_is_short_enough_to_say_out_loud(self):
        value = ref.generate()
        assert len(value) == 13, value          # GRM-XXXX-XXXX
        assert len(value.replace("-", "")) == 11

    def test_it_is_grouped(self):
        prefix, a, b = ref.generate().split("-")
        assert prefix == "GRM"
        assert len(a) == len(b) == 4

    def test_it_avoids_the_characters_people_confuse(self):
        """Crockford base32: no I, L, O or U. No I/1, no O/0, and no U
        keeps accidental words out of a citizen-facing number."""
        for banned in "ILOU":
            assert banned not in ref.ALPHABET
        for _ in range(200):
            body = "".join(ref.generate().split("-")[1:])
            assert all(c in ref.ALPHABET for c in body), body

    def test_many_references_do_not_collide(self):
        assert len({ref.generate() for _ in range(2000)}) == 2000


class TestReadingItBack:
    """What somebody types after hearing it, or copying it off a slip."""

    @pytest.mark.parametrize("typed", [
        "GRM-7K4P-2QX9",
        "grm-7k4p-2qx9",
        "GRM7K4P2QX9",
        "7K4P-2QX9",
        "7k4p2qx9",
        "  GRM 7K4P 2QX9  ",
        "GRM_7K4P_2QX9",
    ])
    def test_it_resolves_however_it_was_written(self, typed):
        assert ref.normalise(typed) == "GRM-7K4P-2QX9"

    @pytest.mark.parametrize("typed,expected", [
        ("GRM-OK4P-2QX9", "GRM-0K4P-2QX9"),   # O heard as zero
        ("GRM-7K4P-2QI9", "GRM-7K4P-2Q19"),   # I written for one
        ("GRM-7K4P-2Ql9", "GRM-7K4P-2Q19"),   # lower-case l for one
    ])
    def test_it_forgives_the_confusable_characters(self, typed, expected):
        assert ref.normalise(typed) == expected

    @pytest.mark.parametrize("junk", [
        "", "   ", "GRM-", "GRM-7K4P", "01M3AT4JSSXFYG02CXC8S6K20X",
        "GRM-7K4P-2QX99", "not a reference",
    ])
    def test_it_says_no_rather_than_guessing(self, junk):
        assert ref.normalise(junk) == ""
        assert ref.looks_like_a_reference(junk) is False


class TestEveryGrievanceHasOne:

    def test_one_is_assigned_on_creation(self):
        g = open_grievance(category="other", description="x")
        assert g.reference
        assert ref.normalise(g.reference) == g.reference

    def test_two_grievances_get_different_ones(self):
        a = open_grievance(category="other", description="a")
        b = open_grievance(category="other", description="b")
        assert a.reference != b.reference

    def test_it_does_not_change_when_the_case_moves(self):
        """A number quoted to a citizen has to keep meaning that case."""
        from apps.grievance.services import resolve

        g = open_grievance(category="other", description="x")
        original = g.reference
        resolve(g, actor="officer", narrative="Sorted at the parish office")
        g.refresh_from_db()
        assert g.reference == original

    def test_the_database_refuses_a_duplicate(self):
        a = open_grievance(category="other", description="a")
        b = open_grievance(category="other", description="b")
        with pytest.raises(IntegrityError), transaction.atomic():
            Grievance.objects.filter(pk=b.pk).update(reference=a.reference)

    def test_the_ulid_is_still_the_key(self):
        """The reference is for people; nothing about the record's
        identity moved."""
        g = open_grievance(category="other", description="x")
        assert Grievance._meta.pk.name == "id"
        assert len(g.id) == 26
        assert Grievance.objects.get(pk=g.id) == g


class TestFindingACaseByItsNumber:

    def test_the_api_serves_it(self, client):
        g = open_grievance(category="other", description="x")
        r = client.get(f"{URL}{g.id}/")
        assert r.status_code == 200
        assert r.data["reference"] == g.reference

    def test_searching_for_it_finds_the_case(self, client):
        g = open_grievance(category="other", description="x")
        open_grievance(category="other", description="another")

        r = client.get(URL, {"q": g.reference})
        assert r.status_code == 200
        assert [row["id"] for row in r.data["results"]] == [g.id]

    @pytest.mark.parametrize("how", [
        str.lower,
        lambda s: s.replace("-", ""),
        lambda s: s.replace("GRM-", ""),
        lambda s: f"  {s}  ",
    ])
    def test_it_finds_the_case_however_it_was_typed(self, client, how):
        g = open_grievance(category="other", description="x")
        r = client.get(URL, {"q": how(g.reference)})
        assert [row["id"] for row in r.data["results"]] == [g.id], how

    def test_a_partial_still_narrows(self, client):
        g = open_grievance(category="other", description="x")
        fragment = g.reference.split("-")[1]
        r = client.get(URL, {"q": fragment})
        assert g.id in {row["id"] for row in r.data["results"]}

    def test_the_ulid_still_works_as_a_search_term(self, client):
        g = open_grievance(category="other", description="x")
        r = client.get(URL, {"q": g.id})
        assert [row["id"] for row in r.data["results"]] == [g.id]

    def test_a_reference_outside_your_scope_finds_nothing(
        self, django_user_model,
    ):
        """Searching is not a way round the scope rule: a number you
        were told still only opens a case you may see."""
        household = _household("SCOPED")
        g = open_grievance(category="other", description="elsewhere",
                           household_id=household.id)

        outsider = django_user_model.objects.create_user(
            username="other.area", password="p",
        )
        OperatorScope.objects.get_or_create(
            user=outsider, scope_level=ScopeLevel.SUB_REGION,
            scope_code="SOMEWHERE-ELSE",
        )
        c = APIClient()
        c.force_authenticate(user=outsider)

        r = c.get(URL, {"q": g.reference})
        assert r.status_code == 200
        assert r.data["results"] == []


class TestItIsNotASequence:
    """CLAUDE.md forbids sequential externally-visible identifiers. A
    running case number would tell anyone holding two references how
    many grievances the registry took between them, and let them walk
    the range."""

    def test_consecutive_grievances_are_not_adjacent(self):
        refs = [
            open_grievance(category="other", description=str(i)).reference
            for i in range(6)
        ]
        bodies = ["".join(r.split("-")[1:]) for r in refs]
        assert len(set(bodies)) == 6
        # Decoded as base32, consecutive cases are nowhere near each
        # other. A sequence would differ by one.
        values = [
            sum(ref.ALPHABET.index(c) * (32 ** i)
                for i, c in enumerate(reversed(b)))
            for b in bodies
        ]
        gaps = [abs(b - a) for a, b in zip(values, values[1:])]
        assert all(g > 1000 for g in gaps), gaps
