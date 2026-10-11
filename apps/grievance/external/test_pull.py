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
    HeldReason,
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


# Autouse isolation (resolver cache, retry sleep) is in conftest.py.

AGREEMENT = "DSA-NSR-001"


@pytest.fixture
def staac_agreement(db):
    """The registry's own record of what it may receive.

    `start_connector_run` refuses without one (AC-DIH-DPA-REQUIRED),
    and `_agreement_covers` refuses a snapshot citing a reference we
    do not hold. Both are the point: the chain must record OUR
    authorisation, not the partner's assertion of it.
    """
    from apps.ingestion_hub.models import DataProvisionAgreement, SourceSystem

    from apps.grievance.external import SOURCE_CODE

    return DataProvisionAgreement.objects.create(
        source_system=SourceSystem.objects.get(code=SOURCE_CODE),
        reference=AGREEMENT,
        purpose="Receive approved NSR grievances from STAAC's GRM.",
        valid_from=date(2026, 1, 1),
    )


@pytest.fixture
def run(staac_agreement):
    from apps.ingestion_hub.services import start_connector_run

    from apps.grievance.external.pull import connector_for_staac

    return start_connector_run(connector_for_staac(), actor="t")


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


def _credential(cursor="", environment="sandbox"):
    """A stored credential, which is where the pull cursor lives.

    The token is written as PLAINTEXT, which is `EncryptedBinaryField`'s
    documented contract: it encrypts on write and decrypts on read.
    This fixture used to call `encrypt()` first, which compensated for
    a `_token()` that called `decrypt()` on an already-decrypted value
    — two wrongs that cancelled, and which no test caught because
    every test injected its client and never went near the seam.
    """
    from apps.grievance.models import StaacCredential

    return StaacCredential.objects.create(
        environment=environment, base_url=BASE,
        token_encrypted=TOKEN.encode(), cursor=cursor,
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
    def test_a_filed_case_keeps_its_place_number_and_clock(self, parish, run):
        bind_category()
        result = file_snapshot(snapshot(), run=run, handover_id=H1, exchange_version=1)
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

    def test_the_snapshot_is_stored_verbatim(self, parish, run):
        bind_category()
        body = snapshot()
        row = file_snapshot(body, run=run, handover_id=H1, exchange_version=1).handover
        assert row.snapshot == body
        assert row.agreement_reference == "DSA-NSR-001"
        # The manifest is the audit record of what STAAC was allowed
        # to disclose for THIS handover, so it is stored as sent.
        assert set(row.fields_manifest) == {
            "complainant.age", "complainant.family_name",
            "complainant.gender", "complainant.given_name",
            "complainant.phone",
        }

    def test_a_null_demographic_stays_not_recorded(self, parish, run):
        """Spec §4.2.1: a field that appears as null must be retained
        as not recorded, never replaced with a guess."""
        bind_category()
        g = file_snapshot(snapshot(), run=run, handover_id=H1,
                          exchange_version=1).handover.grievance
        assert g.reporter_gender == ""
        assert g.reporter_age_years is None
        assert g.reporter_phone == ""

    def test_an_anonymous_complaint_names_nobody(self, parish, run):
        bind_category()
        body = snapshot(complainant={"identity_recorded": False})
        g = file_snapshot(body, run=run, handover_id=H1,
                          exchange_version=1).handover.grievance
        assert g.reporter_name == ""

    def test_a_recorded_gender_and_age_are_translated(self, parish, run):
        bind_category()
        bind_gender()
        body = snapshot(complainant={
            "identity_recorded": True, "given_name": "A", "family_name": "B",
            "gender": "female", "age": 64, "phone": None,
        })
        g = file_snapshot(body, run=run, handover_id=H1,
                          exchange_version=1).handover.grievance
        assert g.reporter_gender == "2"
        assert g.reporter_age_years == 64

    def test_an_unmapped_gender_does_not_cost_the_case(self, parish, run):
        """The asymmetry with category, through the pull: the case is
        filed, the gap is reported."""
        bind_category()
        body = snapshot(complainant={
            "identity_recorded": True, "given_name": "A", "family_name": "B",
            "gender": "female", "age": None, "phone": None,
        })
        result = file_snapshot(body, run=run, handover_id=H1, exchange_version=1)
        assert result.handover.outcome == HandoverOutcome.FILED
        assert result.handover.grievance.reporter_gender == ""
        assert any("no approved binding" in w for w in result.warnings)

    def test_an_unmapped_category_is_held_not_lost(self, parish, run):
        """Refusing at a console form tells an operator. Refusing in a
        pull tells nobody and STAAC will not send it again."""
        result = file_snapshot(snapshot(), run=run, handover_id=H1, exchange_version=1)
        assert result.handover.outcome == HandoverOutcome.HELD
        assert "no approved binding" in result.handover.outcome_detail
        assert result.handover.grievance is None
        assert not Grievance.objects.exists()
        # The evidence is kept, so nothing has to be re-read later.
        assert result.handover.snapshot == snapshot()

    def test_a_held_case_files_once_the_binding_lands(self, parish, run):
        file_snapshot(snapshot(), run=run, handover_id=H1, exchange_version=1)
        bind_category()
        results = file_held()
        assert len(results) == 1 and results[0].created
        g = Grievance.objects.get()
        assert g.category == Category.EXCLUSION_ERROR
        # The complainant's clock still runs from when they reported,
        # not from when the binding was approved.
        assert g.reported_at.isoformat().startswith("2026-10-11T00:02:49")

    def test_a_place_we_cannot_resolve_is_held_not_filed_blank(self, parish, run):
        """Blank geography is not neutral — `apps.security.abac`
        filters on those columns, so a case with none belongs to no
        officer's scope and shows for every officer nationally."""
        bind_category()
        body = snapshot(parish_key="999.9.99.99")
        result = file_snapshot(body, run=run, handover_id=H1, exchange_version=1)
        assert result.handover.outcome == HandoverOutcome.HELD
        assert "names no GeographicUnit" in result.handover.outcome_detail
        assert not Grievance.objects.exists()

    def test_a_shallower_key_still_places_the_case(self, parish, run):
        """`parish_key` is the deepest key the case was coded to, so a
        sub-county is a legitimate value and must not be assumed to
        have four parts."""
        bind_category()
        body = snapshot(parish_key="101.1.01")
        g = file_snapshot(body, run=run, handover_id=H1,
                          exchange_version=1).handover.grievance
        assert g.sub_county_code == "101.1.01"
        assert g.district_code == "101"
        # Nothing below the unit named is invented.
        assert g.parish_code == ""

    def test_the_partners_display_name_is_never_trusted_as_a_name(self, parish, run):
        bind_category()
        body = snapshot(display_name="Somewhere Else")
        result = file_snapshot(body, run=run, handover_id=H1, exchange_version=1)
        assert any("this registry resolves it" in w for w in result.warnings)
        # And the registry's own resolution is what was stored.
        assert result.handover.grievance.parish_code == "101.1.01.01"

    def test_the_same_delivery_twice_is_one_case(self, parish, run):
        bind_category()
        first = file_snapshot(snapshot(), run=run, handover_id=H1, exchange_version=1)
        again = file_snapshot(snapshot(), run=run, handover_id=H1, exchange_version=1)
        assert again.created is False
        assert again.handover.pk == first.handover.pk
        assert Grievance.objects.count() == 1
        assert StaacHandover.objects.count() == 1

    def test_a_second_version_is_a_second_snapshot_of_one_case(self, parish, run):
        """`exchange_version` increments when STAAC withdraws and
        re-offers the same case. That is a new snapshot, not a new
        complaint, so the registry keeps both and files one."""
        bind_category()
        file_snapshot(snapshot(version=1), run=run, handover_id=H1, exchange_version=1)
        file_snapshot(snapshot(version=2), run=run, handover_id=H1, exchange_version=2)
        assert StaacHandover.objects.count() == 2
        assert Grievance.objects.count() == 1

    def test_the_retrieval_of_personal_data_is_audited(self, parish, run):
        bind_category()
        row = file_snapshot(snapshot(), run=run, handover_id=H1,
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
    def test_it_files_every_available_handover(self, parish, staac_agreement):
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
    def test_a_rerun_refetches_nothing(self, parish, staac_agreement):
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
    def test_an_unclassifiable_case_does_not_stop_the_run(self, parish, staac_agreement):
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
    def test_the_cursor_moves_only_behind_a_stored_page(self, parish, staac_agreement):
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
    def test_a_resumed_run_sends_the_stored_cursor(self, parish, staac_agreement):
        credential = _credential(cursor="p7")
        bind_category()
        responses.add(responses.GET, LIST_URL, status=200, json={
            "items": [], "next_cursor": None})
        pull(client=client())
        assert "cursor=p7" in responses.calls[0].request.url
        credential.refresh_from_db()
        assert credential.cursor == ""

    @responses.activate
    def test_restart_ignores_the_stored_cursor(self, parish, staac_agreement):
        _credential(cursor="p7")
        bind_category()
        responses.add(responses.GET, LIST_URL, status=200, json={
            "items": [], "next_cursor": None})
        pull(client=client(), restart=True)
        assert "cursor" not in responses.calls[0].request.url

    @responses.activate
    def test_a_stale_cursor_restarts_instead_of_failing(self, parish, staac_agreement):
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
    def test_the_run_itself_is_audited_at_both_ends(self, parish, staac_agreement):
        bind_category()
        mock_collection(
            pages=[{"items": [], "next_cursor": None}], details={})
        pull(client=client())
        events = AuditEvent.objects.filter(entity_type="staac.pull")
        assert events.count() == 2
        assert any("started" in e.reason for e in events)
        assert any("finished" in e.reason for e in events)


class TestTheStoredCredential:
    """The seam every other test skipped by injecting a client."""

    @responses.activate
    def test_the_stored_token_authenticates_the_call(self, parish, run):
        """Builds the client from the credential, the way production
        does. Nothing exercised this path before, which is how a
        double-encrypt and a double-decrypt lived together unnoticed."""
        _credential()
        bind_category()
        responses.add(responses.GET, LIST_URL, status=200,
                      json={"items": [list_item(H1)], "next_cursor": None})
        responses.add(responses.GET, f"{LIST_URL}{H1}/", status=200,
                      json=snapshot())

        report = pull(environment="sandbox")
        assert report.filed == 1
        sent = responses.calls[0].request.headers["Authorization"]
        assert sent == f"Bearer {TOKEN}", (
            "the token must reach STAAC as it was entered — a second "
            "encrypt or decrypt anywhere on this path corrupts it"
        )

    def test_a_contract_following_writer_produces_a_usable_credential(self):
        """A fixture, a data migration or a shell create writes the
        plaintext. Any of them must yield a working credential, not an
        InvalidToken escaping the command's handler as a traceback."""
        from apps.grievance.external.pull import _token

        credential = _credential()
        credential.refresh_from_db()
        assert _token(credential) == TOKEN

    def test_two_active_credentials_refuse_to_guess(self, parish, run):
        """"production" sorts before "sandbox", so choosing
        alphabetically meant an operator testing without the flag
        reached production."""
        _credential(environment="production")
        _credential(environment="sandbox")
        with pytest.raises(StaacError, match="Name the one to use"):
            pull()

    def test_naming_the_environment_resolves_it(self, parish, run):
        _credential(environment="production")
        _credential(environment="sandbox")
        from apps.grievance.external.pull import credential_for

        assert credential_for("sandbox").environment == "sandbox"

    @responses.activate
    def test_a_run_with_errors_does_not_claim_a_fresh_pull(self, parish, run):
        credential = _credential()
        bind_category()
        responses.add(responses.GET, LIST_URL, status=200,
                      json={"items": [list_item(H1)], "next_cursor": None})
        for _ in range(3):
            responses.add(responses.GET, f"{LIST_URL}{H1}/", status=500,
                          json={})
        report = pull(client=client())
        credential.refresh_from_db()
        assert report.errors
        assert credential.last_pulled_at is None, (
            "a fresh timestamp for a run that imported nothing is the "
            "reassuring kind of wrong"
        )


class TestWhatThePartnerSends:
    @responses.activate
    def test_a_missing_exchange_version_is_refused_not_assumed(self):
        """It is half the idempotency key. Assuming 1 would collide two
        different snapshots of one case, and the second would be read
        as already held and never fetched."""
        responses.add(responses.GET, LIST_URL, status=200, json={
            "items": [{"handover_id": H1, "tracking_number": "C-1",
                       "state": "available"}],
            "next_cursor": None})
        with pytest.raises(StaacError, match="cannot be half of an idempotency key"):
            client().list_page()

    def test_attachments_that_arrive_are_reported_not_ignored(self, parish, run):
        """v1 says the array is always empty and forbids downloading.
        "Always empty" is the partner's statement about their current
        version, not a fact."""
        bind_category()
        body = snapshot()
        body["attachments"] = [{"id": "a1", "filename": "list.jpg"}]
        result = file_snapshot(body, run=run, handover_id=H1, exchange_version=1)
        assert result.handover.outcome == HandoverOutcome.FILED
        assert any("attachment" in w for w in result.warnings)

    def test_no_attachments_says_nothing(self, parish, run):
        bind_category()
        result = file_snapshot(snapshot(), run=run, handover_id=H1, exchange_version=1)
        assert not any("attachment" in w for w in result.warnings)


class TestTheCredentialForm:
    """The admin form is how a token actually gets in, so it is the
    one writer that must agree with the field's contract. It did not,
    and nothing tested it — which is how the double-encrypt shipped."""

    @staticmethod
    def _save(token=TOKEN, instance=None, **extra):
        from apps.grievance.admin import StaacCredentialForm

        data = {"environment": "sandbox", "base_url": BASE,
                "is_active": True, "token": token, **extra}
        form = StaacCredentialForm(data, instance=instance)
        assert form.is_valid(), form.errors
        return form.save()

    def test_a_token_entered_in_the_admin_comes_back_as_entered(self):
        from apps.grievance.external.pull import _token

        saved = self._save()
        saved.refresh_from_db()
        assert _token(saved) == TOKEN

    def test_the_column_holds_ciphertext_not_the_token(self):
        """The round trip passing is not enough: it would also pass if
        the column held plaintext. This is the half that says the
        field is doing its job."""
        from django.db import connection

        saved = self._save()
        with connection.cursor() as cur:
            cur.execute(
                "SELECT token_encrypted FROM grievance_staaccredential "
                "WHERE id = %s", [saved.id],
            )
            at_rest = bytes(cur.fetchone()[0])
        assert TOKEN.encode() not in at_rest
        assert at_rest.startswith(b"gAAAA")  # Fernet

    def test_an_edit_that_leaves_the_token_blank_keeps_it(self):
        from apps.grievance.external.pull import _token

        saved = self._save()
        again = self._save(token="", instance=saved)
        again.refresh_from_db()
        assert _token(again) == TOKEN

    def test_a_new_token_drops_the_cursor(self):
        """STAAC signs cursors per credential, so resuming with the
        old one after a rotation is a silent resume from nowhere."""
        saved = self._save()
        saved.cursor = "p9"
        saved.save(update_fields=["cursor"])
        again = self._save(token="replacement-token", instance=saved)  # noqa: S106
        assert again.cursor == ""

    def test_adding_one_without_a_token_is_refused(self):
        from apps.grievance.admin import StaacCredentialForm

        form = StaacCredentialForm(
            {"environment": "sandbox", "base_url": BASE, "is_active": True,
             "token": ""},
        )
        assert not form.is_valid()
        assert "token is required" in str(form.errors)


class TestTheAgreement:
    """The registry's own record of what it may receive, not the
    partner's assertion of it."""

    def test_a_snapshot_citing_an_agreement_we_do_not_hold_is_held(
        self, parish, run,
    ):
        bind_category()
        body = snapshot()
        body["shared_data"]["agreement_reference"] = "DSA-INVENTED-9"
        result = file_snapshot(body, run=run, handover_id=H1, exchange_version=1)
        assert result.handover.outcome == HandoverOutcome.HELD
        assert result.handover.held_reason == HeldReason.UNVERIFIED_AGREEMENT
        assert not Grievance.objects.exists()

    def test_a_snapshot_naming_no_agreement_is_held(self, parish, run):
        bind_category()
        body = snapshot()
        body["shared_data"]["agreement_reference"] = ""
        result = file_snapshot(body, run=run, handover_id=H1, exchange_version=1)
        assert result.handover.held_reason == HeldReason.UNVERIFIED_AGREEMENT

    def test_an_expired_agreement_does_not_cover_it(self, parish, run,
                                                    staac_agreement):
        bind_category()
        staac_agreement.valid_to = date(2026, 1, 2)
        staac_agreement.save(update_fields=["valid_to"])
        result = file_snapshot(snapshot(), run=run, handover_id=H1,
                               exchange_version=1)
        assert result.handover.held_reason == HeldReason.UNVERIFIED_AGREEMENT

    def test_no_agreement_means_no_run_at_all(self, parish):
        """Not "fetch then refuse" — a partner's personal data is not
        received in the first place."""
        from apps.grievance.external.pull import connector_for_staac
        from apps.ingestion_hub.services import DihError, start_connector_run

        with pytest.raises(DihError):
            start_connector_run(connector_for_staac(), actor="t")

    @responses.activate
    def test_the_pull_says_so_in_words(self, parish):
        with pytest.raises(StaacError, match="recorded here before the first call"):
            pull(client=client())
        assert not responses.calls, "nothing should have been fetched"


class TestWhyItIsHeld:
    """The held reason is a value, so the remediation queue can be
    counted rather than read."""

    def test_an_unbound_category_names_the_code_to_bind(self, parish, run):
        result = file_snapshot(snapshot(), run=run, handover_id=H1,
                               exchange_version=1)
        row = result.handover
        assert row.held_reason == HeldReason.UNBOUND_CATEGORY
        assert row.held_choice_list == STAAC_CATEGORY_LIST
        assert row.held_source_code == "C07"

    def test_a_category_nobody_registered_is_a_different_kind(self, parish, run):
        """Different problems, different owners — the distinction
        UnmappedCategory draws and the first version threw away."""
        body = snapshot(category="Something STAAC invented last week")
        result = file_snapshot(body, run=run, handover_id=H1, exchange_version=1)
        assert result.handover.held_reason == HeldReason.UNKNOWN_CATEGORY

    def test_an_unresolvable_place_is_its_own_kind(self, parish, run):
        bind_category()
        body = snapshot(parish_key="999.9.99.99")
        result = file_snapshot(body, run=run, handover_id=H1, exchange_version=1)
        assert result.handover.held_reason == HeldReason.UNRESOLVED_PLACE
        assert result.handover.held_source_code == "999.9.99.99"

    def test_filing_clears_the_held_fields(self, parish, run):
        file_snapshot(snapshot(), run=run, handover_id=H1, exchange_version=1)
        bind_category()
        file_held()
        row = StaacHandover.objects.get()
        assert row.outcome == HandoverOutcome.FILED
        assert row.held_reason == ""
        assert row.held_source_code == ""

    def test_the_queue_is_countable(self, parish, run):
        """The question an operator actually asks: which codes are
        blocking cases, and how many each."""
        file_snapshot(snapshot(), run=run, handover_id=H1, exchange_version=1)
        file_snapshot(snapshot(handover_id=H2, tracking="C-2"), run=run,
                      handover_id=H2, exchange_version=1)
        from django.db.models import Count

        counted = dict(
            StaacHandover.objects
            .filter(held_reason=HeldReason.UNBOUND_CATEGORY)
            .values_list("held_source_code")
            .annotate(n=Count("id")),
        )
        assert counted == {"C07": 2}


class TestTheRunRecord:
    """One run-accounting structure, not two."""

    @responses.activate
    def test_the_run_is_recorded_with_its_counters(self, parish, staac_agreement):
        from apps.ingestion_hub.models import ConnectorRun, ConnectorRunStatus

        bind_category()
        mock_collection(
            pages=[{"items": [list_item(H1), list_item(H2, tracking="C-2")],
                    "next_cursor": None}],
            details={H1: snapshot(),
                     H2: snapshot(handover_id=H2, tracking="C-2",
                                  category="Environmental and social")},
        )
        report = pull(client=client())
        run = ConnectorRun.objects.get(pk=report.run_id)
        assert run.status == ConnectorRunStatus.SUCCEEDED
        assert run.finished_at is not None
        assert run.records_received == 2   # landed through land_payload
        assert run.records_promoted == 1   # filed
        assert run.records_quarantined == 1  # held
        assert run.note

    @responses.activate
    def test_a_failed_run_is_recorded_as_failed(self, parish, staac_agreement):
        from apps.ingestion_hub.models import ConnectorRun, ConnectorRunStatus

        bind_category()
        responses.add(responses.GET, LIST_URL, status=200,
                      json={"items": [list_item(H1)], "next_cursor": None})
        for _ in range(3):
            responses.add(responses.GET, f"{LIST_URL}{H1}/", status=500, json={})
        report = pull(client=client())
        run = ConnectorRun.objects.get(pk=report.run_id)
        assert run.status == ConnectorRunStatus.FAILED
        assert run.records_rejected == 1

    def test_the_payload_lands_in_the_one_landing_table(self, parish, run):
        from apps.ingestion_hub.models import RawLanding

        bind_category()
        body = snapshot()
        row = file_snapshot(body, run=run, handover_id=H1,
                            exchange_version=1).handover
        landing = RawLanding.objects.get()
        assert landing.payload == body
        assert landing.source_reference == H1
        assert row.raw_landing_id == landing.id
        # And the handover reads it back, so nothing holds two copies.
        assert row.snapshot == body

    def test_a_resend_does_not_land_a_second_copy(self, parish, run):
        from apps.ingestion_hub.models import RawLanding

        bind_category()
        file_snapshot(snapshot(), run=run, handover_id=H1, exchange_version=1)
        file_snapshot(snapshot(), run=run, handover_id=H1, exchange_version=1)
        assert RawLanding.objects.count() == 1
