"""Signal handlers — keep the catalogue in sync with model migrations.

ADR-0023 D5 + R3: every time data_management / reference_data /
update_workflow runs migrations, the catalogue loader re-runs.
Variables whose underlying field shape has changed flip INACTIVE; new
variables seed INACTIVE; everything else is stable.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_migrate
from django.dispatch import receiver

logger = logging.getLogger(__name__)

# App labels whose migrations should trigger a catalogue refresh.
_WATCH_APPS = {"data_management", "reference_data", "update_workflow",
               "data_explorer"}


@receiver(post_migrate)
def _refresh_after_migrate(sender, app_config, **kwargs):
    if app_config.label not in _WATCH_APPS:
        return
    try:
        from . import metadata_loader
        result = metadata_loader.refresh(quiet=True)
        logger.info(
            "data_explorer.metadata_loader refreshed after %s migrate: %s",
            app_config.label, result,
        )
        # Bust the catalogue cache so the next read repopulates.
        from . import catalogue
        catalogue.invalidate()
    except Exception as exc:  # noqa: BLE001 — never block migrate
        logger.warning(
            "data_explorer.metadata_loader refresh skipped after %s "
            "migrate: %s", app_config.label, exc,
        )
