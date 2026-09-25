"""Four entities, one numbering scheme.

Grievance, ChangeRequest, DataRequest and Referral all carry a ULID
primary key and a case number people can quote:

    GRM-2026-0001   UPD-2026-0001   DRS-2026-0001   REF-2026-0001

The scheme, the normalisation and the counter live in one module and
one table. This file is the reason they have to stay that way: four
copies of "take the next number" would drift, and the first thing to
drift is whether a rolled-back transaction burns its number — which
nobody notices until the numbering has gaps and nobody can say why.

Parametrised over all four deliberately. A test written per module is a
test that passes for three of them while the fourth quietly does
something else.
"""

from __future__ import annotations

import itertools

import pytest

from apps.reference_data import references as ref
from apps.reference_data.models import ReferenceSequence

pytestmark = pytest.mark.django_db

PREFIXES = list(ref.PREFIXES)


# --- the scheme itself ------------------------------------------------

class TestTheScheme:

    @pytest.mark.parametrize("prefix", PREFIXES)
    def test_it_is_a_module_code_a_year_and_a_count(self, prefix):
        assert ref.format_reference(prefix, 2026, 1) == f"{prefix}-2026-0001"

    @pytest.mark.parametrize("prefix", PREFIXES)
    def test_the_padding_is_a_minimum_not_a_cap(self, prefix):
        assert ref.format_reference(prefix, 2026, 10000) == f"{prefix}-2026-10000"

    def test_the_prefixes_are_the_sad_module_codes(self):
        """GRM, UPD, DRS, REF — so the number says which queue to look
        in before anyone has typed it anywhere."""
        assert set(PREFIXES) == {"GRM", "UPD", "DRS", "REF"}

    @pytest.mark.parametrize("prefix", PREFIXES)
    def test_the_year_and_prefix_read_back_out_of_it(self, prefix):
        value = ref.format_reference(prefix, 2026, 42)
        assert ref.prefix_of(value) == prefix
        assert ref.year_of(value) == 2026


class TestReadingItBack:

    @pytest.mark.parametrize("prefix", PREFIXES)
    @pytest.mark.parametrize("shape", [
        "{p}-2026-0001", "{p}20260001", "  {p} 2026 0001  ",
        "{p}_2026_0001", "{p}/2026/0001",
    ])
    def test_it_resolves_however_it_was_written(self, prefix, shape):
        typed = shape.format(p=prefix).lower()
        assert ref.normalise(typed) == f"{prefix}-2026-0001"

    @pytest.mark.parametrize("prefix", PREFIXES)
    def test_the_prefix_may_be_dropped_when_the_caller_names_one(self, prefix):
        assert ref.normalise("2026-0001", prefix=prefix) == f"{prefix}-2026-0001"

    def test_a_bare_number_alone_is_refused(self):
        """"2026-0001" is four different records. Guessing between them
        is worse than asking."""
        assert ref.normalise("2026-0001") == ""

    @pytest.mark.parametrize("prefix", PREFIXES)
    def test_it_forgives_the_confusable_characters(self, prefix):
        assert ref.normalise(f"{prefix}-2O26-OOI1") == f"{prefix}-2026-0011"

    def test_asking_for_one_prefix_does_not_match_another(self):
        assert ref.normalise("GRM-2026-0001", prefix="UPD") == ""

    @pytest.mark.parametrize("junk", [
        "", "   ", "GRM-", "GRM-2026", "XXX-2026-0001",
        "01M3AT4JSSXFYG02CXC8S6K20X", "0772123456", "GRM-1899-0001",
    ])
    def test_it_says_no_rather_than_guessing(self, junk):
        assert ref.normalise(junk) == ""
        assert ref.looks_like_a_reference(junk) is False


# --- one counter, four callers ----------------------------------------

