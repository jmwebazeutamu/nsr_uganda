"""The STAAC pull, end to end, against a mocked partner.

STAAC is mocked with `responses` — the same way the Kobo connector is
tested — on a synthetic host, so a missed mock fails loudly instead of
reaching a real service.

The payloads here are taken from STAAC's served code rather than from
its written specification, because the two differ in five places and
the differences are the interesting part: `+00:00` instead of `Z`,
`display_name` carrying the key in brackets, `parish_key` at any
depth, `shared_data.fields` arriving sorted, and a cursor that is
rejected rather than expired.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import responses

from apps.grievance.external.client import (
    CursorRejected,
    StaacClient,
    StaacError,
)
from apps.grievance.external.pull import pull
from apps.grievance.external.service import file_held, file_snapshot
from apps.grievance.intake import STAAC_CATEGORY_LIST, STAAC_GENDER_LIST
from apps.grievance.models import (
    Category,
    Grievance,
    HandoverOutcome,
    StaacHandover,
)
from apps.reference_data.models import ChoiceOption, GeographicUnit
from apps.security.models import AuditEvent

pytestmark = pytest.mark.django_db

BASE = "https://staac.test.invalid"
LIST_URL = f"{BASE}/api/v1/integration/partners/handovers/"
TOKEN = "test-token"  # noqa: S105 — synthetic placeholder

H1 = "d8f05c04-4b0f-4e28-9d87-95c88e6c6a09"
H2 = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    from nsr_mis.common import http as shared_http

    monkeypatch.setattr(shared_http.time, "sleep", lambda _s: None)


@pytest.fixture(autouse=True)
def _forget_resolved_bindings():
    """The choice-list resolvers are lru_cached, and a cache outlives
    the transaction a test is rolled back with. Without this, a test
    that approves a binding leaves it visible to the next test, which
    is precisely how "an unmapped category is held" would pass while
    being wrong."""
    from apps.reference_data.services import clear_resolver_cache

    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def parish(db):
    """The real ladder for the worked example, built the way the
    registry holds one: STAAC's `101.1.01.01` is this registry's
    parish code, because both load the same UBOS frame."""
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


def bind_category(name="Targeting and selection irregularity",
                  canonical=Category.EXCLUSION_ERROR):
    """Approve one binding, the way the ChoiceList workflow would."""
    from apps.reference_data.services import clear_resolver_cache

    option = ChoiceOption.objects.get(
        choice_list__list_name=STAAC_CATEGORY_LIST, label=name,
    )
    option.canonical_code = canonical
    option.save(update_fields=["canonical_code"])
    clear_resolver_cache()
    return option


def bind_gender(code="female", canonical="2"):
    from apps.reference_data.services import clear_resolver_cache

    option = ChoiceOption.objects.get(
        choice_list__list_name=STAAC_GENDER_LIST, code=code,
    )
    option.canonical_code = canonical
    option.save(update_fields=["canonical_code"])
    clear_resolver_cache()


def snapshot(
    handover_id=H1, version=1, tracking="C-26-057528-8",
    category="Targeting and selection irregularity",
    parish_key="101.1.01.01", display_name="BUJUMBA [101.1.01.01]",
    complainant=None, received_at="2026-10-11T00:02:49.571666+00:00",
):
    """A detail response in the shape STAAC's code actually emits."""
    if complainant is None:
        complainant = {
            "identity_recorded": True,
            "given_name": "Test Alice",
            "family_name": "Sample-NSR01",
            "gender": None, "age": None, "phone": None,
        }
    return {
        "handover_id": handover_id,
        "exchange_version": version,
        "source": {
            "system": "STAAC_GRM",
            "tracking_number": tracking,
            "received_at": received_at,
        },
        "programme": {"code": "NSR", "institution": "MGLSD, NSR"},
        "grievance": {
            "category": category,
            "severity": "ADMINISTRATIVE",
            "narrative": (
                "TEST NSR 01 — Fictional test data. My household was omitted "
                "from the National Single Registry after an enumeration visit."
            ),
        },
        "location": {"parish_key": parish_key, "display_name": display_name},
        "complainant": complainant,
        # Sorted, as STAAC's admin view emits it.
        "shared_data": {
            "agreement_reference": "DSA-NSR-001",
            "agreement_version": "1.0",
            "manifest_version": "v1",
            "fields": [
                "complainant.age", "complainant.family_name",
                "complainant.gender", "complainant.given_name",
                "complainant.phone",
            ],
        },
        "attachments": [],
    }


