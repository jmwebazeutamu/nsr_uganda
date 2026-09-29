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

from apps.data_management.models import (
    AssetOwnership,
    Dwelling,
    Livelihood,
    Utilities,
)
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
from apps.reference_data.models import (
    ChoiceList,
    ChoiceListStatus,
    ChoiceOption,
    GeographicUnit,
)

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

#: The nested food-group block, as the upload carries it. Five of the
#: nine names differ from the model's columns.
FOOD_GROUP_DAYS = {
    "staples": 7, "pulses_nuts": 5, "milk_dairy": 1, "meat_fish_eggs": 4,
    "vegetables": 5, "fruits": 4, "oils_fats": 7, "sugar_sweets": 2,
    "condiments": 7,
}
CAPTURED_FOOD_SECURITY = {
    "fies": {f"i{n}_fies": "2" for n in range(1, 9)},
    "food_groups": {
        group: {"days": days, "yesterday": "", "source_primary": "",
                "source_secondary": ""}
        for group, days in FOOD_GROUP_DAYS.items()
    },
}


def _household_payload(geo_codes, *, housing=None, extra=None, first_name="James"):
    payload = {
        "geographic": geo_codes,
        "urban_rural": "rural",
        "housing": dict(CAPTURED_HOUSING if housing is None else housing),
        "food_security": CAPTURED_FOOD_SECURITY,
        "members": [
            {"line_number": 1, "surname": "Okot", "first_name": first_name,
             "sex": "M", "relationship_to_head": "01", "is_head": True},
        ],
    }
    payload.update(extra or {})
    return payload


def _promote(connector, payload):
    run = start_connector_run(connector)
    landing = land_payload(run, payload)
    stage = stage_from_landing(landing, canonical_payload=payload)
    return promote_stage_record(stage, actor="reviewer-1")


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
        # The food-group block. Five of the nine are spelled one way by
        # the questionnaire and another by the model column, which is
        # the second half of what this routing has to get right.
        ("i9_staples_days", "staples_days", []),
        ("i10_pulses_nuts_days", "pulses_nuts_days", ["pulses_days"]),
        ("i11_milk_dairy_days", "milk_dairy_days", ["dairy_days"]),
        ("i12_meat_fish_eggs_days", "meat_fish_eggs_days", ["meat_days"]),
        ("i13_vegetables_days", "vegetables_days", []),
        ("i14_fruits_days", "fruits_days", []),
        ("i15_oils_fats_days", "oils_fats_days", ["oils_days"]),
        ("i16_sugar_sweets_days", "sugar_sweets_days", ["sugar_days"]),
        ("i17_condiments_days", "condiments_days", []),
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
    return _promote(connector, _household_payload(geo_codes))


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


# ── assets: three shapes, one union ───────────────────────────────────

def test_assets_come_from_the_housing_section(promoted):
    """`_create_assets` iterated `payload["assets"]`, a list that does
    not exist. The data is `housing.assets_owned` (a space-separated
    code list) and `housing.asset_counts`. Six `owns_*` PMT variables
    carrying 1.14 of weight read these rows."""
    owned = {
        a.asset_type: a.count
        for a in AssetOwnership.objects.filter(household=promoted)
    }
    assert owned == {"phone": 1, "radio": 0, "bed": 4, "mattress": 2}


def test_a_count_implies_ownership(db, instrument, connector, geo_codes):
    """An item counted but absent from `assets_owned` is still owned."""
    payload = _household_payload(
        geo_codes,
        housing={
            **CAPTURED_HOUSING,
            "assets_owned": "radio",
            "asset_counts": {"bicycle": 2},
        },
        first_name="Ada",
    )
    household = _promote(connector, payload)
    owned = {
        a.asset_type: a.count
        for a in AssetOwnership.objects.filter(household=household)
    }
    assert owned == {"radio": 0, "bicycle": 2}


