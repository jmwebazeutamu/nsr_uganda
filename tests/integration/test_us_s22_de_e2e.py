"""End-to-end DIH -> registry -> PMT chain with a rich detail-entity
payload (US-S22-DE Sprint E, US-S22-DE-12).

This test walks the FULL chain a real Kobo submission travels through
when every detail section is populated:

  start_connector_run(connector)
    -> land_payload(run, payload)
    -> stage_from_landing(landing, canonical_payload=payload)
    -> promote_stage_record(stage, actor="op")
        -> Household + Members create
        -> per-Household 5 one-to-ones (Dwelling/Utilities/Livelihood/
           FoodSecurity/FoodConsumption)
        -> per-Member 4 one-to-ones (Health/Disability/Education/
           Employment)
        -> 5 repeat-group child tables (Assets/Crops/Livestock/
           Shocks/CopingStrategies)
        -> AuditEvent fanout
        -> PMT recompute (when an ACTIVE model exists)

The point is to prove the WIRING CHAIN holds end-to-end, mirroring
tests/integration/test_drs_workflow_e2e.py — no mocks, no shortcuts.

Three test functions:

  * test_full_detail_chain_promotes_and_audits — the rich-payload happy
    path: every detail row created, every typed Member column flows
    through, encryption + computed-column derivations fire, every
    detail-entity create emits an AuditEvent.
  * test_active_pmt_recomputes_22_variable_surface — activates the
    seeded version=22001 model and asserts the PMTResult lands with
    the full input snapshot AND scoring stays under the 20-query budget
    (ADR-0024 / AC-DE-PMT-NO-N-PLUS-1, sized for the e2e test's slim
    2-member roster).
  * test_promote_is_idempotent_on_replay — re-promoting the same stage
    is a no-op for detail rows and audit events.
  * test_promote_succeeds_with_empty_detail_sections — the defensive
    branch: payload omits every detail section, promote still wins,
    zero detail rows land.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from apps.data_management.models import (
    AssetOwnership,
    CopingStrategy,
    Crop,
    Disability,
    Dwelling,
    Education,
    Employment,
    FoodConsumption,
    FoodSecurity,
    Health,
    Livelihood,
    Livestock,
    Shock,
    Utilities,
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
from apps.pmt.models import ModelStatus, PMTModelVersion, PMTResult
from apps.pmt.services import activate_model_version, recompute_for_household
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent
from django.db import connection
from django.test.utils import CaptureQueriesContext

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


# Detail-entity types the promote fanout writes — used to assert AuditEvent
# coverage matches the AC-DE-AUDIT contract one-to-one.
_DETAIL_ENTITY_TYPES = (
    "dwelling", "utilities", "livelihood", "food_security", "food_consumption",
    "asset_ownership", "crop", "livestock", "shock", "coping_strategy",
    "health", "disability", "education", "employment",
)


@pytest.fixture
def geo_codes(db):
    """Seed the 7-level UBOS ladder. The canonical payload references
    these codes by level so promote_stage_record's _geo() resolver
    finds them."""
    codes = [
        ("region", "S22DE-R"), ("sub_region", "S22DE-SR"),
        ("district", "S22DE-D"), ("county", "S22DE-C"),
        ("sub_county", "S22DE-SC"), ("parish", "S22DE-P"),
        ("village", "S22DE-V"),
    ]
    parent = None
    out: dict[str, str] = {}
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
    """A Kobo SourceSystem + active DPA + Connector. The kind="kobo"
    threads into Household.current_intake_source — proves the
    US-S22-DE-04 source-kind threading."""
    src = SourceSystem.objects.create(
        code="S22DE-KOBO", name="S22DE Kobo source", kind=SourceSystemKind.KOBO,
    )
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-S22DE-KOBO",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    return Connector.objects.create(source_system=src, name="kobo-e2e")


def _rich_payload(geo_codes: dict[str, str]) -> dict:
    """The full detail-entity payload shape — every section populated.

    Mirrors the build prompt §3 canonical_payload contract. Two members:
      * line 1, head: chronic illness "4" (HIV) + disability "03"
        (a lot of difficulty walking) -> Disability.wg_disability_flag
        must compute True.
      * line 2, spouse: clean.
    Five repeat-group arrays populated with distinct counts so the test
    can assert on row counts per group.
    """
    return {
        "geographic": geo_codes,
        "urban_rural": "2",  # "2" = rural per the rural_urban ChoiceList
        "address_narrative": "Plot 12, Acholi homestead",
        "gps_lat": "1.234567",
        "gps_lng": "32.345678",
        "gps_accuracy_m": "4.50",
        "residence_status": "1",
        # --- per-Household one-to-ones --------------------------------
        "dwelling": {
            "tenure": "1",
            "dwelling_type": "1",
            "total_rooms": 4,
            "sleeping_rooms": 2,
            "roof_material": "1",
            "wall_material": "1",
            "floor_material": "1",
        },
        "utilities": {
            "cooking_fuel": "1",
            "lighting_energy": "2",
            "drinking_water_source": "3",
            "toilet_facility": "3",
            "toilet_shared": True,
            "households_sharing_toilet": 4,
            "waste_disposal": "1",
        },
        "livelihood": {
            "main_livelihood": "1",
            "crop_production_zone": "2",
            "livestock_zone": "1",
            "agricultural_purpose": "1",
            "land_ownership": "1",
            "land_hectares": "2.500",
            "land_title": "1",
        },
        "food_security": {
            # 5 affirmative ("1"), 3 negative ("2") -> fies_raw_score = 5.
            "worried_food": "1",
            "unhealthy_food": "1",
            "limited_variety": "1",
            "skipped_meal": "1",
            "ate_less": "1",
            "ran_out_food": "2",
            "hungry_no_eat": "2",
            "whole_day_no_eat": "2",
        },
        "food_consumption": {
            # WFP weights: staples=2, pulses=3, dairy=4, meat=4,
            # vegetables=1, fruits=1, oils=0.5, sugar=0.5, condiments=0.
            # Score expected = 7*2 + 4*3 + 0*4 + 3*4 + 5*1 + 2*1
            #                + 7*0.5 + 7*0.5 + 0*0
            #                = 14 + 12 + 0 + 12 + 5 + 2 + 3.5 + 3.5 + 0
            #                = 52.00
            "staples":    {"days_last_7": 7, "source_primary": "1"},
            "pulses":     {"days_last_7": 4, "source_primary": "1"},
            "dairy":      {"days_last_7": 0, "source_primary": "1"},
            "meat":       {"days_last_7": 3, "source_primary": "2"},
            "vegetables": {"days_last_7": 5, "source_primary": "1"},
            "fruits":     {"days_last_7": 2, "source_primary": "1"},
            "oils":       {"days_last_7": 7, "source_primary": "1"},
            "sugar":      {"days_last_7": 7, "source_primary": "1"},
            "condiments": {"days_last_7": 0, "source_primary": "1"},
        },
        # --- per-Household repeat groups (5 distinct rows total) ------
        "assets": [
            {"asset_type": "radio", "count": 1},
            {"asset_type": "tv", "count": 1},
            {"asset_type": "motorcycle", "count": 1},
        ],
        "crops": [
            {"crop_name": "maize", "rank_order": 1},
            {"crop_name": "beans", "rank_order": 2},
        ],
        "livestock": [
            {"livestock_type": "cattle", "count": 3},
            {"livestock_type": "goat", "count": 5},
            {"livestock_type": "chicken", "count": 12},
            {"livestock_type": "pig", "count": 2},
        ],
        "shocks": [
            {
                "shock_type": "01",  # drought
                "severity": "2",
                "livelihoods_affected": ["crops", "livestock"],
                "crops_severity_score": 3,
                "event_date": "2026-04-01",
            },
        ],
        "coping_strategies": [
            {"strategy_type": "took_loan", "category": "livelihood",
             "frequency": "2", "used_flag": True},
            {"strategy_type": "reduced_meals", "category": "food",
             "frequency": "3", "used_flag": True},
            {"strategy_type": "sold_assets", "category": "livelihood",
             "frequency": "1", "used_flag": True},
        ],
        # --- Members + per-Member detail entities --------------------
        "members": [
            {
                "line_number": 1,
                "surname": "Okot", "first_name": "James", "other_name": "P.",
                "relationship_to_head": "01",  # head
                "sex": "1",  # male
                "date_of_birth": "1980-03-14",
                "age_years": 46,
                "marital_status": "2",
                "nationality": "ug",
                "residency_status": "1",
                "birth_certificate_status": "1",
                "telephone_1": "+256700000001",
                "telephone_in_name_flag": True,
                "mobile_money_flag": True,
                "mother_alive_flag": False,
                "father_alive_flag": False,
                "identification_documents": [
                    {"type": "national_id", "ref": "CM800001"},
                ],
                "is_head": True,
                # Health: chronic illness, includes HIV (code "4") to
                # exercise the encrypted helper round-trip.
                "health": {
                    "chronic_illness_flag": "1",
                    "chronic_illness_types": ["1", "4", "7"],
                },
                # Disability: code "03" = "a lot of difficulty" -> the
                # wg_disability_flag derivation must compute True.
                "disability": {
                    "seeing": "01",
                    "hearing": "01",
                    "walking": "03",
                    "memory": "01",
                    "selfcare": "01",
                    "communication": "01",
                },
                "education": {
                    "literacy_status": "1",
                    "ever_attended": "1",
                    "highest_grade": "07",
                    "currently_attending": "2",
                },
                "employment": {
                    "main_activity_last_30d": "1",
                    "work_frequency": "1",
                    "sector": "1",
                    "employment_status": "3",
                    "is_govt_programme_beneficiary": "2",
                    "programmes_benefited": [],
                    "currently_benefiting": "2",
                    "made_savings": "1",
                    "savings_location": "1",
                },
            },
            {
                "line_number": 2,
                "surname": "Akello", "first_name": "Grace",
                "relationship_to_head": "02",  # spouse
                "sex": "2",  # female
                "date_of_birth": "1985-07-20",
                "age_years": 41,
                "marital_status": "2",
                "nationality": "ug",
                "telephone_1": "+256700000002",
                "mobile_money_flag": False,
                "mother_alive_flag": True,
                "father_alive_flag": True,
                "is_head": False,
                "health": {
                    "chronic_illness_flag": "2",
                    "chronic_illness_types": [],
                },
                "disability": {
                    "seeing": "01", "hearing": "01", "walking": "01",
                    "memory": "01", "selfcare": "01", "communication": "01",
                },
                "education": {
                    "literacy_status": "1",
                    "ever_attended": "1",
                    "highest_grade": "11",
                    "currently_attending": "2",
                },
                "employment": {
                    "main_activity_last_30d": "2",
                    "sector": "3",
                    "employment_status": "1",
                },
            },
        ],
    }


def _drive_pipeline(connector, payload: dict):
    """Run the DIH chain up through promote_stage_record. Returns the
    (Household, StageRecord) pair so callers can drill into either."""
    run = start_connector_run(connector)
    landing = land_payload(run, {"raw": "rich-payload"})
    stage = stage_from_landing(landing, canonical_payload=payload)
    hh = promote_stage_record(stage, actor="op")
    return hh, stage


# ---------------------------------------------------------------------------
# Happy path — every detail section flows through
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_full_detail_chain_promotes_and_audits(connector, geo_codes):
    """The rich-payload chain: every detail row is created, the
    typed-column gaps the pre-DE promote skipped are populated, computed
    columns (FIES, FCS, WG disability) derive correctly, the encrypted
    chronic-illness list round-trips, and every detail-entity create
    emits one AuditEvent matching the AC-DE-AUDIT contract."""
    payload = _rich_payload(geo_codes)
    hh, stage = _drive_pipeline(connector, payload)

    # --- Household identity + source-kind threading ------------------
    assert hh.id == stage.provisional_registry_id
    # Pre-DE this was hardcoded "dih"; DE-04 threads the SourceSystem.kind.
    assert hh.current_intake_source == SourceSystemKind.KOBO  # "kobo"
    assert hh.urban_rural == "2"
    assert hh.address_narrative == "Plot 12, Acholi homestead"
    # gps_lat is stored via the DecimalField; refresh_from_db lets the
    # DB-side coercion turn the stringified payload value into Decimal.
    hh.refresh_from_db()
    assert hh.gps_lat == Decimal("1.234567")
    # Legacy dwelling_tenure column is mirrored from the nested block.
    assert hh.dwelling_tenure == "1"
    # Head pointer wired.
    assert hh.head_member is not None
    assert hh.head_member.line_number == 1

    # --- Members + typed columns the pre-DE promote skipped ----------
    members = list(hh.members.order_by("line_number"))
    assert len(members) == 2
    head, spouse = members
    assert head.surname == "Okot" and head.first_name == "James"
    assert head.marital_status == "2"
    assert head.mobile_money_flag is True
    assert head.mother_alive_flag is False
    assert head.identification_documents == [
        {"type": "national_id", "ref": "CM800001"},
    ]
    assert spouse.mobile_money_flag is False
    assert spouse.mother_alive_flag is True

    # --- Per-Household one-to-ones (5/5) -----------------------------
    assert Dwelling.objects.filter(household=hh).count() == 1
    assert hh.dwelling.tenure == "1"
    assert hh.dwelling.total_rooms == 4

    assert Utilities.objects.filter(household=hh).count() == 1
    assert hh.utilities.cooking_fuel == "1"
    assert hh.utilities.households_sharing_toilet == 4

    assert Livelihood.objects.filter(household=hh).count() == 1
    hh.livelihood.refresh_from_db()  # let SQLite coerce to Decimal
    assert hh.livelihood.land_hectares == Decimal("2.500")

    # FIES: 5 affirmative ("1") responses -> raw score = 5.
    assert FoodSecurity.objects.filter(household=hh).count() == 1
    assert hh.food_security.fies_raw_score == 5

    # FCS — WFP weighted sum: 14+12+0+12+5+2+3.5+3.5+0 = 52.00.
    assert FoodConsumption.objects.filter(household=hh).count() == 1
    assert hh.food_consumption.fcs_score == Decimal("52.00")

    # --- Per-Member one-to-ones (head with HIV + disability) ---------
    assert Health.objects.filter(member=head).count() == 1
    # ADR-0019 encrypted round-trip: the helper decodes back to the
    # original list, INCLUDING the HIV code. EncryptedBinaryField's
    # from_db_value returns plaintext on read, so the binding contract
    # at this seam is the helper round-trip — the at-rest ciphertext
    # check belongs to the encryption-layer unit tests.
    decoded = head.health.get_chronic_illness_types()
    assert decoded == ["1", "4", "7"]
    assert "4" in decoded, "HIV code must round-trip through the encrypted helper"
    assert head.health.chronic_illness_types_encrypted

    # Disability: head has "03" (a lot of difficulty) -> wg_disability_flag True.
    assert Disability.objects.filter(member=head).count() == 1
    assert head.disability.wg_disability_flag is True
    # Spouse: all "01" -> wg_disability_flag False.
    assert spouse.disability.wg_disability_flag is False

    # Education + Employment for both members.
    for m in members:
        assert Education.objects.filter(member=m).count() == 1
        assert Employment.objects.filter(member=m).count() == 1
    assert head.education.highest_grade == "07"
    assert head.employment.sector == "1"

    # --- Repeat groups (5 detail tables, distinct row counts) --------
    assert AssetOwnership.objects.filter(household=hh).count() == 3
    assert Crop.objects.filter(household=hh).count() == 2
    assert Livestock.objects.filter(household=hh).count() == 4
    assert Shock.objects.filter(household=hh).count() == 1
    assert CopingStrategy.objects.filter(household=hh).count() == 3

    shock = Shock.objects.get(household=hh)
    assert shock.shock_type == "01"
    assert shock.livelihoods_affected == ["crops", "livestock"]
    assert shock.event_date == date(2026, 4, 1)

    # --- AuditEvent fanout: at least one row per detail entity_type --
    # AC-DE-AUDIT — every detail-entity create emits action="create" +
    # entity_type=<lowercase_model>.
    for et in _DETAIL_ENTITY_TYPES:
        count = AuditEvent.objects.filter(
            action="create", entity_type=et,
        ).count()
        assert count >= 1, f"missing AuditEvent for entity_type={et!r}"

    # Per-section row counts match (the rich payload produces exactly
    # the expected number of fanout audit rows).
    assert AuditEvent.objects.filter(
        action="create", entity_type="asset_ownership",
    ).count() == 3
    assert AuditEvent.objects.filter(
        action="create", entity_type="livestock",
    ).count() == 4
    assert AuditEvent.objects.filter(
        action="create", entity_type="health",
    ).count() == 2
    assert AuditEvent.objects.filter(
        action="create", entity_type="disability",
    ).count() == 2

    # Promotion AuditEvent itself fires once with the lineage envelope.
    promote_evt = AuditEvent.objects.get(
        action="promote", entity_type="household", entity_id=hh.id,
    )
    assert promote_evt.field_changes["stage_record_id"] == stage.id


# ---------------------------------------------------------------------------
# PMT recompute over the seeded 22-variable surface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_active_pmt_recomputes_22_variable_surface(connector, geo_codes):
    """Activate the seeded DRAFT model (version=22001, all weights 0)
    and prove the recompute_for_household call lands a PMTResult whose
    snapshot covers every variable, with the scoring chain staying
    under the 21-query budget for the e2e test's 2-member roster."""
    # Step 1 — promote a rich household so every variable resolves.
    payload = _rich_payload(geo_codes)
    hh, _stage = _drive_pipeline(connector, payload)

    # Step 2 — activate the migration-seeded DRAFT model. version=22001
    # was seeded by pmt/0002_seed_draft_detail_model.py with author=system
    # and weights=0.0, so the approver must differ from "system".
    seeded = PMTModelVersion.objects.get(version=22001)
    assert seeded.status == ModelStatus.DRAFT
    activate_model_version(seeded, approver="op2")
    seeded.refresh_from_db()
    assert seeded.status == ModelStatus.ACTIVE

    # Step 3 — recompute under query budget. AC-DE-PMT-NO-N-PLUS-1: the
    # scoring chain must NOT issue per-member queries. The fixed baseline
    # is 22: members are fetched once, the member-detail tables
    # (health/disability/education/employment) are batch-fetched via
    # member_id__in, and the household-detail tables (asset/livestock/
    # crop/shock/coping) are one query each — none scale with roster
    # size, so a 10-member household issues the same 22. The budget moved
    # 20 → 21 when the US-S22-DE expansion added one detail table, and
    # 21 → 22 when US-CONSENT-12 added the head's ELIGIBILITY-consent
    # gate (one constant lookup, NOT per-member). Any regression to a real
    # N+1 would push it past 22 and trip here.
    with CaptureQueriesContext(connection) as ctx:
        result = recompute_for_household(
            hh, triggered_by="dih_promote_e2e", actor="op2",
        )
    assert result is not None, "recompute returned None despite ACTIVE model"
    assert isinstance(result, PMTResult)

    query_count = len(ctx.captured_queries)
    assert query_count <= 22, (
        f"got {query_count} queries scoring 2-member household; "
        f"budget is 22:\n"
        + "\n".join(q["sql"][:120] for q in ctx.captured_queries)
    )

    # Step 4 — snapshot covers the full 22-variable surface. Every
    # variable that was seeded into the model lands in the snapshot
    # with a (raw, transformed, weight, contribution) record.
    snapshot_keys = set(result.inputs_snapshot.keys())
    seeded_variables = {v["variable"] for v in seeded.variables}
    assert seeded_variables == snapshot_keys, (
        f"seeded variables vs snapshot keys diverge: "
        f"missing={seeded_variables - snapshot_keys}, "
        f"extra={snapshot_keys - seeded_variables}"
    )
    # 22 in the seeded model — sanity that the migration didn't drift.
    assert len(seeded_variables) == 22

    # Every variable resolved to a non-None raw, including the chained
    # head_member.education.highest_grade + head_member.employment.sector
    # paths. (raw==0 is acceptable — _coerce maps None to 0, but the
    # snapshot stores the raw value before coercion. None would mean
    # the prefetch chain didn't attach the row.)
    for key, entry in result.inputs_snapshot.items():
        assert "raw" in entry and "transformed" in entry, (
            f"snapshot entry for {key!r} missing raw/transformed: {entry!r}"
        )
        # raw==None typically means the dotted path didn't resolve.
        # disabled_member_count + similar derived ints, plus the
        # detail-row paths, all populate non-None in the rich payload.
        assert entry["raw"] is not None, (
            f"variable {key!r} did not resolve to a non-None raw value"
        )

    # Band is non-empty.
    assert result.band  # one of extreme_poverty / poverty / vulnerable / not_poor

    # Household current_pmt_score gets stamped on recompute.
    hh.refresh_from_db()
    assert hh.current_pmt_score is not None
    assert hh.current_vulnerability_band == result.band


