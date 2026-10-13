"""The push receiver: the same record, arriving the other way.

Push is an optimisation on top of pull, so what matters most here is
that the two paths cannot disagree — same landing, same agreement
gate, same idempotency key — and that a record arriving twice by
either route is one record.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from apps.grievance.external.receiver import parse_idempotency_key
from apps.grievance.models import (
    Grievance,
    HandoverOutcome,
    HeldReason,
    StaacHandover,
)
from apps.ingestion_hub.models import ConnectorRun, RawLanding
from apps.security.models import AuditEvent

from .test_pull import (  # reuse one definition of the payload
    AGREEMENT,
    H1,
    bind_category,
    snapshot,
    unbind_category,
)

pytestmark = pytest.mark.django_db

SECRET = "push-shared-secret"  # noqa: S105 — synthetic placeholder
URL = "/api/v1/grm/partners/staac/handovers/"


@pytest.fixture
def parish(db):
    from apps.reference_data.models import GeographicUnit

    parent = None
    for level, code, name in [
        ("region", "R-CENTRAL", "Central"),
        ("sub_region", "SR-BUGANDA-SOUTH", "Buganda South"),
        ("district", "101", "Kalangala"),
        ("county", "101.1", "Bujumba County"),
        ("sub_county", "101.1.01", "Bujumba"),
        ("parish", "101.1.01.01", "Bujumba"),
    ]:
        parent = GeographicUnit.objects.create(
            level=level, code=code, name=name, parent=parent,
            effective_from=date(2026, 1, 1),
        )
    return parent


@pytest.fixture
def agreement(db):
    from apps.grievance.external import SOURCE_CODE
    from apps.ingestion_hub.models import DataProvisionAgreement, SourceSystem

    return DataProvisionAgreement.objects.create(
        source_system=SourceSystem.objects.get(code=SOURCE_CODE),
        reference=AGREEMENT, valid_from=date(2026, 1, 1),
    )


@pytest.fixture
def push(settings, client):
    settings.GRM_STAAC_PUSH_SECRET = SECRET

    def _post(body=None, *, key=None, secret=SECRET, **extra):
        body = snapshot() if body is None else body
        version = body.get("exchange_version", 1)
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {secret}",
            "HTTP_IDEMPOTENCY_KEY": (
                key if key is not None
                else f"partner:{body['handover_id']}:{version}:handover"
            ),
            **extra,
        }
        return client.post(
            URL, data=json.dumps(body),
            content_type="application/json", **headers,
        )
    return _post


class TestTheKey:
    def test_it_reads_the_specified_shape(self):
        assert parse_idempotency_key(
            "partner:abc:2:handover") == ("abc", 2)

    @pytest.mark.parametrize("raw", [
        "", "abc", "partner:abc:2", "other:abc:2:handover",
        "partner:abc:2:withdrawal", "partner:abc:zero:handover",
        "partner:abc:0:handover",
    ])
    def test_it_refuses_anything_else(self, raw):
        with pytest.raises(ValueError):
            parse_idempotency_key(raw)


class TestAuthentication:
    def test_without_a_configured_secret_nothing_is_accepted(
        self, settings, client, parish, agreement,
    ):
        """An endpoint that writes grievances and authenticates
        nobody is worse than no endpoint. §6.1 of the contract says
        the real profile is still to be agreed."""
        settings.GRM_STAAC_PUSH_SECRET = ""
        body = snapshot()
        r = client.post(
            URL, data=json.dumps(body), content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"partner:{H1}:1:handover",
            HTTP_AUTHORIZATION="Bearer anything",
        )
        assert r.status_code == 401
        assert not StaacHandover.objects.exists()

    def test_a_wrong_secret_is_refused(self, push, parish, agreement):
        assert push(secret="not-it").status_code == 401
        assert not StaacHandover.objects.exists()

    def test_the_same_answer_either_way(self, settings, client, push,
                                        parish, agreement):
        """A caller must not learn whether the receiver is unconfigured
        or its secret is wrong."""
        wrong = push(secret="not-it")
        settings.GRM_STAAC_PUSH_SECRET = ""
        unset = push(secret="not-it")
        assert wrong.status_code == unset.status_code == 401
        assert wrong.json() == unset.json()


class TestReceiving:
    def test_a_pushed_snapshot_is_filed(self, push, parish, agreement):
        bind_category()
        r = push()
        assert r.status_code == 202, r.content
        assert r.json()["outcome"] == HandoverOutcome.FILED
        assert r.json()["duplicate"] is False
        g = Grievance.objects.get()
        assert g.external_reference == "C-26-057528-8"
        assert g.parish_code == "101.1.01.01"

    def test_it_lands_in_the_same_table_as_a_pull(self, push, parish,
                                                  agreement):
        bind_category()
        push()
        landing = RawLanding.objects.get()
        assert landing.source_reference == H1
        assert StaacHandover.objects.get().raw_landing_id == landing.id

    def test_the_same_push_twice_is_one_record(self, push, parish, agreement):
        """The spec requires a duplicate to succeed without creating
        another grievance, because STAAC's outbox retries."""
        bind_category()
        first = push()
        again = push()
        assert first.status_code == again.status_code == 202
        assert again.json()["duplicate"] is True
        assert Grievance.objects.count() == 1
        assert StaacHandover.objects.count() == 1
        assert RawLanding.objects.count() == 1

    def test_a_record_already_pulled_is_not_created_again(
        self, push, parish, agreement,
    ):
        """Push and pull are the same record arriving twice."""
        from apps.grievance.external.pull import connector_for_staac
        from apps.grievance.external.service import file_snapshot
        from apps.ingestion_hub.services import start_connector_run

        bind_category()
        run = start_connector_run(connector_for_staac(), actor="t")
        file_snapshot(snapshot(), run=run, handover_id=H1, exchange_version=1)
        r = push()
        assert r.json()["duplicate"] is True
        assert Grievance.objects.count() == 1

    def test_an_unbound_category_is_held_and_still_accepted(
        self, push, parish, agreement,
    ):
        """Non-2xx tells STAAC to retry, and retrying will not bind a
        category. Accepted-and-held is the honest answer."""
        unbind_category()
        r = push()
        assert r.status_code == 202
        assert r.json()["outcome"] == HandoverOutcome.HELD
        assert StaacHandover.objects.get().held_reason == (
            HeldReason.UNBOUND_CATEGORY
        )
        assert not Grievance.objects.exists()

    def test_a_key_that_disagrees_with_the_body_is_refused(
        self, push, parish, agreement,
    ):
        bind_category()
        r = push(key=f"partner:{H1}:7:handover")
        assert r.status_code == 409
        assert not StaacHandover.objects.exists()

    def test_a_malformed_key_is_refused(self, push, parish, agreement):
        assert push(key="nonsense").status_code == 400
        assert not StaacHandover.objects.exists()

    def test_no_agreement_means_not_ready_not_bad_request(self, push, parish):
        """503 so STAAC retries: nothing is wrong with its request, and
        once the agreement is recorded the retry works."""
        bind_category()
        r = push()
        assert r.status_code == 503
        assert not StaacHandover.objects.exists()
        assert not RawLanding.objects.exists()

    def test_receiving_is_audited_and_distinguishable_from_a_pull(
        self, push, parish, agreement,
    ):
        bind_category()
        push()
        event = AuditEvent.objects.filter(entity_type="staac.push").first()
        assert event is not None
        assert event.actor_id == "staac-push"
        assert event.field_changes["handover_id"] == H1

    def test_the_run_is_recorded(self, push, parish, agreement):
        bind_category()
        push()
        run = ConnectorRun.objects.latest("started_at")
        assert run.records_received == 1
        assert run.records_promoted == 1