def test_a_null_count_is_not_ownership(db, instrument, connector, geo_codes):
    """`{"tv": null}` means not owned, and must not become a tv with
    zero. Zero owned and not owned are different facts."""
    payload = _household_payload(
        geo_codes,
        housing={**CAPTURED_HOUSING, "assets_owned": "", "asset_counts": {"tv": None}},
        first_name="Ben",
    )
    household = _promote(connector, payload)
    assert not AssetOwnership.objects.filter(household=household).exists()


def test_a_null_count_is_normal_data_and_a_bad_one_is_not(caplog):
    """A null count must be skipped SILENTLY; a junk one must be logged.

    Without the explicit null guard the two collapse: `int(None)` raises
    and lands in the same `except`, so the row is dropped either way but
    every unowned asset on every household writes a warning. That is how
    a log stops being read — and `asset_counts` carries a null for every
    item the household does not own, so it would be most of them.
    """
    from apps.ingestion_hub.services import _asset_rows

    with caplog.at_level("WARNING"):
        assert _asset_rows({"housing": {"asset_counts": {"tv": None}}}) == {}
    assert caplog.records == []

    with caplog.at_level("WARNING"):
        assert _asset_rows({"housing": {"asset_counts": {"tv": "many"}}}) == {}
    assert len(caplog.records) == 1
    assert "tv" in caplog.records[0].getMessage()


def test_the_legacy_assets_list_still_works(db, instrument, connector, geo_codes):
    """The shape the old code expected must keep working — some
    connectors may well send it."""
    payload = _household_payload(
        geo_codes,
        extra={"assets": [{"asset_type": "car", "count": 1}]},
        first_name="Cai",
    )
    household = _promote(connector, payload)
    assert AssetOwnership.objects.get(household=household, asset_type="car").count == 1


# ── food consumption: nested, and renamed ─────────────────────────────

def test_food_consumption_reads_the_nested_food_groups(promoted):
    """Three misses on one block: the section was absent
    (`food_security.food_groups`, not `food_consumption`), the leaf key
    was wrong (`days`, not `days_last_7`), and five of the nine group
    names disagreed with the model's columns."""
    from apps.data_management.models import FoodConsumption

    fc = FoodConsumption.objects.get(household=promoted)
    assert fc.staples_days == 7
    assert fc.fruits_days == 4


@pytest.mark.parametrize(
    ("payload_group", "column"),
    [
        ("pulses_nuts", "pulses_days"),
        ("milk_dairy", "dairy_days"),
        ("meat_fish_eggs", "meat_days"),
        ("oils_fats", "oils_days"),
        ("sugar_sweets", "sugar_days"),
    ],
)
def test_each_renamed_food_group_reaches_its_column(
    promoted, payload_group, column,
):
    """The questionnaire calls it `pulses_nuts_days`; the column is
    `pulses_days`. Both are spellings of one question, so the router
    takes the one the model uses."""
    from apps.data_management.models import FoodConsumption

    fc = FoodConsumption.objects.get(household=promoted)
    assert getattr(fc, column) == FOOD_GROUP_DAYS[payload_group], (
        f"{payload_group} did not reach {column}"
    )


def test_the_legacy_food_consumption_shape_still_works(
    db, instrument, connector, geo_codes,
):
    """`food_consumption.<group>.days_last_7` predates the nested
    food_groups block and has its own end-to-end test. Its leaf key is
    not an alias of anything, so the router cannot see it — it must keep
    working through the explicit path, or fixing the new shape breaks
    the old one."""
    from apps.data_management.models import FoodConsumption

    payload = _household_payload(geo_codes, first_name="Dee")
    payload.pop("food_security")
    payload["food_consumption"] = {
        "staples": {"days_last_7": 6, "source_primary": "own"},
    }
    household = _promote(connector, payload)
    fc = FoodConsumption.objects.get(household=household)
    assert fc.staples_days == 6
    assert fc.staples_source == "own"


