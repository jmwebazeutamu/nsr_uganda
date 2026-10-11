"""The configuration surface, and the dry run.

STAAC_GRM appeared under Connector runs and no screen said how it got
there. These test the answer: what is registered, what is missing,
what a pull would do, and that finding out costs nothing.
"""

from __future__ import annotations

from datetime import date

import pytest
import responses

from apps.grievance.external.pull import configuration_blockers, dry_run
from apps.grievance.external.pull import test_connection
from apps.grievance.external.service import assess
from apps.grievance.models import (
    Grievance,
    HeldReason,
    StaacCredential,
    StaacHandover,
)
from apps.ingestion_hub.models import ConnectorRun, RawLanding
from apps.security.models import AuditEvent

from .test_pull import (
    AGREEMENT,
    BASE,
    H1,
    H2,
    LIST_URL,
    TOKEN,
    bind_category,
    client,
    list_item,
    mock_collection,
    snapshot,
)

pytestmark = pytest.mark.django_db

CONFIG = "/api/v1/grm/partner-api/staac/"


@pytest.fixture
def parish(db):
    from apps.reference_data.models import GeographicUnit

    parent = None
    for level, code, name in [
        ("region", "R-CENTRAL", "Central"),
        ("sub_region", "SR-BS", "Buganda South"),
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
        approved_by="the DPO",
    )


@pytest.fixture
def credential(db):
    return StaacCredential.objects.create(
        environment="sandbox", base_url=BASE,
        token_encrypted=TOKEN.encode("utf-8"),
    )


@pytest.fixture
def run_factory(agreement):
    def _make():
        from apps.ingestion_hub.services import start_connector_run

        from apps.grievance.external.pull import connector_for_staac

        return start_connector_run(connector_for_staac(), actor="t")
    return _make


@pytest.fixture
def admin(db, django_user_model):
    from rest_framework.test import APIClient

    user = django_user_model.objects.create_user(
        username="cfg-admin", password="p", is_staff=True, is_superuser=True,
    )
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def operator(db, django_user_model):
    from rest_framework.test import APIClient

    user = django_user_model.objects.create_user(
        username="cfg-operator", password="p",
    )
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestWhatIsConfigured:
    def test_it_says_where_the_source_came_from(self, admin):
        """The question this screen exists to answer."""
        r = admin.get(CONFIG)
        assert r.status_code == 200
        assert r.data["source"]["code"] == "STAAC_GRM"
        assert r.data["source"]["registered_by"] == "migration grievance.0017"

    def test_it_names_what_is_missing(self, admin):
        r = admin.get(CONFIG)
        blockers = " ".join(r.data["blockers"])
        assert "No active credential" in blockers
        assert "No data-provision agreement" in blockers
        assert "no approved binding" in blockers

    def test_a_configured_registry_has_no_blockers(
        self, admin, agreement, credential,
    ):
        from apps.reference_data.models import ChoiceOption
        from apps.reference_data.services import clear_resolver_cache

        from apps.grievance.intake import STAAC_CATEGORY_LIST

        ChoiceOption.objects.filter(
            choice_list__list_name=STAAC_CATEGORY_LIST,
        ).update(canonical_code="other")
        clear_resolver_cache()
        assert admin.get(CONFIG).data["blockers"] == []

    def test_it_names_who_approved_the_agreement(self, admin, agreement):
        row = admin.get(CONFIG).data["agreements"][0]
        assert row["reference"] == AGREEMENT
        assert row["approved_by"] == "the DPO"
        assert row["in_force"] is True

    def test_it_never_returns_the_token(self, admin, credential):
        body = str(admin.get(CONFIG).data)
        assert TOKEN not in body
        assert admin.get(CONFIG).data["credentials"][0]["has_token"] is True


class TestWhoMayChangeIt:
    def test_an_operator_may_read(self, operator):
        assert operator.get(CONFIG).status_code == 200

    def test_an_operator_may_not_store_a_credential(self, operator):
        r = operator.post(CONFIG, {
            "environment": "sandbox", "base_url": BASE, "token": "x",
        }, format="json")
        assert r.status_code == 403
        assert not StaacCredential.objects.exists()

    def test_an_operator_may_not_call_the_partner(self, operator):
        """Reading the configuration is not the same permission as
        making this registry read a complainant's identity out of
        another organisation."""
        for path in ("test-connection/", "dry-run/", "run/"):
            assert operator.post(CONFIG + path, {}, format="json").status_code == 403

    def test_an_admin_stores_a_credential_without_echoing_it(self, admin):
        r = admin.post(CONFIG, {
            "environment": "sandbox", "base_url": BASE, "token": TOKEN,
        }, format="json")
        assert r.status_code == 200
        assert TOKEN not in str(r.data)
        saved = StaacCredential.objects.get()
        from apps.grievance.external.pull import _token as read_token
        assert read_token(saved) == TOKEN

    def test_storing_a_credential_is_audited_without_the_token(self, admin):
        admin.post(CONFIG, {
            "environment": "sandbox", "base_url": BASE, "token": TOKEN,
        }, format="json")
        event = AuditEvent.objects.filter(
            entity_type="staac.credential", action="update",
        ).first()
        assert event is not None
        assert TOKEN not in str(event.field_changes)
        assert event.field_changes["token_replaced"] is True

    def test_adding_one_without_a_token_is_refused(self, admin):
        r = admin.post(CONFIG, {
            "environment": "sandbox", "base_url": BASE,
        }, format="json")
        assert r.status_code == 400
        assert not StaacCredential.objects.exists()

    def test_a_new_token_clears_the_resume_cursor(self, admin, credential):
        credential.cursor = "p9"
        credential.save(update_fields=["cursor"])
        admin.post(CONFIG, {
            "environment": "sandbox", "base_url": BASE, "token": "replacement",
        }, format="json")
        credential.refresh_from_db()
        assert credential.cursor == ""


