"""Connection-test service + admin form tests (US-S11-003b).

`responses` mocks the outbound Kobo HTTP layer; the Django ORM stays
real so we exercise the ConnectorRun row + AuditEvent emission +
KoboCredential persistence end-to-end.
"""

from __future__ import annotations

import pytest
import responses
from django import forms

from apps.security.models import AuditEvent

from .admin_credentials import KoboCredentialForm
from .connection_test import (
    CredentialMissingError,
    UnsupportedConnectorError,
    run_test_connection,
)
from .models import (
    ConnectorRun,
    ConnectorRunStatus,
    ConnectorRunType,
    KoboCredential,
    SourceSystem,
    SourceSystemKind,
)

KOBO_URL = "https://kobo.test.invalid"


# --------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------

@pytest.fixture
def kobo_source(db):
    return SourceSystem.objects.create(
        code="KOBO-PILOT", name="Kobo pilot", kind=SourceSystemKind.KOBO,
    )


@pytest.fixture
def kobo_source_with_creds(kobo_source):
    KoboCredential.objects.create(
        source_system=kobo_source,
        server_url=KOBO_URL,
        token_encrypted=b"stored-token",
        acquired_by_username="placeholder",
    )
    return kobo_source


@pytest.fixture
def ubos_source(db):
    return SourceSystem.objects.create(
        code="UBOS-BULK", name="UBOS bulk", kind=SourceSystemKind.UBOS,
    )


# --------------------------------------------------------------------
# run_test_connection
# --------------------------------------------------------------------

class TestRunTestConnection:
    @responses.activate
    def test_success_records_passing_run_and_audit(
        self, kobo_source_with_creds,
    ):
        responses.add(
            responses.GET, f"{KOBO_URL}/api/v2/assets.json?limit=1",
            json={"results": []}, status=200,
            headers={"X-OpenRosa-Version": "1.0"},
        )
        run, result = run_test_connection(
            kobo_source_with_creds, actor="admin-user",
        )
        assert result.ok is True
        assert run.run_type == ConnectorRunType.TEST
        assert run.status == ConnectorRunStatus.SUCCEEDED
        assert run.finished_at is not None
        assert "ok latency=" in run.note

        # Bookkeeping on KoboCredential.
        cred = kobo_source_with_creds.kobo_credential
        cred.refresh_from_db()
        assert cred.last_test_ok is True
        assert cred.last_test_at is not None

        # Two AuditEvents: create-run + test_connection on source.
        actions = set(AuditEvent.objects.values_list("action", flat=True))
        assert "create" in actions
        assert "test_connection" in actions

    @responses.activate
    def test_auth_failure_records_failed_run(self, kobo_source_with_creds):
        responses.add(
            responses.GET, f"{KOBO_URL}/api/v2/assets.json?limit=1",
            json={"detail": "bad token"}, status=401,
        )
        run, result = run_test_connection(
            kobo_source_with_creds, actor="admin-user",
        )
        assert result.ok is False
        assert run.status == ConnectorRunStatus.FAILED
        assert "auth_failed" in run.note

        cred = kobo_source_with_creds.kobo_credential
        cred.refresh_from_db()
        assert cred.last_test_ok is False

    def test_missing_credential_raises(self, kobo_source):
        with pytest.raises(CredentialMissingError):
            run_test_connection(kobo_source, actor="admin-user")

    def test_unsupported_kind_raises(self, ubos_source):
        with pytest.raises(UnsupportedConnectorError):
            run_test_connection(ubos_source, actor="admin-user")

    @responses.activate
    def test_creates_placeholder_connector_row_when_none_exists(
        self, kobo_source_with_creds,
    ):
        """The Admin button can fire before an import Connector row
        exists; we lazily materialise one so the FK isn't null."""
        responses.add(
            responses.GET, f"{KOBO_URL}/api/v2/assets.json?limit=1",
            json={"results": []}, status=200,
        )
        run, _ = run_test_connection(
            kobo_source_with_creds, actor="admin-user",
        )
        assert kobo_source_with_creds.connectors.count() == 1
        assert run.connector.source_system_id == kobo_source_with_creds.id

    @responses.activate
    def test_promotion_latency_aggregator_should_ignore_test_runs(
        self, kobo_source_with_creds,
    ):
        """Sanity check on the index — ConnectorRun.run_type lets RPT
        S6-005 filter test probes out of latency stats."""
        responses.add(
            responses.GET, f"{KOBO_URL}/api/v2/assets.json?limit=1",
            json={"results": []}, status=200,
        )
        run, _ = run_test_connection(
            kobo_source_with_creds, actor="admin-user",
        )
        # Direct query mirrors what the aggregator would do.
        imports = ConnectorRun.objects.filter(
            run_type=ConnectorRunType.IMPORT,
        ).count()
        tests = ConnectorRun.objects.filter(
            run_type=ConnectorRunType.TEST,
        ).count()
        assert imports == 0 and tests == 1


