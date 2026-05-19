"""Serializer-contract tests for US-S22-005d.

The HouseholdSerializer and MemberSerializer must expose
`<field>_label` alongside `<field>` for every coded field in
choice_field_map. The household payload must also carry a
parallel `source_payload_labels` tree without mutating
`source_payload`.

The fixture mirrors Nsubuga Ruth's StageRecord shape (per project
memory) so the snapshot assertion at the end matches the bug
report verbatim.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.data_management.api import (
    HouseholdSerializer,
    MemberSerializer,
)
from apps.data_management.choice_field_map import (
    MEMBER_FIELDS,
)
from apps.data_management.models import Household, Member
from apps.ingestion_hub.models import (
    Connector,
    ConnectorRun,
    SourceSystem,
    SourceSystemKind,
    StageRecord,
    StageRecordState,
)
from apps.reference_data.models import GeographicUnit
from apps.reference_data.services import clear_resolver_cache


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def geo(db):
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"),
        ("district", "d", "sr"), ("county", "c", "d"),
        ("sub_county", "sc", "c"), ("parish", "p", "sc"),
        ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"LBL-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return nodes


@pytest.fixture
def household(db, geo):
    return Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"],
        county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
        village=geo["v"],
        urban_rural="2",       # rural
        dwelling_tenure="13",  # Free - private
        residence_status="01",  # Resident
    )


@pytest.fixture
def member(db, household):
    m = Member.objects.create(
        household=household, line_number=1,
        surname="Nsubuga", first_name="Ruth",
        sex="2", relationship_to_head="01",
        marital_status="11", nationality="1",
        residency_status="01", birth_certificate_status="1",
        nin_status="1",
    )
    household.head_member = m
    household.save()
    return m


@pytest.fixture
def nsubuga_payload():
    """Mirror of Nsubuga Ruth's StageRecord.canonical_payload —
    keys + codes match the user's bug report verbatim."""
    return {
        "housing": {
            "tenure": "13",
            "roof_material": "14",
            "wall_material": "11",
            "floor_material": "15",
            "lighting_source": "11",
            "water_source": "10",
            "toilet_type": "15",
            "cooking_fuel": "02",
            "waste_disposal": "18",
            "livelihood_source": "12",
            "assets_owned": "radio phone bicycle",
        },
        "agriculture": {
            "land_ownership": "4",
        },
    }


@pytest.fixture
def staged_household(db, household, nsubuga_payload):
    """Wire a StageRecord onto the household so source_payload
    resolves the way HouseholdSerializer.get_source_payload expects."""
    src = SourceSystem.objects.create(
        code="kobo-test", name="Kobo Test", kind=SourceSystemKind.KOBO,
    )
    conn = Connector.objects.create(source_system=src, name="t")
    run = ConnectorRun.objects.create(connector=conn)
    StageRecord.objects.create(
        connector_run=run,
        provisional_registry_id=household.id,
        canonical_payload=nsubuga_payload,
        state=StageRecordState.PROMOTED,
        promoted_at=datetime(2026, 3, 8, 8, 22, tzinfo=UTC),
    )
    return household


class TestMemberSerializer:
    def test_every_coded_field_has_label_field(self, member):
        data = MemberSerializer(member).data
        for field in MEMBER_FIELDS:
            assert field in data, f"raw {field} missing"
            assert f"{field}_label" in data, f"{field}_label missing"

    def test_known_codes_resolve_to_labels(self, member):
        data = MemberSerializer(member).data
        assert data["sex"] == "2"
        assert data["sex_label"] == "Female"
        assert data["relationship_to_head"] == "01"
        assert data["relationship_to_head_label"] == "Head"
        assert data["marital_status_label"] == "Married - Christian"
        assert data["nationality_label"] == "Ugandan"
        assert data["nin_status_label"] == "Yes, has card"


class TestHouseholdSerializerLabels:
    def test_household_orm_fields_have_labels(self, household):
        data = HouseholdSerializer(household).data
        assert data["urban_rural"] == "2"
        assert data["urban_rural_label"] == "Rural"
        assert data["dwelling_tenure"] == "13"
        assert data["dwelling_tenure_label"] == "Free - private"
        assert data["residence_status"] == "01"
        assert data["residence_status_label"] == "Resident"


class TestSourcePayloadLabels:
    def test_audit_blob_untouched(self, staged_household, nsubuga_payload):
        data = HouseholdSerializer(staged_household).data
        # source_payload is bit-for-bit the canonical_payload —
        # never mutated, never has _label keys merged in.
        assert data["source_payload"] == nsubuga_payload

    def test_labels_tree_resolves_housing(self, staged_household):
        data = HouseholdSerializer(staged_household).data
        labels = data["source_payload_labels"]
        h = labels["housing"]
        assert h["tenure"] == "Free - private"
        assert h["roof_material"] == "Concrete"
        assert h["wall_material"] == "Concrete/Stones"
        assert h["floor_material"] == "Rammed earth"
        assert h["lighting_source"] == "Candle"
        assert h["water_source"] == "Piped water into dwelling"
        assert h["toilet_type"] == "Uncovered Pit Latrine without a slab"
        assert h["cooking_fuel"] == "Electric stove"
        assert h["waste_disposal"] == "Bush"
        assert h["livelihood_source"] == "Commercial Farming"
        assert h["assets_owned"] == ["Radio", "Mobile phone", "Bicycle"]

    def test_labels_tree_resolves_agriculture(self, staged_household):
        data = HouseholdSerializer(staged_household).data
        assert data["source_payload_labels"]["agriculture"]["land_ownership"] == "Doesn't own"

    def test_no_bare_numeric_in_labels_payload(self, staged_household):
        """The acceptance criterion from the spec: no bare numeric
        value should leak through to any _label field on the
        Housing & Assets payload."""
        labels = HouseholdSerializer(staged_household).data["source_payload_labels"]

        def _walk(node):
            if isinstance(node, dict):
                for v in node.values():
                    yield from _walk(v)
            elif isinstance(node, list):
                for v in node:
                    yield from _walk(v)
            else:
                yield node

        for v in _walk(labels.get("housing", {})):
            assert not (isinstance(v, str) and v.isdigit() and len(v) <= 2), (
                f"bare numeric leaked through labels: {v!r}"
            )

    def test_no_payload_yields_empty_labels(self, household):
        # household has no StageRecord wired up
        data = HouseholdSerializer(household).data
        assert data["source_payload"] is None
        assert data["source_payload_labels"] == {}


class TestModelLabelMethods:
    def test_household_has_label_methods(self, household):
        assert household.get_urban_rural_label() == "Rural"
        assert household.get_dwelling_tenure_label() == "Free - private"
        assert household.get_residence_status_label() == "Resident"

    def test_member_has_label_methods(self, member):
        assert member.get_sex_label() == "Female"
        assert member.get_relationship_to_head_label() == "Head"
        assert member.get_marital_status_label() == "Married - Christian"
        assert member.get_nin_status_label() == "Yes, has card"
