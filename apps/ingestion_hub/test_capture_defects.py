"""Regression tests for the defects found running a household capture
end to end through the Operator Console (19 Sep 2026).

Two households were captured at http://192.168.2.3:8005/console/ as an
enumerator, Start capture → 7 sections → Submit for promotion. Both
submitted, and 15 defects fell out. These cover the backend half of the
P0s and the reference-data P1s; the wizard half lives in
design/v0.1/screens/screens-capture.defects.test.jsx.
"""

from __future__ import annotations

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.data_management.models import Household, Member
from apps.ingestion_hub.models import (
    Connector,
    SourceSystem,
    SourceSystemKind,
    StageRecord,
)
from apps.ingestion_hub.services import (
    land_payload,
    process_stage_record,
    promote_stage_record,
    stage_from_landing,
    start_connector_run,
    submit_walk_in_capture,
)
from apps.reference_data.models import GeographicUnit


@pytest.fixture
def geo(db):
    """7-level UBOS ladder for these cases."""
    codes = [
        ("region", "CD-R"), ("sub_region", "CD-SR"), ("district", "CD-D"),
        ("county", "CD-C"), ("sub_county", "CD-SC"), ("parish", "CD-P"),
        ("village", "CD-V"),
    ]
    parent = None
    out = {}
    for level, code in codes:
        parent = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent,
            effective_from=date(2026, 1, 1),
        )
        out[level] = code
    return out


@pytest.fixture
def walkin_connector(db):
    """The seeded parish walk-in connector submit_walk_in_capture needs.

    Created here rather than relied on from the migration so the case
    stands up in an empty test database either way.
    """
    src, _ = SourceSystem.objects.get_or_create(
        code="PARISH-WALKIN",
        defaults={"name": "Parish walk-in", "kind": SourceSystemKind.CAPI_WALKIN},
    )
    connector, _ = Connector.objects.get_or_create(
        source_system=src, name="parish-walkin",
    )
    return connector


def _capture_payload(geo: dict) -> dict:
    """What the capture wizard posts: the shape the operator's two
    households actually produced, NIN fields included."""
    return {
        "geographic": geo,
        "urban_rural": "2",
        "consent": "yes",
        "members": [
            {
                "line_number": 1, "surname": "Akello", "first_name": "Grace",
                "sex": "2", "relationship_to_head": "01", "is_head": True,
                "date_of_birth": "1979-03-12", "age_years": 47,
                # The wizard collects NIN STATUS + LAST FOUR. Never the
                # full number — that is taken at the IDV step.
                "nin_status": "1", "nin_last4": "4821",
            },
        ],
        "source_channel": "parish_walkin",
    }


# ---------------------------------------------------------------------------
# P0 #1 — the receipt slip printed a Registry ID one increment off the
# staged record. `id` and `provisional_registry_id` were two separate
# generate_ulid() calls; python-ulid is monotonic, so they came out
# consecutive in Crockford base32 (…M1YT vs …M1YV).


