"""DIH connector framework — shared base + registry.

The four canonicalisation-only connectors (pdm, nusaf, wfp_scope,
nira_vital) all follow the simple shape:

    canonicalize(raw: dict) -> dict   # pure, raises KeyError/ValueError
    process(raw: dict, *, actor: str) -> Any   # optional; side-effects

US-S11-003a extends the Protocol with three more optional methods
for connectors that actively pull from an upstream API:

    test_connection(credentials) -> ConnectionTestResult
    list_forms(credentials) -> list[dict]
    pull_submissions(credentials, *, form_id, since) -> Iterator[dict]

The original four leave these unset (None); Kobo and the future
NIRA / UBOS HTTP connectors populate them. One registry, one
lookup, one OpenAPI enum — option A from the design discussion.

`credentials` is a connector-specific dict the caller has already
decrypted from the relevant `*Credential` row. The Protocol stays
agnostic about credential SHAPE — each implementation documents
its expected keys (see kobo.KoboConnector below).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ConnectionTestResult:
    """Shape returned by every `test_connection()` implementation.
    The Admin UI's 'Test connection' button renders this directly.

    `latency_ms` is the wall-clock for the whole round-trip including
    any retries, so a successful test after one retry will show the
    cumulative time — operationally useful for spotting flaky links.
    `server_version` is best-effort; some upstream APIs don't expose
    it, in which case it stays None.
    """

    ok: bool
    latency_ms: int
    server_version: str | None = None
    error: str | None = None


class Connector(Protocol):
    """Verb-shaped contract every DIH connector implementation
    honours. canonicalize is mandatory; process is optional and may
    be None for connectors that only normalise (the run side-effect
    is then handled by the generic DIH pipeline)."""

    code: str

    def canonicalize(self, raw: dict) -> dict:
        """Pure: raw payload -> canonical NSR shape. Raises KeyError
        or ValueError for malformed input (quarantine path)."""

    def process(self, raw: dict, *, actor: str) -> Any:
        """Optional: side-effecting driver that runs canonicalize then
        whatever the connector needs (e.g., NIRA reverse-feed routes
        through UPD auto-commit). Connectors that don't override this
        leave it None; the generic DIH run path picks them up."""

    def test_connection(self, credentials: dict) -> ConnectionTestResult:
        """Optional: cheap end-to-end check against the upstream API.
        Used by the Admin UI's 'Test connection' action before saving
        a SourceSystem. Must NOT mutate state on the connector side
        beyond what an authenticated GET would already do (e.g.,
        recording a session token is OK, creating forms is not).
        Connectors that don't reach an external service (the
        canonicalisation-only ones) leave this as None."""

    def list_forms(self, credentials: dict) -> list[dict]:
        """Optional: enumerate forms/datasets the upstream exposes.
        Used by the schedule-builder so an admin can pick which
        forms to pull from. None for connectors that don't have a
        notion of forms."""

    def pull_submissions(
        self, credentials: dict, *, form_id: str, since: str | None = None,
    ) -> Iterator[dict]:
        """Optional: yield raw submission payloads since the given
        watermark (or all, if since is None). Returns an iterator so
        large pulls don't have to load into memory. None for
        connectors that don't pull (push-based or canonicalise-only)."""


# Module-level registry — code -> connector instance. Populated by
# each connector module at import time via register_connector(...).
# The connectors package's __init__.py imports each module so the
# side-effects fire when apps.ingestion_hub is loaded.
CONNECTOR_REGISTRY: dict[str, Connector] = {}


def register_connector(connector: Connector) -> None:
    """Add a connector to the registry. Idempotent — re-registering
    the same code is a no-op (the connector module's import is
    idempotent, so registry stays clean even after `manage.py
    test`-style re-imports)."""
    code = connector.code
    if code in CONNECTOR_REGISTRY:
        return
    CONNECTOR_REGISTRY[code] = connector


def get_connector(code: str) -> Connector | None:
    """Lookup the connector for `code`, or None if unregistered."""
    return CONNECTOR_REGISTRY.get(code)


def registered_codes() -> list[str]:
    """All registered connector codes, sorted. Useful for OpenAPI
    enum generation and ops `manage.py shell` introspection."""
    return sorted(CONNECTOR_REGISTRY)