class TestTheSharedCounter:

    @pytest.mark.parametrize("prefix", PREFIXES)
    def test_each_module_starts_at_one(self, prefix):
        assert ref.next_reference(prefix, 2040) == f"{prefix}-2040-0001"

    def test_the_modules_count_independently(self):
        """One table, four counters. UPD's tenth case is UPD-2041-0010
        however many grievances came in beside it."""
        for _ in range(3):
            ref.next_reference("GRM", 2041)
        assert ref.next_reference("UPD", 2041) == "UPD-2041-0001"
        assert ref.next_reference("GRM", 2041) == "GRM-2041-0004"

    @pytest.mark.parametrize("prefix", PREFIXES)
    def test_each_year_counts_separately(self, prefix):
        ref.next_reference(prefix, 2042)
        assert ref.next_reference(prefix, 2043) == f"{prefix}-2043-0001"

    def test_there_is_one_table(self):
        """Not four. A counter per module is four chances to disagree
        about what a rollback does."""
        ref.next_reference("GRM", 2044)
        ref.next_reference("DRS", 2044)
        rows = ReferenceSequence.objects.filter(year=2044)
        assert {r.prefix for r in rows} == {"GRM", "DRS"}

    def test_a_rollback_gives_the_number_back(self):
        """The property that keeps a year contiguous, and the one that
        would silently differ between four implementations."""
        from django.db import transaction

        first = ref.next_reference("REF", 2045)
        try:
            with transaction.atomic():
                ref.next_reference("REF", 2045)
                raise RuntimeError("abandoned")
        except RuntimeError:
            pass
        second = ref.next_reference("REF", 2045)
        assert first == "REF-2045-0001"
        assert second == "REF-2045-0002", (
            "the abandoned transaction burned its number — the year now "
            "has a gap nobody can explain"
        )

    def test_an_unknown_prefix_is_refused(self):
        with pytest.raises(ValueError, match="unknown reference prefix"):
            ref.next_reference("ZZZ", 2026)


# --- every record actually gets one -----------------------------------

def _grievance():
    from apps.grievance.services import open_grievance
    return open_grievance(category="other", description="x")


def _change_request():
    from apps.update_workflow.models import ChangeRequest
    return ChangeRequest.objects.create(
        entity_type="household", entity_id="01TESTHOUSEHOLD0000000000",
        change_type="correction", changes={}, requester="tester",
    )


#: Each maker is called more than once per test, so anything with a
#: unique column of its own needs a fresh value each time.
_seq = itertools.count(1)


def _data_request():
    from datetime import date

    from apps.data_requests.models import DataRequest
    from apps.partners.models import DataSharingAgreement, Partner

    n = next(_seq)
    partner = Partner.objects.create(code=f"T-PART-{n}", name=f"Partner {n}")
    dsa = DataSharingAgreement.objects.create(
        partner=partner, reference=f"DSA-CASENUM-{n}", version=1,
        effective_from=date(2026, 1, 1), effective_to=date(2030, 12, 31),
    )
    return DataRequest.objects.create(dsa=dsa, requester="tester")


def _referral():
    from datetime import date

    from apps.data_management.models import Household
    from apps.partners.models import Partner, Programme
    from apps.referral.models import Referral
    from apps.reference_data.models import GeographicUnit

    n = next(_seq)
    nodes, parent = {}, None
    for level in ("region", "sub_region", "district", "county",
                  "sub_county", "parish", "village"):
        nodes[level] = GeographicUnit.objects.create(
            level=level, code=f"CN{n}-{level.upper()}", name=level,
            parent=parent, effective_from=date(2026, 1, 1),
        )
        parent = nodes[level]
    household = Household.objects.create(urban_rural="2", **nodes)
    partner = Partner.objects.create(code=f"R-PART-{n}", name=f"Ref Partner {n}")
    programme = Programme.objects.create(
        partner=partner, code=f"R-PROG-{n}", name=f"Ref Programme {n}",
    )
    return Referral.objects.create(household=household, programme=programme)


MAKERS = [
    ("GRM", _grievance),
    ("UPD", _change_request),
    ("DRS", _data_request),
    ("REF", _referral),
]


class TestEveryRecordGetsOne:

    @pytest.mark.parametrize("prefix,make", MAKERS)
    def test_a_new_record_is_numbered(self, prefix, make):
        record = make()
        assert record.reference.startswith(f"{prefix}-")
        assert ref.normalise(record.reference) == record.reference

    @pytest.mark.parametrize("prefix,make", MAKERS)
    def test_two_records_get_different_numbers(self, prefix, make):
        assert make().reference != make().reference

    @pytest.mark.parametrize("prefix,make", MAKERS)
    def test_the_ulid_is_still_the_key(self, prefix, make):
        record = make()
        assert len(record.id) == 26
        assert type(record)._meta.pk.name == "id"

    @pytest.mark.parametrize("prefix,make", MAKERS)
    def test_the_number_does_not_change_when_the_record_is_saved_again(
        self, prefix, make,
    ):
        """A number quoted to somebody has to keep meaning that record."""
        record = make()
        original = record.reference
        record.save()
        record.refresh_from_db()
        assert record.reference == original

    @pytest.mark.parametrize("prefix,make", MAKERS)
    def test_the_column_refuses_a_duplicate(self, prefix, make):
        from django.db import IntegrityError, transaction

        a, b = make(), make()
        Model = type(a)
        with pytest.raises(IntegrityError), transaction.atomic():
            Model.objects.filter(pk=b.pk).update(reference=a.reference)
