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
        assert "required on first save" in str(form.errors["__all__"])

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