@pytest.mark.django_db
class TestOneRegistryIdentifier:
    URL = "/api/v1/dih/walk-in-submissions/"

    def _client(self, django_user_model):
        user = django_user_model.objects.create_user(
            username="parish-op-defects", password="p",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_slip_id_and_persisted_record_id_are_the_same(
        self, django_user_model, geo, walkin_connector,
    ):
        """Submit a capture; the ID the slip renders IS the record's ID.

        This is the one the operator asked for by name: assert on both
        in a single submission, not on either alone.
        """
        response = self._client(django_user_model).post(
            self.URL, _capture_payload(geo), format="json",
        )
        assert response.status_code == 201, response.data

        # What the receipt slip and the SMS preview render.
        slip_id = response.data["provisional_registry_id"]
        # What the DIH review queue row is keyed on.
        queue_id = response.data["id"]
        assert slip_id == queue_id, (
            f"slip shows {slip_id}, queue shows {queue_id} — "
            "the respondent's tracking number does not address their record"
        )

        # And the persisted row agrees with both.
        stage = StageRecord.objects.get(pk=queue_id)
        assert stage.provisional_registry_id == stage.id == slip_id
        assert len(slip_id) == 26

    def test_promoted_household_keeps_the_same_identifier(
        self, django_user_model, geo, walkin_connector,
    ):
        """One ULID from slip to registry: no re-issue at promotion
        (AC-DIH-PROVISIONAL-ID)."""
        response = self._client(django_user_model).post(
            self.URL, _capture_payload(geo), format="json",
        )
        slip_id = response.data["provisional_registry_id"]
        stage = StageRecord.objects.get(pk=response.data["id"])
        if stage.state != "promoted":
            promote_stage_record(stage, actor="nsr-unit-reviewer")
            stage.refresh_from_db()
        assert Household.objects.filter(id=slip_id).exists(), (
            "the household the citizen can be looked up by is not the one "
            "printed on their slip"
        )

    def test_staging_never_mints_a_second_ulid(self, connector_run_payload):
        """Directly at the staging seam, where the two calls used to be."""
        run, payload = connector_run_payload
        landing = land_payload(run, payload)
        stage = stage_from_landing(landing, canonical_payload=payload)
        assert stage.id == stage.provisional_registry_id

    def test_the_two_ids_cannot_drift_even_if_a_writer_omits_one(
        self, connector_run_payload,
    ):
        """The model backstop: an omitted provisional_registry_id
        inherits `id` rather than defaulting to a fresh ULID."""
        run, payload = connector_run_payload
        landing = land_payload(run, payload)
        stage = StageRecord(
            raw_landing=landing, connector_run=run,
            canonical_payload=payload, state="provisional",
        )
        stage.provisional_registry_id = ""
        stage.save()
        assert stage.provisional_registry_id == stage.id


@pytest.fixture
def connector_run_payload(geo, walkin_connector):
    run = start_connector_run(walkin_connector, actor="test")
    return run, _capture_payload(geo)


# ---------------------------------------------------------------------------
# P0 #2 — NIN was never saved. Promotion read only a full `nin`, so the
# roster's nin_status / nin_last4 were dropped on the floor: the staged
# record showed "Head NIN —", the roster table "—" for every member, and
# the decision panel "No NIN provided or IDV not yet run".


@pytest.mark.django_db
class TestNinReachesTheRegistry:
    def test_nin_status_and_last4_survive_promotion(self, geo, walkin_connector):
        payload = _capture_payload(geo)
        stage = submit_walk_in_capture(payload, actor="parish-op")
        promote_stage_record(stage, actor="nsr-unit-reviewer")

        member = Member.objects.get(household_id=stage.provisional_registry_id,
                                    line_number=1)
        assert member.nin_last4 == "4821", (
            "the last four digits the enumerator typed did not reach the "
            "registry"
        )
        assert member.nin_status == "1"

    def test_a_full_nin_still_wins_over_the_roster_fields(self, geo, walkin_connector):
        """A source that supplies the whole number is authoritative — the
        encrypted value, the hash and the suffix have to agree."""
        payload = _capture_payload(geo)
        payload["members"][0]["nin"] = "CM90012345PQRS"
        payload["members"][0]["nin_last4"] = "0000"  # stale roster entry
        stage = submit_walk_in_capture(payload, actor="parish-op")
        if stage.state != "promoted":
            promote_stage_record(stage, actor="nsr-unit-reviewer")

        member = Member.objects.get(household_id=stage.provisional_registry_id,
                                    line_number=1)
        assert member.nin_last4 == "PQRS"
        assert member.nin_status == "1"
        assert member.nin_hash

    def test_a_roster_with_no_nin_at_all_stays_blank(self, geo, walkin_connector):
        payload = _capture_payload(geo)
        payload["members"][0].pop("nin_status")
        payload["members"][0].pop("nin_last4")
        stage = submit_walk_in_capture(payload, actor="parish-op")
        if stage.state != "promoted":
            promote_stage_record(stage, actor="nsr-unit-reviewer")
        member = Member.objects.get(household_id=stage.provisional_registry_id,
                                    line_number=1)
        assert member.nin_last4 == ""

    def test_idv_says_partial_rather_than_nothing(self, geo, walkin_connector):
        """"No NIN provided" was wrong for a household that produced a
        card at the desk. NIRA needs the full number, which the wizard
        never collects, so the honest outcome is its own state."""
        from apps.ingestion_hub.services import IDV_NIN_PARTIAL

        stage = submit_walk_in_capture(_capture_payload(geo), actor="parish-op")
        # The staging gates are what set idv_outcome; the walk-in API
        # runs them straight after submission.
        stage = process_stage_record(stage, actor="parish-op")
        assert stage.idv_outcome == IDV_NIN_PARTIAL

    def test_no_identity_evidence_leaves_idv_blank(self, geo, walkin_connector):
        payload = _capture_payload(geo)
        payload["members"][0].pop("nin_status")
        payload["members"][0].pop("nin_last4")
        stage = submit_walk_in_capture(payload, actor="parish-op")
        stage = process_stage_record(stage, actor="parish-op")
        assert stage.idv_outcome == ""
