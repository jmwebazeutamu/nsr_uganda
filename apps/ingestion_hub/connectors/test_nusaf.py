"""NUSAF connector tests — mapping + end-to-end pipeline run."""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household, Member
from apps.ingestion_hub.connectors.nusaf import nusaf_to_canonical
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


class TestNusafMapping:
    def test_minimal_payload_maps(self):
        raw = {
            "nusaf_beneficiary_id": "NUSAF-2026-00042",
            "project_code": "NUSAF3-LIVELIHOODS",
            "geographic": {
                "region": "R-NORTHERN", "sub_region": "SR-ACHOLI",
                "district": "GULU", "county": "OMORO",
                "sub_county": "OPIT", "parish": "OPIT-NORTH",
                "village": "PADWAT",
            },
            "members": [
                {"role": "Won Pacu", "surname": "OKELLO",
                 "first_name": "OPIYO", "sex": "M",
                 "nin": "cm5555666677778888"},
                {"role": "Dako", "surname": "AKELLO",
                 "first_name": "MARY", "sex": "F"},
            ],
        }
        out = nusaf_to_canonical(raw)
        # Geographic codes pass through.
        assert out["geographic"]["district"] == "GULU"
        # Luo head term recognised.
        head = out["members"][0]
        assert head["is_head"] is True
        assert head["nin"] == "CM5555666677778888"
        assert head["relationship_to_head"] == ""
        # Dako preserved as the relationship label.
        wife = out["members"][1]
        assert wife["is_head"] is False
        assert wife["relationship_to_head"] == "Dako"
        # NUSAF lineage retained.
        assert out["_source_keys"]["nusaf_beneficiary_id"] == "NUSAF-2026-00042"
        assert out["_source_keys"]["project_code"] == "NUSAF3-LIVELIHOODS"

    def test_english_head_synonym_also_works(self):
        raw = {"geographic": _flat_geo(),
               "members": [{"role": "Household Head", "surname": "X",
                            "first_name": "Y"}]}
        assert nusaf_to_canonical(raw)["members"][0]["is_head"] is True

    def test_msisdn_alias_falls_into_telephone_1(self):
        raw = {"geographic": _flat_geo(),
               "members": [{"role": "head", "surname": "X", "first_name": "Y",
                            "msisdn": "+256755000123"}]}
        out = nusaf_to_canonical(raw)
        assert out["members"][0]["telephone_1"] == "+256755000123"

    def test_dict_shaped_geo_block_handled(self):
        """NUSAF sometimes nests {'code': 'X', 'name': '...'} per level."""
        raw = {
            "geographic": {
                "region": {"code": "R-N", "name": "Northern"},
                "sub_region": {"code": "SR-A", "name": "Acholi"},
                "district": {"code": "GULU", "name": "Gulu"},
                "county": "OMORO", "sub_county": "OPIT",
                "parish": "OPIT-NORTH", "village": "PADWAT",
            },
            "members": [],
        }
        out = nusaf_to_canonical(raw)
        assert out["geographic"]["region"] == "R-N"
        assert out["geographic"]["county"] == "OMORO"

    def test_missing_geographic_block_raises(self):
        with pytest.raises(KeyError):
            nusaf_to_canonical({"members": []})


def _flat_geo() -> dict:
    return {"region": "R", "sub_region": "SR", "district": "D",
            "county": "C", "sub_county": "SC", "parish": "P", "village": "V"}


# --- End-to-end pipeline run ------------------------------------------------


@pytest.fixture
def nusaf_geo(db):
    nodes = {}
    parent = None
    for level, code in [
        ("region", "NUSAF-R"), ("sub_region", "NUSAF-SR"),
        ("district", "NUSAF-D"), ("county", "NUSAF-C"),
        ("sub_county", "NUSAF-SC"), ("parish", "NUSAF-P"),
        ("village", "NUSAF-V"),
    ]:
        node = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent,
            effective_from=date(2026, 1, 1),
        )
        nodes[level] = node
        parent = node
    return nodes


@pytest.fixture
def nusaf_connector(db):
    src = SourceSystem.objects.create(
        code="NUSAF-MIS", name="NUSAF MIS", kind=SourceSystemKind.PARTNER_MIS,
    )
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-NUSAF-1",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    return Connector.objects.create(source_system=src, name="nusaf-mis-pull")


class TestNusafEndToEnd:
    def test_nusaf_payload_promotes_through_pipeline(
        self, nusaf_geo, nusaf_connector,
    ):
        raw = {
            "nusaf_beneficiary_id": "NUSAF-2026-99999",
            "project_code": "NUSAF3-LIVELIHOODS",
            "geographic": {
                "region": "NUSAF-R", "sub_region": "NUSAF-SR",
                "district": "NUSAF-D", "county": "NUSAF-C",
                "sub_county": "NUSAF-SC", "parish": "NUSAF-P",
                "village": "NUSAF-V",
            },
            "members": [
                {"role": "Won Pacu", "surname": "OKELLO",
                 "first_name": "OPIYO", "sex": "M",
                 "nin": "CM5555666677778888"},
                {"role": "Latin", "surname": "OKELLO",
                 "first_name": "ALEX", "sex": "M"},
            ],
        }
        canonical = nusaf_to_canonical(raw)

        run = start_connector_run(nusaf_connector)
        landing = land_payload(run, raw,
                               source_reference=raw["nusaf_beneficiary_id"])
        stage = stage_from_landing(landing, canonical_payload=canonical)
        hh = promote_stage_record(stage, actor="nusaf-import-bot")

        assert isinstance(hh, Household)
        members = Member.objects.filter(household=hh).order_by("line_number")
        assert members.count() == 2
        head = members.first()
        assert head.first_name == "OPIYO"
        assert head.nin_hash != ""
        assert head.nin_last4 == "8888"
        run.refresh_from_db()
        assert run.records_promoted == 1
