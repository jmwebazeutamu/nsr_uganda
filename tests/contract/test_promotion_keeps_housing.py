"""A promoted household keeps the housing it was captured with.

Nineteen households were uploaded on 28 Sep 2026 carrying a complete
`housing` section — tenure, dwelling type, roof, wall and floor
material, room counts, water source, toilet, cooking fuel, lighting,
waste disposal, assets and livelihood — and every one of them was
promoted with `Dwelling`, `Utilities` and `Livelihood` all empty. No
error, no audit event, nothing on any screen.

Two faults at once, and either alone would have been enough:

  * `_create_dwelling` read `payload["dwelling"]`; the payload calls the
    section `housing`. `sect` was `{}` so the function returned early.
  * seven field names disagreed too, so fixing the section alone would
    still have dropped most of it:
        rooms_total             -> total_rooms
        rooms_sleeping          -> sleeping_rooms
        water_source            -> drinking_water_source
        toilet_type             -> toilet_facility
        share_toilet            -> toilet_shared
        share_toilet_households -> households_sharing_toilet
        lighting_source         -> lighting_energy

Every one of those pairs was already recorded on `FormQuestion`
(`canonical_field` and `payload_aliases`). Promotion restated them
instead of asking, and drifted.

Downstream this was not cosmetic: eleven PMT variables carrying 1.36 of
weight between them read those columns, so every score computed from
this data omitted them. `apps.pmt.findings` reported the eleven as
`missing_data` — correctly, because the rows genuinely were not there.

These tests assert against the REAL payload shape, taken from a staged
record, not a shape invented to match the code.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Dwelling, Livelihood, Utilities
from apps.ingestion_hub.services import (
    land_payload,
    promote_stage_record,
    stage_from_landing,
    start_connector_run,
)
from apps.ingestion_hub.models import (
    Connector,
    DataProvisionAgreement,
    SourceSystem,
    SourceSystemKind,
    StageRecordState,
)
from apps.intake.models import FormQuestion, FormSection, FormVersion
from apps.reference_data.models import GeographicUnit

pytestmark = pytest.mark.django_db


@pytest.fixture
def geo_codes(db):
    """The 7-level UBOS ladder, mirroring apps/ingestion_hub/tests.py."""
    codes = [
        ("region", "P-R"), ("sub_region", "P-SR"), ("district", "P-D"),
        ("county", "P-C"), ("sub_county", "P-SC"), ("parish", "P-P"),
        ("village", "P-V"),
    ]
    parent = None
    out = {}
    for level, code in codes:
        node = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent,
            effective_from=date(2026, 1, 1),
        )
        out[level] = code
        parent = node
    return out


@pytest.fixture
def connector(db):
    source = SourceSystem.objects.create(
        code="KOBO-PROMO", name="Kobo promotion contract",
        kind=SourceSystemKind.KOBO,
    )
    DataProvisionAgreement.objects.create(
        source_system=source, reference="DPA-KOBO-PROMO",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    return Connector.objects.create(source_system=source, name="kobo-promo")


#: The `housing` block exactly as the 28 Sep upload carried it.
CAPTURED_HOUSING = {
    "tenure": "2",
    "dwelling_type": "3",
    "roof_material": "3",
    "wall_material": "3",
    "floor_material": "1",
    "rooms_total": 4,
    "rooms_sleeping": 2,
    "water_source": "3",
    "toilet_type": "2",
    "share_toilet": "1",
    "share_toilet_households": 2,
    "cooking_fuel": "3",
    "lighting_source": "2",
    "waste_disposal": "1",
    "livelihood_source": "3",
    "assets_owned": "phone radio bed mattress",
    "asset_counts": {"bed": 4, "phone": 1, "mattress": 2},
}

#: payload key -> (model, canonical column, expected value).
ROUTED = [
    ("tenure", Dwelling, "tenure", "2"),
    ("dwelling_type", Dwelling, "dwelling_type", "3"),
    ("roof_material", Dwelling, "roof_material", "3"),
    ("wall_material", Dwelling, "wall_material", "3"),
    ("floor_material", Dwelling, "floor_material", "1"),
    ("rooms_total", Dwelling, "total_rooms", 4),
    ("rooms_sleeping", Dwelling, "sleeping_rooms", 2),
    ("water_source", Utilities, "drinking_water_source", "3"),
    ("toilet_type", Utilities, "toilet_facility", "2"),
    ("share_toilet_households", Utilities, "households_sharing_toilet", 2),
    ("cooking_fuel", Utilities, "cooking_fuel", "3"),
    ("lighting_source", Utilities, "lighting_energy", "2"),
    ("waste_disposal", Utilities, "waste_disposal", "1"),
    ("livelihood_source", Livelihood, "main_livelihood", "3"),
]


@pytest.fixture
def instrument(db):
    """The questionnaire bindings promotion must resolve through.

    Seeded here because `manage.py load_instrument` populates
    FormQuestion, not a migration, so a test database has none. Each row
    states the alias the connector sends and the column it answers — the
    same pairs `apps/intake/canonical_fields.py` seeds in production.
    """
    version = FormVersion.objects.create(
        version=93_001, name="Promotion contract", status="draft",
        author="fixture", effective_from=date(2026, 1, 1),
    )
    section = FormSection.objects.create(
        form_version=version, code="G", name="housing", label="Housing",
        order=1,
    )
    bindings = [
        ("g1_tenure", "tenure", []),
        ("g2_dwelling_type", "dwelling_type", []),
        ("g3_rooms_total", "total_rooms", ["rooms_total"]),
        ("g4_rooms_sleeping", "sleeping_rooms", ["rooms_sleeping"]),
        ("g5_roof_material", "roof_material", []),
        ("g6_wall_material", "wall_material", []),
        ("g7_floor_material", "floor_material", []),
        ("g8_cooking_fuel", "cooking_fuel", []),
        ("g9_lighting_source", "lighting_energy", ["lighting_source"]),
        ("g10_water_source", "drinking_water_source", ["water_source"]),
        ("g11_toilet_type", "toilet_facility", ["toilet_type"]),
        ("g12_share_toilet", "toilet_shared", ["share_toilet"]),
        ("g13_share_toilet_households", "households_sharing_toilet",
         ["share_toilet_households"]),
        ("g14_waste_disposal", "waste_disposal", []),
        ("g16_livelihood_source", "main_livelihood", ["livelihood_source"]),
    ]
    for order, (name, canonical, aliases) in enumerate(bindings, start=1):
        FormQuestion.objects.create(
            section=section, name=name, label=name, type="text",
            canonical_field=canonical,
            payload_aliases=[canonical, *aliases],
            order_in_section=order,
        )
    return version


@pytest.fixture
def promoted(db, instrument, connector, geo_codes):
    """A household promoted from the real payload shape."""
    payload = {
        "geographic": geo_codes,
        "urban_rural": "rural",
        "housing": dict(CAPTURED_HOUSING),
        "members": [
            {"line_number": 1, "surname": "Okot", "first_name": "James",
             "sex": "M", "relationship_to_head": "01", "is_head": True},
        ],
    }
    run = start_connector_run(connector)
    landing = land_payload(run, payload)
    stage = stage_from_landing(landing, canonical_payload=payload)
    household = promote_stage_record(stage, actor="reviewer-1")
    stage.refresh_from_db()
    assert stage.state == StageRecordState.PROMOTED
    return household


def test_promotion_creates_the_detail_rows(promoted):
    """The regression. All three were absent for every real upload."""
    assert Dwelling.objects.filter(household=promoted).exists()
    assert Utilities.objects.filter(household=promoted).exists()
    assert Livelihood.objects.filter(household=promoted).exists()


@pytest.mark.parametrize(
    ("payload_key", "model", "column", "expected"),
    ROUTED,
    ids=[f"{k}->{c}" for k, _m, c, _v in ROUTED],
)
def test_each_captured_answer_reaches_its_canonical_column(
    promoted, payload_key, model, column, expected,
):
    """Field by field, so a partial fix cannot pass.

    Seven of these fourteen pairs have different spellings on the two
    sides. Asserting only that the rows exist would let a fix that
    resolves the section but not the names through.
    """
    row = model.objects.get(household=promoted)
    assert getattr(row, column) == expected, (
        f"payload {payload_key!r} did not reach {model.__name__}.{column}"
    )


def test_the_section_name_is_not_what_routes_the_data(
    db, instrument, connector, geo_codes,
):
    """The same answers under a different section name must still land.

    This registry has seen the block arrive as `dwelling`, as nested
    `housing.dwelling` and as flat `housing`. None of those names is
    recorded anywhere canonical, so routing on them is what broke.
    """
    payload = {
        "geographic": geo_codes,
        "urban_rural": "rural",
        # Nested two deep, under a name nothing has ever used.
        "shelter": {"detail": dict(CAPTURED_HOUSING)},
        "members": [
            {"line_number": 1, "surname": "Okot", "first_name": "Ana",
             "sex": "F", "relationship_to_head": "01", "is_head": True},
        ],
    }
    run = start_connector_run(connector)
    landing = land_payload(run, payload)
    stage = stage_from_landing(landing, canonical_payload=payload)
    household = promote_stage_record(stage, actor="reviewer-1")

    dwelling = Dwelling.objects.get(household=household)
    assert dwelling.floor_material == "1"
    assert dwelling.total_rooms == 4
    assert Utilities.objects.get(household=household).lighting_energy == "2"


def test_a_key_the_questionnaire_does_not_know_is_left_alone(
    db, instrument, connector, geo_codes,
):
    """No guessing. An unrecognised key is reported, never matched by
    similarity — `rooms_total`/`total_rooms` is exactly the shape of
    pair a fuzzy match gets confidently wrong."""
    from apps.intake.payload_fields import canonical_key, unmapped_keys

    assert canonical_key("rooms_total") == "total_rooms"
    assert canonical_key("roomz_total") == ""
    assert "roomz_total" in unmapped_keys({"housing": {"roomz_total": 4}})


def test_no_detail_row_is_invented_when_nothing_was_captured(
    db, instrument, connector, geo_codes,
):
    """A household with no housing answers must not gain an empty
    Dwelling row — that would turn "never asked" into "asked and
    blank", which is the distinction PMT's missing_data finding
    depends on."""
    payload = {
        "geographic": geo_codes,
        "urban_rural": "rural",
        "members": [
            {"line_number": 1, "surname": "Okot", "first_name": "Sam",
             "sex": "M", "relationship_to_head": "01", "is_head": True},
        ],
    }
    run = start_connector_run(connector)
    landing = land_payload(run, payload)
    stage = stage_from_landing(landing, canonical_payload=payload)
    household = promote_stage_record(stage, actor="reviewer-1")

    assert not Dwelling.objects.filter(household=household).exists()
    assert not Utilities.objects.filter(household=household).exists()


def test_canonical_names_land_without_the_instrument_seeded(
    db, connector, geo_codes,
):
    """Promotion must fail OPEN, not closed, when FormQuestion is empty.

    `FormQuestion` is populated by `manage.py load_instrument`, not by a
    migration, so an environment built from schema alone has none. If
    alias resolution were the only route, promotion would silently drop
    every detail row there — a worse failure than the aliasing bug this
    fix exists to close. A key that IS the column name is canonical by
    identity and needs no question to say so.

    Note the absent `instrument` fixture: that is the point.
    """
    assert not FormQuestion.objects.exists()
    payload = {
        "geographic": geo_codes,
        "urban_rural": "rural",
        "dwelling": {
            "tenure": "2", "floor_material": "1", "total_rooms": 4,
        },
        "members": [
            {"line_number": 1, "surname": "Okot", "first_name": "Zoe",
             "sex": "F", "relationship_to_head": "01", "is_head": True},
        ],
    }
    run = start_connector_run(connector)
    landing = land_payload(run, payload)
    stage = stage_from_landing(landing, canonical_payload=payload)
    household = promote_stage_record(stage, actor="reviewer-1")

    dwelling = Dwelling.objects.get(household=household)
    assert dwelling.tenure == "2"
    assert dwelling.floor_material == "1"
    assert dwelling.total_rooms == 4


def test_an_alias_still_needs_the_instrument(db, connector, geo_codes):
    """The other half of the same contract, stated so the fallback
    cannot quietly grow into a guess: `rooms_total` is NOT a column
    name, so without the questionnaire there is no authority to say it
    means `total_rooms`, and it must not be assumed."""
    from apps.intake.payload_fields import canonical_key

    assert not FormQuestion.objects.exists()
    assert canonical_key("rooms_total") == ""


def test_a_coded_answer_is_refused_for_a_boolean_column(promoted):
    """`toilet_shared` is a BooleanField; the instrument answers with
    the `yes_no` codes "1" and "2".

    Django accepts "1" as True and raises on "2", so guessing would
    record half the population as sharing a toilet and abort promotion
    for the other half. Whether code "1" means True is not recorded in
    the column, the question or the choice list, so it is refused and
    logged rather than assumed — and the other thirteen fields still
    land, which is the whole point.
    """
    utilities = Utilities.objects.get(household=promoted)
    assert utilities.toilet_shared is None
    # The rest of the section is unaffected by that one refusal.
    assert utilities.drinking_water_source == "3"
    assert utilities.households_sharing_toilet == 2


def test_a_value_the_column_cannot_hold_does_not_abort_the_promotion(
    db, instrument, connector, geo_codes,
):
    """One unusable answer must not cost the household its other
    fifteen. Before this, a bad value raised inside the atomic
    promotion block and took the whole record with it."""
    payload = {
        "geographic": geo_codes,
        "urban_rural": "rural",
        "housing": {**CAPTURED_HOUSING, "rooms_total": "not a number"},
        "members": [
            {"line_number": 1, "surname": "Okot", "first_name": "Ivan",
             "sex": "M", "relationship_to_head": "01", "is_head": True},
        ],
    }
    run = start_connector_run(connector)
    landing = land_payload(run, payload)
    stage = stage_from_landing(landing, canonical_payload=payload)
    household = promote_stage_record(stage, actor="reviewer-1")

    dwelling = Dwelling.objects.get(household=household)
    assert dwelling.total_rooms is None
    assert dwelling.floor_material == "1"
    assert dwelling.sleeping_rooms == 2