# --------------------------------------------------------------------
# KoboCredentialForm
# --------------------------------------------------------------------

class TestKoboCredentialForm:
    @responses.activate
    def test_first_save_mints_token_via_acquire_token(self, kobo_source):
        responses.add(
            responses.POST, f"{KOBO_URL}/token/?format=json",
            json={"token": "newly-minted"}, status=200,
        )
        form = KoboCredentialForm(
            data={
                "server_url": KOBO_URL,
                "username": "operator-name",
                "password": "operator-secret",
            },
            instance=KoboCredential(source_system=kobo_source),
        )
        assert form.is_valid(), form.errors
        cred = form.save()
        assert cred.acquired_by_username == "operator-name"
        # Token round-trips through encryption.
        cred.refresh_from_db()
        assert bytes(cred.token_encrypted) == b"newly-minted"

    def test_first_save_requires_username_and_password(self, kobo_source):
        form = KoboCredentialForm(
            data={"server_url": KOBO_URL},
            instance=KoboCredential(source_system=kobo_source),
        )
        assert not form.is_valid()
        assert "__all__" in form.errors
        # New error wording covers BOTH the password-exchange and the
        # pre-minted token path (US-S11-009).
        msg = str(form.errors["__all__"])
        assert "username + password" in msg
        assert "pre-minted" in msg

    @responses.activate
    def test_edit_with_blank_password_keeps_existing_token(
        self, kobo_source_with_creds,
    ):
        existing = kobo_source_with_creds.kobo_credential
        original_token = bytes(existing.token_encrypted)
        form = KoboCredentialForm(
            data={"server_url": KOBO_URL, "username": "", "password": ""},
            instance=existing,
        )
        assert form.is_valid(), form.errors
        cred = form.save()
        cred.refresh_from_db()
        assert bytes(cred.token_encrypted) == original_token

    @responses.activate
    def test_save_surfaces_acquire_token_failure_as_form_error(
        self, kobo_source,
    ):
        responses.add(
            responses.POST, f"{KOBO_URL}/token/?format=json",
            json={"detail": "no"}, status=401,
        )
        form = KoboCredentialForm(
            data={
                "server_url": KOBO_URL, "username": "u", "password": "wrong",
            },
            instance=KoboCredential(source_system=kobo_source),
        )
        assert form.is_valid()
        with pytest.raises(forms.ValidationError):
            form.save()

    # --- Pre-minted token path (MFA-friendly fallback) -----------------

    def test_pre_minted_token_skips_acquire_token(self, kobo_source):
        """A pre-minted token bypasses the /token/ exchange. The form
        accepts it verbatim and stores it encrypted; acquired_by_
        username records the (pre-minted) lineage."""
        form = KoboCredentialForm(
            data={
                "server_url": KOBO_URL,
                "username": "", "password": "",
                "api_token": "preminted-abc123",
            },
            instance=KoboCredential(source_system=kobo_source),
        )
        assert form.is_valid(), form.errors
        cred = form.save()
        cred.refresh_from_db()
        assert bytes(cred.token_encrypted) == b"preminted-abc123"
        assert cred.acquired_by_username == "(pre-minted)"

    def test_pre_minted_token_strips_whitespace(self, kobo_source):
        """Copy-paste from the Kobo web UI often grabs trailing
        whitespace; strip() prevents a silent off-by-one bug at probe
        time."""
        form = KoboCredentialForm(
            data={
                "server_url": KOBO_URL,
                "api_token": "  preminted-xyz789\n",
            },
            instance=KoboCredential(source_system=kobo_source),
        )
        assert form.is_valid()
        cred = form.save()
        cred.refresh_from_db()
        assert bytes(cred.token_encrypted) == b"preminted-xyz789"

    def test_both_paths_at_once_rejects(self, kobo_source):
        """Providing username+password AND api_token is contradictory —
        the form must surface that rather than silently picking one."""
        form = KoboCredentialForm(
            data={
                "server_url": KOBO_URL,
                "username": "u", "password": "p",
                "api_token": "preminted-abc",
            },
            instance=KoboCredential(source_system=kobo_source),
        )
        assert not form.is_valid()
        assert "EITHER" in str(form.errors["__all__"])

    def test_first_save_rejects_when_no_auth_path_provided(self, kobo_source):
        """No username+password AND no token — still rejected on first
        save (regression for the original validation)."""
        form = KoboCredentialForm(
            data={"server_url": KOBO_URL},
            instance=KoboCredential(source_system=kobo_source),
        )
        assert not form.is_valid()
        assert "__all__" in form.errors