# ---------------------------------------------------------------------------
# Idempotency — promote replay is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_promote_is_idempotent_on_replay(connector, geo_codes):
    """Re-promoting the same StageRecord must not duplicate detail rows
    or audit events. The early-return at the top of promote_stage_record
    short-circuits the entire fanout."""
    payload = _rich_payload(geo_codes)
    run = start_connector_run(connector)
    landing = land_payload(run, {"raw": "rich-payload"})
    stage = stage_from_landing(landing, canonical_payload=payload)

    hh1 = promote_stage_record(stage, actor="op")
    # Counts after first promote.
    before = {
        et: AuditEvent.objects.filter(
            action="create", entity_type=et,
        ).count()
        for et in _DETAIL_ENTITY_TYPES
    }
    detail_counts_before = {
        "dwelling": Dwelling.objects.filter(household=hh1).count(),
        "utilities": Utilities.objects.filter(household=hh1).count(),
        "livelihood": Livelihood.objects.filter(household=hh1).count(),
        "food_security": FoodSecurity.objects.filter(household=hh1).count(),
        "food_consumption": FoodConsumption.objects.filter(household=hh1).count(),
        "assets": AssetOwnership.objects.filter(household=hh1).count(),
        "crops": Crop.objects.filter(household=hh1).count(),
        "livestock": Livestock.objects.filter(household=hh1).count(),
        "shocks": Shock.objects.filter(household=hh1).count(),
        "coping_strategies": CopingStrategy.objects.filter(household=hh1).count(),
        "health": Health.objects.filter(member__household=hh1).count(),
        "disability": Disability.objects.filter(member__household=hh1).count(),
        "education": Education.objects.filter(member__household=hh1).count(),
        "employment": Employment.objects.filter(member__household=hh1).count(),
    }

    # Replay — must return the SAME Household, no new rows / audits.
    hh2 = promote_stage_record(stage, actor="op")
    assert hh1.id == hh2.id

    after = {
        et: AuditEvent.objects.filter(
            action="create", entity_type=et,
        ).count()
        for et in _DETAIL_ENTITY_TYPES
    }
    assert before == after, (
        f"replay duplicated audit rows: before={before}, after={after}"
    )
    # And no detail rows duplicated.
    assert detail_counts_before["dwelling"] == 1
    assert Dwelling.objects.filter(household=hh1).count() == 1
    assert AssetOwnership.objects.filter(household=hh1).count() == \
        detail_counts_before["assets"]
    assert Livestock.objects.filter(household=hh1).count() == \
        detail_counts_before["livestock"]
    assert Health.objects.filter(member__household=hh1).count() == 2


