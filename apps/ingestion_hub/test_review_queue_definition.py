"""One definition of the DIH working queue.

The sidebar badge counted `state=pending_promotion` and read 0 while the
screen it pointed at held twelve records — nine in idv_pending, three in
quality_failed. The queue screen listed five states, the home card listed
four (it omitted ddup_review), and the badge listed one. Three
definitions of one concept, which is this project's most common defect.

The server now owns it and every caller asks for `?queue=review`.
"""

import pytest
from datetime import date

from apps.ingestion_hub.models import (
    REVIEW_QUEUE_STATES, TERMINAL_STAGE_STATES, StageRecordState,
)


class TestTheDefinition:
    def test_the_queue_is_every_state_that_is_not_finished(self):
        assert set(REVIEW_QUEUE_STATES) == {
            s.value for s in StageRecordState if s not in TERMINAL_STAGE_STATES
        }

    def test_the_states_an_operator_still_has_work_on_are_all_in_it(self):
        for state in (
            StageRecordState.PROVISIONAL,
            StageRecordState.QUALITY_FAILED,
            StageRecordState.IDV_PENDING,
            StageRecordState.DDUP_REVIEW,
            StageRecordState.PENDING_PROMOTION,
        ):
            assert state.value in REVIEW_QUEUE_STATES

    def test_finished_records_are_not_in_it(self):
        for state in (
            StageRecordState.PROMOTED,
            StageRecordState.REJECTED,
            StageRecordState.QUARANTINED,
        ):
            assert state.value not in REVIEW_QUEUE_STATES

    def test_a_new_state_joins_the_queue_rather_than_disappearing(self):
        """Derived by exclusion on purpose. A state added later and not
        marked terminal is work nobody has done yet, so every counter
        should see it without anyone remembering to update a list."""
        assert len(REVIEW_QUEUE_STATES) == len(StageRecordState) - len(
            TERMINAL_STAGE_STATES
        )


@pytest.mark.django_db
class TestTheEndpointAgreesWithTheDefinition:
    @pytest.fixture
    def queue(self, db, django_user_model):
        from apps.ingestion_hub.models import (
            Connector, ConnectorRun, RawLanding, SourceSystem, StageRecord,
        )

        source = SourceSystem.objects.create(code="T-QUEUE", name="Queue test")
        connector = Connector.objects.create(
            source_system=source, name="queue-test-connector",
        )
        run = ConnectorRun.objects.create(connector=connector)
        made = {}
        for state in StageRecordState:
            landing = RawLanding.objects.create(connector_run=run, payload={})
            made[state.value] = StageRecord.objects.create(
                raw_landing=landing, connector_run=run,
                canonical_payload={}, state=state,
            )
        return made

    def _client(self, client, django_user_model, name):
        user = django_user_model.objects.create_user(username=name, password="pw")
        user.is_staff = user.is_superuser = True
        user.save()
        client.force_login(user)
        return client

    def test_queue_review_returns_exactly_the_unfinished_records(
        self, client, django_user_model, queue,
    ):
        c = self._client(client, django_user_model, "q1")
        response = c.get("/api/v1/dih/stage-records/?queue=review&page_size=100")
        assert response.status_code == 200
        states = {r["state"] for r in response.json()["results"]}
        assert states == set(REVIEW_QUEUE_STATES)

    def test_the_count_matches_what_the_list_returns(
        self, client, django_user_model, queue,
    ):
        """The badge reads `count` off a page_size=1 response, so the
        count and the list must describe the same set — that mismatch is
        the whole defect."""
        c = self._client(client, django_user_model, "q2")
        badge = c.get("/api/v1/dih/stage-records/?queue=review&page_size=1")
        listing = c.get("/api/v1/dih/stage-records/?queue=review&page_size=100")
        assert badge.json()["count"] == len(listing.json()["results"])
        assert badge.json()["count"] == len(REVIEW_QUEUE_STATES)

    def test_promoted_and_rejected_never_appear(
        self, client, django_user_model, queue,
    ):
        c = self._client(client, django_user_model, "q3")
        response = c.get("/api/v1/dih/stage-records/?queue=review&page_size=100")
        states = {r["state"] for r in response.json()["results"]}
        assert not (states & {"promoted", "rejected", "quarantined"})

    def test_the_explicit_state_filter_still_works(
        self, client, django_user_model, queue,
    ):
        """?queue is an addition, not a replacement — other callers and
        the admin still filter by an explicit state."""
        c = self._client(client, django_user_model, "q4")
        response = c.get("/api/v1/dih/stage-records/?state=promoted&page_size=100")
        assert [r["state"] for r in response.json()["results"]] == ["promoted"]

    def test_stage_geography_labels_are_derived_from_geographicunit(
        self, client, django_user_model, db,
    ):
        """The DIH display projection never trusts connector label strings.

        The stored payload retains canonical codes for promotion; API reads
        obtain the visible names from the versioned Reference Data hierarchy.
        """
        from apps.ingestion_hub.models import (
            Connector, ConnectorRun, RawLanding, SourceSystem, StageRecord,
        )
        from apps.reference_data.models import GeographicUnit

        units = {}
        for level, parent in [
            ("region", None), ("sub_region", "region"),
            ("district", "sub_region"), ("county", "district"),
            ("sub_county", "county"), ("parish", "sub_county"),
            ("village", "parish"),
        ]:
            units[level] = GeographicUnit.objects.create(
                level=level, code=f"DISPLAY-{level}",
                name=f"Reference {level.replace('_', ' ').title()}",
                parent=units.get(parent), effective_from=date(2026, 1, 1),
            )
        source = SourceSystem.objects.create(code="T-GEO-LABEL", name="Test geo labels")
        connector = Connector.objects.create(source_system=source, name="test-geo-labels")
        run = ConnectorRun.objects.create(connector=connector)
        stage = StageRecord.objects.create(
            raw_landing=RawLanding.objects.create(connector_run=run, payload={}),
            connector_run=run,
            canonical_payload={
                "geographic": {
                    **{level: unit.code for level, unit in units.items()},
                    "_labels": {"parish": "Untrusted connector parish"},
                },
            },
        )
        c = self._client(client, django_user_model, "geo-label-reader")
        response = c.get(f"/api/v1/dih/stage-records/{stage.id}/")
        assert response.status_code == 200, response.content
        geography = response.json()["canonical_payload"]["geographic"]
        assert geography["_labels"] == {
            level: unit.name for level, unit in units.items()
        }
        # Serialization is a projection; source data stays code-only plus
        # its original lineage label, rather than being overwritten on read.
        stage.refresh_from_db()
        assert stage.canonical_payload["geographic"]["_labels"]["parish"] == "Untrusted connector parish"
