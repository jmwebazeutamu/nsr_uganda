from django.apps import AppConfig


class PmtConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pmt"
    label = "pmt"
    verbose_name = "Proxy Means Test (PMT)"

    def ready(self) -> None:
        # Wire the UPD post-commit recompute hook.
        # Import-side effect: every @register decoration in
        # registered_features.py runs, populating apps.pmt.registry.
        # Import the system-check module so its @register hooks fire.
        from . import (
            checks,  # noqa: F401
            registered_features,  # noqa: F401
            signals,  # noqa: F401
        )
