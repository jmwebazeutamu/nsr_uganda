"""DIH connector framework — shared base + registry.

The four existing connectors (pdm, nusaf, wfp_scope, nira_vital) all
follow the same shape:

    canonicalize(raw: dict) -> dict   # pure, raises KeyError/ValueError
    process(raw: dict, *, actor: str) -> Any   # optional; side-effects

This module gives them a single Protocol + a module-level registry
indexed by source-system code. The registry lets a future REST
surface (e.g., a generic POST /api/v1/dih/connectors/{code}/push/
endpoint) resolve the right connector without per-connector
URL routing.

NO behaviour change for the existing connectors — this is the
extraction layer. Each connector module ends with a register_connector
call (see pdm.py etc.).
"""

from __future__ import annotations

from typing import Any, Protocol


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
