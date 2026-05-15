"""Connection-test service for DIH source systems (US-S11-003b).

The Admin UI's 'Test connection' action fans out through here. The
service is connector-agnostic — it looks up the registered connector
for a SourceSystem, decrypts the credential row, calls
`connector.test_connection(creds)`, records a ConnectorRun row of
type TEST, and emits an AuditEvent.

NIRA + UBOS will land sibling credential models (NiraCredential,
UbosCredential) following the KoboCredential pattern. The dispatch
function gains an elif branch when each ships — see ADR-0007.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit as emit_audit

from .connectors.base import ConnectionTestResult, get_connector
from .models import (
    Connector as ConnectorModel,
)
from .models import (
    ConnectorRun,
    ConnectorRunStatus,
    ConnectorRunType,
    KoboCredential,
    SourceSystem,
    SourceSystemKind,
)

logger = logging.getLogger(__name__)


class CredentialMissingError(Exception):
    """No *Credential row exists for this SourceSystem yet."""


class UnsupportedConnectorError(Exception):
    """The SourceSystem's kind has no live test_connection implementation
    yet (NIRA and UBOS are 'coming soon' per the dropdown)."""


def credentials_for(source_system: SourceSystem) -> dict:
    """Decrypt the credential row that matches the SourceSystem's kind.
    The returned dict matches the shape each connector documents in
    its module docstring (Kobo: {server_url, token})."""
    if source_system.kind == SourceSystemKind.KOBO:
        try:
            cred = source_system.kobo_credential
        except KoboCredential.DoesNotExist as exc:
            raise CredentialMissingError(
                f"no Kobo credential for source {source_system.code}",
            ) from exc
        return {
            "server_url": cred.server_url,
            # EncryptedBinaryField returns decrypted bytes; the Kobo
            # connector expects str.
            "token": bytes(cred.token_encrypted).decode("utf-8"),
        }
    raise UnsupportedConnectorError(
        f"source kind {source_system.kind!r} has no credential model yet",
    )


def _connector_model_for(source_system: SourceSystem) -> ConnectorModel:
    """Return the SourceSystem's first Connector row, creating a
    placeholder if needed so the ConnectorRun FK is never null.
    Live import runs come through start_connector_run() in services.py
    which uses pre-seeded Connector rows; the Admin 'Test connection'
    button can fire before a Connector row exists, so we lazily
    materialise one with a "test-connection" name."""
    existing = source_system.connectors.first()
    if existing:
        return existing
    return ConnectorModel.objects.create(
        source_system=source_system,
        name="test-connection",
        config={"created_by": "admin test_connection action"},
    )


@transaction.atomic
def run_test_connection(
    source_system: SourceSystem, *, actor: str,
) -> tuple[ConnectorRun, ConnectionTestResult]:
    """Probe the upstream and record the attempt.

    Always returns a (run, result) pair, even on failure — the caller
    (admin action) renders both. Raises only on misconfiguration
    (no credential row, no connector registered).
    """
    connector_impl = get_connector(source_system.code)
    if connector_impl is None or connector_impl.test_connection is None:
        raise UnsupportedConnectorError(
            f"no live connector registered for code {source_system.code!r}",
        )

    creds = credentials_for(source_system)
    connector_row = _connector_model_for(source_system)

    run = ConnectorRun.objects.create(
        connector=connector_row,
        run_type=ConnectorRunType.TEST,
        status=ConnectorRunStatus.RUNNING,
    )
    emit_audit(
        "create", "connector_run", run.id, actor=actor,
        actor_kind="user",
        field_changes={"connector_id": connector_row.id, "run_type": "test"},
    )

    result = connector_impl.test_connection(creds)
    run.finished_at = timezone.now()
    run.status = (
        ConnectorRunStatus.SUCCEEDED if result.ok else ConnectorRunStatus.FAILED
    )
    # Notes are operator-visible in the ConnectorRun admin list, so put
    # a one-liner there too — error message on failure, latency + version
    # on success.
    run.note = (
        f"ok latency={result.latency_ms}ms version={result.server_version or '-'}"
        if result.ok
        else f"failed: {result.error}"
    )
    run.save(update_fields=("finished_at", "status", "note"))

    # Bookkeep the freshness signal on KoboCredential so the admin
    # list_display can show "last tested" without a JOIN to runs.
    if source_system.kind == SourceSystemKind.KOBO:
        # Updating through the related row; same transaction.
        source_system.kobo_credential.last_test_at = run.finished_at
        source_system.kobo_credential.last_test_ok = result.ok
        source_system.kobo_credential.save(
            update_fields=("last_test_at", "last_test_ok"),
        )

    emit_audit(
        "test_connection", "source_system", source_system.id, actor=actor,
        actor_kind="user",
        reason=("ok" if result.ok else (result.error or "failed")),
        field_changes={
            "run_id": run.id,
            "latency_ms": result.latency_ms,
            "ok": result.ok,
        },
    )
    return run, result
