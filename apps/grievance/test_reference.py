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

    def test_it_is_a_year_and_a_running_number(self):
        assert ref.format_reference(2026, 1) == "GRM-2026-0001"
        assert ref.format_reference(2027, 1) == "GRM-2027-0001"

    def test_the_padding_is_a_minimum_not_a_cap(self):
        """The 10,000th case of a year is a case, not an error."""
        assert ref.format_reference(2026, 12) == "GRM-2026-0012"
        assert ref.format_reference(2026, 9999) == "GRM-2026-9999"
        assert ref.format_reference(2026, 10000) == "GRM-2026-10000"

    def test_it_is_short_enough_to_say_out_loud(self):
        assert len(ref.format_reference(2026, 1)) == 13

    def test_the_year_is_readable_back_out_of_it(self):
        assert ref.year_of("GRM-2026-0042") == 2026
        assert ref.year_of("nonsense") is None


class TestReadingItBack:
    """What somebody types after hearing it, or copying it off a slip."""

    @pytest.mark.parametrize("typed", [
        "GRM-2026-0001",
        "grm-2026-0001",
        "GRM20260001",
        "2026-0001",
        "20260001",
        "  GRM 2026 0001  ",
        "GRM_2026_0001",
        "GRM/2026/0001",
    ])
    def test_it_resolves_however_it_was_written(self, typed):
        assert ref.normalise(typed) == "GRM-2026-0001"

    @pytest.mark.parametrize("typed", [
        "GRM-2O26-OOO1",   # letter O for zero, throughout
        "GRM-2026-OOI1",   # and an I for one
    ])
    def test_it_forgives_the_confusable_characters(self, typed):
        """Digits only, so these cannot be ambiguous — but people who
        learned the old alphabet still type them."""
        assert ref.normalise(typed).startswith("GRM-20")

    @pytest.mark.parametrize("junk", [
        "", "   ", "GRM-", "GRM-2026", "01M3AT4JSSXFYG02CXC8S6K20X",
        "not a reference", "GRM-1899-0001", "GRM-3100-0001",
    ])
    def test_it_says_no_rather_than_guessing(self, junk):
        assert ref.normalise(junk) == ""
        assert ref.looks_like_a_reference(junk) is False

    def test_a_number_that_is_not_a_year_is_not_a_case(self):
        """A phone number is eight digits too."""
        assert ref.normalise("0772123456") == ""


class TestTheSequence:

    def test_it_starts_at_one(self):
        assert ref.next_reference(2030) == "GRM-2030-0001"

    def test_it_counts_up(self):
        assert [ref.next_reference(2031) for _ in range(3)] == [
            "GRM-2031-0001", "GRM-2031-0002", "GRM-2031-0003",
        ]

    def test_each_year_counts_separately(self):
        ref.next_reference(2032)
        ref.next_reference(2032)
        assert ref.next_reference(2033) == "GRM-2033-0001"
        assert ref.next_reference(2032) == "GRM-2032-0003"

    def test_the_counter_is_stored_not_derived(self):
        """Counting rows would renumber a year after a deletion and
        hand out a number somebody already has."""
        from apps.grievance.models import GrmReferenceSequence

        ref.next_reference(2034)
        ref.next_reference(2034)
        assert GrmReferenceSequence.objects.get(year=2034).last_number == 2

    def test_a_case_is_numbered_in_the_year_it_was_opened(self):
        """A case raised on 31 December keeps a number from the year it
        happened, whatever day the row gets written."""
        from datetime import datetime, timezone as tz

        from apps.grievance.models import Grievance

        g = open_grievance(category="other", description="new year's eve")
        Grievance.objects.filter(pk=g.pk).update(
            opened_at=datetime(2029, 12, 31, 23, 0, tzinfo=tz.utc),
        )
        g.refresh_from_db()
        assert ref.assign(g).startswith("GRM-2029-")


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


class TestItIsASequenceAndWhatThatCosts:
    """CLAUDE.md said never to use sequential externally-visible
    identifiers. ADR-0038 amends that for this one field, with the
    trade stated: a running number is guessable and it leaks volume.

    Guessable is not the same as a way in. These pin the thing that
    actually protects the records, so that if it ever stops being true
    the amendment stops being defensible.
    """

    def test_the_numbers_do_run_in_order(self):
        refs = [
            open_grievance(category="other", description=str(i)).reference
            for i in range(3)
        ]
        numbers = [int(r.split("-")[2]) for r in refs]
        assert numbers == sorted(numbers)
        assert numbers[1] == numbers[0] + 1
        assert numbers[2] == numbers[1] + 1

    def test_guessing_the_next_one_gets_you_nothing_out_of_scope(
        self, django_user_model,
    ):
        """The whole mitigation, in one test. An operator who holds one
        reference can trivially write down the next — and it opens
        nothing they could not already see."""
        household = _household("GUESS")
        mine = open_grievance(category="other", description="mine")
        theirs = open_grievance(category="other", description="theirs",
                                household_id=household.id)

        # Consecutive, so `theirs` is guessable from `mine`.
        assert int(theirs.reference.split("-")[2]) == \
            int(mine.reference.split("-")[2]) + 1

        outsider = django_user_model.objects.create_user(
            username="guesser", password="p",
        )
        OperatorScope.objects.get_or_create(
            user=outsider, scope_level=ScopeLevel.SUB_REGION,
            scope_code="SOMEWHERE-ELSE",
        )
        c = APIClient()
        c.force_authenticate(user=outsider)

        assert c.get(URL, {"q": theirs.reference}).data["results"] == []
        assert c.get(f"{URL}{theirs.id}/").status_code == 404

    def test_an_anonymous_caller_gets_nothing_at_all(self):
        g = open_grievance(category="other", description="x")
        r = APIClient().get(URL, {"q": g.reference})
        assert r.status_code in (401, 403)
