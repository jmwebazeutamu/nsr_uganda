"""US-S22-DE-04 — fanout of canonical_payload sections into detail tables.

Asserts the bits that promote_stage_record now does on top of the
prior behaviour:

  * Per-section creation (Dwelling / Utilities / Livelihood / FoodSecurity
    / FoodConsumption / repeat groups, plus per-member Health /
    Disability / Education / Employment).
  * Defensive helpers — a missing or empty section is silently skipped.
  * Idempotency — replay of a promoted stage record doesn't duplicate
    detail rows or audit events (the early return at top of
    promote_stage_record short-circuits the fanout entirely).
  * AC-DE-AUDIT — every detail-entity create writes one AuditEvent
    with action="create" and entity_type=<lowercase_model>.
  * Backward-compat — a legacy top-level `dwelling_tenure` key still
    writes Household.dwelling_tenure AND creates a Dwelling row with
    the same tenure.
  * Source-kind threading — current_intake_source reflects the real
    source-system kind ("capi_walkin", "ubos", "kobo", …) instead of
    the hardcoded "dih".
  * Missing Member typed columns (marital_status / mobile_money_flag
    / mother_alive_flag / identification_documents / …) now flow
    through promotion.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import (
    AssetOwnership,
    CopingStrategy,
    Crop,
    Disability,
    Dwelling,
    Education,
    Employment,
    Health,
    Livestock,
    Shock,
)
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
from apps.security.models import AuditEvent

# --- Fixtures -------------------------------------------------------------


@pytest.fixture
def geo_codes(db):
    """7-level UBOS ladder; codes also referenced in the canonical payload."""
    codes = [
        ("region", "DE-R"), ("sub_region", "DE-SR"), ("district", "DE-D"),
        ("county", "DE-C"), ("sub_county", "DE-SC"), ("parish", "DE-P"),
        ("village", "DE-V"),
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


def _connector(kind=SourceSystemKind.KOBO, code="KOBO-DE"):
    src = SourceSystem.objects.create(code=code, name=code, kind=kind)
    DataProvisionAgreement.objects.create(
        source_system=src, reference=f"DPA-{code}",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    return Connector.objects.create(source_system=src, name=code.lower())


@pytest.fixture
def connector(db):
    return _connector()


def _stage_with_payload(connector, geo_codes, payload):
    """Run the DIH pipeline up to a STAGE record with the given payload."""
    run = start_connector_run(connector)
    landing = land_payload(run, {"raw": "test"})
    return stage_from_landing(landing, canonical_payload=payload)


def _base_payload(geo_codes, **extra):
    payload = {
        "geographic": geo_codes,
        "urban_rural": "rural",
        "address_narrative": "Test homestead",
        "members": [
            {"line_number": 1, "surname": "Okot", "first_name": "James",
             "sex": "M", "relationship_to_head": "01", "is_head": True},
        ],
    }
    payload.update(extra)
    return payload


# --- Per-section creation ---------------------------------------------------


@pytest.mark.django_db
class TestPerSectionCreate:
    def test_dwelling_section_creates_row(self, connector, geo_codes):
        payload = _base_payload(geo_codes, dwelling={
            "tenure": "1", "dwelling_type": "1",
            "total_rooms": 4, "sleeping_rooms": 2,
            "roof_material": "1", "wall_material": "1", "floor_material": "1",
        })
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        assert Dwelling.objects.filter(household=hh).count() == 1
        d = hh.dwelling
        assert d.tenure == "1"
        assert d.total_rooms == 4
        assert d.sleeping_rooms == 2

    def test_no_dwelling_section_no_row(self, connector, geo_codes):
        stage = _stage_with_payload(connector, geo_codes, _base_payload(geo_codes))
        hh = promote_stage_record(stage, actor="op")
        assert not Dwelling.objects.filter(household=hh).exists()

    def test_utilities_section_creates_row(self, connector, geo_codes):
        payload = _base_payload(geo_codes, utilities={
            "cooking_fuel": "1", "drinking_water_source": "3",
            "toilet_facility": "3", "households_sharing_toilet": 6,
        })
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        assert hh.utilities.cooking_fuel == "1"
        assert hh.utilities.households_sharing_toilet == 6

    def test_livelihood_section_creates_row(self, connector, geo_codes):
        from decimal import Decimal
        payload = _base_payload(geo_codes, livelihood={
            "main_livelihood": "1", "land_hectares": "1.250",
            "land_ownership": "1",
        })
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        hh.livelihood.refresh_from_db()  # let DB coerce to Decimal
        assert hh.livelihood.main_livelihood == "1"
        assert hh.livelihood.land_hectares == Decimal("1.250")

    def test_food_security_section_creates_row_and_scores(self, connector, geo_codes):
        payload = _base_payload(geo_codes, food_security={
            "worried_food": "1", "unhealthy_food": "1",
            "limited_variety": "1", "skipped_meal": "2",
        })
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        # 3 affirmative responses ("1") → fies_raw_score = 3.
        assert hh.food_security.fies_raw_score == 3

    def test_food_consumption_section_creates_and_scores(self, connector, geo_codes):
        from decimal import Decimal
        payload = _base_payload(geo_codes, food_consumption={
            "staples": {"days_last_7": 7, "source_primary": "1"},
            "meat":    {"days_last_7": 3, "source_primary": "2"},
        })
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        # WFP: 7 × 2 + 3 × 4 = 26.
        assert hh.food_consumption.fcs_score == Decimal("26")
        assert hh.food_consumption.staples_days == 7
        assert hh.food_consumption.meat_days == 3

    def test_assets_creates_one_row_per_entry(self, connector, geo_codes):
        payload = _base_payload(geo_codes, assets=[
            {"asset_type": "radio", "count": 2},
            {"asset_type": "tv", "count": 1},
        ])
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        assert AssetOwnership.objects.filter(household=hh).count() == 2

    def test_crops_creates_rows(self, connector, geo_codes):
        payload = _base_payload(geo_codes, crops=[
            {"crop_name": "maize", "rank_order": 1},
            {"crop_name": "beans", "rank_order": 2},
        ])
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        assert {c.crop_name for c in Crop.objects.filter(household=hh)} == {
            "maize", "beans",
        }

    def test_livestock_creates_rows(self, connector, geo_codes):
        payload = _base_payload(geo_codes, livestock=[
            {"livestock_type": "cattle", "count": 3},
            {"livestock_type": "goat", "count": 5},
        ])
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        assert Livestock.objects.filter(household=hh).count() == 2

    def test_shocks_creates_rows(self, connector, geo_codes):
        payload = _base_payload(geo_codes, shocks=[
            {"shock_type": "01", "severity": "2",
             "event_date": "2026-04-01"},
        ])
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        assert Shock.objects.filter(household=hh).count() == 1

    def test_coping_strategies_creates_rows(self, connector, geo_codes):
        payload = _base_payload(geo_codes, coping_strategies=[
            {"strategy_type": "took_loan", "category": "livelihood",
             "used_flag": True},
            {"strategy_type": "reduced_meals", "category": "food",
             "used_flag": True},
        ])
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        assert CopingStrategy.objects.filter(household=hh).count() == 2


# --- Per-member detail entities -----------------------------------------


@pytest.mark.django_db
class TestPerMemberDetails:
    def test_member_health_disability_education_employment(self, connector, geo_codes):
        payload = _base_payload(geo_codes)
        payload["members"][0].update({
            "health": {"chronic_illness_flag": "1",
                       "chronic_illness_types": ["4", "5"]},
            "disability": {"seeing": "01", "walking": "03"},
            "education": {"literacy_status": "1", "highest_grade": "07"},
            "employment": {"main_activity_last_30d": "1", "sector": "1"},
        })
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        m = hh.members.first()
        assert m.health.chronic_illness_flag == "1"
        assert m.health.get_chronic_illness_types() == ["4", "5"]
        assert m.disability.wg_disability_flag is True  # "03" = a lot of difficulty
        assert m.education.literacy_status == "1"
        assert m.employment.sector == "1"

    def test_no_member_detail_sections_no_rows(self, connector, geo_codes):
        stage = _stage_with_payload(connector, geo_codes, _base_payload(geo_codes))
        hh = promote_stage_record(stage, actor="op")
        m = hh.members.first()
        assert not Health.objects.filter(member=m).exists()
        assert not Disability.objects.filter(member=m).exists()
        assert not Education.objects.filter(member=m).exists()
        assert not Employment.objects.filter(member=m).exists()


# --- Member typed-column gaps the prior promote skipped -----------------


@pytest.mark.django_db
class TestMemberTypedColumns:
    def test_promote_populates_marital_nationality_birth_cert(self, connector, geo_codes):
        payload = _base_payload(geo_codes)
        payload["members"][0].update({
            "marital_status": "2", "nationality": "ug",
            "residency_status": "1", "birth_certificate_status": "1",
        })
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        m = hh.members.first()
        assert m.marital_status == "2"
        assert m.nationality == "ug"
        assert m.residency_status == "1"
        assert m.birth_certificate_status == "1"

    def test_promote_populates_flags_and_parents(self, connector, geo_codes):
        payload = _base_payload(geo_codes)
        payload["members"][0].update({
            "telephone_in_name_flag": True,
            "mobile_money_flag": True,
            "mother_alive_flag": False,
            "father_alive_flag": True,
            "mother_line_number": 3,
            "father_line_number": 4,
            "identification_documents": [{"type": "national_id", "ref": "X"}],
        })
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        m = hh.members.first()
        assert m.telephone_in_name_flag is True
        assert m.mobile_money_flag is True
        assert m.mother_alive_flag is False
        assert m.father_alive_flag is True
        assert m.mother_line_number == 3
        assert m.father_line_number == 4
        assert m.identification_documents == [{"type": "national_id", "ref": "X"}]


# --- Idempotency --------------------------------------------------------


@pytest.mark.django_db
class TestIdempotency:
    def test_replay_does_not_duplicate_detail_rows(self, connector, geo_codes):
        payload = _base_payload(geo_codes, dwelling={"tenure": "1"})
        payload["assets"] = [{"asset_type": "radio", "count": 1}]
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh1 = promote_stage_record(stage, actor="op")
        hh2 = promote_stage_record(stage, actor="op")
        assert hh1.id == hh2.id
        assert Dwelling.objects.filter(household=hh1).count() == 1
        assert AssetOwnership.objects.filter(household=hh1).count() == 1

    def test_replay_does_not_duplicate_audit_events(self, connector, geo_codes):
        payload = _base_payload(geo_codes, dwelling={"tenure": "1"})
        stage = _stage_with_payload(connector, geo_codes, payload)
        promote_stage_record(stage, actor="op")
        first_audit = AuditEvent.objects.filter(
            action="create", entity_type="dwelling",
        ).count()
        promote_stage_record(stage, actor="op")
        second_audit = AuditEvent.objects.filter(
            action="create", entity_type="dwelling",
        ).count()
        assert first_audit == 1
        assert second_audit == 1


# --- Audit chain --------------------------------------------------------


@pytest.mark.django_db
class TestAuditChain:
    def test_every_detail_create_writes_audit(self, connector, geo_codes):
        payload = _base_payload(geo_codes,
            dwelling={"tenure": "1"},
            utilities={"cooking_fuel": "1"},
            livelihood={"main_livelihood": "1"},
            assets=[{"asset_type": "radio", "count": 1}],
        )
        payload["members"][0]["disability"] = {"seeing": "01"}
        stage = _stage_with_payload(connector, geo_codes, payload)
        promote_stage_record(stage, actor="op")
        # One per detail-entity create. entity_type matches the
        # AC-DE-AUDIT contract (<lowercase_model>).
        for et in (
            "dwelling", "utilities", "livelihood",
            "asset_ownership", "disability",
        ):
            assert AuditEvent.objects.filter(
                action="create", entity_type=et,
            ).count() == 1, et


# --- Backward-compat for legacy dwelling_tenure -------------------------


@pytest.mark.django_db
class TestDwellingTenureBackcompat:
    def test_legacy_top_level_writes_both_columns(self, connector, geo_codes):
        # Old shape — no `dwelling` block, just the top-level key.
        payload = _base_payload(geo_codes)
        payload["dwelling_tenure"] = "2"
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        # Household column populated (deprecated mirror).
        assert hh.dwelling_tenure == "2"
        # Dwelling row created with matching tenure.
        assert hh.dwelling.tenure == "2"

    def test_nested_dwelling_block_takes_precedence(self, connector, geo_codes):
        # Both keys supplied — nested wins.
        payload = _base_payload(geo_codes, dwelling={"tenure": "3"})
        payload["dwelling_tenure"] = "2"
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        assert hh.dwelling.tenure == "3"
        assert hh.dwelling_tenure == "3"


# --- Source-kind threading ----------------------------------------------


@pytest.mark.django_db
class TestSourceKindThreading:
    @pytest.mark.parametrize("kind_value", [
        SourceSystemKind.UBOS,
        SourceSystemKind.CAPI_WALKIN,
        SourceSystemKind.KOBO,
    ])
    def test_current_intake_source_reflects_source_kind(
        self, geo_codes, kind_value,
    ):
        # Each kind value should end up on Household.current_intake_source.
        # Pre-US-S22-DE-04 this was always the literal "dih".
        c = _connector(kind=kind_value, code=f"SRC-{kind_value}")
        stage = _stage_with_payload(c, geo_codes, _base_payload(geo_codes))
        hh = promote_stage_record(stage, actor="op")
        assert hh.current_intake_source == kind_value


@pytest.mark.django_db
class TestKoboShockDetailReachesTheRegistry:
    """The whole chain, not just the connector.

    Section K detail was dropped at the mapping step, so this asserts the
    connector's output survives promotion into Shock rows — the thing
    that actually matters. 360 households were in the registry with 0
    Shock rows between them when this was found.
    """

    def test_connector_output_promotes_into_shock_rows(self, connector, geo_codes):
        from apps.ingestion_hub.connectors.kobo import _kobo_shock_rows

        raw = {
            "k03_crops_shock_type": "01", "k04_crops_shock_severity": "1",
            "k03_livestock_shock_type": "04", "k04_livestock_shock_severity": "3",
        }
        # Exactly what the connector puts on the canonical payload.
        payload = _base_payload(geo_codes, shocks=_kobo_shock_rows(raw))
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")

        rows = Shock.objects.filter(household=hh)
        assert rows.count() == 2
        by_livelihood = {r.livelihoods_affected[0]: r for r in rows}
        assert by_livelihood["01"].shock_type == "01"
        assert by_livelihood["01"].severity == "1"
        assert by_livelihood["02"].shock_type == "04"
        assert by_livelihood["02"].severity == "3"

    def test_a_household_with_no_shock_detail_creates_no_rows(
        self, connector, geo_codes,
    ):
        """K01 saying "yes, affected" with no K03 answer must not invent
        a shock — a Shock row with no type is not a shock."""
        from apps.ingestion_hub.connectors.kobo import _kobo_shock_rows

        payload = _base_payload(
            geo_codes, shocks=_kobo_shock_rows({"k01_shock_affected": "1"}),
        )
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        assert Shock.objects.filter(household=hh).count() == 0


@pytest.mark.django_db
class TestDetailRowsPromoteFromEitherProducer:
    """Promotion reads top-level `shocks` and `coping_strategies`.

    Nothing wrote them there: the Kobo connector dropped section K and put
    coping under shocks_coping, while the capture wizard nests both under
    food_shocks. 360 households were in the registry with 0 Shock and 0
    CopingStrategy rows between them. Both locations now resolve.
    """

    def test_kobo_coping_output_promotes(self, connector, geo_codes):
        from apps.ingestion_hub.connectors.kobo import _kobo_coping_rows

        rows = _kobo_coping_rows({
            "l01a_casual_labor": "4",       # used
            "l01c_borrow_money": "1",       # never — still an answer
            "l02d_reduce_meals": "5",
        })
        payload = _base_payload(geo_codes, coping_strategies=rows)
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")

        created = {
            c.strategy_type: c
            for c in CopingStrategy.objects.filter(household=hh)
        }
        assert set(created) == {"casual_labor", "took_loan", "reduced_meals"}
        assert created["casual_labor"].used_flag is True
        assert created["took_loan"].used_flag is False
        assert created["casual_labor"].category == "livelihood"
        assert created["reduced_meals"].category == "food"

    def test_the_wizards_nested_rows_promote_too(self, connector, geo_codes):
        """The wizard already wrote correct rows in the right shape — just
        in a place promotion never looked."""
        payload = _base_payload(geo_codes)
        payload["food_shocks"] = {
            "coping": [
                {"category": "food", "frequency": "4",
                 "strategy_type": "reduced_meals"},
            ],
            "shocks": [
                {"shock_type": "01", "severity": "2",
                 "livelihoods_affected": ["01"]},
            ],
        }
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")

        assert CopingStrategy.objects.filter(household=hh).count() == 1
        assert Shock.objects.filter(household=hh).count() == 1

    def test_the_top_level_contract_still_wins(self, connector, geo_codes):
        """Top-level stays the contract; the other locations are
        fallbacks, not equals."""
        payload = _base_payload(geo_codes, coping_strategies=[
            {"strategy_type": "took_loan", "category": "livelihood",
             "frequency": "3", "used_flag": True},
        ])
        payload["food_shocks"] = {"coping": [
            {"strategy_type": "reduced_meals", "category": "food",
             "frequency": "5", "used_flag": True},
        ]}
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")

        rows = CopingStrategy.objects.filter(household=hh)
        assert [r.strategy_type for r in rows] == ["took_loan"], (
            "both locations were read — rows would be created twice"
        )

    def test_the_per_question_dict_is_not_mistaken_for_rows(
        self, connector, geo_codes,
    ):
        """Kobo's shocks_coping.coping is the complete answer set keyed by
        question, not registry rows. Reading it as rows would create
        garbage strategy_types."""
        payload = _base_payload(geo_codes)
        payload["shocks_coping"] = {
            "coping": {"l01a_casual_labor": "4", "l02d_reduce_meals": "5"},
        }
        stage = _stage_with_payload(connector, geo_codes, payload)
        hh = promote_stage_record(stage, actor="op")
        assert CopingStrategy.objects.filter(household=hh).count() == 0
