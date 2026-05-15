"""DIH connector package.

Importing this package triggers the side-effect of each connector
module's register_connector() call, populating CONNECTOR_REGISTRY.
That lets `from apps.ingestion_hub.connectors.base import get_connector`
work from anywhere without per-call import dance.
"""

from . import kobo, nira_vital, nusaf, pdm, wfp_scope  # noqa: F401
from .base import (  # noqa: F401
    CONNECTOR_REGISTRY,
    ConnectionTestResult,
    Connector,
    get_connector,
    register_connector,
    registered_codes,
)