def test_the_questionnaire_wins_when_both_shapes_arrive(
    db, instrument, connector, geo_codes,
):
    """A payload carrying both must take the questionnaire-resolved
    value; the legacy path fills gaps, it does not override."""
    from apps.data_management.models import FoodConsumption

    payload = _household_payload(geo_codes, first_name="Eli")
    payload["food_consumption"] = {"staples": {"days_last_7": 1}}
    household = _promote(connector, payload)
    assert FoodConsumption.objects.get(household=household).staples_days == 7


# ── coping strategies: per-question answers, not rows ─────────────────

def _coping(answers):
    return {"shocks_coping": {"coping": answers}}


def test_coping_answers_become_rows(db, instrument, connector, geo_codes):
    """`_detail_rows` sees `shocks_coping.coping` and skips it, on the
    stated grounds that "the connector derives the rows separately". It
    does not — `coping_strategies` arrives as an empty list — so every
    answered coping question was dropped."""
    from apps.data_management.models import CopingStrategy

    payload = _household_payload(geo_codes, first_name="Fay")
    payload.update(_coping({"l01a_casual_labor": "3", "l02c_reduce_portions": "2"}))
    household = _promote(connector, payload)

    rows = {
        c.strategy_type: (c.category, c.frequency, c.used_flag)
        for c in CopingStrategy.objects.filter(household=household)
    }
    assert rows == {
        "casual_labor": ("livelihood", "3", True),
        "smaller_portions": ("food", "2", True),
    }


def test_never_is_an_answer_and_still_makes_a_row(
    db, instrument, connector, geo_codes,
):
    """`coping_frequency` code 1 is Never. Asked-and-not-used is an
    answer and must be recorded; `used_flag` is what distinguishes it
    from asked-and-used. Dropping it would make "we asked and they cope
    fine" indistinguishable from "we never asked"."""
    from apps.data_management.models import CopingStrategy

    payload = _household_payload(geo_codes, first_name="Gus")
    payload.update(_coping({"l01b_sell_assets": "1"}))
    household = _promote(connector, payload)

    row = CopingStrategy.objects.get(household=household)
    assert row.strategy_type == "sold_asset"
    assert row.frequency == "1"
    assert row.used_flag is False


def test_a_strategy_with_no_registry_code_is_reported_not_invented(
    db, instrument, connector, geo_codes, caplog,
):
    """Ten of the eighteen L questions are answered, carried, and have
    no code in `coping_strategy_type`. Inventing one would put a value
    in the column that no choice list carries. They are reported until
    the frame gains a code."""
    from apps.data_management.models import CopingStrategy

    payload = _household_payload(geo_codes, first_name="Hal")
    payload.update(_coping({"l01i_begging": "2", "l01a_casual_labor": "2"}))
    with caplog.at_level("WARNING"):
        household = _promote(connector, payload)

    assert [c.strategy_type for c in
            CopingStrategy.objects.filter(household=household)] == ["casual_labor"]
    assert any("l01i_begging" in r.getMessage() for r in caplog.records)


def test_an_unanswered_question_makes_no_row(
    db, instrument, connector, geo_codes,
):
    """Blank is "not asked", not "never". All eighteen arrive blank on a
    household with no shocks, and they must not become eighteen rows."""
    from apps.data_management.models import CopingStrategy

    payload = _household_payload(geo_codes, first_name="Ivy")
    payload.update(_coping({k: "" for k in
                            ("l01a_casual_labor", "l02d_reduce_meals")}))
    household = _promote(connector, payload)
    assert not CopingStrategy.objects.filter(household=household).exists()


def test_explicit_rows_win_over_the_question_answers(
    db, instrument, connector, geo_codes,
):
    """A producer that sends real rows keeps its own shape."""
    from apps.data_management.models import CopingStrategy

    payload = _household_payload(geo_codes, first_name="Jo")
    payload.update(_coping({"l01a_casual_labor": "3"}))
    payload["coping_strategies"] = [
        {"strategy_type": "took_loan", "category": "livelihood",
         "frequency": "4", "used_flag": True},
    ]
    household = _promote(connector, payload)
    assert [c.strategy_type for c in
            CopingStrategy.objects.filter(household=household)] == ["took_loan"]


