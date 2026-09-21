"""Regression tests for the second capture run (20 Sep 2026).

Four households have now been captured through the Operator Console.
Every one of them was stuck: the wizard posted `geographic.subregion`,
promotion required `geographic.sub_region`, and the walk-in endpoint
swallowed the resulting DihError. The records sat at `provisional` with
an EMPTY dqa_summary — which the review queue renders as
"clean · 0 blocking · 0 warnings".

That one bug produced two of the reported symptoms and hid a third:

  * the IDV gate reported "not run" on a record that plainly held a NIN
    (the gates never executed at all);
  * DQA reported clean on records nothing had evaluated;
  * and it was invisible in round 1, because round 1's own tests built
    their payloads with the REGISTRY's key names rather than the ones
    the wizard actually posts.

`_wizard_payload` below is therefore built from the wizard's real output
shape — the keys screens-capture.jsx posts — not from the shape the
backend finds convenient.
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
    StageRecordState,
)
from apps.ingestion_hub.services import (
    GATE_NOT_RUN_RULE_ID,
    IDV_NIN_PARTIAL,
    IDV_NOT_RUN_RULE_ID,
    normalise_geographic_keys,
    process_stage_record,
    promote_stage_record,
    submit_walk_in_capture,
)
from apps.reference_data.models import GeographicUnit


@pytest.fixture
def geo(db):
    codes = [
        ("region", "R2-R"), ("sub_region", "R2-SR"), ("district", "R2-D"),
        ("county", "R2-C"), ("sub_county", "R2-SC"), ("parish", "R2-P"),
    ]
    parent = None
    for level, code in codes:
        parent = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent,
            effective_from=date(2026, 1, 1),
        )
    return {c for _, c in codes}


@pytest.fixture
def walkin_connector(db):
    src, _ = SourceSystem.objects.get_or_create(
        code="PARISH-WALKIN",
        defaults={"name": "Parish walk-in", "kind": SourceSystemKind.CAPI_WALKIN},
    )
    connector, _ = Connector.objects.get_or_create(
        source_system=src, name="parish-walkin",
    )
    return connector


def _wizard_payload(**over) -> dict:
    """EXACTLY what design/v0.1/screens/screens-capture.jsx posts.

    Keys, nesting and spelling all matter here: a test that renames them
    to suit the backend is a test that cannot catch a rename.
    """
    payload = {
        "geographic": {
            "region": "R2-R", "sub_region": "R2-SR", "district": "R2-D",
            "county": "R2-C", "sub_county": "R2-SC", "parish": "R2-P",
            "village": "",
            "_labels": {"region": "R2-R", "parish": "R2-P"},
        },
        "urban_rural": "2",
        "address_narrative": "third homestead past the trading centre",
        "consent": "yes",
        "respondent_name": "Okello Santo",
        "contact_phone": "+256782998877",
        "members": [{
            "line_number": 1, "surname": "Okello", "first_name": "Santo",
            "sex": "1", "relationship_to_head": "01", "is_head": True,
            "date_of_birth": "1979-03-12", "age_years": 47,
            "nin_status": "1", "nin_last4": "7766",
            "telephone_1": "+256782998877",
        }],
        "source_channel": "parish_walkin",
    }
    payload.update(over)
    return payload


def _no_nin_payload() -> dict:
    """A capture carrying no identity evidence, so nothing flags and the
    record is eligible for the fast-track auto-promote."""
    payload = _wizard_payload()
    payload["members"][0].pop("nin_status", None)
    payload["members"][0].pop("nin_last4", None)
    return payload


def _legacy_wizard_payload() -> dict:
    """The spelling the wizard used until 20 Sep 2026, and the spelling
    every record already staged is carrying."""
    payload = _wizard_payload()
    geo = payload["geographic"]
    payload["geographic"] = {
        "region": geo["region"], "subregion": geo["sub_region"],
        "district": geo["district"], "county": geo["county"],
        "subcounty": geo["sub_county"], "parish": geo["parish"], "village": "",
    }
    return payload


# ---------------------------------------------------------------------------
# The key mismatch itself.


class TestGeographicKeyNormalisation:
    def test_legacy_spelling_is_copied_onto_the_canonical_key(self):
        out = normalise_geographic_keys(_legacy_wizard_payload())
        assert out["geographic"]["sub_region"] == "R2-SR"
        assert out["geographic"]["sub_county"] == "R2-SC"

    def test_the_legacy_key_is_left_in_place(self):
        """The raw landing and the canonical payload have to stay
        comparable — erasing what the wizard sent makes the lineage
        chain harder to audit, not easier."""
        out = normalise_geographic_keys(_legacy_wizard_payload())
        assert out["geographic"]["subregion"] == "R2-SR"

    def test_a_canonical_payload_is_returned_untouched(self):
        payload = _wizard_payload()
        assert normalise_geographic_keys(payload) is payload

    def test_a_present_canonical_key_is_never_overwritten(self):
        payload = _legacy_wizard_payload()
        payload["geographic"]["sub_region"] = "ALREADY-SET"
        out = normalise_geographic_keys(payload)
        assert out["geographic"]["sub_region"] == "ALREADY-SET"

    @pytest.mark.parametrize("payload", [
        {}, {"geographic": None}, {"geographic": "nope"}, None, [],
    ])
    def test_malformed_input_does_not_raise(self, payload):
        normalise_geographic_keys(payload)


@pytest.mark.django_db
class TestWalkInCaptureActuallyCompletes:
    URL = "/api/v1/dih/walk-in-submissions/"

    def _client(self, django_user_model):
        user = django_user_model.objects.create_user(
            username="parish-op-r2", password="p",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_the_wizards_own_payload_reaches_the_registry(
        self, django_user_model, geo, walkin_connector,
    ):
        """The whole defect in one assertion: post what the wizard
        posts, and the record must not be left sitting at provisional."""
        response = self._client(django_user_model).post(
            self.URL, _wizard_payload(), format="json",
        )
        assert response.status_code == 201, response.data
        stage = StageRecord.objects.get(pk=response.data["id"])
        assert stage.state != StageRecordState.PROVISIONAL, (
            "the staging gates did not run — the record is in the queue "
            "showing an empty DQA summary, which reads as 'clean'"
        )

    def test_a_record_already_staged_under_the_old_spelling_can_still_promote(
        self, geo, walkin_connector,
    ):
        """Four records were stranded this way. They have to be
        recoverable, not rewritten by hand."""
        stage = submit_walk_in_capture(_legacy_wizard_payload(), actor="op")
        stage = process_stage_record(stage, actor="op")
        assert stage.state != StageRecordState.PROVISIONAL
        if stage.state != StageRecordState.PROMOTED:
            promote_stage_record(stage, actor="nsr-reviewer")
        assert Household.objects.filter(id=stage.provisional_registry_id).exists()

    def test_a_gate_failure_is_written_onto_the_record(
        self, django_user_model, geo, walkin_connector,
    ):
        """An empty dqa_summary is indistinguishable from a clean pass on
        every surface that reads it. A record whose gates could not run
        must not look like one that passed them.

        Uses a payload with no NIN so nothing flags and the record takes
        the fast-track path into promote_stage_record — which is where
        the original `sub_region required` DihError was raised, and
        swallowed.
        """
        payload = _no_nin_payload()
        payload["geographic"]["parish"] = "NO-SUCH-PARISH"
        response = self._client(django_user_model).post(
            self.URL, payload, format="json",
        )
        assert response.status_code == 201, response.data
        stage = StageRecord.objects.get(pk=response.data["id"])
        assert stage.state == StageRecordState.QUALITY_FAILED
        codes = [f["rule_id"] for f in stage.dqa_summary["blocking_failures"]]
        assert GATE_NOT_RUN_RULE_ID in codes
        reason = stage.dqa_summary["blocking_failures"][0]["reason"]
        assert "NO-SUCH-PARISH" in reason, (
            "the finding has to name what actually went wrong"
        )

    def test_the_registry_id_still_survives_a_gate_failure(
        self, django_user_model, geo, walkin_connector,
    ):
        """The respondent has already been handed the slip. A gate
        failure must not void their ID."""
        payload = _no_nin_payload()
        payload["geographic"]["parish"] = "NO-SUCH-PARISH"
        response = self._client(django_user_model).post(
            self.URL, payload, format="json",
        )
        assert len(response.data["provisional_registry_id"]) == 26
        assert response.data["provisional_registry_id"] == response.data["id"]


# ---------------------------------------------------------------------------
# Item 1 — the IDV gate.


@pytest.mark.django_db
class TestIdvReadsThePersistedNin:
    def test_a_recorded_nin_produces_an_idv_outcome(self, geo, walkin_connector):
        stage = submit_walk_in_capture(_wizard_payload(), actor="op")
        stage = process_stage_record(stage, actor="op")
        assert stage.idv_outcome == IDV_NIN_PARTIAL, (
            "the record holds a NIN; 'not run' with no explanation is the "
            "report that sent an operator looking for a field that was set"
        )

    def test_dqa_flags_a_nin_that_was_never_verified(self, geo, walkin_connector):
        stage = submit_walk_in_capture(_wizard_payload(), actor="op")
        stage = process_stage_record(stage, actor="op")
        codes = [w["rule_id"] for w in stage.dqa_summary["warnings"]]
        assert IDV_NOT_RUN_RULE_ID in codes

    def test_an_unverified_nin_is_kept_out_of_the_fast_track(
        self, geo, walkin_connector,
    ):
        """AC-DIH-FT-AUTO's `idv_ok` is satisfied by "no NIN", so a
        household that produced a card at the desk used to auto-promote
        with no verification of any kind."""
        stage = submit_walk_in_capture(_wizard_payload(), actor="op")
        stage = process_stage_record(stage, actor="op")
        assert stage.state == StageRecordState.PENDING_PROMOTION

    def test_a_household_with_no_nin_is_not_flagged(self, geo, walkin_connector):
        payload = _wizard_payload()
        payload["members"][0].pop("nin_status")
        payload["members"][0].pop("nin_last4")
        stage = submit_walk_in_capture(payload, actor="op")
        stage = process_stage_record(stage, actor="op")
        assert stage.idv_outcome == ""
        codes = [w["rule_id"] for w in stage.dqa_summary["warnings"]]
        assert IDV_NOT_RUN_RULE_ID not in codes


# ---------------------------------------------------------------------------
# Item 2 — the household contact number.


@pytest.mark.django_db
class TestHouseholdContactNumber:
    def test_the_head_telephone_is_the_contact_number(self, geo, walkin_connector):
        """ADR-0033: one number, on Member.telephone_1 of the head.
        Identification's phone box writes to that member, so there is no
        second field to fall out of step with it."""
        stage = submit_walk_in_capture(_wizard_payload(), actor="op")
        stage = process_stage_record(stage, actor="op")
        if stage.state != StageRecordState.PROMOTED:
            promote_stage_record(stage, actor="nsr-reviewer")
        head = Member.objects.get(
            household_id=stage.provisional_registry_id, line_number=1,
        )
        assert head.telephone_1 == "+256782998877"

    def test_the_respondent_name_is_kept(self, geo, walkin_connector):
        """The respondent is often not the head. The name was collected
        on screen and posted nowhere."""
        stage = submit_walk_in_capture(_wizard_payload(), actor="op")
        assert stage.canonical_payload["respondent_name"] == "Okello Santo"

    def test_the_address_narrative_reaches_the_household(self, geo, walkin_connector):
        """Household.address_narrative existed and promotion already read
        it; nothing collected it, so every record showed Address —."""
        stage = submit_walk_in_capture(_wizard_payload(), actor="op")
        stage = process_stage_record(stage, actor="op")
        if stage.state != StageRecordState.PROMOTED:
            promote_stage_record(stage, actor="nsr-reviewer")
        household = Household.objects.get(id=stage.provisional_registry_id)
        assert household.address_narrative == "third homestead past the trading centre"

    def test_a_household_with_no_contact_number_still_captures(
        self, geo, walkin_connector,
    ):
        """No number is a legitimate state — the slip is then the only
        copy. It must not block the capture, and it must not be
        misreported as a number."""
        payload = _wizard_payload()
        payload["members"][0]["telephone_1"] = ""
        payload["contact_phone"] = ""
        stage = submit_walk_in_capture(payload, actor="op")
        stage = process_stage_record(stage, actor="op")
        if stage.state != StageRecordState.PROMOTED:
            promote_stage_record(stage, actor="nsr-reviewer")
        head = Member.objects.get(
            household_id=stage.provisional_registry_id, line_number=1,
        )
        assert head.telephone_1 == ""