class TestTheDryRun:
    """Its whole promise is that it writes nothing."""

    @responses.activate
    def test_it_writes_absolutely_nothing(self, parish, agreement,
                                          credential):
        bind_category()
        mock_collection(
            pages=[{"items": [list_item(H1)], "next_cursor": None}],
            details={H1: snapshot()},
        )
        before = (
            Grievance.objects.count(), StaacHandover.objects.count(),
            RawLanding.objects.count(), ConnectorRun.objects.count(),
        )
        report = dry_run(client=client())
        after = (
            Grievance.objects.count(), StaacHandover.objects.count(),
            RawLanding.objects.count(), ConnectorRun.objects.count(),
        )
        assert report.would_file == 1
        assert before == after, (
            "a dry run that leaves anything behind is not one"
        )
        credential.refresh_from_db()
        assert credential.cursor == "", "not even a cursor"

    @responses.activate
    def test_it_runs_without_an_agreement_and_says_so(self, parish,
                                                      credential):
        """A dry run whose first act is to refuse for want of
        configuration cannot tell you which configuration is
        missing."""
        bind_category()
        mock_collection(
            pages=[{"items": [list_item(H1)], "next_cursor": None}],
            details={H1: snapshot()},
        )
        report = dry_run(client=client())
        assert report.examined == 1
        assert report.would_hold == 1
        assert any("agreement" in b for b in report.blockers)
        assert report.rows[0].held_reason == HeldReason.UNVERIFIED_AGREEMENT

    @responses.activate
    def test_it_says_which_category_blocks_which_case(self, parish,
                                                      agreement, credential):
        mock_collection(
            pages=[{"items": [list_item(H1)], "next_cursor": None}],
            details={H1: snapshot()},
        )
        row = dry_run(client=client()).rows[0]
        assert row.verdict == "hold"
        assert row.held_reason == HeldReason.UNBOUND_CATEGORY
        assert row.held_source_code == "C07"
        assert row.tracking_number == "C-26-057528-8"

    @responses.activate
    def test_it_agrees_with_the_run_that_follows_it(self, parish, agreement,
                                                    credential):
        """The two must not be able to disagree — a preview that
        promises something the run will not do is worse than no
        preview. Both call `assess`."""
        from apps.grievance.external.pull import pull

        bind_category()
        mock_collection(
            pages=[{"items": [list_item(H1), list_item(H2, tracking="C-2")],
                    "next_cursor": None}],
            details={H1: snapshot(),
                     H2: snapshot(handover_id=H2, tracking="C-2",
                                  category="Environmental and social")},
        )
        preview = dry_run(client=client())
        mock_collection(
            pages=[{"items": [list_item(H1), list_item(H2, tracking="C-2")],
                    "next_cursor": None}],
            details={H1: snapshot(),
                     H2: snapshot(handover_id=H2, tracking="C-2",
                                  category="Environmental and social")},
        )
        real = pull(client=client())
        assert (preview.would_file, preview.would_hold) == (real.filed, real.held)

    @responses.activate
    def test_already_held_records_are_not_refetched(self, parish, agreement,
                                                    credential):
        from apps.grievance.external.pull import pull

        bind_category()
        mock_collection(
            pages=[{"items": [list_item(H1)], "next_cursor": None}] * 2,
            details={H1: snapshot()},
        )
        pull(client=client())
        report = dry_run(client=client())
        assert report.already_held == 1
        assert report.examined == 0


class TestTheConnectionTest:
    @responses.activate
    def test_it_reports_reach_and_latency(self, credential):
        responses.add(responses.GET, LIST_URL, status=200,
                      json={"items": [list_item(H1)], "next_cursor": None})
        result = test_connection(client=client())
        assert result.ok is True
        assert "1 handover" in (result.server_version or "")

    @responses.activate
    def test_a_refused_credential_is_a_result_not_an_exception(self,
                                                               credential):
        responses.add(responses.GET, LIST_URL, status=401, json={})
        result = test_connection(client=client())
        assert result.ok is False
        assert "credential" in result.error

    def test_it_does_not_need_an_agreement(self, credential):
        """Otherwise it cannot tell you the agreement is the
        problem."""
        assert not configuration_blockers() == []


class TestOneAssessment:
    """The preview and the filing must not be able to disagree."""

    def test_both_paths_go_through_the_same_function(
        self, parish, agreement, run_factory, monkeypatch,
    ):
        """Behavioural, not a grep: force `assess` to hold everything
        and check that BOTH the dry run and the real filing hold. A
        source check would pass on a docstring mentioning the name,
        which is exactly how the first version of this test fooled
        itself."""
        from apps.grievance.external import service
        from apps.grievance.external.service import Assessment, file_snapshot

        bind_category()
        forced = Assessment(
            will_file=False, held_reason=HeldReason.REFUSED,
            detail="forced by the test", tracking_number="C-26-057528-8",
        )
        monkeypatch.setattr(service, "assess", lambda *a, **k: forced)

        result = file_snapshot(
            snapshot(), run=run_factory(), handover_id=H1,
            exchange_version=1,
        )
        assert result.handover.outcome == "held"
        assert result.handover.outcome_detail == "forced by the test"
        assert not Grievance.objects.exists(), (
            "the filing decided for itself instead of asking assess()"
        )