# ── member-level detail: the second failure layer ─────────────────────
#
# The housing fixes above were all promotion reading the wrong key. The
# member blocks fail the same way, plus a second way: six roster fields
# were never carried by the connector at all, so promotion could not
# have read them under any name.

MEMBER_HEALTH = {"chronic_illness": "2", "seeing": "1", "hearing": "1",
                 "walking": "1", "remembering": "1", "self_care": "1",
                 "communicating": "1"}
MEMBER_EDUCATION = {"literacy": "3", "ever_school": "1",
                    "never_school_reason": "", "highest_grade": "10"}
MEMBER_EMPLOYMENT = {"main_job": "05", "work_sector": "2",
                     "work_status": "3", "gov_program_beneficiary": "1",
                     "programmes": "NUSAF", "savings_place": "2"}


@pytest.fixture
def member_instrument(instrument):
    """The member-level bindings, on top of the household ones."""
    section = FormSection.objects.create(
        form_version=instrument, code="C", name="roster", label="Roster",
        order=2,
    )
    bindings = [
        ("d1_chronic_illness", "chronic_illness_flag", ["chronic_illness"]),
        ("e1_literacy", "literacy_status", ["literacy"]),
        ("e2_ever_school", "ever_attended", ["ever_school"]),
        ("e4_highest_grade", "highest_grade", []),
        ("f1_main_job", "main_activity_last_30d", ["main_job"]),
        ("f3_work_sector", "sector", ["work_sector"]),
        ("f4_work_status", "employment_status", ["work_status"]),
        # The two whose column name was missing from the alias table
        # until migration intake.0014.
        ("f6_gov_program_beneficiary", "is_govt_programme_beneficiary",
         ["gov_program_beneficiary"]),
        ("f7_programmes", "programmes_benefited", ["programmes"]),
        ("f10_savings_place", "savings_location", ["savings_place"]),
        ("i1_fies", "worried_food", ["i1_fies"]),
        ("i4_fies", "skipped_meal", ["i4_fies"]),
    ]
    for order, (name, canonical, aliases) in enumerate(bindings, start=1):
        FormQuestion.objects.create(
            section=section, name=name, label=name, type="text",
            canonical_field=canonical,
            payload_aliases=[canonical, *aliases],
            order_in_section=order,
        )
    return instrument


@pytest.fixture
def promoted_member(db, member_instrument, connector, geo_codes):
    payload = _household_payload(geo_codes, first_name="Ken")
    payload["food_security"] = {
        "fies": {"i1_fies": "1", "i4_fies": "2"},
        "food_groups": CAPTURED_FOOD_SECURITY["food_groups"],
    }
    payload["members"][0].update({
        "health": MEMBER_HEALTH,
        "education": MEMBER_EDUCATION,
        "employment": MEMBER_EMPLOYMENT,
    })
    household = _promote(connector, payload)
    return household.members.first()


def test_the_fies_items_are_persisted(promoted_member):
    """The row was always created — the section is truthy either way —
    with all eight columns blank and fies_raw_score 0. A household that
    reads as assessed and food-secure when nothing was read."""
    from apps.data_management.models import FoodSecurity

    fs = FoodSecurity.objects.get(household=promoted_member.household)
    assert fs.worried_food == "1"
    assert fs.skipped_meal == "2"
    # Recomputed on save from the affirmative items.
    assert fs.fies_raw_score == 1


def test_chronic_illness_is_persisted(promoted_member):
    """Kobo sends `chronic_illness`; the column is
    `chronic_illness_flag`."""
    from apps.data_management.models import Health

    assert Health.objects.get(member=promoted_member).chronic_illness_flag == "2"


