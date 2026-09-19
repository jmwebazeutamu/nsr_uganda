"""Questions the enumerator asks must end up in the registry.

Three sets of answers were being collected in the field, carried in the
staged payload, and then dropped:

  * **D3-D8, the Washington Group short set.** Every connector puts them
    in the member's `health` section — which is what
    `update_workflow.MEMBER_PAYLOAD_FIELD_PATHS` documents as the
    canonical path — while `_create_disability` read a `disability`
    section no connector emits. 1,283 members on the dev registry, zero
    Disability rows. WG status is a targeting input for vulnerability
    programmes.
  * **C12-C15, parental survival and the parents' roster lines.** The
    Kobo mapping never read them, so `mother_alive_flag`,
    `father_alive_flag`, `mother_line_number` and `father_line_number`
    were null on all 1,283, and the two rules that read them
    (AC-PARENT-AGE, AC-ORPHAN-FLAG) had nothing to work with.
  * **The reported household size.** Carried inside `interview`, where
    neither `Household.reported_household_size` nor
    AC-MEMBER-COUNT-MATCH's `$reported_household_size` could see it.

Each case here goes from a raw submission in the shape the live form
actually posts — the field names are taken from RawLanding rows on the
dev registry — through to the column.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
from apps.ingestion_hub.models import (
    Connector,
    DataProvisionAgreement,
    SourceSystem,
    SourceSystemKind,
)
from apps.ingestion_hub.services import (
    land_payload,
    promote_stage_record,
    stage_from_landing,
    start_connector_run,
)
from apps.reference_data.models import GeographicUnit

#: The ladder the submissions below reference. Same shape as the one in
#: tests.py, kept local so this file stands on its own.
GEO = {
    "region": "T-R", "sub_region": "T-SR", "district": "T-D",
    "county": "T-C", "sub_county": "T-SC", "parish": "T-P",
    "village": "T-V",
}


@pytest.fixture
def geo(db):
    """Create the ladder using the codes the connector *derives*.

    Kobo sends form values; the connector turns them into UBOS codes
    (`R-{slug}`, `SR-{sub}-{region}`, `{parish}.{village}`). Planting
    the form values would leave promotion looking for units that do not
    exist — so the fixture asks the connector what it will produce.
    """
    derived = kobo_to_canonical(_submission([_member(1, "01")]))["geographic"]
    parent = None
    for level in ("region", "sub_region", "district", "county",
                  "sub_county", "parish", "village"):
        parent = GeographicUnit.objects.create(
            level=level, code=derived[level], name=derived[level],
            parent=parent, effective_from=date(2026, 1, 1),
        )
    return derived


@pytest.fixture
def connector(db):
    src = SourceSystem.objects.create(
        code="KOBO-FIELDS", name="Kobo", kind=SourceSystemKind.KOBO,
    )
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-KOBO-FIELDS",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    return Connector.objects.create(source_system=src, name="kobo-fields")


def _promote(connector, raw: dict):
    """Raw submission -> staged -> promoted. The whole path, because the
    gaps this file covers each sat between two of those steps."""
    canonical = kobo_to_canonical(raw)
    run = start_connector_run(connector)
    landing = land_payload(run, raw)
    stage = stage_from_landing(landing, canonical_payload=canonical)
    promote_stage_record(stage, actor="test")
    return stage


def _member(index: int, relationship: str, **overrides) -> dict:
    row = {
        "member_index": index,
        "c1_full_name": f"Test Member{index}",
        "c2_relationship": relationship,
        "c4_sex": "2",
        "c6_age_years": "40",
        "c8_nin_status": "0",
    }
    row.update(overrides)
    return row


def _submission(members: list[dict], **overrides) -> dict:
    raw = {
        "a0_region": GEO["region"],
        "a1_subregion": GEO["sub_region"],
        "a2_district_city": GEO["district"],
        "a3_county_municipality": GEO["county"],
        "a4_subcounty_division_tc": GEO["sub_county"],
        "a5_parish_ward": GEO["parish"],
        "a6_lc1_village_cell": GEO["village"],
        "a7_rural_urban": "2",
        "household_members": members,
    }
    raw.update(overrides)
    return raw


# --- C12-C15: the parents --------------------------------------------------

def test_parental_survival_and_lines_are_mapped():
    canonical = kobo_to_canonical(_submission([
        _member(1, "01"),
        _member(
            2, "04",
            c12_mother_alive="1", c13_father_alive="2",
            c15_mother_line="1", c6_age_years="9",
        ),
    ]))
    child = canonical["members"][1]
    assert child["mother_alive_flag"] is True
    assert child["father_alive_flag"] is False
    assert child["mother_line_number"] == 1
    assert child["father_line_number"] is None


def test_dont_know_is_not_recorded_as_no():
    """1=Yes, 2=No, 8=Don't know. The columns are nullable so that
    "not established" stays distinguishable from "no" — an orphan
    referral should not be triggered by an unanswered question."""
    canonical = kobo_to_canonical(_submission([
        _member(1, "01", c12_mother_alive="8", c13_father_alive=""),
    ]))
    head = canonical["members"][0]
    assert head["mother_alive_flag"] is None
    assert head["father_alive_flag"] is None


def test_group_nested_submissions_are_mapped_too():
    """The live form posts group-prefixed keys
    (`household_members/c12_mother_alive`); the flatten helper aliases
    them. This is the shape the dev registry's RawLanding rows carry."""
    canonical = kobo_to_canonical(_submission([{
        "household_members/member_index": 1,
        "household_members/c1_full_name": "Test Member1",
        "household_members/c2_relationship": "01",
        "household_members/c4_sex": "2",
        "household_members/c6_age_years": "40",
        "household_members/c8_nin_status": "0",
        "household_members/c12_mother_alive": "2",
        "household_members/c13_father_alive": "2",
    }]))
    head = canonical["members"][0]
    assert head["mother_alive_flag"] is False
    assert head["father_alive_flag"] is False


