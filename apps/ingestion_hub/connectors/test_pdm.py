"""PDM connector tests — mapping unit tests + end-to-end pipeline run."""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household, Member
from apps.ingestion_hub.connectors.pdm import pdm_to_canonical
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

# --- Pure mapping ----------------------------------------------------------


class TestPdmMapping:
    def test_minimal_payload_maps(self):
        raw = {
            "pdm_household_id": "PDM-2026-00001",
            "sacco_code": "SACCO-99",
            "geographic": {
                "region": "R-NORTHERN", "sub_region": "SR-LANGO",
                "district": "DOKOLO", "county": "DOKOLO",
                "sub_county": "ADEKNINO", "parish": "AMUR", "village": "TEKWARO",
            },
            "members": [
                {"role": "Household Head", "surname": "ACENG", "first_name": "ALICE",
                 "sex": "F", "nin": "cf1234567890123x"},
                {"role": "Spouse", "surname": "OPIYO", "first_name": "JOHN",
                 "sex": "M"},
            ],
        }
        out = pdm_to_canonical(raw)
        assert out["geographic"]["district"] == "DOKOLO"
        # Post-ADR-0010: connector defaults urban_rural to blank when
        # upstream omits the field. The raw fixture above does not
        # carry an explicit urban_rural — DQA flags the gap.
        assert out["urban_rural"] == ""
        # Head detection + NIN uppercased.
        head = out["members"][0]
        assert head["is_head"] is True
        assert head["nin"] == "CF1234567890123X"
        assert head["relationship_to_head"] == ""
        spouse = out["members"][1]
        assert spouse["is_head"] is False
        assert spouse["relationship_to_head"] == "Spouse"
        # Source lineage retained.
        assert out["_source_keys"]["pdm_household_id"] == "PDM-2026-00001"

    def test_phone_fallback_picks_phone_when_telephone_1_missing(self):
        raw = {
            "geographic": _flat_geo(),
            "members": [{"role": "head", "surname": "X", "first_name": "Y",
                         "phone": "+256700000000"}],
        }
        out = pdm_to_canonical(raw)
        assert out["members"][0]["telephone_1"] == "+256700000000"

    def test_missing_geographic_block_raises(self):
        with pytest.raises(KeyError):
            pdm_to_canonical({"members": []})

    def test_empty_members_is_fine(self):
        out = pdm_to_canonical({"geographic": _flat_geo()})
        assert out["members"] == []


def _flat_geo() -> dict:
    return {"region": "R", "sub_region": "SR", "district": "D",
            "county": "C", "sub_county": "SC", "parish": "P", "village": "V"}


# --- End-to-end pipeline run ------------------------------------------------


@pytest.fixture
def pdm_geo(db):
    nodes = {}
    parent = None
    for level, code in [
        ("region", "R"), ("sub_region", "SR"), ("district", "D"),
        ("county", "C"), ("sub_county", "SC"), ("parish", "P"), ("village", "V"),
    ]:
        node = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent,
            effective_from=date(2026, 1, 1),
        )
        nodes[level] = node
        parent = node
    return nodes


@pytest.fixture
def pdm_connector(db):
    src = SourceSystem.objects.create(
        code="PDM-MIS", name="PDM MIS", kind=SourceSystemKind.PARTNER_MIS,
    )
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-PDM-1",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    return Connector.objects.create(source_system=src, name="pdm-mis-pull")


class TestPdmEndToEnd:
    def test_pdm_payload_promotes_through_pipeline(self, pdm_geo, pdm_connector):
        raw = {
            "pdm_household_id": "PDM-2026-9999",
            "sacco_code": "SACCO-77",
            "geographic": _flat_geo(),
            "members": [
                {"role": "Household Head", "surname": "ACENG",
                 "first_name": "ALICE", "sex": "F",
                 "nin": "CM12345678901230"},
                {"role": "Child", "surname": "ACENG",
                 "first_name": "JUNIOR", "sex": "M"},
            ],
        }
        canonical = pdm_to_canonical(raw)

        run = start_connector_run(pdm_connector)
        landing = land_payload(run, raw,
                               source_reference=raw["pdm_household_id"])
        stage = stage_from_landing(landing, canonical_payload=canonical)
        hh = promote_stage_record(stage, actor="pdm-import-bot")

        assert isinstance(hh, Household)
        members = Member.objects.filter(household=hh).order_by("line_number")
        assert members.count() == 2
        head = members.first()
        # ALICE is the head; nin_hash populated, last4 visible.
        assert head.first_name == "ALICE"
        assert head.nin_hash != ""
        assert head.nin_last4 == "1230"
        # Lineage: connector_run links back to PDM source.
        run.refresh_from_db()
        assert run.records_promoted == 1
