"""Registry browse API tests — US-005.

Covers the filters + aggregates added on the Household and Member
viewsets to back the Registry browse screens. Each filter is asserted
to narrow the list, and the aggregates endpoint is asserted to honour
the same filter params so the KPI strip reflects the visible slice.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.data_management.models import Disability, Household, Member
from apps.reference_data.models import GeographicUnit
from apps.reference_data.services import clear_resolver_cache

URL_HOUSEHOLDS = "/api/v1/data-management/households/"
URL_HH_AGGREGATES = "/api/v1/data-management/households/aggregates/"
URL_MEMBERS = "/api/v1/data-management/members/"
URL_M_AGGREGATES = "/api/v1/data-management/members/aggregates/"


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def api(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_superuser(
        username="registry-test", password="p",
    )
    c = APIClient()
    c.force_authenticate(user=u)
    return c


def _geo_chain(label_suffix: str, sub_region_code: str) -> dict:
    """Build a seven-level UBOS chain rooted at a fresh region. Suffix
    keeps codes unique across fixture calls so the same test can seed
    two parallel chains for the sub_region-filter tests."""
    nodes: dict[str, GeographicUnit] = {}
    chain = [
        ("region",     "r",  None,        f"R-{label_suffix}"),
        ("sub_region", "sr", "r",         sub_region_code),
        ("district",   "d",  "sr",        f"D-{label_suffix}"),
        ("county",     "c",  "d",         f"C-{label_suffix}"),
        ("sub_county", "sc", "c",         f"SC-{label_suffix}"),
        ("parish",     "p",  "sc",        f"P-{label_suffix}"),
        ("village",    "v",  "p",         f"V-{label_suffix}"),
    ]
    for level, key, parent, code in chain:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=code, name=f"{level.title()}-{label_suffix}",
            parent=nodes.get(parent),
            effective_from=date(2026, 1, 1),
        )
    return nodes


def _make_household(geo, **over):
    return Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"],
        county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
        village=geo["v"], urban_rural="2", **over,
    )


def _make_member(hh, line=1, **over):
    return Member.objects.create(
        household=hh, line_number=line,
        surname=over.pop("surname", "Okello"),
        first_name=over.pop("first_name", "James"),
        sex=over.pop("sex", "1"),
        age_years=over.pop("age_years", 30),
        relationship_to_head=over.pop("relationship_to_head", ""),
        nin_status=over.pop("nin_status", "8"),
        **over,
    )


@pytest.fixture
def seeded_buganda(db):
    """One Buganda sub-region with two households and a handful of
    members. Names + nin_status + sex vary across rows so individual
    filters can be exercised against a deterministic slice."""
    geo = _geo_chain("BUGANDA", "SR-BUGANDA-SOUTH")

    hh1 = _make_household(
        geo, current_vulnerability_band="Poorest 40%",
        current_intake_source="DIH",
    )
    hh2 = _make_household(
        geo, current_vulnerability_band="Middle 40%",
        current_intake_source="Walk-in",
    )

    head1 = _make_member(
        hh1, line=1, surname="Nsubuga", first_name="Ruth",
        sex="2", age_years=42, relationship_to_head="01",
        nin_status="1",
    )
    hh1.head_member = head1
    hh1.save()

    _make_member(
        hh1, line=2, surname="Tumusiime", first_name="Samuel",
        sex="1", age_years=46, relationship_to_head="02",
        nin_status="1",
    )
    child = _make_member(
        hh1, line=3, surname="Okello", first_name="James",
        sex="1", age_years=14, relationship_to_head="03",
        nin_status="3",
    )

    head2 = _make_member(
        hh2, line=1, surname="Mukasa", first_name="Patrick",
        sex="1", age_years=51, relationship_to_head="01",
        nin_status="1",
    )
    hh2.head_member = head2
    hh2.save()
    _make_member(
        hh2, line=2, surname="Mukasa", first_name="Joyce",
        sex="2", age_years=65, relationship_to_head="02",
        nin_status="1",
    )

    return {"geo": geo, "hh1": hh1, "hh2": hh2, "child": child}


@pytest.fixture
def seeded_karamoja(db):
    """Parallel sub-region so the sub_region filter has something to
    exclude. One household, one head with a WG-SS disability flag."""
    geo = _geo_chain("KARAMOJA", "SR-KARAMOJA")
    hh = _make_household(
        geo, current_vulnerability_band="Poorest 20%",
        current_intake_source="Walk-in",
    )
    head = _make_member(
        hh, line=1, surname="Lokol", first_name="Naume",
        sex="2", age_years=31, relationship_to_head="01",
        nin_status="1",
    )
    hh.head_member = head
    hh.save()
    # Disability OneToOne — wg_disability_flag computed on save() per
    # ADR-0022, so seeing="03" flips wg_disability_flag to True.
    Disability.objects.create(member=head, seeing="03")
    return {"geo": geo, "hh": hh, "head": head}


# ───────────────────────────────────────────────────────────────
# Household list filters
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestHouseholdFilters:

    def test_q_matches_head_member_surname(self, api, seeded_buganda):
        r = api.get(f"{URL_HOUSEHOLDS}?q=nsubuga")
        ids = {h["id"] for h in r.data["results"]}
        assert ids == {seeded_buganda["hh1"].id}

    def test_q_matches_household_id_substring(self, api, seeded_buganda):
        partial = seeded_buganda["hh1"].id[:6].lower()
        r = api.get(f"{URL_HOUSEHOLDS}?q={partial}")
        ids = {h["id"] for h in r.data["results"]}
        assert seeded_buganda["hh1"].id in ids

    def test_sub_region_narrows_to_that_chain(
        self, api, seeded_buganda, seeded_karamoja,
    ):
        r = api.get(f"{URL_HOUSEHOLDS}?sub_region=SR-KARAMOJA")
        ids = {h["id"] for h in r.data["results"]}
        assert ids == {seeded_karamoja["hh"].id}

    def test_band_filter(self, api, seeded_buganda):
        r = api.get(f"{URL_HOUSEHOLDS}?band=Middle 40%")
        ids = {h["id"] for h in r.data["results"]}
        assert ids == {seeded_buganda["hh2"].id}

    def test_intake_source_filter(self, api, seeded_buganda, seeded_karamoja):
        r = api.get(f"{URL_HOUSEHOLDS}?intake_source=Walk-in")
        ids = {h["id"] for h in r.data["results"]}
        assert seeded_buganda["hh2"].id in ids
        assert seeded_karamoja["hh"].id in ids
        assert seeded_buganda["hh1"].id not in ids


# ───────────────────────────────────────────────────────────────
# Household aggregates
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestHouseholdAggregates:

    def test_total_count_matches_visible_set(
        self, api, seeded_buganda, seeded_karamoja,
    ):
        r = api.get(URL_HH_AGGREGATES)
        assert r.status_code == 200
        assert r.data["total"] == 3
        assert r.data["registered"] == 3
        assert r.data["provisional_pending"] == 0
        # No enrolments seeded — programme_enrolled stays at 0.
        assert r.data["programme_enrolled"] == 0

    def test_aggregates_honour_sub_region_filter(
        self, api, seeded_buganda, seeded_karamoja,
    ):
        r = api.get(f"{URL_HH_AGGREGATES}?sub_region=SR-KARAMOJA")
        assert r.data["total"] == 1
        assert r.data["registered"] == 1


# ───────────────────────────────────────────────────────────────
# Member list filters
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestMemberFilters:

    def test_q_matches_surname(self, api, seeded_buganda):
        r = api.get(f"{URL_MEMBERS}?q=Mukasa")
        names = {m["surname"] for m in r.data["results"]}
        assert names == {"Mukasa"}

    def test_sex_filter_returns_only_one_code(self, api, seeded_buganda):
        r = api.get(f"{URL_MEMBERS}?sex=2")
        assert {m["sex"] for m in r.data["results"]} == {"2"}

    def test_relationship_to_head_filter(self, api, seeded_buganda):
        r = api.get(f"{URL_MEMBERS}?relationship_to_head=01")
        rels = {m["relationship_to_head"] for m in r.data["results"]}
        assert rels == {"01"}

    def test_household_filter_narrows_to_that_household(
        self, api, seeded_buganda,
    ):
        hh_id = seeded_buganda["hh1"].id
        r = api.get(f"{URL_MEMBERS}?household={hh_id}")
        hh_ids = {m["household"] for m in r.data["results"]}
        assert hh_ids == {hh_id}

    def test_nin_status_filter(self, api, seeded_buganda):
        r = api.get(f"{URL_MEMBERS}?nin_status=3")
        statuses = {m["nin_status"] for m in r.data["results"]}
        assert statuses == {"3"}

    def test_age_band_10_14_returns_only_teen(self, api, seeded_buganda):
        r = api.get(f"{URL_MEMBERS}?age_band=10-14")
        ages = {m["age_years"] for m in r.data["results"]}
        assert ages == {14}

    def test_age_band_60_plus(self, api, seeded_buganda):
        r = api.get(f"{URL_MEMBERS}?age_band=60%2B")  # "60+" url-encoded
        ages = {m["age_years"] for m in r.data["results"]}
        assert ages == {65}

    def test_sub_region_filter(
        self, api, seeded_buganda, seeded_karamoja,
    ):
        r = api.get(f"{URL_MEMBERS}?sub_region=SR-KARAMOJA")
        assert all(
            m["household"] == seeded_karamoja["hh"].id
            for m in r.data["results"]
        )

    def test_disability_any_returns_only_flagged(
        self, api, seeded_buganda, seeded_karamoja,
    ):
        r = api.get(f"{URL_MEMBERS}?disability=any")
        ids = {m["id"] for m in r.data["results"]}
        assert ids == {seeded_karamoja["head"].id}

    def test_disability_domain_seeing(
        self, api, seeded_buganda, seeded_karamoja,
    ):
        r = api.get(f"{URL_MEMBERS}?disability=seeing")
        ids = {m["id"] for m in r.data["results"]}
        assert ids == {seeded_karamoja["head"].id}


# ───────────────────────────────────────────────────────────────
# Member aggregates
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestMemberAggregates:

    def test_baseline_counts(
        self, api, seeded_buganda, seeded_karamoja,
    ):
        r = api.get(URL_M_AGGREGATES)
        assert r.status_code == 200
        # 5 buganda members + 1 karamoja head = 6
        assert r.data["total_individuals"] == 6
        # The Buganda child (age 14) is the only under-18.
        assert r.data["children_under_18"] == 1
        # Joyce (65) is the only 60+.
        assert r.data["elderly_60_plus"] == 1
        # Only Karamoja head has wg_disability_flag.
        assert r.data["with_disability_wgss"] == 1
        # Ruth + Joyce + Naume = 3 females.
        assert r.data["female"] == 3
        # Every head + spouse seeded with nin_status="1".
        assert r.data["nin_verified"] == 5

    def test_aggregates_honour_sub_region_filter(
        self, api, seeded_buganda, seeded_karamoja,
    ):
        r = api.get(f"{URL_M_AGGREGATES}?sub_region=SR-KARAMOJA")
        assert r.data["total_individuals"] == 1
        assert r.data["with_disability_wgss"] == 1
        assert r.data["female"] == 1
        assert r.data["children_under_18"] == 0
