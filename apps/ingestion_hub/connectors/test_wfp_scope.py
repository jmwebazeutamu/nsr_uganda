"""WFP SCOPE connector tests — mapping + end-to-end pipeline run."""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household, Member
from apps.ingestion_hub.connectors.wfp_scope import wfp_scope_to_canonical
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


def _flat_geo() -> dict:
    return {"region": "R", "sub_region": "SR", "district": "D",
            "county": "C", "sub_county": "SC", "parish": "P", "village": "V"}


class TestScopeMapping:
    def test_minimal_payload_maps(self):
        raw = {
            "scope_beneficiary_id": "UGA-2026-1234567",
            "cohort_code": "REFUGEE-WESTNILE-2026",
            "geographic": _flat_geo(),
            "members": [
                {"role": "Head of Household", "name_en": "AGNES OKELLO",
                 "sex": "F", "state": "active", "nin": "cf9999000011112222"},
                {"role": "Child", "name_en": "PETER OKELLO",
                 "sex": "M", "state": "active"},
            ],
        }
        out = wfp_scope_to_canonical(raw)
        # Geographic codes pass through.
        assert out["geographic"]["village"] == "V"
        # Head detection via the UN HOH vocabulary.
        head = out["members"][0]
        assert head["is_head"] is True
        # English name split into surname / first_name.
        assert head["surname"] == "OKELLO"
        assert head["first_name"] == "AGNES"
        # NIN normalised to upper.
        assert head["nin"] == "CF9999000011112222"
        # SCOPE lineage retained.
        assert out["_source_keys"]["scope_beneficiary_id"] == "UGA-2026-1234567"

    def test_inactive_member_dropped_with_count(self):
        raw = {
            "geographic": _flat_geo(),
            "members": [
                {"role": "head", "name_en": "X Y", "state": "active"},
                {"role": "spouse", "name_en": "A B", "state": "inactive"},
                {"role": "child", "name_en": "C D", "state": "registered"},
            ],
        }
        out = wfp_scope_to_canonical(raw)
        # Only the active member survives.
        assert len(out["members"]) == 1
        assert out["_source_keys"]["dropped_inactive"] == 2

    def test_local_name_preserved_for_lineage(self):
        raw = {
            "geographic": _flat_geo(),
            "members": [
                {"role": "head", "name_en": "OPIYO MARTIN",
                 "name_local": "ओप्योइ मार्टिन", "state": "active"},
            ],
        }
        out = wfp_scope_to_canonical(raw)
        # Local-language name lives in _local_name on the member row
        # so audit lineage can show what came in.
        assert out["members"][0]["_local_name"] == "ओप्योइ मार्टिन"

    def test_explicit_surname_overrides_name_en_split(self):
        # When SCOPE provides explicit surname/first_name, prefer them
        # over the heuristic split of name_en.
        raw = {
            "geographic": _flat_geo(),
            "members": [
                {"role": "head", "name_en": "MARY OKELLO JANE",
                 "surname": "OKELLO", "first_name": "MARY", "state": "active"},
            ],
        }
        m = wfp_scope_to_canonical(raw)["members"][0]
        assert m["surname"] == "OKELLO"
        assert m["first_name"] == "MARY"

    def test_missing_geographic_block_raises(self):
        with pytest.raises(KeyError):
            wfp_scope_to_canonical({"members": []})


# --- End-to-end pipeline run ------------------------------------------------


@pytest.fixture
def scope_geo(db):
    nodes = {}
    parent = None
    for level, code in [
        ("region", "WFP-R"), ("sub_region", "WFP-SR"),
        ("district", "WFP-D"), ("county", "WFP-C"),
        ("sub_county", "WFP-SC"), ("parish", "WFP-P"),
        ("village", "WFP-V"),
    ]:
        node = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent,
            effective_from=date(2026, 1, 1),
        )
        nodes[level] = node
        parent = node
    return nodes


@pytest.fixture
def scope_connector(db):
    src = SourceSystem.objects.create(
        code="WFP-SCOPE", name="WFP SCOPE", kind=SourceSystemKind.WFP_SCOPE,
    )
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-WFP-SCOPE-1",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    return Connector.objects.create(source_system=src, name="wfp-scope-pull")


class TestScopeEndToEnd:
    def test_scope_payload_promotes_through_pipeline(
        self, scope_geo, scope_connector,
    ):
        raw = {
            "scope_beneficiary_id": "UGA-2026-9999999",
            "cohort_code": "REFUGEE-WESTNILE-2026",
            "geographic": {
                "region": "WFP-R", "sub_region": "WFP-SR",
                "district": "WFP-D", "county": "WFP-C",
                "sub_county": "WFP-SC", "parish": "WFP-P",
                "village": "WFP-V",
            },
            "members": [
                {"role": "Head of Household", "name_en": "AGNES OKELLO",
                 "sex": "F", "state": "active", "nin": "CF9999000011112222"},
                {"role": "spouse", "name_en": "PETER OKELLO", "sex": "M",
                 "state": "active"},
                {"role": "child", "name_en": "JOY OKELLO", "sex": "F",
                 "state": "inactive"},  # dropped
            ],
        }
        canonical = wfp_scope_to_canonical(raw)
        assert canonical["_source_keys"]["dropped_inactive"] == 1

        run = start_connector_run(scope_connector)
        landing = land_payload(run, raw,
                               source_reference=raw["scope_beneficiary_id"])
        stage = stage_from_landing(landing, canonical_payload=canonical)
        hh = promote_stage_record(stage, actor="scope-import-bot")

        assert isinstance(hh, Household)
        members = Member.objects.filter(household=hh).order_by("line_number")
        # Only the two active members made it through.
        assert members.count() == 2
        head = members.first()
        assert head.first_name == "AGNES"
        assert head.surname == "OKELLO"
        assert head.nin_last4 == "2222"
        run.refresh_from_db()
        assert run.records_promoted == 1