# --- the reported household size -------------------------------------------

def test_reported_household_size_is_a_canonical_field():
    canonical = kobo_to_canonical(_submission([_member(1, "01")], hh_size="7"))
    assert canonical["reported_household_size"] == 7
    # Still available where it always was, for the interview card.
    assert canonical["interview"]["hh_size"] == 7


def test_a_missing_size_is_none_not_zero():
    canonical = kobo_to_canonical(_submission([_member(1, "01")]))
    assert canonical["reported_household_size"] is None


# --- D3-D8 reaching the registry -------------------------------------------

def test_the_promote_mapping_covers_every_wg_domain():
    """The six WG columns and the payload keys they come from. The
    mismatch this pins — `memory` from `remembering`, `selfcare` from
    `self_care`, `communication` from `communicating` — is why reading a
    `disability` section by column name found nothing."""
    from apps.ingestion_hub.services import _WG_PAYLOAD_KEYS

    payload = kobo_to_canonical(_submission([
        _member(
            1, "01",
            d3_seeing="01", d4_hearing="02", d5_walking="03",
            d6_remembering="04", d7_self_care="01", d8_communicating="02",
        ),
    ]))
    health = payload["members"][0]["health"]
    assert {c: health.get(k, "") for c, k in _WG_PAYLOAD_KEYS.items()} == {
        "seeing": "01", "hearing": "02", "walking": "03",
        "memory": "04", "selfcare": "01", "communication": "02",
    }


@pytest.mark.django_db
def test_disability_row_is_created_on_promotion(geo, connector):
    """End to end: a submission with WG answers, promoted, produces the
    Disability row — with wg_disability_flag computed from "a lot of
    difficulty" (03) per the model's own threshold."""
    from apps.data_management.models import Disability

    raw = _submission([
        _member(
            1, "01",
            d3_seeing="01", d4_hearing="01", d5_walking="03",
            d6_remembering="01", d7_self_care="01", d8_communicating="01",
        ),
    ], hh_size="1")
    stage = _promote(connector, raw)

    row = Disability.objects.first()
    assert row is not None, (
        "no Disability row — the WG answers were dropped between the "
        "staged payload and the registry again"
    )
    assert row.walking == "03"
    assert row.memory == "01"
    assert row.wg_disability_flag is True


@pytest.mark.django_db
def test_no_answers_means_no_row(geo, connector):
    """A blank row would read as "assessed, no difficulty", which is a
    different statement from "not asked"."""
    from apps.data_management.models import Disability

    raw = _submission([_member(1, "01")], hh_size="1")
    stage = _promote(connector, raw)
    assert Disability.objects.count() == 0


@pytest.mark.django_db
def test_the_household_keeps_the_size_the_respondent_reported(geo, connector):
    from apps.data_management.models import Household

    raw = _submission([_member(1, "01"), _member(2, "02")], hh_size="6")
    stage = _promote(connector, raw)

    hh = Household.objects.get(id=stage.provisional_registry_id)
    # Reported 6, roster 2 — the disagreement is preserved rather than
    # reconciled, because that disagreement is the finding.
    assert hh.reported_household_size == 6
    assert hh.members.count() == 2


@pytest.mark.django_db
def test_parent_fields_reach_the_member_row(geo, connector):
    from apps.data_management.models import Member

    raw = _submission([
        _member(1, "01"),
        _member(2, "04", c12_mother_alive="1", c13_father_alive="2",
                c15_mother_line="1", c6_age_years="9"),
    ], hh_size="2")
    stage = _promote(connector, raw)

    child = Member.objects.get(line_number=2)
    assert child.mother_alive_flag is True
    assert child.father_alive_flag is False
    assert child.mother_line_number == 1