def test_education_is_persisted(promoted_member):
    from apps.data_management.models import Education

    education = Education.objects.get(member=promoted_member)
    assert education.literacy_status == "3"
    assert education.ever_attended == "1"
    assert education.highest_grade == "10"


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("main_activity_last_30d", "05"),
        ("sector", "2"),
        ("employment_status", "3"),
        ("is_govt_programme_beneficiary", "1"),
        ("programmes_benefited", "NUSAF"),
        ("savings_location", "2"),
    ],
)
def test_each_employment_answer_reaches_its_column(
    promoted_member, column, expected,
):
    """Six of the ten disagreed. Two of those six — F6 and F7 — had no
    alias naming the column at all until migration intake.0014, so the
    routing alone would still have dropped them."""
    from apps.data_management.models import Employment

    employment = Employment.objects.get(member=promoted_member)
    assert getattr(employment, column) == expected


def test_disability_is_read_from_the_health_block(promoted_member):
    """No connector has ever emitted a `disability` section; all of them
    put the WG short set under `health`."""
    from apps.data_management.models import Disability

    disability = Disability.objects.get(member=promoted_member)
    assert disability.seeing == "1"
    assert disability.memory == "1"
    assert disability.selfcare == "1"


def test_a_member_with_no_detail_blocks_gains_no_rows(
    db, member_instrument, connector, geo_codes,
):
    """Absent is not blank. A roster row with no health block must not
    gain a Health row of empty strings, which would read as "asked, no
    illness"."""
    from apps.data_management.models import Education, Health

    payload = _household_payload(geo_codes, first_name="Lea")
    household = _promote(connector, payload)
    member = household.members.first()
    assert not Health.objects.filter(member=member).exists()
    assert not Education.objects.filter(member=member).exists()


# ── crops and livestock: coded facts collected as prose ───────────────

@pytest.fixture
def agriculture_lists(db):
    """The seeded `crop_name` and `livestock_type` lists.

    Deliberately NOT a hand-built fixture: the whole question is whether
    the instrument's prose matches the registry's real labels, and a
    fixture written to match would answer it by construction. These are
    the lists migrations seed, with the labels operators actually see —
    including "Banana / matoke" and "Other poultry (duck / turkey /
    etc.)", which are exactly the ones free text struggles with.
    """
    from apps.reference_data.services import clear_resolver_cache

    lists = {
        name: ChoiceList.objects.filter(
            list_name=name, status=ChoiceListStatus.ACTIVE,
        ).first()
        for name in ("crop_name", "livestock_type")
    }
    for name, choice_list in lists.items():
        assert choice_list is not None, f"{name} is not seeded"
    clear_resolver_cache()
    return lists


def _agri(crops="", livestock=""):
    return {"agriculture": {"crops_grown": crops, "livestock_counts": livestock}}


def test_the_crop_list_is_split_and_resolved_to_codes(agriculture_lists):
    """`crop_name` is a code column. "Maize, beans" must become codes,
    in the order given, or the column holds labels."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    crops, _ = _agriculture_free_text_rows(_agri(crops="Maize, beans"))
    assert crops == [
        {"crop_name": "maize", "rank_order": 1},
        {"crop_name": "beans", "rank_order": 2},
    ]


def test_livestock_counts_are_split_into_type_and_count(agriculture_lists):
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    _, livestock = _agriculture_free_text_rows(
        _agri(livestock="Cattle 2; Chicken 8"),
    )
    assert livestock == [
        {"livestock_type": "cattle", "count": 2},
        {"livestock_type": "chicken", "count": 8},
    ]


def test_a_multi_word_name_resolves(agriculture_lists):
    """The count is the trailing number, so the name may be several
    words — and the real label has punctuation in it."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    _, livestock = _agriculture_free_text_rows(
        _agri(livestock="Other poultry (duck / turkey / etc.) 12"),
    )
    assert livestock == [{"livestock_type": "other_poultry", "count": 12}]


