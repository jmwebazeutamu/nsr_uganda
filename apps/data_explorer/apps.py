"""DATA-EXP AppConfig.

Two ready()-time side-effects per ADR-0023 D5:

1. Connect the `post_migrate` signal so the metadata loader runs again
   whenever data_management, reference_data, or update_workflow apply
   migrations. Variables whose underlying field shape changes flip
   INACTIVE automatically — dual approval re-activates them.

2. Call `metadata_loader.refresh()` once at startup so the catalogue
   is fresh when the first request lands. Wrapped in a guard that
   tolerates the unmigrated-DB case (the loader is a no-op when the
   underlying tables don't exist yet).
"""

from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class DataExplorerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.data_explorer"
    label = "data_explorer"
    verbose_name = "Data Explorer (DATA-EXP)"

    def ready(self) -> None:
        # Side-effect imports — signal handlers register at import time.
        # post_migrate is the primary refresh trigger.
        # ADR-0023 OPEN-4 default: startup + signal. The startup pass
        # is best-effort — the loader is idempotent and tolerates the
        # unmigrated-DB case (table-not-present → silent skip). Django
        # emits a RuntimeWarning when DB queries fire from ready();
        # the loader's "tables exist?" check is the cheapest possible
        # query and the warning is acceptable per the ADR.
        import os

        from . import signals  # noqa: F401
        if os.environ.get("DATA_EXPLORER_SKIP_STARTUP_REFRESH") == "1":
            return
        try:
            from . import metadata_loader
            metadata_loader.refresh(quiet=True)
        except Exception as exc:  # noqa: BLE001 — startup must not crash
            logger.warning("data_explorer metadata_loader skipped: %s", exc)