# --- US-S11-010 — list-forms + pull-submissions admin actions ----------


class TestKoboPullActions:
    """The two admin actions on SourceSystemAdmin: `list_kobo_forms_
    action` (read-only diagnostic) and `pull_kobo_submissions_action`
    (writes RawLanding rows). Both unit-tested by calling the action
    callable directly with a stubbed request — the Django admin
    plumbing is the same RequestFactory-style harness GRM S4-005 and
    UPD S5-001 use."""

    @pytest.fixture
    def kobo_with_dpa(self, kobo_source_with_creds):
        from datetime import date

        from apps.ingestion_hub.models import DataProvisionAgreement
        DataProvisionAgreement.objects.create(
            source_system=kobo_source_with_creds, reference="DPA-KOBO-TEST",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        )
        return kobo_source_with_creds

    def _request(self, user):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.http import HttpRequest
        req = HttpRequest()
        req.user = user
        req.session = {}
        req._messages = FallbackStorage(req)
        return req

    @pytest.fixture
    def staff_user(self, django_user_model):
        return django_user_model.objects.create_user(
            username="admin-bot", password="x", is_staff=True,
        )

    @responses.activate
    def test_list_forms_action_renders_form_count(
        self, kobo_with_dpa, staff_user,
    ):
        from apps.ingestion_hub.admin_credentials import list_kobo_forms_action
        from apps.ingestion_hub.models import SourceSystem
        responses.add(
            responses.GET, f"{KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "aF1", "name": "Pilot survey",
                 "asset_type": "survey", "deployment__active": True},
                {"uid": "aF2", "name": "Draft form",
                 "asset_type": "survey", "deployment__active": False},
            ]}, status=200,
        )
        qs = SourceSystem.objects.filter(pk=kobo_with_dpa.pk)
        req = self._request(staff_user)
        list_kobo_forms_action(None, req, qs)
        # Audit event emitted; messages stack carries the rendered list.
        from apps.security.models import AuditEvent
        ev = AuditEvent.objects.filter(action="list_forms").first()
        assert ev is not None and ev.reason == "2 assets visible"

    @responses.activate
    def test_pull_action_lands_raw_submissions(
        self, kobo_with_dpa, staff_user,
    ):
        from apps.ingestion_hub.admin_credentials import pull_kobo_submissions_action
        from apps.ingestion_hub.models import (
            ConnectorRun,
            ConnectorRunStatus,
            ConnectorRunType,
            RawLanding,
            SourceSystem,
        )
        # list_forms → one deployed form
        responses.add(
            responses.GET, f"{KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "FORM-A", "name": "Pilot", "asset_type": "survey",
                 "deployment__active": True},
            ]}, status=200,
        )
        # pull_submissions → 3 rows, no next page
        responses.add(
            responses.GET, f"{KOBO_URL}/api/v2/assets/FORM-A/data.json",
            json={"results": [
                {"_id": 1, "Q1": "a"},
                {"_id": 2, "Q1": "b"},
                {"_id": 3, "Q1": "c"},
            ], "next": None}, status=200,
        )
        qs = SourceSystem.objects.filter(pk=kobo_with_dpa.pk)
        req = self._request(staff_user)
        pull_kobo_submissions_action(None, req, qs)

        runs = ConnectorRun.objects.filter(
            connector__source_system=kobo_with_dpa,
            run_type=ConnectorRunType.IMPORT,
        )
        assert runs.count() == 1
        run = runs.first()
        assert run.status == ConnectorRunStatus.SUCCEEDED
        assert run.records_landed == 3
        # Raw rows visible in RawLanding admin.
        landings = RawLanding.objects.filter(connector_run=run)
        assert landings.count() == 3
        assert landings.first().payload["Q1"] in ("a", "b", "c")
        # source_reference picks up Kobo's _id for the per-row audit
        # lineage. Could be the int 1/2/3 if not coerced — confirm str.
        assert landings.first().source_reference in ("1", "2", "3")

    @responses.activate
    def test_pull_action_respects_cap(self, kobo_with_dpa, staff_user):
        """The PULL_BATCH_CAP keeps an admin request bounded even when
        Kobo returns thousands of historical submissions."""
        from apps.ingestion_hub.admin_credentials import (
            PULL_BATCH_CAP,
            pull_kobo_submissions_action,
        )
        from apps.ingestion_hub.models import RawLanding, SourceSystem
        responses.add(
            responses.GET, f"{KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "FORM-B", "name": "Big", "asset_type": "survey",
                 "deployment__active": True},
            ]}, status=200,
        )
        oversized = {
            "results": [{"_id": n, "v": n} for n in range(PULL_BATCH_CAP + 25)],
            "next": None,
        }
        responses.add(
            responses.GET, f"{KOBO_URL}/api/v2/assets/FORM-B/data.json",
            json=oversized, status=200,
        )
        qs = SourceSystem.objects.filter(pk=kobo_with_dpa.pk)
        req = self._request(staff_user)
        pull_kobo_submissions_action(None, req, qs)
        assert RawLanding.objects.count() == PULL_BATCH_CAP

    @responses.activate
    def test_pull_action_fails_run_on_upstream_error(
        self, kobo_with_dpa, staff_user,
    ):
        from apps.ingestion_hub.admin_credentials import pull_kobo_submissions_action
        from apps.ingestion_hub.models import (
            ConnectorRun,
            ConnectorRunStatus,
            SourceSystem,
        )
        responses.add(
            responses.GET, f"{KOBO_URL}/api/v2/assets.json",
            json={"results": [
                {"uid": "FORM-C", "name": "C", "asset_type": "survey",
                 "deployment__active": True},
            ]}, status=200,
        )
        # First page returns 500 three times (retry budget) — pull fails.
        for _ in range(3):
            responses.add(
                responses.GET, f"{KOBO_URL}/api/v2/assets/FORM-C/data.json",
                status=500,
            )
        qs = SourceSystem.objects.filter(pk=kobo_with_dpa.pk)
        req = self._request(staff_user)
        # `requests` retry sleep is monkeypatched by the autouse fixture.
        pull_kobo_submissions_action(None, req, qs)
        run = ConnectorRun.objects.filter(
            connector__source_system=kobo_with_dpa,
        ).order_by("-started_at").first()
        assert run.status == ConnectorRunStatus.FAILED
        assert "pull failed" in run.note


# --------------------------------------------------------------------
# Source-system form choices — "coming soon" suffix on NIRA/UBOS.
# --------------------------------------------------------------------

class TestSourceSystemForm:
    def test_kobo_choice_unchanged(self):
        from .admin_credentials import SourceSystemForm
        form = SourceSystemForm()
        labels = dict(form.fields["kind"].choices)
        assert labels[SourceSystemKind.KOBO] == "KoboToolbox"

    def test_ubos_and_partner_choices_marked_coming_soon(self):
        from .admin_credentials import SourceSystemForm
        form = SourceSystemForm()
        labels = dict(form.fields["kind"].choices)
        assert "(coming soon)" in labels[SourceSystemKind.UBOS]
        assert "(coming soon)" in labels[SourceSystemKind.PARTNER_MIS]