def test_a_plural_is_reported_not_stemmed(agriculture_lists, caplog):
    """"Goats" is not "Goat". Stemming it would be the same move that
    makes "Matooke" mean whatever is closest, and both would put a
    household on record as farming something it never named."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    with caplog.at_level("WARNING"):
        _, livestock = _agriculture_free_text_rows(_agri(livestock="Goats 3"))
    assert livestock == []
    assert any("Goats" in r.getMessage() for r in caplog.records)


def test_an_unmatched_crop_is_reported_not_nearest_matched(
    agriculture_lists, caplog,
):
    """"bananas" against the label "Banana / matoke"."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    with caplog.at_level("WARNING"):
        crops, _ = _agriculture_free_text_rows(_agri(crops="Coffee, bananas"))
    assert crops == [{"crop_name": "coffee", "rank_order": 1}]
    assert any("bananas" in r.getMessage() for r in caplog.records)
    # And the label it was "obviously" meant to be does resolve, which
    # is what makes the miss a vocabulary problem rather than a bug.
    from apps.reference_data.services import code_for_label
    assert code_for_label("crop_name", "Banana / matoke") == "banana"


def test_a_name_with_no_count_is_recorded_with_zero(agriculture_lists):
    """Owning cattle without a number recorded is still owning cattle."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    _, livestock = _agriculture_free_text_rows(_agri(livestock="Cattle"))
    assert livestock == [{"livestock_type": "cattle", "count": 0}]


def test_case_and_spacing_do_not_matter(agriculture_lists):
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    crops, _ = _agriculture_free_text_rows(_agri(crops="  MAIZE ,   beans "))
    assert [c["crop_name"] for c in crops] == ["maize", "beans"]


def test_the_rows_reach_the_registry(
    db, instrument, agriculture_lists, connector, geo_codes,
):
    from apps.data_management.models import Crop, Livestock

    payload = _household_payload(geo_codes, first_name="Mo")
    payload.update(_agri(crops="Maize, beans", livestock="Cattle 2"))
    household = _promote(connector, payload)

    assert sorted(c.crop_name for c in Crop.objects.filter(household=household)) == [
        "beans", "maize",
    ]
    row = Livestock.objects.get(household=household)
    assert (row.livestock_type, row.count) == ("cattle", 2)


def test_explicit_agriculture_rows_win(
    db, instrument, agriculture_lists, connector, geo_codes,
):
    from apps.data_management.models import Crop

    payload = _household_payload(geo_codes, first_name="Nia")
    payload.update(_agri(crops="Maize"))
    payload["crops"] = [{"crop_name": "coffee", "rank_order": 1}]
    household = _promote(connector, payload)
    assert [c.crop_name for c in Crop.objects.filter(household=household)] == [
        "coffee",
    ]


def test_an_ambiguous_label_resolves_to_nothing(db):
    """Two active options sharing a label make the answer unknowable,
    so neither is offered rather than the first winning by load order."""
    from apps.reference_data.services import clear_resolver_cache, code_for_label

    choice_list = ChoiceList.objects.create(
        list_name="ambig_crop", version=1,
        status=ChoiceListStatus.ACTIVE, author="fixture",
    )
    for code in ("a", "b"):
        ChoiceOption.objects.create(
            choice_list=choice_list, code=code, label="Millet",
            status=ChoiceOption.Status.ACTIVE,
        )
    clear_resolver_cache()
    assert code_for_label("ambig_crop", "Millet") == ""


# ── crops and livestock as coded questions ────────────────────────────
#
# H5 and H3 were free text over code columns, so every answer arrived as
# something the registry could not store. Migration intake.0015 makes
# them selects; these pin that new answers are codes and that the prose
# already collected still reads.

def test_coded_crops_are_taken_as_codes(agriculture_lists):
    """A select_multiple answers with space-separated codes."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    crops, _ = _agriculture_free_text_rows(
        {"agriculture": {"crops_grown": "maize beans"}},
    )
    assert crops == [
        {"crop_name": "maize", "rank_order": 1},
        {"crop_name": "beans", "rank_order": 2},
    ]