def list_item(handover_id=H1, version=1, tracking="C-26-057528-8"):
    return {
        "handover_id": handover_id,
        "tracking_number": tracking,
        "programme_code": "NSR",
        "state": "available",
        "exchange_version": version,
        "available_at": "2026-10-10T10:15:00Z",
        "updated_at": "2026-10-10T10:15:00Z",
    }


def mock_collection(pages, details):
    """Register one response per page, then one per detail."""
    for body in pages:
        responses.add(responses.GET, LIST_URL, json=body, status=200)
    for handover_id, body in details.items():
        responses.add(
            responses.GET, f"{LIST_URL}{handover_id}/", json=body, status=200,
            headers={"ETag": f'W/"{handover_id[:8]}"',
                     "X-Correlation-ID": str(uuid.uuid4())},
        )


def _credential(cursor=""):
    """A stored credential, which is where the pull cursor lives."""
    from apps.grievance.models import StaacCredential
    from apps.security.encryption import encrypt

    return StaacCredential.objects.create(
        environment="sandbox", base_url=BASE,
        token_encrypted=encrypt(TOKEN.encode()), cursor=cursor,
    )


def client():
    return StaacClient(base_url=BASE, token=TOKEN)


# ── the transport ─────────────────────────────────────────────────────

class TestTheTransport:
    @responses.activate
    def test_the_token_travels_in_a_header_never_the_url(self):
        responses.add(responses.GET, LIST_URL,
                      json={"items": [], "next_cursor": None}, status=200)
        client().list_page()
        request = responses.calls[0].request
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in request.url
        # Spec §4.3 — these payloads must not reach a shared cache.
        assert request.headers["Cache-Control"] == "no-store"
        assert request.headers["X-Correlation-ID"]

    @responses.activate
    def test_it_pages_until_the_cursor_is_null(self):
        responses.add(responses.GET, LIST_URL, status=200, json={
            "items": [list_item(H1)], "next_cursor": "page-2"})
        responses.add(responses.GET, LIST_URL, status=200, json={
            "items": [list_item(H2, tracking="C-26-000000-1")],
            "next_cursor": None})
        pages = list(client().iter_refs())
        assert [c for _, c in pages] == ["page-2", ""]
        assert [r[0].handover_id for r, _ in pages] == [H1, H2]
        assert "cursor=page-2" in responses.calls[1].request.url

    @responses.activate
    def test_changed_since_is_not_sent_with_a_cursor(self):
        """The spec forbids the pair. Sending both would be refused,
        and a refusal here looks like a dead integration."""
        responses.add(responses.GET, LIST_URL, status=200,
                      json={"items": [], "next_cursor": None})
        client().list_page(cursor="c", changed_since="2026-10-01T00:00:00Z")
        url = responses.calls[0].request.url
        assert "cursor=c" in url
        assert "changed_since" not in url

    @responses.activate
    def test_a_repeated_cursor_stops_rather_than_loops(self):
        for _ in range(3):
            responses.add(responses.GET, LIST_URL, status=200, json={
                "items": [], "next_cursor": "same"})
        with pytest.raises(StaacError, match="already returned"):
            list(client().iter_refs())

    @responses.activate
    def test_a_rejected_cursor_is_its_own_error(self):
        """400 is recoverable by restarting; 401 is not. Collapsing
        them would turn a key rotation into a dead integration."""
        responses.add(responses.GET, LIST_URL, status=400, json={})
        with pytest.raises(CursorRejected):
            client().list_page(cursor="stale")

    @responses.activate
    def test_an_unapproved_address_reads_as_a_credential_problem(self):
        """STAAC answers 401 for both a bad token and an unapproved
        source IP, on purpose. The message has to name both so nobody
        spends the morning re-issuing a token that was fine."""
        responses.add(responses.GET, LIST_URL, status=401, json={})
        with pytest.raises(StaacError, match="address the IG has not approved"):
            client().list_page()

    @responses.activate
    def test_429_is_retried_with_backoff(self):
        responses.add(responses.GET, LIST_URL, status=429,
                      headers={"Retry-After": "1"}, json={})
        responses.add(responses.GET, LIST_URL, status=200,
                      json={"items": [], "next_cursor": None})
        refs, cursor = client().list_page()
        assert refs == [] and cursor == ""
        assert len(responses.calls) == 2

    @responses.activate
    def test_an_etag_makes_a_reread_conditional(self):
        responses.add(responses.GET, f"{LIST_URL}{H1}/", status=304, body="")
        snap = client().fetch(H1, etag='W/"abc"')
        assert snap.not_modified is True
        assert responses.calls[0].request.headers["If-None-Match"] == 'W/"abc"'