# ---------------------------------------------------------------------------
# Unhappy path — payload missing every detail section still promotes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_promote_succeeds_with_empty_detail_sections(connector, geo_codes):
    """Defensive branch: a payload with NO detail sections still
    promotes, but zero detail rows land. Each helper short-circuits on
    a missing / empty section; the absence of audit rows for detail
    entities is itself part of the contract."""
    bare_payload = {
        "geographic": geo_codes,
        "urban_rural": "2",
        "members": [
            {
                "line_number": 1, "surname": "Lone", "first_name": "Solo",
                "sex": "1", "relationship_to_head": "01", "is_head": True,
            },
        ],
        # NO dwelling/utilities/livelihood/food_security/food_consumption
        # NO assets/crops/livestock/shocks/coping_strategies
        # NO per-member health/disability/education/employment
    }
    run = start_connector_run(connector)
    landing = land_payload(run, {"raw": "bare"})
    stage = stage_from_landing(landing, canonical_payload=bare_payload)
    hh = promote_stage_record(stage, actor="op")

    # Household + 1 Member still created.
    assert hh is not None
    assert hh.members.count() == 1

    # Zero detail rows.
    assert not Dwelling.objects.filter(household=hh).exists()
    assert not Utilities.objects.filter(household=hh).exists()
    assert not Livelihood.objects.filter(household=hh).exists()
    assert not FoodSecurity.objects.filter(household=hh).exists()
    assert not FoodConsumption.objects.filter(household=hh).exists()
    assert not AssetOwnership.objects.filter(household=hh).exists()
    assert not Crop.objects.filter(household=hh).exists()
    assert not Livestock.objects.filter(household=hh).exists()
    assert not Shock.objects.filter(household=hh).exists()
    assert not CopingStrategy.objects.filter(household=hh).exists()
    assert not Health.objects.filter(member__household=hh).exists()
    assert not Disability.objects.filter(member__household=hh).exists()
    assert not Education.objects.filter(member__household=hh).exists()
    assert not Employment.objects.filter(member__household=hh).exists()

    # Zero detail-entity AuditEvents from THIS household's promotion.
    # (We scope on stage.connector_run_id via the household.id audit
    # rows; the cheapest check is just "no detail rows -> no audits"
    # holds because each helper guards the emit on `created=True`.)
    # We assert on the per-entity action="create" rows being absent
    # for the entity_types — which is true at the table level because
    # this fixture's tests start with an empty DB.
    for et in _DETAIL_ENTITY_TYPES:
        assert AuditEvent.objects.filter(
            action="create", entity_type=et,
        ).count() == 0, (
            f"bare-payload promotion unexpectedly emitted audit for {et!r}"
        )

    # Promote event itself still fires.
    assert AuditEvent.objects.filter(
        action="promote", entity_type="household", entity_id=hh.id,
    ).exists()