def test_rank_follows_the_order_asked_for(agriculture_lists):
    """H5 asks for crops "in order of importance", so the order the
    enumerator gave is the rank and must not be sorted."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    crops, _ = _agriculture_free_text_rows(
        {"agriculture": {"crops_grown": "coffee maize"}},
    )
    assert [c["crop_name"] for c in crops] == ["coffee", "maize"]


def test_livestock_kept_pairs_with_its_counts(agriculture_lists):
    """Mirrors assets: which kinds, then one count each."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    _, livestock = _agriculture_free_text_rows({"agriculture": {
        "livestock_kept": "cattle chicken",
        "livestock_counts_by_kind": {"cattle": 2, "chicken": 8},
    }})
    assert livestock == [
        {"livestock_type": "cattle", "count": 2},
        {"livestock_type": "chicken", "count": 8},
    ]


def test_a_kind_kept_without_a_count_is_still_kept(agriculture_lists):
    """Count 0 is what the column already meant for unrecorded."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    _, livestock = _agriculture_free_text_rows({"agriculture": {
        "livestock_kept": "goat",
        "livestock_counts_by_kind": {"goat": None},
    }})
    assert livestock == [{"livestock_type": "goat", "count": 0}]


def test_a_count_without_a_selection_is_still_ownership(agriculture_lists):
    """Same rule as assets — a counted animal is a kept animal, however
    the selection question was answered."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    _, livestock = _agriculture_free_text_rows({"agriculture": {
        "livestock_kept": "",
        "livestock_counts_by_kind": {"cattle": 3},
    }})
    assert livestock == [{"livestock_type": "cattle", "count": 3}]


def test_a_code_the_list_does_not_carry_is_reported(agriculture_lists, caplog):
    """A select cannot normally emit one, but these payloads are POSTed
    around form validation, so the check stays."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    with caplog.at_level("WARNING"):
        _, livestock = _agriculture_free_text_rows({"agriculture": {
            "livestock_kept": "dragon",
        }})
    assert livestock == []
    assert any("dragon" in r.getMessage() for r in caplog.records)


def test_prose_still_reads_after_the_question_changed(agriculture_lists):
    """Answers collected before intake.0015 are still prose and are not
    migrated. Losing them to fix the question would be the worse
    outcome."""
    from apps.ingestion_hub.services import _agriculture_free_text_rows

    crops, livestock = _agriculture_free_text_rows({"agriculture": {
        "crops_grown": "Maize, beans",
        "livestock_counts": "Cattle 2; Chicken 8",
    }})
    assert [c["crop_name"] for c in crops] == ["maize", "beans"]
    assert livestock == [
        {"livestock_type": "cattle", "count": 2},
        {"livestock_type": "chicken", "count": 8},
    ]


@pytest.mark.django_db
def test_the_instrument_asks_for_codes_now():
    """The point of the change: both questions are selects bound to the
    list whose codes the registry stores.

    The instrument is loaded here rather than assumed. `load_instrument`
    rebuilds FormQuestion from `fixtures/instrument_v1.json`, so this
    checks the fixture — which is what a fresh environment gets — and
    not only migration 0015, which only reaches databases that already
    had the questions. Skipping when the table was empty would have let
    the fixture and the migration drift apart unnoticed.
    """
    from django.core.management import call_command

    from apps.intake.models import FormQuestion

    call_command("load_instrument", quiet=True)
    crops = FormQuestion.objects.filter(name="h5_crops_grown").first()
    stock = FormQuestion.objects.filter(name="h3_livestock_counts").first()
    assert crops is not None and stock is not None
    assert crops.type == "select_multiple"
    assert crops.choice_list_ref.list_name == "crop_name"
    assert stock.type == "select_multiple"
    assert stock.choice_list_ref.list_name == "livestock_type"
    # The old payload key still resolves, so collected answers are not
    # orphaned by the rename of its canonical field.
    assert "livestock_counts" in (stock.payload_aliases or [])
    # And the per-kind counts exist, or a selected kind has nowhere to
    # record how many.
    counts = FormQuestion.objects.filter(name__startswith="h3_count_")
    assert counts.count() == 8
    assert all(q.type == "integer" for q in counts)