# ── the mapping ───────────────────────────────────────────────────────

class TestTheMapping:
    def test_a_filed_case_keeps_its_place_number_and_clock(self, parish):
        bind_category()
        result = file_snapshot(snapshot(), handover_id=H1, exchange_version=1)
        g = result.handover.grievance
        assert result.handover.outcome == HandoverOutcome.FILED
        assert g.category == Category.EXCLUSION_ERROR
        assert g.parish_code == "101.1.01.01"
        assert g.district_code == "101"
        assert g.region_code == "R-CENTRAL"
        assert g.external_reference == "C-26-057528-8"
        assert g.source_system == "STAAC_GRM"
        # +00:00, not Z — parsed, not pattern-matched.
        assert g.reported_at.isoformat().startswith("2026-10-11T00:02:49")
        assert g.reporter_name == "Test Alice Sample-NSR01"

    def test_the_snapshot_is_stored_verbatim(self, parish):
        bind_category()
        body = snapshot()
        row = file_snapshot(body, handover_id=H1, exchange_version=1).handover
        assert row.snapshot == body
        assert row.agreement_reference == "DSA-NSR-001"
        # The manifest is the audit record of what STAAC was allowed
        # to disclose for THIS handover, so it is stored as sent.
        assert set(row.fields_manifest) == {
            "complainant.age", "complainant.family_name",
            "complainant.gender", "complainant.given_name",
            "complainant.phone",
        }

    def test_a_null_demographic_stays_not_recorded(self, parish):
        """Spec §4.2.1: a field that appears as null must be retained
        as not recorded, never replaced with a guess."""
        bind_category()
        g = file_snapshot(snapshot(), handover_id=H1,
                          exchange_version=1).handover.grievance
        assert g.reporter_gender == ""
        assert g.reporter_age_years is None
        assert g.reporter_phone == ""

    def test_an_anonymous_complaint_names_nobody(self, parish):
        bind_category()
        body = snapshot(complainant={"identity_recorded": False})
        g = file_snapshot(body, handover_id=H1,
                          exchange_version=1).handover.grievance
        assert g.reporter_name == ""

    def test_a_recorded_gender_and_age_are_translated(self, parish):
        bind_category()
        bind_gender()
        body = snapshot(complainant={
            "identity_recorded": True, "given_name": "A", "family_name": "B",
            "gender": "female", "age": 64, "phone": None,
        })
        g = file_snapshot(body, handover_id=H1,
                          exchange_version=1).handover.grievance
        assert g.reporter_gender == "2"
        assert g.reporter_age_years == 64

    def test_an_unmapped_gender_does_not_cost_the_case(self, parish):
        """The asymmetry with category, through the pull: the case is
        filed, the gap is reported."""
        bind_category()
        body = snapshot(complainant={
            "identity_recorded": True, "given_name": "A", "family_name": "B",
            "gender": "female", "age": None, "phone": None,
        })
        result = file_snapshot(body, handover_id=H1, exchange_version=1)
        assert result.handover.outcome == HandoverOutcome.FILED
        assert result.handover.grievance.reporter_gender == ""
        assert any("no approved binding" in w for w in result.warnings)

    def test_an_unmapped_category_is_held_not_lost(self, parish):
        """Refusing at a console form tells an operator. Refusing in a
        pull tells nobody and STAAC will not send it again."""
        result = file_snapshot(snapshot(), handover_id=H1, exchange_version=1)
        assert result.handover.outcome == HandoverOutcome.HELD
        assert "no approved binding" in result.handover.outcome_detail
        assert result.handover.grievance is None
        assert not Grievance.objects.exists()
        # The evidence is kept, so nothing has to be re-read later.
        assert result.handover.snapshot == snapshot()

    def test_a_held_case_files_once_the_binding_lands(self, parish):
        file_snapshot(snapshot(), handover_id=H1, exchange_version=1)
        bind_category()
        results = file_held()
        assert len(results) == 1 and results[0].created
        g = Grievance.objects.get()
        assert g.category == Category.EXCLUSION_ERROR
        # The complainant's clock still runs from when they reported,
        # not from when the binding was approved.
        assert g.reported_at.isoformat().startswith("2026-10-11T00:02:49")

    def test_a_place_we_cannot_resolve_is_held_not_filed_blank(self, parish):
        """Blank geography is not neutral — `apps.security.abac`
        filters on those columns, so a case with none belongs to no
        officer's scope and shows for every officer nationally."""
        bind_category()
        body = snapshot(parish_key="999.9.99.99")
        result = file_snapshot(body, handover_id=H1, exchange_version=1)
        assert result.handover.outcome == HandoverOutcome.HELD
        assert "names no GeographicUnit" in result.handover.outcome_detail
        assert not Grievance.objects.exists()

    def test_a_shallower_key_still_places_the_case(self, parish):
        """`parish_key` is the deepest key the case was coded to, so a
        sub-county is a legitimate value and must not be assumed to
        have four parts."""
        bind_category()
        body = snapshot(parish_key="101.1.01")
        g = file_snapshot(body, handover_id=H1,
                          exchange_version=1).handover.grievance
        assert g.sub_county_code == "101.1.01"
        assert g.district_code == "101"
        # Nothing below the unit named is invented.
        assert g.parish_code == ""

    def test_the_partners_display_name_is_never_trusted_as_a_name(self, parish):
        bind_category()
        body = snapshot(display_name="Somewhere Else")
        result = file_snapshot(body, handover_id=H1, exchange_version=1)
        assert any("this registry resolves it" in w for w in result.warnings)
        # And the registry's own resolution is what was stored.
        assert result.handover.grievance.parish_code == "101.1.01.01"

    def test_the_same_delivery_twice_is_one_case(self, parish):
        bind_category()
        first = file_snapshot(snapshot(), handover_id=H1, exchange_version=1)
        again = file_snapshot(snapshot(), handover_id=H1, exchange_version=1)
        assert again.created is False
        assert again.handover.pk == first.handover.pk
        assert Grievance.objects.count() == 1
        assert StaacHandover.objects.count() == 1

    def test_a_second_version_is_a_second_snapshot_of_one_case(self, parish):
        """`exchange_version` increments when STAAC withdraws and
        re-offers the same case. That is a new snapshot, not a new
        complaint, so the registry keeps both and files one."""
        bind_category()
        file_snapshot(snapshot(version=1), handover_id=H1, exchange_version=1)
        file_snapshot(snapshot(version=2), handover_id=H1, exchange_version=2)
        assert StaacHandover.objects.count() == 2
        assert Grievance.objects.count() == 1

    def test_the_retrieval_of_personal_data_is_audited(self, parish):
        bind_category()
        row = file_snapshot(snapshot(), handover_id=H1,
                            exchange_version=1, etag='W/"x"',
                            correlation_id="corr-1").handover
        read = AuditEvent.objects.filter(
            entity_type="staac.handover", action="read",
        ).first()
        assert read is not None
        assert read.field_changes["handover_id"] == H1
        assert read.field_changes["correlation_id"] == "corr-1"
        assert set(read.field_changes["fields_manifest"]) == set(
            row.fields_manifest)
        # What was disclosed, never the disclosed values.
        assert "Sample-NSR01" not in str(read.field_changes)


# ── the run ───────────────────────────────────────────────────────────

class TestTheRun:
    @responses.activate
    def test_it_files_every_available_handover(self, parish):
        bind_category()
        mock_collection(
            pages=[
                {"items": [list_item(H1)], "next_cursor": "p2"},
                {"items": [list_item(H2, tracking="C-26-000000-1")],
                 "next_cursor": None},
            ],
            details={
                H1: snapshot(),
                H2: snapshot(handover_id=H2, tracking="C-26-000000-1"),
            },
        )
        report = pull(client=client())
        assert (report.listed, report.fetched, report.filed) == (2, 2, 2)
        assert report.pages == 2
        assert Grievance.objects.count() == 2
        assert set(Grievance.objects.values_list("external_reference", flat=True)) == {
            "C-26-057528-8", "C-26-000000-1"}

    @responses.activate
    def test_a_rerun_refetches_nothing(self, parish):
        """Reconciliation re-lists what we hold. Re-fetching would
        re-read a complainant's identity for no reason."""
        bind_category()
        mock_collection(
            pages=[{"items": [list_item(H1)], "next_cursor": None}] * 2,
            details={H1: snapshot()},
        )
        pull(client=client())
        second = pull(client=client())
        assert second.fetched == 0
        assert second.already_held == 1
        assert Grievance.objects.count() == 1

    @responses.activate
    def test_an_unclassifiable_case_does_not_stop_the_run(self, parish):
        bind_category()
        mock_collection(
            pages=[{"items": [list_item(H1), list_item(H2, tracking="C-2")],
                    "next_cursor": None}],
            details={
                H1: snapshot(),
                H2: snapshot(handover_id=H2, tracking="C-2",
                             category="Environmental and social"),
            },
        )
        report = pull(client=client())
        assert report.filed == 1
        assert report.held == 1
        assert StaacHandover.objects.count() == 2

    @responses.activate
    def test_the_cursor_moves_only_behind_a_stored_page(self, parish):
        """The ordering that makes a pull resumable, in both
        directions.

        Page 1 stores cleanly, so its cursor is persisted. Page 2 has
        a record that cannot be fetched, so the cursor must STAY at
        page 1's value — advancing past a record STAAC will never
        offer again loses the complaint permanently, because from
        STAAC's side it was delivered.
        """
        credential = _credential()
        bind_category()
        responses.add(responses.GET, LIST_URL, status=200, json={
            "items": [list_item(H1)], "next_cursor": "p2"})
        responses.add(responses.GET, f"{LIST_URL}{H1}/", status=200,
                      json=snapshot())
        responses.add(responses.GET, LIST_URL, status=200, json={
            "items": [list_item(H2, tracking="C-2")], "next_cursor": "p3"})
        for _ in range(3):  # exhausts the retry budget
            responses.add(responses.GET, f"{LIST_URL}{H2}/", status=500,
                          json={})

        report = pull(client=client())
        credential.refresh_from_db()
        assert report.filed == 1
        assert report.errors, "the unreadable record should be reported"
        assert credential.cursor == "p2", (
            "the cursor must sit at the last page that stored completely, "
            "not at the page whose record was lost"
        )

    @responses.activate
    def test_a_resumed_run_sends_the_stored_cursor(self, parish):
        credential = _credential(cursor="p7")
        bind_category()
        responses.add(responses.GET, LIST_URL, status=200, json={
            "items": [], "next_cursor": None})
        pull(client=client())
        assert "cursor=p7" in responses.calls[0].request.url
        credential.refresh_from_db()
        assert credential.cursor == ""

    @responses.activate
    def test_restart_ignores_the_stored_cursor(self, parish):
        _credential(cursor="p7")
        bind_category()
        responses.add(responses.GET, LIST_URL, status=200, json={
            "items": [], "next_cursor": None})
        pull(client=client(), restart=True)
        assert "cursor" not in responses.calls[0].request.url

    @responses.activate
    def test_a_stale_cursor_restarts_instead_of_failing(self, parish):
        """STAAC signs cursors with no expiry, so the thing that
        invalidates one is a key change. Treating that as fatal would
        leave the integration dead until someone noticed."""
        bind_category()
        responses.add(responses.GET, LIST_URL, status=400, json={})
        responses.add(responses.GET, LIST_URL, status=200, json={
            "items": [list_item(H1)], "next_cursor": None})
        responses.add(responses.GET, f"{LIST_URL}{H1}/", status=200,
                      json=snapshot())
        report = pull(client=client(), restart=False)
        assert report.restarted_from_beginning is True
        assert report.filed == 1

    @responses.activate
    def test_the_run_itself_is_audited_at_both_ends(self, parish):
        bind_category()
        mock_collection(
            pages=[{"items": [], "next_cursor": None}], details={})
        pull(client=client())
        events = AuditEvent.objects.filter(entity_type="staac.pull")
        assert events.count() == 2
        assert any("started" in e.reason for e in events)
        assert any("finished" in e.reason for e in events)
